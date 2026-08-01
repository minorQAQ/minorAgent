from __future__ import annotations

import io
import sys
import time
import webbrowser
import asyncio
from typing import Optional, Literal, Tuple

import pyautogui
from PIL import Image
from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model

import agent.utils.env_utils as env_utils


class BrowserControl(BaseTool):
    """统一浏览器控制工具：支持打开/关闭浏览器、刷新/关闭标签页、打开指定 URL"""

    args_schema: type[BaseModel] = create_model(
        "BrowserControlInput",
        action=(Literal["open", "close"], Field(
            default="open",
            description="操作类型：'open' 打开/刷新，'close' 关闭"
        )),
        url=(Optional[str], Field(
            default=None,
            description="URL 地址、'current' 表示当前页，留空则操作整个浏览器窗口"
        )),
        browser=(Optional[str], Field(
            default=None,
            description="浏览器名称，如 'edge', 'chrome', 'firefox'，不指定则使用系统默认"
        )),
    )
    name: str = "browser_control"
    description: str = (
        "统一控制浏览器：打开/关闭浏览器、刷新/关闭标签页、打开指定 URL。\n"
        "- action='open', url=None: 打开浏览器首页\n"
        "- action='open', url='current': 刷新当前标签页\n"
        "- action='open', url='https://...': 在新标签页打开指定 URL\n"
        "- action='close', url=None: 关闭整个浏览器窗口\n"
        "- action='close', url='任意非空字符(例如current)': 关闭当前标签页\n"
        "操作完成后会返回当前屏幕截图，帮助判断操作是否成功。"
        "仅用于进行浏览器操作时调用，其余任何情况严禁调用。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    # ---------- 辅助方法（与原版相同，无改动） ----------
    def _get_browser_info(self, browser_name: Optional[str]):
        """解析浏览器名称，返回 webbrowser 控制器与窗口标题关键字。"""
        if browser_name is None:
            return webbrowser.get(), None
        name_lower = browser_name.lower().strip()
        if name_lower not in env_utils.BROWSER_MAP:
            raise ValueError(f"不支持的浏览器: {browser_name}，支持: {', '.join(env_utils.BROWSER_MAP.keys())}")
        reg_name, title_keyword = env_utils.BROWSER_MAP[name_lower]
        try:
            controller = webbrowser.get(reg_name)
        except webbrowser.Error:
            controller = webbrowser.get(browser_name)
        return controller, title_keyword

    def _activate_window(self, title_keyword: str) -> bool:
        """在 Windows 上按标题关键字激活浏览器窗口（非 Win32 返回 False）。"""
        if sys.platform != "win32":
            return False
        try:
            time.sleep(0.3)
            windows = pyautogui.getWindowsWithTitle(title_keyword)
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                return True
        except Exception:
            pass
        return False

    def _send_keys(self, *keys):
        """通过 pyautogui 发送组合键。"""
        pyautogui.hotkey(*keys)

    # ---------- 核心操作（返回操作结果描述） ----------
    def _try_activate_any_browser(self) -> bool:
        """尝试激活任意已知浏览器窗口（不指定 browser 时的回退方案）。"""
        for _reg_name, title_keyword in env_utils.BROWSER_MAP.values():
            if self._activate_window(title_keyword):
                return True
        return False

    def _open_action(self, url: Optional[str], browser: Optional[str]) -> str:
        """执行打开首页、刷新当前页或打开指定 URL。"""
        controller, title_keyword = self._get_browser_info(browser)
        if url is None:
            controller.open("about:blank")
            if title_keyword:
                self._activate_window(title_keyword)
            else:
                self._try_activate_any_browser()
            browser_info = f" (使用 {browser})" if browser else ""
            return f"已打开浏览器首页{browser_info}"
        elif url.lower() == "current":
            if title_keyword:
                if not self._activate_window(title_keyword):
                    return f"未找到 {browser or '默认'} 浏览器窗口，无法刷新"
            time.sleep(0.2)
            if sys.platform == "darwin":
                self._send_keys("command", "r")
            else:
                self._send_keys("f5")
            return "已刷新当前标签页"
        else:
            controller.open(url)
            if title_keyword:
                self._activate_window(title_keyword)
            else:
                self._try_activate_any_browser()
            # 等待浏览器窗口出现并开始加载
            time.sleep(1.0)
            return f"已尝试打开 URL: {url}"

    def _close_action(self, url: Optional[str], browser: Optional[str]) -> str:
        """执行关闭浏览器窗口或当前标签页。"""
        _, title_keyword = self._get_browser_info(browser)
        if url is None:
            if title_keyword:
                if not self._activate_window(title_keyword):
                    return f"未找到 {browser or '默认'} 浏览器窗口，无法关闭"
            else:
                self._try_activate_any_browser()
            time.sleep(0.2)
            if sys.platform == "darwin":
                self._send_keys("command", "q")
            else:
                self._send_keys("alt", "f4")
            return "已尝试关闭浏览器窗口"
        else:
            if title_keyword:
                if not self._activate_window(title_keyword):
                    return f"未找到 {browser or '默认'} 浏览器窗口，无法关闭标签页"
            else:
                self._try_activate_any_browser()
            time.sleep(0.2)
            if sys.platform == "darwin":
                self._send_keys("command", "w")
            else:
                self._send_keys("ctrl", "w")
            return "已尝试关闭当前标签页"

    # ---------- 同步主逻辑，返回 (描述, artifact) ----------
    def _run(self, action: str = "open", url: Optional[str] = None, browser: Optional[str] = None) -> Tuple[str, dict]:
        try:
            if action == "open":
                msg = self._open_action(url, browser)
            elif action == "close":
                msg = self._close_action(url, browser)
            else:
                msg = f"不支持的操作类型: {action}"
        except Exception as e:
            msg = f"执行浏览器操作时出错: {e}"

        # 无论操作是否成功，都尝试截屏（等待窗口切换）
        time.sleep(0.3)
        try:
            # 先尝试获取 GUI 操作区域，限定截屏范围
            try:
                from agent.core.config_manager import get_active_monitor_region
                region = get_active_monitor_region()
            except Exception:
                region = None
            if region:
                pil_img = pyautogui.screenshot(region=(region["x"], region["y"], region["width"], region["height"]))
            else:
                pil_img = pyautogui.screenshot()
            pil_img = pil_img.resize((env_utils.GROUNDING_WIDTH, env_utils.GROUNDING_HEIGHT), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            raw_png = buf.getvalue()
            return msg, {"image_bytes": raw_png}
        except Exception as e:
            return f"{msg}\n(截屏失败: {e})", {}

    # ---------- 异步入口 ----------
    async def _arun(self, action: str = "open", url: Optional[str] = None, browser: Optional[str] = None) -> Tuple[str, dict]:
        return await asyncio.to_thread(self._run, action, url, browser)
