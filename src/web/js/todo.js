// todo.js -- Todo List 悬浮窗

import { $, escapeHtml } from './utils.js';
import { state } from './state.js';

function _updateBadge(show) {
  try {
    import('./action-bar.js').then(m => m.setActionBadge('todo', show));
  } catch {}
}

function buildTodoListOverlay(todoData) {
  if (!todoData || !todoData.steps || !todoData.steps.length) {
    return null;
  }

  const overlay = document.createElement("div");
  overlay.className = "todo-list-overlay";
  overlay.hidden = true;  // 默认隐藏，按钮点击后显示

  const header = document.createElement("div");
  header.className = "todo-list-header";
  header.textContent = "\u{1F4CB} Todo List";
  header.addEventListener("click", () => {
    overlay.classList.toggle("todo-list-overlay--collapsed");
  });
  overlay.appendChild(header);

  const list = document.createElement("ul");
  list.className = "todo-list-body";
  todoData.steps.forEach((s, i) => {
    const item = document.createElement("li");
    item.className = "todo-list-item";
    const statusIcon = todoData.done_steps && todoData.done_steps.includes(i)
      ? '<span class="todo-check">\u2713</span>'
      : '<span class="todo-spinner"></span>';
    item.innerHTML = `${statusIcon}<span class="todo-label">${escapeHtml(s)}</span>`;
    list.appendChild(item);
  });
  overlay.appendChild(list);

  return overlay;
}

function _getContainer() {
  const chatMessages = $("chatMessages");
  return chatMessages ? (chatMessages.closest(".chat-area") || chatMessages.parentElement) : null;
}

function updateTodoOverlay(todoData) {
  _updateBadge(!!(todoData && todoData.steps && todoData.steps.length));

  // 如果已有 overlay，更新其内容
  if (state._currentTodoOverlay) {
    const existing = state._currentTodoOverlay;
    // 更新列表内容
    const list = existing.querySelector(".todo-list-body");
    if (list) {
      list.innerHTML = "";
      if (todoData && todoData.steps && todoData.steps.length) {
        todoData.steps.forEach((s, i) => {
          const item = document.createElement("li");
          item.className = "todo-list-item";
          const statusIcon = todoData.done_steps && todoData.done_steps.includes(i)
            ? '<span class="todo-check">\u2713</span>'
            : '<span class="todo-spinner"></span>';
          item.innerHTML = `${statusIcon}<span class="todo-label">${escapeHtml(s)}</span>`;
          list.appendChild(item);
        });
      }
    }
    existing.hidden = false;
    return;
  }

  if (!todoData || !todoData.steps || !todoData.steps.length) {
    _updateBadge(false);
    return;
  }

  const overlay = buildTodoListOverlay(todoData);
  if (!overlay) return;

  const container = _getContainer();
  if (!container) return;

  // 移除旧 overlay（如果有）
  const old = container.querySelector(".todo-list-overlay");
  if (old) old.remove();

  // 新增（初始隐藏，等待按钮点击）
  overlay.hidden = false;
  container.appendChild(overlay);
  state._currentTodoOverlay = overlay;

  // 同步双浮窗布局
  try { import('./pending-overlay.js').then(m => m.updateOverlayLayout && m.updateOverlayLayout()); } catch {}
}

function clearTodoOverlay() {
  _updateBadge(false);
  if (state._currentTodoOverlay) {
    state._currentTodoOverlay.hidden = true;
  }
  // 也隐藏 DOM 中可能存在的其他 todo overlay
  document.querySelectorAll(".todo-list-overlay").forEach((el) => el.hidden = true);
}

export { buildTodoListOverlay, updateTodoOverlay, clearTodoOverlay };
