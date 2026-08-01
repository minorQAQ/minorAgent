"""Agent 死循环检测模块。

系统定位:
    在 ReAct 循环的 agent 节点和路由节点之间，检测工具调用死循环、
    todolist 进度停滞等异常模式，提供分级响应：
    - Level 1: 注入反思提示引导模型自我纠正
    - Level 2: 强制终止图执行并向用户报告

配置来源:
    env_config.json 中的 LOOP_DETECT_* 参数，可由前端动态修改。

可扩展性：
    可增加更多循环模式检测器、自定义检测规则。
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Optional

from langchain_core.messages import AIMessage, ToolMessage

from agent.utils.tool_call_utils import normalize_tool_call, format_args_summary

# ============================================================
#  配置加载（每次检测时实时读取，支持前端热更新）
# ============================================================

def get_loop_config() -> dict:
    """从 env_config.json 读取循环检测参数（每次调用实时读取）。"""
    try:
        from agent.core.config_manager import load_env_config
        env = load_env_config()
    except Exception:
        env = {}
    return {
        "todolist_stale_rounds": int(env.get("LOOP_DETECT_TODOLIST_STALE_ROUNDS", 10)),
        "repeated_tool_warn": int(env.get("LOOP_DETECT_REPEATED_TOOL_WARN", 3)),
        "repeated_tool_end": int(env.get("LOOP_DETECT_REPEATED_TOOL_END", 5)),
    }

# ============================================================
#  状态存储（按 session_id，线程安全）
# ============================================================

_lock = threading.Lock()
_session_state: dict[str, dict] = {}


def _get_session_state(session_id: str) -> dict:
    """获取或创建 session 级循环检测状态。"""
    if not session_id:
        session_id = "_default"
    with _lock:
        if session_id not in _session_state:
            _session_state[session_id] = {
                "round_count": 0,
                "last_todolist_done_count": -1,
                "todolist_stale_rounds": 0,
            }
        return _session_state[session_id]


def reset_session(session_id: str) -> None:
    """重置指定 session 的循环检测状态（每轮用户输入时调用）。"""
    if not session_id:
        session_id = "_default"
    with _lock:
        _session_state[session_id] = {
            "round_count": 0,
            "last_todolist_done_count": -1,
            "todolist_stale_rounds": 0,
        }


def clear_session(session_id: str) -> None:
    """清除指定 session 的循环检测状态（会话结束时调用）。"""
    if not session_id:
        session_id = "_default"
    with _lock:
        _session_state.pop(session_id, None)


# ============================================================
#  工具调用历史分析
# ============================================================

def _tool_call_fingerprint(tc: dict) -> str:
    """计算单个工具调用的指纹 (tool_name, args_hash)。

    输入:
        tc: 已 normalize 的工具调用 dict。

    输出:
        "tool_name:md5hash" 格式的指纹字符串。
    """
    tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
    tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
    args_str = json.dumps(tc_args, sort_keys=True, default=str)
    args_hash = hashlib.md5(args_str.encode()).hexdigest()[:12]
    return f"{tc_name}:{args_hash}"


def get_recent_tool_calls_from_messages(
    messages: list,
    count: int = 10,
) -> list[dict]:
    """从消息列表中提取最近 N 个工具调用（含指纹）。

    输入:
        messages: 消息列表。
        count: 需要提取的最近工具调用数量。

    输出:
        [{"name": str, "args": dict, "fingerprint": str}, ...]，按时间正序排列。
    """
    result = []
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tc_dict = normalize_tool_call(tc)
                fingerprint = _tool_call_fingerprint(tc_dict)
                result.append({
                    "name": tc_dict.get("name", "unknown"),
                    "args": tc_dict.get("args", {}),
                    "fingerprint": fingerprint,
                })
    # 按时间正序，取最近 count 个
    return result[-count:] if len(result) > count else result


def _compute_consecutive_same(recent_calls: list[dict]) -> int:
    """计算从末尾向前连续相同的工具调用次数（基于指纹）。

    输入:
        recent_calls: 工具调用列表（时间正序）。

    输出:
        末尾连续相同指纹的次数。
    """
    if not recent_calls:
        return 0
    last_fp = recent_calls[-1]["fingerprint"]
    count = 0
    for call in reversed(recent_calls):
        if call["fingerprint"] == last_fp:
            count += 1
        else:
            break
    return count


def detect_repeated_tool_calls(
    messages: list,
    session_id: str = "",
) -> tuple[int, str, str | None]:
    """检测连续相同工具调用。

    输入:
        messages: 当前消息列表。
        session_id: 会话 ID。

    输出:
        (连续次数, 工具名, 参数摘要 | None)
        连续次数为 0 表示无重复。
    """
    cfg = get_loop_config()
    warn_threshold = max(cfg["repeated_tool_warn"], 2)
    end_threshold = max(cfg["repeated_tool_end"], warn_threshold + 1)
    lookback = end_threshold + 2

    recent = get_recent_tool_calls_from_messages(messages, count=lookback)
    consecutive = _compute_consecutive_same(recent)

    if consecutive < warn_threshold:
        return 0, "", None

    last_call = recent[-1] if recent else {}
    args_summary = format_args_summary(last_call.get("args", {}))
    return consecutive, last_call.get("name", "unknown"), args_summary


# ============================================================
#  Todolist 进度停滞检测
# ============================================================

def _get_current_todolist_done_count(session_id: str) -> int:
    """获取当前 todolist 的已完成步骤数。"""
    try:
        from agent.tools.todo_list import get_todo_store_data
        todo = get_todo_store_data(session_id)
        if todo and todo.get("steps"):
            return len(todo.get("done_steps", []))
    except Exception:
        pass
    return -1


def check_and_record_todolist_progress(
    messages: list,
    session_id: str = "",
) -> tuple[bool, int, str]:
    """检查 todolist 进度是否停滞，并更新内部状态。

    每轮 call_model 调用时调用一次。随着 round_count 递增，
    对比当前 done_count 与上次记录的 done_count，统计停滞轮数。

    输入:
        messages: 当前消息列表。
        session_id: 会话 ID。

    输出:
        (是否停滞超过阈值, 停滞轮数, todolist 状态摘要)
        需要注入反思提示时返回 True。
    """
    cfg = get_loop_config()
    stale_threshold = max(cfg["todolist_stale_rounds"], 1)

    state = _get_session_state(session_id)
    state["round_count"] = state.get("round_count", 0) + 1

    current_done = _get_current_todolist_done_count(session_id)

    # 如果没有 todolist，不检查
    if current_done < 0:
        state["last_todolist_done_count"] = -1
        state["todolist_stale_rounds"] = 0
        return False, 0, ""

    last_done = state.get("last_todolist_done_count", -1)

    if current_done != last_done:
        # 有进展，重置停滞计数
        state["last_todolist_done_count"] = current_done
        state["todolist_stale_rounds"] = 0
        return False, 0, ""
    else:
        # 无进展，递增停滞计数
        state["todolist_stale_rounds"] = state.get("todolist_stale_rounds", 0) + 1
        stale = state["todolist_stale_rounds"]

        # 构建 todolist 摘要
        try:
            from agent.tools.todo_list import get_todo_store_data
            todo = get_todo_store_data(session_id)
            steps = todo.get("steps", []) if todo else []
            done_set = set(todo.get("done_steps", [])) if todo else set()
            next_undone = ""
            for i, s in enumerate(steps):
                if i not in done_set:
                    next_undone = s[:50]
                    break
            total = len(steps)
            summary = f"总共 {total} 步，当前卡在步骤 {len(done_set)+1}/{total}：{next_undone}"
        except Exception:
            summary = f"已停滞 {stale} 轮"

        if stale >= stale_threshold:
            return True, stale, summary
        return False, stale, summary


def should_force_end(
    messages: list,
    session_id: str = "",
) -> tuple[bool, str, str | None]:
    """检查是否应强制终止（Level 2 响应）。

    当前仅检测连续相同工具调用超过 end 阈值的情况。

    输入:
        messages: 当前消息列表。
        session_id: 会话 ID。

    输出:
        (是否强制终止, 工具名, 参数摘要)
    """
    count, tool_name, args_summary = detect_repeated_tool_calls(messages, session_id)
    cfg = get_loop_config()
    end_threshold = max(cfg["repeated_tool_end"], cfg.get("repeated_tool_warn", 3) + 1)

    if count >= end_threshold:
        return True, tool_name, args_summary
    return False, "", None


# ============================================================
#  反循环反思提示生成
# ============================================================

def build_loop_reflection_prompt(
    messages: list,
    session_id: str = "",
) -> str | None:
    """根据当前状态构建反循环反思提示。

    输入:
        messages: 当前消息列表。
        session_id: 会话 ID。

    输出:
        反思提示文本；无需注入时返回 None。
    """
    parts = []

    # 检查 1: 连续相同工具调用 (Level 1 - 警告)
    tool_count, tool_name, args_summary = detect_repeated_tool_calls(messages, session_id)
    cfg = get_loop_config()
    warn_threshold = max(cfg["repeated_tool_warn"], 2)

    if tool_count >= warn_threshold:
        parts.append(
            f"【循环警告】你已经连续 {tool_count} 次调用工具 `{tool_name}` "
            f"且参数基本相同（{args_summary}），但似乎没有取得实质进展。\n"
            f"请反思当前策略是否有效，考虑：\n"
            f"1. 更换工具或策略\n"
            f"2. 检查之前的工具返回结果是否有误\n"
            f"3. 如果确实无法推进，向用户说明当前困难并请求帮助"
        )

    # 检查 2: Todolist 进度停滞
    is_stale, stale_rounds, stale_summary = check_and_record_todolist_progress(
        messages, session_id
    )
    stale_threshold = max(cfg["todolist_stale_rounds"], 1)

    if is_stale:
        parts.append(
            f"【进度停滞警告】TodoList 已有 {stale_rounds} 轮没有进度"
            + (f"（{stale_summary}）。" if stale_summary else "。")
            + f"\n请反思当前卡点，考虑是否需要调整计划或换一种方式继续。"
        )

    if not parts:
        return None

    return "\n\n".join(parts)


def build_force_end_message(
    tool_name: str,
    consecutive_count: int,
    args_summary: str | None = None,
) -> str:
    """构建强制终止时向前端输出的异常循环消息。

    输入:
        tool_name: 循环调用的工具名称。
        consecutive_count: 连续调用次数。
        args_summary: 参数摘要。

    输出:
        用户可读的循环报告文本。
    """
    args_info = f"\n参数：{args_summary}" if args_summary else ""
    return (
        f"**检测到异常循环**\n\n"
        f"工具 `{tool_name}` 已连续调用 {consecutive_count} 次且参数相同，判定为死循环，已强制终止本次任务。{args_info}\n\n"
        f"建议：请尝试换一种方式描述任务，或简化任务后重试。"
    )
