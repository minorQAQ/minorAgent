"""Agent 重复工具调用检测模块。

系统定位:
    在 ReAct 循环的 agent 节点调用 LLM 前，检测连续相同工具调用的异常模式，
    提供 Level 1 响应：注入反思提示引导模型自我纠正（不再强制终止，Level 2 已移除）。

配置来源:
    env_config.json 中的 LOOP_DETECT_REPEATED_TOOL_WARN 参数，可由前端动态修改。

可扩展性：
    可增加更多循环模式检测器、自定义检测规则。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import AIMessage

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
        "repeated_tool_warn": int(env.get("LOOP_DETECT_REPEATED_TOOL_WARN", 3)),
    }

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
    lookback = warn_threshold + 2

    recent = get_recent_tool_calls_from_messages(messages, count=lookback)
    consecutive = _compute_consecutive_same(recent)

    if consecutive < warn_threshold:
        return 0, "", None

    last_call = recent[-1] if recent else {}
    args_summary = format_args_summary(last_call.get("args", {}))
    return consecutive, last_call.get("name", "unknown"), args_summary


# ============================================================
#  反循环反思提示生成
# ============================================================

def build_loop_reflection_prompt(
    messages: list,
    session_id: str = "",
) -> str | None:
    """根据当前状态构建反循环反思提示（Level 1 响应）。

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

    if not parts:
        return None

    return "\n\n".join(parts)
