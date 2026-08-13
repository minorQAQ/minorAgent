from __future__ import annotations

import json
from typing import Any, Literal, Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, model_validator


def _iter_todo_args(records: list[dict[str, Any]] | None):
    """遍历工具调用记录中的 todo_list 调用参数（含子 Agent 嵌套在 call_subagent 内的记录）。"""
    for rec in records or []:
        if rec.get("name") == "todo_list":
            yield rec.get("args") or {}
        for sub in rec.get("sub_tool_calls") or []:
            if sub.get("name") == "todo_list":
                yield sub.get("args") or {}


def _accumulate_todo_args(args_list: list[dict[str, Any]]) -> tuple[list[str], set[int]]:
    """按时间顺序累积 todo_list 调用参数 → (steps, done_steps)。

    steps 取自最近一次传入完整步骤列表的调用（重新传入即修改/重建计划）；
    done_steps 累积全部 done_step。
    """
    steps: list[str] = []
    done_steps: set[int] = set()
    for args in args_list:
        raw_steps = args.get("steps")
        if isinstance(raw_steps, str):
            try:
                raw_steps = json.loads(raw_steps)
            except (json.JSONDecodeError, ValueError):
                raw_steps = None
        if isinstance(raw_steps, list) and raw_steps:
            steps = [str(s) for s in raw_steps]
            done_steps = set()
        try:
            n = int(args.get("done_step", -1))
        except (TypeError, ValueError):
            n = -1
        if steps and n >= 1:
            done_steps.update(range(min(n, len(steps))))
    return steps, done_steps


def _collect_todo_args(sid: str) -> list[dict[str, Any]]:
    """按时间顺序收集 todo_list 调用参数：已落盘 turn（正序）+ 当前 live 记录。

    live 记录仅在 turn 执行期间存在（turn 结束后被清空），因此跨轮状态
    需从已落盘 turn 的工具调用记录重建。
    """
    args_list: list[dict[str, Any]] = []
    if not sid:
        return args_list
    try:
        from agent.history.tool_call_recorder import list_turns
        turns = list_turns(sid, limit=100000)  # 倒序（最新在前）
        for t in reversed(turns):  # 转为正序
            args_list.extend(_iter_todo_args(t.get("tool_calls") or []))
    except Exception:
        pass
    try:
        from agent.history.tool_call_recorder import get_live_tool_calls
        args_list.extend(_iter_todo_args(get_live_tool_calls(sid)))
    except Exception:
        pass
    return args_list


def _reconstruct_state(sid: str, steps_arg: Optional[list[str]], done_step_arg: int) -> tuple[list[str], set[int]]:
    """从已落盘 turn + 当前 live 记录重建累计 todo 状态，并应用本次调用参数。

    本工具是纯函数、不维护任何全局 store——每次调用都从框架的记录通道
    读取自身调用历史，前端浮窗亦由同一通道（工具调用的 args）驱动更新。
    """
    steps, done_steps = _accumulate_todo_args(_collect_todo_args(sid))
    # 本次调用的参数覆盖/追加
    if steps_arg:
        steps = [str(s) for s in steps_arg]
        done_steps = set()
    if steps and done_step_arg >= 1:
        done_steps.update(range(min(done_step_arg, len(steps))))
    return steps, done_steps


def get_todo_status_text(session_id: str) -> str:
    """构建当前会话的 TodoList 状态文本（供每轮注入到模型上下文）。

    从已落盘 turn + 当前 live 记录重建累计状态，输出形如：
        当前TodoList进度：2/5 已完成
          1. [已完成] 打开哔哩哔哩网站
          2. [待完成] 点击顶部搜索框，输入"燕三嘤嘤嘤"并点击搜索
    无计划时返回空字符串。
    """
    if not session_id:
        return ""
    steps, done_steps = _accumulate_todo_args(_collect_todo_args(session_id))
    if not steps:
        return ""
    total = len(steps)
    done_count = len(done_steps)
    lines = [f"当前TodoList进度：{done_count}/{total} 已完成"]
    for i, s in enumerate(steps):
        status = "[已完成]" if i in done_steps else "[待完成]"
        lines.append(f"  {i + 1}. {status} {s}")
    return "\n".join(lines)


class TodoListInput(BaseModel):
    steps: Optional[list[str]] = Field(
        default=None,
        description="任务步骤列表，每项为一步的描述。仅在首次创建计划或需要修改/重建计划时传入，后续更新进度时请省略此参数以节省 token。",
    )
    done_step: int = Field(
        default=-1,
        description="当前已推进到的步骤编号（从1开始）。传入 n 则步骤 1~n 全部标记为完成。-1 表示仅查看当前状态。",
    )

    @model_validator(mode="before")
    @classmethod
    def parse_steps_string(cls, data: Any) -> Any:
        """容错：如果 steps 以 JSON 字符串形式传入（某些 LLM 的 function calling 行为），自动解析为列表。"""
        if isinstance(data, dict) and isinstance(data.get("steps"), str):
            raw = data["steps"].strip()
            if raw.startswith("["):
                try:
                    data["steps"] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    pass
        return data


class TodoList(BaseTool):
    """任务管理工具，用于拆分复杂任务为多个步骤并跟踪进度。

    Plan 模式下此工具为**必须调用**，Agent 模式下为可选。
    首次调用时传入完整步骤列表，后续仅传 done_step 标记进度；重新传入
    steps 可修改或重建计划。

    调用时会随 live 工具记录推送状态，前端据此实时渲染 Todo 浮窗；
    返回值只包含创建/更新结果（成功或失败+原因），**不返回完整步骤列表**
    ——当前计划状态由系统每轮注入模型上下文（get_todo_status_text）。
    """

    args_schema: type[BaseModel] = TodoListInput
    name: str = "todo_list"
    description: str = (
        "任务管理工具。用于将复杂任务拆分为多个步骤并跟踪执行进度。\n"
        "Plan 模式下必须首先调用此工具创建任务计划；Agent 模式下按需调用。\n"
        "参数说明：\n"
        "- steps (list[str], 可选)：任务步骤列表。仅在首次创建计划或需要修改/重建计划时传入所有步骤。\n"
        "  **步骤粒度要求**：同一页面/界面上的连续操作应合并为一条步骤，用\"并\"连接。例如：\n"
        '  * 推荐："点击搜索框，输入XXX并点击搜索"（合并了点击、输入、搜索）\n'
        '  * 推荐："在结果中点击目标进入主页"（合并了查找+点击）\n'
        '  * 禁止："1.点击搜索框 2.输入文字 3.点击搜索"（过于细碎）\n'
        "- done_step (int, 可选)：当前已推进到的步骤编号（从1开始）。传入 n 则步骤 1~n 全部标记为已完成。不传或传 -1 则只查看当前状态。\n"
        "调用示例：\n"
        '- 首次创建（B站搜索示例）：{"steps": ["打开哔哩哔哩网站", "点击顶部搜索框，输入\'燕三嘤嘤嘤\'并点击搜索", "在搜索结果中找到燕三嘤嘤嘤并点击头像或名称进入他的主页", "在他的主页点开视频列表里的第一个视频", "验证视频是否正在播放"], "done_step": -1}\n'
        '- 修改/重建计划：重新传入 {"steps": [...]}\n'
        '- 已完成前2步：{"done_step": 2}  （步骤1和2均标记为完成）\n'
        '- 已完成前4步：{"done_step": 4}\n'
        '- 查看状态：{"done_step": -1}\n'
        "任务全部完成后无需再次调用。\n"
        "返回值说明：创建成功（共 N 步）/ 更新成功（已完成 X/N 步）或失败原因，不包含完整步骤列表；当前计划状态由系统每轮注入。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content"

    def _run(self, steps: list[str] | None = None, done_step: int = -1) -> str:
        try:
            sid = ""
            try:
                from agent.history.tool_call_recorder import get_current_session
                sid = get_current_session() or ""
            except Exception:
                pass
            stored_steps, done_steps = _reconstruct_state(sid, steps, done_step)

            # 创建 / 修改 / 重建计划
            if steps is not None:
                if not steps:
                    return "TodoList 创建失败：steps 不能为空列表。"
                msg = f"TodoList 创建成功，共 {len(stored_steps)} 步。"
                if done_step >= 1:
                    msg += f" 已完成 {len(done_steps)} 步。"
                return msg

            # 更新进度
            if done_step >= 1:
                if not stored_steps:
                    return "TodoList 更新失败：当前没有已创建的 TodoList，请先传入 steps 创建计划。"
                if done_step > len(stored_steps):
                    return f"TodoList 更新失败：done_step={done_step} 超过总步数 {len(stored_steps)}。"
                return f"TodoList 进度更新成功：已完成 {len(done_steps)}/{len(stored_steps)} 步。"

            # 仅查看状态
            if not stored_steps:
                return "当前无 TodoList。"
            return f"当前进度：已完成 {len(done_steps)}/{len(stored_steps)} 步。"
        except Exception as e:
            return f"TodoList 更新失败：{str(e)}"

    async def _arun(self, steps: list[str] | None = None, done_step: int = -1) -> str:
        return self._run(steps, done_step)
