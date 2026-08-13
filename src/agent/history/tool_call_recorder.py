"""工具调用历史记录器：按 session/turn 存储及实时推送。

设计:
    每次用户输入 → 新建一个 turn，图节点执行期间通过 live 字典实时推送，
    前端轮询显示；turn 结束后 persist 到 JSON 并清除 live 记录。
    不同 turn 间数据完全隔离，不会泄漏到新对话中。
"""
from __future__ import annotations

import base64
import json
import time
import threading
import queue as _queue_module
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, ToolMessage

from agent.utils.agent_utils import SESSIONS_ROOT
from agent.utils.tool_call_utils import normalize_tool_call, format_args_summary, extract_reasoning_text

TOOL_CALLING_ROOT = Path(SESSIONS_ROOT)

# ---------- 子 Agent 轨迹存储（线程安全） ----------
# key: f"{session_id}/{turn_id}/{agent_name}"
_sub_traces_store: dict[str, list[dict[str, Any]]] = {}
_sub_traces_lock = threading.Lock()

# ---------- 当前 turn 上下文 ----------
_current_turn_id: ContextVar[str] = ContextVar("current_turn_id", default="")
_current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")
_context_fallback_lock = threading.Lock()
_current_turn_fallback = ""
_current_session_fallback = ""

# ---------- 子 Agent 上下文（实时路由到 call_subagent.sub_tool_calls） ----------
# 子 Agent 执行期间置为 True，使 record_*_live 调用路由到 _sub_live_records，
# 再由 get_live_tool_calls / _build_live_snapshot 合并到 call_subagent 条目的
# sub_tool_calls 中，供前端实时嵌套展开子 Agent 的工具调用轨迹。
# 同时子 Agent 轨迹仍通过 record_sub_agent_trace 独立存档供持久化注入。
_sub_agent_context: ContextVar[bool] = ContextVar("sub_agent_context", default=False)


def is_sub_agent_context() -> bool:
    """当前是否运行在子 Agent 上下文中。"""
    return _sub_agent_context.get()


@contextmanager
def sub_agent_context():
    """进入子 Agent 执行上下文：将 record_*_live 路由到 call_subagent 嵌套区域。

    子 Agent 的工具调用记录写入独立的 _sub_live_records[session_id]，
    get_live_tool_calls 将其注入到 call_subagent 条目的 sub_tool_calls 中，
    前端在 call_subagent 展开时实时渲染嵌套的子工具调用列表。

    进入时清空上一子 Agent 遗留的实时记录与待消费思考，
    避免同一轮内多个子 Agent 顺序执行时发生记忆串扰。
    """
    token = _sub_agent_context.set(True)
    try:
        _sid = get_current_session()
        if _sid:
            with _sub_live_lock:
                _sub_live_records.pop(_sid, None)
            with _sub_pending_thinking_lock:
                _sub_pending_thinking.pop(_sid, None)
        yield
    finally:
        _sub_agent_context.reset(token)

# ---------- 实时记录（线程安全） ----------
_live_lock = threading.Lock()
_live_records: dict[str, list[dict[str, Any]]] = {}

# 子 Agent 实时工具调用记录（session_id → list），独立存储，
# 在 get_live_tool_calls 中合并到 call_subagent 条目的 sub_tool_calls 中供前端嵌套展开。
_sub_live_records: dict[str, list[dict[str, Any]]] = {}
_sub_live_lock = threading.Lock()

# 子 Agent 待附加 thinking（与主 Agent 的 _pending_thinking 隔离）
_sub_pending_thinking: dict[str, str] = {}
_sub_pending_thinking_lock = threading.Lock()

# 轮次开始时间（key = session_id），用于计时
_turn_start_times: dict[str, float] = {}  # key = session_id

# 活跃 session 集合，用于区分 turn 已结束 vs 服务重启
_active_sessions: set[str] = set()

# ---------- SSE 订阅机制（pub/sub） ----------
# 每个 session 可有多个订阅者，工具调用状态变更时推送快照
_live_subscribers: dict[str, list[_queue_module.Queue]] = {}
_subscribers_lock = threading.Lock()

# ---------- 当前会话 token 用量（来自 LLM response usage_metadata） ----------
_session_tokens_lock = threading.Lock()
_session_tokens: dict[str, int] = {}  # session_id → total_tokens
_session_token_breakdowns: dict[str, dict] = {}  # session_id → {messages, tools, system}
_session_tokens_loaded: set[str] = set()  # 已从磁盘加载过的 session_id


def _persist_token(session_id: str, tokens: int, breakdown: dict | None = None) -> None:
    """将 token 写入存储（后端无关：mysql 存 sessions.extra，json 写 _session_tokens.json）。"""
    from agent.history import session_storage
    existing = session_storage.load_session_extra(session_id) or {}
    existing["tokens"] = tokens
    if breakdown:
        existing["token_breakdown"] = breakdown
    session_storage.save_session_extra(session_id, existing)


def _load_token_from_disk(session_id: str) -> int:
    """从存储读取 token（若不存在返回 0）。"""
    from agent.history import session_storage
    return int(session_storage.load_session_extra(session_id).get("tokens", 0) or 0)


def set_session_tokens(session_id: str, total_tokens: int, breakdown: dict | None = None) -> None:
    """存储当前会话的 LLM 最新 token 用量（内存 + 磁盘）。

    breakdown: {"messages": float, "tools": float, "system": float} 三类估算占比，
    由 nodes._estimate_token_breakdown 计算。
    """
    with _session_tokens_lock:
        _session_tokens[session_id] = total_tokens
        if breakdown:
            _session_token_breakdowns[session_id] = dict(breakdown)
    _persist_token(session_id, total_tokens, breakdown)


def get_session_tokens(session_id: str) -> int:
    """获取当前会话的 LLM 最新 token 用量（内存 → 磁盘 → 0）。"""
    with _session_tokens_lock:
        if session_id in _session_tokens:
            return _session_tokens[session_id]
    # 首次访问：从磁盘恢复
    if session_id not in _session_tokens_loaded:
        _session_tokens_loaded.add(session_id)
        tokens = _load_token_from_disk(session_id)
        if tokens:
            with _session_tokens_lock:
                _session_tokens[session_id] = tokens
        return tokens
    return 0


def get_session_token_breakdown(session_id: str) -> dict:
    """获取当前会话的三类 token 估算占比（消息/工具/系统提示词）。

    内存优先，回退存储（JSON 文件的 breakdown / MySQL 的 token_breakdown）。
    """
    with _session_tokens_lock:
        if session_id in _session_token_breakdowns:
            return dict(_session_token_breakdowns[session_id])
    from agent.history import session_storage
    extra = session_storage.load_session_extra(session_id) or {}
    bd = extra.get("token_breakdown")
    if isinstance(bd, dict):
        return bd
    return {"messages": 0.0, "tools": 0.0, "system": 0.0}


def clear_session_tokens(session_id: str) -> None:
    """清除指定会话的 token 记录（内存 + 存储）。"""
    with _session_tokens_lock:
        _session_tokens.pop(session_id, None)
        _session_token_breakdowns.pop(session_id, None)
    from agent.history import session_storage
    existing = session_storage.load_session_extra(session_id) or {}
    existing["tokens"] = 0
    existing.pop("token_breakdown", None)
    session_storage.save_session_extra(session_id, existing)

# ---------- 待附加的 thinking ----------
# 当 record_reflection_live 被调用时，thinking 暂存于此；
# 随后的 record_tool_call_live 会将其附加到工具调用记录中。
_pending_thinking: dict[str, str] = {}
_pending_thinking_lock = threading.Lock()


def set_current_turn(turn_id: str) -> None:
    global _current_turn_fallback
    _current_turn_id.set(turn_id)
    with _context_fallback_lock:
        _current_turn_fallback = turn_id


def get_current_turn() -> str:
    turn_id = _current_turn_id.get()
    if turn_id:
        return turn_id
    with _context_fallback_lock:
        return _current_turn_fallback


def set_current_session(session_id: str) -> None:
    global _current_session_fallback
    _current_session_id.set(session_id)
    with _context_fallback_lock:
        _current_session_fallback = session_id


def get_current_session() -> str:
    session_id = _current_session_id.get()
    if session_id:
        return session_id
    with _context_fallback_lock:
        return _current_session_fallback


def start_live_turn(session_id: str) -> str:
    """开始一个新 turn 并返回 turn_id。清除该 session 旧 live 记录。"""
    turn_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    return init_live_turn_with_id(session_id, turn_id)


def init_live_turn_with_id(session_id: str, turn_id: str) -> str:
    """使用已有 turn_id 初始化 live 记录（不清除旧 turn 持久化数据）。"""
    set_current_turn(turn_id)
    with _live_lock:
        _live_records[session_id] = []
        _turn_start_times[session_id] = time.time()  # 记录轮次开始时间
        _active_sessions.add(session_id)
    with _pending_thinking_lock:
        _pending_thinking.pop(session_id, None)
    return turn_id


def record_tool_call_live(session_id: str, name: str, args: dict[str, Any]) -> None:
    """图节点中调用：记录工具调用开始。同时消费 pending thinking。"""
    # 子 Agent 上下文：路由到 _sub_live_records，由 get_live_tool_calls 合并到
    # call_subagent 条目的 sub_tool_calls 中供前端嵌套展开。
    if is_sub_agent_context():
        with _sub_pending_thinking_lock:
            thinking = _sub_pending_thinking.pop(session_id, None)
        with _sub_live_lock:
            if session_id not in _sub_live_records:
                _sub_live_records[session_id] = []
            entry = {
                "name": name,
                "args": _json_safe(args),
                "args_summary": format_args_summary(args, max_len=40),
                "status": "running",
                "result_text": "",
            }
            if thinking:
                entry["thinking"] = thinking
            _sub_live_records[session_id].append(entry)
        _notify_live(session_id)
        return
    with _pending_thinking_lock:
        thinking = _pending_thinking.pop(session_id, None)
    with _live_lock:
        if session_id not in _live_records:
            _live_records[session_id] = []
        entry = {
            "name": name,
            "args": _json_safe(args),
            "args_summary": format_args_summary(args, max_len=40),
            "status": "running",
            "result_text": "",
        }
        if thinking:
            entry["thinking"] = thinking
        _live_records[session_id].append(entry)
    _notify_live(session_id)


def record_tool_result_live(
    session_id: str,
    name: str,
    result_text: str,
    artifact: Any | None = None,
) -> None:
    """记录工具返回结果，供前端实时展示文本、图片预览、音频信息与文件信息。"""
    # 子 Agent 上下文：路由到 _sub_live_records
    if is_sub_agent_context():
        with _sub_live_lock:
            records = _sub_live_records.get(session_id, [])
            for rec in reversed(records):
                if rec["name"] == name and rec["status"] == "running":
                    rec["status"] = "done"
                    rec["result_text"] = (result_text or "")[:500]
                    images = _artifact_image_data_urls(artifact)
                    if images:
                        rec["result_images"] = images
                    audio_info = _artifact_audio_info(artifact)
                    if audio_info:
                        rec["result_audio"] = audio_info
                    file_infos = _artifact_file_infos(artifact)
                    if file_infos:
                        rec["result_file_info"] = file_infos
                    break
        _notify_live(session_id)
        return
    with _live_lock:
        records = _live_records.get(session_id, [])
        for rec in reversed(records):
            if rec["name"] == name and rec["status"] == "running":
                rec["status"] = "done"
                rec["result_text"] = (result_text or "")[:500]
                images = _artifact_image_data_urls(artifact)
                if images:
                    rec["result_images"] = images
                audio_info = _artifact_audio_info(artifact)
                if audio_info:
                    rec["result_audio"] = audio_info
                file_infos = _artifact_file_infos(artifact)
                if file_infos:
                    rec["result_file_info"] = file_infos
                # 增量持久化到磁盘，防止进程崩溃时记录丢失
                _safe_persist_live_records(session_id, list(records))
                break
    _notify_live(session_id)


def _safe_persist_live_records(session_id: str, records: list[dict[str, Any]]) -> None:
    """将实时记录增量写入存储，防止进程崩溃丢失数据。

    系统定位:
        委托统一存储的 persist_live_records（可选行为：json 后端写 tool_*.json，
        mysql 后端不增量入库，由 save_turn 在轮次结束时统一落库）。
    """
    try:
        turn_id = get_current_turn()
        if not turn_id:
            return
        from agent.history import session_storage
        session_storage.persist_live_records(
            session_id, turn_id, records, started_at=_turn_start_times.get(session_id)
        )
    except Exception:
        pass  # 持久化失败不应影响主流程


def _artifact_image_data_urls(artifact: Any | None) -> list[str]:
    if not artifact:
        return []

    images: list[str] = []
    image_bytes_list: list[bytes] = []

    def collect(item: Any) -> None:
        if isinstance(item, bytes):
            image_bytes_list.append(item)
            return
        if not isinstance(item, dict):
            return
        if isinstance(item.get("image_bytes"), bytes):
            image_bytes_list.append(item["image_bytes"])
        # 支持 doc_tool 的 "images" 键（多图片列表）
        if isinstance(item.get("images"), list):
            for img in item["images"]:
                if isinstance(img, bytes):
                    image_bytes_list.append(img)
                elif isinstance(img, dict) and isinstance(img.get("image_bytes"), bytes):
                    image_bytes_list.append(img["image_bytes"])
        for key in ("image_url", "url", "data_url"):
            value = item.get(key)
            if isinstance(value, str) and (value.startswith("data:image/") or value.startswith("http")):
                images.append(value)
        image_url = item.get("image_url")
        if isinstance(image_url, dict):
            value = image_url.get("url")
            if isinstance(value, str) and (value.startswith("data:image/") or value.startswith("http")):
                images.append(value)

    # 处理 batch 类型 artifact
    if isinstance(artifact, dict) and artifact.get("file_type") == "batch":
        for item in artifact.get("items", []):
            collect(item)
    elif isinstance(artifact, list):
        for item in artifact:
            collect(item)
    else:
        collect(artifact)

    images.extend(
        "data:image/png;base64," + base64.standard_b64encode(img).decode("ascii")
        for img in image_bytes_list
    )
    return images


def _artifact_audio_info(artifact: Any | None) -> dict[str, Any] | None:
    """从 artifact 中提取音频元信息（不含音频字节，仅路径等元数据）。"""
    if not artifact:
        return None
    # 处理 batch 类型
    if isinstance(artifact, dict) and artifact.get("file_type") == "batch":
        for item in artifact.get("items", []):
            if isinstance(item, dict) and item.get("file_type") == "audio":
                return {
                    "file_path": item.get("file_path", ""),
                    "file_name": item.get("file_name", ""),
                }
        return None
    if isinstance(artifact, dict) and artifact.get("file_type") == "audio":
        return {
            "file_path": artifact.get("file_path", ""),
            "file_name": artifact.get("file_name", ""),
        }
    return None


def _artifact_file_infos(artifact: Any | None) -> list[dict[str, Any]] | None:
    """从 artifact 中提取非图片文件/文件夹的元信息列表（不含文件字节）。"""
    if not artifact:
        return None
    if not isinstance(artifact, dict):
        return None
    # 处理 batch 类型
    if artifact.get("file_type") == "batch":
        result = []
        for item in artifact.get("items", []):
            if not isinstance(item, dict):
                continue
            ft = item.get("file_type", "")
            if ft == "file":
                result.append({
                    "file_type": "file",
                    "file_path": item.get("file_path", ""),
                    "file_name": item.get("file_name", ""),
                    "file_size": item.get("file_size", 0),
                    "mime_type": item.get("mime_type", "application/octet-stream"),
                })
            elif ft == "image":
                result.append({
                    "file_type": "image",
                    "file_path": item.get("file_path", ""),
                    "file_name": item.get("file_name", ""),
                })
            elif ft == "folder":
                result.append({
                    "file_type": "folder",
                    "file_path": item.get("file_path", ""),
                    "file_name": item.get("file_name", ""),
                })
        return result if result else None
    if artifact.get("file_type") == "file":
        return [{
            "file_type": "file",
            "file_path": artifact.get("file_path", ""),
            "file_name": artifact.get("file_name", ""),
            "file_size": artifact.get("file_size", 0),
            "mime_type": artifact.get("mime_type", "application/octet-stream"),
        }]
    if artifact.get("file_type") == "image":
        return [{
            "file_type": "image",
            "file_path": artifact.get("file_path", ""),
            "file_name": artifact.get("file_name", ""),
        }]
    if artifact.get("file_type") == "folder":
        return [{
            "file_type": "folder",
            "file_path": artifact.get("file_path", ""),
            "file_name": artifact.get("file_name", ""),
        }]
    return None


def end_live_turn(session_id: str) -> list[dict[str, Any]]:
    """结束实时记录并返回该 turn 所有记录（同时清空反思与 pending thinking）。"""
    set_current_turn("")
    clear_live_reflections(session_id)
    with _pending_thinking_lock:
        _pending_thinking.pop(session_id, None)
    with _sub_pending_thinking_lock:
        _sub_pending_thinking.pop(session_id, None)
    with _sub_live_lock:
        _sub_live_records.pop(session_id, None)
    with _live_lock:
        _active_sessions.discard(session_id)
        return _live_records.pop(session_id, [])


# ---------- SSE 订阅 API ----------
def subscribe_live(session_id: str) -> _queue_module.Queue:
    """订阅指定 session 的实时工具调用更新，返回一个 Queue。"""
    q: _queue_module.Queue = _queue_module.Queue(maxsize=64)
    with _subscribers_lock:
        if session_id not in _live_subscribers:
            _live_subscribers[session_id] = []
        _live_subscribers[session_id].append(q)
    return q


def unsubscribe_live(session_id: str, q: _queue_module.Queue) -> None:
    """取消订阅。"""
    with _subscribers_lock:
        subs = _live_subscribers.get(session_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            _live_subscribers.pop(session_id, None)


def _build_live_snapshot(session_id: str) -> dict[str, Any]:
    """构建当前实时状态的快照（不加锁，调用者需确保数据一致性或在锁外读取）。

    除工具调用/思考/轮次开始时间外，还附带当前等待中的人工请求
    （human_requests），前端据此渲染确认浮窗。
    """
    snapshot = {
        "tool_calls": get_live_tool_calls(session_id),
        "reflections": get_live_reflections(session_id),
        "started_at": get_turn_started_at(session_id),
    }
    try:
        # 惰性导入避免与 human_request(其模块级导入本模块) 循环依赖
        from agent.core.human_request import get_human_requests_for_session
        snapshot["human_requests"] = get_human_requests_for_session(session_id)
    except Exception:
        snapshot["human_requests"] = []
    return snapshot


def _notify_live(session_id: str) -> None:
    """通知所有订阅者：推送当前快照。在工具调用状态变更后调用。"""
    with _subscribers_lock:
        subs = list(_live_subscribers.get(session_id, []))
    if not subs:
        return
    snapshot = _build_live_snapshot(session_id)
    for q in subs:
        try:
            q.put_nowait(snapshot)
        except _queue_module.Full:
            # 队列满时丢弃最旧的消息，放入最新的
            try:
                q.get_nowait()
                q.put_nowait(snapshot)
            except Exception:
                pass


def save_aborted_turn(session_id: str, turn_id: str) -> None:
    """Abort 时将当前内存中的 live 记录落盘为 turn JSON，避免工具调用历史丢失。"""
    with _live_lock:
        records = list(_live_records.get(session_id, []))
    if not records:
        return
    # 将 live 记录格式转为 save_turn 兼容格式
    normalized: list[dict[str, Any]] = []
    for r in records:
        entry = {
            "name": r.get("name", ""),
            "args": r.get("args", {}),
            "args_summary": r.get("args_summary", ""),
            "status": r.get("status", "done" if r.get("result_text") else "running"),
            "result_text": r.get("result_text", ""),
            "thinking": r.get("thinking", ""),
            "result_images": r.get("result_images", []),
            "result_audio": r.get("result_audio"),
            "result_file_info": r.get("result_file_info"),
        }
        normalized.append(entry)
    session_dir = session_tool_dir(session_id)
    _ensure_dir(session_dir)
    ended_at = time.time()
    # 优先使用 _turn_start_times（轮次开始时刻），回退到 ended_at（确保 duration 不为负）
    started_at = _turn_start_times.get(session_id) or ended_at
    # 工具调用记录统一走存储（后端无关：mysql 只入库，json 只写文件，不双写）
    from agent.history import session_storage
    _meta = {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration": max(0, ended_at - started_at),
        "aborted": True,
    }
    session_storage.save_tool_calls(session_id, turn_id, normalized, meta=_meta)


def get_live_tool_calls(session_id: str) -> list[dict[str, Any]]:
    """轮询接口：当前执行中 turn 的实时工具调用列表。

    优先返回内存中的实时记录；若内存为空（如服务重启后），回退到磁盘上
    最近一次增量持久化的 ``tool_*.json`` 文件，确保运行中记录不丢失。
    若 session 不在活跃集合中（turn 已结束），直接返回空列表，不回退磁盘，
    避免跨 turn 残留上轮工具调用记录。

    同时将子 Agent 的实时工具调用（_sub_live_records）注入到 call_subagent
    条目的 sub_tool_calls 中，供前端实时嵌套展开。
    """
    with _live_lock:
        records = _live_records.get(session_id)
        if records is not None:
            records = list(records)
        elif session_id not in _active_sessions:
            return []
        else:
            records = None
    # 回退磁盘
    if records is None:
        try:
            latest = get_latest_turn(session_id)
            if latest and latest.get("tool_calls"):
                records = list(latest["tool_calls"])
        except Exception:
            pass
    if not records:
        return []

    # ---- 注入子 Agent 实时轨迹到 call_subagent 条目 ----
    with _sub_live_lock:
        sub_calls = list(_sub_live_records.get(session_id, []))
    if sub_calls:
        # 找到最后一个 running 的 call_subagent 条目（从末尾向前找）
        for rec in reversed(records):
            if rec.get("name") in ("call_subagent", "agent_call") and rec.get("status") == "running":
                rec["sub_tool_calls"] = sub_calls
                break

    return records


def get_turn_started_at(session_id: str) -> float | None:
    """获取当前轮次的开始时间（Unix 时间戳），供前端实时计时使用。"""
    with _live_lock:
        if session_id in _turn_start_times:
            return _turn_start_times[session_id]
        if session_id not in _active_sessions:
            return None
    # 内存为空但 session 仍在活跃中：回退到磁盘上最近的 tool_*.json
    try:
        latest = get_latest_turn(session_id)
        if latest and latest.get("started_at"):
            return float(latest["started_at"])
    except Exception:
        pass
    return None


# ---------- 反思内容共享存储 ----------
# Agent 反思（think）内容通过此 store 实时推送到前端展示
_think_store: dict[str, list[dict[str, Any]]] = {}
_think_lock = threading.Lock()


def record_reflection_live(session_id: str, content: str) -> None:
    """记录一次反思内容到共享存储，同时设为 pending thinking 供后续工具调用附加。

    输入:
        session_id: 会话 ID。
        content: 反思提示文本。

    输出: 无。
    """
    if not session_id or not content:
        return
    # 子 Agent 上下文：thinking 存入 _sub_pending_thinking，
    # 由 record_tool_call_live 消费后附加到子工具调用条目。
    if is_sub_agent_context():
        with _sub_pending_thinking_lock:
            _sub_pending_thinking[session_id] = content
        # 不添加到 _think_store（子 Agent 思考在主 Agent 思考面板中不独立显示，
        # 而是嵌套在 call_subagent 展开的各个子工具调用条目的 thinking 字段中）
        return
    # 设为 pending thinking：下一个 record_tool_call_live 会消费它
    with _pending_thinking_lock:
        _pending_thinking[session_id] = content
    with _think_lock:
        if session_id not in _think_store:
            _think_store[session_id] = []
        # 避免重复记录相同内容
        for entry in _think_store[session_id]:
            if entry["content"] == content:
                return
        entry = {
            "content": content,
            "summary": content[:60].replace("\n", " "),
            "timestamp": time.time(),
        }
        _think_store[session_id].append(entry)
    _notify_live(session_id)


def get_live_reflections(session_id: str) -> list[dict[str, Any]]:
    """获取当前会话的反思列表（前端轮询）。"""
    with _think_lock:
        return list(_think_store.get(session_id, []))


def clear_live_reflections(session_id: str) -> None:
    """清空指定会话的反思记录。"""
    with _think_lock:
        _think_store.pop(session_id, None)


# ---------- 持久化 ----------
def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def session_tool_dir(session_id: str) -> Path:
    return TOOL_CALLING_ROOT / session_id


def extract_tool_calls_from_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """从图执行后的消息列表中提取完整的工具调用链（含思维链）。"""
    records: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    # 同名工具调用计数器，避免多张截图文件名冲突
    name_counter: dict[str, int] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            # 提取该 AIMessage 的 thinking，仅附加到第一个 tool_call
            # 提取规则见 extract_reasoning_text：开启思考取深度思考（reasoning_content/
            # 内联 <think> 块），关闭思考取 content 中的一句话反思
            thinking = extract_reasoning_text(msg)
            first = True
            for tc in msg.tool_calls:
                d = normalize_tool_call(tc)
                entry = {
                    "name": d.get("name", "unknown"),
                    "args": _json_safe(d.get("args", {})),
                    "args_summary": format_args_summary(d.get("args", {}), max_len=40),
                    "status": "done",
                    "result_text": "",
                    "result_files": [],
                    "result_images": [],
                }
                if thinking and first:
                    entry["thinking"] = thinking
                    first = False
                pending.append(entry)
        elif isinstance(msg, ToolMessage):
            if pending:
                entry = pending.pop(0)
                entry["result_text"] = str(msg.content) if msg.content else ""
                artifact = getattr(msg, "artifact", None)
                if artifact:
                    tool_name = msg.name or entry["name"]
                    idx = name_counter.get(tool_name, 0)
                    name_counter[tool_name] = idx + 1
                    unique_name = f"{tool_name}_{idx}"
                    result_files, bytes_map = _save_artifact_files(artifact, unique_name)
                    entry["result_files"] = result_files
                    entry["_all_bytes"] = bytes_map  # 供 save_turn 落盘（图片 + 文件）
                    # 提取图片 data URL（供前端直接展示）
                    images = _artifact_image_data_urls(artifact)
                    if images:
                        entry["result_images"] = images
                    # 提取音频信息（不含字节，仅路径元数据）
                    audio_info = _artifact_audio_info(artifact)
                    if audio_info:
                        entry["result_audio"] = audio_info
                    # 提取文件信息
                    file_infos = _artifact_file_infos(artifact)
                    if file_infos:
                        entry["result_file_info"] = file_infos
                records.append(entry)
    # 未匹配到 ToolMessage 的 pending 条目也标记为 done
    records.extend(pending)
    return records


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        return str(value)


def _save_artifact_files(artifact: Any, base_name: str) -> tuple[list[str], dict[str, bytes]]:
    """从 artifact 中提取文件名列表和 {文件名: bytes} 映射。

    支持 image_bytes（图片）和 file_bytes（send_file 的非图片文件），以及 batch 类型。
    音频类型不落盘（仅通过元信息传递路径）。
    """
    import os as _os
    files: list[str] = []
    bytes_map: dict[str, bytes] = {}

    # 处理 batch 类型 artifact（send_file 多文件）
    if isinstance(artifact, dict) and artifact.get("file_type") == "batch":
        for i, item in enumerate(artifact.get("items", [])):
            if isinstance(item, dict):
                if "image_bytes" in item:
                    fname = f"_artifact_{base_name}_{i}.png"
                    files.append(fname)
                    bytes_map[fname] = item["image_bytes"]
                elif item.get("file_type") == "file" and "file_bytes" in item:
                    file_name = item.get("file_name", "file")
                    ext = _os.path.splitext(file_name)[1] or ".bin"
                    fname = f"_file_{base_name}_{i}{ext}"
                    files.append(fname)
                    bytes_map[fname] = item["file_bytes"]
        return files, bytes_map

    if isinstance(artifact, dict):
        if "image_bytes" in artifact:
            fname = f"_artifact_{base_name}_0.png"
            files.append(fname)
            bytes_map[fname] = artifact["image_bytes"]
        if "images" in artifact and isinstance(artifact["images"], list):
            for i, img in enumerate(artifact["images"]):
                if isinstance(img, bytes):
                    fname = f"_artifact_{base_name}_{i}.png"
                    files.append(fname)
                    bytes_map[fname] = img
                elif isinstance(img, dict) and "image_bytes" in img:
                    fname = f"_artifact_{base_name}_{i}.png"
                    files.append(fname)
                    bytes_map[fname] = img["image_bytes"]
        if artifact.get("file_type") == "file" and "file_bytes" in artifact:
            file_name = artifact.get("file_name", "file")
            ext = _os.path.splitext(file_name)[1] or ".bin"
            fname = f"_file_{base_name}{ext}"
            files.append(fname)
            bytes_map[fname] = artifact["file_bytes"]
    elif isinstance(artifact, list):
        for i, item in enumerate(artifact):
            if isinstance(item, dict) and "image_bytes" in item:
                fname = f"_artifact_{base_name}_{i}.png"
                files.append(fname)
                bytes_map[fname] = item["image_bytes"]
            elif isinstance(item, bytes):
                fname = f"_artifact_{base_name}_{i}.png"
                files.append(fname)
                bytes_map[fname] = item
    elif isinstance(artifact, bytes):
        fname = f"_artifact_{base_name}.png"
        files.append(fname)
        bytes_map[fname] = artifact
    return files, bytes_map


def save_turn(session_id: str, turn_id: str, user_message: dict[str, Any],
              messages: list[BaseMessage]) -> str | None:
    """持久化工具调用记录（仅工具调用信息，不含对话内容）。

    合并策略：优先使用 live 记录中正确的 thinking/args_summary，
    再补充 extract_tool_calls_from_messages 提取的 artifact 数据（result_files/images 等）。
    单条工具计时（timestamp/ended_at）已移除，仅保留轮次级 started_at/ended_at/duration。
    """
    extracted = extract_tool_calls_from_messages(messages)
    if not extracted:
        return None

    session_dir = session_tool_dir(session_id)
    _ensure_dir(session_dir)

    # 收集产物文件，直接保存在 session 文件夹下（二进制产物始终落盘，与后端无关）
    for tc in extracted:
        all_bytes_map = tc.pop("_all_bytes", {})
        for fname, data_bytes in all_bytes_map.items():
            (session_dir / fname).write_bytes(data_bytes)

    # 读取已有的 live 记录（含正确的 thinking/args_summary）：
    # 统一从存储读取（json 后端为实时增量写盘的文件，mysql 后端无增量记录 → None）
    started_at = _turn_start_times.pop(session_id, None)
    from agent.history import session_storage
    live_record = session_storage.get_turn_record(session_id, turn_id)
    live_calls: list[dict[str, Any]] = []
    if live_record:
        live_calls = live_record.get("tool_calls") or []
        if live_record.get("started_at"):
            started_at = live_record["started_at"]

    # 合并：以 extracted 为基础，从 live 记录中补充正确的 thinking/args_summary
    tool_calls = _merge_extracted_with_live(extracted, live_calls)

    # 注入子 Agent 的工具调用轨迹到 call_subagent 条目中
    _inject_sub_traces_to_record(tool_calls, session_id, turn_id)

    ended_at = time.time()
    # 工具调用记录统一走存储（后端无关：mysql 只入库，json 只写文件，不双写）
    _meta = {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration": (ended_at - started_at) if started_at else None,
    }
    session_storage.save_tool_calls(session_id, turn_id, tool_calls, meta=_meta)
    return None


def _merge_extracted_with_live(
    extracted: list[dict[str, Any]],
    live_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将 extracted 的 artifact 数据合并到 live 记录上（保留 live 的 thinking/args_summary）。

    匹配策略：按索引位置匹配（同一轮次中工具调用顺序应一致）。
    如果数量不一致，回退到按 name+顺序 匹配。
    """
    if not live_calls:
        return extracted
    # 按索引合并
    result: list[dict[str, Any]] = []
    live_by_name: dict[str, list[dict[str, Any]]] = {}
    for lc in live_calls:
        live_by_name.setdefault(lc.get("name", ""), []).append(lc)
    name_idx: dict[str, int] = {}
    for i, ext in enumerate(extracted):
        name = ext.get("name", "")
        if i < len(live_calls):
            # 优先按索引匹配
            lc = live_calls[i]
        else:
            # 回退到按 name+顺序 匹配
            idx = name_idx.get(name, 0)
            name_idx[name] = idx + 1
            candidates = live_by_name.get(name, [])
            lc = candidates[idx] if idx < len(candidates) else {}
        merged = dict(ext)
        # 从 live 记录补充 thinking / args_summary（单条工具计时已移除，不再合并 timestamp/ended_at）
        for field in ("thinking", "args_summary"):
            if lc.get(field) is not None and not merged.get(field):
                merged[field] = lc[field]
        result.append(merged)
    return result


def _inject_sub_traces_to_record(tool_calls: list[dict[str, Any]], session_id: str, turn_id: str) -> None:
    """将子 Agent 的工具调用轨迹注入到 tool_calls 的 call_subagent 条目中（用于持久化）。"""
    for tc in tool_calls:
        if tc.get("name") not in ("call_subagent", "agent_call"):
            continue
        args = tc.get("args", {})
        if isinstance(args, str):
            try:
                import json as _json
                args = _json.loads(args)
            except Exception:
                args = {}
        sub_name = args.get("agent_name", "")
        if sub_name:
            sub_tc = get_sub_agent_traces_for_turn(session_id, turn_id, sub_name)
            if sub_tc:
                tc["sub_tool_calls"] = sub_tc


def list_turns(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """列出会话下所有 turn（按时间倒序，默认最近5轮）。

    输入:
        session_id: 会话 ID。
        limit: 返回的最大轮数，默认 5。
    """
    from agent.history import session_storage
    return session_storage.list_turn_records(session_id, limit)


def get_latest_turn(session_id: str) -> dict[str, Any] | None:
    """获取最近一个 turn 的完整记录（后端无关）。"""
    from agent.history import session_storage
    return session_storage.get_latest_turn_record(session_id)


def get_tool_calls_for_latest_turn(session_id: str) -> list[dict[str, Any]]:
    """获取最近一个 turn 的工具调用（供 UI 渲染）。"""
    latest = get_latest_turn(session_id)
    if not latest:
        return []
    return _tool_calls_from_turn_record(latest, session_id)


def _load_turn_record(session_id: str, turn_id: str) -> dict[str, Any] | None:
    """读取指定 turn_id 的工具调用记录（后端无关）。

    系统定位:
        get_tool_calls_for_turn / get_turn_meta / get_thinking_for_turn 共用的
        读取入口。返回与 tool_*.json 同构的 record dict；不存在返回 None。
    """
    if not turn_id:
        return None
    from agent.history import session_storage
    return session_storage.get_turn_record(session_id, turn_id)


def get_tool_calls_for_turn(session_id: str, turn_id: str) -> list[dict[str, Any]]:
    """获取指定 turn_id 的工具调用（供 UI 按消息还原）。"""
    if not turn_id:
        return []
    record = _load_turn_record(session_id, turn_id)
    if not record:
        return []
    return _tool_calls_from_turn_record(record, session_id)


def get_turn_meta(session_id: str, turn_id: str) -> dict[str, Any]:
    """获取指定 turn_id 的轮次级元数据（started_at/ended_at/duration）。"""
    if not turn_id:
        return {}
    record = _load_turn_record(session_id, turn_id)
    if not record:
        return {}
    return {
        k: record.get(k)
        for k in ("started_at", "ended_at", "duration")
        if record.get(k) is not None
    }


def get_thinking_for_turn(session_id: str, turn_id: str) -> list[dict[str, Any]]:
    """获取指定 turn_id 的思维链（供 UI 按消息还原）。"""
    if not turn_id:
        return []
    record = _load_turn_record(session_id, turn_id)
    if not record:
        return []
    # thinking 嵌入在 tool_calls 的各项中
    thinking_chain = []
    for tc in record.get("tool_calls", []):
        if tc.get("thinking"):
            thinking_chain.append({"content": tc["thinking"]})
    return thinking_chain


def _tool_calls_from_turn_record(record: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    """从 turn 记录中提取工具调用列表，补充图片路径、文件下载路径与音频信息。"""
    turn_id = record.get("turn_id", "")
    result = []
    for tc in record.get("tool_calls", []):
        entry = dict(tc)
        full_files = []
        for fname in tc.get("result_files", []):
            full_files.append(str(session_tool_dir(session_id) / fname))
        entry["result_files_full"] = full_files
        # 图片文件（_artifact_*.png）走 /api/tool-image 展示
        # 其他文件（_file_*）走 /api/tool-file 下载
        image_files = []
        other_files = []
        for fp in full_files:
            import os as _os
            fname = _os.path.basename(fp)
            if fname.startswith("_artifact_"):
                image_files.append(f"/api/tool-image?path={fp}&session={turn_id}")
            else:
                other_files.append(f"/api/tool-file?path={fp}&session={turn_id}")
        # 保留 live 记录中已有的 result_images（data URLs 来自实时录制），
        # 仅在无 data URL 时才用磁盘文件 URL 回退，避免覆盖导致前端无法渲染
        existing_images = entry.get("result_images")
        if (not existing_images or not isinstance(existing_images, list) or len(existing_images) == 0):
            entry["result_images"] = image_files
        if other_files:
            entry["result_download_files"] = other_files
        # 音频：补充 API 可访问的 URL
        if entry.get("result_audio") and entry["result_audio"].get("file_path"):
            entry["result_audio"]["api_url"] = (
                f"/api/tool-file?path={entry['result_audio']['file_path']}&session={turn_id}"
            )
        entry["turn_id"] = turn_id
        result.append(entry)
    return result


# ---------- 子 Agent 轨迹存取 ----------
def record_sub_agent_trace(session_id: str, turn_id: str, agent_name: str, tool_calls: list[dict[str, Any]]) -> None:
    """记录子 Agent 的完整工具调用轨迹，供前端嵌套展开。

    输入:
        session_id: 会话 ID。
        turn_id: 当前轮次 ID。
        agent_name: 被调用的子 Agent 名称。
        tool_calls: extract_tool_calls_from_messages 提取的子 Agent 工具调用列表。
    """
    if not session_id or not turn_id or not agent_name:
        return
    key = f"{session_id}/{turn_id}/{agent_name}"
    with _sub_traces_lock:
        _sub_traces_store[key] = tool_calls


def get_sub_agent_traces_for_turn(session_id: str, turn_id: str, agent_name: str) -> list[dict[str, Any]]:
    """获取指定会话/轮次/子 Agent 的轨迹。

    输入:
        session_id: 会话 ID。
        turn_id: 轮次 ID。
        agent_name: 子 Agent 名称。

    输出:
        工具调用轨迹列表。
    """
    if not session_id or not turn_id or not agent_name:
        return []
    key = f"{session_id}/{turn_id}/{agent_name}"
    with _sub_traces_lock:
        return list(_sub_traces_store.get(key, []))
