// token-bar.js -- Token 上下文进度条（压缩阈值游标）
// 在输入框下方展示当前 token 用量 / 最大上下文的动态进度条，
// 单个可拖拽游标对应 COMPRESS_RATE 压缩阈值

import { $, showToast } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';

let _pollTimer = null;
let _settings = null;  // { context_window, compress_rate }
let _currentTokens = 0;
let _dragging = false;

// ===== DOM refs =====
let _barTrack, _barFill, _barSegGreen, _barSegRed;
let _handleCompress;
let _labelText;

// ===== 初始化 =====
export function initTokenBar() {
  _barTrack = $("tokenBarTrack");
  _barFill = $("tokenBarFill");
  _barSegGreen = $("tokenBarSegGreen");
  _barSegRed = $("tokenBarSegRed");
  _handleCompress = $("tokenHandleCompress");
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
    _settings = { context_window: 262144, compress_rate: 0.6 };
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
        compress_rate: data.compress_rate,
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

  const cw = _settings.context_window || 262144;
  const compressRate = _settings.compress_rate || 0.6;
  const tokens = _currentTokens;

  // 进度条填充位置（cap at 100%）
  const pct = Math.min(100, (tokens / cw) * 100);
  const compressPct = compressRate * 100;

  // 颜色分段：低于压缩阈值绿色，超过阈值红色
  const greenW = Math.min(pct, compressPct);
  const redW = Math.max(0, pct - compressPct);

  if (_barSegGreen) _barSegGreen.style.width = `${greenW}%`;
  if (_barSegRed) _barSegRed.style.width = `${redW}%`;

  // 填充条隐藏（分段已承担可视化角色）
  if (_barFill) _barFill.style.width = '0%';

  // 游标位置
  if (_handleCompress) _handleCompress.style.left = `${compressPct}%`;

  // 标签文字
  if (_labelText) {
    _labelText.textContent = `${_fmtNum(tokens)} / ${_fmtNum(cw)} tokens`;
    // 颜色提示
    const cls = tokens > cw * compressRate ? 'danger' : 'safe';
    _labelText.className = `token-label token-label--${cls}`;
  }

  // 游标超限反馈
  if (_handleCompress) {
    _handleCompress.classList.toggle('overshot', tokens > cw * compressRate);
  }
}

function _fmtNum(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

// ===== 游标拖拽 =====
function attachHandleEvents() {
  if (!_handleCompress || !_barTrack) return;

  _handleCompress.addEventListener('mousedown', (e) => {
    e.preventDefault();
    _dragging = true;
    _handleCompress.classList.add('dragging');
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
  });

  // 触摸支持
  _handleCompress.addEventListener('touchstart', (e) => {
    e.preventDefault();
    _dragging = true;
    _handleCompress.classList.add('dragging');
    document.addEventListener('touchmove', onTouchMove, { passive: false });
    document.addEventListener('touchend', onDragEndTouch);
  });
}

function getPctFromEvent(clientX) {
  const rect = _barTrack.getBoundingClientRect();
  return Math.max(5, Math.min(95, ((clientX - rect.left) / rect.width) * 100));
}

function onDragMove(e) {
  if (!_dragging) return;
  const pct = getPctFromEvent(e.clientX);
  setHandlePct(pct);
}

function onTouchMove(e) {
  if (!_dragging) return;
  e.preventDefault();
  const pct = getPctFromEvent(e.touches[0].clientX);
  setHandlePct(pct);
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
  _dragging = false;
  if (_handleCompress) _handleCompress.classList.remove('dragging');
  // 保存到后端
  saveRateSetting();
}

function setHandlePct(pct) {
  const rate = Math.round(pct) / 100;
  _settings.compress_rate = rate;
  updateBarUI();
}

async function saveRateSetting() {
  try {
    await api("/api/config/compress-settings", {
      method: "POST",
      body: JSON.stringify({ compress_rate: _settings.compress_rate }),
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
