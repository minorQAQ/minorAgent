"""LangGraph 状态类型定义。

系统定位:
    定义图运行时共享状态 ``AgentState``，被 ``graph``、``nodes``、
    ``routing`` 作为 StateGraph 的 schema 使用。

可扩展性:
    - 可在此增加 ``session_id``、``pending_approval`` 等字段，
      需配合 reducer（如 add_messages）声明合并策略。
"""
from __future__ import annotations

from typing import Annotated, Literal, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph 图状态。

    字段:
        messages: 对话消息序列，通过 ``add_messages`` 追加合并。
        agent_mode: 运行模式 — "agent"（标准）| "plan"（先规划再执行）| "cron"（定时任务无人值守）。

    系统定位:
        ReAct 循环（agent -> tools -> process_tool_artifact -> agent）的载体。

    可扩展性:
        扩展字段时保持 TypedDict 与 reducer 注解一致，避免并发更新冲突。
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    agent_mode: str  # "agent" | "plan"
