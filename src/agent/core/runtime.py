"""Agent 运行时：对话执行、历史持久化与人工确认续跑。

系统定位:
    Web 层（即 ``web.ui_session``）与 LangGraph 之间的编排层。
    ``agents/*`` 组装 ``AgentRuntime`` 实例，本模块提供统一执行 API。

主要流程:
    execute_agent: 用户消息 -> summarizer 压缩 -> graph.invoke -> 响应/待确认
    continue_after_human_action: 用户确认/拒绝 -> 工具执行或图续跑

可扩展性：
    - ``AgentRuntime`` 可增加 checkpointer、tracing、多模态配置。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langchain_core.messages import messages_from_dict

from agent.core.approvals import PENDING_TOOL_APPROVALS, remove_pending_ui_message, human_interaction_result
from agent.history.tool_call_recorder import save_turn, start_live_turn, end_live_turn, save_aborted_turn, set_current_turn, set_current_session
from agent.memory.system_prompt import get_plan_system_prompt, get_cron_system_prompt
from agent.core.loop_detector import reset_session as reset_loop_session, should_force_end as loop_should_force_end, build_force_end_message, clear_session as clear_loop_session
from agent.core.routing import first_pending_tool_meta
from agent.core.tool_policy import classify_tool_execution
from agent.tools.agent_call import SubAgentPendingError
from agent.utils.agent_utils import assistant_text, get_history
from agent.utils.tool_call_utils import normalize_tool_call, invoke_tool_and_build_message
from web.ui_session import rewrite_user_message_files_to_session_dir, session_dir, sync_turn_from_chat_history

AgentMode = Literal["agent", "plan", "cron"]


@dataclass
class AgentRuntime:
    """单个 Agent 的运行时配置容器。

    字段:
        name: Agent 标识，用于 session_meta 与日志。
        graph: 编译后的 LangGraph。
        llm: 原始 LLM 实例（压缩、TTS 等）。
        tools: 工具列表。
        tools_by_name: 工具名 → 工具实例，供确认后手动 invoke。
        system_prompt: 系统提示词，传入 summarizer。
        max_iterations: 最大迭代次数，超过则输出 OOM（默认 200）。

    系统定位:
        ``agents/main_agent`` 等模块的装配结果，传入 execute_agent。

    可扩展性：
        可增加 default_mode、专用 checkpointer 等字段。
    """

    name: str
    graph: Any
    llm: Any
    tools: list[Any]
    tools_by_name: dict[str, Any]
    system_prompt: str
    max_iterations: int = 200
    trajectory_rounds: int = 3
    description: str = ""


_OOM_MESSAGE = "OOM: 已达到最大迭代次数限制，任务未能完成。请简化任务或增加 max_iterations 配置后重试。"


def _inject_summary_context(session_id: str, messages: list) -> None:
    """注入压缩摘要（游标之前的工具调用历史已压缩进摘要，仅主 Agent）。"""
    if not session_id:
        return
    try:
        from agent.utils.agent_utils import get_session_meta
        meta = get_session_meta(session_id, "main")
        summary = meta.get("compressed_content") or ""
        if summary:
            # 固定 id：图内 compress 节点更新摘要时按同 id 替换，避免重复累积
            messages.append(SystemMessage(
                content=f"【历史工具调用摘要】\n{summary}",
                id="compressed_summary",
            ))
    except Exception:
        pass


def _inject_tool_history_context(session_id: str, messages: list) -> None:
    """注入压缩游标之后的全部轮次历史工具调用上下文（替代原"最近5轮"注入）。

    系统定位:
        上下文组成（用户方案）：
        系统提示词 + 压缩摘要 + 对话历史 + 压缩游标后的工具调用历史 + 本轮反思。
    """
    if not session_id:
        return
    try:
        from agent.utils.agent_utils import build_tool_history_messages
        messages.extend(build_tool_history_messages(session_id, "main"))
    except Exception:
        pass


def _rollback_chat_history_to_last_user(chat_history: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    """将 chat_history 回滚到上一条用户消息之前，并同步 turn 文件。"""
    rolled_back = list(chat_history)
    while rolled_back and rolled_back[-1].get("role") != "user":
        rolled_back.pop()
    if rolled_back:
        rolled_back.pop()
    if session_id:
        sync_turn_from_chat_history(session_id, rolled_back, "")
    return rolled_back


def _ensure_todo_cleared(session_id: str) -> None:
    """安全清理指定会话的 todo_list 缓存。"""
    if not session_id:
        return
    try:
        from agent.tools.todo_list import clear_todo_store_session
        clear_todo_store_session(session_id)
    except Exception:
        pass

# ---------- Abort 机制 ----------
_abort_flags: dict[str, threading.Event] = {}
_abort_lock = threading.Lock()


def set_abort_flag(session_id: str) -> None:
    """设置指定会话的 abort 标志，通知正在执行的 Agent 终止。"""
    if not session_id:
        return
    with _abort_lock:
        event = _abort_flags.get(session_id)
        if event is None:
            event = threading.Event()
            _abort_flags[session_id] = event
        event.set()


def check_abort(session_id: str) -> bool:
    """检查指定会话是否已被标记 abort。"""
    if not session_id:
        return False
    with _abort_lock:
        event = _abort_flags.get(session_id)
        return event is not None and event.is_set()


def clear_abort_flag(session_id: str) -> None:
    """清除指定会话的 abort 标志。"""
    if not session_id:
        return
    with _abort_lock:
        _abort_flags.pop(session_id, None)


def _invoke_with_recursion_limit(
    runtime: AgentRuntime,
    graph: Any,
    input_data: dict,
    config: dict | None = None,
) -> dict:
    """包装 graph.invoke，注入 recursion_limit 并捕获超限错误返回 OOM 消息。"""
    cfg = dict(config or {})
    cfg["recursion_limit"] = runtime.max_iterations
    try:
        return graph.invoke(input_data, config=cfg)
    except GraphRecursionError:
        print(f"[OOM] Agent '{runtime.name}' 达到最大迭代次数 {runtime.max_iterations}，输出 OOM。)")
        return {"messages": [AIMessage(content=_OOM_MESSAGE)], "_oom": True}
    except SubAgentPendingError as e:
        # 子 Agent 触发 HITL：冒泡到主图，返回主图消息快照 + sub_pending 元数据
        return {
            "messages": e.main_messages or [],
            "_sub_pending": e.pending_meta,
            "_main_tool_call_id": e.main_tool_call_id,
        }


def save_messages_to_history(session_id: str, user_msg: HumanMessage, assistant_msg: AIMessage) -> None:
    """将本轮用户与助手消息写入 JSON 聊天历史（turn 文件）。

    输入:
        session_id: 会话 ID；空则跳过。
        user_msg: 用户 HumanMessage；含 synthetic 标记时不写入。
        assistant_msg: 助手 AIMessage。

    输出:
        无。

    系统定位:
        execute_agent 正常回复结束后持久化对话。

    可扩展性：
        可改为异步写入、双写向量库、按 agent_name 分表。
    """
    if not session_id:
        return
    history = get_history(session_id)
    if not user_msg.additional_kwargs.get("synthetic"):
        history.add_message(user_msg)
    history.add_message(assistant_msg)


def _message_content_equals(left: Any, right: Any) -> bool:
    """宽松比较消息 content，兼容纯文本与多模态列表。"""
    if left == right:
        return True
    return assistant_text(left) == assistant_text(right)


def _pending_action_id(meta: dict[str, Any] | None) -> str | None:
    """从 assistant meta 中提取 pending_action.id。"""
    pending_action = (meta or {}).get("pending_action") or {}
    return pending_action.get("id")


def _remember_pending_user_content(pending_meta: dict[str, Any], user_content: Any) -> None:
    """将本轮用户输入缓存到 PENDING_TOOL_APPROVALS，供确认续跑时对齐历史。"""
    approval_id = _pending_action_id(pending_meta)
    if approval_id and approval_id in PENDING_TOOL_APPROVALS:
        PENDING_TOOL_APPROVALS[approval_id]["user_content"] = user_content


def _persist_messages_from_pending_turn(
    session_id: str,
    messages: list[Any],
    pending: dict[str, Any],
) -> None:
    if not session_id or not messages:
        return
    # 找到本轮用户消息
    user_content = pending.get("user_content")
    start_index = 0
    if user_content is not None:
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if isinstance(msg, HumanMessage) and not msg.additional_kwargs.get("synthetic"):
                if _message_content_equals(msg.content, user_content):
                    start_index = idx
                    break
    # 只提取：
    # - 用户消息（跳过 synthetic。）
    # - 最终一条不包含 tool_calls 的助手消息
    user_msg = None
    final_assistant = None

    for msg in messages[start_index:]:
        if isinstance(msg, HumanMessage) and not msg.additional_kwargs.get("synthetic"):
            user_msg = msg
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            final_assistant = msg

    history = get_history(session_id)
    if user_msg:
        history.add_message(user_msg)
    if final_assistant:
        history.add_message(final_assistant)


def _invoke_after_manual_tool_result(
    runtime: AgentRuntime,
    messages: list[Any],
    session_id: str,
    *,
    max_steps: int = 8,
    agent_mode: str = "agent",
) -> tuple[list[Any], dict[str, Any] | None]:
    """人工确认后继续推进图，并在遇到新的待确认项时暂停。"""
    current_messages = messages
    for _ in range(max_steps):
        result = _invoke_with_recursion_limit(runtime, runtime.graph, {"messages": current_messages, "agent_mode": agent_mode}, {"configurable": {"session_id": session_id}})
        all_messages = result["messages"]

        # 循环检测 Level 2：检查是否因死循环被强制终止
        force_end, loop_tool, loop_args = loop_should_force_end(all_messages, session_id)
        if force_end:
            # 返回特殊标记：pending_meta 中携带 _loop_force_end 信息
            return all_messages, {"_loop_force_end": True, "tool_name": loop_tool, "args_summary": loop_args or ""}

        pending_meta = first_pending_tool_meta(all_messages, session_id)
        if pending_meta:
            return all_messages, pending_meta

        last_msg = all_messages[-1] if all_messages else None
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return all_messages, None

        next_messages = [*all_messages]
        progressed = False
        for raw_tool_call in last_msg.tool_calls:
            tool_call = normalize_tool_call(raw_tool_call)
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args") or {}
            tool_call_id = tool_call.get("id") or f"manual_{session_id}_{len(next_messages)}"
            if classify_tool_execution(tool_name, tool_args) != "direct":
                continue
            tool = runtime.tools_by_name.get(tool_name or "")
            if not tool:
                continue
            tool_content, tool_artifact = invoke_tool_and_build_message(tool, tool_name, tool_args, tool_call_id)
            msg_kwargs = {"content": tool_content, "tool_call_id": tool_call_id, "name": tool_name or "unknown_tool"}
            if tool_artifact:
                msg_kwargs["artifact"] = tool_artifact
            next_messages.append(ToolMessage(**msg_kwargs))
            progressed = True
        if not progressed:
            return all_messages, None
        current_messages = next_messages
    return current_messages, None


def _finalize_turn(
    runtime: AgentRuntime,
    all_messages: list[Any],
    chat_history: list[dict[str, Any]],
    session_id: str,
    user_content: Any,
    turn_id: str,
    agent_mode: str = "agent",
) -> list[dict[str, Any]]:
    """处理图执行完成后的公共逻辑：检查 pending、保存 turn、构建 assistant 消息。"""
    # 循环检测 Level 2
    loop_force_end, loop_tool_name, loop_args_summary = loop_should_force_end(all_messages, session_id)
    if loop_force_end:
        end_live_turn(session_id)
        from agent.core.loop_detector import detect_repeated_tool_calls as _detect_repeated
        actual_count, _, _ = _detect_repeated(all_messages, session_id)
        loop_msg = build_force_end_message(loop_tool_name, actual_count, loop_args_summary)
        chat_history.append({"role": "assistant", "content": loop_msg, "meta": {"turn_id": turn_id}})
        if session_id:
            clear_loop_session(session_id)
            _ensure_todo_cleared(session_id)
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history

    # 检查待确认项
    pending_meta = first_pending_tool_meta(all_messages, session_id)
    if pending_meta:
        # 不调用 end_live_turn：human_interaction 和其他工具一样走 live 记录通道，
        # 前端持续轮询展示 running 状态，浮窗只是它的"前端 UI"
        _remember_pending_user_content(pending_meta, user_content)
        approval_id = _pending_action_id(pending_meta)
        if approval_id and approval_id in PENDING_TOOL_APPROVALS:
            PENDING_TOOL_APPROVALS[approval_id]["agent_mode"] = agent_mode
            PENDING_TOOL_APPROVALS[approval_id]["turn_id"] = turn_id
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history

    # 无待确认项：正常结束
    end_live_turn(session_id)
    assistant_msg = all_messages[-1] if all_messages else AIMessage(content="")
    content = assistant_text(assistant_msg.content) or "（空回复）"

    assistant_meta = {
        "turn_id": turn_id,
    }
    chat_history.append({"role": "assistant", "content": content, "meta": assistant_meta})

    # 持久化
    if session_id and turn_id:
        save_turn(session_id, turn_id, {"role": "user", "content": user_content}, all_messages)
    _persist_messages_from_pending_turn(session_id, all_messages, {"user_content": user_content})
    _ensure_todo_cleared(session_id)

    if session_id:
        sync_turn_from_chat_history(session_id, chat_history, "")
    return chat_history


def _classify_error(e: Exception) -> str:
    """将异常归类为用户可读的错误提示。"""
    msg = str(e)
    # LLM API 认证/鉴权错误
    if any(k in msg.lower() for k in ("401", "403", "unauthorized", "forbidden", "invalid api key", "authentication", "incorrect api key")):
        return "API Key 无效或无权访问，请检查模型配置中的 API Key 和 Base URL。"
    # 速率限制
    if any(k in msg.lower() for k in ("429", "rate limit", "too many requests", "quota")):
        return "API 调用频率过高或额度不足，请稍后重试或检查 API 配额。"
    # 网络/连接错误
    if any(k in msg.lower() for k in ("connection", "timeout", "connect", "network", "refused", "unreachable", "econnrefused", "etimedout", "socket", "dns")):
        return f"无法连接到模型服务，请检查网络连接和 Base URL 是否正确。"
    # 上下文超长
    if any(k in msg.lower() for k in ("context length", "too long", "maximum context", "token", "reduce", "truncat")):
        return "对话内容超过了模型上下文窗口限制，请尝试压缩对话或开启新会话。"
    # 模型不可用
    if any(k in msg.lower() for k in ("model not found", "does not exist", "not available", "deployment", "404")):
        return "指定的模型不可用，请检查 Model Name 是否正确。"
    # 服务器内部错误
    if any(k in msg.lower() for k in ("500", "502", "503", "internal", "server error", "overloaded")):
        return "模型服务端暂时故障，请稍后重试。"
    # RecursionError (LangGraph loop detection)
    if isinstance(e, RecursionError) or "recursion" in msg.lower():
        return "Agent 执行轮数超过限制，任务可能过于复杂，请尝试拆分或简化任务后重试。"
    # 通用兜底
    return f"执行过程中出现错误，请稍后重试。如果问题持续，请联系开发者。\n错误详情: {msg[:200]}"

def execute_agent(
    runtime: AgentRuntime,
    chat_history: list[dict[str, Any]],
    session_id: str = "test",
    agent_mode: AgentMode = "agent",
) -> list[dict[str, Any]]:
    """处理用户新一轮输入，驱动 Agent 图执行并更新 chat_history。

    输入:
        runtime: Agent 运行时配置。
        chat_history: Web UI 聊天历史（dict 列表）；末条须为 user。
        session_id: 会话 ID，用于历史、文件目录、turn 同步。
        agent_mode: agent（默认）| plan（先规划再执行）。

    输出:
        更新后的 chat_history；可能追加 assistant 消息、pending_action。

    系统定位:
        对外主入口，由 Web/API 层在每轮用户发送后调用。

    可扩展性:
        可返回 generator 支持流式；可注入 middleware 做鉴权、限流。
    """
    chat_history = chat_history or []

    if not chat_history or chat_history[-1].get("role") != "user":
        return chat_history

    if session_id:
        rewrite_user_message_files_to_session_dir(chat_history[-1], session_id)

    user_content = chat_history[-1]["content"]

    # 按运行模式选择系统提示词：plan/cron 使用专用提示词，其余用 runtime 默认
    if agent_mode == "plan":
        system_prompt = get_plan_system_prompt()
    elif agent_mode == "cron":
        system_prompt = get_cron_system_prompt()
    else:
        system_prompt = runtime.system_prompt

    # 从 turn 文件加载历史消息 + 注入压缩摘要与工具调用历史
    # 上下文组成：系统提示词 + 压缩摘要(若有) + 对话历史 + 压缩游标后的工具调用历史
    # 图内 compress 节点负责在 token 超阈值时压缩工具调用历史并更新游标
    messages = [SystemMessage(content=system_prompt)]
    if session_id:
        _inject_summary_context(session_id, messages)
        history = get_history(session_id)
        messages.extend(history.messages)
        # 注入压缩游标之后的所有轮次工具调用上下文
        _inject_tool_history_context(session_id, messages)
    messages.append(HumanMessage(content=user_content))

    graph_config = {
        "configurable": {"session_id": session_id},
    }

    try:
        # 开始实时记录（按 turn 隔离旧数据）
        turn_id = ""
        if session_id:
            # 优先使用 _chat_start_core 设置的 pending turn_id
            from agent.utils.agent_utils import take_pending_turn_id
            from agent.history.tool_call_recorder import start_live_turn, init_live_turn_with_id, set_current_session as _set_cur_sess
            pending_tid = take_pending_turn_id(session_id)
            if pending_tid:
                turn_id = init_live_turn_with_id(session_id, pending_tid)
            else:
                turn_id = start_live_turn(session_id)
            _set_cur_sess(session_id)
            clear_abort_flag(session_id)
            # 重置循环检测状态（每轮用户输入后重新开始计数）
            reset_loop_session(session_id)
        # 主 Agent 上下文：TodoList 按 agent 隔离时，主 Agent 用保留键 "__main__"
        from agent.tools.todo_list import set_current_agent_name
        set_current_agent_name("__main__")
        result = _invoke_with_recursion_limit(runtime, runtime.graph, {"messages": messages, "agent_mode": agent_mode}, graph_config)
        set_current_turn("")
        set_current_session("")

        # 检查是否被 abort：保留已完成的工具调用记录，追加暂停消息结束本轮
        if session_id and check_abort(session_id):
            clear_abort_flag(session_id)
            save_aborted_turn(session_id, turn_id)
            end_live_turn(session_id)
            _ensure_todo_cleared(session_id)
            chat_history.append({"role": "assistant", "content": "已被用户手动暂停", "meta": {"paused": True}})
            if session_id:
                sync_turn_from_chat_history(session_id, chat_history, "")
            return chat_history

        # ===== 子 Agent HITL 冒泡：主图在 call_subagent 处暂停 =====
        sub_pending_meta = result.get("_sub_pending")
        if sub_pending_meta:
            sub_approval_id = _pending_action_id(sub_pending_meta)
            if sub_approval_id and sub_approval_id in PENDING_TOOL_APPROVALS:
                entry = PENDING_TOOL_APPROVALS[sub_approval_id]
                entry["main_messages"] = list(result.get("messages") or [])
                entry["main_tool_call_id"] = result.get("_main_tool_call_id") or f"manual_{sub_approval_id}"
                entry["agent_mode"] = agent_mode
                entry["turn_id"] = turn_id
                entry["user_content"] = user_content
            # 不调用 end_live_turn：turn 仍 live，前端轮询展示 running + 浮窗
            if session_id:
                sync_turn_from_chat_history(session_id, chat_history, "")
            return chat_history

        all_messages = result["messages"]
        chat_history = _finalize_turn(runtime, all_messages, chat_history, session_id, user_content, turn_id, agent_mode)
        return chat_history

    except RuntimeError as e:
        if str(e) == "ABORTED_BY_USER":
            set_current_turn("")
            set_current_session("")
            clear_abort_flag(session_id)
            save_aborted_turn(session_id, turn_id)
            end_live_turn(session_id)
            _ensure_todo_cleared(session_id)
            chat_history.append({"role": "assistant", "content": "已被用户手动暂停", "meta": {"paused": True}})
            if session_id:
                sync_turn_from_chat_history(session_id, chat_history, "")
            return chat_history
        import traceback
        set_current_turn("")
        set_current_session("")
        end_live_turn(session_id)
        err_msg = _classify_error(e)
        print(f"[ERROR] 调用模型时出错: {err_msg}")
        traceback.print_exc()
        chat_history.append({"role": "assistant", "content": err_msg})
    except Exception as e:
        import traceback
        set_current_turn("")
        set_current_session("")
        end_live_turn(session_id)
        err_msg = _classify_error(e)
        print(f"[ERROR] 调用模型时出错: {err_msg}")
        traceback.print_exc()
        chat_history.append({"role": "assistant", "content": err_msg})

    if session_id:
        sync_turn_from_chat_history(session_id, chat_history, "")
    return chat_history


def _handle_loop_force_end_in_pending(pending_meta: dict[str, Any], chat_history: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]] | None:
    """若 pending_meta 包含 _loop_force_end，写入终止消息并返回 chat_history；否则返回 None。"""
    if not pending_meta.get("_loop_force_end"):
        return None
    loop_msg = build_force_end_message(
        pending_meta.get("tool_name", ""), 0,
        pending_meta.get("args_summary", ""),
    )
    chat_history.append({"role": "assistant", "content": loop_msg, "meta": {}})
    if session_id:
        clear_loop_session(session_id)
        sync_turn_from_chat_history(session_id, chat_history, "")
    return chat_history


def _finalize_new_pending_after_human_action(
    pending_meta: dict[str, Any],
    pending: dict[str, Any],
    chat_history: list[dict[str, Any]],
    session_id: str,
    agent_mode: str,
) -> list[dict[str, Any]]:
    """记录新的待确认项并返回 chat_history。"""
    _remember_pending_user_content(pending_meta, pending.get("user_content"))
    approval_id2 = _pending_action_id(pending_meta)
    if approval_id2 and approval_id2 in PENDING_TOOL_APPROVALS:
        PENDING_TOOL_APPROVALS[approval_id2]["agent_mode"] = agent_mode
        # 传递原始 turn_id 给嵌套的人机交互，确保所有记录写入同一个文件
        original_turn_id = pending.get("turn_id", "")
        if original_turn_id:
            PENDING_TOOL_APPROVALS[approval_id2]["turn_id"] = original_turn_id
    # 不追加空消息 — pending_action 由 API 层单独返回
    if session_id:
        sync_turn_from_chat_history(session_id, chat_history, "")
    return chat_history


def _resume_graph_after_tool_message(
    runtime: AgentRuntime,
    prior_messages: list[Any],
    session_id: str,
    agent_mode: str,
    pending: dict[str, Any],
    chat_history: list[dict[str, Any]],
    turn_id: str,
) -> list[dict[str, Any]]:
    """用已追加好 ToolMessage 的 prior_messages 续跑图，统一处理 pending/结束/持久化。

    用于主 Agent skip 续跑、子 Agent 完成后恢复主图。pending 提供 user_content/turn_id。
    """
    try:
        all_messages, pending_meta = _invoke_after_manual_tool_result(runtime, prior_messages, session_id, agent_mode=agent_mode)
        if pending_meta:
            end_live_turn(session_id)
            result = _handle_loop_force_end_in_pending(pending_meta, chat_history, session_id)
            if result is not None:
                return result
            return _finalize_new_pending_after_human_action(pending_meta, pending, chat_history, session_id, agent_mode)
        end_live_turn(session_id)
        assistant_msg = all_messages[-1] if all_messages else AIMessage(content="")
        content = assistant_text(assistant_msg.content) or "（空回复）"
        chat_history.append({"role": "assistant", "content": content, "meta": {"turn_id": turn_id}})
        _persist_messages_from_pending_turn(session_id, all_messages, pending)
        if session_id and turn_id:
            save_turn(session_id, turn_id, {"role": "user", "content": pending.get("user_content") or ""}, all_messages)
            _ensure_todo_cleared(session_id)
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history
    except Exception:
        import traceback
        traceback.print_exc()
        end_live_turn(session_id)
        content = "续跑图执行时遇到问题。"
        chat_history.append({"role": "assistant", "content": content, "meta": {}})
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history


def _extract_sub_final_text(all_messages: list[Any]) -> str:
    """从子 Agent 图消息中提取最后一条非工具调用的助手消息文本。"""
    for msg in reversed(all_messages or []):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
    return "子 Agent 已完成任务但未返回文字结果。"


def _invoke_sub_graph(
    sub_runtime: AgentRuntime,
    sub_messages: list[Any],
    session_id: str,
    agent_name: str,
    main_messages: list[Any],
    main_tool_call_id: str,
    agent_mode: str,
    user_content: Any,
    turn_id: str,
) -> tuple[list[Any], dict[str, Any] | None]:
    """恢复子 Agent 图执行（复用 _invoke_after_manual_tool_result）。

    若子图又产生 pending，已在 PENDING_TOOL_APPROVALS 中标记 is_sub_agent 并附加
    sub_runtime/sub_messages/main_messages/main_tool_call_id，供下一轮确认恢复。
    """
    from agent.tools.todo_list import set_current_agent_name
    set_current_agent_name(agent_name)
    # 子 Agent 续跑同样需抑制 record_*_live，避免其思考/工具调用
    # 混入主 Agent 的实时列表（与 agent_call.CallSubAgentTool._run 保持一致）。
    from agent.history.tool_call_recorder import sub_agent_context
    try:
        with sub_agent_context():
            sub_all_messages, sub_pending_meta = _invoke_after_manual_tool_result(
                sub_runtime, sub_messages, session_id, agent_mode=agent_mode
            )
    finally:
        set_current_agent_name("__main__")

    if sub_pending_meta and not sub_pending_meta.get("_loop_force_end"):
        approval_id = _pending_action_id(sub_pending_meta)
        if approval_id and approval_id in PENDING_TOOL_APPROVALS:
            entry = PENDING_TOOL_APPROVALS[approval_id]
            entry["is_sub_agent"] = True
            entry["agent_name"] = agent_name
            entry["sub_runtime"] = sub_runtime
            entry["sub_messages"] = list(sub_all_messages)  # 更新为最新子图消息
            entry["main_messages"] = main_messages
            entry["main_tool_call_id"] = main_tool_call_id
            entry["agent_mode"] = agent_mode
            entry["turn_id"] = turn_id
            entry["user_content"] = user_content
    return sub_all_messages, sub_pending_meta


def _resume_sub_agent(
    runtime: AgentRuntime,
    pending: dict[str, Any],
    chat_history: list[dict[str, Any]],
    session_id: str,
    approval_id: str,
    decision: str,
    instruction: str | None,
    agent_mode: str,
) -> list[dict[str, Any]]:
    """子 Agent HITL 确认/跳过后恢复：先续子图，子图完成后再恢复主图。"""
    sub_runtime = pending.get("sub_runtime")
    sub_messages = list(pending.get("sub_messages") or [])
    main_messages = list(pending.get("main_messages") or [])
    main_tool_call_id = pending.get("main_tool_call_id") or f"manual_{approval_id}"
    agent_name = pending.get("agent_name") or "子Agent"
    original_turn_id = pending.get("turn_id", "")
    sub_type = pending.get("type")
    sub_tool_call = dict(pending.get("tool_call") or {})
    sub_tool_name = sub_tool_call.get("name") or "unknown_tool"
    sub_call_id = sub_tool_call.get("id") or f"sub_{approval_id}"

    # 1) 构造子图续跑的 ToolMessage
    if decision == "skip" and sub_type != "human_interaction":
        sub_messages.append(ToolMessage(
            content=f"用户已跳过此工具调用（{sub_tool_name}），未执行。",
            tool_call_id=sub_call_id, name=sub_tool_name,
        ))
    elif sub_type == "human_interaction":
        sub_messages.append(ToolMessage(
            content=human_interaction_result(pending, "approve", instruction),
            tool_call_id=sub_call_id, name="human_interaction",
        ))
    else:
        sub_tool = sub_runtime.tools_by_name.get(sub_tool_name) if sub_runtime else None
        if sub_tool:
            tc, ta = invoke_tool_and_build_message(sub_tool, sub_tool_name, sub_tool_call.get("args") or {}, sub_call_id)
            msg_kwargs = {"content": tc, "tool_call_id": sub_call_id, "name": sub_tool_name}
            if ta:
                msg_kwargs["artifact"] = ta
            sub_messages.append(ToolMessage(**msg_kwargs))
        else:
            sub_messages.append(ToolMessage(
                content=f"工具 {sub_tool_name} 未找到", tool_call_id=sub_call_id, name=sub_tool_name,
            ))

    # 2) 恢复子图
    if session_id:
        set_current_session(session_id)
        if original_turn_id:
            from agent.history.tool_call_recorder import set_current_turn as _set_tc_turn
            _set_tc_turn(original_turn_id)
    sub_all_messages, sub_pending_meta = _invoke_sub_graph(
        sub_runtime, sub_messages, session_id, agent_name,
        main_messages, main_tool_call_id, agent_mode,
        pending.get("user_content"), original_turn_id,
    )

    if sub_pending_meta:
        # 子图又产生 pending（嵌套/连续 HITL）— _invoke_sub_graph 已注册新 pending（含 main 上下文）
        result = _handle_loop_force_end_in_pending(sub_pending_meta, chat_history, session_id)
        if result is not None:
            return result
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history

    # 3) 子图完成：提取最终文本，恢复主图
    sub_final_text = _extract_sub_final_text(sub_all_messages)
    main_messages.append(ToolMessage(content=sub_final_text, tool_call_id=main_tool_call_id, name="call_subagent"))
    from agent.tools.todo_list import set_current_agent_name
    set_current_agent_name("__main__")
    if session_id:
        turn_id = start_live_turn(session_id)
    else:
        turn_id = original_turn_id or ""
    main_pending = {"user_content": pending.get("user_content"), "turn_id": original_turn_id}
    return _resume_graph_after_tool_message(runtime, main_messages, session_id, agent_mode, main_pending, chat_history, original_turn_id or turn_id)


def continue_after_human_action(
    runtime: AgentRuntime,
    chat_history: list[dict[str, Any]],
    session_id: str,
    approval_id: str,
    decision: Literal["approve", "reject", "edit", "skip"],
    instruction: str | None = None,
) -> list[dict[str, Any]]:
    """用户对待确认项做出决策后，继续执行或结束该轮交互。

    输入:
        runtime: Agent 运行时。
        chat_history: 当前聊天历史。
        session_id: 会话 ID。
        approval_id: pending_action.id。
        decision: approve | reject | edit | skip。
            - approve: 执行工具/确认续跑；skip: 不执行工具但继续图（ToolMessage 标记跳过）。
            - reject: 与手动暂停一致——暂停当前 Agent 运行、保留之前的运行记录、
              前端追加"已被用户手动暂停"消息（对三种审批统一生效：权限不足 /
              workspace 越界 / 人机交互）。
            - edit: human_interaction selection 提交文本。
        instruction: selection 时为用户输入文本。

    输出:
        更新后的 chat_history。

    系统定位:
        UI 确认框回调入口；按 pending.type 与 is_sub_agent 分支：
        human_interaction / tool_call / sub_agent。

    可扩展性：
        可增加 timeout 自动 reject；支持批量 approve 多个 tool_call。
    """
    chat_history = chat_history or []
    pending = PENDING_TOOL_APPROVALS.pop(approval_id, None)
    if not pending:
        chat_history.append({"role": "assistant", "content": "该待确认项已处理或已过期。", "meta": {}})
        return chat_history

    remove_pending_ui_message(chat_history, approval_id)

    agent_mode = pending.get("agent_mode", "agent")

    # ===== 拒绝：统一三种审批（权限不足 / workspace 越界 / 人机交互）=====
    # 与手动暂停（/api/chat/abort）一致：暂停当前 Agent 运行、保留之前的运行记录，
    # 前端收到"已被用户手动暂停"消息。不恢复图执行。
    if decision == "reject":
        last_msg = chat_history[-1] if chat_history else None
        if not (last_msg and last_msg.get("role") == "assistant" and last_msg.get("content") == "已被用户手动暂停"):
            chat_history.append({"role": "assistant", "content": "已被用户手动暂停", "meta": {"paused": True}})
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history

    # ===== 子 Agent HITL 恢复（approve / skip，无 reject）=====
    if pending.get("is_sub_agent"):
        return _resume_sub_agent(runtime, pending, chat_history, session_id, approval_id, decision, instruction, agent_mode)

    # ===== 跳过：仅 tool_call 类型支持，human_interaction 不支持跳过 =====
    if decision == "skip" and pending.get("type") != "human_interaction":
        tool_call = dict(pending.get("tool_call") or {})
        tool_name = tool_call.get("name") or "unknown_tool"
        call_id = tool_call.get("id") or f"manual_{approval_id}"
        skip_content = f"用户已跳过此工具调用（{tool_name}），未执行。"
        prior_messages = messages_from_dict(pending.get("messages") or [])
        prior_messages.append(ToolMessage(content=skip_content, tool_call_id=call_id, name=tool_name))
        original_turn_id = pending.get("turn_id", "")
        if session_id:
            set_current_session(session_id)
            if original_turn_id:
                from agent.history.tool_call_recorder import set_current_turn as _set_tc_turn
                _set_tc_turn(original_turn_id)
            turn_id = start_live_turn(session_id)
        else:
            turn_id = original_turn_id or ""
        from agent.tools.todo_list import set_current_agent_name
        set_current_agent_name("__main__")
        return _resume_graph_after_tool_message(runtime, prior_messages, session_id, agent_mode, pending, chat_history, turn_id)

    if pending.get("type") == "human_interaction":
        original_turn_id = pending.get("turn_id", "")
        if session_id and original_turn_id:
            set_current_session(session_id)
            # 恢复原始 turn_id 到上下文，确保后续 live 记录写入正确的文件
            from agent.history.tool_call_recorder import record_tool_result_live, set_current_turn as _set_tc_turn
            _set_tc_turn(original_turn_id)
            tool_content = human_interaction_result(pending, decision, instruction)
            record_tool_result_live(session_id, "human_interaction", tool_content)
        else:
            tool_content = human_interaction_result(pending, decision, instruction) if session_id else ""
        try:
            tool_call = dict(pending.get("tool_call") or {})
            prior_messages = messages_from_dict(pending.get("messages") or [])
            call_id = tool_call.get("id") or f"human_{approval_id}"
            prior_messages.append(ToolMessage(content=tool_content, tool_call_id=call_id, name="human_interaction"))
            all_messages, pending_meta = _invoke_after_manual_tool_result(runtime, prior_messages, session_id, agent_mode=agent_mode)

            if pending_meta:
                # 新一轮 human_interaction：不清理 live 记录，前端继续轮询展示
                result = _handle_loop_force_end_in_pending(pending_meta, chat_history, session_id)
                if result is not None:
                    return result
                return _finalize_new_pending_after_human_action(pending_meta, pending, chat_history, session_id, agent_mode)

            # 正常结束
            end_live_turn(session_id)
            assistant_msg = all_messages[-1] if all_messages else AIMessage(content="")
            content = assistant_text(assistant_msg.content) or "（空回复）"
            chat_history.append({"role": "assistant", "content": content, "meta": {"turn_id": original_turn_id or f"human_{approval_id}"}})
            _persist_messages_from_pending_turn(session_id, all_messages, pending)
            if session_id and original_turn_id:
                save_turn(session_id, original_turn_id, {"role": "user", "content": pending.get("user_content") or ""}, all_messages)
                _ensure_todo_cleared(session_id)
                sync_turn_from_chat_history(session_id, chat_history, "")
            return chat_history
        except Exception:
            import traceback
            traceback.print_exc()
            end_live_turn(session_id)
            content = "处理人工交互结果时遇到问题。"
            chat_history.append({"role": "assistant", "content": content, "meta": {}})
            if session_id:
                sync_turn_from_chat_history(session_id, chat_history, "")
            return chat_history

    tool_call = dict(pending.get("tool_call") or {})
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args") or {}
    tool = runtime.tools_by_name.get(tool_name)
    if not tool:
        chat_history.append({"role": "assistant", "content": f"找不到工具：{tool_name}", "meta": {}})
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history

    if session_id:
        set_current_session(session_id)
        turn_id = start_live_turn(session_id)
    else:
        turn_id = ""
    try:
        tool_content, tool_artifact = invoke_tool_and_build_message(tool, tool_name, tool_args, tool_call.get("id", ""))
        prior_messages = messages_from_dict(pending.get("messages") or [])
        call_id = tool_call.get("id") or f"manual_{approval_id}"
        msg_kwargs = {"content": tool_content, "tool_call_id": call_id, "name": tool_name}
        if tool_artifact:
            msg_kwargs["artifact"] = tool_artifact
        prior_messages.append(ToolMessage(**msg_kwargs))
        all_messages, pending_meta = _invoke_after_manual_tool_result(runtime, prior_messages, session_id, agent_mode=agent_mode)

        if pending_meta:
            end_live_turn(session_id)
            result = _handle_loop_force_end_in_pending(pending_meta, chat_history, session_id)
            if result is not None:
                return result
            return _finalize_new_pending_after_human_action(pending_meta, pending, chat_history, session_id, agent_mode)

        # 正常结束
        end_live_turn(session_id)
        assistant_msg = all_messages[-1] if all_messages else AIMessage(content="")
        content = assistant_text(assistant_msg.content) or "（空回复）"
        chat_history.append({"role": "assistant", "content": content, "meta": {"turn_id": turn_id}})
        _persist_messages_from_pending_turn(session_id, all_messages, pending)
        if session_id and turn_id:
            save_turn(session_id, turn_id, {"role": "user", "content": pending.get("user_content") or ""}, all_messages)
            _ensure_todo_cleared(session_id)
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history
    except Exception:
        import traceback
        traceback.print_exc()
        end_live_turn(session_id)
        content = "执行确认后的工具调用时遇到问题。"
        prior_messages = messages_from_dict(pending.get("messages") or [])
        call_id = tool_call.get("id") or f"manual_{approval_id}"
        prior_messages.extend([
            ToolMessage(content=content, tool_call_id=call_id, name=tool_name or "unknown_tool"),
            AIMessage(content=content),
        ])
        chat_history.append({"role": "assistant", "content": content, "meta": {}})
        _persist_messages_from_pending_turn(session_id, prior_messages, pending)
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history
