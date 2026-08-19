// turn-nav.js -- 聊天回合导航条：每个用户输入一条横条，点击跳转到对应回合，当前回合高亮
// 悬停横条时左侧浮窗显示该用户输入内容的前 20 字。

import { $ } from './utils.js';
import { state } from './state.js';

const chatMessages = $("chatMessages");

let _navEl = null;       // 导航容器（.turn-nav）
let _tipEl = null;       // 悬停浮窗（.turn-nav-tip）
let _turns = [];         // [{ el, bar, snippet }]
let _bound = false;

/** 提取用户消息的可读文本（不含 @file/@folder 引用），最多 20 字 */
function extractUserSnippet(el) {
  const txtEl = el.querySelector(".msg-text");
  let s = (txtEl ? txtEl.textContent : "").trim();
  if (!s) s = (el.textContent || "").trim();
  return s.slice(0, 20) || "（无文本）";
}

/** 从 DOM 消息元素构建回合分组：每个用户输入（.msg.user）为一条导航条，
 *  其后的助手消息归入同一回合（仅用于定位，不新建条）。typing 指示器不参与。 */
function buildTurns() {
  if (!chatMessages) return [];
  const turns = [];
  for (const el of chatMessages.children) {
    if (!el.classList || !el.classList.contains("msg") || el.classList.contains("msg-typing")) continue;
    if (el.classList.contains("user")) {
      turns.push({ el, bar: null, snippet: extractUserSnippet(el) });
    }
  }
  return turns;
}

/** 在悬停横条左侧显示用户输入摘要浮窗 */
function showTip(bar, text) {
  if (!_tipEl) return;
  _tipEl.textContent = text;
  _tipEl.hidden = false;
  const navRect = _navEl.getBoundingClientRect();
  const barRect = bar.getBoundingClientRect();
  const top = barRect.top - navRect.top + barRect.height / 2;
  const tipHeight = _tipEl.offsetHeight || 24;
  // 上下边界内夹紧，避免被 .chat-shell 的 overflow:hidden 裁剪
  _tipEl.style.top = Math.min(Math.max(top, tipHeight / 2 + 4), navRect.height - tipHeight / 2 - 4) + "px";
}

function hideTip() {
  if (_tipEl) _tipEl.hidden = true;
}

function bindScroll() {
  if (_bound || !chatMessages) return;
  _bound = true;
  chatMessages.addEventListener("scroll", hideTip);
}

/** 重建回合导航条（消息列表渲染 / 流式回复结束后调用） */
export function renderTurnNav() {
  if (!chatMessages) return;
  if (state.mode === "cron") { hideTurnNav(); return; }
  const turns = buildTurns();
  _turns = turns;

  if (!_navEl) {
    _navEl = document.createElement("div");
    _navEl.className = "turn-nav";
    _navEl.setAttribute("role", "navigation");
    _navEl.setAttribute("aria-label", "回合导航");
    const shell = chatMessages.closest(".chat-shell") || chatMessages.parentElement;
    if (shell) shell.appendChild(_navEl);

    _tipEl = document.createElement("div");
    _tipEl.className = "turn-nav-tip";
    _tipEl.hidden = true;
    _navEl.appendChild(_tipEl);
  }
  if (turns.length === 0) {
    _navEl.hidden = true;
    hideTip();
    return;
  }
  _navEl.hidden = false;
  _navEl.innerHTML = "";
  _navEl.appendChild(_tipEl); // 浮窗保持在横条之后渲染（位于最上层）

  turns.forEach((t, i) => {
    const bar = document.createElement("button");
    bar.type = "button";
    bar.className = "turn-nav-bar";
    bar.title = `回合 ${i + 1}：${t.snippet}`;
    bar.addEventListener("click", () => {
      if (!t.el || !chatMessages) return;
      const cRect = chatMessages.getBoundingClientRect();
      const eRect = t.el.getBoundingClientRect();
      chatMessages.scrollTop += eRect.top - cRect.top;
    });
    // 悬停 / 聚焦时左侧浮窗显示用户输入前 20 字
    bar.addEventListener("mouseenter", () => showTip(bar, t.snippet));
    bar.addEventListener("mouseleave", hideTip);
    bar.addEventListener("focus", () => showTip(bar, t.snippet));
    bar.addEventListener("blur", hideTip);
    t.bar = bar;
    _navEl.appendChild(bar);
  });

  bindScroll();
  hideTip();
}

function hideTurnNav() {
  if (_navEl) _navEl.hidden = true;
  hideTip();
}

/** 模式切换后同步显隐（cron 模式复用聊天容器，需隐藏导航条） */
export function syncTurnNavVisibility() {
  if (state.mode === "cron") hideTurnNav();
  else renderTurnNav();
}
