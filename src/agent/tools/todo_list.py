from __future__ import annotations

import json
from typing import Any, Literal, Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, model_validator


def _iter_todo_records(records: list[dict[str, Any]] | None):
    """遍历 live 工具记录中的 todo_list 调用（含子 Agent 嵌套在 call_subagent 内的记录）。"""
    for rec in records or []:
        if rec.get("name") == "todo_list":
            yield rec
        for sub in rec.get("sub_tool_calls") or []:
            if sub.get("name") == "todo_list":
                yield sub


def _reconstruct_state(sid: str, steps_arg: Optional[list[str]], done_step_arg: int) -> tuple[list[str], set[int]]:
    """从当前轮的 live 工具记录重建累计 todo 状态。

    steps 取自最近一次传入完整步骤列表的调用；done_steps 累积全部 done_step。
    本工具是纯函数、不维护任何全局 store——每次调用都从框架的 live 记录通道
    读取自身调用历史，前端浮窗亦由同一通道（工具调用的 args）驱动更新。
    """
    steps: list[str] = []
    done_steps: set[int] = set()
    if sid:
        try:
            from agent.history.tool_call_recorder import get_live_tool_calls
            for rec in _iter_todo_records(get_live_tool_calls(sid)):
                args = rec.get("args") or {}
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
        except Exception:
            pass
    # 本次调用的参数覆盖/追加（live 记录不可用时的兜底）
    if steps_arg:
        steps = [str(s) for s in steps_arg]
        done_steps = set()
    if steps and done_step_arg >= 1:
        done_steps.update(range(min(done_step_arg, len(steps))))
    return steps, done_steps


class TodoListInput(BaseModel):
    steps: Optional[list[str]] = Field(
        default=None,
        description="任务步骤列表，每项为一步的描述。仅在首次创建计划时传入，后续更新进度时请省略此参数以节省 token。",
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
    首次调用时传入完整步骤列表，后续仅传 done_step 标记进度。

    调用时会随 live 工具记录推送状态，前端据此实时渲染 Todo 浮窗；
    返回值是纯文本，不携带任何结构化前缀。
    """

    args_schema: type[BaseModel] = TodoListInput
    name: str = "todo_list"
    description: str = (
        "任务管理工具。用于将复杂任务拆分为多个步骤并跟踪执行进度。\n"
        "Plan 模式下必须首先调用此工具创建任务计划；Agent 模式下按需调用。\n"
        "参数说明：\n"
        "- steps (list[str], 可选)：任务步骤列表。仅在首次创建计划时传入所有步骤。\n"
        "  **步骤粒度要求**：同一页面/界面上的连续操作应合并为一条步骤，用\"并\"连接。例如：\n"
        '  * 推荐："点击搜索框，输入XXX并点击搜索"（合并了点击、输入、搜索）\n'
        '  * 推荐："在结果中点击目标进入主页"（合并了查找+点击）\n'
        '  * 禁止："1.点击搜索框 2.输入文字 3.点击搜索"（过于细碎）\n'
        "- done_step (int, 可选)：当前已推进到的步骤编号（从1开始）。传入 n 则步骤 1~n 全部标记为已完成。不传或传 -1 则只查看当前状态。\n"
        "调用示例：\n"
        '- 首次创建（B站搜索示例）：{"steps": ["打开哔哩哔哩网站", "点击顶部搜索框，输入\'燕三嘤嘤嘤\'并点击搜索", "在搜索结果中找到燕三嘤嘤嘤并点击头像或名称进入他的主页", "在他的主页点开视频列表里的第一个视频", "验证视频是否正在播放"], "done_step": -1}\n'
        '- 已完成前2步：{"done_step": 2}  （步骤1和2均标记为完成）\n'
        '- 已完成前4步：{"done_step": 4}\n'
        '- 查看状态：{"done_step": -1}\n'
        "任务全部完成后无需再次调用。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content"

    def _run(self, steps: list[str] | None = None, done_step: int = -1) -> str:
        try:
            steps = steps or []
            sid = ""
            try:
                from agent.history.tool_call_recorder import get_current_session
                sid = get_current_session() or ""
            except Exception:
                pass
            stored_steps, done_steps = _reconstruct_state(sid, steps, done_step)
            if not stored_steps:
                return "[Todo List]\n(当前无任务)"
            lines = ["[Todo List]"]
            for i, s in enumerate(stored_steps):
                status = "[Done]" if i in done_steps else "[Pending]"
                lines.append(f"- [{i+1}/{len(stored_steps)}] {status}: {s}")
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] todo_list 工具执行出错: {str(e)}"

    async def _arun(self, steps: list[str] | None = None, done_step: int = -1) -> str:
        return self._run(steps, done_step)
