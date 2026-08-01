// action-bar.js -- 操作图标按钮栏：TodoList / 人机交互 / 文档变更
// 替代原来的 floating overlay 模式，改用图标按钮 toggle 面板

import { $ } from './utils.js';

/** 当前激活的面板类型 */
let _activePanel = null;
/** 连击保护：上次切换时间戳（ms） */
let _lastToggleTime = 0;
const TOGGLE_COOLDOWN = 300;

/**
 * 初始化操作按钮栏事件
 * @param {object} callbacks - { onToggleTodo, onTogglePending, onToggleDoc }
 */
export function initActionBar(callbacks = {}) {
  const todoBtn = $('actionTodoBtn');
  const pendingBtn = $('actionPendingBtn');
  const docBtn = $('actionDocBtn');

  if (todoBtn) {
    todoBtn.addEventListener('click', () => {
      _togglePanel('todo', todoBtn, callbacks.onToggleTodo);
    });
  }
  if (pendingBtn) {
    pendingBtn.addEventListener('click', () => {
      _togglePanel('pending', pendingBtn, callbacks.onTogglePending);
    });
  }
  if (docBtn) {
    docBtn.addEventListener('click', () => {
      _togglePanel('doc', docBtn, callbacks.onToggleDoc);
    });
  }
}

function _togglePanel(name, btn, callback) {
  const now = Date.now();
  if (now - _lastToggleTime < TOGGLE_COOLDOWN) return;
  _lastToggleTime = now;

  if (_activePanel === name) {
    _deactivateAll();
    if (callback) callback(false);
    return;
  }
  _deactivateAll();
  btn.classList.add('is-active');
  _activePanel = name;
  if (callback) callback(true);
}

/** 关闭所有面板并取消按钮激活态 */
export function deactivateAllActionPanels() {
  _deactivateAll();
}

function _deactivateAll() {
  ['actionTodoBtn', 'actionPendingBtn', 'actionDocBtn'].forEach((id) => {
    const btn = $(id);
    if (btn) btn.classList.remove('is-active');
  });
  _activePanel = null;
}

/** 设置某个按钮的角标（红点） */
export function setActionBadge(name, show) {
  const id = name === 'todo' ? 'actionTodoBtn'
    : name === 'pending' ? 'actionPendingBtn'
    : 'actionDocBtn';
  const btn = $(id);
  if (!btn) return;
  const existing = btn.querySelector('.badge-dot');
  if (show && !existing) {
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    btn.style.position = 'relative';
    btn.appendChild(dot);
  } else if (!show && existing) {
    existing.remove();
  }
}
