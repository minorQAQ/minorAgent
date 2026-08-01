"""LangGraph 工作流图构建。

系统定位:
    将 LLM（已 bind_tools）、工具列表组装为可编译的 StateGraph，
    供 ``agents/agent`` 及各子 Agent 的 ``AgentRuntime`` 使用。

图结构:
    react:  START -> agent -> (tools | END)
           tools -> process_tool_artifact -> agent

可扩展性:
    - 可增加 checkpoint、interrupt 节点、子图路由。
    - 可为不同 Agent 注入不同的 conditional_edges 或额外节点（如 RAG 检索）。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agent.core.nodes import make_call_model_node, process_tool_artifact
from agent.core.routing import should_continue
from agent.core.state import AgentState


def build_agent_graph(tools: list[Any], model_with_tools: Any, trajectory_rounds: int = 3):
    """构建并编译标准 ReAct Agent 图。

    输入:
        tools: LangChain BaseTool 列表，供工具节点执行。
        model_with_tools: 已 ``bind_tools`` 的聊天模型，供 agent 节点调用。
        trajectory_rounds: 短期记忆保留最近 N 轮工具返回结果，默认 3。

    输出:
        编译后的 LangGraph CompiledGraph，支持 ``invoke({"messages": ...})``。

    系统定位:
        默认图类型 "react"，供各 Agent 使用。
        工具执行节点统一使用 make_parallel_tool_node：线程池并行执行同一轮的
        多个 tool_call（含子 Agent 并行），单个 tool_call 时跳过线程池直接执行。

    可扩展性:
        返回前可 ``workflow.compile(checkpointer=...)`` 启用持久化；
        可参数化节点名以支持多 Agent 图合并。
    """
    from agent.tools.agent_call import make_parallel_tool_node

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", make_call_model_node(model_with_tools, trajectory_rounds=trajectory_rounds))

    # 工具执行节点：线程池并行执行（含子 Agent 并行）
    workflow.add_node("tools", make_parallel_tool_node(tools))

    workflow.add_node("process_tool_artifact", process_tool_artifact)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "process_tool_artifact")
    workflow.add_edge("process_tool_artifact", "agent")
    return workflow.compile()
