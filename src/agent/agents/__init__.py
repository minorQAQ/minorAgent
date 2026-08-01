"""Agent 实例注册包。

系统定位:
    对外导出各 Agent 的 ``AgentRuntime`` 单例。
    所有 Agent 实例均从 ``agent_config.json`` 动态构建，不再 hardcoded。
    主 Agent 通过 ``CallSubAgentTool`` 以工具委派方式调用子 Agent，
    子 Agent 各自运行独立的单 Agent ReAct 图。

Agent 列表:
    - main_agent_runtime: 主 Agent 运行时（从配置中 role="main" 的 agent 动态创建）。
    - reload_all_agent_runtimes: 重新加载配置并重建所有 Agent 运行时。

可扩展性:
    新增 Agent 只需在 agent_config.json 中添加配置项，无需编写 .py 文件。
"""
from agent.agents.agent_runtime import (
    build_all_agent_runtimes,
    get_main_agent_runtime,
    get_all_agent_runtimes,
    get_agent_runtime,
    reload_all_agent_runtimes,
    execute_agent,
    continue_after_human_action,
    main_agent_runtime,
    AgentMode,
)

reload_main_agent_runtime = reload_all_agent_runtimes  # 向后兼容别名

__all__ = [
    "main_agent_runtime",
    "reload_main_agent_runtime",
    "reload_all_agent_runtimes",
    "build_all_agent_runtimes",
    "get_main_agent_runtime",
    "get_all_agent_runtimes",
    "get_agent_runtime",
    "execute_agent",
    "continue_after_human_action",
    "AgentMode",
]
