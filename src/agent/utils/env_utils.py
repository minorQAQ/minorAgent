"""环境变量加载与全局配置常量。

系统定位:
    项目配置入口，模块导入时从 ``agents/config.json`` 的 env 分区加载配置，
    并向 ``core/llm``、``utils/agent_utils``、``utils/image_utils`` 等模块
    提供 LLM、压缩策略、RAG、浏览器等运行时参数。

可扩展性:
    - 新增配置项时，在此定义常量并注明默认值与类型转换逻辑。
    - 可将 ``BROWSER_MAP`` 扩展为从环境变量或配置文件动态加载。
"""
import json
import os
from pathlib import Path
from typing import Dict, Tuple


def _get_env(name: str, default: str | None = None, cast: type | None = None, required: bool = False):
    """读取并可选类型转换单个环境变量。

    功能描述:
        从 ``os.environ`` 取值，支持必填校验与类型转换。

    输入:
        name: 环境变量名。
        default: 缺省值；与 required=True 互斥使用。
        cast: 转换类型（如 int、float）。
        required: 为 True 且变量缺失时抛出 ``EnvironmentError``。

    输出:
        原始字符串或 cast 后的值；缺失且无 default 时为 None。

    系统定位:
        本模块内部私有辅助，所有模块级常量均通过此函数初始化。

    可扩展性:
        可扩展 bool 解析、路径规范化、密钥脱敏日志等。
    """
    value = os.getenv(name, default)
    if value is None and required:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    if cast is None or value is None:
        return value
    try:
        return cast(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid value for {name}: {value}") from exc


def _refresh_globals():
    """刷新模块级常量（热重载用）。

    WORKING_DIR / WORKSPACE_DIR 已从环境变量移除：工作空间默认取启动目录
    （os.getcwd()），实际工作空间由 workspace 分区与工作空间 API 管理。
    THINKING_LEVEL 已改为会话级变量（存于各会话 session_meta.json），
    此处仅保留全局默认档位作为无会话上下文（cron、describe_image 等）的兜底。
    """
    global WORKING_DIR, WORKSPACE_DIR, USER_PYTHON_PATH
    global LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT
    global LLM_CONTEXT_WINDOW, COMPRESS_RATE, THINKING_LEVEL
    global IMG_SIZE, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP, GROUNDING_WIDTH, GROUNDING_HEIGHT
    global SEND_FILE_SIZE_LIMIT

    WORKING_DIR = os.getcwd()
    # 将相对路径解析为绝对路径，确保无论从哪个目录启动服务，WORKING_DIR 始终指向项目根目录
    if WORKING_DIR and not os.path.isabs(WORKING_DIR):
        WORKING_DIR = os.path.abspath(WORKING_DIR)
    WORKSPACE_DIR = ""
    USER_PYTHON_PATH = _get_env("USER_PYTHON_PATH", default="")
    LLM_BASE_URL = _get_env("LLM_BASE_URL", required=True)
    LLM_API_KEY = _get_env("LLM_API_KEY", required=True)
    LLM_MODEL = _get_env("LLM_MODEL", required=True)
    LLM_TIMEOUT = _get_env("LLM_TIMEOUT", default="60", cast=float)
    LLM_CONTEXT_WINDOW = int(os.getenv("LLM_CONTEXT_WINDOW", 262144))
    COMPRESS_RATE = float(os.getenv("COMPRESS_RATE", 0.6))
    THINKING_LEVEL = _get_env("THINKING_LEVEL", default="low")
    if THINKING_LEVEL not in THINKING_LEVELS:
        THINKING_LEVEL = "low"
    IMG_SIZE = int(os.getenv("IMG_SIZE", 768))
    RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", 500))
    RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", 50))
    GROUNDING_WIDTH = int(os.getenv("GROUNDING_WIDTH", 1000))
    GROUNDING_HEIGHT = int(os.getenv("GROUNDING_HEIGHT", 1000))
    SEND_FILE_SIZE_LIMIT = int(os.getenv("SEND_FILE_SIZE_LIMIT", 30)) * 1024 * 1024


# ---------- 深度思考档位 ----------
# low=agent+不思考  high=plan+不思考  xhigh=agent+思考  max=plan+思考
# ultra 为未来 react→审批图预留占位，暂按"agent+思考"处理
THINKING_LEVELS: tuple[str, ...] = ("low", "high", "xhigh", "max", "ultra")
_THINKING_ENABLED_LEVELS: frozenset[str] = frozenset({"xhigh", "max", "ultra"})
# 全局默认档位：仅作为无会话上下文（cron 等）的兜底；会话级档位见 get_session_thinking_level
THINKING_LEVEL: str = "low"


def get_session_thinking_level(session_id: str | None) -> str:
    """读取会话级思考档位（存于该会话的 session_meta.json）。

    输入:
        session_id: 会话 ID；为空或读取失败时返回全局默认档位。

    输出:
        合法档位字符串（low | high | xhigh | max | ultra）。
    """
    if session_id:
        try:
            from agent.utils.agent_utils import get_session_thinking_level as _get_session_level
            lv = _get_session_level(session_id)
            if lv in THINKING_LEVELS:
                return lv
        except Exception:
            pass
    return THINKING_LEVEL


def thinking_enabled(level: str | None = None, session_id: str | None = None) -> bool:
    """判断思考档位是否启用深度思考（level 优先，其次按会话档位，最后全局默认）。"""
    if level:
        lv = level
    elif session_id:
        lv = get_session_thinking_level(session_id)
    else:
        lv = THINKING_LEVEL
    return (lv or "low").lower() in _THINKING_ENABLED_LEVELS


def get_thinking_extra_body(level: str | None = None, session_id: str | None = None) -> dict | None:
    """根据思考档位返回 Multimodel_LLM 的 extra_body。

    返回空 dict {} 表示恢复模型原生行为（启用思考）；None 表示禁用思考（默认）。
    传入 session_id 时按该会话的会话级档位解析（供运行时每轮动态应用）。
    """
    return {} if thinking_enabled(level, session_id) else None


# ---------- 本地服务模型（ASR / TTS / RAG / ImageGen） ----------
# 这四个服务在 env_config.json 的 models 列表中注册（model 字段为模型名），
# 运行时按模型名匹配取得 base_url / api_key；未注册时回退到默认本地端口。
SERVICE_MODELS: dict[str, str] = {
    "asr": "Qwen3-ASR-1.7B",
    "tts": "VoxCPM1.5",
    "rag": "Qwen3-Embedding-0.6B",
    "image_gen": "Z-Image-Turbo",
}
SERVICE_DEFAULT_URLS: dict[str, str] = {
    "asr": "http://localhost:8901",
    "tts": "http://localhost:8902",
    "rag": "http://localhost:8903",
    "image_gen": "http://localhost:8904",
}


def get_service_model_config(service: str) -> dict:
    """获取本地服务（asr/tts/rag/image_gen）的模型配置。

    优先在 env_config.json 的 models 列表中按 model 名匹配（含 base_url / api_key / model），
    未注册时回退到默认本地端口（api_key 为空）。

    输入:
        service: 服务标识，SERVICE_MODELS 中的键（asr/tts/rag/image_gen）。

    输出:
        {"model": str, "base_url": str, "api_key": str}
    """
    model_name = SERVICE_MODELS.get(service, "")
    default_url = SERVICE_DEFAULT_URLS.get(service, "")
    try:
        from agent.core.config_manager import get_model_by_name
        cfg = get_model_by_name(model_name)
        if cfg and cfg.get("base_url"):
            return {
                "model": str(cfg.get("model", model_name)),
                "base_url": str(cfg["base_url"]).rstrip("/"),
                "api_key": str(cfg.get("api_key", "") or ""),
            }
    except Exception:
        pass
    return {
        "model": model_name,
        "base_url": default_url.rstrip("/"),
        "api_key": "",
    }


def _load_config() -> dict:
    """加载 config.json 的 env 分区，不存在时回退到 .env 文件。

    优先级: agents/config.json（通过 config_manager 统一读取） > .env > 默认值
    """
    # 优先通过 config_manager 读取（单一数据源，避免重复解析同一文件）
    try:
        from agent.core.config_manager import load_env_config
        config = load_env_config()
        if isinstance(config, dict):
            # 将非 models 的值写入 os.environ
            for key, value in config.items():
                if key != "models" and value is not None:
                    os.environ[key] = str(value)
            # 从 models 列表中提取第一个模型的 LLM 参数
            models = config.get("models")
            if isinstance(models, list) and models:
                m = models[0]
                if m.get("api_key"): os.environ["LLM_API_KEY"] = str(m["api_key"])
                if m.get("base_url"): os.environ["LLM_BASE_URL"] = str(m["base_url"])
                if m.get("model"): os.environ["LLM_MODEL"] = str(m["model"])
                if m.get("timeout") is not None: os.environ["LLM_TIMEOUT"] = str(m["timeout"])
            _refresh_globals()
            return config
    except Exception:
        pass

    # 回退：直接读取文件（config_manager 不可用时）
    _config_path = Path(__file__).resolve().parents[1] / "agents" / "config.json"

    if _config_path.is_file():
        try:
            with open(_config_path, "r", encoding="utf-8") as f:
                merged = json.load(f)
            config = merged.get("env") if isinstance(merged, dict) else None
            if isinstance(config, dict):
                for key, value in config.items():
                    if key != "models" and value is not None:
                        os.environ[key] = str(value)
                models = config.get("models")
                if isinstance(models, list) and models:
                    m = models[0]
                    if m.get("api_key"): os.environ["LLM_API_KEY"] = str(m["api_key"])
                    if m.get("base_url"): os.environ["LLM_BASE_URL"] = str(m["base_url"])
                    if m.get("model"): os.environ["LLM_MODEL"] = str(m["model"])
                    if m.get("timeout") is not None: os.environ["LLM_TIMEOUT"] = str(m["timeout"])
                _refresh_globals()
                return config
        except (json.JSONDecodeError, OSError):
            pass

    return {}


def reload_config() -> dict:
    """实时重载 env_config.json 配置，刷新所有模块级常量。

    可在不重启进程的情况下重新读取配置文件，更新 GROUNDING_WIDTH 等运行时参数。
    注意：调用方需通过 ``import agent.utils.env_utils as env_utils`` 然后访问
    ``env_utils.GROUNDING_WIDTH`` 才能获取到更新后的值，直接 ``from ... import``
    的方式会绑定旧值。

    输出:
        加载到的配置字典，失败时返回空字典。
    """
    result = _load_config()
    _refresh_globals()
    return result


_load_config()
_refresh_globals()  # 确保无论配置加载成功与否，都有默认值

# ---------- 浏览器工具映射（内部名 -> 可执行名, 显示名） ----------
BROWSER_MAP: Dict[str, Tuple[str, str]] = {
    "edge": ("microsoft-edge", "Microsoft Edge"),
    "chrome": ("chrome", "Google Chrome"),
    "firefox": ("firefox", "Mozilla Firefox"),
    "safari": ("safari", "Safari"),
    "opera": ("opera", "Opera"),
    "brave": ("brave", "brave browser"),
}


def get_workspace_dir() -> str:
    """获取 agent 的工作空间绝对路径。

    WORKSPACE_DIR 可能是相对路径（相对于 WORKING_DIR）或绝对路径。
    如果未配置 WORKSPACE_DIR，回退到 WORKING_DIR。

    输出:
        workspace 的绝对路径字符串，保证目录存在。

    系统定位:
        供 tools 模块获取默认的文件操作目录，agent 产生的代码、图片等文件
        默认存入此目录。
    """
    working = WORKING_DIR if WORKING_DIR else os.getcwd()
    ws = WORKSPACE_DIR if WORKSPACE_DIR else ""

    if ws:
        if os.path.isabs(ws):
            workspace = ws
        else:
            workspace = os.path.join(working, ws)
    else:
        workspace = working

    # 确保目录存在
    os.makedirs(workspace, exist_ok=True)
    return workspace


def get_venv_dir() -> str:
    """获取 Python 可执行文件路径对应的虚拟环境目录。

    从 USER_PYTHON_PATH 取所在 Scripts 目录的上级目录。
    例如 "C:\\myenv\\Scripts\\python.exe" → "C:\\myenv"

    输出:
        虚拟环境目录的绝对路径，未配置时返回 ""。
    """
    if USER_PYTHON_PATH and os.path.isfile(USER_PYTHON_PATH):
        return os.path.dirname(os.path.dirname(USER_PYTHON_PATH))
    return ""
