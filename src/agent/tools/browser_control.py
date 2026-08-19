"""浏览器控制工具与 Playwright 会话管理器。

本模块包含两部分:
    1. BrowserSession —— Playwright 会话管理器（非工具，供本工具与 web_page 共用）
    2. BrowserControl —— 浏览器控制 LangChain 工具（开/关浏览器、标签页管理）

会话架构（分离进程 + CDP 连接）:
    - 浏览器以独立进程启动（--remote-debugging-port），Agent 退出后窗口保留
    - Agent 重启后通过 CDP 自动重连同一浏览器（登录态、标签页不丢）
    - 专用后台线程运行 asyncio loop，所有 Playwright 异步操作在该线程串行执行，
      规避 sync API 的线程亲和问题

可扩展性:
    - 端口与 profile 目录取环境变量 BROWSER_DEBUG_PORT / BROWSER_PROFILE_DIR 覆盖
    - 新的页面级操作经 BrowserSession.call_async 提交协程即可，无需改动线程模型
"""
from __future__ import annotations

import asyncio
import atexit
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import TimeoutError as _FutureTimeoutError
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Tuple

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model


# ==================== 第一部分：BrowserSession 会话管理器 ====================

# ---------- 配置常量 ----------
_AGENT_DIR = Path(__file__).resolve().parents[1]
BROWSER_DEBUG_PORT = int(os.getenv("BROWSER_DEBUG_PORT", "9222"))
BROWSER_PROFILE_DIR = str(Path(os.getenv("BROWSER_PROFILE_DIR", str(_AGENT_DIR / "data" / "browser_profile"))))
_CDP_URL = f"http://127.0.0.1:{BROWSER_DEBUG_PORT}"
_LAUNCH_TIMEOUT = 15.0          # 分离启动后等待 CDP 就绪的秒数
_DEFAULT_OP_TIMEOUT = 45.0      # 单次操作的默认外层超时

# Windows 分离进程标志：DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
# 使浏览器进程独立于 Agent 进程存活（Agent 退出后浏览器窗口保留）
_DETACHED_FLAGS = 0x00000008 | 0x00000200 | 0x01000000


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def normalize_url(url: str) -> str:
    """补全 URL 协议头：无协议时默认 https://（about:blank、edge:// 等已有 scheme 的不处理）。"""
    u = (url or "").strip()
    if u and "://" not in u and not _SCHEME_RE.match(u):
        u = "https://" + u
    return u


def _candidate_paths(browser: Optional[str]) -> list[str]:
    """按优先级返回浏览器可执行文件候选路径列表。"""
    b = (browser or "edge").lower().strip()
    if b == "chrome":
        order = ["chrome", "edge", "chromium"]
    elif b in ("chromium", "playwright"):
        order = ["chromium", "edge", "chrome"]
    else:  # 默认 edge
        order = ["edge", "chrome", "chromium"]
    pf64 = os.getenv("ProgramFiles", r"C:\Program Files")
    pf86 = os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.getenv("LOCALAPPDATA", "")
    known: dict[str, list[str]] = {
        "edge": [
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf64, "Microsoft", "Edge", "Application", "msedge.exe"),
        ],
        "chrome": [
            os.path.join(pf64, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe") if local else "",
        ],
        "chromium": sorted(
            glob.glob(os.path.join(local, "ms-playwright", "chromium-*", "chrome-win", "chrome.exe")),
            reverse=True,
        ) if local else [],
    }
    out: list[str] = []
    for name in order:
        out.extend(p for p in known.get(name, []) if p)
    return out


def _resolve_executable(browser: Optional[str]) -> str:
    """解析第一个存在的浏览器可执行文件路径，找不到时抛出明确错误。"""
    for p in _candidate_paths(browser):
        if os.path.isfile(p):
            return p
    raise RuntimeError(
        "未找到可用的浏览器（Edge / Chrome / Playwright 内置 Chromium）。"
        "请安装 Edge/Chrome，或运行 `playwright install chromium`。"
    )


def _cdp_alive() -> Optional[dict]:
    """探测 CDP 调试端口是否存活，存活返回 /json/version 内容。"""
    try:
        with urllib.request.urlopen(f"{_CDP_URL}/json/version", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None


class BrowserSession:
    """浏览器会话单例：持有 CDP 连接与当前标签页，对外提供同步门面方法。"""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()
        # 以下状态仅由会话线程读写
        self._playwright = None
        self._browser = None          # connect_over_cdp 得到的 Browser
        self._context = None          # 默认 BrowserContext（持久 profile）
        self._page = None             # 当前活动标签页
        self._proc: Optional[subprocess.Popen] = None
        self._watched: set[int] = set()   # 已注册 close 监听的 page id
        # ref 注册表（snapshot 序号 -> CSS 选择器）
        self._refs: dict[int, str] = {}
        self._refs_page = None
        self._launch_browser_pref: Optional[str] = None
        atexit.register(self._atexit_shutdown)

    # ---------- 线程模型 ----------
    def _ensure_thread(self) -> None:
        """惰性启动会话线程（daemon，随进程退出）。

        loop 在调用线程创建后再交给线程运行，避免 _loop 赋值竞态。
        """
        if self._thread and self._thread.is_alive():
            return
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            loop = asyncio.new_event_loop()
            self._loop = loop
            self._thread = threading.Thread(target=self._thread_main, args=(loop,), name="browser-session", daemon=True)
            self._thread.start()

    def _thread_main(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()

    def call_async(self, coro_fn: Callable[["BrowserSession"], Any], timeout: float = _DEFAULT_OP_TIMEOUT) -> Any:
        """提交协程到会话线程执行并阻塞等待结果。

        coro_fn: 接收 session 的函数，返回 coroutine（在会话线程的事件循环中运行）。
        """
        self._ensure_thread()
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro_fn(self), self._loop)
        try:
            return fut.result(timeout=timeout)
        except _FutureTimeoutError:
            fut.cancel()
            raise TimeoutError(f"浏览器操作超时（>{timeout:.0f}s）") from None

    # ---------- 内部异步实现（全部在会话线程运行） ----------
    async def _ensure_connected(self) -> None:
        """确保 CDP 连接与当前页可用；浏览器未运行时分离启动。"""
        if self._browser is not None and self._browser.is_connected() and self._context is not None:
            await self._ensure_current_page()
            return
        await self._cleanup_connection()
        if _cdp_alive() is None:
            await self._launch_detached()
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError("playwright 未安装，请先 `pip install playwright`") from e
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(_CDP_URL)
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        try:
            self._context.set_default_timeout(10_000)             # 动作超时 10s
            self._context.set_default_navigation_timeout(30_000)  # 导航超时 30s
        except Exception:
            pass
        await self._ensure_current_page()

    async def _ensure_current_page(self) -> None:
        """确保 self._page 指向一个存活标签页（优先沿用当前页，否则取最后一页/新建）。"""
        pages = list(self._context.pages)
        if self._page in pages:
            page = self._page
        elif pages:
            page = pages[-1]
        else:
            page = await self._context.new_page()
        self._page = page
        self._watch_page(page)
        try:
            await page.bring_to_front()
        except Exception:
            pass

    def _watch_page(self, page) -> None:
        """为标签页注册 close 监听（幂等），关闭后自动回退当前页并清理 ref。"""
        if id(page) in self._watched:
            return
        self._watched.add(id(page))

        def _on_close(p=page):
            if self._page is p:
                self._page = None
            if self._refs_page is p:
                self._refs.clear()
                self._refs_page = None

        try:
            page.on("close", _on_close)
        except Exception:
            pass

    async def _launch_detached(self) -> None:
        """以分离进程启动浏览器并等待 CDP 就绪。"""
        exe = _resolve_executable(self._launch_browser_pref)
        Path(BROWSER_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
        cmd = [
            exe,
            f"--remote-debugging-port={BROWSER_DEBUG_PORT}",
            f"--user-data-dir={BROWSER_PROFILE_DIR}",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-crash-restore-bubble",
            "about:blank",
        ]
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = _DETACHED_FLAGS
        else:
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kwargs
        )
        deadline = time.monotonic() + _LAUNCH_TIMEOUT
        while time.monotonic() < deadline:
            if _cdp_alive() is not None:
                return
            if self._proc.poll() is not None:
                break
            await asyncio.sleep(0.3)
        raise RuntimeError(
            "浏览器启动失败：CDP 调试端口未就绪"
            f"（端口 {BROWSER_DEBUG_PORT}，profile 可能被其他浏览器实例占用，可关闭残留浏览器进程后重试）"
        )

    async def _cleanup_connection(self) -> None:
        """断开 CDP 连接（不关闭浏览器进程）。"""
        self._page = None
        self._context = None
        self._refs.clear()
        self._refs_page = None
        if self._browser is not None:
            try:
                await self._browser.close()  # CDP 模式下仅断开连接
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ---------- 页面信息 ----------
    async def _page_meta(self) -> dict[str, Any]:
        page = self._page
        if page is None:
            return {"title": "", "url": ""}
        try:
            title = await page.title()
        except Exception:
            title = ""
        return {"title": title, "url": page.url}

    # ---------- 会话级异步操作（供 call_async 调用） ----------
    async def ensure(self, browser: Optional[str] = None) -> dict[str, Any]:
        """确保浏览器就绪并返回当前页信息（不新建标签页）。"""
        if browser:
            self._launch_browser_pref = browser
        await self._ensure_connected()
        return await self._page_meta()

    async def open_tab(self, url: Optional[str] = None, browser: Optional[str] = None) -> dict[str, Any]:
        """新建标签页并可选导航到 url。"""
        if browser:
            self._launch_browser_pref = browser
        await self._ensure_connected()
        page = await self._context.new_page()
        self._page = page
        self._watch_page(page)
        try:
            await page.bring_to_front()
        except Exception:
            pass
        if url:
            await page.goto(normalize_url(url), wait_until="domcontentloaded")
        return await self._page_meta()

    async def refresh(self) -> dict[str, Any]:
        """刷新当前标签页。"""
        await self._ensure_connected()
        try:
            await self._page.reload(wait_until="domcontentloaded")
        except Exception:
            await self._page.goto(self._page.url, wait_until="domcontentloaded")
        return await self._page_meta()

    async def switch_tab(self, index: int) -> dict[str, Any]:
        """切换到第 index 个标签页（从 0 开始）。"""
        await self._ensure_connected()
        pages = list(self._context.pages)
        if not (0 <= index < len(pages)):
            raise ValueError(f"标签页索引 {index} 越界，当前共 {len(pages)} 个标签页（0~{len(pages) - 1}）")
        self._page = pages[index]
        self._watch_page(self._page)
        try:
            await self._page.bring_to_front()
        except Exception:
            pass
        return await self._page_meta()

    async def close_tab(self) -> str:
        """关闭当前标签页（若为最后一页则保留浏览器，自动补开空白页）。"""
        await self._ensure_connected()
        cur = self._page
        others = [p for p in self._context.pages if p is not cur]
        try:
            await cur.close()
        except Exception:
            pass
        if others:
            self._page = others[-1]
        else:
            # 最后一个标签页关闭会导致浏览器退出，补开空白页保持会话存活
            try:
                self._page = await self._context.new_page()
            except Exception:
                await self._cleanup_connection()
                return "已关闭最后一个标签页，浏览器已退出"
        try:
            await self._page.bring_to_front()
        except Exception:
            pass
        meta = await self._page_meta()
        return f"已关闭标签页，当前页: {meta['title'] or meta['url'] or 'about:blank'}"

    async def close_browser(self) -> str:
        """真正关闭浏览器进程（CDP Browser.close 命令）。"""
        was_connected = self._browser is not None and self._browser.is_connected()
        if was_connected:
            try:
                cdp = await self._browser.new_browser_cdp_session()
                await cdp.send("Browser.close")
            except Exception:
                pass
        await self._cleanup_connection()
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return "已关闭浏览器" if was_connected else "浏览器未在运行（已清理本地连接状态）"

    async def list_tabs(self) -> list[dict[str, Any]]:
        """列出全部标签页（索引、标题、URL），当前页带标记。"""
        await self._ensure_connected()
        tabs = []
        for i, p in enumerate(self._context.pages):
            try:
                title = await p.title()
            except Exception:
                title = ""
            tabs.append({
                "index": i,
                "title": title,
                "url": p.url,
                "current": p is self._page,
            })
        return tabs

    async def _settle_current(self) -> None:
        """等待当前页稳定（截图前调用），避免截到加载动画而非动作结果。

        三段式：主文档加载完成（4s 上限）→ 网络空闲（3s 上限，覆盖 AJAX；
        长轮询页面会超时直接放行）→ 0.3s 渲染缓冲。
        """
        page = self._page
        if page is None:
            return
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        await asyncio.sleep(0.3)

    async def screenshot(self, full_page: bool = False) -> bytes:
        """当前标签页截图（先等待页面稳定），返回 PNG 字节。"""
        await self._ensure_connected()
        await self._settle_current()
        return await self._page.screenshot(full_page=full_page)

    # ---------- ref 注册表（供 web_page 在会话线程内使用） ----------
    def set_refs(self, refs: dict[int, str], page) -> None:
        self._refs = refs
        self._refs_page = page

    def get_ref_selector(self, ref: int) -> Optional[str]:
        return self._refs.get(ref)

    # ---------- 同步门面（工具线程/主线程调用，内部转投会话线程） ----------
    def open(self, url: Optional[str] = None, browser: Optional[str] = None) -> dict[str, Any]:
        return self.call_async(lambda s: s.ensure(browser) if url is None else s.open_tab(url, browser),
                               timeout=_DEFAULT_OP_TIMEOUT + _LAUNCH_TIMEOUT)

    def refresh_sync(self) -> dict[str, Any]:
        return self.call_async(lambda s: s.refresh())

    def switch_tab_sync(self, index: int) -> dict[str, Any]:
        return self.call_async(lambda s: s.switch_tab(index))

    def close_tab_sync(self) -> str:
        return self.call_async(lambda s: s.close_tab())

    def close_browser_sync(self) -> str:
        return self.call_async(lambda s: s.close_browser())

    def list_tabs_sync(self) -> list[dict[str, Any]]:
        return self.call_async(lambda s: s.list_tabs())

    def screenshot_sync(self, full_page: bool = False) -> bytes:
        return self.call_async(lambda s: s.screenshot(full_page))

    # ---------- 进程退出 ----------
    def _atexit_shutdown(self) -> None:
        """Agent 退出时仅断开连接，浏览器窗口保留（独立进程可被下次重连）。"""
        try:
            if self._loop and self._thread and self._thread.is_alive():
                fut = asyncio.run_coroutine_threadsafe(self._cleanup_connection(), self._loop)
                try:
                    fut.result(timeout=3)
                except Exception:
                    fut.cancel()
        except Exception:
            pass


# ---------- 模块级单例 ----------
_session: Optional[BrowserSession] = None
_session_lock = threading.Lock()


def get_browser_session() -> BrowserSession:
    """获取浏览器会话单例（browser_control 与 web_page 共用）。"""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = BrowserSession()
    return _session


# ==================== 第二部分：BrowserControl 工具 ====================

class BrowserControl(BaseTool):
    """统一浏览器控制工具（Playwright 分离进程 + CDP 架构）。

    浏览器以独立进程运行（Agent 退出后窗口保留，重启自动重连），
    登录态通过持久化 profile 保存。
    """

    args_schema: type[BaseModel] = create_model(
        "BrowserControlInput",
        action=(Literal["open", "close", "list_tabs", "switch_tab"], Field(
            default="open",
            description="操作类型：'open' 打开/刷新，'close' 关闭，'list_tabs' 列出标签页，'switch_tab' 切换标签页"
        )),
        url=(Optional[str], Field(
            default=None,
            description="URL 地址、'current' 表示刷新当前页；action=open 且留空表示打开浏览器（新标签空白页）"
        )),
        browser=(Optional[str], Field(
            default=None,
            description="浏览器引擎：'edge'（默认）/ 'chrome' / 'chromium'（Playwright 内置）"
        )),
        tab_index=(Optional[int], Field(
            default=None,
            description="标签页索引（从 0 开始），switch_tab 时必填，可用 list_tabs 查询"
        )),
    )
    name: str = "browser_control"
    description: str = (
        "控制浏览器（独立进程，跨会话存活）：打开 URL、刷新、关闭浏览器/标签页、列出与切换标签页。\n"
        "- action='open', url=None: 打开浏览器（若未运行则启动，聚焦当前页）\n"
        "- action='open', url='current': 刷新当前标签页\n"
        "- action='open', url='https://...': 新标签页打开指定 URL\n"
        "- action='close', url=None: 关闭整个浏览器\n"
        "- action='close', url='任意非空字符(例如current)': 关闭当前标签页\n"
        "- action='list_tabs': 列出全部标签页（索引、标题、URL）\n"
        "- action='switch_tab', tab_index=N: 切换到第 N 个标签页\n"
        "操作完成后返回当前页面截图。打开页面后的元素级操作请使用 web_page 工具。\n"
        "仅用于进行浏览器操作时调用，其余任何情况严禁调用。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    # ---------- 同步主逻辑，返回 (描述, artifact) ----------
    def _run(self, action: str = "open", url: Optional[str] = None,
             browser: Optional[str] = None, tab_index: Optional[int] = None) -> Tuple[str, dict]:
        session = get_browser_session()
        try:
            if action == "open":
                if url is None:
                    meta = session.open(browser=browser)
                    msg = f"浏览器已就绪，当前页: {meta.get('title') or meta.get('url') or 'about:blank'}"
                elif url.lower() == "current":
                    meta = session.refresh_sync()
                    msg = f"已刷新当前页: {meta.get('title') or meta.get('url') or 'about:blank'}"
                else:
                    meta = session.open(url=url, browser=browser)
                    msg = f"已在新标签页打开: {meta.get('url') or url}（{meta.get('title') or ''}）"
            elif action == "close":
                if url is None:
                    msg = session.close_browser_sync()
                else:
                    msg = session.close_tab_sync()
            elif action == "list_tabs":
                tabs: list[dict[str, Any]] = session.list_tabs_sync()
                if not tabs:
                    msg = "当前没有打开的标签页"
                else:
                    rows = [
                        f"[{t['index']}]{'（当前）' if t['current'] else ''} {t['title'][:40]} | {t['url'][:80]}"
                        for t in tabs
                    ]
                    msg = f"共 {len(tabs)} 个标签页:\n" + "\n".join(rows)
            elif action == "switch_tab":
                if tab_index is None:
                    msg = "switch_tab 需要 tab_index 参数（可先用 list_tabs 查询索引）"
                else:
                    meta = session.switch_tab_sync(tab_index)
                    msg = f"已切换到标签页[{tab_index}]: {meta.get('title') or meta.get('url') or 'about:blank'}"
            else:
                msg = f"不支持的操作类型: {action}"
        except Exception as e:
            return f"执行浏览器操作时出错: {e}", {}

        # 关闭整个浏览器后无页面可截，其余情况返回当前页截图
        if action == "close" and url is None:
            return msg, {}
        try:
            png = session.screenshot_sync()
            return msg, {"image_bytes": png}
        except Exception as e:
            return f"{msg}\n(截屏失败: {e})", {}

    # ---------- 异步入口 ----------
    async def _arun(self, action: str = "open", url: Optional[str] = None,
                    browser: Optional[str] = None, tab_index: Optional[int] = None) -> Tuple[str, dict]:
        return await asyncio.to_thread(self._run, action, url, browser, tab_index)
