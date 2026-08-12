"""人工请求注册表：交互类工具与确认钳点的通用阻塞通道。

系统定位:
    交互类工具的通用框架服务。工具只需调用 ``ask_human`` 阻塞等待答案并自行
    格式化返回值；等待期间请求会随 live snapshot 推送到前端渲染浮窗，
    用户通过 ``POST /api/human-action`` 回答后阻塞解除、图自然继续——
    同意/拒绝/补充信息都只是普通工具返回值，拒绝不会结束整轮任务。

    无人值守（AGENT_HEADLESS，如 cron）时 ``ask_human`` 立即返回默认答案，
    避免任务悬死；用户暂停（abort）时阻塞解除并抛 ``ABORTED_BY_USER``，
    由 runtime 统一按暂停处理。

可扩展性:
    新交互类工具 = 工具内调一次 ``ask_human(meta)``，框架零改动。
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from contextvars import ContextVar
from typing import Any

# ---------- 当前 agent 名称（用于前端浮窗按 agent 分组） ----------
# 主 Agent 使用保留键 "__main__"；子 Agent 使用其 agent_name。
# ContextVar + 全局 fallback 双轨：主线程/线程池子进程均可读到正确值；
# HTTP 请求线程（前端轮询）无上下文 → fallback 默认 "__main__"。
_current_agent_name: ContextVar[str] = ContextVar("current_agent_name", default="")
_agent_name_fallback_lock = threading.Lock()
_agent_name_fallback = "__main__"


def set_current_agent_name(agent_name: str) -> None:
    """设置当前线程的 agent 名称（主 Agent 传 "__main__"，子 Agent 传其名称）。"""
    global _agent_name_fallback
    _current_agent_name.set(agent_name or "")
    with _agent_name_fallback_lock:
        _agent_name_fallback = agent_name or "__main__"


def get_current_agent_name() -> str:
    """获取当前 agent 名称；ContextVar 为空时回退到全局 fallback（默认 "__main__"）。"""
    name = _current_agent_name.get()
    if name:
        return name
    with _agent_name_fallback_lock:
        return _agent_name_fallback or "__main__"


# ---------- 等待中的请求注册表 ----------
# request_id -> {session_id, event, answer, meta, created_at}
_WAITING_REQUESTS: dict[str, dict[str, Any]] = {}
_requests_lock = threading.Lock()

_ABORT_CHECK_INTERVAL = 0.2  # 等待循环中检查 abort 标志的间隔（秒）

_DEFAULT_HEADLESS_ANSWER = "无人值守环境，无法进行人工交互，请基于现有信息自行决策。"


def _notify(session_id: str) -> None:
    """推送一次 live snapshot，使前端浮窗数据源（human_requests）即时更新。"""
    try:
        from agent.history.tool_call_recorder import _notify_live
        _notify_live(session_id)
    except Exception:
        pass


def ask_human(session_id: str, meta: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    """阻塞等待人工应答，返回 ``{"decision": str, "instruction": str}``。

    输入:
        session_id: 会话 ID。
        meta: 浮窗渲染数据（id/type/title/prompt/options/questions/instruction/
              agent_name/is_sub_agent/policy_note 等），由调用方按前端协议构造。
        timeout: 等待超时秒数；None 表示无限等待。

    输出:
        用户决策字典。decision 取值与前端一致：approve | reject | edit | skip；
        无人值守时立即返回默认 reject；超时返回 decision="timeout"。

    异常:
        等待期间检测到 abort 标志时抛 RuntimeError("ABORTED_BY_USER")，
        由 runtime 统一按手动暂停处理。
    """
    # 无人值守（cron/headless）：不阻塞，立即返回默认答案
    if os.environ.get("AGENT_HEADLESS"):
        return {"decision": "reject", "instruction": _DEFAULT_HEADLESS_ANSWER}

    request_id = uuid.uuid4().hex
    entry: dict[str, Any] = {
        "session_id": session_id,
        "request_id": request_id,
        "event": threading.Event(),
        "answer": None,
        "meta": dict(meta or {}),
        "created_at": time.time(),
    }
    entry["meta"].setdefault("id", request_id)
    with _requests_lock:
        _WAITING_REQUESTS[request_id] = entry
    _notify(session_id)

    try:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            # 每次醒来先检查 abort：暂停优先于答案
            try:
                from agent.core.runtime import check_abort
                if session_id and check_abort(session_id):
                    raise RuntimeError("ABORTED_BY_USER")
            except RuntimeError:
                raise
            except Exception:
                pass
            if entry["event"].wait(timeout=_ABORT_CHECK_INTERVAL):
                # 醒来后再检查一次 abort：暂停优先于答案，避免与 resolve 的竞态
                try:
                    from agent.core.runtime import check_abort
                    if session_id and check_abort(session_id):
                        raise RuntimeError("ABORTED_BY_USER")
                except RuntimeError:
                    raise
                except Exception:
                    pass
                break
            if deadline is not None and time.time() >= deadline:
                return {"decision": "timeout", "instruction": "等待人工应答超时"}
        return entry["answer"] or {"decision": "reject", "instruction": "未收到应答"}
    finally:
        with _requests_lock:
            _WAITING_REQUESTS.pop(request_id, None)
        _notify(session_id)


def answer_human_request(session_id: str, request_id: str, decision: str, instruction: str = "") -> bool:
    """回答一个等待中的人工请求（由 POST /api/human-action 调用）。

    输出:
        True 表示找到并已应答；False 表示请求不存在或不属于该会话（已过期）。
    """
    with _requests_lock:
        entry = _WAITING_REQUESTS.get(request_id)
        if entry is None or entry.get("session_id") != session_id:
            return False
        entry["answer"] = {"decision": decision, "instruction": instruction or ""}
        entry["event"].set()
    return True


def get_human_requests_for_session(session_id: str) -> list[dict[str, Any]]:
    """获取指定会话所有等待中的人工请求（供 live snapshot 推送给前端渲染浮窗）。"""
    with _requests_lock:
        return [dict(e["meta"]) for e in _WAITING_REQUESTS.values() if e.get("session_id") == session_id]


def resolve_all_for_session(session_id: str, decision: str = "reject", instruction: str = "") -> int:
    """一次性应答指定会话的所有等待请求（abort/清会话时调用），返回应答数量。"""
    with _requests_lock:
        entries = [e for e in _WAITING_REQUESTS.values() if e.get("session_id") == session_id]
        for e in entries:
            e["answer"] = {"decision": decision, "instruction": instruction or ""}
            e["event"].set()
    return len(entries)
