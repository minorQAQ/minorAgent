"""Agent 核心运行时包。

包含:
    - state / graph: LangGraph 状态与图拓扑
    - nodes / routing: 图节点与条件路由
    - runtime: 对外执行入口 execute_agent / continue_after_human_action
    - llm: ChatQwen 多模态网关
    - approvals: HITL 待确认管理（含 human_interaction 参数规范化）
    - tool_policy: 工具执行安全策略

系统定位:
    Agent 业务逻辑中枢，``agents`` 包在此之上组装具体 Agent 实例。

可扩展性:
    子 Agent 可复用本包组件，仅替换 tools、system_prompt 与 graph 变体。
"""
