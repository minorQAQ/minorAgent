"""轮次执行器：后台线程驱动 execute_agent，解耦 HTTP 请求与图执行生命周期。

系统定位:
    Web 层将每次对话轮次放入后台线程执行，HTTP 请求通过 ``start_turn`` /
    ``wait_turn`` 挂载到同一轮次。断连/关标签页不影响执行——轮次照常跑完并
    落盘，重连后可见；同一会话的重复请求共享同一轮，避免并发竞态。

    轮次内的人工交互由 ``human_request.ask_human`` 在图上线程中阻塞等待，
    前端通过 live snapshot 渲染浮窗，答案由 ``POST /api/human-action`` 应答。

可扩展性:
    可增加轮次超时、自动清理、多 runtime 支持。
"""
from __future__ import annotations

import threading
from typing import Any

_turns: dict[str, dict[str, Any]] = {}
_turns_lock = threading.Lock()


def start_turn(session_id: str, chat_history: list[dict[str, Any]], agent_mode: str = "agent") -> str:
    """为会话启动（或复用）一轮后台执行。

    输入:
        session_id: 会话 ID。
        chat_history: 以末条 user 结尾的聊天历史（与 execute_agent 入参一致）。
        agent_mode: agent | plan。

    输出:
        "running" | "done"——该会话是否已有轮次在运行。
    """
    with _turns_lock:
        existing = _turns.get(session_id)
        if existing and not existing["done"].is_set():
            return "running"

        handle: dict[str, Any] = {
            "session_id": session_id,
            "done": threading.Event(),
            "result": None,
        }
        _turns[session_id] = handle

    def _worker():
        try:
            from agent.agents.agent_runtime import execute_agent
            new_hist = execute_agent(list(chat_history), session_id=session_id, agent_mode=agent_mode)
            handle["result"] = {"chat_history": new_hist}
        except Exception as e:
            import traceback
            traceback.print_exc()
            handle["result"] = {"error": str(e)}
        finally:
            handle["done"].set()

    thread = threading.Thread(target=_worker, name=f"turn-{session_id}", daemon=True)
    handle["thread"] = thread
    thread.start()
    return "running"


def wait_turn(session_id: str, timeout: float | None = None) -> dict[str, Any] | None:
    """等待轮次结束并返回 execute_agent 的结果 dict。

    输出:
        {"chat_history": list} | {"error": str}；无运行轮次或等待超时返回 None。
        timeout=None 表示无限等待（人工交互可能持续较长时间）。
    """
    with _turns_lock:
        handle = _turns.get(session_id)
    if not handle:
        return None
    if not handle["done"].wait(timeout=timeout):
        return None
    return handle["result"]


def get_turn_status(session_id: str) -> str:
    """查询会话当前是否有轮次在运行。"""
    with _turns_lock:
        handle = _turns.get(session_id)
        return "running" if handle and not handle["done"].is_set() else "done"


def drop_turn(session_id: str) -> None:
    """丢弃会话的轮次句柄（会话删除时调用；运行中的轮次不受影响，由 abort 负责终止）。"""
    with _turns_lock:
        _turns.pop(session_id, None)
