# ui_session.py
"""
Web/API 与会话 UI 状态：会话 id 列表、turn 级存储、多模态 user 消息结构、附件落盘。
与 LangChain 链解耦；execute_agent 仍在 agent_runtime 中，此处提供其依赖的同步与解析函数。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from agent.utils.agent_utils import (
    SESSIONS_ROOT,
    assistant_text,
    AUDIO_FILE_EXTENSIONS,
    load_all_turn_messages,
    save_turn_messages,
    delete_turns_after,
    get_last_turn_id,
    turn_files_dir,
    session_dir as _agent_session_dir,
    set_pending_turn_id,
)
from agent.utils.image_utils import IMAGE_FILE_EXTENSIONS

_AUDIO_EXTENSIONS = AUDIO_FILE_EXTENSIONS  # 别名，保持向后兼容
_memory_session_ids: set[str] = set()


def session_dir(session_id: str) -> str:
    """返回会话目录的绝对路径。"""
    return _agent_session_dir(session_id)


def list_session_ids_ordered() -> list[str]:
    """从存储按最近活动倒序列出所有 session_id（后端无关）。

    系统定位:
        mysql 后端从 sessions 表按 updated_at 倒序读取；
        json 后端从目录扫描（存在 turn_*.json 的目录按 mtime 倒序）。
    """
    from agent.history import session_storage
    return session_storage.list_session_ids()


def new_timestamp_session_id() -> str:
    """生成基于时间戳的唯一会话 ID，冲突时追加序号后缀。

    输入: 无。

    输出:
        新的会话 ID 字符串（如 "20260609_143022" 或 "20260609_143022_1"）。

    系统定位:
        前端点击“新建会话”时调用的 ID 生成器。
    """
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    existing = set(list_session_ids_ordered()) | _memory_session_ids
    if base not in existing:
        _memory_session_ids.add(base)
        return base
    n = 1
    while True:
        cand = f"{base}_{n}"
        if cand not in existing:
            _memory_session_ids.add(cand)
            return cand
        n += 1


def prune_memory_session_ids() -> None:
    """移除已持久化的内存 session_id 缓存，避免集合无限增长。

    输入: 无。

    输出: 无。

    系统定位:
        每次会话操作后调用，清理过期的内存缓存。
    """
    persisted = set(list_session_ids_ordered())
    for sid in list(_memory_session_ids):
        if sid in persisted:
            _memory_session_ids.discard(sid)


def delete_session(session_id: str) -> None:
    """删除会话的内存缓存、目录（附件等）与存储记录。

    输入:
        session_id: 要删除的会话 ID。

    输出: 无。

    系统定位:
        API 层删除会话时彻底清理所有相关数据（目录清理与后端无关，
        记录删除由统一存储处理后端无关）。
    """
    if not session_id:
        return
    _memory_session_ids.discard(session_id)
    shutil.rmtree(session_dir(session_id), ignore_errors=True)
    try:
        from agent.history.tool_call_recorder import session_tool_dir
        shutil.rmtree(str(session_tool_dir(session_id)), ignore_errors=True)
    except Exception:
        pass
    # 存储记录删除（后端无关：mysql 删三表，json 删会话目录/记录文件）
    from agent.history import session_storage
    session_storage.delete_session(session_id)


def _build_user_chat_content(query) -> str | list | None:
    """根据上传文件扩展名直接生成多模态 content（与 LLM 输入格式一致）。

    输入:
        query: {"text": str, "files": list[str], "file_names": list[str]}

    输出:
        content 结构（str 或 list），无有效内容时返回 None。

    系统定位:
        add_message 中将前端上传的原始 query 转为 LangChain 可识别的 content。
        注意：用户上传的音频文件作为普通文件 part 展示（不再生成 audio part）；
        语音输入（麦克风录音）由 /api/chat/start 阻塞 ASR 转为 text，不进入此函数。
    """
    parts: list = []
    file_names = query.get("file_names") or []
    for idx, filepath in enumerate(query.get("files", []) or []):
        if not filepath:
            continue
        original_name = file_names[idx] if idx < len(file_names) else os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()
        if ext in IMAGE_FILE_EXTENSIONS:
            parts.append({"type": "image_url", "image_url": {"url": filepath}, "name": original_name})
        else:
            # 音频文件作为普通文件 part 展示（前端按文件卡片渲染）
            parts.append({"path": filepath, "name": original_name})
    text = (query.get("text") or "").strip()
    if text:
        parts.append({"type": "text", "text": text})
    if not parts:
        return None
    if len(parts) == 1 and parts[0].get("type") == "text":
        return parts[0]["text"]
    return parts


def _sanitize_filename_stem(name: str) -> str:
    """清理文件名主干中的非法字符，空名回退为 file。

    输入:
        name: 原始文件名。

    输出:
        清洗后的文件名主干（不含扩展名）。

    系统定位:
        _next_session_copy_name 中生成安全的文件名前缀。
    """
    stem = os.path.splitext(name or "")[0].strip()
    if not stem:
        return "file"
    sanitized = []
    for ch in stem:
        if ch in '<>:"/\\|?*':
            sanitized.append("_")
        else:
            sanitized.append(ch)
    stem = "".join(sanitized).rstrip(" .")
    return stem or "file"


def _next_session_copy_name(dest_dir: str, session_id: str, original_name: str, ext: str) -> str:
    """在会话目录内生成不冲突的附件副本文件名（含 session_id 与递增序号）。

    输入:
        dest_dir: 会话目录。
        session_id: 会话 ID。
        original_name: 原始文件名。
        ext: 扩展名（含点）。

    输出:
        不冲突的文件名字符串。

    系统定位:
        rewrite_user_message_files_to_session_dir 中为每个附件生成唯一副本名。
    """
    ext = ext or ""
    base_name = _sanitize_filename_stem(original_name)
    prefix = f"{base_name}_{session_id}_"
    max_index = 0
    try:
        for entry in os.listdir(dest_dir):
            stem, _existing_ext = os.path.splitext(entry)
            if not stem.startswith(prefix):
                continue
            suffix = stem[len(prefix):]
            if suffix.isdigit():
                max_index = max(max_index, int(suffix))
    except OSError:
        pass
    return f"{base_name}_{session_id}_{max_index + 1}{ext}"


def _rewrite_user_files_to_dir(user_msg: dict, dest_dir: str, session_id: str) -> None:
    """将 user 消息中的外部附件复制到指定目录并原地更新路径引用。
    
    (原 rewrite_user_message_files_to_session_dir，现改为通用版本)
    """
    os.makedirs(dest_dir, exist_ok=True)
    raw = user_msg.get("content")
    if not isinstance(raw, list):
        return
    new_list: list = []
    for piece in raw:
        if isinstance(piece, str) or not isinstance(piece, dict):
            new_list.append(piece)
            continue
        if piece.get("type") == "text":
            new_list.append(piece)
            continue
        src = piece.get("path") or (piece.get("file") or {}).get("path")
        if piece.get("type") == "image_url":
            src = src or (piece.get("image_url") or {}).get("url")
        if piece.get("type") == "audio":
            src = src or piece.get("audio_path")
        if not src or not os.path.isfile(src):
            new_list.append(piece)
            continue
        dest_dir_norm = os.path.normpath(dest_dir) + os.sep
        src_norm = os.path.normpath(src)
        if src_norm.startswith(dest_dir_norm):
            new_list.append(piece)
            continue
        ext = os.path.splitext(src)[1] or ""
        original_name = piece.get("name") or os.path.basename(src)
        dest_name = _next_session_copy_name(dest_dir, session_id, original_name, ext)
        dest = os.path.join(dest_dir, dest_name)
        shutil.copy2(src, dest)
        new_piece = dict(piece)
        new_piece["path"] = dest
        if piece.get("name"):
            new_piece["name"] = piece["name"]
        if piece.get("type") == "image_url":
            new_piece["image_url"] = {"url": dest}
        if piece.get("type") == "audio":
            new_piece["audio_path"] = dest
        new_list.append(new_piece)
    user_msg["content"] = new_list


def rewrite_user_message_files_to_session_dir(user_msg: dict, session_id: str) -> None:
    """向后兼容包装：将附件复制到会话根目录。"""
    _rewrite_user_files_to_dir(user_msg, session_dir(session_id), session_id)


def _serialize_user_msg_for_turn(user_msg: dict) -> dict:
    """将 user 消息序列化为可持久化到 turn 文件的 content 列表结构。

    输入:
        user_msg: 用户消息字典。

    输出:
        用于写入 turn 文件的 user 条目字典（含相对路径引用）。

    系统定位:
        sync_turn_from_chat_history 中将 user 消息转为可持久化格式。
    """
    raw = user_msg.get("content")
    content_list: list[dict] = []
    if isinstance(raw, str):
        if raw.strip():
            content_list.append({"type": "text", "text": raw})
    elif isinstance(raw, list):
        for piece in raw:
            if isinstance(piece, str) and piece.strip():
                content_list.append({"type": "text", "text": piece.strip()})
            elif isinstance(piece, dict):
                if piece.get("type") == "text":
                    content_list.append({"type": "text", "text": piece.get("text") or ""})
                    continue
                fp = piece.get("path") or (piece.get("file") or {}).get("path")
                if piece.get("type") == "image_url":
                    fp = fp or (piece.get("image_url") or {}).get("url")
                if piece.get("type") == "audio":
                    fp = fp or piece.get("audio_path")
                if not fp:
                    continue
                ext = os.path.splitext(fp)[1].lower()
                try:
                    rel = os.path.relpath(os.path.normpath(fp), os.path.normpath(SESSIONS_ROOT))
                except ValueError:
                    rel = fp.replace("\\", "/")
                if ext in IMAGE_FILE_EXTENSIONS:
                    part_type = "image_url"
                else:
                    # 音频文件作为普通文件 part 持久化与展示（不再区分 audio 类型）
                    part_type = "file"
                content_list.append({
                    "type": part_type,
                    "relpath": rel.replace("\\", "/"),
                    "name": piece.get("name") or os.path.basename(fp),
                })
    return {"content": content_list}


def _turn_user_entry_to_content(user_entry: dict) -> str | list:
    """将 turn 文件中的 user 条目还原为 UI/LLM 使用的 content（含附件绝对路径）。

    输入:
        user_entry: turn 文件中读取的 user 条目字典。

    输出:
        content 结构（str 或 list），用于展示或模型输入。

    系统定位:
        load_ui_messages_for_session 中从 turn 文件重建用户消息。
    """
    root_norm = os.path.normpath(SESSIONS_ROOT)
    parts_out: list = []
    any_image_missing = False
    had_image_parts = False

    content_data = user_entry.get("content")
    if content_data is None:
        return ""

    for p in content_data:
        part_type = p.get("type")
        if part_type == "text":
            t = (p.get("text") or "").strip()
            if t:
                parts_out.append({"type": "text", "text": t})
            continue
        rel = (p.get("relpath") or "").replace("/", os.sep)
        display_name = p.get("name") or (os.path.basename(rel) if rel else "附件")
        abs_p = os.path.normpath(os.path.join(root_norm, rel))
        try:
            under = os.path.commonpath([abs_p, root_norm]) == root_norm
        except ValueError:
            under = False
        if not under:
            if part_type == "image_url":
                any_image_missing = True
                had_image_parts = True
            continue
        if part_type == "image_url":
            had_image_parts = True
            if os.path.isfile(abs_p):
                parts_out.append({"type": "image_url", "image_url": {"url": abs_p}, "path": abs_p, "name": display_name})
            else:
                any_image_missing = True
        elif part_type == "audio":
            # 兼容旧 turn 文件：历史 user audio 降级为普通文件展示
            if os.path.isfile(abs_p):
                parts_out.append({"path": abs_p, "name": display_name})
            else:
                parts_out.append({"type": "text", "text": f"[附件已丢失: {display_name}]"})
        elif part_type == "file":
            if os.path.isfile(abs_p):
                parts_out.append({"path": abs_p, "name": display_name})
            else:
                parts_out.append({"type": "text", "text": f"[附件已丢失: {display_name}]"})

    if had_image_parts and any_image_missing:
        parts_out.append({"type": "text", "text": "[图片已丢失]"})

    if not parts_out:
        return ""
    if len(parts_out) == 1 and parts_out[0].get("type") == "text":
        return parts_out[0]["text"]
    return parts_out


def _serialize_assistant_entry(assistant_msg: dict | None) -> dict:
    """将 assistant 消息及其 meta 序列化为 turn 文件的 assistant 条目。"""
    ac = (assistant_msg or {}).get("content", "")
    meta = dict((assistant_msg or {}).get("meta") or {})
    if isinstance(ac, str):
        atext = ac
    else:
        atext = assistant_text(ac) or "（空回复）"
    output_type = meta.get("output_type") or "text"
    entry = {
        "text": atext,
        "output_type": output_type,
        "turn_id": meta.get("turn_id"),
    }
    # 仅语音输出时写入音频相关字段
    if output_type == "voice":
        audio = meta.get("audio")
        audio_relpath = None
        if isinstance(audio, dict) and audio.get("path"):
            try:
                audio_relpath = os.path.relpath(
                    os.path.normpath(audio["path"]), os.path.normpath(SESSIONS_ROOT)
                )
            except ValueError:
                audio_relpath = str(audio["path"]).replace("\\", "/")
        entry["autoplay"] = bool(meta.get("autoplay") or (audio or {}).get("autoplay"))
        entry["audio_duration_seconds"] = (audio or {}).get("duration_seconds") if isinstance(audio, dict) else None
        entry["audio_relpath"] = audio_relpath.replace("\\", "/") if audio_relpath else None
    return entry


def _serialize_message_for_turn(msg: dict) -> dict | None:
    """按 role 分发单条 chat_history 消息到 user/assistant turn 级结构。

    输入:
        msg: 消息字典。

    输出:
        turn 格式的消息条目，或 None（无法识别）。
    """
    role = msg.get("role")
    if role == "user":
        return {"role": "user", "user": _serialize_user_msg_for_turn(msg)}
    if role == "assistant":
        return {"role": "assistant", "assistant": _serialize_assistant_entry(msg)}
    return None


def sync_turn_from_chat_history(session_id: str, chat_history: list, latest_user_image_description: str) -> None:
    """将最后一轮对话的消息写入 turn 级存储（含 turn_id 元数据）。"""
    if not session_id or not chat_history:
        return
    turn_id = get_last_turn_id(session_id)
    if not turn_id:
        return

    # 找到本轮消息区间：最后一条 user 及之后的消息
    start_idx = len(chat_history) - 1
    while start_idx >= 0 and chat_history[start_idx].get("role") != "user":
        start_idx -= 1
    if start_idx < 0:
        return
    turn_messages = list(chat_history[start_idx:])

    # 序列化（附带 turn_id）
    messages_out: list[dict] = []
    for msg in turn_messages:
        item = _serialize_message_for_turn(msg)
        if item is not None:
            # 将 turn_id 注入到每条消息中
            if msg.get("role") == "assistant" and isinstance(msg.get("meta"), dict):
                msg["meta"]["turn_id"] = turn_id
                item = _serialize_message_for_turn(msg)
            elif msg.get("role") == "user":
                if "meta" not in msg:
                    msg["meta"] = {}
                msg["meta"]["turn_id"] = turn_id
                item = _serialize_message_for_turn(msg)
            if item:
                pass  # turn_id 已存入 assistant 条目中，不需要冗余的 _turn_id
            messages_out.append(item)

    save_turn_messages(session_id, turn_id, messages_out)


def rollback_turns_from_history(session_id: str, chat_history: list) -> int:
    """根据回撤后的 chat_history，删除多余的 turn 目录。

    返回删除的 turn 数量。
    """
    if not session_id or not chat_history:
        if session_id:
            return delete_turns_after(session_id, "00000000_000000")
        return 0

    # 找到最后一个 turn：chat_history 中最后一条 user 消息所属的 turn
    keep_turn_id = "00000000_000000"
    for i in range(len(chat_history) - 1, -1, -1):
        tid = chat_history[i].get("meta", {}).get("turn_id") if isinstance(chat_history[i].get("meta"), dict) else None
        if tid:
            keep_turn_id = tid
            break

    return delete_turns_after(session_id, keep_turn_id)


def _assistant_turn_entry_to_content(entry: dict) -> str | list:
    """将 turn 文件中的 assistant 条目还原为 UI content（文本与/或音频部件）。

    输入:
        entry: turn 文件中的 assistant 条目字典。

    输出:
        content 结构（str 或 list），用于前端展示。
    """
    text = (entry.get("text") or "").strip()
    output_type = entry.get("output_type") or "text"
    autoplay = bool(entry.get("autoplay"))
    audio_duration_seconds = entry.get("audio_duration_seconds")
    audio_relpath = entry.get("audio_relpath")
    audio_abs_path = None
    if audio_relpath:
        root_norm = os.path.normpath(SESSIONS_ROOT)
        audio_abs_path = os.path.normpath(os.path.join(root_norm, audio_relpath.replace("/", os.sep)))
        try:
            under = os.path.commonpath([audio_abs_path, root_norm]) == root_norm
        except ValueError:
            under = False
        if not under or not os.path.isfile(audio_abs_path):
            audio_abs_path = None
    parts: list[dict] = []
    if output_type in ("text", "voice") and text:
        parts.append({"type": "text", "text": text})
    if output_type == "voice" and audio_abs_path:
        parts.append({
            "type": "audio",
            "audio_path": audio_abs_path,
            "path": audio_abs_path,
            "autoplay": autoplay,
            "duration_seconds": audio_duration_seconds,
        })
    if not parts:
        return text
    if len(parts) == 1 and parts[0].get("type") == "text":
        return parts[0]["text"]
    return parts


def _assistant_turn_entry_to_message(asst_entry: dict) -> dict | None:
    """将 turn 文件中的 assistant 条目还原为完整 assistant 消息 dict（含 meta）。

    输入:
        asst_entry: turn 文件中的 assistant 条目字典。

    输出:
        消息字典，包含 role、content、meta；无有效内容时返回 None。
    """
    if not isinstance(asst_entry, dict):
        asst_entry = {"text": str(asst_entry)}
    asst_content = _assistant_turn_entry_to_content(asst_entry)
    if not str(asst_entry.get("text") or "").strip() and asst_content == "":
        return None

    meta = {
        "output_type": asst_entry.get("output_type", "text"),
    }
    if asst_entry.get("autoplay"):
        meta["autoplay"] = asst_entry["autoplay"]
    if asst_entry.get("pending_action"):
        meta["pending_action"] = asst_entry.get("pending_action")
    if asst_entry.get("turn_id"):
        meta["turn_id"] = asst_entry.get("turn_id")
    audio_relpath = asst_entry.get("audio_relpath")
    if audio_relpath:
        root_norm = os.path.normpath(SESSIONS_ROOT)
        audio_path = os.path.normpath(os.path.join(root_norm, audio_relpath.replace("/", os.sep)))
        if os.path.isfile(audio_path):
            meta["audio"] = {
                "path": audio_path,
                "autoplay": asst_entry.get("autoplay", False),
                "duration_seconds": asst_entry.get("audio_duration_seconds"),
                "format": "wav",
                "sample_rate": 24000,
            }
    return {"role": "assistant", "content": asst_content, "meta": meta}


def _load_ui_messages_from_turn(session_id: str) -> list | None:
    """从 turn 文件加载 UI 消息。

    输入:
        session_id: 会话 ID。

    输出:
        消息列表，或 None（表示无有效数据）。
    """
    turn_msgs = load_all_turn_messages(session_id)
    if not turn_msgs:
        return None
    out: list[dict] = []
    for item in turn_msgs:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role == "user":
            out.append({"role": "user", "content": _turn_user_entry_to_content(item.get("user") or {})})
        elif role == "assistant":
            assistant_msg = _assistant_turn_entry_to_message(item.get("assistant") or {})
            if assistant_msg is not None:
                out.append(assistant_msg)
    return out


def load_ui_messages_for_session(session_id: str) -> list:
    """从 turn 文件加载会话 UI 消息；缺失时返回空列表。

    输入:
        session_id: 会话 ID。

    输出:
        消息列表（总是有效列表，可能为空）。
    """
    if not session_id:
        return []
    m = _load_ui_messages_from_turn(session_id)
    if m is not None:
        return m
    return []


def rewrite_user_files_for_last_turn(chat_history: list, session_id: str) -> None:
    """若末条为 user 消息，将其附件复制到 session 目录。

    输入:
        chat_history: 聊天历史列表。
        session_id: 会话 ID。

    输出: 无。

    系统定位:
        API 层添加用户消息后立即调用，落盘附件。
    """
    if session_id and chat_history and chat_history[-1].get("role") == "user":
        dest_dir = session_dir(session_id)
        _rewrite_user_files_to_dir(chat_history[-1], dest_dir, session_id)


def add_message(chat_history, query):
    """将上传 query 转为 user 消息追加到 chat_history；无有效内容时返回 None。

    输入:
        chat_history: 现有聊天历史。
        query: {"text": str, "files": list[str], "file_names": list[str]}

    输出:
        成功返回 new_chat_history，无有效内容返回 None。

    系统定位:
        API 层构造用户消息的核心函数。
    """
    chat_history = chat_history or []
    user_content = _build_user_chat_content(query)
    if user_content is None:
        return None
    chat_history.append({"role": "user", "content": user_content})
    return chat_history


def clear_ui_and_turns(session_id: str):
    """清空会话所有 turn 数据并返回空 chat_history 与重置后的 query 状态。"""
    if session_id:
        # 删除所有 turn JSON 文件和对应目录
        delete_turns_after(session_id, "00000000_000000")
    return [], {"text": "", "files": []}