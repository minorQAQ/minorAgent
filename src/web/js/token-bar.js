// token-bar.js -- Token 上下文进度条（含压缩游标 + 手动压缩）
// 在输入框下方展示当前 token 用量 / 最大上下文的动态进度条，
// 两个可拖拽游标对应 MINI_COMPRESS_RATE / HARD_COMPRESS_RATE

import { $, showToast } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';

let _pollTimer = null;
let _settings = null;  // { context_window, mini_rate, hard_rate, current_turns }
let _currentTokens = 0;
let _dragging = null;   // 'mini' | 'hard' | null

// ===== DOM refs =====
let _barTrack, _barFill, _barSegGreen, _barSegYellow, _barSegRed;
let _handleMini, _handleHard;
let _labelText;

// ===== 初始化 =====
export function initTokenBar() {
  _barTrack = $("tokenBarTrack");
  _barFill = $("tokenBarFill");
  _barSegGreen = $("tokenBarSegGreen");
  _barSegYellow = $("tokenBarSegYellow");
  _barSegRed = $("tokenBarSegRed");
  _handleMini = $("tokenHandleMini");
  _handleHard = $("tokenHandleHard");
  _labelText = $("tokenLabel");

  if (!_barTrack) return;

  // 从 state 恢复当前会话的 token 用量
  _currentTokens = state.currentTokens || 0;

  // 加载压缩设置
  loadSettings().then(() => {
    updateBarUI();
    attachHandleEvents();
  });

  // 立即拉一次最新数据，然后启动轮询
  pollTokens();
  startPolling();
}

// ===== 加载设置 =====
async function loadSettings() {
  try {
    const data = await api("/api/config/compress-settings");
    _settings = data;
  } catch {
    _settings = { context_window: 131072, mini_compress_rate: 0.4, hard_compress_rate: 0.7 };
  }
}

// ===== 轮询 token 用量 =====
function startPolling() {
  stopPolling();
  _pollTimer = setInterval(pollTokens, 2000);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

async function pollTokens() {
  if (!state.sessionId) return;
  try {
    const data = await api(`/api/chat/tokens/${state.sessionId}`);
    _currentTokens = data.tokens || 0;
    if (data.context_window) {
      _settings = {
        context_window: data.context_window,
        mini_rate: data.mini_rate,
        hard_rate: data.hard_rate,
      };
    }
    updateBarUI();
  } catch {
    // 静默失败
  }
}

// ===== 更新进度条 =====
function updateBarUI() {
  if (!_barTrack || !_settings) return;

  const cw = _settings.context_window || 131072;
  const miniRate = _settings.mini_rate || 0.4;
  const hardRate = _settings.hard_rate || 0.7;
  const tokens = _currentTokens;

  // 进度条填充位置（cap at 100%）
  const pct = Math.min(100, (tokens / cw) * 100);
  const miniPct = miniRate * 100;
  const hardPct = hardRate * 100;

  // 颜色分段宽仅延伸到实际 token 用量位置
  const greenW = Math.min(pct, miniPct);
  const yellowW = Math.max(0, Math.min(pct - miniPct, hardPct - miniPct));
  const redW = Math.max(0, pct - hardPct);

  if (_barSegGreen) _barSegGreen.style.width = `${greenW}%`;
  if (_barSegYellow) _barSegYellow.style.width = `${yellowW}%`;
  if (_barSegRed) _barSegRed.style.width = `${redW}%`;

  // 填充条隐藏（分段已承担可视化角色）
  if (_barFill) _barFill.style.width = '0%';

  // 游标位置
  if (_handleMini) _handleMini.style.left = `${miniPct}%`;
  if (_handleHard) _handleHard.style.left = `${hardPct}%`;

  // 标签文字
  if (_labelText) {
    _labelText.textContent = `${_fmtNum(tokens)} / ${_fmtNum(cw)} tokens`;
    // 颜色提示
    const cls = tokens > cw * hardRate ? 'danger' : tokens > cw * miniRate ? 'warn' : 'safe';
    _labelText.className = `token-label token-label--${cls}`;
  }

  // 游标超出反馈
  if (_handleMini) {
    _handleMini.classList.toggle('overshot', tokens > cw * miniRate);
  }
  if (_handleHard) {
    _handleHard.classList.toggle('overshot', tokens > cw * hardRate);
  }
}

function _fmtNum(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

// ===== 游标拖拽 =====
function attachHandleEvents() {
  if (!_handleMini || !_handleHard || !_barTrack) return;

  const handles = [
    { el: _handleMini, key: 'mini' },
    { el: _handleHard, key: 'hard' },
  ];

  for (const h of handles) {
    h.el.addEventListener('mousedown', (e) => {
      e.preventDefault();
      _dragging = h.key;
      h.el.classList.add('dragging');
      document.addEventListener('mousemove', onDragMove);
      document.addEventListener('mouseup', onDragEnd);
    });

    // 触摸支持
    h.el.addEventListener('touchstart', (e) => {
      e.preventDefault();
      _dragging = h.key;
      h.el.classList.add('dragging');
      document.addEventListener('touchmove', onTouchMove, { passive: false });
      document.addEventListener('touchend', onDragEndTouch);
    });
  }
}

function getPctFromEvent(clientX) {
  const rect = _barTrack.getBoundingClientRect();
  return Math.max(5, Math.min(95, ((clientX - rect.left) / rect.width) * 100));
}

function onDragMove(e) {
  if (!_dragging) return;
  const pct = getPctFromEvent(e.clientX);
  setHandlePct(_dragging, pct);
}

function onTouchMove(e) {
  if (!_dragging) return;
  e.preventDefault();
  const pct = getPctFromEvent(e.touches[0].clientX);
  setHandlePct(_dragging, pct);
}

function onDragEnd() {
  endDrag();
  document.removeEventListener('mousemove', onDragMove);
  document.removeEventListener('mouseup', onDragEnd);
}

function onDragEndTouch() {
  endDrag();
  document.removeEventListener('touchmove', onTouchMove);
  document.removeEventListener('touchend', onDragEndTouch);
}

function endDrag() {
  if (!_dragging) return;
  const key = _dragging;
  _dragging = null;
  if (_handleMini) _handleMini.classList.remove('dragging');
  if (_handleHard) _handleHard.classList.remove('dragging');
  // 保存到后端
  saveRateSetting(key);
}

function setHandlePct(key, pct) {
  const rate = Math.round(pct) / 100;
  if (key === 'mini') {
    _settings.mini_rate = rate;
    // mini 不能超过 hard
    if (_settings.hard_rate && rate >= _settings.hard_rate) {
      _settings.hard_rate = Math.min(1, rate + 0.05);
    }
  } else if (key === 'hard') {
    _settings.hard_rate = rate;
    // hard 不能小于 mini
    if (_settings.mini_rate && rate <= _settings.mini_rate) {
      _settings.mini_rate = Math.max(0.05, rate - 0.05);
    }
  }
  updateBarUI();
}

async function saveRateSetting(key) {
  const body = {};
  if (key === 'mini') body.mini_compress_rate = _settings.mini_rate;
  if (key === 'hard') body.hard_compress_rate = _settings.hard_rate;
  try {
    await api("/api/config/compress-settings", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch {
    showToast("保存压缩设置失败");
  }
}

// ===== 公开：外部调用 =====
/** 强制立即刷新 token 计数（发送消息后调用） */
export function refreshTokens() {
  pollTokens();
}

/** 停止轮询（页面卸载时调用） */
export function stopTokenPolling() {
  stopPolling();
}
