"""LangGraph 图节点：模型调用、反思机制与工具产物后处理。

系统定位:
    实现 ReAct 循环中的 ``agent`` 节点工厂、``process_tool_artifact`` 节点。
    在 ``graph`` 注册到 StateGraph。

反思机制：
    ``make_call_model_node`` 在每次调用 LLM 前注入反思引导提示，
    模型收到后会在输出 tool_calls 的同时产出文本思考内容（思维链）。
    该文本思考内容被提取并记录到 think store 供前端实时展示。

可扩展性：
    - ``make_call_model_node`` 可注入 streaming、重试、用量统计回调。
    - ``process_tool_artifact`` 可扩展 audio、文件、结构化 JSON 等 artifact 类型。
"""
from __future__ import annotations

from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.core.loop_detector import build_loop_reflection_prompt
from agent.core.state import AgentState
from agent.memory.system_prompt import PLAN_FIRST_CALL_PROMPT, REFLECTION_PROMPT
from agent.utils.image_utils import image_bytes_to_openai_image_url_part
from agent.utils.tool_call_utils import normalize_tool_call, extract_reasoning_text
from langchain_core.messages import SystemMessage

def _has_image_content(msg: HumanMessage) -> bool:
    """判断 HumanMessage 是否包含图片内容（截图等 data URL）。

    输入:
        msg: 待检查的 HumanMessage。

    输出:
        True 表示 content 中包含 image_url 类型的内容块。
    """
    content = msg.content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return True
    return False


def _filter_short_term_memory(messages: list, trajectory_rounds: int) -> list:
    """过滤短期记忆：保留所有工具调用记录和工具文字返回值，图片截图仅保留最近 trajectory_rounds 轮。

    输入:
        messages: 完整消息列表。
        trajectory_rounds: 保留最近 N 轮的图片截图（合成 HumanMessage）；<=0 表示不过滤任何消息。

    输出:
        过滤后的消息列表。

    系统定位:
        call_model 节点在调用 LLM 前进行消息裁剪，避免 GUI 等多轮工具调用
        场景下上下文过长。

    规则:
        - 保留所有 SystemMessage、HumanMessage（非合成图片）、AIMessage、ToolMessage
        - 仅 process_tool_artifact 生成的合成图片 HumanMessage 按 trajectory_rounds 裁剪
        - 每轮由一个 AIMessage（含 tool_calls）定义
    """
    if trajectory_rounds <= 0:
        return list(messages)

    # 从后向前遍历，统计已遇到的含 tool_calls 的 AIMessage 轮数
    rounds_seen = 0
    kept_indices = set()

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]

        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            rounds_seen += 1

        # 合成图片消息：仅保留最近 trajectory_rounds 轮
        if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("synthetic") and _has_image_content(msg):
            if rounds_seen < trajectory_rounds:
                kept_indices.add(i)
        else:
            kept_indices.add(i)

    return [messages[i] for i in sorted(kept_indices)]


def _get_todolist_status() -> str:
    """获取当前会话的 todolist 状态摘要。

    输出:
        todolist 状态文本；无 todolist 时返回空字符串。
    """
    try:
        from agent.history.tool_call_recorder import get_current_session
        from agent.tools.todo_list import get_todo_store_data
        sid = get_current_session()
        if not sid:
            return ""
        todo = get_todo_store_data(sid)
        if not todo or not todo.get("steps"):
            return ""
        steps = todo["steps"]
        done = set(todo.get("done_steps", []))
        lines = []
        for i, s in enumerate(steps):
            status = "[已完成]" if i in done else "[待完成]"
            lines.append(f"  {i+1}. {status} {s}")
        total = len(steps)
        done_count = len(done)
        header = f"当前TodoList进度：{done_count}/{total} 已完成"
        return header + "\n" + "\n".join(lines)
    except Exception:
        return ""


def _build_reflection_prompt(agent_mode: str, is_first_call: bool, messages: list, session_id: str = "") -> str | None:
    """构建反思提示词，引导 Agent 在下一步执行前进行思考。

    输入:
        agent_mode: 运行模式（"agent" | "plan"）。
        is_first_call: 是否为当前任务的首次 agent 调用。
        messages: 当前消息列表（已过滤短期记忆），供循环检测使用。
        session_id: 会话 ID，供循环检测使用。

    输出:
        反思提示文本，不需要反思时返回 None。
    """
    todo_status = _get_todolist_status()

    # Plan 模式首次调用：强制要求生成 todolist
    if agent_mode == "plan" and is_first_call:
        return PLAN_FIRST_CALL_PROMPT

    # 非 plan 模式首次调用，不需要反思
    if is_first_call:
        return None

    # 后续调用：引导模型先思考再行动
    parts = [REFLECTION_PROMPT]

    if todo_status:
        parts.append(todo_status)
    else:
        parts.append("当前无 TodoList。")

    # 循环检测：注入反循环反思提示
    loop_warning = build_loop_reflection_prompt(messages, session_id)
    if loop_warning:
        parts.append(loop_warning)

    return "\n".join(parts)


def _is_first_agent_call(messages: list) -> bool:
    """判断是否为当前用户任务的首轮 agent 调用。

    规则：找到最后一条非 synthetic 的 HumanMessage（即用户最新输入）。
    检查其后是否存在 AIMessage。若不存在，说明 agent 尚未对该输入做出响应。

    输入:
        messages: 已过滤短期记忆的消息列表。

    输出:
        True 表示首次调用。
    """
    # 从后向前找到最后一条非 synthetic 的 HumanMessage
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, HumanMessage) and not msg.additional_kwargs.get("synthetic"):
            last_user_idx = i
            break

    if last_user_idx < 0:
        return True

    # 检查该用户消息之后是否有 AIMessage
    for i in range(last_user_idx + 1, len(messages)):
        if isinstance(messages[i], AIMessage):
            return False
    return True


# ---------- ReAct 循环内上下文压缩 ----------
def _extract_total_tokens(response: Any) -> int:
    """从模型 response 中提取 total_tokens。"""
    usage = None
    if hasattr(response, "response_metadata"):
        meta = response.response_metadata
        if isinstance(meta, dict):
            usage = meta.get("token_usage", {})
    if not usage and hasattr(response, "usage_metadata"):
        meta = response.usage_metadata
        if isinstance(meta, dict):
            usage = meta
    return usage.get("total_tokens", 0) if usage else 0


def _compress_messages_in_loop(state: dict, response: Any) -> None:
    """基于 LLM 返回的 token 用量，就地压缩 state["messages"]。

    读 response metadata 中的 ``total_tokens``，无需任何持久化字段。
    旧消息被原地替换为 SystemMessage 摘要，新消息保留不变。

    同时将 total_tokens 存入 tool_call_recorder 供前端实时展示。
    """
    total = _extract_total_tokens(response)
    if total <= 0:
        return

    # 存储最新 token 用量供前端轮询
    _sid = ""
    try:
        from agent.history.tool_call_recorder import get_current_session, set_session_tokens
        _sid = get_current_session() or ""
        if _sid:
            set_session_tokens(_sid, total)
    except Exception:
        pass

    from agent.utils.env_utils import LLM_CONTEXT_WINDOW, HARD_COMPRESS_RATE, MINI_COMPRESS_RATE
    light_thresh = int(LLM_CONTEXT_WINDOW * MINI_COMPRESS_RATE)
    hard_thresh = int(LLM_CONTEXT_WINDOW * HARD_COMPRESS_RATE)

    if total <= light_thresh:
        return

    messages: list = list(state["messages"])

    # 找到最新一条非 synthetic 的 HumanMessage（当前用户输入位置）
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            kw = getattr(messages[i], "additional_kwargs", {}) or {}
            if not kw.get("synthetic"):
                last_user_idx = i
                break
    if last_user_idx <= 0:
        return

    # 确定保留起点：hard 只保留 user 之后，light 保留本轮首个 agent 动作
    if total > hard_thresh:
        keep_from = last_user_idx
    else:
        keep_from = last_user_idx
        for i in range(last_user_idx - 1, 0, -1):
            if isinstance(messages[i], AIMessage) and getattr(messages[i], "tool_calls", None):
                keep_from = i
                break

    if keep_from <= 0:
        return

    # 构建待压缩文本
    to_compress = messages[:keep_from]
    parts = []
    for m in to_compress:
        if isinstance(m, SystemMessage):
            parts.append(f"[系统] {getattr(m, 'content', '')}")
        elif isinstance(m, HumanMessage):
            kw = getattr(m, "additional_kwargs", {}) or {}
            if not kw.get("synthetic"):
                parts.append(f"用户: {getattr(m, 'content', '')}")
        elif isinstance(m, AIMessage):
            if hasattr(m, "tool_calls") and m.tool_calls:
                names = [tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?") for tc in m.tool_calls]
                parts.append(f"AI调用工具: {', '.join(names)}")
            else:
                parts.append(f"AI回复: {getattr(m, 'content', '')[:200]}")
        elif isinstance(m, ToolMessage):
            parts.append(f"工具({getattr(m, 'name', '?')})返回: {getattr(m, 'content', '')[:300]}")

    compress_text = "\n".join(parts[-50:])
    if not compress_text.strip():
        return

    label = "全量" if total > hard_thresh else "轻量"
    before_len = len(messages)

    # SSE 通知前端：压缩开始
    try:
        from agent.history.tool_call_recorder import record_tool_call_live
        if _sid:
            record_tool_call_live(_sid, "summarizer", {
                "action": f"{label}压缩中",
                "before_tokens": total,
                "before_messages": before_len,
            })
    except Exception:
        pass

    from agent.core.llm import llm as compress_llm
    from agent.utils.agent_utils import summarize_chat_text

    try:
        summary_text = summarize_chat_text(compress_llm, compress_text)
        compressed_msg = SystemMessage(content=f"【运行中上下文摘要】\n{summary_text}")
        state["messages"] = [compressed_msg] + messages[keep_from:]
        after_len = len(state["messages"])

        # SSE 通知前端：压缩完成
        try:
            from agent.history.tool_call_recorder import record_tool_result_live
            if _sid:
                record_tool_result_live(_sid, "summarizer",
                    f"压缩完成: {before_len}→{after_len}条消息")
        except Exception:
            pass
    except Exception as e:
        # SSE 通知前端：压缩失败
        try:
            from agent.history.tool_call_recorder import record_tool_result_live
            if _sid:
                record_tool_result_live(_sid, "summarizer",
                    f"压缩失败: {str(e)}")
        except Exception:
            pass


def make_call_model_node(
    model_with_tools: Any,
    trajectory_rounds: int = 3,
) -> Callable[[AgentState], dict]:
    """创建带反思机制 + 上下文中压缩的调用已绑定工具的 LLM 的图节点闭包。

    每次调用前注入反思引导提示；调用后提取模型同时产出的文本思考内容（content），
    记录到 think store，供前端实时展示思维链。Plan 模式下首次调用强制要求生成 todolist。

    在每次 LLM 调用后，根据 response 的 ``usage_metadata.total_tokens`` 判断
    是否触发消息列表就地压缩——确保 ReAct 循环中的上下文永不溢出。
    """

    def call_model(state: AgentState) -> dict:
        all_messages = list(state["messages"])
        agent_mode = state.get("agent_mode", "agent")

        # 检查 abort 标志
        try:
            from agent.core.runtime import check_abort
            from agent.history.tool_call_recorder import get_current_session
            sid = get_current_session()
            if sid and check_abort(sid):
                raise RuntimeError("ABORTED_BY_USER")
        except RuntimeError:
            raise
        except Exception:
            pass

        filtered_messages = _filter_short_term_memory(all_messages, trajectory_rounds)

        # 判断是否为首轮 agent 调用（当前轮尚无 AIMessage）
        is_first_call = _is_first_agent_call(filtered_messages)

        # 获取 session_id 供循环检测使用
        try:
            from agent.history.tool_call_recorder import get_current_session
            _sid = get_current_session()
        except Exception:
            _sid = ""

        # 构建反思提示并注入到消息列表（仅作引导，不记录到前端）
        reflection = _build_reflection_prompt(agent_mode, is_first_call, filtered_messages, _sid)
        messages_for_llm = list(filtered_messages)
        if reflection:
            reflection_msg = HumanMessage(content=reflection, additional_kwargs={"synthetic": True, "reflection": True})
            messages_for_llm.append(reflection_msg)

        response = model_with_tools.invoke(messages_for_llm)

        # 基于模型返回 token 用量的上下文中压缩（读 response metadata，不依赖 SQLite）
        # 同时将 total_tokens 存入 session_tokens 供前端轮询
        _compress_messages_in_loop(state, response)

        # 提取模型真实输出的思考内容（content），记录到前端 think 面板
        # 模型同时输出 content + tool_calls 时，content 就是其思维链
        # 部分模型（如 Qwen enable_thinking）将思考放在 additional_kwargs.reasoning_content
        response_content = extract_reasoning_text(response)
        if response_content and isinstance(response_content, str) and response_content.strip():
            has_tool_calls = getattr(response, "tool_calls", None)
            if has_tool_calls:
                # 有 tool_calls 时 content 是思考过程，记录到 think 面板
                try:
                    from agent.history.tool_call_recorder import record_reflection_live, get_current_session
                    sid = get_current_session()
                    if sid:
                        record_reflection_live(sid, response_content.strip())
                except Exception:
                    pass

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tc_normalized = normalize_tool_call(tc)
                tool_name = tc_normalized.get("name", "unknown")
                tool_args = tc_normalized.get("args", {})
                try:
                    from agent.history.tool_call_recorder import record_tool_call_live, get_current_session
                    sid = get_current_session()
                    if sid:
                        record_tool_call_live(sid, tool_name, tool_args)
                        if tool_name == "todo_list":
                            try:
                                from agent.tools.todo_list import update_todo_store_from_tool_args
                                update_todo_store_from_tool_args(sid, tool_args)
                            except Exception:
                                pass
                except Exception:
                    pass

        return {"messages": [response]}

    return call_model


def process_tool_artifact(state: AgentState) -> dict:
    last_msg = state["messages"][-1]

    # ---- 实时记录工具结果到前端 ----
    # 处理尾部所有连续的 ToolMessage（并行工具调用时会有多条），
    # record_tool_result_live 对已 done 的记录是幂等的，不会重复标记
    try:
        from agent.history.tool_call_recorder import record_tool_result_live, get_current_session
        sid = get_current_session()
        if sid:
            # 从末尾向前收集连续的 ToolMessage
            trailing = []
            for msg in reversed(state["messages"]):
                if not isinstance(msg, ToolMessage):
                    break
                trailing.append(msg)
            # 按原始顺序处理（保证 record_tool_result_live 的 reverse 查找正确）
            for msg in reversed(trailing):
                record_tool_result_live(
                    sid,
                    msg.name or "unknown",
                    str(msg.content) if msg.content else "",
                    msg.artifact,
                )
    except Exception:
        pass

    if not isinstance(last_msg, ToolMessage) or not last_msg.artifact:
        return {}

    artifact = last_msg.artifact
    img_bytes_list: list[bytes] = []
    source_path = ""

    if isinstance(artifact, dict):
        if "image_bytes" in artifact:
            img_bytes_list.append(artifact["image_bytes"])
        if "images" in artifact and isinstance(artifact["images"], list):
            for item in artifact["images"]:
                if isinstance(item, bytes):
                    img_bytes_list.append(item)
                elif isinstance(item, dict) and "image_bytes" in item:
                    img_bytes_list.append(item["image_bytes"])
        source_path = artifact.get("file_path", "") or artifact.get("source_path", "")
    elif isinstance(artifact, list):
        for item in artifact:
            if isinstance(item, dict) and "image_bytes" in item:
                img_bytes_list.append(item["image_bytes"])
            elif isinstance(item, bytes):
                img_bytes_list.append(item)
    elif isinstance(artifact, bytes):
        img_bytes_list.append(artifact)

    if not img_bytes_list:
        return {}

    content_parts = []
    failed_count = 0
    for img_bytes in img_bytes_list:
        data_url = image_bytes_to_openai_image_url_part(img_bytes)
        if data_url is None:
            failed_count += 1
            continue
        content_parts.append(data_url)

    if not content_parts:
        human_msg = HumanMessage(
            content="工具返回了截图，但图片处理失败，请向用户说明。",
            additional_kwargs={"synthetic": True},
        )
        return {"messages": [human_msg]}

    content_parts.append({"type": "text", "text": "上面是工具返回的截图。" + (f"（来源：{source_path}）" if source_path else "")})
    if failed_count > 0:
        content_parts[-1]["text"] += f"（其中 {failed_count} 张图片处理失败，请忽略）"

    human_msg = HumanMessage(content=content_parts, additional_kwargs={"synthetic": True})
    return {"messages": [human_msg]}
