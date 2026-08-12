"""Agent 配置管理：从 JSON 文件加载/保存 agent、tool、env、model 配置。

系统定位:
    提供统一接口读写 ``agent/config/`` 下的 JSON 配置文件，
    使前端手动配置的 JSON 可以替代 core 底下的相应 .py 硬编码。

配置文件:
    agent_config.json  - Agent 运行时配置（名称、模型引用、工具列表、system_prompt）
    tool_config.json   - 工具权限与参数配置
    env_config.json    - 环境变量与 LLM 模型列表

可扩展性:
    可增加版本号、校验 schema、多环境配置切换。
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------- 配置文件路径 ----------
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
AGENT_CONFIG_PATH = _CONFIG_DIR / "agent_config.json"
TOOL_CONFIG_PATH = _CONFIG_DIR / "tool_config.json"
ENV_CONFIG_PATH = _CONFIG_DIR / "env_config.json"


# ---------- 模型配置 ----------
@dataclass
class ModelConfig:
    id: str = ""           # 唯一标识
    name: str = ""         # 显示名称
    api_key: str = ""
    base_url: str = ""
    model: str = ""        # API 模型名
    timeout: float = 60.0
    max_retries: int = 0


@dataclass
class AgentConfig:
    name: str = ""
    description: str = ""                                      # 简短能力描述，暴露给主Agent用于委派决策
    system_prompt: str = ""
    max_iterations: int = 200
    llm_model_id: str = ""                                     # 引用 env_config.json models 列表中的模型 ID
    tools: list[str] = field(default_factory=list)
    enabled: bool = True
    role: str = "sub"                                          # "main" | "sub"
    trajectory_rounds: int = 3                                 # 短期记忆：执行过程中保留最近 N 轮工具返回结果


@dataclass
class ToolConfig:
    name: str = ""
    display_name: str = ""
    description: str = ""
    permission: str = "confirm"                  # "direct" | "confirm"
    auto_execute_rules: list[dict] = field(default_factory=list)  # [{"parameter":"action","operator":"equals","value":"open"}, ...]
    enabled: bool = True
    timeout: float = 300.0                       # 工具执行超时（秒），超时后返回"工具执行超时"


# ---------- 通用 JSON 读写 ----------
def _read_json(path: Path) -> dict | list | None:
    """读取 JSON 文件，不存在或格式错误返回 None。"""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Any) -> bool:
    """写入 JSON 文件，成功返回 True。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ---------- Agent 配置 ----------
def _default_agent_config() -> list[dict]:
    """生成默认 agent 配置（单 agent: main）。"""
    from agent.memory.system_prompt import get_main_system_prompt
    from agent.tools import get_all_available_tool_names
    models = load_models()
    default_model_id = models[0]["id"] if models else ""
    return [
        {
            "name": "main",
            "system_prompt": get_main_system_prompt(),
            "max_iterations": 200,
            "llm_model_id": default_model_id,
            "tools": get_all_available_tool_names(),
            "enabled": True,
            "role": "main",
            "trajectory_rounds": 3,
        }
    ]


def load_agent_configs() -> list[AgentConfig]:
    """从 agent_config.json 加载 agent 配置列表，无文件时返回默认。

    对于 role='main' 的 Agent，system_prompt 始终从 get_main_system_prompt() 动态获取
    （忽略 JSON 中的静态值），确保提示词可热更新且包含正确的动态路径。
    对于 role='sub' 的 Agent，若未指定 system_prompt 则自动使用默认子 Agent 提示词。
    """
    from agent.memory.system_prompt import DEFAULT_SUB_AGENT_PROMPT, get_main_system_prompt
    raw = _read_json(AGENT_CONFIG_PATH)
    if not raw or not isinstance(raw, list):
        raw = _default_agent_config()
        _write_json(AGENT_CONFIG_PATH, raw)

    configs = []
    for item in raw:
        role = item.get("role", "sub")
        if role == "main":
            # main agent 始终从代码动态加载 system_prompt，保证热更新和动态路径正确
            system_prompt = get_main_system_prompt()
        else:
            system_prompt = item.get("system_prompt", "")
            # 子 Agent 未指定提示词时使用默认子 Agent 提示词
            if not system_prompt:
                system_prompt = DEFAULT_SUB_AGENT_PROMPT
        configs.append(AgentConfig(
            name=item.get("name", ""),
            description=item.get("description", ""),
            system_prompt=system_prompt,
            max_iterations=item.get("max_iterations", 200),
            llm_model_id=item.get("llm_model_id", ""),
            tools=item.get("tools", []),
            enabled=item.get("enabled", True),
            role=role,
            trajectory_rounds=item.get("trajectory_rounds", 3),
        ))
    return configs


def save_agent_configs(configs: list[dict]) -> bool:
    """将 agent 配置列表写入 agent_config.json。"""
    return _write_json(AGENT_CONFIG_PATH, configs)


# ---------- Tool 配置 ----------

# 各工具的默认 auto_execute_rules —— 与 tool_policy.py 的硬编码规则对应
_TOOL_DEFAULT_AUTO_RULES: dict[str, list[dict]] = {
    "browser_control": [
        {"parameter": "action", "operator": "equals", "value": "open"},
    ],
    "rag_tool": [
        {"parameter": "action_type", "operator": "equals", "value": "query"},
    ],
    "skill_router": [
        {"parameter": "query", "operator": "exists", "value": ""},
    ],
    "mail_tool": [
        {"parameter": "action", "operator": "equals", "value": "read"},
    ],
}


def _get_tool_parameters() -> dict[str, list[dict]]:
    """获取每个工具的参数名和类型信息，供前端生成 auto_execute_rules 提示。

    返回:
        {tool_name: [{"name": "action", "type": "Literal[open,close]"}, ...], ...}
    """
    from agent.tools import _ALL_AVAILABLE_TOOL_CLASSES
    import typing
    result: dict[str, list[dict]] = {}
    for name, cls in _ALL_AVAILABLE_TOOL_CLASSES.items():
        try:
            inst = cls()
            schema = getattr(inst, "args_schema", None)
            if schema is None:
                result[name] = []
                continue
            fields_info = getattr(schema, "model_fields", {})
            params = []
            for fname, finfo in fields_info.items():
                annotation = finfo.annotation
                type_str = str(annotation) if annotation is not None else "Any"
                # 简化 Literal 显示
                import re
                m = re.search(r"Literal\[(.+?)\]", type_str)
                if m:
                    type_str = "Literal[" + m.group(1) + "]"
                params.append({"name": fname, "type": type_str})
            result[name] = params
        except Exception:
            result[name] = []
    return result


def _default_tool_config() -> list[dict]:
    """根据所有可用工具生成默认 tool 配置。"""
    from agent.tools import get_all_available_tool_names, get_all_available_tool_descriptions
    from agent.core.tool_policy import classify_tool_execution
    all_names = get_all_available_tool_names()
    all_descriptions = get_all_available_tool_descriptions()
    result = []
    for tname in all_names:
        display_name, desc = all_descriptions.get(tname, (tname, ""))
        perm = classify_tool_execution(tname, {})
        default_rules = _TOOL_DEFAULT_AUTO_RULES.get(tname, [])
        result.append({
            "name": tname,
            "display_name": display_name,
            "description": desc,
            "permission": perm,
            "auto_execute_rules": default_rules,
            "enabled": True,
            "timeout": 300.0,
        })
    return result


def load_tool_configs() -> list[ToolConfig]:
    """从 tool_config.json 加载工具配置，无文件时返回默认；有新工具时自动补入。"""
    raw = _read_json(TOOL_CONFIG_PATH)
    if not raw or not isinstance(raw, list):
        raw = _default_tool_config()
        _write_json(TOOL_CONFIG_PATH, raw)

    # 补上代码中已注册但 JSON 中缺失的新工具
    registered = get_registered_tool_names()
    existing_names = {item.get("name", "") for item in raw}
    missing = [n for n in registered if n not in existing_names]
    if missing:
        defaults = {t["name"]: t for t in _default_tool_config()}
        for name in missing:
            if name in defaults:
                raw.append(defaults[name])
        _write_json(TOOL_CONFIG_PATH, raw)

    configs = []
    for item in raw:
        configs.append(ToolConfig(
            name=item.get("name", ""),
            display_name=item.get("display_name", ""),
            description=item.get("description", ""),
            permission=item.get("permission", "confirm"),
            auto_execute_rules=item.get("auto_execute_rules", []),
            enabled=item.get("enabled", True),
            timeout=float(item.get("timeout", 300.0)),
        ))
    return configs


def save_tool_configs(configs: list[dict]) -> bool:
    """将 tool 配置列表写入 tool_config.json。"""
    ok = _write_json(TOOL_CONFIG_PATH, configs)
    invalidate_tool_timeout_cache()  # 配置变更后清除超时缓存，确保新执行读到新超时
    return ok


# ---------- 工具超时缓存 ----------
DEFAULT_TOOL_TIMEOUT = 300.0
_tool_timeout_cache: dict[str, float] = {}
_tool_timeout_cache_lock = threading.Lock()


def get_tool_timeout(tool_name: str) -> float:
    """获取工具执行超时（秒），缓存 {tool_name: timeout}。

    未配置或查询失败返回 DEFAULT_TOOL_TIMEOUT（300）。
    供 invoke_tool_and_build_message 在执行工具前查询。
    """
    if not tool_name:
        return DEFAULT_TOOL_TIMEOUT
    with _tool_timeout_cache_lock:
        if tool_name in _tool_timeout_cache:
            return _tool_timeout_cache[tool_name]
    timeout = DEFAULT_TOOL_TIMEOUT
    try:
        for cfg in load_tool_configs():
            if cfg.name == tool_name:
                timeout = cfg.timeout if cfg.timeout and cfg.timeout > 0 else DEFAULT_TOOL_TIMEOUT
                break
    except Exception:
        timeout = DEFAULT_TOOL_TIMEOUT
    with _tool_timeout_cache_lock:
        _tool_timeout_cache[tool_name] = timeout
    return timeout


def invalidate_tool_timeout_cache() -> None:
    """清除工具超时缓存（save_tool_configs 后调用，确保配置变更立即生效）。"""
    with _tool_timeout_cache_lock:
        _tool_timeout_cache.clear()


# ---------- 强制权限工具（前端锁死，不可修改） ----------
# 仅必须 confirm 的工具锁死；safe_tools 默认 direct 但用户可改为 confirm
_FORCED_CONFIRM_TOOLS = {"human_interaction"}


def get_tool_forced_permissions() -> dict[str, str]:
    """返回强制权限的工具映射 {tool_name: "confirm"}，
    前端应对这些工具禁用权限下拉框和 auto_execute_rules 编辑。"""
    return {name: "confirm" for name in _FORCED_CONFIRM_TOOLS}


# ---------- 模型管理 ----------
def _default_models() -> list[dict]:
    """生成默认模型列表，首次启动时从 .env 继承已有 LLM 配置。"""
    import os
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")
    timeout = os.environ.get("LLM_TIMEOUT", "60")
    if api_key and base_url and model:
        return [
            {
                "id": str(uuid.uuid4())[:8],
                "name": "默认模型",
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
                "timeout": float(timeout) if timeout else 60.0,
                "max_retries": 0,
            }
        ]
    return []


def load_models() -> list[dict]:
    """从 env_config.json 的 models 字段加载模型列表。"""
    raw = _read_json(ENV_CONFIG_PATH)
    if isinstance(raw, dict) and "models" in raw and isinstance(raw["models"], list) and raw["models"]:
        return raw["models"]
    return _default_models()


def save_models(models: list[dict]) -> bool:
    """将模型列表写入 env_config.json（合并其他字段）。"""
    current = load_env_config()
    current["models"] = models
    return _write_json(ENV_CONFIG_PATH, current)


# ---------- Env 配置 ----------
def _default_env_config() -> dict:
    """生成默认 env 配置（不含 models，models 由 load_models 独立处理）。"""
    import os as _os
    _default_working = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    return {
        "WORKING_DIR": _default_working,
        "WORKSPACE_DIR": "",
        "STREAMING_TTS_URL": "",
        "ASR_BASE_URL": "",
        "RAG_BASE_URL": "",
        "IMAGE_GEN_URL": "http://localhost:8904",
        "LLM_CONTEXT_WINDOW": "262144",
        "COMPRESS_RATE": "0.6",
        "THINKING_LEVEL": "low",
        "IMG_SIZE": "768",
        "RAG_CHUNK_SIZE": "500",
        "RAG_CHUNK_OVERLAP": "50",
        "GROUNDING_WIDTH": "1000",
        "GROUNDING_HEIGHT": "1000",
        "LOOP_DETECT_TODOLIST_STALE_ROUNDS": "10",
        "LOOP_DETECT_REPEATED_TOOL_WARN": "3",
        "LOOP_DETECT_REPEATED_TOOL_END": "5",
        "SEND_FILE_SIZE_LIMIT": "30",
        "STORAGE_BACKEND": "json",
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "",
        "MYSQL_DATABASE": "agent_history",
        "EMAIL_ADDRESS": "",
        "EMAIL_AUTH_CODE": "",
    }


def load_env_config() -> dict:
    """从 env_config.json 加载环境变量配置，无文件时返回默认。"""
    raw = _read_json(ENV_CONFIG_PATH)
    if not raw or not isinstance(raw, dict):
        raw = _default_env_config()
        raw["models"] = _default_models()
        _write_json(ENV_CONFIG_PATH, raw)
        return raw
    # 确保有 models 字段
    if "models" not in raw or not isinstance(raw.get("models"), list):
        raw["models"] = _default_models()
    return raw


def save_env_config(config: dict) -> bool:
    """将 env 配置写入 env_config.json（保留已有 models）。"""
    # 保留已有的 models 列表（由 models API 单独管理）
    existing = _read_json(ENV_CONFIG_PATH)
    if isinstance(existing, dict) and "models" in existing:
        config["models"] = existing["models"]
    return _write_json(ENV_CONFIG_PATH, config)


# ---------- 获取所有已注册工具的基础信息 ----------
def get_registered_tool_names() -> list[str]:
    """返回所有可用工具名称（含数据库工具）。"""
    from agent.tools import get_all_available_tool_names
    return get_all_available_tool_names()


# ---------- GUI 显示器配置 ----------
GUI_CONFIG_PATH = _CONFIG_DIR / "gui_config.json"


def _default_gui_config() -> dict:
    """生成默认 GUI 显示器配置（主显示器）。"""
    try:
        from screeninfo import get_monitors
        monitors = get_monitors()
        primary = next((m for m in monitors if m.is_primary), monitors[0] if monitors else None)
        if primary:
            return {
                "gui_monitor_name": primary.name or "",
                "gui_monitor_index": 0,
                "gui_model_id": "",
                "monitors_snapshot": _serialize_monitors(monitors),
            }
    except Exception:
        pass
    return {
        "gui_monitor_name": "",
        "gui_monitor_index": 0,
        "gui_model_id": "",
        "monitors_snapshot": [],
    }


def _serialize_monitors(monitors) -> list[dict]:
    """将 screeninfo Monitor 对象序列化为可 JSON 化的字典列表。"""
    result = []
    for m in monitors:
        result.append({
            "name": m.name or "",
            "x": m.x,
            "y": m.y,
            "width": m.width,
            "height": m.height,
            "is_primary": m.is_primary,
        })
    return result


def _get_live_monitors() -> list[dict]:
    """实时获取当前连接的显示器列表（通过 screeninfo）。"""
    from screeninfo import get_monitors
    return _serialize_monitors(get_monitors())


def load_gui_config() -> dict:
    """从 gui_config.json 加载 GUI 显示器配置，无文件时返回默认。"""
    raw = _read_json(GUI_CONFIG_PATH)
    if not raw or not isinstance(raw, dict):
        raw = _default_gui_config()
        _write_json(GUI_CONFIG_PATH, raw)
    return raw


def save_gui_config(config: dict) -> bool:
    """将 GUI 显示器配置写入 gui_config.json。"""
    return _write_json(GUI_CONFIG_PATH, config)


def get_gui_model_config() -> dict | None:
    """获取 GUI 工具专用的模型配置。

    从 gui_config.json 读取 gui_model_id，在 env_config.json 的 models 列表中查找对应模型。
    若 gui_model_id 为空或找不到对应模型，返回 None（表示使用 agent 主模型）。

    返回:
        模型配置 dict 或 None
    """
    gui_config = load_gui_config()
    model_id = gui_config.get("gui_model_id", "").strip()
    if not model_id:
        return None
    models = load_models()
    for m in models:
        if m.get("id", "") == model_id:
            return dict(m)
    return None


def get_gui_llm():
    """获取 GUI 工具专用的 LLM 实例。

    若 gui_config.json 中 gui_model_id 已配置且在模型列表中存在，返回对应的 ChatQwen 实例；
    否则返回 None（调用方应回退到全局 llm 单例）。

    返回:
        ChatQwen 实例或 None
    """
    model_cfg = get_gui_model_config()
    if model_cfg is None:
        return None
    from agent.core.llm import ChatQwen
    # 深度思考由全局 THINKING_LEVEL 档位控制（与主 Agent 一致），取代 per-model enable_thinking
    from agent.utils.env_utils import get_thinking_extra_body
    return ChatQwen(
        model=model_cfg["model"],
        api_key=model_cfg["api_key"],
        base_url=model_cfg["base_url"],
        timeout=model_cfg.get("timeout", 60),
        max_retries=model_cfg.get("max_retries", 0),
        extra_body=get_thinking_extra_body(),
    )


def get_active_monitor_region() -> dict | None:
    """获取当前选中的 GUI 操作显示器的区域信息。

    返回:
        {"x": int, "y": int, "width": int, "height": int, "name": str} 或 None

    系统定位:
        供 gui_tool.py 截取指定显示器区域并做坐标变换。
    """
    config = load_gui_config()
    monitor_name = config.get("gui_monitor_name", "")

    monitors = _get_live_monitors()

    if not monitors:
        return None

    # 按名称模糊匹配
    if monitor_name:
        for m in monitors:
            if monitor_name.lower() in (m.get("name", "") or "").lower():
                return {"x": m["x"], "y": m["y"], "width": m["width"], "height": m["height"], "name": m["name"]}

    # 回退：主显示器
    primary = next((m for m in monitors if m.get("is_primary")), monitors[0] if monitors else None)
    if primary:
        return {"x": primary["x"], "y": primary["y"], "width": primary["width"], "height": primary["height"], "name": primary["name"]}
    return None
