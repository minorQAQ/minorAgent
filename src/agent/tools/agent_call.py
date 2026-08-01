"""Agent 委派工具：主 Agent 通过 call_subagent 工具将任务委派给子 Agent 执行。

系统定位:
    封装在 ReAct 图的工具集中，使主 Agent 可以像调用普通工具一样
    调用子 Agent 执行子任务。支持一轮中发起多个 call_subagent 调用，
    结合并行 ToolNode 实现子 Agent 并行执行。

工具签名:
    call_subagent(agent_name, task_description) -> str

并行说明:
    将主 agent 图的 ToolNode 替换为 parallel_tool_node（本模块提供），
    即可在一次 LLM 响应中的多个 call_subagent 被并行执行。
"""
from __future__ import annotations

import concurrent.futures
from typing import Any

from langchain.tools import BaseTool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.core.state import AgentState
from agent.utils.tool_call_utils import invoke_tool_and_build_message


class SubAgentPendingError(Exception):
    """子 Agent 执行中遇到 HITL/确认工具时抛出，冒泡到主图捕获。

    携带 pending_meta（含 approval_id）与 agent_name；
    main_messages / main_tool_call_id 由 parallel_tool_node 捕获时填充，
    供主图在用户确认/跳过后恢复执行。
    """

    def __init__(self, pending_meta: dict, agent_name: str = ""):
        super().__init__(f"sub-agent '{agent_name}' pending human action")
        self.pending_meta = pending_meta
        self.agent_name = agent_name
        self.main_messages = None       # 由 parallel_tool_node 填充：主图消息快照
        self.main_tool_call_id = None   # 由 parallel_tool_node 填充：call_subagent 的 tool_call_id


class CallSubAgentInput(BaseModel):
    """call_subagent 工具的输入参数。"""
    agent_name: str = Field(
        description="要调用的子 Agent 名称。必须是 agent_config.json 中已启用且 role='sub' 的 Agent。"
    )
    task_description: str = Field(
        description="委派给子 Agent 的详细任务描述，子 Agent 将根据此描述独立执行任务。"
    )


class CallSubAgentTool(BaseTool):
    """主 Agent 调用子 Agent 执行任务的工具。

    调用后直接运行子 Agent 的编译图，返回最终结果。
    子 Agent 拥有独立的 system_prompt、工具集和 LLM，完全独立执行。
    可用的子 Agent 列表在工具实例化时从已注册的 AgentRuntime 中动态获取。
    """

    args_schema: type[BaseModel] = CallSubAgentInput
    name: str = "call_subagent"
    description: str = (
        "调用一个已启用的子 Agent 执行指定任务。"
        "子 Agent 会独立运行并返回最终结果。"
        "适用于需要专业能力（如代码分析、文档处理等）进行辅助的场景。"
        "可用子 Agent: {available_agents}"
    )

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._description_refreshed = False
        # 不在 __init__ 中调用 _refresh_description()，避免循环导入
        # 描述在首次 _run 时延迟刷新

    def _refresh_description(self, sub_names: list[str] | None = None, sub_descriptions: dict[str, str] | None = None) -> None:
        """根据当前已注册的子 Agent 动态更新工具描述，使主 Agent 能知晓可委派的目标。

        Args:
            sub_names: 可选，直接传入子 Agent 名称列表（避免模块加载时的循环导入）。
                       为 None 时从 agent_runtime 动态查询。
            sub_descriptions: 可选，子 Agent 名称到能力描述的映射。
        """
        if sub_names is None:
            from agent.agents.agent_runtime import get_all_agent_runtimes, get_main_agent_runtime
            try:
                all_rt = get_all_agent_runtimes()
                main_rt = get_main_agent_runtime()
                sub_names = [name for name in all_rt if main_rt is None or all_rt[name] is not main_rt]
                sub_descriptions = {}
                for name in sub_names:
                    desc = all_rt[name].description
                    if desc:
                        sub_descriptions[name] = desc
            except Exception:
                sub_names = []
                sub_descriptions = {}

        if sub_descriptions is None:
            sub_descriptions = {}

        if sub_names:
            desc_lines = [
                "调用一个已启用的子 Agent 执行指定任务。"
                "子 Agent 会独立运行并返回最终结果。"
                '参数 agent_name 必须是以下子 Agent 之一: ' + ", ".join(sub_names) + "。"
            ]
            desc_lines.append("各子 Agent 能力说明:")
            for name in sub_names:
                if name in sub_descriptions and sub_descriptions[name]:
                    desc_lines.append(f"  - {name}: {sub_descriptions[name]}")
                else:
                    desc_lines.append(f"  - {name}")
            desc_lines.append("参数 task_description 为需要子 Agent 执行的详细任务描述。")
            desc = " ".join(desc_lines)
        else:
            desc = (
                "调用子 Agent 执行任务。当前没有可用的子 Agent，"
                "请在 agent_config.json 中启用 role='sub' 的 Agent。"
            )
        if self.description != desc:
            object.__setattr__(self, "description", desc)

    def _get_sub_agent_runtime(self, agent_name: str):
        """查找并返回已启用的子 Agent 运行时。"""
        from agent.agents.agent_runtime import get_agent_runtime, get_main_agent_runtime
        runtime = get_agent_runtime(agent_name)
        if runtime is None:
            available = []
            from agent.agents.agent_runtime import get_all_agent_runtimes
            all_rt = get_all_agent_runtimes()
            for name, rt in all_rt.items():
                main_rt = get_main_agent_runtime()
                if main_rt and rt is not main_rt:
                    available.append(name)
            raise ValueError(
                f"子 Agent '{agent_name}' 未找到或未启用。"
                f"当前可用的子 Agent: {available if available else '无'}"
            )
        # 确保不是主 agent 自己调自己
        main_rt = get_main_agent_runtime()
        if main_rt and runtime is main_rt:
            raise ValueError(f"不能委派任务给主 Agent 自身 '{agent_name}'")
        return runtime

    def _run(self, agent_name: str, task_description: str) -> str:
        """同步执行子 Agent 任务并返回结果。同时记录子 Agent 轨迹供前端嵌套展开。"""
        # 延迟刷新：首次调用时才加载子 Agent 列表（避免循环导入）
        if not self._description_refreshed:
            self._refresh_description()
            self._description_refreshed = True
        try:
            runtime = self._get_sub_agent_runtime(agent_name)
        except ValueError as e:
            return f"call_subagent 失败: {e}"

        # 构建子 Agent 的输入消息（记忆隔离）
        messages = [
            SystemMessage(content=runtime.system_prompt),
            HumanMessage(content=task_description),
        ]

        config = {"recursion_limit": runtime.max_iterations}

        # 设置子 Agent 上下文：TodoList 按 agent 隔离时使用子 Agent 名称
        from agent.tools.todo_list import set_current_agent_name
        set_current_agent_name(agent_name)
        # 进入子 Agent 执行上下文：抑制其 record_*_live 调用，
        # 避免子 Agent 的思考/工具调用混入主 Agent 的实时列表。
        # 子 Agent 轨迹仍由 _record_sub_trace 独立存档，持久化时嵌套注入。
        from agent.history.tool_call_recorder import sub_agent_context
        try:
            with sub_agent_context():
                result = runtime.graph.invoke({"messages": messages}, config=config)
            all_messages = result.get("messages", [])

            # 提取子 Agent 工具调用轨迹 → 存档供前端嵌套展开
            _record_sub_trace(agent_name, all_messages)

            # ===== 子 Agent HITL 冒泡检测（Part 2）=====
            # 子图在 confirm/human_interaction 工具处会 END；检测是否产生 pending，
            # 若有则向 PENDING_TOOL_APPROVALS 打 agent_name 标记并抛 SubAgentPendingError，
            # 由主图捕获后弹窗（前端按 agent_name 分组显示）。
            from agent.history.tool_call_recorder import get_current_session
            sub_session_id = get_current_session() or ""
            sub_pending_meta = _detect_sub_pending(all_messages, sub_session_id, runtime, agent_name)
            if sub_pending_meta is not None:
                # 抛出前还原主 Agent 上下文（finally 会再次还原，此处冗余但安全）
                raise SubAgentPendingError(sub_pending_meta, agent_name)

            # 提取最后一条非工具调用的助手消息作为最终结果
            from langchain_core.messages import AIMessage
            final_text = ""
            for msg in reversed(all_messages):
                if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                    content = msg.content
                    if isinstance(content, str):
                        final_text = content
                        break
                    elif isinstance(content, list):
                        text_parts = [
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        final_text = "\n".join(text_parts)
                        break

            if not final_text:
                final_text = "子 Agent 已完成任务但未返回文字结果。"

            return f"[子Agent: {agent_name}] 执行结果:\n{final_text}"

        except SubAgentPendingError:
            raise
        except Exception as e:
            return f"[子Agent: {agent_name}] 执行出错: {str(e)}"
        finally:
            # 还原主 Agent 上下文
            set_current_agent_name("__main__")

    async def _arun(self, agent_name: str, task_description: str) -> str:
        """异步执行（委托给同步实现）。"""
        import asyncio
        return await asyncio.to_thread(self._run, agent_name, task_description)


# ---------- 子 Agent 轨迹记录 ----------
def _detect_sub_pending(all_messages: list, session_id: str, runtime: Any, agent_name: str) -> dict | None:
    """检测子 Agent 图是否在 confirm/human_interaction 处暂停。

    若是，向 PENDING_TOOL_APPROVALS 对应条目打 agent_name/is_sub_agent 标记，
    并附加 sub_runtime/sub_messages（原始 BaseMessage 列表）供主图恢复时使用。
    返回 pending_meta 或 None。
    """
    try:
        from agent.core.routing import first_pending_tool_meta
        from agent.core.approvals import PENDING_TOOL_APPROVALS
        meta = first_pending_tool_meta(all_messages, session_id)
        if not meta:
            return None
        pending_action = meta.get("pending_action") or {}
        approval_id = pending_action.get("id")
        if approval_id and approval_id in PENDING_TOOL_APPROVALS:
            entry = PENDING_TOOL_APPROVALS[approval_id]
            entry["agent_name"] = agent_name
            entry["is_sub_agent"] = True
            entry["sub_runtime"] = runtime
            entry["sub_messages"] = list(all_messages)  # 原始 BaseMessage 列表，供恢复
        return meta
    except SubAgentPendingError:
        raise
    except Exception:
        return None


def _record_sub_trace(agent_name: str, messages: list) -> None:
    """记录子 Agent 的工具调用轨迹，供前端嵌套展开。

    同时写入 tool_call_recorder 的 session/turn 作用域存储。
    """

    # 桥接到 tool_call_recorder（按 session/turn 作用域）
    try:
        from agent.history.tool_call_recorder import (
            record_sub_agent_trace as _recorder_record,
            extract_tool_calls_from_messages as _recorder_extract,
            get_current_session as _recorder_session,
            get_current_turn as _recorder_turn,
        )
        session_id = _recorder_session()
        turn_id = _recorder_turn()
        if session_id and turn_id:
            sub_tc = _recorder_extract(list(messages))
            _recorder_record(session_id, turn_id, agent_name, sub_tc)
    except Exception:
        pass


# ---------- 并行工具节点 ----------
def make_parallel_tool_node(tools: list[Any], max_workers: int = 5):
    """创建并行工具执行节点，替换 LangGraph 默认的 ToolNode。

    输入:
        tools: LangChain BaseTool 列表。
        max_workers: 线程池最大并发数。

    输出:
        LangGraph 节点函数（签名兼容 ToolNode）。

    系统定位:
        在 build_agent_graph 中替代 ToolNode，使一轮内的多个工具调用
        （包括多个 call_subagent）可以并行执行，显著提升多子 Agent 场景效率。

    可扩展性:
        可增加超时控制、错误隔离（单个工具失败不影响其他）。
    """

    # 构建工具名 → 工具实例的映射
    tools_by_name: dict[str, BaseTool] = {t.name: t for t in tools}

    def _execute_single(tool_name: str, tool_args: dict, tool_call_id: str = "") -> tuple[str, str, Any]:
        """在线程池中执行单个工具。

        委托 invoke_tool_and_build_message 统一处理返回类型。
        返回 (tool_name, content, artifact)，artifact 为 None 表示无产物。
        SubAgentPendingError 不被吞掉，向上冒泡到 parallel_tool_node。
        """
        tool = tools_by_name.get(tool_name)
        if tool is None:
            return tool_name, f"工具 '{tool_name}' 未找到", None
        try:
            content, artifact = invoke_tool_and_build_message(tool, tool_name, tool_args, tool_call_id)
            return tool_name, content, artifact
        except SubAgentPendingError:
            raise  # 子 Agent HITL 冒泡，主图需暂停
        except Exception as e:
            return tool_name, f"工具执行出错: {e}", None

    def parallel_tool_node(state: AgentState) -> dict:
        """并行执行最后一条 AIMessage 中的所有 tool_calls。"""
        from langchain_core.messages import AIMessage, ToolMessage

        last_msg = state["messages"][-1]
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return {}

        tool_calls = last_msg.tool_calls
        # 主图消息快照：若子 Agent 触发 HITL 冒泡，供主图恢复时使用
        main_messages_snapshot = list(state["messages"])

        # 只有 1 个工具调用时直接串行执行，避免线程开销
        if len(tool_calls) == 1:
            tc = tool_calls[0]
            tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
            try:
                name, content, artifact = _execute_single(tc_name, tc_args, tc_id)
            except SubAgentPendingError as e:
                e.main_messages = main_messages_snapshot
                e.main_tool_call_id = tc_id
                raise
            msg_kwargs = {"content": str(content), "tool_call_id": tc_id, "name": name}
            if artifact:
                msg_kwargs["artifact"] = artifact
            return {
                "messages": [ToolMessage(**msg_kwargs)]
            }

        # 多个工具调用：线程池并行执行
        futures: dict[concurrent.futures.Future, dict] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(tool_calls))) as executor:
            for tc in tool_calls:
                tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                future = executor.submit(_execute_single, tc_name, tc_args, tc_id)
                futures[future] = {"id": tc_id, "name": tc_name}

        # 收集结果，保持顺序
        tool_messages = []
        for tc in tool_calls:
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
            tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            # 查找对应 future 的结果（无法保持顺序时降级为错误）
            matched = False
            for future, meta in dict(futures).items():
                if meta["id"] == tc_id:
                    try:
                        _, content, artifact = future.result()
                    except SubAgentPendingError as e:
                        e.main_messages = main_messages_snapshot
                        e.main_tool_call_id = tc_id
                        raise
                    msg_kwargs = {"content": str(content), "tool_call_id": tc_id, "name": tc_name}
                    if artifact:
                        msg_kwargs["artifact"] = artifact
                    tool_messages.append(ToolMessage(**msg_kwargs))
                    matched = True
                    break
            if not matched:
                # 降级：尝试单次执行
                try:
                    name, content, artifact = _execute_single(tc_name, {}, tc_id)
                except SubAgentPendingError as e:
                    e.main_messages = main_messages_snapshot
                    e.main_tool_call_id = tc_id
                    raise
                msg_kwargs = {"content": str(content), "tool_call_id": tc_id, "name": tc_name}
                if artifact:
                    msg_kwargs["artifact"] = artifact
                tool_messages.append(ToolMessage(**msg_kwargs))

        return {"messages": tool_messages}

    return parallel_tool_node
