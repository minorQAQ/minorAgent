# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import csv
import ctypes
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model

try:
    import win32com.client as win32com_client  # type: ignore
except Exception:
    win32com_client = None

_windll = getattr(ctypes, "windll", None)
user32: object | None = _windll.user32 if os.name == "nt" and _windll is not None else None
WM_CLOSE = 0x0010
SW_RESTORE = 9


_INDEX_PATH = Path(__file__).resolve().parents[1] / "history" / "data_base" / "software_index.json"
_SHORTCUT_ROOTS = [
    Path(os.environ.get("ProgramData", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("USERPROFILE", "")) / "Desktop",
    Path(os.environ.get("PUBLIC", "")) / "Desktop",
]
_APP_PATH_KEYS = [
    r"Software\Microsoft\Windows\CurrentVersion\App Paths",
]
_SKIP_KEYWORDS = (
    "卸载",
    "uninstall",
    "help",
    "manual",
    "documentation",
    "release notes",
    "readme",
    "website",
    "faq",
    "license",
    "update",
)
_CHAT_APP_PROCESS_NAMES = {
    "qq": ["QQ", "NTQQ"],
    "腾讯qq": ["QQ", "NTQQ"],
    "腾讯QQ": ["QQ", "NTQQ"],
    "wechat": ["WeChat", "Weixin"],
    "weixin": ["WeChat", "Weixin"],
    "微信": ["WeChat", "Weixin"],
}


@dataclass
class SoftwareRecord:
    display_name: str
    aliases: list[str] = field(default_factory=list)
    launch_type: str = ""
    launch_target: str = ""
    shortcut_path: str = ""
    working_dir: str = ""
    process_names: list[str] = field(default_factory=list)
    source: str = ""


def _normalize(text: str) -> str:
    value = text.casefold().strip()
    value = re.sub(r"\.lnk$", "", value)
    value = re.sub(r"\.exe$", "", value)
    value = re.sub(r"[\s\-_()（）\[\]【】]+", "", value)
    return value


def _should_skip(name: str) -> bool:
    lowered = name.casefold()
    return any(keyword in lowered for keyword in _SKIP_KEYWORDS)


def _add_aliases(*values: str) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        for item in (cleaned, Path(cleaned).stem):
            key = _normalize(item)
            if not key or key in seen:
                continue
            seen.add(key)
            aliases.append(item)
    return aliases


def _resolve_shortcut(path: Path) -> tuple[str, str]:
    if win32com_client is None:
        return "", ""
    try:
        shell = win32com_client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(path))
        target = (shortcut.Targetpath or "").strip()
        working_dir = (shortcut.WorkingDirectory or "").strip()
        return target, working_dir
    except Exception:
        return "", ""


def _scan_shortcuts() -> list[SoftwareRecord]:
    records: list[SoftwareRecord] = []
    for root in _SHORTCUT_ROOTS:
        if not root.exists():
            continue
        for shortcut in root.rglob("*.lnk"):
            display_name = shortcut.stem.strip()
            if not display_name or _should_skip(display_name):
                continue
            target, working_dir = _resolve_shortcut(shortcut)
            process_names: list[str] = []
            if target:
                process_names.append(Path(target).stem)
            records.append(
                SoftwareRecord(
                    display_name=display_name,
                    aliases=_add_aliases(display_name, Path(target).stem if target else ""),
                    launch_type="shortcut",
                    launch_target=str(shortcut),
                    shortcut_path=str(shortcut),
                    working_dir=working_dir,
                    process_names=process_names,
                    source="shortcut",
                )
            )
    return records


def _scan_app_paths() -> list[SoftwareRecord]:
    try:
        import winreg as winreg_module  # type: ignore
    except Exception:
        return []
    records: list[SoftwareRecord] = []
    for hive in (winreg_module.HKEY_LOCAL_MACHINE, winreg_module.HKEY_CURRENT_USER):
        for subkey in _APP_PATH_KEYS:
            try:
                root = winreg_module.OpenKey(hive, subkey)
            except OSError:
                continue
            try:
                count = winreg_module.QueryInfoKey(root)[0]
                for index in range(count):
                    name = winreg_module.EnumKey(root, index)
                    try:
                        child = winreg_module.OpenKey(root, name)
                        exe_path, _ = winreg_module.QueryValueEx(child, "")
                    except OSError:
                        continue
                    exe_path = str(exe_path).strip()
                    if not exe_path:
                        continue
                    display_name = Path(name).stem.strip() or Path(exe_path).stem.strip()
                    if not display_name or _should_skip(display_name):
                        continue
                    records.append(
                        SoftwareRecord(
                            display_name=display_name,
                            aliases=_add_aliases(display_name, Path(exe_path).stem),
                            launch_type="app_path",
                            launch_target=exe_path,
                            process_names=[Path(exe_path).stem],
                            source="app_path",
                        )
                    )
            finally:
                winreg_module.CloseKey(root)
    return records


def _deduplicate(records: list[SoftwareRecord]) -> list[SoftwareRecord]:
    merged: dict[tuple[str, str], SoftwareRecord] = {}
    for record in records:
        key = (record.launch_type, record.launch_target.casefold())
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            continue
        existing.aliases = sorted(set(existing.aliases + record.aliases), key=str.casefold)
        existing.process_names = sorted(set(existing.process_names + record.process_names), key=str.casefold)
        if not existing.display_name and record.display_name:
            existing.display_name = record.display_name
    return sorted(merged.values(), key=lambda item: item.display_name.casefold())


def _write_index(records: list[SoftwareRecord]) -> None:
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": int(time.time()),
        "count": len(records),
        "items": [asdict(record) for record in records],
    }
    _INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_index() -> list[SoftwareRecord]:
    if not _INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") or []
    records: list[SoftwareRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        records.append(
            SoftwareRecord(
                display_name=str(item.get("display_name") or ""),
                aliases=list(item.get("aliases") or []),
                launch_type=str(item.get("launch_type") or ""),
                launch_target=str(item.get("launch_target") or ""),
                shortcut_path=str(item.get("shortcut_path") or ""),
                working_dir=str(item.get("working_dir") or ""),
                process_names=list(item.get("process_names") or []),
                source=str(item.get("source") or ""),
            )
        )
    return records


def _build_index() -> list[SoftwareRecord]:
    records = _deduplicate(_scan_shortcuts() + _scan_app_paths())
    _write_index(records)
    return records


def _match_score(query: str, candidate: str) -> float:
    q = _normalize(query)
    c = _normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c:
        return 0.95
    if c in q and len(c) >= 4 and len(c) / max(len(q), 1) >= 0.6:
        return 0.9
    return SequenceMatcher(None, q, c).ratio()


def _rank_matches(query: str, records: list[SoftwareRecord]) -> list[tuple[float, SoftwareRecord]]:
    ranked: list[tuple[float, SoftwareRecord]] = []
    for record in records:
        candidates = [record.display_name, *record.aliases]
        score = max((_match_score(query, candidate) for candidate in candidates), default=0.0)
        if score >= 0.55:
            ranked.append((score, record))
    ranked.sort(key=lambda item: (-item[0], item[1].display_name.casefold()))
    return ranked


def _open_record(record: SoftwareRecord) -> str:
    if not hasattr(os, "startfile"):
        raise RuntimeError("software_control 目前仅支持 Windows 本机软件启动")
    target = record.shortcut_path or record.launch_target
    if not target:
        raise RuntimeError(f"未找到 {record.display_name} 的启动入口")
    if not Path(target).exists():
        raise RuntimeError(f"启动入口不存在：{target}")
    os.startfile(target)  # type: ignore[attr-defined]
    return target


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off", ""}:
            return False
    return bool(value)


def _list_running_processes() -> list[dict[str, str]]:
    try:
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            encoding="gbk",
            errors="ignore",
        )
    except Exception:
        return []
    processes: list[dict[str, str]] = []
    for row in csv.reader(output.splitlines()):
        if len(row) < 2:
            continue
        image_name = row[0].strip()
        pid = row[1].strip()
        if not image_name or not pid:
            continue
        processes.append(
            {
                "image_name": image_name,
                "pid": pid,
                "stem": Path(image_name).stem,
            }
        )
    return processes


def _find_running_pids(record: SoftwareRecord) -> list[int]:
    process_keys = {_normalize(name) for name in record.process_names if name}
    process_keys.add(_normalize(record.display_name))
    process_keys.update(_normalize(alias) for alias in record.aliases if alias)
    matched: list[int] = []
    for proc in _list_running_processes():
        if _normalize(proc["stem"]) in process_keys:
            try:
                matched.append(int(proc["pid"]))
            except ValueError:
                continue
    return sorted(set(matched))


def _find_visible_windows_for_pids(pids: list[int]) -> list[tuple[int, int, str]]:
    u32 = user32
    if u32 is None:
        return []
    pid_set = set(pids)
    results: list[tuple[int, int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, lparam):
        if not u32.IsWindowVisible(hwnd):
            return True
        length = u32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        u32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pid_set:
            results.append((pid.value, int(hwnd), title))
        return True

    u32.EnumWindows(enum_proc, 0)
    return results


def _chat_app_process_names(query: str, record: SoftwareRecord) -> list[str]:
    candidates = [query, record.display_name, *record.aliases]
    for candidate in candidates:
        key = _normalize(candidate)
        if key in _CHAT_APP_PROCESS_NAMES:
            return _CHAT_APP_PROCESS_NAMES[key]
    return []


def _find_pids_for_process_names(process_names: list[str]) -> list[int]:
    process_keys = {_normalize(name) for name in process_names if name}
    matched: list[int] = []
    for proc in _list_running_processes():
        if _normalize(proc["stem"]) in process_keys:
            try:
                matched.append(int(proc["pid"]))
            except ValueError:
                continue
    return sorted(set(matched))


def _activate_existing_window_for_pids(pids: list[int]) -> tuple[int, int, str] | None:
    if user32 is None or not pids:
        return None
    windows = _find_visible_windows_for_pids(pids)
    if not windows:
        return None
    pid, hwnd, title = windows[0]
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return pid, hwnd, title


def _wait_for_pids_exit(pids: list[int], timeout_seconds: float = 5.0) -> list[int]:
    deadline = time.time() + timeout_seconds
    remaining = set(pids)
    while time.time() < deadline and remaining:
        current = set()
        for proc in _list_running_processes():
            try:
                pid = int(proc["pid"])
            except ValueError:
                continue
            if pid in remaining:
                current.add(pid)
        remaining = current
        if remaining:
            time.sleep(0.4)
    return sorted(remaining)


def _close_windows(windows: list[tuple[int, int, str]]) -> None:
    u32 = user32
    if u32 is None:
        return
    for _, hwnd, _ in windows:
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _force_kill_pids(pids: list[int]) -> list[int]:
    killed: list[int] = []
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="ignore",
            )
            killed.append(pid)
        except Exception:
            continue
    return killed


class SoftwareControl(BaseTool):
    args_schema: type[BaseModel] = create_model(
        "SoftwareControlInput",
        action=(str, Field(default="open", description="操作类型：open 表示打开软件，close 表示正常关闭软件，force_close 表示强制关闭软件。")),
        software_name=(str, Field(description="要操作的软件名称，例如微信、Visual Studio Code、MATLAB。")),
        rescan=(bool, Field(default=False, description="是否强制重新扫描本机软件并刷新索引。")),
    )
    name: str = "software_control"
    description: str = (
        "操作本机已安装的软件。工具会自动扫描 Windows 开始菜单快捷方式、桌面快捷方式和 App Paths，"
        "建立软件索引后根据用户输入做模糊匹配。action=open 时打开软件；action=close 时仅做正常关闭；"
        "action=force_close 时才允许在正常关闭失败后强制结束进程。仅当用户明确要求打开、关闭或强制关闭某个本机软件时调用。"
    )

    def _run(self, action: str = "open", software_name: str = "", rescan: bool = False) -> str:
        try:
            if os.name != "nt":
                return "software_control 目前仅支持 Windows 本机软件操作。"
            query = (software_name or "").strip()
            if not query:
                return "软件名称不能为空。"
            action = (action or "open").strip().lower()
            rescan = _coerce_bool(rescan)
            if action not in {"open", "close", "force_close"}:
                return "action 仅支持 open、close 或 force_close。"
            force_requested = action == "force_close"

            records = _build_index() if rescan else _load_index()
            if not records:
                records = _build_index()

            ranked = _rank_matches(query, records)
            if not ranked:
                records = _build_index()
                ranked = _rank_matches(query, records)
            if not ranked:
                return f'未找到与"{query}"匹配的软件，请换一个更具体的软件名。'

            best_score, best_record = ranked[0]
            if best_score < 0.72:
                return f'未找到与"{query}"足够接近的软件，请换一个更具体的软件名。'
            if len(ranked) > 1 and best_score < 0.88 and (best_score - ranked[1][0]) < 0.08:
                candidates = [
                    f"{item.display_name} (score={score:.2f}, source={item.source})"
                    for score, item in ranked[:5]
                ]
                return (
                    f"找到多个相近软件，暂不自动打开。你可以说得更具体一些。\n"
                    f"候选项：\n" + "\n".join(candidates)
                )

            if action == "open":
                running_pids = _find_running_pids(best_record)
                chat_process_names = _chat_app_process_names(query, best_record)
                if chat_process_names:
                    running_pids = sorted(set(running_pids + _find_pids_for_process_names(chat_process_names)))
                existing_window = _activate_existing_window_for_pids(running_pids)
                if existing_window:
                    pid, hwnd, title = existing_window
                    return (
                        f"Switched to existing software window: {best_record.display_name}\n"
                        f"Match score: {best_score:.2f}\n"
                        f"PID: {pid}\n"
                        f"Window title: {title}\n"
                        f"Window handle: {hwnd}\n"
                        "Note: an existing visible window was detected, so the shortcut was not launched again."
                    )
                try:
                    opened_target = _open_record(best_record)
                except Exception as exc:
                    return f'已匹配到软件"{best_record.display_name}"，但启动失败：{exc}'

                process_hint = ", ".join(best_record.process_names) if best_record.process_names else "unknown"
                return (
                    f"已打开软件：{best_record.display_name}\n"
                    f"匹配得分：{best_score:.2f}\n"
                    f"启动方式：{best_record.launch_type}\n"
                    f"启动入口：{opened_target}\n"
                    f"进程提示：{process_hint}\n"
                    f"索引文件：{_INDEX_PATH}"
                )

            running_pids = _find_running_pids(best_record)
            if not running_pids:
                process_hint = ", ".join(best_record.process_names) if best_record.process_names else "unknown"
                return (
                    f"已匹配到软件：{best_record.display_name}\n"
                    f"匹配得分：{best_score:.2f}\n"
                    f"但当前没有发现正在运行的对应进程。\n"
                    f"进程提示：{process_hint}"
                )

            windows = _find_visible_windows_for_pids(running_pids)
            if windows:
                _close_windows(windows)
                remaining = _wait_for_pids_exit(running_pids, timeout_seconds=5.0)
                if not remaining:
                    titles = "；".join(title for _, _, title in windows[:3])
                    return (
                        f"已正常关闭软件：{best_record.display_name}\n"
                        f"匹配得分：{best_score:.2f}\n"
                        f"关闭方式：窗口关闭请求\n"
                        f"涉及 PID：{', '.join(str(pid) for pid in running_pids)}\n"
                        f"窗口标题示例：{titles}"
                    )
                if not force_requested:
                    return (
                        f'已向软件"{best_record.display_name}"发送正常关闭请求，但仍有进程未退出。\n'
                        f"剩余 PID：{', '.join(str(pid) for pid in remaining)}\n"
                        f"如需强制关闭，请明确使用 force_close 动作后重试。"
                    )
                killed = _force_kill_pids(remaining)
                return (
                    f'软件"{best_record.display_name}"正常关闭未完全成功，已执行强制关闭。\n'
                    f"强制结束 PID：{', '.join(str(pid) for pid in killed) if killed else 'none'}"
                )

            if not force_requested:
                return (
                    f'已找到软件"{best_record.display_name}"的运行进程，但未找到可见主窗口，暂未自动强制关闭。\n'
                    f"运行 PID：{', '.join(str(pid) for pid in running_pids)}\n"
                    f"如需强制关闭，请明确使用 force_close 动作后重试。"
                )
            killed = _force_kill_pids(running_pids)
            return (
                f'软件"{best_record.display_name}"未找到可见主窗口，已按进程强制关闭。\n'
                f"强制结束 PID：{', '.join(str(pid) for pid in killed) if killed else 'none'}"
            )
        except Exception as e:
            return f"[ERROR] software_control 工具执行出错: {str(e)}"

    async def _arun(self, action: str = "open", software_name: str = "", rescan: bool = False) -> str:
        import asyncio
        return await asyncio.to_thread(self._run, action, software_name, rescan)
