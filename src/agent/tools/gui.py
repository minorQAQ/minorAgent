"""
GUI 自动化工具。
采用批量坐标生成方案：一次截图 + 一次 LLM 调用批量生成所有动作坐标。
N 个需要定位的动作 = 1 次 LLM 调用。
提示词中内置 One-shot 示例纠正大模型输出格式。
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import sys
import time
from typing import Any, Literal, Optional, Tuple

import pyautogui
from langchain.tools import BaseTool
from langchain_core.messages import HumanMessage
from PIL import Image
from pydantic import BaseModel, Field

from agent.core.llm import llm
import agent.utils.env_utils as env_utils

# ---------- GUI 模型实例缓存 ----------
_gui_llm = None
_gui_llm_initialized = False


def _get_gui_llm():
    """获取 GUI 工具实际使用的 LLM 实例（优先 GUI 专用模型，否则回退主模型）。"""
    global _gui_llm, _gui_llm_initialized
    if not _gui_llm_initialized:
        _gui_llm_initialized = True
        try:
            from agent.core.config_manager import get_gui_llm
            _gui_llm = get_gui_llm()
        except Exception:
            _gui_llm = None
    return _gui_llm if _gui_llm is not None else llm


# ---------- 类型定义 ----------
GUIAction = Literal[
    "click",
    "type",
    "drag_and_drop",
    "scroll",
    "hotkey",
    "hold_and_press",
    "wait",
    "screenshot",
    "move_to",
]

GUITargetType = Literal["auto", "button", "input", "checkbox", "list_item", "link"]


class GUIActionItem(BaseModel):
    """单个 GUI 动作。"""
    action: GUIAction = Field(..., description="GUI 操作类型。")
    element_description: Optional[str] = Field(
        default=None,
        description="目标元素的自然语言描述。对于 type 操作，提供此项会先定位并点击目标输入框再输入。",
    )
    ending_description: Optional[str] = Field(
        default=None,
        description="拖拽终点的自然语言描述（仅 drag_and_drop 使用）。",
    )
    text: str = Field(default="", description="要输入的文本。")
    overwrite: bool = Field(default=False, description="输入前全选已有文本。")
    enter: bool = Field(default=False, description="输入后按回车。")
    num_clicks: int = Field(default=1, description="鼠标点击次数。")
    button_type: Literal["left", "middle", "right"] = Field(default="left", description="鼠标按键。")
    hold_keys: list[str] = Field(default_factory=list, description="点击或拖拽时按住的功能键。")
    keys: list[str] = Field(default_factory=list, description="快捷键按键 / 敲击按键。")
    press_keys: list[str] = Field(default_factory=list, description="按住 hold_keys 时敲击的按键。")
    hotkey_count: int = Field(default=1, description="快捷键重复按下次数，仅 hotkey 操作用。")
    clicks: int = Field(default=0, description="滚轮量，负数为向下。")
    shift: bool = Field(default=False, description="水平滚动（True 时为横向）。")
    wait_seconds: float = Field(default=0.5, description="等待秒数。")
    target_type: GUITargetType = Field(
        default="auto",
        description="目标 UI 元素类型：checkbox / input / list_item / button / link / auto。",
    )


class GUIToolInput(BaseModel):
    actions: list[GUIActionItem] = Field(
        default_factory=list,
        description="有序 GUI 操作列表，按顺序依次执行。空列表则仅返回当前截图。",
    )


# ---------- 图片工具函数 ----------
def _get_gui_region() -> dict | None:
    """获取当前 GUI 操作显示器区域，失败返回 None（全屏）。"""
    try:
        from agent.core.config_manager import get_active_monitor_region
        return get_active_monitor_region()
    except Exception:
        return None


def _screenshot_png() -> Tuple[bytes, Tuple[int, int]]:
    region = _get_gui_region()
    if region:
        image = pyautogui.screenshot(
            region=(region["x"], region["y"], region["width"], region["height"])
        )
    else:
        image = pyautogui.screenshot()
    width, height = image.size
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue(), (width, height)


def _resize_for_grounding(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image = image.resize(
        (env_utils.GROUNDING_WIDTH, env_utils.GROUNDING_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _image_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


# ---------- 坐标解析与转换 ----------
def _parse_batch_coordinates(text: str) -> list[Tuple[int, int]]:
    """解析批量坐标输出。

    按行提取坐标对，每行取第一对有效的 (x, y)。
    兼容格式：
        - "(50, 960)"
        - "(100,200)"
        - "1, (50, 960)"  （带编号前缀）
        - "1:(100,200)"   （带编号前缀）

    所有坐标会被裁剪到 [0, GROUNDING-1] × [0, GROUNDING-1]。
    """
    W, H = env_utils.GROUNDING_WIDTH - 1, env_utils.GROUNDING_HEIGHT - 1
    coordinates: list[Tuple[int, int]] = []

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        matches = re.findall(r"\(\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*\)", line)
        if matches:
            x = int(float(matches[0][0]))
            y = int(float(matches[0][1]))
            x = max(0, min(W, x))
            y = max(0, min(H, y))
            coordinates.append((x, y))

    return coordinates


def _scale_to_screen(coords: Tuple[int, int], screen_size: Tuple[int, int]) -> Tuple[int, int]:
    """将 grounding 坐标映射到绝对屏幕坐标（考虑 GUI 操作区域偏移）。"""
    screen_width, screen_height = screen_size
    x, y = coords
    local_x = round(x * screen_width / env_utils.GROUNDING_WIDTH)
    local_y = round(y * screen_height / env_utils.GROUNDING_HEIGHT)
    region = _get_gui_region()
    offset_x = region["x"] if region else 0
    offset_y = region["y"] if region else 0
    return (offset_x + local_x, offset_y + local_y)


# ---------- 文本输入辅助 ----------
def _type_text(text: str) -> None:
    if not text:
        return
    has_unicode = any(ord(ch) > 127 for ch in text)
    if has_unicode:
        try:
            import pyperclip
            pyperclip.copy(text)
            modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(modifier, "v")
            return
        except Exception:
            pass
    pyautogui.write(text)


def _select_all_and_clear() -> None:
    modifier = "command" if sys.platform == "darwin" else "ctrl"
    pyautogui.hotkey(modifier, "a")
    pyautogui.press("backspace")


def _with_hold_keys_down(keys: list[str]) -> None:
    for key in keys or []:
        pyautogui.keyDown(key)


def _with_hold_keys_up(keys: list[str]) -> None:
    for key in reversed(keys or []):
        pyautogui.keyUp(key)


# ---------- target_type 辅助：提供类型特定的定位提示 ----------
def _target_type_instructions(target_type: str) -> str:
    """根据目标 UI 元素类型，返回针对性的定位提示。"""
    normalized = (target_type or "auto").strip().lower()
    instructions = {
        "checkbox": (
            "Target type: checkbox. Return the checkbox/radio circle or square itself as the click point, "
            "not the label row. The point should be at the center of the small check control only. "
            "Do not click nearby agreement/privacy/service link text."
        ),
        "input": (
            "Target type: input. Return a point inside the editable text box area where typing will focus the field. "
            "Choose the center of the text area."
        ),
        "list_item": (
            "Target type: list_item. Return the full row/list item including icon/avatar and label, "
            "and choose the row center as the click point."
        ),
        "button": (
            "Target type: button. Return the full clickable button and choose its center point. "
            "Make sure the point is on the button itself, not on adjacent text."
        ),
        "link": (
            "Target type: link. Return only the clickable text/link area and choose the text center as the point."
        ),
    }
    return instructions.get(normalized, "")


def _infer_target_type(element_description: str, target_type: str) -> str:
    """根据元素描述自动推断 target_type（仅当 target_type=\"auto\" 时生效）。"""
    normalized = (target_type or "auto").strip().lower()
    if normalized != "auto":
        return normalized

    desc = element_description or ""
    checkbox_terms = ["复选框", "勾选框", "勾选", "已阅读", "同意", "协议", "隐私", "服务协议", "用户协议", "checkbox"]
    if any(term in desc for term in checkbox_terms):
        return "checkbox"

    input_terms = ["输入框", "输入","文本框", "消息框", "编辑框", "输入栏", "input", "textbox"]
    if any(term in desc for term in input_terms):
        return "input"

    list_terms = ["列表", "联系人", "聊天列表", "文件列表", "这一行", "整行", "list"]
    if any(term in desc for term in list_terms):
        return "list_item"

    button_terms = ["按钮", "登录", "确定", "取消", "发送", "button"]
    if any(term in desc for term in button_terms):
        return "button"

    return "auto"


# =====================================================================
#  核心工具类
# =====================================================================
class GUITool(BaseTool):
    """GUI 自动化工具。

    坐标生成阶段采用批量方案：一次截图 + 全部 query 批量输入 LLM + 一次性解析所有坐标。
    N 个需要定位的动作 = 1 次 LLM 调用。
    """

    args_schema: type[BaseModel] = GUIToolInput
    name: str = "gui_tool"
    description: str = (
        "GUI 自动化工具。通过截图视觉定位桌面元素，将坐标映射到真实屏幕，并执行 pyautogui 动作。"
        "接收一个有序的动作列表，按顺序依次执行。每个动作项支持的操作：click（点击）、type（输入文本，可通过 element_description 指定目标输入框自动聚焦）、"
        "drag_and_drop（拖拽）、scroll（滚动）、hotkey（快捷键）、"
        "hold_and_press（按住组合键并敲击）、wait（等待）、screenshot（截图）、move_to（移动鼠标）。\n"
        "【type 使用说明】type 支持 element_description 参数来描述在哪里输入。当提供了 element_description 时，"
        "会先视觉定位并点击目标输入框，然后再输入文本，无需单独调用 click。不提供 element_description 则直接在当前焦点输入。\n"
        "所有动作执行完毕后，返回当前屏幕的截图。\n"
        "\n"
        "【网页滚动提示】浏览器中向下滚动网页推荐使用快捷键，而非 scroll 滚轮："
        "{\"action\":\"hotkey\",\"keys\":[\"space\"]}（空格键即 Page Down）。"
        "向上滚动可使用 {\"action\":\"hotkey\",\"keys\":[\"shift\",\"space\"]}。\n"
        "\n"
        "【下拉框处理策略】操作下拉选择框直接使用 type 动作即可，系统会自动匹配选项：\n"
        "  {\"action\":\"type\",\"element_description\":\"目标下拉框\",\"text\":\"选项名称\"}\n"
        "\n"
        "示例：\n"
        "- 登录表单：{\"actions\": ["
        "{\"action\":\"type\",\"element_description\":\"用户名输入框\",\"text\":\"admin\"},"
        "{\"action\":\"type\",\"element_description\":\"密码输入框\",\"text\":\"123456\",\"enter\":true}"
        "]}\n"
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    # ---------- 批量坐标生成核心 ----------
    def _collect_grounding_queries(self, actions: list[GUIActionItem]) -> list[Tuple[int, str, str, str]]:
        """遍历所有动作，收集需要视觉定位的 query。

        返回 [(action_index, query_type, query_text, target_type), ...]
        query_type: "element" (元素描述) 或 "ending" (拖拽终点)。
        target_type: 推断后的 UI 元素类型，用于定位提示。
        对于 type 操作且无 element_description 的，不收集（无需定位）。
        """
        queries: list[Tuple[int, str, str, str]] = []
        for idx, act in enumerate(actions):
            action = str(act.action).strip()
            if action in ("screenshot", "wait", "hotkey", "hold_and_press"):
                continue

            if action in ("click", "scroll", "move_to"):
                desc = (act.element_description or "").strip()
                if desc:
                    ttype = _infer_target_type(desc, act.target_type or "auto")
                    queries.append((idx, "element", desc, ttype))
                continue

            if action == "type":
                desc = (act.element_description or "").strip()
                if desc:
                    ttype = _infer_target_type(desc, act.target_type or "auto")
                    queries.append((idx, "element", desc, ttype))
                continue

            if action == "drag_and_drop":
                start_desc = (act.element_description or "").strip()
                end_desc = (act.ending_description or "").strip()
                if start_desc:
                    stype = _infer_target_type(start_desc, act.target_type or "auto")
                    queries.append((idx, "element", start_desc, stype))
                if end_desc:
                    etype = _infer_target_type(end_desc, act.target_type or "auto")
                    queries.append((idx, "ending", end_desc, etype))
                continue

        return queries

    def _build_batch_prompt(self, queries: list[Tuple[int, str, str, str]]) -> str:
        """构建包含 One-shot 示例的批量定位 prompt，每项查询附加 target_type 指令。"""
        W = env_utils.GROUNDING_WIDTH
        H = env_utils.GROUNDING_HEIGHT

        numbered = []
        for i, (act_idx, qtype, qtext, ttype) in enumerate(queries, 1):
            label = f"action{act_idx + 1}_{qtype}"
            tip = _target_type_instructions(ttype)
            if tip:
                numbered.append(f"{i}. [{label}] {qtext}\n   {tip}")
            else:
                numbered.append(f"{i}. [{label}] {qtext}")
        query_text = "\n\n".join(numbered)

        prompt = (
            "You are a visual grounding model for desktop GUI control.\n"
            f"The screenshot has been resized to exactly {W}x{H} pixels.\n"
            "Your task is to locate MULTIPLE target elements in the same image in a single response.\n"
            "\n"
            "=== OUTPUT FORMAT (STRICT) ===\n"
            "You MUST output one line per query in the EXACT format below:\n"
            "  (<x>, <y>)\n"
            "Where:\n"
            "  - x: horizontal pixel coordinate (integer, 0 = leftmost)\n"
            "  - y: vertical pixel coordinate (integer, 0 = topmost)\n"
            "\n"
            "=== ONE-SHOT EXAMPLE ===\n"
            "Scenario: A desktop screenshot ({W}x{H}) showing a browser with multiple UI elements.\n"
            "\n"
            "Queries:\n"
            "1. [action1_element] the browser address bar at the top of the window\n"
            "2. [action2_element] the search input field in the main content area\n"
            "3. [action3_element] the search button next to the input field\n"
            "4. [action3_ending] the first search result link after clicking search\n"
            "\n"
            "Expected output (four lines, one per query):\n"
            f"({W // 2}, {H // 6})\n"
            f"({W // 2}, {H // 3})\n"
            f"({W // 2 + 200}, {H // 3})\n"
            f"({W // 2}, {H // 2 + 50})\n"
            "\n"
            "=== NOW YOUR TURN ===\n"
            "Locate the following elements in the provided screenshot:\n"
            f"{query_text}\n"
            "\n"
            "=== RULES (FAILURE TO FOLLOW = INCORRECT) ===\n"
            "1. Output exactly one line per query, in the SAME order (1, 2, 3, ...).\n"
            "2. Each line format: `(<integer_x>, <integer_y>)` — nothing else on that line.\n"
            "3. NO explanations, NO markdown, NO additional text before or after the coordinate lines.\n"
            "4. Coordinates must be integers in range x=[0,{W-1}] y=[0,{H-1}].\n"
            "5. If you genuinely cannot find an element, output your best reasonable guess for its coordinates.\n"
            "6. Do NOT wrap the output in code fences (```), quotes, or JSON.\n"
            "7. For a sequence of operations on the same page, generate coordinates strictly in action order. "
            "Each coordinate pair corresponds to one step of the GUI operation sequence. "
            "(对于一个页面中的操作需要按顺序进行单步多GUI操作)\n"
        )
        return prompt

    def _batch_ground_elements(
        self, queries: list[Tuple[int, str, str, str]], screen_size: Tuple[int, int]
    ) -> dict[Tuple[int, str], Tuple[int, int]]:
        """一次截图 + 一次 LLM 调用，批量生成所有目标元素的坐标。

        参数:
            queries: [(action_index, query_type, query_text, target_type), ...]
            screen_size: (screen_width, screen_height)

        返回:
            {(action_index, query_type): (screen_x, screen_y), ...}
        """
        if not queries:
            return {}

        # 1. 截图
        raw_png, _ = _screenshot_png()
        grounding_png = _resize_for_grounding(raw_png)

        # 2. 构建 prompt + 单次 LLM 调用
        prompt = self._build_batch_prompt(queries)
        response = _get_gui_llm().invoke(
            [
                HumanMessage(
                    content=[
                        {"type": "image_url", "image_url": {"url": _image_data_url(grounding_png)}},
                        {"type": "text", "text": prompt},
                    ]
                )
            ]
        )
        response_text = str(response.content).strip()

        # 3. 解析坐标
        coords = _parse_batch_coordinates(response_text)

        # 4. 建立映射 (action_index, query_type) → (screen_x, screen_y)
        result: dict[Tuple[int, str], Tuple[int, int]] = {}
        for i, (act_idx, qtype, _qtext, _ttype) in enumerate(queries):
            if i < len(coords):
                result[(act_idx, qtype)] = _scale_to_screen(coords[i], screen_size)

        return result

    # ---------- 截图 artifact ----------
    def _artifact_screenshot(self) -> dict:
        try:
            image_bytes, _ = _screenshot_png()
            resized_bytes = _resize_for_grounding(image_bytes)
            return {"image_bytes": resized_bytes}
        except Exception:
            return {}

    # ---------- 顶层入口 ----------
    def _run(self, actions: list[GUIActionItem] | None = None) -> Tuple[str, dict]:
        try:
            if not actions:
                return ("", self._artifact_screenshot())

            # 1. 先截图一次，获取屏幕尺寸
            _, screen_size = _screenshot_png()

            # 2. 批量定位：一次 LLM 调用生成所有动作需要的坐标
            queries = self._collect_grounding_queries(actions)
            coords_map = self._batch_ground_elements(queries, screen_size)

            # 3. 构建 (action_index, query_type) → (x, y) 查找表
            action_coords: dict[int, dict[str, Tuple[int, int]]] = {}
            for (act_idx, qtype), coord in coords_map.items():
                action_coords.setdefault(act_idx, {})[qtype] = coord

            # 4. 顺序执行动作列表
            result_messages: list[str] = []
            for idx, act in enumerate(actions, start=1):
                if act.action == "screenshot":
                    result_messages.append(f"{idx}. Screenshot (skipped, final screenshot will be taken)")
                    continue

                act_idx = idx - 1  # 0-indexed
                cached = action_coords.get(act_idx, {})
                try:
                    msg = self._dispatch(cached_coords=cached, **act.model_dump())
                    result_messages.append(f"{idx}. {msg}")
                except Exception as exc:
                    error_msg = f"{idx}. [GUI Error] {act.action}: {exc}"
                    result_messages.append(error_msg)
                    print(error_msg)

                time.sleep(1)

            final_text = "\n".join(result_messages)
            return (final_text, self._artifact_screenshot())
        except Exception as e:
            return (f"[ERROR] gui_tool 执行出错: {str(e)}", {})

    def _dispatch(self, cached_coords: dict[str, Tuple[int, int]], **kwargs: Any) -> str:
        """分发到具体动作方法，传入已缓存的坐标（cached_coords = {"element": (x,y), "ending": (x,y)}）。"""
        action = str(kwargs["action"]).strip()
        if action == "click":
            return self._click(cached_coords, **kwargs)
        if action == "type":
            return self._type(cached_coords, **kwargs)
        if action == "drag_and_drop":
            return self._drag_and_drop(cached_coords, **kwargs)
        if action == "scroll":
            return self._scroll(cached_coords, **kwargs)
        if action == "hotkey":
            return self._hotkey(**kwargs)
        if action == "hold_and_press":
            return self._hold_and_press(**kwargs)
        if action == "wait":
            seconds = float(kwargs["wait_seconds"])
            time.sleep(seconds)
            return f"Waited {seconds:.2f} seconds."
        if action == "move_to":
            return self._move_to(cached_coords, **kwargs)
        raise ValueError(f"unsupported GUI action: {action}")

    # ---------- 各动作实现 ----------
    def _click(self, cached_coords: dict[str, Tuple[int, int]], **kwargs: Any) -> str:
        desc = (kwargs.get("element_description") or "").strip()
        if desc and "element" in cached_coords:
            x, y = cached_coords["element"]
        else:
            x, y = pyautogui.position()
        hold_keys = kwargs["hold_keys"]
        _with_hold_keys_down(hold_keys)
        try:
            pyautogui.click(x, y, clicks=max(1, int(kwargs["num_clicks"])), button=kwargs["button_type"])
        finally:
            _with_hold_keys_up(hold_keys)
        return f"Clicked target at ({x},{y})."

    def _type(self, cached_coords: dict[str, Tuple[int, int]], **kwargs: Any) -> str:
        element_desc = (kwargs.get("element_description") or "").strip()
        if element_desc and "element" in cached_coords:
            x, y = cached_coords["element"]
            pyautogui.click(x, y)
            if kwargs["overwrite"]:
                _select_all_and_clear()
            _type_text(kwargs["text"])
            if kwargs["enter"]:
                pyautogui.press("enter")
            return f"Clicked target and typed text at ({x},{y})."
        # 不提供 element_description：直接在当前焦点输入
        if kwargs["overwrite"]:
            _select_all_and_clear()
        _type_text(kwargs["text"])
        if kwargs["enter"]:
            pyautogui.press("enter")
        return "Typed text."

    def _drag_and_drop(self, cached_coords: dict[str, Tuple[int, int]], **kwargs: Any) -> str:
        x1, y1 = cached_coords.get("element", pyautogui.position())
        x2, y2 = cached_coords.get("ending", pyautogui.position())
        hold_keys = kwargs["hold_keys"]
        pyautogui.moveTo(x1, y1)
        _with_hold_keys_down(hold_keys)
        try:
            pyautogui.dragTo(x2, y2, duration=1.0, button="left")
            pyautogui.mouseUp()
        finally:
            _with_hold_keys_up(hold_keys)
        return f"Dragged from ({x1},{y1}) to ({x2},{y2})."

    def _move_to(self, cached_coords: dict[str, Tuple[int, int]], **kwargs: Any) -> str:
        x, y = cached_coords.get("element", pyautogui.position())
        pyautogui.moveTo(x, y)
        return f"Moved mouse to ({x},{y})."

    def _scroll(self, cached_coords: dict[str, Tuple[int, int]], **kwargs: Any) -> str:
        x, y = cached_coords.get("element", pyautogui.position())
        pyautogui.moveTo(x, y)
        time.sleep(0.1)
        clicks = int(kwargs["clicks"])
        if kwargs["shift"]:
            pyautogui.hscroll(clicks)
        else:
            pyautogui.vscroll(clicks)
        return f"Scrolled by {clicks} at ({x},{y})."

    def _hotkey(self, **kwargs: Any) -> str:
        keys = kwargs["keys"]
        if not keys:
            raise ValueError("keys is required for hotkey")
        count = max(1, int(kwargs.get("hotkey_count", 1)))
        for _ in range(count):
            pyautogui.hotkey(*keys)
        return f"Pressed hotkey {keys} x{count}." if count > 1 else f"Pressed hotkey {keys}."

    def _hold_and_press(self, **kwargs: Any) -> str:
        hold_keys = kwargs["hold_keys"]
        press_keys = kwargs["press_keys"] or kwargs["keys"]
        if not press_keys:
            raise ValueError("press_keys or keys is required for hold_and_press")
        _with_hold_keys_down(hold_keys)
        try:
            pyautogui.press(press_keys)
        finally:
            _with_hold_keys_up(hold_keys)
        return f"Held {hold_keys} and pressed {press_keys}."

    async def _arun(self, actions: list[GUIActionItem] | None = None) -> Tuple[str, dict]:
        return await asyncio.to_thread(self._run, actions)
