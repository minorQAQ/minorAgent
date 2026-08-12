"""LangGraph 条件路由：工具循环 vs 结束。

系统定位:
    连接 ``graph`` 的条件边，在模型输出 tool_calls 时决定图走向。
    人工确认不再由图级暂停承接：confirm 工具 / human_interaction 均为
    阻塞式普通工具，在 ``tool_call_utils.invoke_tool_and_build_message``
    钳点处阻塞等待用户决策，图自然继续。

可扩展性:
    - ``should_continue`` 可扩展为多目标路由（如专用 RAG 节点）。
"""
from __future__ import annotations

from typing import Literal

from langgraph.graph import END

from agent.core.state import AgentState
from agent.core.loop_detector import should_force_end as _loop_should_force_end


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """根据最后一条 AI 消息中的 tool_calls 决定下一节点。

    输入:
        state: 含 messages 的 AgentState。

    输出:
        ``"tools"`` 进入 ToolNode；``"__end__"`` 结束图（无待执行工具调用、
        循环检测强制终止）。

    系统定位:
        ``graph`` 中 agent 节点的 conditional_edges 路由函数。
        若检测到死循环（连续相同工具调用超阈值），则强制 END。

    可扩展性:
        可先执行 direct 类工具、仅对 confirm 类暂停（需拆分 tool_calls 处理）。
    """
    last_msg = state["messages"][-1]

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        # 循环检测 Level 2：连续相同工具调用超过 END 阈值 → 强制终止
        messages = state["messages"]
        try:
            from agent.history.tool_call_recorder import get_current_session
            _sid = get_current_session()
        except Exception:
            _sid = ""
        force_end, loop_tool, loop_args = _loop_should_force_end(messages, _sid)
        if force_end:
            return END
        return "tools"
    return END
