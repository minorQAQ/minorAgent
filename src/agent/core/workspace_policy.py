"""工作空间访问策略：doc_tool / terminal_execute 的越界拦截与审批。

系统定位:
    工作空间选中后（见 ``web/server.py`` 的 /api/workspace 系列接口），对文档写操作
    （doc_tool 的 create/update/delete）与终端文件操作（terminal_execute 的
    working_dir / 命令变更目标）做路径沙箱校验，把"提示词劝导"变为"工具层强制"。

    访问模式 (access_mode，持久化于 config.json 的 workspace 分区):
        - restricted: 越界直接拦截，返回错误文案给 Agent 自行纠正。
        - approval:   越界时暂停图，交由前端人工审批（复用 HITL 审批卡片）。
        - full:       不做越界审查。

    无人值守（cron 子进程，``cron/runner.py`` 调用 ``mark_headless``）时，
    approval 模式自动退化为 restricted：待审批项存于子进程内存、随进程退出丢失，
    无人在线审批，退化为拦截避免静默失败。

    注意: shell 命令无法完全沙箱（任意代码可执行），terminal_execute 的命令扫描为
    保守启发式，仅拦截明显的越界文件操作；强保证来自 doc_tool 路径校验与
    working_dir 校验。

可扩展性:
    - 新增需审查的工具时，扩展 ``check_violation`` 分支与 ``_POLICY_TOOLS``。
    - 可将访问模式改为按工作空间独立存储（当前为全局单值）。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any, Literal, Optional

# ============================================================
#  访问模式
# ============================================================

_ACCESS_MODES: tuple[str, ...] = ("restricted", "approval", "full")
_DEFAULT_MODE: str = "restricted"

_WS_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[1] / "agents" / "config.json"

# 无人值守标记环境变量（cron 子进程设置）
_HEADLESS_ENV = "AGENT_HEADLESS"

# 进程内缓存：server.py 写模式时同步更新；get_access_mode 每次读文件兜底，
# 保证 cron 子进程能拿到用户最新选择（子进程缓存初始为 None → 读文件）。
_mode_cache: str | None = None


def _read_ws_config() -> dict:
    """读取 config.json 的 workspace 分区；失败返回空字典。"""
    if _WS_CONFIG_PATH.is_file():
        try:
            with open(_WS_CONFIG_PATH, "r", encoding="utf-8") as f:
                merged = json.load(f)
            cfg = merged.get("workspace") if isinstance(merged, dict) else None
            if isinstance(cfg, dict):
                return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_ws_config(data: dict) -> bool:
    """写入 config.json 的 workspace 分区（保留其他分区）；失败返回 False。"""
    try:
        merged = {}
        if _WS_CONFIG_PATH.is_file():
            with open(_WS_CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                merged = loaded
        merged["workspace"] = data
        with open(_WS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def get_access_mode() -> str:
    """读取当前访问模式（restricted | approval | full）。

    优先读配置文件（即时生效）；读失败回退进程内缓存，再回退默认值。
    """
    global _mode_cache
    try:
        mode = _read_ws_config().get("access_mode", _DEFAULT_MODE)
        if mode in _ACCESS_MODES:
            return mode
    except Exception:
        pass
    if _mode_cache in _ACCESS_MODES:
        return _mode_cache
    return _DEFAULT_MODE


def set_access_mode(mode: str) -> bool:
    """设置访问模式并持久化到 config.json 的 workspace 分区。

    输入:
        mode: restricted | approval | full。

    输出:
        持久化成功返回 True，非法模式或写入失败返回 False。
    """
    global _mode_cache
    if mode not in _ACCESS_MODES:
        return False
    cfg = _read_ws_config()
    cfg["access_mode"] = mode
    ok = _write_ws_config(cfg)
    if ok:
        _mode_cache = mode
    return ok


# ============================================================
#  无人值守标记（cron 子进程）
# ============================================================

def mark_headless() -> None:
    """标记当前进程为无人值守（cron 子进程），approval 模式退化为拦截。"""
    os.environ[_HEADLESS_ENV] = "1"


def is_headless() -> bool:
    """当前进程是否无人值守（无人在线审批）。"""
    return os.environ.get(_HEADLESS_ENV) == "1"


# ============================================================
#  路径解析与包含判断
# ============================================================

def get_workspace_root() -> str:
    """获取当前工作空间根路径（运行时选中优先，回退 env_config 默认）。"""
    try:
        from agent.memory.system_prompt import _current_workspace_dir
        if _current_workspace_dir and os.path.isabs(_current_workspace_dir):
            return os.path.normpath(_current_workspace_dir)
    except Exception:
        pass
    from agent.utils.env_utils import get_workspace_dir
    return os.path.normpath(get_workspace_dir())


def _resolve_target(path: str, workspace_root: str) -> str | None:
    """将用户提供的路径解析为真实绝对路径；解析失败返回 None。

    相对路径按工作空间解析（而非进程 cwd）；随后用 pathlib.Path.resolve()
    消化 ``..`` 与符号链接/junction，避免路径逃逸。
    """
    if not path or not isinstance(path, str):
        return None
    raw = path.strip().strip('"').strip("'")
    if not raw:
        return None
    target = raw if os.path.isabs(raw) else os.path.join(workspace_root, raw)
    try:
        return str(pathlib.Path(target).resolve())
    except (OSError, ValueError):
        return None


def _is_within(root: str, target: str) -> bool:
    """判断 target 是否位于 root（含子目录）内。

    使用 normcase 处理 Windows 大小写不敏感；跨盘符（commonpath 抛
    ValueError）一律视为越界。
    """
    root_norm = os.path.normcase(os.path.abspath(root))
    target_norm = os.path.normcase(os.path.abspath(target))
    try:
        common = os.path.commonpath([root_norm, target_norm])
    except ValueError:  # 不同盘符（如 C: vs D:）
        return False
    return common == root_norm


# ============================================================
#  越界检测
# ============================================================

# doc_tool 写操作（read 放行：允许读取工作空间外的参考文档/上传附件）
_WRITE_ACTIONS = {"create", "update", "delete"}


def check_doc_tool(args: dict[str, Any]) -> str | None:
    """doc_tool 越界检测：create/update/delete 的 file_path 必须位于工作空间内。

    输入:
        args: 工具调用参数字典。

    输出:
        越界原因字符串；无越界返回 None。
    """
    action = args.get("action")
    if action not in _WRITE_ACTIONS:
        return None
    file_path = args.get("file_path")
    if not file_path or not isinstance(file_path, str):
        return None  # 缺路径交由工具自身报错，不在此处误拦
    root = get_workspace_root()
    target = _resolve_target(file_path, root)
    if target is None:
        return f"无法解析目标路径: {file_path}"
    if not _is_within(root, target):
        return f"目标路径 '{file_path}' 不在工作空间 '{root}' 内（解析为 '{target}'）"
    return None


# 文件变更类动词（小写；含尾部空格避免误匹配普通单词）
_MUTATION_VERBS: tuple[str, ...] = (
    "remove-item", "remove ", "rm ", "rd ", "ri ", "del ", "erase ",
    "new-item", "ni ", "mkdir", "md ", "set-content", "sc ", "add-content",
    "ac ", "out-file", "copy-item", "copy ", "cp ", "move-item", "mv ", "mi ",
    "set-location", "cd ", "pushd ",
)

# Windows 绝对路径（盘符或 UNC），不含引号与空白
_ABS_WIN_RE = re.compile(r"""(?<![A-Za-z0-9\\/])([A-Za-z]:[\\/][^\s"'<>|&;()]+|\\\\[^\s"'<>|&;()]+)""")
# 路径中的 .. 组件（如 ..\foo、../foo、cd ..）
_TRAVERSAL_RE = re.compile(r"""(?:^|[\s"'=;(])(\.\.(?=[\s\\/'"<>&|;)]|$))""")


def _path_escapes(path: str, root: str) -> bool:
    """判断命令中的路径参数是否解析到工作空间外（绝对路径或 ``..`` 遍历）。

    相对路径（相对工作空间）解析后仍在工作空间内，不算越界。
    """
    if not path:
        return False
    if _TRAVERSAL_RE.search(path):
        return True
    if re.match(r"""[A-Za-z]:[\\/]|\\\\""", path):
        target = _resolve_target(path, root)
        if target is None:
            return True
        return not _is_within(root, target)
    return False


def _check_command_paths(command: str, root: str) -> str | None:
    """扫描命令中文件变更类动词/重定向指向的路径是否越界。

    启发式：对每个变更动词，用 shlex 分词其后全部参数（posix=False 保留
    Windows 反斜杠路径），逐个检查是否解析到工作空间外；重定向 ``>``/``>>``
    的目标单独检查。无法完全沙箱 shell，仅拦截明显越界目标。
    """
    import shlex
    lowered = command.lower()
    for verb in _MUTATION_VERBS:
        idx = lowered.find(verb)
        while idx != -1:
            rest = command[idx + len(verb):]
            try:
                tokens = shlex.split(rest, posix=False)
            except ValueError:
                tokens = re.findall(r"""[^\s"'<>|&;()]+""", rest)
            for token in tokens:
                # 去掉尾部常见符号（; | & ( 等）
                candidate = token.rstrip(";|&()<>,")
                if _path_escapes(candidate, root):
                    return (f"命令中 '{verb.strip()}' 的目标路径 '{candidate}' "
                            f"超出工作空间 '{root}'")
            idx = lowered.find(verb, idx + 1)
    # 重定向 > / >> 的目标
    for m in re.finditer(r""">>?[ \t]*("([^"]*)"|'([^']*)'|([^\s"'<>|&;()]+))""", command):
        candidate = m.group(2) or m.group(3) or m.group(4) or ""
        if _path_escapes(candidate, root):
            return f"命令重定向目标路径 '{candidate}' 超出工作空间 '{root}'"
    return None


def check_terminal_execute(args: dict[str, Any]) -> str | None:
    """terminal_execute 越界检测：working_dir 与命令中的文件变更目标。

    输入:
        args: 工具调用参数字典。

    输出:
        越界原因字符串；无越界返回 None。
    """
    root = get_workspace_root()
    working_dir = args.get("working_dir")
    if working_dir and isinstance(working_dir, str):
        target = _resolve_target(working_dir, root)
        if target is None:
            return f"无法解析工作目录: {working_dir}"
        if not _is_within(root, target):
            return (f"工作目录 '{working_dir}' 不在工作空间 '{root}' 内"
                    f"（解析为 '{target}'）")
    command = args.get("command")
    if command and isinstance(command, str):
        reason = _check_command_paths(command, root)
        if reason:
            return reason
    return None


# 需审查的工具（其余工具不审查）
_POLICY_TOOLS = ("doc_tool", "terminal_execute")


def check_violation(tool_name: str | None, args: dict[str, Any]) -> str | None:
    """返回工具调用的越界原因；无越界或无需审查返回 None。

    输入:
        tool_name: 工具名。
        args: 工具调用参数字典。
    """
    if tool_name == "doc_tool":
        return check_doc_tool(args)
    if tool_name == "terminal_execute":
        return check_terminal_execute(args)
    return None


def decision(tool_name: str | None, args: dict[str, Any]) -> Literal["allow", "block", "approve"]:
    """根据访问模式与越界情况决定处理方式。

    输出:
        - "allow":   放行（full 模式或未越界）。
        - "block":   拦截（restricted 模式，或 approval 模式且无人值守）。
        - "approve": 暂停待人工审批（approval 模式、交互会话）。
    """
    if get_access_mode() == "full":
        return "allow"
    if check_violation(tool_name, args) is None:
        return "allow"
    if get_access_mode() == "restricted":
        return "block"
    if is_headless():
        return "block"  # 无人值守（cron）无人在线审批，退化为拦截
    return "approve"


# ============================================================
#  拦截文案
# ============================================================

_MODE_NAMES = {
    "restricted": "限制访问",
    "approval": "权限审查",
    "full": "完全访问",
}


def build_block_message(tool_name: str | None, args: dict[str, Any], reason: str | None = None) -> str:
    """构建拦截时返回给 Agent 的错误文案（供其自行纠正）。"""
    reason = reason or check_violation(tool_name, args) or "检测到超出工作空间范围的操作"
    mode = get_access_mode()
    mode_name = _MODE_NAMES.get(mode, mode)
    root = get_workspace_root()
    detail = ""
    if tool_name == "doc_tool" and args.get("file_path"):
        detail = f"\n目标文件: {args.get('file_path')}"
    elif tool_name == "terminal_execute" and args.get("command"):
        detail = f"\n命令: {(args.get('command') or '')[:200]}"
    return (
        f"[ERROR] 该操作已按访问模式「{mode_name}」拦截：超出工作空间范围。\n"
        f"原因: {reason}\n"
        f"工作空间: {root}{detail}\n"
        f"请将目标路径调整到工作空间目录下后重试。"
    )
