"""动态 Agent 工厂：根据 agent_config.json 全动态创建 AgentRuntime。

系统定位:
    实现从配置文件全动态加载 Agent 实例。所有 Agent 的运行参数（图类型、
    模型、工具集、系统提示词、最大迭代次数）均由 agent_config.json 驱动。
    同时提供 Web/API 层的入口函数 execute_agent 和 continue_after_human_action。

使用方式:
    from agent.agents.agent_runtime import get_main_agent_runtime, reload_all_agent_runtimes, execute_agent
    runtime = get_main_agent_runtime()
"""
from __future__ import annotations

from typing import Any, Literal

from agent.core.config_manager import load_agent_configs, load_models, AgentConfig
from agent.core.graph import build_agent_graph
from agent.core.runtime import continue_after_human_action as continue_runtime_after_human_action
from agent.core.runtime import execute_agent as execute_runtime_agent
from agent.core.runtime import AgentRuntime
from agent.tools import get_tools

AgentMode = Literal["agent", "plan", "cron"]

# ---------- 缓存 ----------
_all_agent_runtimes: dict[str, AgentRuntime] = {}
_main_agent_name: str = "main"


def _build_llm_for_agent(cfg: AgentConfig):
    """根据 Agent 配置中指定的 llm_model_id 构建 LLM 实例。

    从 env_config.json 的 models 列表中查找匹配的模型配置，
    用其参数构造 ChatQwen 实例。若未找到匹配模型则回退到环境变量默认值。
    """
    from agent.core.llm import ChatQwen

    models = load_models()
    model_config = None
    for m in models:
        if m.get("id") == cfg.llm_model_id:
            model_config = m
            break

    if model_config:
        # enable_thinking: true 时传入空 extra_body 恢复模型原生行为（启用思考）
        # 默认不传 extra_body，由 ChatQwen 使用禁用思考的默认值
        if model_config.get("enable_thinking"):
            extra_body = {}
        else:
            extra_body = None
        return ChatQwen(
            model=model_config.get("model", ""),
            api_key=model_config.get("api_key", ""),
            base_url=model_config.get("base_url", ""),
            timeout=float(model_config.get("timeout", 60)),
            max_retries=int(model_config.get("max_retries", 0)),
            extra_body=extra_body,
        )
    # 回退：使用环境变量中已加载的默认 LLM 配置
    from agent.core.llm import llm as _default_llm
    return ChatQwen(
        model=_default_llm.model_name,
        api_key=_default_llm.openai_api_key or "",
        base_url=_default_llm.openai_api_base or "",
    )


def _build_agent_runtime(cfg: AgentConfig) -> AgentRuntime:
    """根据单个 AgentConfig 构建 AgentRuntime 实例。

    输入:
        cfg: Agent 配置（name/graph/tools/llm_model_id/system_prompt/max_iterations）。

    输出:
        完整的 AgentRuntime 实例，可被 execute_agent 直接使用。
    """
    # 1. 构建 LLM
    agent_llm = _build_llm_for_agent(cfg)

    # 2. 获取所有可用工具并按配置过滤
    all_tools = get_tools()
    if cfg.tools:
        agent_tools = [t for t in all_tools if t.name in cfg.tools]
    else:
        agent_tools = all_tools

    # 2.1 强制为主 Agent 加载 doc_tool 与 todo_list（不可通过配置移除）
    #     doc_tool: 文档读写必需；todo_list: Plan 模式第一步规划必需
    if cfg.role == "main":
        for force_name in ("doc_tool", "todo_list"):
            if not any(t.name == force_name for t in agent_tools):
                for t in all_tools:
                    if t.name == force_name:
                        agent_tools.append(t)
                        break

    # 3. bind_tools
    model_with_tools = agent_llm.bind_tools(agent_tools, tool_choice="auto")

    # 4. 构建图
    graph = build_agent_graph(
        tools=agent_tools,
        model_with_tools=model_with_tools,
        trajectory_rounds=cfg.trajectory_rounds,
    )

    # 5. 组装 AgentRuntime
    return AgentRuntime(
        name=cfg.name,
        description=cfg.description,
        graph=graph,
        llm=agent_llm,
        tools=agent_tools,
        tools_by_name={tool.name: tool for tool in agent_tools},
        system_prompt=cfg.system_prompt,
        max_iterations=cfg.max_iterations,
        trajectory_rounds=cfg.trajectory_rounds,
    )


def _refresh_subagent_tool_description() -> None:
    """在运行时构建完成后刷新 CallSubAgentTool 的描述，使主 Agent 知晓可委派的子 Agent。

    通过传入 sub_names 和 sub_descriptions 参数避免从 agent_runtime 自身重新导入（循环导入）。
    在 build_all_agent_runtimes() 和 reload_all_agent_runtimes() 之后调用。
    """
    sub_names = []
    sub_descriptions = {}
    for name, rt in _all_agent_runtimes.items():
        if name != _main_agent_name:
            sub_names.append(name)
            if rt.description:
                sub_descriptions[name] = rt.description
    from agent.tools.agent_call import CallSubAgentTool
    main_rt = _all_agent_runtimes.get(_main_agent_name)
    if main_rt is None:
        return
    for tool in main_rt.tools:
        if isinstance(tool, CallSubAgentTool):
            tool._refresh_description(sub_names, sub_descriptions)
            break


def build_all_agent_runtimes() -> dict[str, AgentRuntime]:
    """从 agent_config.json 读取所有启用 Agent 并构建运行时字典。

    输出:
        {agent_name: AgentRuntime} 字典，其中第一个 role="main" 的为 main_agent。

    系统定位:
        启动时调用一次，构建全局运行时缓存。
    """
    global _all_agent_runtimes, _main_agent_name
    configs = load_agent_configs()
    _all_agent_runtimes = {}
    _main_agent_name = "main"

    for cfg in configs:
        if not cfg.enabled:
            continue
        try:
            runtime = _build_agent_runtime(cfg)
            _all_agent_runtimes[cfg.name] = runtime
            if cfg.role == "main":
                _main_agent_name = cfg.name
        except Exception as e:
            print(f"[AgentFactory] 构建 Agent '{cfg.name}' 失败: {e}")

    # 确保至少有一个 main agent
    if _main_agent_name not in _all_agent_runtimes and _all_agent_runtimes:
        first_name = next(iter(_all_agent_runtimes))
        _main_agent_name = first_name
        print(f"[AgentFactory] 未找到 role='main' 的 Agent，自动将 '{first_name}' 设为主 Agent。")

    # 所有子 Agent 就绪后，刷新 call_subagent 工具描述并重建主 Agent，
    # 使主 Agent bind_tools 时携带最新的子 Agent 列表与能力描述
    _refresh_subagent_tool_description()
    main_cfg = next((c for c in configs if c.enabled and c.role == "main"), None)
    if main_cfg:
        try:
            _all_agent_runtimes[_main_agent_name] = _build_agent_runtime(main_cfg)
        except Exception as e:
            print(f"[AgentFactory] 重建主 Agent '{_main_agent_name}' 失败: {e}")

    return _all_agent_runtimes


def get_main_agent_runtime() -> AgentRuntime | None:
    """获取当前配置中 role="main" 的 AgentRuntime。

    若运行时缓存为空则自动构建。
    """
    global _all_agent_runtimes
    if not _all_agent_runtimes:
        build_all_agent_runtimes()
    return _all_agent_runtimes.get(_main_agent_name)


def get_all_agent_runtimes() -> dict[str, AgentRuntime]:
    """获取所有已构建的 Agent 运行时字典。"""
    if not _all_agent_runtimes:
        build_all_agent_runtimes()
    return dict(_all_agent_runtimes)


def get_agent_runtime(name: str) -> AgentRuntime | None:
    """按名称获取指定 Agent 运行时。"""
    if not _all_agent_runtimes:
        build_all_agent_runtimes()
    return _all_agent_runtimes.get(name)


def reload_all_agent_runtimes() -> dict:
    """重新加载配置并重建所有 Agent 运行时，返回当前状态。

    输出:
        {"agents": [{"name": str, "tools_count": int, "max_iterations": int}, ...],
         "main_agent": str}
    """
    global _all_agent_runtimes, _main_agent_name
    _all_agent_runtimes.clear()
    build_all_agent_runtimes()

    # 同步更新模块级缓存引用
    global main_agent_runtime, agent_graph, tools, TOOLS_BY_NAME, llm
    main_rt = _all_agent_runtimes.get(_main_agent_name)
    if main_rt:
        main_agent_runtime = main_rt
        agent_graph = main_rt.graph
        tools = main_rt.tools
        TOOLS_BY_NAME = main_rt.tools_by_name
        llm = main_rt.llm

    # 刷新 CallSubAgentTool 描述
    _refresh_subagent_tool_description()

    agents_info = []
    for name, rt in _all_agent_runtimes.items():
        agents_info.append({
            "name": name,
            "description": rt.description,
            "tools_count": len(rt.tools),
            "max_iterations": rt.max_iterations,
        })

    return {
        "agents": agents_info,
        "main_agent": _main_agent_name,
    }


# ---------- Web/API 层入口 ----------

def execute_agent(
    chat_history: list[dict[str, Any]],
    session_id: str = "test",
    agent_mode: AgentMode = "agent",
) -> list[dict[str, Any]]:
    """Web/API 层入口：使用 main_agent 运行时处理用户新一轮输入。"""
    return execute_runtime_agent(
        runtime=main_agent_runtime,
        chat_history=chat_history,
        session_id=session_id,
        agent_mode=agent_mode,
    )


def continue_after_human_action(
    chat_history: list[dict[str, Any]],
    session_id: str,
    approval_id: str,
    decision: Literal["approve", "reject", "edit"],
    instruction: str | None = None,
) -> list[dict[str, Any]]:
    """Web/API 层入口：用户对待确认项决策后继续执行 main_agent。"""
    return continue_runtime_after_human_action(
        runtime=main_agent_runtime,
        chat_history=chat_history,
        session_id=session_id,
        approval_id=approval_id,
        decision=decision,
        instruction=instruction,
    )


# ---------- 首次导入时从配置构建主 Agent 运行时并缓存引用 ----------
_built = build_all_agent_runtimes()
main_agent_runtime = get_main_agent_runtime()
agent_graph = main_agent_runtime.graph
tools = main_agent_runtime.tools
TOOLS_BY_NAME = main_agent_runtime.tools_by_name
llm = main_agent_runtime.llm
