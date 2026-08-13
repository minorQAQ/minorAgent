"""Agent 核心运行时包。

包含:
    - state / graph: LangGraph 状态与图拓扑
    - nodes / routing: 图节点与条件路由
    - runtime: 对外执行入口 execute_agent
    - human_request: 人工请求注册表（交互类工具的通用阻塞通道）
    - turn_runner: 后台线程轮次执行器
    - llm: Multimodel_LLM 多模态网关
    - tool_policy: 工具执行安全策略

系统定位:
    Agent 业务逻辑中枢，``agents`` 包在此之上组装具体 Agent 实例。

可扩展性:
    子 Agent 可复用本包组件，仅替换 tools、system_prompt 与 graph 变体。
"""
