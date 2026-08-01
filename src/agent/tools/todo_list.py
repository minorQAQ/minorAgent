from __future__ import annotations

import json
import threading
from contextvars import ContextVar
from typing import Any, Optional, Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, model_validator


# ---------- 当前 agent 上下文（用于 TodoList 按 agent 隔离）----------
# 主 Agent 使用保留键 "__main__"；子 Agent 使用其 agent_name。
# ContextVar + 全局 fallback 双轨：主线程/线程池子进程均可读到正确值；
# HTTP 请求线程（前端轮询）无上下文 → fallback 默认 "__main__" → 只见主 Agent。
_current_agent_name: ContextVar[str] = ContextVar("current_agent_name", default="")
_agent_name_fallback_lock = threading.Lock()
_current_agent_name_fallback = "__main__"


def set_current_agent_name(agent_name: str) -> None:
    """设置当前线程的 agent 名称（主 Agent 传 "__main__"，子 Agent 传其名称）。"""
    global _current_agent_name_fallback
    _current_agent_name.set(agent_name or "")
    with _agent_name_fallback_lock:
        _current_agent_name_fallback = agent_name or "__main__"


def get_current_agent_name() -> str:
    """获取当前 agent 名称；ContextVar 为空时回退到全局 fallback（默认 "__main__"）。"""
    name = _current_agent_name.get()
    if name:
        return name
    with _agent_name_fallback_lock:
        return _current_agent_name_fallback or "__main__"


# ---------- Todo List 实时推送共享存储 ----------
# TodoList 工具本身和 web server 共享此 dict，无需跨模块 import server
# 二级键：外层 session_id，内层 agent_name（主 Agent 用 "__main__"）
_todo_store: dict[str, dict[str, dict]] = {}


def _resolve_agent(agent_name: str | None) -> str:
    return agent_name or get_current_agent_name() or "__main__"


def get_todo_store_data(session_id: str, agent_name: str | None = None) -> dict | None:
    """读取指定 session + agent 的 todo。

    前端轮询时不传 agent_name → 走 get_current_agent_name() → HTTP 线程回退到 "__main__"，
    因此前端只见主 Agent 的 todo；子 Agent 的 todo 隔离在内层键中不暴露。
    """
    if not session_id:
        return None
    ag = _resolve_agent(agent_name)
    return (_todo_store.get(session_id) or {}).get(ag)


def update_todo_store_session(
    session_id: str,
    steps: list[str] | None = None,
    done_step: int = -1,
    agent_name: str | None = None,
) -> dict | None:
    if not session_id:
        return None
    ag = _resolve_agent(agent_name)
    sess = _todo_store.setdefault(session_id, {})
    current = sess.get(ag) or {"steps": [], "done_steps": []}
    stored_steps = list(current.get("steps") or [])
    done_steps = list(current.get("done_steps") or [])

    if steps:
        stored_steps = list(steps)
        done_steps = []

    if stored_steps and 1 <= done_step <= len(stored_steps):
        for i in range(done_step):
            if i not in done_steps:
                done_steps.append(i)
        done_steps.sort()

    todo_data = {"steps": stored_steps, "done_steps": done_steps}
    sess[ag] = todo_data
    return todo_data


def update_todo_store_from_tool_args(session_id: str, tool_args: dict[str, Any], agent_name: str | None = None) -> dict | None:
    raw_steps = tool_args.get("steps") if isinstance(tool_args, dict) else None
    if isinstance(raw_steps, str):
        try:
            raw_steps = json.loads(raw_steps)
        except (json.JSONDecodeError, ValueError):
            raw_steps = None
    steps = raw_steps if isinstance(raw_steps, list) else None

    done_step = tool_args.get("done_step", -1) if isinstance(tool_args, dict) else -1
    try:
        done_step = int(done_step)
    except (TypeError, ValueError):
        done_step = -1

    return update_todo_store_session(session_id, steps, done_step, agent_name=agent_name)


def set_todo_store_data(session_id: str, todo_data: dict, agent_name: str | None = None) -> None:
    if not session_id:
        return
    ag = _resolve_agent(agent_name)
    sess = _todo_store.setdefault(session_id, {})
    sess[ag] = {
        "steps": list(todo_data.get("steps") or []),
        "done_steps": list(todo_data.get("done_steps") or []),
    }


def clear_todo_store_session(session_id: str) -> None:
    """清除指定 session 下所有 agent 的 todo（主 + 各子 Agent）。"""
    _todo_store.pop(session_id, None)


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
    """

    args_schema: type[BaseModel] = TodoListInput
    name: str = "todo_list"
    description: str = (
        "任务管理工具。用于将复杂任务拆分为多个步骤并跟踪执行进度。\n"
        "Plan 模式下必须首先调用此工具创建任务计划；Agent 模式下按需调用。\n"
        "参数说明：\n"
        "- steps (list[str], 可选)：任务步骤列表。仅在首次创建计划时传入所有步骤。\n"
        "  **步骤粒度要求**：同一页面/界面上的连续操作应合并为一条步骤，用\"并\"连接。例如：\n"
        '  * 推荐：\"点击搜索框，输入XXX并点击搜索\"（合并了点击、输入、搜索）\n'
        '  * 推荐：\"在结果中点击目标进入主页\"（合并了查找+点击）\n'
        '  * 禁止：\"1.点击搜索框 2.输入文字 3.点击搜索\"（过于细碎）\n'
        "- done_step (int, 可选)：当前已推进到的步骤编号（从1开始）。传入 n 则步骤 1~n 全部标记为已完成。不传或传 -1 则只查看当前状态。\n"
        "调用示例：\n"
        '- 首次创建（B站搜索示例）：{\"steps\": [\"打开哔哩哔哩网站\", \"点击顶部搜索框，输入\'燕三嘤嘤嘤\'并点击搜索\", \"在搜索结果中找到燕三嘤嘤嘤并点击头像或名称进入他的主页\", \"在他的主页点开视频列表里的第一个视频\", \"验证视频是否正在播放\"], \"done_step\": -1}\n'
        '- 已完成前2步：{\"done_step\": 2}  （步骤1和2均标记为完成）\n'
        '- 已完成前4步：{\"done_step\": 4}\n'
        '- 查看状态：{\"done_step\": -1}\n'
        "任务全部完成后无需再次调用。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content"

    def _run(self, steps: list[str] | None = None, done_step: int = -1) -> str:
        try:
            steps = steps or []

            # 从全局 store 读取当前会话 + 当前 agent 的状态（由 runtime 层在调用前设置 session/agent）
            from agent.history.tool_call_recorder import get_current_session
            sid = get_current_session() or ""
            current = get_todo_store_data(sid) or {"steps": [], "done_steps": []}
            stored_steps = list(current.get("steps") or [])
            done_steps = list(current.get("done_steps") or [])

            # 如果传入了新的 steps，更新存储
            if steps:
                stored_steps = steps
                done_steps = []

            # 标记步骤完成
            if stored_steps and 1 <= done_step <= len(stored_steps):
                for i in range(done_step):
                    if i not in done_steps:
                        done_steps.append(i)
                done_steps.sort()

            todo_data = {"steps": stored_steps, "done_steps": done_steps}

            # 实时推送到前端 todo 浮窗
            if sid:
                set_todo_store_data(sid, todo_data)

            if not stored_steps:
                return json.dumps({"__todo_list__": True, "data": todo_data}, ensure_ascii=False) + "\n[Todo List]\n(当前无任务)"

            lines = ["[Todo List]"]
            for i, s in enumerate(stored_steps):
                status = "[Done]" if i in done_steps else "[Pending]"
                lines.append(f"- [{i+1}/{len(stored_steps)}] {status}: {s}")
            return json.dumps({"__todo_list__": True, "data": todo_data}, ensure_ascii=False) + "\n" + "\n".join(lines)
        except Exception as e:
            return f"[ERROR] todo_list 工具执行出错: {str(e)}"

    async def _arun(self, steps: list[str] | None = None, done_step: int = -1) -> str:
        return self._run(steps, done_step)
