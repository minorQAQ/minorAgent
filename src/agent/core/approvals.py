"""待确认操作（HITL）：内存注册、UI 元数据构建、参数规范化与结果生成。

系统定位:
    维护进程内 ``PENDING_TOOL_APPROVALS`` 字典；在图因需确认工具而暂停时
    保存上下文并构建前端 UI 元数据；在用户操作后生成 ToolMessage 供图继续执行。

内容分区:
    - PENDING 存储与元数据构建（build_approval_meta / build_human_interaction_meta）
    - UI 消息辅助（remove_pending_ui_message）
    - human_interaction 工具的参数规范化与结果文案（normalize / result）

注意:
    当前为内存存储，进程重启后待确认项丢失；生产环境可改为 Redis/DB。

可扩展性:
    - 增加 TTL、session 级清理、持久化后端。
    - ``build_*_meta`` 可与前端组件协议版本化。
    - 新增 interaction_type 时同步扩展 normalize / result 分支。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from langchain_core.messages import BaseMessage
from langchain_core.messages import messages_to_dict

from agent.tools.human_interaction import HumanInteraction
from agent.utils.tool_call_utils import json_safe

# ============================================================
#  PENDING 存储
# ============================================================

PENDING_TOOL_APPROVALS: dict[str, dict[str, Any]] = {}


# ============================================================
#  UI 元数据构建
# ============================================================

def build_approval_meta(session_id: str, tool_call: dict[str, Any], messages: Sequence[BaseMessage], agent_name: str = "主Agent") -> dict[str, Any]:
    """为需确认的普通工具调用构建 UI 元数据并注册 pending。

    输入:
        session_id: 会话 ID。
        tool_call: normalize 后的工具调用 dict。
        messages: 当前图内消息序列（序列化后存入 pending）。
        agent_name: 发起该待确认项的 agent 名称（主 Agent 默认 "主Agent"）。

    输出:
        ``{"pending_action": {...}}``，含 id、type=tool_call、args、options 等。
    """
    approval_id = uuid.uuid4().hex
    tool_name = tool_call.get("name") or "unknown_tool"
    args = json_safe(tool_call.get("args") or {})
    display_call = {"name": tool_name, "args": args}
    instruction = json.dumps(display_call, ensure_ascii=False, indent=2)
    PENDING_TOOL_APPROVALS[approval_id] = {
        "session_id": session_id,
        "type": "tool_call",
        "tool_call": {"id": tool_call.get("id"), "name": tool_name, "args": args},
        "messages": messages_to_dict(list(messages)),
        "agent_name": agent_name,
        "is_sub_agent": agent_name not in ("", "主Agent", "__main__"),
    }
    return {
        "pending_action": {
            "id": approval_id,
            "type": "tool_call",
            "title": f"待确认执行工具：{tool_name}",
            "tool_name": tool_name,
            "args": display_call,
            "instruction": instruction,
            "options": ["approve", "reject"],
            "agent_name": agent_name,
            "is_sub_agent": agent_name not in ("", "主Agent", "__main__"),
            "resolved": False,
        }
    }


def build_human_interaction_meta(session_id: str, tool_call: dict[str, Any], messages: Sequence[BaseMessage], agent_name: str = "主Agent") -> dict[str, Any]:
    """为 human_interaction 工具构建 UI 元数据并注册 pending。

    输入:
        session_id: 会话 ID。
        tool_call: 含 name=args 的工具调用。
        messages: 当前消息序列。
        agent_name: 发起该待确认项的 agent 名称（主 Agent 默认 "主Agent"）。

    输出:
        ``{"pending_action": {...}}``，type=human_interaction，含 interaction_type 等。
    """
    approval_id = uuid.uuid4().hex
    args = normalize_human_interaction_args(tool_call.get("args") or {})
    interaction_type = args.get("interaction_type") or "information"
    default_titles = {
        "information": "请补充信息",
        "selection": "请选择一个选项",
    }
    PENDING_TOOL_APPROVALS[approval_id] = {
        "session_id": session_id,
        "type": "human_interaction",
        "tool_call": {"id": tool_call.get("id"), "name": "human_interaction", "args": args},
        "messages": messages_to_dict(list(messages)),
        "agent_name": agent_name,
        "is_sub_agent": agent_name not in ("", "主Agent", "__main__"),
    }
    return {
        "pending_action": {
            "id": approval_id,
            "type": "human_interaction",
            "interaction_type": interaction_type,
            "title": args.get("title") or default_titles.get(str(interaction_type), "需要人工处理"),
            "prompt": args.get("prompt") or "请处理后继续。",
            "tool_name": "human_interaction",
            "args": {
                "交互类型": interaction_type,
                "说明": args.get("prompt") or "请处理后继续。",
                "可选项": args.get("options") or [],
            },
            "instruction": args.get("suggested_response") or "",
            "options": args.get("options") or [],
            "questions": args.get("questions") or None,
            "agent_name": agent_name,
            "is_sub_agent": agent_name not in ("", "主Agent", "__main__"),
            "resolved": False,
        }
    }


def remove_pending_ui_message(chat_history: list[dict[str, Any]], approval_id: str) -> None:
    """在 chat_history 中将指定 approval_id 的 pending_action 标记为已解决（原地修改）。"""
    for msg in reversed(chat_history):
        pending = ((msg.get("meta") or {}).get("pending_action") or {}) if isinstance(msg, dict) else {}
        if pending.get("id") == approval_id:
            pending["resolved"] = True
            msg.setdefault("meta", {})["pending_action"] = pending
            return


def get_pending_actions_for_session(session_id: str) -> list[dict[str, Any]]:
    """获取指定会话所有未解决的 pending_action 列表（human_interaction + tool_call + sub_agent）。

    从 PENDING_TOOL_APPROVALS 中扫描，返回可供前端浮窗渲染的 pending_action 字典列表。
    每项携带 agent_name / is_sub_agent，供前端按 agent 分组弹窗。
    """
    actions = []
    for approval_id, entry in PENDING_TOOL_APPROVALS.items():
        if entry.get("session_id") != session_id:
            continue
        is_sub = bool(entry.get("is_sub_agent"))
        agent_name = entry.get("agent_name") or ("主Agent" if not is_sub else "子Agent")
        entry_type = entry.get("type")
        if entry_type == "human_interaction":
            args = normalize_human_interaction_args((entry.get("tool_call") or {}).get("args") or {})
            interaction_type = args.get("interaction_type") or "information"
            default_titles = {
                "information": "请补充信息",
                "selection": "请选择一个选项",
            }
            actions.append({
                "id": approval_id,
                "type": "human_interaction",
                "interaction_type": interaction_type,
                "title": args.get("title") or default_titles.get(str(interaction_type), "需要人工处理"),
                "prompt": args.get("prompt") or "请处理后继续。",
                "instruction": args.get("suggested_response") or "",
                "options": args.get("options") or [],
                "questions": args.get("questions") or None,
                "tool_name": "human_interaction",
                "agent_name": agent_name,
                "is_sub_agent": is_sub,
                "resolved": False,
            })
        elif entry_type == "tool_call":
            tool_call = entry.get("tool_call") or {}
            tool_name = tool_call.get("name") or "unknown_tool"
            args = tool_call.get("args") or {}
            display_call = {"name": tool_name, "args": args}
            actions.append({
                "id": approval_id,
                "type": "tool_call",
                "title": f"待确认执行工具：{tool_name}",
                "tool_name": tool_name,
                "args": display_call,
                "instruction": json.dumps(display_call, ensure_ascii=False, indent=2),
                "options": ["approve", "skip"] if is_sub else ["approve", "reject", "skip"],
                "agent_name": agent_name,
                "is_sub_agent": is_sub,
                "resolved": False,
            })
    return actions


# ============================================================
#  human_interaction 工具的参数规范化与结果文案
# ============================================================

def normalize_human_interaction_args(args: dict[str, Any]) -> dict[str, Any]:
    """规范化 human_interaction 工具参数为固定 schema。

    输入:
        args: 模型传入的原始参数字典。

    输出:
        含 interaction_type、title、prompt、options、suggested_response、questions 的字典；
        interaction_type 限定为 information | selection。
    """
    normalized = dict(args or {})
    normalized["interaction_type"] = str(normalized.get("interaction_type") or "information")
    if normalized["interaction_type"] not in {"information", "selection"}:
        normalized["interaction_type"] = "information"
    normalized["title"] = str(normalized.get("title") or "需要人工处理")
    normalized["prompt"] = str(normalized.get("prompt") or "请处理后继续。")
    normalized["options"] = HumanInteraction.normalize_options(normalized.get("options"))
    normalized["suggested_response"] = str(normalized.get("suggested_response") or "")
    # 规范化 questions 字段
    questions = normalized.get("questions")
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except (json.JSONDecodeError, TypeError):
            questions = None
    if isinstance(questions, list):
        normalized_questions = []
        for q in questions:
            if isinstance(q, dict):
                nq = {
                    "question": str(q.get("question", "")),
                    "options": HumanInteraction.normalize_options(q.get("options")),
                }
                normalized_questions.append(nq)
        normalized["questions"] = normalized_questions if normalized_questions else None
    else:
        normalized["questions"] = None
    return normalized


def human_interaction_result(pending: dict[str, Any], decision: str, instruction: str | None) -> str:
    """根据用户决策生成写入 ToolMessage 的文本结果。

    输入:
        pending: PENDING_TOOL_APPROVALS 中 type=human_interaction 的条目。
        decision: approve | reject | edit。
        instruction: 用户输入文本（补充信息、选项、修改说明等）。

    输出:
        供 LangGraph 继续推理的 ToolMessage 字符串内容。
    """
    tool_call = pending.get("tool_call") or {}
    args = normalize_human_interaction_args(tool_call.get("args") or {})
    interaction_type = args.get("interaction_type") or "information"
    options = args.get("options") or []
    return HumanInteraction.format_result(interaction_type, options, instruction or "")
