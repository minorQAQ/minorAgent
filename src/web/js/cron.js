// cron.js -- 定时任务（Cron）模式前端逻辑
//
// 职责:
//   1. 侧栏任务列表渲染（含状态徽章 + 悬停操作）
//   2. 任务新建/编辑/删除/启停（弹窗表单）
//   3. 聊天区复用 chat-render 渲染执行记录 + 顶部任务信息条
//   4. SSE 实时流（/api/cron/{id}/live/stream）→ 复用 injectLiveToolCalls
//   5. 追问发送（POST /api/cron/{id}/run {prompt}）→ 子进程执行
//
// 与 chat/edit 模式的关系:
//   - 共享 #chatMessages DOM 与 renderMessages，切换离开时由 leaveCronMode 恢复聊天视图。
//   - 不触碰 state.sessionId（chat 会话标识），cron 任务用 state.activeCronTaskId 标识。

import { $, showToast, escapeHtml } from './utils.js';
import { showConfirm, showAlert } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';
import { renderMessages, appendThinkingIndicator, scrollChatToBottom } from './chat-render.js';
import { injectLiveToolCalls } from './toolcalls.js';

// ===== 状态文案 / 颜色映射 =====
const STATUS_TEXT = {
  pending: '待运行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  expired: '过时失效',
  disabled: '已禁用',
};

const TRIGGER_TEXT = {
  cron: (t) => formatCronTrigger(t.cron),
  interval: (t) => `每 ${t.interval_seconds || 0}s`,
  once: (t) => t.run_at ? `定时: ${t.run_at.replace('T', ' ').slice(0, 16)}` : '一次性延时',
};

// 将 cron 表达式格式化为用户友好的闹钟文案（无法解析时回退显示原始 cron）
function formatCronTrigger(cronExpr) {
  const alarm = cronToAlarm(cronExpr);
  if (!alarm) return cronExpr ? `cron: ${cronExpr}` : 'cron 表达式';
  const time = `${String(alarm.hour).padStart(2, '0')}:${String(alarm.minute).padStart(2, '0')}`;
  if (alarm.weekdays.length === 7) return `每天 ${time}`;
  const wdLabels = { 0: '日', 1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六' };
  const sorted = [...alarm.weekdays].sort((a, b) => (a === 0 ? 7 : a) - (b === 0 ? 7 : b));
  return `周${sorted.map((d) => wdLabels[d]).join('、')} ${time}`;
}

// ===== DOM 引用 =====
let cronListEl = null;
let cronNewBtnEl = null;
let chatPanelEl = null;
let chatMessagesEl = null;
let chatPlaceholderEl = null;
let textInputEl = null;
let sendBtnEl = null;

// cron 专属 DOM（动态创建/管理）
let cronBannerEl = null;        // 顶部任务信息条
let cronPlaceholderEl = null;   // 空状态占位
let cronEditOverlayEl = null;   // 编辑弹窗

// 运行态追踪
let _typingEl = null;           // 当前 live 工具调用挂载的思考气泡
let _eventSource = null;        // SSE 连接
let _statusPollTimer = null;    // 状态轮询定时器
let _reconnectTimer = null;
let _collectedReflections = [];
let _lastReflectionCount = 0;
let _turnStartedAt = null;
let _cronActive = false;        // 是否处于 cron 模式（控制 SSE/轮询生命周期）
let _periodMinutes = 30;        // 时间段长度（分钟），供冲突检测使用，启动时从后端拉取

/** 从后端拉取时间段长度并缓存 */
async function refreshPeriodMinutes() {
  try {
    const res = await api("/api/cron/period");
    if (res && typeof res.period_minutes === "number") {
      _periodMinutes = res.period_minutes;
    }
  } catch (_) { /* 拉取失败沿用默认值 */ }
}

// ===== 初始化 =====
export function initCronMode() {
  cronListEl = $("cronList");
  cronNewBtnEl = $("cronNewBtn");
  chatPanelEl = $("chatPanel");
  chatMessagesEl = $("chatMessages");
  chatPlaceholderEl = $("chatPlaceholder");
  textInputEl = $("textInput");
  sendBtnEl = $("sendBtn");

  // 新建按钮
  cronNewBtnEl?.addEventListener("click", () => openCronEditor(null));

  // 任务列表事件委托：选中 / 操作按钮
  cronListEl?.addEventListener("click", (e) => {
    const actionBtn = e.target.closest("[data-cron-action]");
    if (actionBtn) {
      e.stopPropagation();
      const tid = actionBtn.dataset.taskId;
      const action = actionBtn.dataset.cronAction;
      if (tid && action) handleListAction(action, tid);
      return;
    }
    const item = e.target.closest("[data-cron-task-id]");
    if (item) {
      const tid = item.dataset.cronTaskId;
      if (tid) selectCronTask(tid);
    }
  });

  // 编辑弹窗事件
  bindCronEditorEvents();
}

// ===== 模式进入 / 离开（由 edit-mode.js 钩子调用） =====
export async function enterCronMode() {
  _cronActive = true;
  ensureCronPlaceholders();
  // 拉取时间段长度供冲突检测使用
  refreshPeriodMinutes();
  await renderCronTasks();
  // 恢复上次选中的任务，否则展示空状态
  if (state.activeCronTaskId) {
    await selectCronTask(state.activeCronTaskId, { silent: true });
  } else {
    showCronEmptyState();
  }
}

export async function leaveCronMode() {
  _cronActive = false;
  stopCronLive();
  hideCronPlaceholders();
  // 恢复聊天会话视图（cron 模式复用了 #chatMessages）
  await restoreChatView();
}

// ===== 任务列表渲染 =====
export async function renderCronTasks() {
  if (!cronListEl) return;
  try {
    const data = await api("/api/cron");
    state.cronTasks = data.tasks || [];
  } catch (e) {
    state.cronTasks = [];
    showToast("加载定时任务失败: " + (e.message || e));
  }
  cronListEl.innerHTML = "";
  if (state.cronTasks.length === 0) {
    const empty = document.createElement("li");
    empty.className = "cron-empty";
    empty.textContent = "暂无定时任务，点击 + 新建";
    cronListEl.appendChild(empty);
    return;
  }
  for (const t of state.cronTasks) {
    cronListEl.appendChild(renderCronListItem(t));
  }
}

function renderCronListItem(task) {
  const li = document.createElement("li");
  li.className = "cron-item";
  if (task.task_id === state.activeCronTaskId) li.classList.add("active");
  li.dataset.cronTaskId = task.task_id;
  li.title = task.prompt ? String(task.prompt).slice(0, 120) : (task.name || "");

  const status = task.is_running ? "running" : (task.last_status || "pending");
  const dot = document.createElement("span");
  dot.className = `cron-status-dot cron-status-dot--${status}`;

  const body = document.createElement("div");
  body.className = "cron-item-body";

  const name = document.createElement("div");
  name.className = "cron-item-name";
  name.textContent = task.name || "未命名任务";

  const meta = document.createElement("div");
  meta.className = "cron-item-meta";
  const trigText = task.trigger ? (TRIGGER_TEXT[task.trigger.type] || (() => ""))(task.trigger) : "";
  const nextText = task.next_run_at ? `下次: ${task.next_run_at.replace("T", " ").slice(5, 16)}` : STATUS_TEXT[status];
  meta.textContent = `${trigText} · ${nextText}`;

  body.appendChild(name);
  body.appendChild(meta);

  // 悬停操作按钮
  const actions = document.createElement("div");
  actions.className = "cron-item-actions";

  // toggle: 启用时显示暂停图标，禁用时显示启用（播放）图标
  actions.appendChild(makeActionBtn(task.task_id, "toggle",
    task.enabled ? "暂停" : "启用", task.enabled ? SVG_PAUSE : SVG_PLAY, false));
  actions.appendChild(makeActionBtn(task.task_id, "run", "立即运行", SVG_PLAY, false));
  actions.appendChild(makeActionBtn(task.task_id, "edit", "编辑", null, false, "/image/编辑.svg"));
  actions.appendChild(makeActionBtn(task.task_id, "delete", "删除", null, true, "/image/删除.svg"));

  li.appendChild(dot);
  li.appendChild(body);
  li.appendChild(actions);
  return li;
}

// 内联 SVG（缺失图标文件的兜底，保证渲染清晰）
const SVG_PAUSE = '<svg viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="2" width="4" height="12" rx="1"/><rect x="9" y="2" width="4" height="12" rx="1"/></svg>';
const SVG_PLAY = '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M4 2.5v11a.5.5 0 0 0 .77.42l8.5-5.5a.5.5 0 0 0 0-.84l-8.5-5.5A.5.5 0 0 0 4 2.5z"/></svg>';

// ===== 闹钟式触发 UI 构建与 cron 互转 =====
// 周几定义（cron 标准：0=周日, 1=周一 ... 6=周六），显示顺序为周一~周日
const WEEKDAYS = [
  { cron: 1, label: '一' },
  { cron: 2, label: '二' },
  { cron: 3, label: '三' },
  { cron: 4, label: '四' },
  { cron: 5, label: '五' },
  { cron: 6, label: '六' },
  { cron: 0, label: '日' },
];

const ARROW_UP = '<svg viewBox="0 0 12 12" fill="currentColor"><path d="M6 2.2l4.2 4.8H1.8z"/></svg>';
const ARROW_DOWN = '<svg viewBox="0 0 12 12" fill="currentColor"><path d="M6 9.8L1.8 5h8.4z"/></svg>';

// 闹钟式选择器实例（在 bindCronEditorEvents 中构建）
let _alarmWeekdayPicker = null;
let _alarmTimePicker = null;
let _onceDatePicker = null;
let _onceTimePicker = null;

// cron 表达式 → 闹钟状态 {weekdays, hour, minute}；无法解析返回 null
function cronToAlarm(cronExpr) {
  if (!cronExpr) return null;
  const parts = String(cronExpr).trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minF, hourF, domF, monF, dowF] = parts;
  // 仅支持 "分 时 * * 周" 的闹钟式形态（不支持 */N、范围、步进）
  if (domF !== '*' || monF !== '*') return null;
  if (!/^\d+$/.test(minF) || !/^\d+$/.test(hourF)) return null;
  const minute = parseInt(minF, 10);
  const hour = parseInt(hourF, 10);
  if (minute < 0 || minute > 59 || hour < 0 || hour > 23) return null;
  let weekdays;
  if (dowF === '*') {
    weekdays = [0, 1, 2, 3, 4, 5, 6];
  } else {
    if (!/^[\d,]+$/.test(dowF)) return null;
    const nums = dowF.split(',').map((s) => parseInt(s, 10));
    if (nums.some((n) => n < 0 || n > 7)) return null;
    weekdays = [...new Set(nums.map((n) => (n === 7 ? 0 : n)))];
    if (weekdays.length === 0) return null;
  }
  return { weekdays, hour, minute };
}

// 闹钟状态 → cron 表达式（全选周几时 DOW 用 * 表示每天）
function alarmToCron(weekdays, hour, minute) {
  const h = String(hour).padStart(2, '0');
  const m = String(minute).padStart(2, '0');
  let dow;
  if (!weekdays || weekdays.length === 0 || weekdays.length === 7) {
    dow = '*';
  } else {
    dow = [...weekdays].sort((a, b) => {
      // 排序：周一(1)~周六(6)在前，周日(0)最后
      const ra = a === 0 ? 7 : a;
      const rb = b === 0 ? 7 : b;
      return ra - rb;
    }).join(',');
  }
  return `${m} ${h} * * ${dow}`;
}

// 构建时分滚轮选择器：上下箭头 + 点击输入 + 滚轮
function buildTimePicker(container, initHour, initMinute) {
  if (!container) return null;
  container.innerHTML = '';
  let hour = initHour ?? 9;
  let minute = initMinute ?? 0;

  function makeUnit(max, getVal, setVal) {
    const unit = document.createElement('div');
    unit.className = 'cron-time-unit';
    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'cron-time-arrow';
    upBtn.innerHTML = ARROW_UP;
    upBtn.setAttribute('aria-label', '增加');
    const valEl = document.createElement('div');
    valEl.className = 'cron-time-value';
    valEl.textContent = String(getVal()).padStart(2, '0');
    valEl.tabIndex = 0;
    valEl.setAttribute('role', 'spinbutton');
    valEl.setAttribute('aria-valuemin', '0');
    valEl.setAttribute('aria-valuemax', String(max));
    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'cron-time-arrow';
    downBtn.innerHTML = ARROW_DOWN;
    downBtn.setAttribute('aria-label', '减少');

    const render = () => { valEl.textContent = String(getVal()).padStart(2, '0'); valEl.setAttribute('aria-valuenow', String(getVal())); };
    const bump = (delta) => {
      let v = getVal() + delta;
      if (v < 0) v = max;
      if (v > max) v = 0;
      setVal(v);
      render();
    };
    upBtn.addEventListener('click', () => bump(1));
    downBtn.addEventListener('click', () => bump(-1));

    // 点击数值进入可编辑态，回车/失焦提交
    const enterEdit = () => {
      valEl.classList.add('is-editing');
      valEl.contentEditable = 'true';
      valEl.focus();
      const range = document.createRange();
      range.selectNodeContents(valEl);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    };
    const commitEdit = () => {
      valEl.classList.remove('is-editing');
      valEl.contentEditable = 'false';
      const raw = (valEl.textContent || '').replace(/\D/g, '');
      let v = raw ? parseInt(raw, 10) : getVal();
      if (isNaN(v)) v = getVal();
      if (v < 0) v = 0;
      if (v > max) v = max;
      setVal(v);
      render();
    };
    valEl.addEventListener('click', enterEdit);
    valEl.addEventListener('blur', commitEdit);
    valEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); valEl.blur(); }
      else if (e.key === 'Escape') { render(); valEl.blur(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); bump(1); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); bump(-1); }
    });
    // 鼠标滚轮在 unit 内滚动调值
    unit.addEventListener('wheel', (e) => {
      e.preventDefault();
      bump(e.deltaY < 0 ? 1 : -1);
    }, { passive: false });

    unit.appendChild(upBtn);
    unit.appendChild(valEl);
    unit.appendChild(downBtn);
    return { unit, render };
  }

  const hourUnit = makeUnit(23, () => hour, (v) => { hour = v; });
  const sep = document.createElement('span');
  sep.className = 'cron-time-sep';
  sep.textContent = ':';
  const minUnit = makeUnit(59, () => minute, (v) => { minute = v; });

  container.appendChild(hourUnit.unit);
  container.appendChild(sep);
  container.appendChild(minUnit.unit);

  return {
    getHour: () => hour,
    getMinute: () => minute,
    setHour: (v) => { hour = Math.max(0, Math.min(23, v | 0)); hourUnit.render(); },
    setMinute: (v) => { minute = Math.max(0, Math.min(59, v | 0)); minUnit.render(); },
  };
}

// 构建周几方块选择器：点击切换 + 弹跳动画
function buildWeekdaySelector(container, selected) {
  if (!container) return null;
  container.innerHTML = '';
  const set = new Set(selected || []);
  WEEKDAYS.forEach((wd) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cron-weekday-btn' + (set.has(wd.cron) ? ' is-on' : '');
    btn.textContent = wd.label;
    btn.dataset.cron = String(wd.cron);
    btn.setAttribute('aria-pressed', set.has(wd.cron) ? 'true' : 'false');
    btn.addEventListener('click', () => {
      if (set.has(wd.cron)) {
        set.delete(wd.cron);
        btn.classList.remove('is-on');
        btn.setAttribute('aria-pressed', 'false');
      } else {
        set.add(wd.cron);
        // 强制 reflow 重启弹跳动画
        btn.classList.remove('is-on');
        void btn.offsetWidth;
        btn.classList.add('is-on');
        btn.setAttribute('aria-pressed', 'true');
      }
    });
    container.appendChild(btn);
  });
  return {
    getWeekdays: () => [...set],
    setWeekdays: (arr) => {
      set.clear();
      (arr || []).forEach((d) => set.add(d));
      container.querySelectorAll('.cron-weekday-btn').forEach((b) => {
        const on = set.has(Number(b.dataset.cron));
        b.classList.toggle('is-on', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    },
  };
}

// 构建主题化日期选择器：触发按钮 + 下拉日历
function buildDatePicker(container, initialDate) {
  if (!container) return null;
  container.innerHTML = '';
  let selected = initialDate ? { ...initialDate } : null;
  const today = new Date();
  let viewYear, viewMonth;
  if (initialDate) {
    viewYear = initialDate.year;
    viewMonth = initialDate.month;
  } else {
    viewYear = today.getFullYear();
    viewMonth = today.getMonth();
  }

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'cron-date-trigger';
  trigger.innerHTML = '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M5 1a1 1 0 0 1 1 1v1h4V2a1 1 0 1 1 2 0v1h1a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h1V2a1 1 0 0 1 1-1zM3 6v8h10V6H3z"/></svg><span class="cron-date-trigger-text"></span>';
  const trigText = trigger.querySelector('.cron-date-trigger-text');
  container.appendChild(trigger);

  const cal = document.createElement('div');
  cal.className = 'cron-calendar';
  cal.hidden = true;
  container.appendChild(cal);

  const fmtSelected = () => selected
    ? `${selected.year}-${String(selected.month + 1).padStart(2, '0')}-${String(selected.day).padStart(2, '0')}`
    : '';
  const updateTrigger = () => {
    if (selected) {
      trigText.textContent = fmtSelected();
      trigger.classList.remove('is-placeholder');
    } else {
      trigText.textContent = '选择日期…';
      trigger.classList.add('is-placeholder');
    }
  };

  function renderCalendar() {
    cal.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'cron-calendar-header';
    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'cron-calendar-nav';
    prevBtn.innerHTML = '<svg viewBox="0 0 12 12" fill="currentColor"><path d="M8 1L3 6l5 5z"/></svg>';
    prevBtn.setAttribute('aria-label', '上个月');
    const title = document.createElement('span');
    title.className = 'cron-calendar-title';
    title.textContent = `${viewYear}年${viewMonth + 1}月`;
    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'cron-calendar-nav';
    nextBtn.innerHTML = '<svg viewBox="0 0 12 12" fill="currentColor"><path d="M4 1l5 5-5 5z"/></svg>';
    nextBtn.setAttribute('aria-label', '下个月');
    prevBtn.addEventListener('click', () => {
      viewMonth--;
      if (viewMonth < 0) { viewMonth = 11; viewYear--; }
      renderCalendar();
    });
    nextBtn.addEventListener('click', () => {
      viewMonth++;
      if (viewMonth > 11) { viewMonth = 0; viewYear++; }
      renderCalendar();
    });
    header.appendChild(prevBtn);
    header.appendChild(title);
    header.appendChild(nextBtn);
    cal.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'cron-calendar-grid';
    ['日', '一', '二', '三', '四', '五', '六'].forEach((d) => {
      const dow = document.createElement('span');
      dow.className = 'cron-calendar-dow';
      dow.textContent = d;
      grid.appendChild(dow);
    });

    const firstDay = new Date(viewYear, viewMonth, 1).getDay();
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const daysInPrev = new Date(viewYear, viewMonth, 0).getDate();
    const todayY = today.getFullYear();
    const todayM = today.getMonth();
    const todayD = today.getDate();

    for (let i = firstDay - 1; i >= 0; i--) {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'cron-calendar-day is-other-month';
      cell.textContent = String(daysInPrev - i);
      cell.disabled = true;
      grid.appendChild(cell);
    }
    for (let day = 1; day <= daysInMonth; day++) {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'cron-calendar-day';
      cell.textContent = String(day);
      if (viewYear === todayY && viewMonth === todayM && day === todayD) cell.classList.add('is-today');
      if (selected && selected.year === viewYear && selected.month === viewMonth && selected.day === day) cell.classList.add('is-selected');
      cell.addEventListener('click', () => {
        selected = { year: viewYear, month: viewMonth, day };
        renderCalendar();
        updateTrigger();
        cal.hidden = true;
      });
      grid.appendChild(cell);
    }
    const totalCells = firstDay + daysInMonth;
    const trailing = (7 - (totalCells % 7)) % 7;
    for (let i = 1; i <= trailing; i++) {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'cron-calendar-day is-other-month';
      cell.textContent = String(i);
      cell.disabled = true;
      grid.appendChild(cell);
    }
    cal.appendChild(grid);

    const footer = document.createElement('div');
    footer.className = 'cron-calendar-footer';
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'cron-cal-clear';
    clearBtn.textContent = '清除';
    clearBtn.addEventListener('click', () => {
      selected = null;
      updateTrigger();
      renderCalendar();
    });
    const todayBtn = document.createElement('button');
    todayBtn.type = 'button';
    todayBtn.className = 'cron-cal-today';
    todayBtn.textContent = '今天';
    todayBtn.addEventListener('click', () => {
      viewYear = todayY; viewMonth = todayM;
      selected = { year: todayY, month: todayM, day: todayD };
      updateTrigger();
      renderCalendar();
      cal.hidden = true;
    });
    footer.appendChild(clearBtn);
    footer.appendChild(todayBtn);
    cal.appendChild(footer);
  }

  trigger.addEventListener('click', () => {
    cal.hidden = !cal.hidden;
    if (!cal.hidden) renderCalendar();
  });
  // 点击外部关闭日历
  const outsideHandler = (e) => {
    if (cal.hidden) return;
    if (!container.contains(e.target)) cal.hidden = true;
  };
  document.addEventListener('click', outsideHandler);

  updateTrigger();
  return {
    getSelected: () => fmtSelected(),
    setSelected: (dateStr) => {
      if (!dateStr) { selected = null; updateTrigger(); return; }
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
      if (m) {
        selected = { year: parseInt(m[1], 10), month: parseInt(m[2], 10) - 1, day: parseInt(m[3], 10) };
        viewYear = selected.year;
        viewMonth = selected.month;
      }
      updateTrigger();
    },
  };
}

function makeActionBtn(taskId, action, title, inlineSvg, danger, iconSrc) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cron-item-action-btn" + (danger ? " danger" : "");
  btn.title = title;
  btn.dataset.taskId = taskId;
  btn.dataset.cronAction = action;
  if (iconSrc) {
    const img = document.createElement("img");
    img.src = iconSrc;
    img.alt = "";
    btn.appendChild(img);
  } else if (inlineSvg) {
    btn.innerHTML = inlineSvg;
  }
  return btn;
}

async function handleListAction(action, taskId) {
  if (action === "toggle") {
    try {
      await api(`/api/cron/${encodeURIComponent(taskId)}/toggle`, { method: "POST" });
      await renderCronTasks();
      if (taskId === state.activeCronTaskId) await refreshCronBanner();
    } catch (e) { showToast("切换状态失败: " + (e.message || e)); }
  } else if (action === "run") {
    if (taskId === state.activeCronTaskId) {
      await runCronTaskNow(taskId, null);
    } else {
      await selectCronTask(taskId);
      await runCronTaskNow(taskId, null);
    }
  } else if (action === "edit") {
    openCronEditor(taskId);
  } else if (action === "delete") {
    const ok = await showConfirm(`确认删除该定时任务？\n\n任务的所有执行记录将被一并删除，此操作不可撤销。`);
    if (!ok) return;
    try {
      await api(`/api/cron/${encodeURIComponent(taskId)}`, { method: "DELETE" });
      if (taskId === state.activeCronTaskId) {
        state.activeCronTaskId = "";
        showCronEmptyState();
      }
      await renderCronTasks();
      showToast("已删除定时任务");
    } catch (e) { showToast("删除失败: " + (e.message || e)); }
  }
}

// ===== 选中任务 / 加载消息 =====
export async function selectCronTask(taskId, opts = {}) {
  if (!taskId) return;
  state.activeCronTaskId = taskId;
  // 更新列表选中态
  cronListEl?.querySelectorAll(".cron-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.cronTaskId === taskId);
  });
  await loadCronMessages(taskId);
  await refreshCronBanner();
  // 若任务正在运行，接入 SSE 实时流
  const task = state.cronTasks.find((t) => t.task_id === taskId);
  const running = task ? !!task.is_running : false;
  if (running) {
    startCronRunningSession(taskId);
  }
}

async function loadCronMessages(taskId) {
  try {
    const data = await api(`/api/cron/${encodeURIComponent(taskId)}/messages`);
    const msgs = data.messages || [];
    showCronChatArea();
    if (msgs.length === 0) {
      // 任务尚无执行记录：展示提示而非触发 chat 欢迎屏
      if (chatMessagesEl) {
        chatMessagesEl.hidden = false;
        chatMessagesEl.style.display = "";
        chatMessagesEl.innerHTML = "";
        const note = document.createElement("div");
        note.className = "msg assistant";
        note.innerHTML = `<div class="msg-bubble"><div class="cron-empty-record">该任务暂无执行记录。点击顶部"立即运行"可手动触发一次。</div></div>`;
        chatMessagesEl.appendChild(note);
      }
      if (chatPlaceholderEl) chatPlaceholderEl.hidden = true;
    } else {
      renderMessages(msgs);
    }
    // 若有 last_error 且非运行中，追加错误提示
    if (data.last_error && data.last_status === "failed") {
      appendCronErrorNote(data.last_error);
    }
  } catch (e) {
    showToast("加载执行记录失败: " + (e.message || e));
    showCronEmptyState();
  }
}

function appendCronErrorNote(error) {
  if (!chatMessagesEl) return;
  const note = document.createElement("div");
  note.className = "msg assistant";
  note.innerHTML = `<div class="msg-bubble"><div class="cron-error-note">⚠ 上次执行失败: ${escapeHtml(String(error).slice(0, 300))}</div></div>`;
  chatMessagesEl.appendChild(note);
  scrollChatToBottom();
}

// ===== 顶部任务信息条 =====
async function refreshCronBanner() {
  const taskId = state.activeCronTaskId;
  if (!taskId) { hideCronBanner(); return; }
  let task;
  try {
    const data = await api(`/api/cron/${encodeURIComponent(taskId)}`);
    task = data.task;
  } catch { task = state.cronTasks.find((t) => t.task_id === taskId); }
  if (!task) { hideCronBanner(); return; }
  renderCronBanner(task);
}

function renderCronBanner(task) {
  ensureCronBanner();
  const status = task.is_running ? "running" : (task.last_status || "pending");
  const trigText = task.trigger ? (TRIGGER_TEXT[task.trigger.type] || (() => ""))(task.trigger) : "";
  const nextText = task.next_run_at ? `下次运行 ${task.next_run_at.replace("T", " ").slice(0, 16)}` : "无后续运行";

  cronBannerEl.innerHTML = "";
  const name = document.createElement("span");
  name.className = "cron-chat-banner-name";
  name.textContent = task.name || "未命名任务";

  const info = document.createElement("div");
  info.className = "cron-chat-banner-info";
  info.innerHTML = `<span>${escapeHtml(trigText)}</span><span>${escapeHtml(nextText)}</span>`;

  const badge = document.createElement("span");
  badge.className = `cron-status-badge cron-status-badge--${status}`;
  badge.textContent = STATUS_TEXT[status] || status;
  info.appendChild(badge);

  const actions = document.createElement("div");
  actions.className = "cron-banner-actions";
  if (status === "running") {
    const abortBtn = document.createElement("button");
    abortBtn.type = "button";
    abortBtn.className = "cron-banner-btn cron-banner-btn--danger";
    abortBtn.textContent = "终止";
    abortBtn.addEventListener("click", () => abortCronTask());
    actions.appendChild(abortBtn);
  } else {
    const runBtn = document.createElement("button");
    runBtn.type = "button";
    runBtn.className = "cron-banner-btn";
    runBtn.textContent = "立即运行";
    runBtn.addEventListener("click", () => runCronTaskNow(task.task_id, null));
    actions.appendChild(runBtn);
  }

  cronBannerEl.appendChild(name);
  cronBannerEl.appendChild(info);
  cronBannerEl.appendChild(actions);
  cronBannerEl.hidden = false;
}

function hideCronBanner() {
  if (cronBannerEl) cronBannerEl.hidden = true;
}

// ===== 运行 / 追问 =====
export async function runCronTaskNow(taskId, prompt) {
  if (!taskId) return;
  if (state.cronRunning) { showToast("任务正在运行中"); return; }
  try {
    await api(`/api/cron/${encodeURIComponent(taskId)}/run`, {
      method: "POST",
      body: JSON.stringify(prompt ? { prompt } : {}),
    });
  } catch (e) {
    showToast("启动任务失败: " + (e.message || e));
    return;
  }
  startCronRunningSession(taskId);
}

// 启动运行态：SSE 实时流 + 状态轮询 + 思考气泡
function startCronRunningSession(taskId) {
  state.cronRunning = true;
  updateSendBtnForCron();
  // 追加思考气泡作为 live 工具调用挂载点
  _typingEl = appendThinkingIndicator();
  _collectedReflections = [];
  _lastReflectionCount = 0;
  _turnStartedAt = null;
  startCronLiveStream(taskId);
  startStatusPolling(taskId);
  refreshCronBanner();
}

// 追问发送（由 app.js 在 cron 模式下调用）
export async function sendCronChat() {
  const taskId = state.activeCronTaskId;
  if (!taskId) { showToast("请先选择一个定时任务"); return; }
  if (state.cronRunning) { showToast("任务正在运行中，请等待完成或终止"); return; }
  const trimmed = textInputEl ? textInputEl.value.trim() : "";
  if (!trimmed) return;
  if (textInputEl) textInputEl.value = "";
  await runCronTaskNow(taskId, trimmed);
}

export async function abortCronTask() {
  const taskId = state.activeCronTaskId;
  if (!taskId || !state.cronRunning) return;
  const ok = await showConfirm("确认终止当前运行中的定时任务？\n\n已完成的工具调用将被保留。");
  if (!ok) return;
  try {
    await api(`/api/cron/${encodeURIComponent(taskId)}/abort`, { method: "POST" });
  } catch (e) { showToast("终止失败: " + (e.message || e)); }
  // 状态将由 finished/SSE 或轮询收敛
}

export function isCronRunning() { return state.cronRunning; }

// ===== SSE 实时流（复用 injectLiveToolCalls 契约） =====
function startCronLiveStream(taskId) {
  stopCronLiveStream();
  try {
    _eventSource = new EventSource(`/api/cron/${encodeURIComponent(taskId)}/live/stream`);
  } catch {
    return;
  }
  _eventSource.addEventListener("update", (e) => {
    try { handleLiveSnapshot(JSON.parse(e.data)); } catch { /* ignore */ }
  });
  _eventSource.addEventListener("finished", (e) => {
    try {
      const data = e.data ? JSON.parse(e.data) : {};
      handleCronFinished(state.activeCronTaskId, data);
    } catch { handleCronFinished(state.activeCronTaskId, {}); }
  });
  _eventSource.addEventListener("ping", () => { /* 心跳保活 */ });
  _eventSource.onerror = () => {
    if (_eventSource) { _eventSource.close(); _eventSource = null; }
    // 非运行态不重连；运行态延迟重连以接续 live
    if (state.cronRunning && _cronActive) {
      _reconnectTimer = setTimeout(() => {
        if (state.cronRunning && _cronActive) startCronLiveStream(taskId);
      }, 1500);
    }
  };
}

function stopCronLiveStream() {
  if (_eventSource) { _eventSource.close(); _eventSource = null; }
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
}

function handleLiveSnapshot(liveData) {
  if (!liveData) return;
  if (liveData.started_at && !_turnStartedAt) {
    _turnStartedAt = Number(liveData.started_at);
  }
  // 收集思考内容
  if (liveData.reflections && liveData.reflections.length > _lastReflectionCount) {
    const newOnes = liveData.reflections.slice(_lastReflectionCount);
    newOnes.forEach((r) => {
      if (r && r.content) {
        _collectedReflections.push({ content: r.content, between_calls: liveData.tool_calls ? liveData.tool_calls.length : -1 });
      }
    });
    _lastReflectionCount = liveData.reflections.length;
  }
  // 工具调用渲染
  if (_typingEl && liveData.tool_calls && liveData.tool_calls.length > 0) {
    injectLiveToolCalls(_typingEl, liveData.tool_calls, _turnStartedAt, _collectedReflections);
  }
}

// ===== 状态轮询（备份 finished 检测 + banner 更新） =====
function startStatusPolling(taskId) {
  stopStatusPolling();
  const poll = async () => {
    if (!state.cronRunning || !_cronActive) return;
    try {
      const data = await api(`/api/cron/${encodeURIComponent(taskId)}`);
      const t = data.task;
      if (t && !t.is_running && t.last_status !== "running") {
        // 任务已结束
        handleCronFinished(taskId, { status: t.last_status, error: t.last_error });
        return;
      }
      // 仍在运行：刷新 banner
      renderCronBanner(t);
    } catch { /* ignore */ }
    if (state.cronRunning && _cronActive) {
      _statusPollTimer = setTimeout(poll, 2500);
    }
  };
  _statusPollTimer = setTimeout(poll, 2500);
}

function stopStatusPolling() {
  if (_statusPollTimer) { clearTimeout(_statusPollTimer); _statusPollTimer = null; }
}

// 任务结束收敛：移除思考气泡、停止流、重载消息、更新状态
async function handleCronFinished(taskId, data) {
  if (!state.cronRunning) return;
  state.cronRunning = false;
  stopCronLiveStream();
  stopStatusPolling();
  // 移除思考气泡
  if (_typingEl && _typingEl.parentNode) {
    const wrap = _typingEl.querySelector(".tool-call-list-wrap");
    if (wrap && typeof wrap._stopTimer === "function") wrap._stopTimer();
    _typingEl.remove();
  }
  _typingEl = null;
  _collectedReflections = [];
  _lastReflectionCount = 0;
  _turnStartedAt = null;
  updateSendBtnForCron();
  // 刷新列表 + banner + 消息
  await renderCronTasks();
  if (taskId === state.activeCronTaskId) {
    await loadCronMessages(taskId);
    await refreshCronBanner();
  }
  // 状态提示
  const status = data && data.status;
  if (status === "failed") {
    showToast("定时任务执行失败" + (data.error ? `: ${String(data.error).slice(0, 80)}` : ""));
  } else if (status === "completed") {
    showToast("定时任务执行完成");
  }
}

function stopCronLive() {
  stopCronLiveStream();
  stopStatusPolling();
  if (_typingEl && _typingEl.parentNode) {
    const wrap = _typingEl.querySelector(".tool-call-list-wrap");
    if (wrap && typeof wrap._stopTimer === "function") wrap._stopTimer();
    _typingEl.remove();
  }
  _typingEl = null;
  state.cronRunning = false;
}

// ===== 发送按钮状态（cron 模式） =====
function updateSendBtnForCron() {
  if (!sendBtnEl) return;
  if (state.cronRunning) {
    sendBtnEl.classList.add("btn-pause");
    sendBtnEl.disabled = false;
    sendBtnEl.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="2" width="4" height="12" rx="1"/><rect x="9" y="2" width="4" height="12" rx="1"/></svg>';
  } else {
    sendBtnEl.classList.remove("btn-pause");
    sendBtnEl.disabled = false;
    sendBtnEl.innerHTML = '<img src="/image/发送.svg" alt="" aria-hidden="true" class="send-btn-icon" />';
  }
}

// ===== 占位 / 聊天区显隐管理 =====
function ensureCronPlaceholders() {
  ensureCronBanner();
  ensureCronEmptyPlaceholder();
}

function ensureCronBanner() {
  if (cronBannerEl || !chatPanelEl) return;
  cronBannerEl = document.createElement("div");
  cronBannerEl.className = "cron-chat-banner";
  cronBannerEl.hidden = true;
  chatPanelEl.insertBefore(cronBannerEl, chatPanelEl.firstChild);
}

function ensureCronEmptyPlaceholder() {
  if (cronPlaceholderEl || !chatPanelEl) return;
  cronPlaceholderEl = document.createElement("div");
  cronPlaceholderEl.className = "cron-chat-placeholder";
  cronPlaceholderEl.hidden = true;
  cronPlaceholderEl.innerHTML = `
    <img src="/image/时钟.svg" alt="" />
    <h3>定时任务模式</h3>
    <p>从左侧选择一个任务查看执行记录，或点击 + 新建定时任务。任务触发时将自动在子进程执行，运行过程实时展示于此，完成后可继续追问。</p>
  `;
  chatPanelEl.appendChild(cronPlaceholderEl);
}

function hideCronPlaceholders() {
  if (cronBannerEl) cronBannerEl.hidden = true;
  if (cronPlaceholderEl) cronPlaceholderEl.hidden = true;
}

function showCronEmptyState() {
  if (!chatPanelEl) return;
  ensureCronPlaceholders();
  if (chatPlaceholderEl) chatPlaceholderEl.hidden = true;
  if (chatMessagesEl) { chatMessagesEl.hidden = true; chatMessagesEl.style.display = "none"; }
  if (cronPlaceholderEl) cronPlaceholderEl.hidden = false;
  hideCronBanner();
  // cron 空状态保持输入框在底部，避免触发 chat 欢迎屏（welcomeView）
  import("../app.js").then((m) => m.setComposerCentered(false)).catch(() => {});
}

function showCronChatArea() {
  ensureCronPlaceholders();
  if (cronPlaceholderEl) cronPlaceholderEl.hidden = true;
  if (chatMessagesEl) { chatMessagesEl.hidden = false; chatMessagesEl.style.display = ""; }
  if (chatPlaceholderEl) chatPlaceholderEl.hidden = true;
  import("../app.js").then((m) => m.setComposerCentered(false)).catch(() => {});
}

// 离开 cron 模式时恢复聊天会话视图
async function restoreChatView() {
  if (!chatPanelEl) return;
  // 隐藏 cron 专属元素
  if (cronBannerEl) cronBannerEl.hidden = true;
  if (cronPlaceholderEl) cronPlaceholderEl.hidden = true;
  // 重新加载当前聊天会话消息
  try {
    if (state.sessionId) {
      const data = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/messages`);
      renderMessages(data.messages || []);
    } else {
      renderMessages([]);
    }
  } catch {
    // 静默失败，保留现状
  }
}

// ===== 编辑 / 新建弹窗 =====
function bindCronEditorEvents() {
  // 弹窗 DOM 由 index.html 提供；此处只绑定事件
  const overlay = $("cronEditOverlay");
  if (!overlay) return;
  cronEditOverlayEl = overlay;

  $("cronEditClose")?.addEventListener("click", () => closeCronEditor());
  $("cronEditCancel")?.addEventListener("click", () => closeCronEditor());
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeCronEditor();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay && !overlay.hidden) closeCronEditor();
  });

  // 触发类型分段切换
  overlay.querySelectorAll(".cron-trigger-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      overlay.querySelectorAll(".cron-trigger-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const t = btn.dataset.triggerType;
      toggleTriggerFields(t);
    });
  });

  // 构建闹钟式选择器（cron 类型）与主题化日期时间选择器（once 类型）
  _alarmWeekdayPicker = buildWeekdaySelector($("cronWeekdayRow"), [1, 2, 3, 4, 5]);
  _alarmTimePicker = buildTimePicker($("cronTimePicker"), 9, 0);
  _onceDatePicker = buildDatePicker($("cronDatePicker"), null);
  _onceTimePicker = buildTimePicker($("cronOnceTimePicker"), 9, 0);

  // 高级模式切换：闹钟 ⇄ 手动 cron 输入
  $("cronAdvancedToggle")?.addEventListener("click", () => {
    const picker = $("cronAlarmPicker");
    const raw = $("cronAdvancedRaw");
    if (!picker || !raw) return;
    const mode = picker.dataset.mode;
    if (mode === "alarm") {
      // 切到高级：把当前闹钟状态生成的 cron 填入 raw 输入框
      if (_alarmWeekdayPicker && _alarmTimePicker) {
        $("cronEditCron").value = alarmToCron(
          _alarmWeekdayPicker.getWeekdays(),
          _alarmTimePicker.getHour(),
          _alarmTimePicker.getMinute(),
        );
      }
      raw.hidden = false;
      picker.dataset.mode = "advanced";
      $("cronAdvancedToggle").textContent = "返回闹钟模式";
    } else {
      // 切回闹钟：尝试解析 raw cron，成功则同步到闹钟 UI
      const cron = ($("cronEditCron").value || "").trim();
      const alarm = cronToAlarm(cron);
      if (alarm) {
        _alarmWeekdayPicker?.setWeekdays(alarm.weekdays);
        _alarmTimePicker?.setHour(alarm.hour);
        _alarmTimePicker?.setMinute(alarm.minute);
      }
      raw.hidden = true;
      picker.dataset.mode = "alarm";
      $("cronAdvancedToggle").textContent = "高级：手动输入 cron 表达式";
    }
  });

  // 启用开关
  $("cronEnabledSwitch")?.addEventListener("click", () => {
    const sw = $("cronEnabledSwitch");
    const on = sw.dataset.on !== "true";
    sw.dataset.on = on ? "true" : "false";
  });

  // 保存
  $("cronEditSave")?.addEventListener("click", () => saveCronTask());
}

function toggleTriggerFields(type) {
  const overlay = cronEditOverlayEl;
  if (!overlay) return;
  overlay.querySelector("[data-trigger-field='cron']").hidden = type !== "cron";
  overlay.querySelector("[data-trigger-field='interval']").hidden = type !== "interval";
  overlay.querySelector("[data-trigger-field='once']").hidden = type !== "once";
}

// 初始化 cron 闹钟选择器（编辑/新建共用）
// 能解析为闹钟式 → 闹钟模式；无法解析但有 cron → 高级模式；无 cron → 默认值
function initCronAlarmPicker(cronExpr, defaultWeekdays, defaultHour, defaultMinute) {
  const picker = $("cronAlarmPicker");
  const raw = $("cronAdvancedRaw");
  const toggleBtn = $("cronAdvancedToggle");
  const cronInput = $("cronEditCron");
  if (!picker) return;
  const defWd = defaultWeekdays || [1, 2, 3, 4, 5];
  const defH = defaultHour ?? 9;
  const defM = defaultMinute ?? 0;
  const alarm = cronToAlarm(cronExpr);
  if (alarm) {
    _alarmWeekdayPicker?.setWeekdays(alarm.weekdays);
    _alarmTimePicker?.setHour(alarm.hour);
    _alarmTimePicker?.setMinute(alarm.minute);
    if (cronInput) cronInput.value = cronExpr;
    if (raw) raw.hidden = true;
    picker.dataset.mode = "alarm";
    if (toggleBtn) toggleBtn.textContent = "高级：手动输入 cron 表达式";
  } else if (cronExpr) {
    // 无法解析为闹钟式：进入高级模式，保留原始 cron
    if (cronInput) cronInput.value = cronExpr;
    if (raw) raw.hidden = false;
    picker.dataset.mode = "advanced";
    if (toggleBtn) toggleBtn.textContent = "返回闹钟模式";
    _alarmWeekdayPicker?.setWeekdays(defWd);
    _alarmTimePicker?.setHour(defH);
    _alarmTimePicker?.setMinute(defM);
  } else {
    _alarmWeekdayPicker?.setWeekdays(defWd);
    _alarmTimePicker?.setHour(defH);
    _alarmTimePicker?.setMinute(defM);
    if (cronInput) cronInput.value = alarmToCron(defWd, defH, defM);
    if (raw) raw.hidden = true;
    picker.dataset.mode = "alarm";
    if (toggleBtn) toggleBtn.textContent = "高级：手动输入 cron 表达式";
  }
}

// 初始化 once 日期+时间选择器
function initOncePicker(runAt) {
  if (runAt) {
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(runAt);
    if (m) {
      _onceDatePicker?.setSelected(m[1]);
      _onceTimePicker?.setHour(parseInt(m[2], 10));
      _onceTimePicker?.setMinute(parseInt(m[3], 10));
      return;
    }
  }
  // 新建：默认 1 小时后（避免一创建即过期）
  const future = new Date(Date.now() + 60 * 60 * 1000);
  const dateStr = `${future.getFullYear()}-${String(future.getMonth() + 1).padStart(2, "0")}-${String(future.getDate()).padStart(2, "0")}`;
  _onceDatePicker?.setSelected(dateStr);
  _onceTimePicker?.setHour(future.getHours());
  _onceTimePicker?.setMinute(0);
}

export function openCronEditor(taskId) {
  const overlay = $("cronEditOverlay");
  if (!overlay) return;
  state._cronEditingTaskId = taskId || "";
  $("cronEditTitle").textContent = taskId ? "编辑定时任务" : "新建定时任务";

  // 访问模式提示：定时任务无人值守，非「完全访问」时越界会被拦截/退化拦截
  const accessHint = $("cronAccessModeHint");
  if (accessHint) {
    const modeLabel = { restricted: "限制访问", approval: "权限审查", full: "完全访问" }[state.accessMode] || state.accessMode;
    if (state.accessMode === "full") {
      accessHint.hidden = true;
    } else {
      accessHint.hidden = false;
      accessHint.textContent = `⚠️ 定时任务无人值守执行：当前访问模式为「${modeLabel}」，超出工作空间的操作会被拦截或退化拦截，建议先切换为「完全访问」。`;
    }
  }

  // 重置表单
  const setVal = (id, v) => { const el = $(id); if (el) el.value = v ?? ""; };

  if (taskId) {
    // 编辑模式：加载现有任务数据
    const task = state.cronTasks.find((t) => t.task_id === taskId);
    if (!task) { showToast("任务不存在"); return; }
    setVal("cronEditName", task.name);
    setVal("cronEditPrompt", task.prompt);
    setVal("cronEditTimeout", task.timeout_seconds);
    const trig = task.trigger || { type: "cron" };
    setVal("cronEditInterval", trig.interval_seconds);
    // 闹钟式选择器初始化（cron 类型）
    initCronAlarmPicker(trig.cron, [1, 2, 3, 4, 5], 9, 0);
    // 主题化日期时间选择器初始化（once 类型）
    initOncePicker(trig.run_at);
    // 触发类型按钮
    overlay.querySelectorAll(".cron-trigger-type-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.triggerType === trig.type);
    });
    toggleTriggerFields(trig.type);
    // 启用开关
    const sw = $("cronEnabledSwitch");
    if (sw) sw.dataset.on = task.enabled ? "true" : "false";
  } else {
    // 新建模式：默认值
    setVal("cronEditName", "");
    setVal("cronEditPrompt", "");
    setVal("cronEditTimeout", 300);
    setVal("cronEditInterval", 3600);
    // 闹钟式默认：周一至周五 09:00
    initCronAlarmPicker("", [1, 2, 3, 4, 5], 9, 0);
    // once 默认 1 小时后
    initOncePicker("");
    overlay.querySelectorAll(".cron-trigger-type-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.triggerType === "cron");
    });
    toggleTriggerFields("cron");
    const sw = $("cronEnabledSwitch");
    if (sw) sw.dataset.on = "true";
  }

  overlay.hidden = false;
}

function closeCronEditor() {
  const overlay = $("cronEditOverlay");
  if (overlay) overlay.hidden = true;
  state._cronEditingTaskId = "";
}

async function saveCronTask() {
  const overlay = $("cronEditOverlay");
  if (!overlay) return;
  const getVal = (id) => { const el = $(id); return el ? el.value.trim() : ""; };

  const name = getVal("cronEditName");
  const prompt = getVal("cronEditPrompt");
  if (!name) { showToast("请填写任务名称"); return; }
  if (!prompt) { showToast("请填写任务提示词"); return; }

  const activeBtn = overlay.querySelector(".cron-trigger-type-btn.active");
  const triggerType = activeBtn ? activeBtn.dataset.triggerType : "cron";
  const trigger = { type: triggerType };
  if (triggerType === "cron") {
    const picker = $("cronAlarmPicker");
    const mode = picker?.dataset.mode;
    if (mode === "alarm" && _alarmWeekdayPicker && _alarmTimePicker) {
      const weekdays = _alarmWeekdayPicker.getWeekdays();
      if (weekdays.length === 0) { showToast("请至少选择一个星期"); return; }
      trigger.cron = alarmToCron(weekdays, _alarmTimePicker.getHour(), _alarmTimePicker.getMinute());
    } else {
      // 高级模式：读取手动输入的 cron 表达式
      trigger.cron = getVal("cronEditCron");
      if (!trigger.cron) { showToast("请填写 cron 表达式"); return; }
    }
  } else if (triggerType === "interval") {
    trigger.interval_seconds = parseInt(getVal("cronEditInterval"), 10) || 0;
    if (trigger.interval_seconds <= 0) { showToast("请填写大于 0 的间隔秒数"); return; }
  } else if (triggerType === "once") {
    // 从主题化日期 + 时间选择器组装 run_at（ISO 字符串）
    const dateStr = _onceDatePicker ? _onceDatePicker.getSelected() : "";
    if (!dateStr) { showToast("请选择触发日期"); return; }
    const hour = _onceTimePicker ? _onceTimePicker.getHour() : 0;
    const minute = _onceTimePicker ? _onceTimePicker.getMinute() : 0;
    trigger.run_at = `${dateStr}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00`;
    // 同步到隐藏 input（便于其他逻辑读取）
    const runAtInput = $("cronEditRunAt");
    if (runAtInput) runAtInput.value = trigger.run_at;
  }

  const timeout_seconds = parseInt(getVal("cronEditTimeout"), 10) || 300;
  const enabled = $("cronEnabledSwitch")?.dataset.on === "true";

  const payload = { name, prompt, trigger, timeout_seconds, enabled };

  // 提交前检测时段冲突：候选任务时间点前后一个时间段内是否已有其他任务
  try {
    await refreshPeriodMinutes();
    const conflictBody = { trigger };
    const editId = state._cronEditingTaskId;
    if (editId) conflictBody.exclude_task_id = editId;
    const conflictRes = await api("/api/cron/check-conflict", { method: "POST", body: JSON.stringify(conflictBody) });
    if (conflictRes && conflictRes.conflict) {
      const names = (conflictRes.conflict_with && conflictRes.conflict_with.length)
        ? conflictRes.conflict_with.join("、") : "其他任务";
      await showAlert(`时间段内已有其他任务（${names}），需重新设置时间点。\n（当前时间段长度：${conflictRes.period_minutes} 分钟）`);
      return;
    }
  } catch (_) {
    // 冲突检测失败不阻断保存（降级为允许保存）
  }

  const saveBtn = $("cronEditSave");
  if (saveBtn) saveBtn.disabled = true;

  try {
    const taskId = state._cronEditingTaskId;
    if (taskId) {
      await api(`/api/cron/${encodeURIComponent(taskId)}`, { method: "PUT", body: JSON.stringify(payload) });
      showToast("已更新定时任务");
    } else {
      await api("/api/cron", { method: "POST", body: JSON.stringify(payload) });
      showToast("已创建定时任务");
    }
    closeCronEditor();
    await renderCronTasks();
    // 若编辑的是当前选中任务，刷新 banner
    if (taskId && taskId === state.activeCronTaskId) await refreshCronBanner();
  } catch (e) {
    showToast("保存失败: " + (e.message || e));
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}
