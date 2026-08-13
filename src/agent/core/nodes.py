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
from agent.memory.system_prompt import SUB_AGENT_OOM_PROMPT
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
        - 保留所有 SystemMessage、HumanMessage（非合成）、AIMessage、ToolMessage
        - 仅 process_tool_artifact 生成的合成图片 HumanMessage 按 trajectory_rounds 裁剪
        - 只对实际包含图片截图的轮次计数，无截图的轮次跳过不计数
        - 上一/几轮的反思提示词（reflection 标记）不进入本轮上下文
        - 带 tool_calls 的历史 AIMessage 仅保留工具调用，content 中的思考文本不进入上下文
    """
    if trajectory_rounds <= 0:
        return list(messages)

    # 从后向前遍历，先标记哪些轮次包含图片截图
    # 一"轮"由一个 AIMessage（含 tool_calls）之后的消息（ToolMessage + synthetic HumanMessage）组成
    img_rounds_seen = 0
    kept_indices = set()

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]

        # 上一/几轮的反思提示词不进入本轮上下文（每次 agent 调用前会注入当轮反思）
        if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("reflection"):
            continue

        # 合成图片消息：仅保留最近 trajectory_rounds 轮（有图片的轮才计数）
        if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("synthetic") and _has_image_content(msg):
            if img_rounds_seen < trajectory_rounds:
                kept_indices.add(i)
            continue

        # 遇到 AIMessage（含 tool_calls）时，检查本轮是否有图片来决定是否增加计数
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            # 向后搜索本轮是否有截图（从该 AIMessage 到下一个 AIMessage 之间）
            has_image = False
            for j in range(i + 1, len(messages)):
                mj = messages[j]
                if isinstance(mj, AIMessage) and getattr(mj, "tool_calls", None):
                    break
                if isinstance(mj, HumanMessage) and mj.additional_kwargs.get("synthetic") and _has_image_content(mj):
                    has_image = True
                    break
            if has_image:
                img_rounds_seen += 1

        kept_indices.add(i)

    result = [messages[i] for i in sorted(kept_indices)]

    # 剥离历史模型思考文本：上一/几轮的思考不进入本轮上下文。
    # 带 tool_calls 的 AIMessage，其 content 仅是思维链，保留 tool_calls 即可
    # （思考内容已由 extract_reasoning_text 单独记录到前端 think 面板）。
    cleaned: list = []
    for m in result:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None) and getattr(m, "content", None):
            cleaned.append(m.model_copy(update={"content": ""}))
        else:
            cleaned.append(m)
    return cleaned


def _build_dynamic_tail_prompt(messages: list, session_id: str = "") -> str:
    """构建每轮追加到消息末尾的动态尾部提示（仅变化部分）。

    输入:
        messages: 当前消息列表（已过滤短期记忆），供循环检测使用。
        session_id: 会话 ID，供循环检测与 TodoList 状态重建使用。

    输出:
        动态尾部文本；无 TodoList 且无循环提醒时返回空串
        （此时不加任何占位提示，省 token）。

    系统定位:
        - 固定反思引导已移入系统提示词前缀（system_prompt._reflection_section），
          不再在节点中间构造固定提示；
        - 循环警告：思考关闭档位注入（Level 1 仅提醒，不强制终止）；
        - TodoList 状态：思考开/关均注入（事实状态，供模型跟踪计划进度）。
    """
    from agent.utils.env_utils import thinking_enabled

    parts: list[str] = []

    # 思考关闭：循环警告（Level 1 仅提醒，不强制终止）
    if not thinking_enabled():
        loop_warning = build_loop_reflection_prompt(messages, session_id)
        if loop_warning:
            parts.append(loop_warning)

    # TodoList 状态：思考开/关均注入（事实状态，供模型跟踪计划进度）
    try:
        from agent.tools.todo_list import get_todo_status_text
        todo_status = get_todo_status_text(session_id)
    except Exception:
        todo_status = ""
    if todo_status:
        parts.append(todo_status)

    return "\n\n".join(parts)


def _dynamic_tail_agent_key() -> str:
    """动态尾部长期记忆的 agent 键：主 Agent 为 "main"，子 Agent 用其名称。

    主/子 Agent 的动态尾部各自隔离，避免子 Agent 覆盖主 Agent 的长期记忆。
    """
    try:
        from agent.core.human_request import get_current_agent_name
        name = get_current_agent_name()
    except Exception:
        name = ""
    return "main" if name in ("", "__main__") else name


def _persist_dynamic_tail(session_id: str, text: str) -> None:
    """持久化当前轮动态尾部到 session_meta（长期记忆，供后续轮次注入查看）。"""
    if not session_id:
        return
    try:
        from agent.utils.agent_utils import update_session_dynamic_tail
        update_session_dynamic_tail(session_id, _dynamic_tail_agent_key(), text)
    except Exception:
        pass


def _load_dynamic_tail_history(session_id: str) -> list[str]:
    """读取当前 Agent 的动态尾部长期记忆历史（时间正序，最新在末尾）。"""
    if not session_id:
        return []
    try:
        from agent.utils.agent_utils import get_session_dynamic_tail_history
        return get_session_dynamic_tail_history(session_id, _dynamic_tail_agent_key())
    except Exception:
        return []


# ---------- ReAct 循环内上下文压缩 ----------
def _extract_usage(response: Any) -> dict:
    """从模型 response 提取完整 usage 字典（prompt_tokens/completion_tokens/total_tokens）。"""
    usage = None
    if hasattr(response, "response_metadata"):
        meta = response.response_metadata
        if isinstance(meta, dict):
            usage = meta.get("token_usage", {})
    if not usage and hasattr(response, "usage_metadata"):
        meta = response.usage_metadata
        if isinstance(meta, dict):
            usage = meta
    return usage if isinstance(usage, dict) else {}


def _extract_total_tokens(response: Any) -> int:
    """从模型 response 中提取 total_tokens。"""
    return _extract_usage(response).get("total_tokens", 0) or 0


def _estimate_token_breakdown(messages: list[Any], usage: dict) -> dict[str, float]:
    """估算三类上下文的 token 占用（按输入字符占比分摊 prompt_tokens）。

    分类规则:
        system —— SystemMessage（系统提示词、压缩摘要）
        tools  —— ToolMessage 与含 tool_ctx 的历史工具调用 HumanMessage
        messages—— 其余（用户/助手对话），另计入 completion_tokens

    说明: LLM API 不返回按来源分类的 token 数，此值为字符占比估算，
    仅用于前端环形指示的占比展示。
    """
    sys_chars = tool_chars = msg_chars = 0
    for m in messages or []:
        text = str(getattr(m, "content", "") or "")
        if isinstance(m, SystemMessage):
            sys_chars += len(text)
        elif isinstance(m, ToolMessage) or (
            isinstance(m, HumanMessage) and (m.additional_kwargs or {}).get("tool_ctx")
        ):
            tool_chars += len(text)
        else:
            msg_chars += len(text)
    total_chars = sys_chars + tool_chars + msg_chars
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    if total_chars <= 0:
        return {"messages": float(completion_tokens), "tools": 0.0, "system": 0.0}

    def _share(chars: int) -> float:
        return round(prompt_tokens * chars / total_chars, 1)

    return {
        "messages": round(_share(msg_chars) + completion_tokens, 1),
        "tools": _share(tool_chars),
        "system": _share(sys_chars),
    }


def _compute_next_cursor(session_id: str) -> int:
    """计算下一次压缩游标：当前轮次起点在全局工具调用序列中的索引。

    触发压缩时当前 turn 尚未持久化（save_turn 在图执行结束后才调用），
    因此游标 = 当前 turn 之前所有已完成轮次的工具调用总数。
    游标之前的工具调用历史已包含在压缩摘要中，注入上下文时跳过。
    """
    try:
        from agent.history.tool_call_recorder import list_turns
        turns = list_turns(session_id, limit=100000)
        return sum(len(t.get("tool_calls") or []) for t in turns)
    except Exception:
        return -1


def _maybe_trigger_compress(response: Any, messages: list[Any] | None = None, model_name: str = "") -> tuple[str, int, int]:
    """根据 LLM 返回的 token 用量判断下一步动作。

    返回值 (trigger, total_tokens, threshold):
        "none"    —— 未达阈值，无需处理。
        "compress"—— 主 Agent 达到阈值，标记压缩，由 compress 节点统一执行。
        "sub_oom" —— 子 Agent 达到阈值（子 Agent 不压缩），由 agent 节点注入
                     整理提示词，让子 Agent 整理任务进度直接返回主 Agent。

    同时将 total_tokens 与估算的三类占比（消息/工具/系统提示词）存入
    tool_call_recorder 供前端环形指示展示（仅主 Agent），并累加进全局
    usage_stats（跨会话按小时/模型聚合，供欢迎区活跃度矩阵展示）。
    """
    total = _extract_total_tokens(response)
    if total <= 0:
        return ("none", 0, 0)

    # 存储最新 token 用量供前端轮询（仅统计主 Agent，子 Agent 上下文不计入）
    is_sub = False
    try:
        from agent.history.tool_call_recorder import get_current_session, is_sub_agent_context, set_session_tokens
        _sid = get_current_session() or ""
        is_sub = is_sub_agent_context()
        if _sid and not is_sub:
            breakdown = _estimate_token_breakdown(messages or [], _extract_usage(response))
            set_session_tokens(_sid, total, breakdown=breakdown)
            # 全局用量统计（跨会话累加，按小时 + 模型维度）
            try:
                from agent.core.usage_stats import record_usage
                record_usage(total, model=model_name)
            except Exception:
                pass
    except Exception:
        pass

    from agent.utils.env_utils import LLM_CONTEXT_WINDOW, COMPRESS_RATE
    threshold = int(LLM_CONTEXT_WINDOW * COMPRESS_RATE)
    if total <= threshold:
        return ("none", total, threshold)
    if is_sub:
        return ("sub_oom", total, threshold)
    return ("compress", total, threshold)


COMPRESSED_SUMMARY_PREFIX = "【历史工具调用摘要】"
COMPRESSED_SUMMARY_MSG_ID = "compressed_summary"


def maybe_compress_context(state: AgentState) -> dict:
    """上下文压缩节点：位于 process_tool_artifact 之后、agent 之前。

    当 agent 节点检测到 token 超阈值（state["_need_compress"]=True）时，
    将上下文中注入的"历史工具调用与返回值"压缩为摘要（系统提示词、对话历史
    均不压缩），更新压缩游标，并通过 RemoveMessage 移除已被摘要覆盖的历史工具
    调用消息，替换为累积摘要 SystemMessage。

    输出:
        {"messages": [RemoveMessage..., 摘要 SystemMessage], "_need_compress": False}
    """
    if not state.get("_need_compress"):
        return {}

    # 子 Agent 不做压缩（超限时已在 agent 节点直接报错）
    sid = ""
    try:
        from agent.history.tool_call_recorder import get_current_session, is_sub_agent_context
        if is_sub_agent_context():
            return {"_need_compress": False}
        sid = get_current_session() or ""
    except Exception:
        return {"_need_compress": False}

    messages = list(state["messages"])
    ctx_msgs = [
        m for m in messages
        if isinstance(m, HumanMessage) and (m.additional_kwargs or {}).get("tool_ctx")
    ]
    if not ctx_msgs:
        return {"_need_compress": False}

    compress_text = "\n".join(
        str(getattr(m, "content", "") or "").strip() for m in ctx_msgs
    ).strip()
    if not compress_text:
        return {"_need_compress": False}

    before_len = len(messages)

    # SSE 通知前端：压缩开始
    try:
        from agent.history.tool_call_recorder import record_tool_call_live
        if sid:
            record_tool_call_live(sid, "summarizer", {
                "action": "上下文压缩中",
                "before_messages": before_len,
            })
    except Exception:
        pass

    try:
        from agent.core.llm import get_default_llm
        from agent.utils.agent_utils import get_session_meta, summarize_chat_text, update_session_meta

        summary_text = summarize_chat_text(get_default_llm(), compress_text)

        # 累积压缩摘要并更新压缩游标（游标前历史已被摘要覆盖）
        if sid:
            meta = get_session_meta(sid, "main")
            old_content = meta.get("compressed_content") or ""
            new_content = (old_content + "\n\n" + summary_text).strip() if old_content else summary_text
            cursor = _compute_next_cursor(sid)
            update_session_meta(sid, "main", cursor, new_content)
        else:
            new_content = summary_text

        # 通过 RemoveMessage 移除已被摘要覆盖的历史工具调用消息，
        # 并以固定 id 插入最新累积摘要（同 id 消息会被替换而非追加）
        from langgraph.graph.message import RemoveMessage
        updates: list = [
            RemoveMessage(id=m.id)
            for m in ctx_msgs
            if getattr(m, "id", None)
        ]
        updates.append(SystemMessage(
            content=f"{COMPRESSED_SUMMARY_PREFIX}\n{new_content}",
            id=COMPRESSED_SUMMARY_MSG_ID,
        ))

        # SSE 通知前端：压缩完成
        try:
            from agent.history.tool_call_recorder import record_tool_result_live
            if sid:
                record_tool_result_live(sid, "summarizer",
                    f"压缩完成: 压缩 {len(ctx_msgs)} 条历史工具调用消息")
        except Exception:
            pass
        return {"messages": updates, "_need_compress": False}
    except Exception as e:
        # SSE 通知前端：压缩失败
        try:
            from agent.history.tool_call_recorder import record_tool_result_live
            if sid:
                record_tool_result_live(sid, "summarizer",
                    f"压缩失败: {str(e)}")
        except Exception:
            pass
        return {"_need_compress": False}


def make_call_model_node(
    model_with_tools: Any,
    trajectory_rounds: int = 3,
) -> Callable[[AgentState], dict]:
    """创建带按思考档位注入提示 + 上下文中压缩的调用已绑定工具的 LLM 的图节点闭包。

    每次调用 LLM 前按思考档位注入提示（思考关闭：反思引导 + TodoList 状态 +
    循环警告；思考开启：仅 TodoList 状态）；调用后提取模型产出的思考/反思内容
    （思考开启取深度思考，思考关闭取一句话反思），记录到 think store，
    供前端实时展示思维链。

    在每次 LLM 调用后，根据 response 的 ``usage_metadata.total_tokens`` 判断
    是否触发消息列表就地压缩——确保 ReAct 循环中的上下文永不溢出。
    """

    def call_model(state: AgentState) -> dict:
        all_messages = list(state["messages"])

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

        # 获取 session_id 供循环检测使用
        try:
            from agent.history.tool_call_recorder import get_current_session
            _sid = get_current_session()
        except Exception:
            _sid = ""

        # 构建动态尾部提示并注入到消息列表末尾（仅作引导，不记录到前端）。
        # 固定反思引导已并入系统提示词前缀，此处仅注入变化部分：
        # TodoList 状态与循环提醒；无 TodoList 且无循环提醒时不注入（省 token）。
        messages_for_llm = list(filtered_messages)
        tail = _build_dynamic_tail_prompt(filtered_messages, _sid)
        if tail:
            # 长期记忆：持久化本轮动态尾部，供后续轮次注入查看
            _persist_dynamic_tail(_sid, tail)
            # 注入全部历史动态尾部（含本轮），使 Agent 能看到之前所有轮的
            # todo 状态与循环提醒；这些消息仅存在于本次调用，不进图状态。
            for hist_text in _load_dynamic_tail_history(_sid):
                messages_for_llm.append(HumanMessage(
                    content=hist_text,
                    additional_kwargs={"synthetic": True, "reflection": True},
                ))

        response = model_with_tools.invoke(messages_for_llm)

        # 模型名（用于全局用量统计按模型分账）
        model_name = ""
        try:
            model_name = str(getattr(getattr(model_with_tools, "bound", None), "model_name", "") or "")
        except Exception:
            pass

        # 基于模型返回 token 用量判断：主 Agent 标记压缩 / 子 Agent 超限整理。
        # total_tokens 同时存入 session_tokens 供前端轮询（仅主 Agent）。
        trigger, _total, _threshold = _maybe_trigger_compress(response, messages_for_llm, model_name)
        if trigger == "sub_oom":
            # 子 Agent 不压缩：注入整理提示词重新调用，让模型整理任务进度直接
            # 返回主 Agent（提示词内附 OOM 溢出信息）。
            oom_msg = HumanMessage(
                content=SUB_AGENT_OOM_PROMPT.format(total_tokens=_total, threshold=_threshold),
                additional_kwargs={"synthetic": True, "reflection": True},
            )
            response = model_with_tools.invoke(list(messages_for_llm) + [oom_msg])
            # 剥离工具调用：确保子 Agent 以文字整理结果结束，不再进入工具循环
            if getattr(response, "tool_calls", None):
                response = AIMessage(content=getattr(response, "content", "") or "（子Agent上下文超限，已完成任务整理）")
            need_compress = False
        else:
            need_compress = (trigger == "compress")
        state["_need_compress"] = need_compress

        # 提取模型产出的思考/反思内容，记录到前端 think 面板与后端记录
        # - 思考关闭：模型在反思提示引导下输出的 content（一句话反思）
        # - 思考开启：深度思考（additional_kwargs.reasoning_content 或内联 <think> 块，
        #   由 _create_chat_result 归一化到 reasoning_content）
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
                        # 记录工具调用 ID：并行 call_subagent 按 id 匹配注入子轨迹
                        record_tool_call_live(sid, tool_name, tool_args, tc_normalized.get("id", ""))
                except Exception:
                    pass

        return {"messages": [response], "_need_compress": need_compress}

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
