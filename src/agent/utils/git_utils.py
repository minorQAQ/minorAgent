"""工作区 git 集成工具（元数据目录 .minorAgent，替代自研 snapshot 体系）。

系统定位:
    - 为 Edit 文件树提供 git 状态（新增绿/修改橙），为会话回撤提供文件恢复
    - 元数据目录用工作区内的 ``.minorAgent``（GIT_DIR 环境变量方式，工作区不出现 .git）
    - 所有操作 try/except 包裹：git 不可用/非仓库时静默跳过，不影响主流程

可扩展性:
    - 提交时机由调用方决定（轮次结束落盘时 commit_turn，回撤时 reset_to_commit）
    - 新的 git 子命令可复用 _run / _run_lines 封装
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

# 元数据目录名（工作区内）
GIT_META_DIR = ".minorAgent"
_INIT_MSG = "minor: init"
_TURN_MSG_PREFIX = "minor: "

_SAFE_ENV = dict(os.environ)


def _ws_git_dir(workspace: str) -> str:
    return os.path.join(workspace, GIT_META_DIR)


def _git_env(workspace: str) -> dict:
    """为指定工作区构造 GIT_DIR/GIT_WORK_TREE 环境（元数据放 .minorAgent）。"""
    env = dict(_SAFE_ENV)
    env["GIT_DIR"] = _ws_git_dir(workspace)
    env["GIT_WORK_TREE"] = workspace
    return env


def _run(workspace: str, *args: str, timeout: float = 20.0) -> tuple[int, str]:
    """在指定工作区执行 git 命令，返回 (returncode, stdout)。

    注意：不做 strip——porcelain 输出行首的空格是状态码的一部分
    （如 " D path" 表示 worktree 删除），剥离会破坏解析。
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=workspace,
            env=_git_env(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return -1, ""


def is_repo(workspace: str) -> bool:
    """工作区是否已初始化为 git 仓库。"""
    if not workspace or not os.path.isdir(workspace):
        return False
    return os.path.isdir(_ws_git_dir(workspace))


def ensure_repo(workspace: str) -> bool:
    """确保工作区为 git 仓库（首次自动 init + 初始 commit），失败返回 False。

    初始 commit 让回撤有最底层的恢复点；.minorAgent 写入 info/exclude，
    避免 git status 把元数据目录自身显示为未跟踪。
    """
    if not workspace or not os.path.isdir(workspace):
        return False
    if is_repo(workspace):
        return True
    try:
        rc, _ = _run(workspace, "init", "--quiet")
        if rc != 0:
            return False
        # 本地 user 配置（仅作用于该仓库）
        _run(workspace, "config", "user.name", "minor-agent")
        _run(workspace, "config", "user.email", "minor-agent@local")
        # 排除元数据目录自身（append 模式句柄不可读，需先读后写）
        exclude = os.path.join(_ws_git_dir(workspace), "info", "exclude")
        try:
            os.makedirs(os.path.dirname(exclude), exist_ok=True)
            existing = ""
            if os.path.isfile(exclude):
                with open(exclude, "r", encoding="utf-8") as f:
                    existing = f.read()
            if GIT_META_DIR not in existing:
                with open(exclude, "a", encoding="utf-8") as f:
                    f.write(f"\n{GIT_META_DIR}/\n")
        except OSError:
            pass
        # 初始 commit（空改动也提交，保证 HEAD 存在）
        _run(workspace, "add", "-A")
        rc, _ = _run(workspace, "commit", "-m", _INIT_MSG, "--allow-empty")
        return rc == 0
    except Exception:
        return False


def _porcelain_state(code: str) -> str:
    """git status --porcelain 单字符状态码 → 业务状态。"""
    if code.startswith("??"):
        return "untracked"
    # 第一列 X=index(暂存)，第二列 Y=worktree：任一非空格即视为 modified/deleted
    if len(code) >= 2:
        x, y = code[0], code[1]
        if "D" in (x, y):
            return "deleted"
        if x != " " or y != " ":
            return "modified"
    return "modified"


def status(workspace: str) -> list[dict]:
    """返回工作区 git 状态列表：[{path, state}]，非仓库/失败返回 []。

    state: untracked(新增) | modified(修改/暂存) | deleted(删除)
    """
    if not is_repo(workspace):
        return []
    rc, out = _run(workspace, "status", "--porcelain", "-z")
    if rc != 0 or not out:
        return []
    result: list[dict] = []
    # -z 模式：每项为 "XY path\0"，重命名/复制为 "XY old -> new\0"
    for entry in out.split("\0"):
        if not entry or len(entry) < 3:
            continue
        code, path = entry[:2], entry[3:]
        if code.startswith("R") or code.startswith("C"):
            path = path.split(" -> ")[-1] if " -> " in path else path
        result.append({"path": path, "state": _porcelain_state(code)})
    return result


def commit_turn(workspace: str, session_id: str, turn_id: str) -> bool:
    """提交轮次结束后的工作区快照，message 编码会话与回合（供回撤定位）。"""
    if not workspace or not os.path.isdir(workspace):
        return False
    if not ensure_repo(workspace):
        return False
    try:
        _run(workspace, "add", "-A")
        rc, _ = _run(workspace, "commit", "-m", f"{_TURN_MSG_PREFIX}{session_id} {turn_id}")
        return rc == 0
    except Exception:
        return False


def find_restore_commit(workspace: str, session_id: str, keep_turn_id: str) -> Optional[str]:
    """定位回撤恢复点 commit：该会话 < keep_turn_id 的最近一次轮次提交，无则初始提交。

    回撤到某条消息时，文件应恢复到"该消息之前"的状态 =
    上一个已完成轮次的提交（turn_id 严格小于 keep_turn_id）。
    """
    if not is_repo(workspace):
        return None
    rc, out = _run(workspace, "log", "--format=%H%x09%s")
    if rc != 0 or not out:
        return None
    best: Optional[str] = None
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        commit_hash, msg = parts[0], parts[1]
        if msg == _INIT_MSG:
            best = best or commit_hash  # 兜底：初始提交
            continue
        if not msg.startswith(_TURN_MSG_PREFIX):
            continue
        m = re.match(rf"^{re.escape(_TURN_MSG_PREFIX)}(\S+)\s+(\S+)$", msg)
        if not m or m.group(1) != session_id:
            continue
        tid = m.group(2)
        if tid < keep_turn_id:  # turn_id 为时间戳字符串，字典序即时间序
            best = commit_hash
    return best


def reset_to_commit(workspace: str, commit: str) -> bool:
    """将工作区与 git 状态恢复到指定 commit（丢弃该点之后的改动与未跟踪文件）。"""
    if not is_repo(workspace) or not commit:
        return False
    try:
        rc, _ = _run(workspace, "reset", "--hard", commit)
        if rc != 0:
            return False
        _run(workspace, "clean", "-fd")
        return True
    except Exception:
        return False


def rollback_workspace_to(workspace: str, session_id: str, keep_turn_id: str) -> bool:
    """会话回撤时恢复工作区文件与 git 状态（无恢复点返回 False，调用方跳过）。"""
    if not workspace:
        return False
    commit = find_restore_commit(workspace, session_id, keep_turn_id)
    if not commit:
        return False
    return reset_to_commit(workspace, commit)
