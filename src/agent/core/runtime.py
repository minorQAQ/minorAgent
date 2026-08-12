"""Agent 运行时：对话执行与历史持久化。

系统定位:
    Web 层（即 ``web.ui_session``）与 LangGraph 之间的编排层。
    ``agents/*`` 组装 ``AgentRuntime`` 实例，本模块提供统一执行 API。

主要流程:
    execute_agent: 用户消息 -> summarizer 压缩 -> graph.invoke -> 响应

    人机交互为阻塞式普通工具（见 ``agent.core.human_request``）：图内工具调用
    在线程中阻塞等待前端浮窗应答，同意/拒绝/补充信息都只是普通工具返回值，
    无需图暂停/续跑机制（不再有 continue_after_human_action）。

可扩展性：
    - ``AgentRuntime`` 可增加 checkpointer、tracing、多模态配置。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from agent.history.tool_call_recorder import save_turn, start_live_turn, end_live_turn, save_aborted_turn, set_current_turn, set_current_session
from agent.memory.system_prompt import get_plan_system_prompt, get_cron_system_prompt
from agent.core.loop_detector import should_force_end as loop_should_force_end, build_force_end_message
from agent.utils.agent_utils import assistant_text, get_history
from web.ui_session import rewrite_user_message_files_to_session_dir, sync_turn_from_chat_history

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


def _finalize_turn(
    runtime: AgentRuntime,
    all_messages: list[Any],
    chat_history: list[dict[str, Any]],
    session_id: str,
    user_content: Any,
    turn_id: str,
    agent_mode: str = "agent",
) -> list[dict[str, Any]]:
    """处理图执行完成后的公共逻辑：检查循环强制终止、保存 turn、构建 assistant 消息。"""
    # 循环检测 Level 2
    loop_force_end, loop_tool_name, loop_args_summary = loop_should_force_end(all_messages, session_id)
    if loop_force_end:
        end_live_turn(session_id)
        from agent.core.loop_detector import detect_repeated_tool_calls as _detect_repeated
        actual_count, _, _ = _detect_repeated(all_messages, session_id)
        loop_msg = build_force_end_message(loop_tool_name, actual_count, loop_args_summary)
        chat_history.append({"role": "assistant", "content": loop_msg, "meta": {"turn_id": turn_id}})
        if session_id:
            sync_turn_from_chat_history(session_id, chat_history, "")
        return chat_history

    # 正常结束
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
        更新后的 chat_history；可能追加 assistant 消息。

    系统定位:
        对外主入口，由 Web/API 层（turn_runner）在每轮用户发送后调用。
        人机交互在图上线程内阻塞等待，无待确认返回路径。

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
        # 主 Agent 上下文
        from agent.core.human_request import set_current_agent_name
        set_current_agent_name("__main__")
        result = _invoke_with_recursion_limit(runtime, runtime.graph, {"messages": messages, "agent_mode": agent_mode}, graph_config)
        set_current_turn("")
        set_current_session("")

        # 检查是否被 abort：保留已完成的工具调用记录，追加暂停消息结束本轮
        if session_id and check_abort(session_id):
            clear_abort_flag(session_id)
            save_aborted_turn(session_id, turn_id)
            end_live_turn(session_id)
            chat_history.append({"role": "assistant", "content": "已被用户手动暂停", "meta": {"paused": True}})
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
