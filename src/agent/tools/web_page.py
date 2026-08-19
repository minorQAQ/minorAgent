"""web_page 工具：对当前浏览器页面执行 DOM 级批量操作。

定位方式（无需视觉 grounding，毫秒级命中）:
    - ref: snapshot 返回的元素序号
    - selector: Playwright 选择器（CSS / text=登录 / role=button / xpath= 等，
      纯中文或含空格的字符串会自动按 text= 处理）

批量语义:
    actions 列表顺序执行，首错即停并报告失败步骤；每次调用结束返回页面截图
    artifact（复用 nodes.py 的 image_bytes 注入链路）。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Literal, Optional, Tuple

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from .browser_control import get_browser_session, normalize_url

# ---------- snapshot / extract 注入页面的 JS ----------
_SNAPSHOT_JS = """() => {
  const SELECTOR = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [onclick], [contenteditable="true"]';
  const els = Array.from(document.querySelectorAll(SELECTOR));
  const out = [];
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  };
  const cssPath = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let cur = el, depth = 0;
    while (cur && cur.nodeType === 1 && depth < 6) {
      let seg = cur.tagName.toLowerCase();
      if (seg === 'html' || seg === 'body') break;
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (same.length > 1) seg += ':nth-of-type(' + (same.indexOf(cur) + 1) + ')';
      }
      parts.unshift(seg);
      cur = parent;
      depth += 1;
      if (cur && cur.id) { parts.unshift('#' + CSS.escape(cur.id)); break; }
    }
    return parts.join(' > ');
  };
  for (const el of els) {
    try {
      if (!isVisible(el)) continue;
      const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
      out.push({
        sel: cssPath(el),
        tag: el.tagName.toLowerCase(),
        text: text,
        aria: (el.getAttribute('aria-label') || '').slice(0, 40),
        ph: (el.getAttribute('placeholder') || '').slice(0, 40),
        href: (el.getAttribute('href') || '').slice(0, 80),
        type: el.getAttribute('type') || ''
      });
      if (out.length >= 80) break;
    } catch (e) {}
  }
  return { title: document.title, url: location.href, elements: out };
}"""

_EXTRACT_JS = """(sel) => {
  const el = sel ? document.querySelector(sel) : document.body;
  if (!el) return null;
  return { title: document.title, url: location.href, text: el.innerText || '' };
}"""


# 选择器结构字符：出现任意一个即视为"已是选择器语法"，不做 text= 自动转换
_SELECTOR_META_RE = re.compile(r"[\[\]#.:>~+*@=()]")


def _normalize_selector(sel: str) -> str:
    """选择器归一化：仅对不含结构字符的纯中文短语自动加 text= 前缀。

    注意：
    - input[placeholder="用户名"]、button:has-text("提交") 等是合法 CSS /
      Playwright 引擎语法（中文出现在属性值/伪类参数里），必须原样透传，
      不能因"含中文"被误转成 text=xxx
    - 含空格的 ASCII 串可能是 CSS 后代选择器（如 "h2 a"），同样不转换
    """
    s = (sel or "").strip()
    if not s:
        raise ValueError("selector 不能为空")
    # 已带 Playwright 选择器引擎前缀
    if re.match(r"^(css|text|xpath|id|role|placeholder|label|alt|title|testid|data-testid|nth|visible)=|^(>>|internal:)", s):
        return s
    if s.startswith("//") or s.startswith(".."):
        return "xpath=" + s
    # 纯中文短语（无任何选择器结构字符）→ text= 引擎匹配
    if re.search(r"[\u4e00-\u9fff]", s) and not _SELECTOR_META_RE.search(s):
        return "text=" + s
    return s


# ---------- 动作定义 ----------
WebPageAction = Literal[
    "goto", "snapshot", "click", "fill", "hover", "select",
    "scroll", "press", "wait", "extract", "back", "forward",
    "reload", "screenshot", "eval_js",
]


class WebPageActionItem(BaseModel):
    """单个页面动作。"""
    action: WebPageAction = Field(..., description="动作类型。")
    url: str = Field(default="", description="目标 URL（goto 用，无协议头自动补 https://）。")
    ref: Optional[int] = Field(default=None, description="snapshot 返回的元素序号（优先于 selector）。")
    selector: Optional[str] = Field(
        default=None,
        description="Playwright 选择器，合法写法原样传入即可：CSS（#id、.cls、input[placeholder=\"用户名\"]）、"
                    "text=登录、placeholder=用户名、role=button[name=\"提交\"]、xpath=//div。"
                    "仅纯中文短语会自动按 text= 匹配；不要给 CSS/引擎语法外再套 text= 前缀。",
    )
    text: str = Field(default="", description="fill 要输入的文本。")
    press_enter: bool = Field(default=False, description="fill 输入完成后按回车（触发表单提交/搜索）。")
    button: Literal["left", "right"] = Field(default="left", description="鼠标按键（click 用）。")
    double_click: bool = Field(default=False, description="是否双击（click 用）。")
    key: str = Field(default="", description="按键（press 用），如 Enter、Control+a、ArrowDown。")
    clicks: int = Field(default=0, description="滚轮量（scroll 用，与 gui_tool 一致：负数为向下）。")
    scroll_to: Literal["", "top", "bottom"] = Field(default="", description="滚动到页面顶部/底部（scroll 用，优先于 clicks）。")
    value: str = Field(default="", description="select 下拉选项的 value 或可见文本。")
    wait_seconds: float = Field(default=1.0, description="等待秒数（wait 用）。")
    wait_selector: str = Field(default="", description="等待该选择器元素出现（wait 用，优先于固定秒数）。")
    full_page: bool = Field(default=False, description="是否整页截图（screenshot 用）。")
    max_length: int = Field(default=3000, description="extract 文本最大返回长度。")
    js: str = Field(default="", description="eval_js 要执行的 JS 表达式或箭头函数。")


def _short_url(url: str, limit: int = 100) -> str:
    """结果文本中的 URL 截断（data: 或超长 query 的 URL 全量回显会污染上下文）。"""
    u = url or ""
    return u if len(u) <= limit else u[:limit] + "..."


class WebPageInput(BaseModel):
    actions: list[WebPageActionItem] = Field(
        default_factory=list,
        description="有序页面动作列表，按顺序依次执行；空列表仅返回当前页面截图。",
    )


class WebPage(BaseTool):
    """DOM 级网页操作工具：通过 snapshot 序号或选择器精准操作页面元素。"""

    args_schema: type[BaseModel] = WebPageInput
    name: str = "web_page"
    description: str = (
        "对浏览器当前页面执行 DOM 级精准操作（毫秒级，优于 gui_tool 视觉定位）。\n"
        "典型流程：browser_control 打开 URL → web_page snapshot 获取元素清单 → 按 ref/selector 批量操作。\n"
        "支持动作：goto/snapshot/click/fill/hover/select/scroll/press/wait/extract/back/forward/reload/screenshot/eval_js。\n"
        "元素定位：优先用 snapshot 返回的 ref 序号；用 selector 时合法语法原样传入"
        "（CSS：input[placeholder=\"用户名\"]；引擎：text=登录 / placeholder=用户名 / role=button[name=\"提交\"] / xpath=//div）。\n"
        "同一页面的连续操作必须合并为一次调用（actions 传多个动作），页面跳转后需重新 snapshot。\n"
        "改变页面状态的操作会附操作后截图；纯观察批次（snapshot/extract）不附图。\n"
        "仅用于已打开的浏览器页面操作，其余情况严禁调用。"
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    # ---------- 单个动作执行（会话线程内运行） ----------
    async def _exec_action(self, session, item: WebPageActionItem) -> str:
        page = session._page

        def _resolve() -> str:
            """解析元素选择器：ref 优先，其次 selector（归一化）。"""
            if item.ref is not None:
                sel = session.get_ref_selector(item.ref)
                if sel is None:
                    raise ValueError(f"ref={item.ref} 不存在（页面可能已跳转），请重新执行 snapshot")
                return sel
            if not item.selector:
                raise ValueError("该动作需要提供 ref 或 selector 定位元素")
            return _normalize_selector(item.selector)

        async def _loc_op(op, sel: str):
            """执行 locator 操作，定位超时时给出 snapshot+ref 引导提示。"""
            try:
                return await op()
            except Exception as e:
                if type(e).__name__ == "TimeoutError":
                    raise ValueError(
                        f"元素定位超时（10s）: {sel}。建议先执行 snapshot 获取元素清单，再用 ref 序号定位"
                    ) from e
                raise

        if item.action == "goto":
            if not item.url:
                raise ValueError("goto 需要 url")
            await page.goto(normalize_url(item.url), wait_until="domcontentloaded")
            return f"已打开 {_short_url(page.url)}（{await page.title()}）"

        if item.action == "snapshot":
            data = await page.evaluate(_SNAPSHOT_JS)
            elements = data.get("elements", [])
            refs = {i + 1: e["sel"] for i, e in enumerate(elements)}
            session.set_refs(refs, page)
            lines = [f"页面: {data.get('title', '')} | {data.get('url', '')}"]
            lines.append(f"可交互元素共 {len(elements)} 个（click/fill 等用 ref 序号定位）:")
            for i, e in enumerate(elements, 1):
                tag = e["tag"]
                if tag == "input" and e.get("type"):
                    tag += f"[{e['type']}]"
                parts = [f"[{i}] {tag}"]
                if e.get("text"):
                    parts.append(f"\"{e['text']}\"")
                if e.get("aria"):
                    parts.append(f"aria=\"{e['aria']}\"")
                if e.get("ph"):
                    parts.append(f"placeholder=\"{e['ph']}\"")
                if e.get("href"):
                    parts.append(f"-> {e['href']}")
                lines.append(" ".join(parts))
            return "\n".join(lines)

        if item.action == "click":
            sel = _resolve()
            loc = page.locator(sel)
            if item.double_click:
                await _loc_op(lambda: loc.dblclick(button=item.button), sel)
            else:
                await _loc_op(lambda: loc.click(button=item.button), sel)
            return f"已点击元素（{item.ref and f'ref={item.ref}' or item.selector}）"

        if item.action == "fill":
            sel = _resolve()
            loc = page.locator(sel)
            await _loc_op(lambda: loc.fill(item.text), sel)
            if item.press_enter:
                await page.keyboard.press("Enter")
                return f"已输入并回车: \"{item.text[:50]}\""
            return f"已输入: \"{item.text[:50]}\""

        if item.action == "hover":
            sel = _resolve()
            loc = page.locator(sel)
            await _loc_op(lambda: loc.hover(), sel)
            return "已悬停元素"

        if item.action == "select":
            if not item.value:
                raise ValueError("select 需要 value（选项 value 或可见文本）")
            sel = _resolve()
            loc = page.locator(sel)
            try:
                await _loc_op(lambda: loc.select_option(value=item.value), sel)
            except Exception:
                await _loc_op(lambda: loc.select_option(label=item.value), sel)
            return f"已选择: {item.value[:50]}"

        if item.action == "scroll":
            if item.scroll_to == "top":
                await page.evaluate("window.scrollTo(0, 0)")
                return "已滚动到顶部"
            if item.scroll_to == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return "已滚动到底部"
            # 与 gui_tool 一致：负数向下（Playwright wheel 正 deltaY 向下）
            await page.mouse.wheel(0, -item.clicks * 100)
            return f"已滚动（滚轮量 {item.clicks}）"

        if item.action == "press":
            if not item.key:
                raise ValueError("press 需要 key（如 Enter、Control+a）")
            await page.keyboard.press(item.key)
            return f"已按键: {item.key}"

        if item.action == "wait":
            if item.wait_selector:
                await page.wait_for_selector(
                    _normalize_selector(item.wait_selector),
                    timeout=max(item.wait_seconds, 1.0) * 1000,
                )
                return f"已等到元素出现: {item.wait_selector}"
            await asyncio.sleep(max(item.wait_seconds, 0.0))
            return f"已等待 {item.wait_seconds}s"

        if item.action == "extract":
            try:
                title = await page.title()
            except Exception:
                title = ""
            if item.selector:
                # 走 locator（支持 CSS/text=/xpath= 等全部引擎；多匹配时拼接前 20 个）
                sel = _normalize_selector(item.selector)
                loc = page.locator(sel)
                count = await loc.count()
                if count == 0:
                    raise ValueError(f"未找到元素: {item.selector}")
                texts = []
                for i in range(min(count, 20)):
                    try:
                        t = (await loc.nth(i).inner_text()).strip()
                    except Exception:
                        t = ""
                    if t:
                        texts.append(t)
                text = "\n".join(texts)
            else:
                data = await page.evaluate(_EXTRACT_JS, None)
                text = ((data or {}).get("text") or "").strip()
            limit = min(max(item.max_length, 200), 10000)
            head = f"页面: {title} | {_short_url(page.url)}\n"
            body = text[:limit] + ("...(已截断)" if len(text) > limit else "")
            return head + (body or "(无文本内容)")

        if item.action == "back":
            await page.go_back(wait_until="domcontentloaded")
            return f"已后退到 {page.url}"

        if item.action == "forward":
            await page.go_forward(wait_until="domcontentloaded")
            return f"已前进到 {page.url}"

        if item.action == "reload":
            await page.reload(wait_until="domcontentloaded")
            return f"已刷新（{await page.title()}）"

        if item.action == "screenshot":
            return f"已请求截图（{'整页' if item.full_page else '视口'}）"

        if item.action == "eval_js":
            if not item.js:
                raise ValueError("eval_js 需要 js 表达式")
            result = await page.evaluate(item.js)
            return f"JS 执行结果: {str(result)[:2000]}"

        raise ValueError(f"不支持的动作类型: {item.action}")

    # ---------- 批量执行（一次 call_async 提交，会话线程内串行） ----------
    # 纯观察型动作：结果本身就是页面状态文本，无需再附截图（省视觉 token）
    _OBSERVE_ONLY = {"snapshot", "extract", "eval_js", "wait"}

    async def _run_batch(self, session, actions: list[WebPageActionItem]) -> Tuple[str, Optional[bytes]]:
        await session._ensure_connected()
        lines: list[str] = []
        png: Optional[bytes] = None
        want_full = False
        screenshot_requested = False
        prev_observe = False
        for idx, item in enumerate(actions, 1):
            if item.action == "screenshot":
                want_full = item.full_page
                screenshot_requested = True
            # 观察型动作（snapshot/extract 等）执行前等待页面稳定，
            # 避免 JS 未渲染完就读到旧状态；连续观察只等待一次
            is_observe = item.action in self._OBSERVE_ONLY
            if is_observe and not prev_observe:
                try:
                    await session._settle_current()
                except Exception:
                    pass
            try:
                line = await self._exec_action(session, item)
                lines.append(f"步骤{idx} [{item.action}] {line}")
                prev_observe = is_observe
            except Exception as e:
                lines.append(f"步骤{idx} [{item.action}] 失败: {e}")
                break
        # 操作结束截图：空动作或含非观察型动作（点击/输入等改变页面状态的操作）时附加；
        # 纯观察批次（snapshot/extract 等）文本结果已含页面信息，跳过截图。
        # 截图统一走 session.screenshot（内含页面稳定等待，避免截到加载动画）
        need_shot = screenshot_requested or (not actions) or any(
            a.action not in self._OBSERVE_ONLY for a in actions
        )
        if need_shot:
            try:
                png = await session.screenshot(want_full) if session._page else None
            except Exception:
                png = None
        if screenshot_requested:
            lines.append("截图见随附图片")
        msg = "\n".join(lines) if lines else "无动作（已返回当前页面截图）"
        return msg, png

    # ---------- 同步主逻辑 ----------
    def _run(self, actions: list[WebPageActionItem] | list[dict] | None = None) -> Tuple[str, dict]:
        session = get_browser_session()
        # LangChain 调用路径传入 pydantic 模型实例；直连/测试路径可能传 dict，两者兼容
        items = [
            a if isinstance(a, WebPageActionItem) else WebPageActionItem(**a)
            for a in (actions or [])
        ]
        try:
            msg, png = session.call_async(
                lambda s: self._run_batch(s, items),
                timeout=180.0,
            )
        except Exception as e:
            return f"web_page 执行出错: {e}", {}
        artifact: dict = {}
        if png:
            artifact["image_bytes"] = png
        return msg, artifact

    async def _arun(self, actions: list[WebPageActionItem] | list[dict] | None = None) -> Tuple[str, dict]:
        return await asyncio.to_thread(self._run, actions)
