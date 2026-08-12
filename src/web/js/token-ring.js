// token-ring.js -- 上下文 Token 环形指示器（替代原横向进度条）
// 深色底环 + 从顶部顺时针填充的浅色弧线表示 token 占用率（模型选择器左侧）。
// 悬停弹出面板：
//   顶部：上下文容量 xxk/xxk (xx%)
//   简约进度条：token 用量填充 + 静态压缩阈值刻度线（阈值仅在环境变量中修改，不可拖动）
//   下方：三类占比降序列表（消息 / 工具 / 系统提示词），占用多的在上方

import { $, showToast, withClickGuard } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';

let _pollTimer = null;
let _settings = null;               // { context_window, compress_rate }
let _breakdown = { messages: 0, tools: 0, system: 0 };

const _RING_R = 11;
const _RING_C = 2 * Math.PI * _RING_R;

/** 初始化环形指示器（bootstrap 后调用） */
export function initTokenRing() {
  const fill = $("tokenRingFill");
  if (fill) fill.style.strokeDasharray = `${_RING_C}`;
  bindRingEvents();
  pollTokens();
  startPolling();
}

function startPolling() {
  stopTokenPolling();
  _pollTimer = setInterval(pollTokens, 2000);
}

export function stopTokenPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

export function refreshTokens() {
  pollTokens();
}

async function pollTokens() {
  if (!state.sessionId) return;
  try {
    const data = await api(`/api/chat/tokens/${state.sessionId}`);
    state.currentTokens = data.tokens || 0;
    _settings = {
      context_window: data.context_window || 262144,
      compress_rate: data.compress_rate != null ? data.compress_rate : 0.6,
    };
    _breakdown = data.breakdown || { messages: 0, tools: 0, system: 0 };
    updateRingUI();
  } catch { /* 静默失败 */ }
}

function _fmtK(n) {
  return `${(Number(n) / 1024).toFixed(1)}k`;
}

/** 更新圆环弧线、容量文案、用量进度条与占比列表 */
function updateRingUI() {
  const cw = _settings ? _settings.context_window : 262144;
  const tokens = state.currentTokens || 0;
  const pct = Math.min(100, (tokens / cw) * 100);

  const fill = $("tokenRingFill");
  if (fill) fill.style.strokeDashoffset = `${_RING_C * (1 - pct / 100)}`;

  const cap = $("tokenRingCapacity");
  if (cap) cap.textContent = `上下文容量 ${_fmtK(tokens)} / ${_fmtK(cw)} (${pct.toFixed(1)}%)`;

  // 用量进度条：填充 = token 占用率
  const barFill = $("tokenRingRateFill");
  if (barFill) barFill.style.width = `${pct}%`;

  // 压缩阈值刻度线（静态，仅展示；阈值在环境变量中修改）
  const rate = _settings ? _settings.compress_rate : 0.6;
  const marker = $("tokenRingThreshold");
  if (marker) marker.style.left = `${rate * 100}%`;
  const rateLabel = $("tokenRingRateLabel");
  if (rateLabel) rateLabel.textContent = `压缩阈值 ${Math.round(rate * 100)}%（在环境变量中修改）`;

  renderBreakdown();
}

/** 占比列表：按占用降序（占用多的在上方） */
function renderBreakdown() {
  const container = $("tokenRingBreakdown");
  if (!container) return;
  const rows = [
    { key: "消息", val: Number(_breakdown.messages) || 0 },
    { key: "工具", val: Number(_breakdown.tools) || 0 },
    { key: "系统提示词", val: Number(_breakdown.system) || 0 },
  ];
  const total = rows.reduce((s, r) => s + r.val, 0);
  rows.sort((a, b) => b.val - a.val);
  container.innerHTML = "";
  rows.forEach((r) => {
    const row = document.createElement("div");
    row.className = "token-ring-breakdown-row";

    const dot = document.createElement("span");
    dot.className = "token-ring-breakdown-dot";
    dot.textContent = "·";

    const key = document.createElement("span");
    key.className = "token-ring-breakdown-key";
    key.textContent = r.key;

    const val = document.createElement("span");
    val.className = "token-ring-breakdown-val";
    val.textContent = `${total > 0 ? ((r.val / total) * 100).toFixed(1) : "0.0"}%`;

    row.appendChild(dot);
    row.appendChild(key);
    row.appendChild(val);
    container.appendChild(row);
  });
}

/** 绑定圆环 hover 显示/隐藏与点击切换面板（含连击保护） */
function bindRingEvents() {
  const wrap = $("tokenRingWrap");
  const panel = $("tokenRingPanel");
  if (!wrap || !panel) return;

  wrap.addEventListener("mouseenter", () => { panel.hidden = false; });
  wrap.addEventListener("mouseleave", () => { panel.hidden = true; });

  const btn = $("tokenRingBtn");
  if (btn) {
    btn.addEventListener("click", withClickGuard((e) => {
      e.stopPropagation();
      panel.hidden = !panel.hidden;
    }));
  }
}
