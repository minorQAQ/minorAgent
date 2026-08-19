// notify-strip.js -- 通知条系统（替代 todo / pending 浮窗）
//
// 职责:
//   1. 输入区上方长条通知条：todo 步骤摘要条 + 人机交互/审查条
//   2. 左侧按钮点击 → 该条隐藏并在输入区生成对应按钮（画板按钮右侧，从左到右追加）
//   3. 点击输入区按钮 → 按钮消失、对应通知条重新出现
//   4. 点击条内容 → 展开/收起（pending 展开为卡片，多卡片左右切换；展开态隐藏摘要行）
//   5. 会话级存储：chat session 与 cron task 各自保留 todo/pending 状态
//
// 数据源:
//   - todo: live snapshot tool_calls 中 name === "todo_list" 的调用（与原 todo.js 同逻辑）
//   - pending: live snapshot human_requests 数组（human_interaction / tool_call）
//
// 提交: 复用 pending.js handleHumanAction（阻塞式，后端唤醒工具线程）
//
// 性能: 渲染为补丁式——快照驱动/交互时只就地更新变化部分（文本/chip/图标），
//       展开区仅在内容键变化时重建；不做整条重建，避免运行期卡顿。

import { $, escapeHtml, showToast } from './utils.js';
import { state } from './state.js';
import { handleHumanAction } from './pending.js';

// ===== 模块状态 =====

const stripState = {
  todo: { steps: [], doneSteps: [], dismissed: false, expanded: false },
  pending: { items: [], index: 0, dismissed: false, expanded: false },
};

/** 会话级快照：sessionKey → 深拷贝的 stripState */
const _sessionStore = new Map();

/** 输入区动态按钮（按生成顺序从左到右）：[{kind, btn}] */
const _composerBtns = [];

/** 当前通知条所属会话键（chat: sessionId / cron: activeCronTaskId） */
function _currentSessionKey() {
  if (state.mode === "cron") return "cron:" + (state.activeCronTaskId || "");
  return "chat:" + (state.sessionId || "");
}

// ===== 会话级存储 =====

/** 切换会话前保存当前通知条状态 */
export function saveStripSession(key) {
  const k = key || _currentSessionKey();
  if (!k || k.endsWith(":")) return;
  _sessionStore.set(k, JSON.parse(JSON.stringify(stripState)));
  // 防止无限膨胀：只保留最近 40 个会话
  if (_sessionStore.size > 40) {
    const firstKey = _sessionStore.keys().next().value;
    _sessionStore.delete(firstKey);
  }
}

/** 切换到目标会话：保存当前 → 恢复目标 → 重渲染。
 *  @param {string} newKey - 目标会话键
 *  @param {string} [saveKey] - 当前状态应保存到的会话键；
 *      缺省时用 _currentSessionKey()（适用于尚未切换 ID 的场景，如模式切换）；
 *      调用方已改 ID 时必须显式传入旧键，避免旧状态被存到新键下。
 */
export function switchStripSession(newKey, saveKey) {
  saveStripSession(saveKey);
  const target = newKey || _currentSessionKey();
  const saved = _sessionStore.get(target);
  if (saved) {
    stripState.todo = saved.todo || { steps: [], doneSteps: [], dismissed: false, expanded: false };
    stripState.pending = saved.pending || { items: [], index: 0, dismissed: false, expanded: false };
  } else {
    stripState.todo = { steps: [], doneSteps: [], dismissed: false, expanded: false };
    stripState.pending = { items: [], index: 0, dismissed: false, expanded: false };
  }
  _clearComposerBtns();
  renderStrip();
}

// ===== Todo 数据派生（与原 todo.js updateTodoOverlayFromRecords 同逻辑） =====

/** 从 live tool_calls 派生 todo 数据并更新通知条。 */
export function updateTodoStrip(toolCalls) {
  if (!toolCalls || !toolCalls.length) return;
  let steps = null;
  const doneSteps = new Set();
  for (const call of toolCalls) {
    if (!call || call.name !== "todo_list") continue;
    const args = (call.args || {});
    if (Array.isArray(args.steps) && args.steps.length) {
      steps = args.steps.map((s) => String(s));
      doneSteps.clear();
    }
    if (!steps) continue;
    const n = parseInt(args.done_step, 10);
    if (Number.isFinite(n) && n >= 1) {
      for (let i = 0; i < Math.min(n, steps.length); i++) doneSteps.add(i);
    }
  }
  if (!steps) return;
  const prev = stripState.todo;
  const changed = JSON.stringify(prev.steps) !== JSON.stringify(steps)
    || JSON.stringify(prev.doneSteps) !== JSON.stringify([...doneSteps].sort((a, b) => a - b));
  stripState.todo.steps = steps;
  stripState.todo.doneSteps = [...doneSteps].sort((a, b) => a - b);
  // 新 todo 出现 → 重置 dismissed（用户需要重新感知）
  if (changed) stripState.todo.dismissed = false;
  if (changed) renderStrip(); // 仅变化时渲染（补丁式，开销极小）
}

/**
 * 从历史消息回溯该会话的全局 todo 状态（会话级存储）。
 * 扫描消息中 assistant 消息的 meta.tool_calls，取最后一个带 steps 的
 * todo_list 调用重建步骤，后续 done_step 调用累积完成进度。
 * 用于切换/加载会话时恢复通知条，使 todo 状态跨轮次、跨会话保持。
 */
export function restoreTodoFromMessages(messages) {
  if (!Array.isArray(messages)) return;
  let steps = null;
  const doneSteps = new Set();
  for (const msg of messages) {
    const tcs = (msg && msg.meta && msg.meta.tool_calls) || [];
    for (const call of tcs) {
      if (!call || call.name !== "todo_list") continue;
      const args = (call.args || {});
      if (Array.isArray(args.steps) && args.steps.length) {
        steps = args.steps.map((s) => String(s));
        doneSteps.clear();
      }
      if (!steps) continue;
      const n = parseInt(args.done_step, 10);
      if (Number.isFinite(n) && n >= 1) {
        for (let i = 0; i < Math.min(n, steps.length); i++) doneSteps.add(i);
      }
    }
  }
  if (!steps) return;
  stripState.todo.steps = steps;
  stripState.todo.doneSteps = [...doneSteps].sort((a, b) => a - b);
  stripState.todo.dismissed = false;
  saveStripSession(); // 持久化到会话快照（跨会话切换恢复）
  renderStrip();
}

// ===== Pending 数据更新 =====

/** 用 live snapshot 的 human_requests 更新 pending 通知条。 */
export function updatePendingStrip(humanRequests) {
  const items = Array.isArray(humanRequests) ? humanRequests : [];
  const prevIds = stripState.pending.items.map((p) => p.id).join(",");
  const nextIds = items.map((p) => p.id).join(",");
  const changed = prevIds !== nextIds || items.length !== stripState.pending.items.length;
  stripState.pending.items = items;
  if (stripState.pending.index >= items.length) {
    stripState.pending.index = Math.max(0, items.length - 1);
  }
  // 新请求出现 → 重置 dismissed
  if (changed && items.length) stripState.pending.dismissed = false;
  if (!items.length) {
    stripState.pending.expanded = false;
    stripState.pending.index = 0;
  }
  if (changed) renderStrip(); // 仅变化时渲染
}

// ===== DOM 构建 =====

function _stripRoot() {
  return $("notifyStrip");
}

function _itemsRoot() {
  return $("notifyStripItems");
}

/** 通知条是否有任何可见内容 */
function _hasContent() {
  const hasTodo = stripState.todo.steps.length > 0 && !stripState.todo.dismissed;
  const hasPending = stripState.pending.items.length > 0 && !stripState.pending.dismissed;
  return hasTodo || hasPending;
}

/** 主渲染入口（补丁式）：diff 条集合 → 复用/增删 → 就地更新内容。 */
export function renderStrip() {
  const root = _stripRoot();
  const items = _itemsRoot();
  if (!root || !items) return;

  // 期望的可见条集合（出现顺序自下而上：todo 在下，pending 在上）
  const desired = [];
  if (stripState.pending.items.length > 0 && !stripState.pending.dismissed) desired.push({ kind: "pending" });
  if (stripState.todo.steps.length > 0 && !stripState.todo.dismissed) desired.push({ kind: "todo" });

  if (!desired.length) {
    // 空态：完全消失（零占位，composer 紧贴聊天区）
    if (!root.hidden) {
      root.classList.remove("notify-strip--visible");
      root.hidden = true;
    }
    items.innerHTML = "";
    return;
  }

  const wasHidden = root.hidden;
  root.hidden = false;
  if (wasHidden) {
    // 下一帧加可见类，触发进入动画
    requestAnimationFrame(() => root.classList.add("notify-strip--visible"));
  } else {
    root.classList.add("notify-strip--visible");
  }

  // diff：按顺序同步子元素（最多 2 项）
  const oldKids = Array.from(items.children);
  const newKids = desired.map((d) => {
    const existing = oldKids.find((el) => el.dataset.stripKind === d.kind);
    if (existing) return existing; // 复用，避免重建
    return d.kind === "todo" ? _buildTodoItem() : _buildPendingItem();
  });
  oldKids.forEach((el) => { if (!newKids.includes(el)) el.remove(); });
  newKids.forEach((el, i) => {
    if (items.children[i] !== el) items.insertBefore(el, items.children[i] || null);
  });

  // 就地更新内容（只改变化的文本/chip/图标/展开区）
  newKids.forEach((el) => {
    if (el.dataset.stripKind === "todo") _updateTodoItemEl(el);
    else _updatePendingItemEl(el);
  });
}

/** Todo 通知条基础行（按钮 + 内容；展开区由 _updateTodoItemEl 维护） */
function _buildTodoItem() {
  const item = document.createElement("div");
  item.className = "strip-item strip-item--todo";
  item.dataset.stripKind = "todo";

  const row = document.createElement("div");
  row.className = "strip-item-row";

  // 左侧按钮：点击隐藏本条 → 输入区生成按钮
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "strip-item-btn";
  btn.title = "隐藏 Todo 条（收入输入区）";
  btn.innerHTML = '<img src="/image/todolist.svg" alt="Todo" />';
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    _dismissStripItem("todo");
  });
  row.appendChild(btn);

  // 内容区（点击展开/收起）
  const content = document.createElement("div");
  content.className = "strip-item-content";
  content.addEventListener("click", () => {
    stripState.todo.expanded = !stripState.todo.expanded;
    renderStrip();
  });

  const icon = document.createElement("span");
  icon.className = "strip-todo-icon";
  content.appendChild(icon);

  const text = document.createElement("span");
  text.className = "strip-item-text";
  content.appendChild(text);

  const chip = document.createElement("span");
  chip.className = "strip-item-count";
  content.appendChild(chip);

  row.appendChild(content);
  item.appendChild(row);
  return item;
}

/** Todo 展开区（头部含收起按钮 + 完整步骤列表） */
function _buildTodoExpandBody() {
  const { steps, doneSteps } = stripState.todo;
  const body = document.createElement("div");
  body.className = "strip-expand-area";

  const head = document.createElement("div");
  head.className = "strip-expand-head";
  const label = document.createElement("span");
  label.className = "strip-expand-label";
  label.textContent = `Todo List · ${doneSteps.length}/${steps.length}`;
  head.appendChild(label);
  head.appendChild(_buildCollapseBtn("todo"));
  body.appendChild(head);

  const list = document.createElement("ul");
  list.className = "strip-todo-list";
  steps.forEach((s, i) => {
    const li = document.createElement("li");
    li.className = "strip-todo-step" + (doneSteps.includes(i) ? " strip-todo-step--done" : "");
    const dot = document.createElement("span");
    dot.className = "strip-todo-icon" + (doneSteps.includes(i) ? " strip-todo-icon--done" : "");
    li.appendChild(dot);
    const labelEl = document.createElement("span");
    labelEl.className = "strip-todo-label";
    labelEl.textContent = s;
    li.appendChild(labelEl);
    list.appendChild(li);
  });
  body.appendChild(list);
  return body;
}

/** 就地更新 Todo 条：图标/文本/chip 只改文本节点；展开区按内容键重建。 */
function _updateTodoItemEl(item) {
  const { steps, doneSteps, expanded } = stripState.todo;
  const nextIdx = steps.findIndex((_, i) => !doneSteps.includes(i));
  const showIdx = nextIdx >= 0 ? nextIdx : steps.length - 1;
  const allDone = nextIdx < 0;

  item.classList.toggle("strip-item--expanded", expanded);
  // 行内文本节点就地更新（无重建）
  const icon = item.querySelector(".strip-todo-icon");
  if (icon) icon.classList.toggle("strip-todo-icon--done", allDone);
  const text = item.querySelector(".strip-item-text");
  if (text) text.textContent = steps[showIdx] || "";
  const chip = item.querySelector(".strip-item-count");
  if (chip) chip.textContent = `${doneSteps.length}/${steps.length}`;

  // 展开区维护：仅在内容键变化时重建，否则保留 DOM（避免打字/滚动丢状态）
  const existingBody = item.querySelector(".strip-expand-area");
  const key = JSON.stringify(steps) + "|" + doneSteps.join(",");
  if (expanded) {
    if (!existingBody || item._stepsKey !== key) {
      if (existingBody) existingBody.remove();
      item.appendChild(_buildTodoExpandBody());
      item._stepsKey = key;
    }
  } else if (existingBody) {
    existingBody.remove();
    item._stepsKey = null;
  }
}

/** Pending 通知条基础行（按钮 + 内容；展开区由 _updatePendingItemEl 维护） */
function _buildPendingItem() {
  const item = document.createElement("div");
  item.className = "strip-item strip-item--pending";
  item.dataset.stripKind = "pending";

  const row = document.createElement("div");
  row.className = "strip-item-row";

  // 左侧按钮：点击隐藏本条 → 输入区生成按钮
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "strip-item-btn";
  btn.title = "隐藏待确认条（收入输入区）";
  btn.innerHTML = '<img src="/image/人机交互.svg" alt="待确认" />';
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    _dismissStripItem("pending");
  });
  row.appendChild(btn);

  // 内容区（点击展开/收起）
  const content = document.createElement("div");
  content.className = "strip-item-content";
  content.addEventListener("click", () => {
    stripState.pending.expanded = !stripState.pending.expanded;
    renderStrip();
  });

  const icon = document.createElement("span");
  icon.className = "strip-pending-icon";
  content.appendChild(icon);

  const text = document.createElement("span");
  text.className = "strip-item-text";
  content.appendChild(text);

  const chip = document.createElement("span");
  chip.className = "strip-item-count";
  content.appendChild(chip);

  row.appendChild(content);
  item.appendChild(row);
  return item;
}

/** 就地更新 Pending 条：标题/chip 只改文本；展开区按卡片键重建。 */
function _updatePendingItemEl(item) {
  const { items, index, expanded } = stripState.pending;
  const current = items[index];

  item.classList.toggle("strip-item--expanded", expanded);
  const text = item.querySelector(".strip-item-text");
  if (text) text.textContent = current ? (current.title || "需要确认") : "需要确认";
  const chip = item.querySelector(".strip-item-count");
  if (chip) chip.textContent = items.length > 1 ? `×${items.length}` : "1";

  const existingBody = item.querySelector(".strip-expand-area");
  if (expanded && current) {
    const key = (current.id || "") + "|" + index;
    if (!existingBody || item._cardKey !== key) {
      if (existingBody) existingBody.remove();
      const body = document.createElement("div");
      body.className = "strip-expand-area";
      body.appendChild(_buildPendingCard(current, index));
      if (items.length > 1) body.appendChild(_buildPendingNav());
      item.appendChild(body);
      item._cardKey = key;
    }
  } else if (existingBody) {
    existingBody.remove();
    item._cardKey = null;
  }
}

/** 收起按钮（展开区右上角） */
function _buildCollapseBtn(kind) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "strip-collapse-btn";
  btn.textContent = "收起";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (kind === "todo") stripState.todo.expanded = false;
    else stripState.pending.expanded = false;
    renderStrip();
  });
  return btn;
}

/** 左右导航条（多 pending 项时） */
function _buildPendingNav() {
  const { items, index } = stripState.pending;
  const nav = document.createElement("div");
  nav.className = "strip-card-nav";

  const prev = document.createElement("button");
  prev.type = "button";
  prev.className = "strip-nav-arrow";
  prev.textContent = "‹";
  prev.disabled = index <= 0;
  prev.addEventListener("click", (e) => {
    e.stopPropagation();
    if (stripState.pending.index > 0) {
      stripState.pending.index--;
      renderStrip();
    }
  });

  const indicator = document.createElement("span");
  indicator.className = "strip-nav-indicator";
  indicator.textContent = `${index + 1}/${items.length}`;

  const next = document.createElement("button");
  next.type = "button";
  next.className = "strip-nav-arrow";
  next.textContent = "›";
  next.disabled = index >= items.length - 1;
  next.addEventListener("click", (e) => {
    e.stopPropagation();
    if (stripState.pending.index < stripState.pending.items.length - 1) {
      stripState.pending.index++;
      renderStrip();
    }
  });

  nav.appendChild(prev);
  nav.appendChild(indicator);
  nav.appendChild(next);
  return nav;
}

// ===== Pending 卡片构建 =====

function _buildPendingCard(pending, idx) {
  const isToolCall = pending.type === "tool_call";
  const isLast = idx >= stripState.pending.items.length - 1;

  const card = document.createElement("div");
  card.className = "strip-card";
  card.dataset.pendingId = pending.id || "";

  if (isToolCall) {
    _buildToolCallCard(card, pending);
  } else {
    _buildHumanCard(card, pending, isLast);
  }
  return card;
}

/** 审查卡片（tool_call）：参数摘要 + 同意/拒绝 */
function _buildToolCallCard(card, pending) {
  const head = document.createElement("div");
  head.className = "strip-card-head";
  const title = document.createElement("div");
  title.className = "strip-card-title";
  title.textContent = pending.title || `待确认执行工具：${pending.tool_name || ""}`;
  head.appendChild(title);
  head.appendChild(_buildCollapseBtn("pending"));
  card.appendChild(head);

  // 越界审批提示
  if (pending.policy_note) {
    const note = document.createElement("div");
    note.className = "strip-card-note";
    note.textContent = "⚠ 越界操作待审批：" + pending.policy_note;
    card.appendChild(note);
  }

  // 参数摘要（单行关键参数）
  const argsEl = document.createElement("div");
  argsEl.className = "strip-card-args";
  argsEl.textContent = _argsSummary(pending.args, !!pending.policy_note);
  card.appendChild(argsEl);

  const footer = document.createElement("div");
  footer.className = "strip-card-footer";

  const rejectBtn = document.createElement("button");
  rejectBtn.type = "button";
  rejectBtn.className = "strip-card-btn strip-card-btn--reject";
  rejectBtn.textContent = "拒绝";
  rejectBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    _submitPending(pending, "reject", "");
  });

  const approveBtn = document.createElement("button");
  approveBtn.type = "button";
  approveBtn.className = "strip-card-btn strip-card-btn--approve";
  approveBtn.textContent = "同意";
  approveBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    _submitPending(pending, "approve", "");
  });

  footer.appendChild(rejectBtn);
  footer.appendChild(approveBtn);
  card.appendChild(footer);
}

/** 人机交互卡片：标题 + 问题 + 选项 + 补充输入框（输入内容直接作为工具返回值） */
function _buildHumanCard(card, pending, isLast) {
  const head = document.createElement("div");
  head.className = "strip-card-head";
  const title = document.createElement("div");
  title.className = "strip-card-title";
  title.textContent = pending.title || "需要确认";
  head.appendChild(title);
  head.appendChild(_buildCollapseBtn("pending"));
  card.appendChild(head);

  if (pending.prompt) {
    const content = document.createElement("div");
    content.className = "strip-card-content";
    content.textContent = _unescapeNewlines(pending.prompt);
    card.appendChild(content);
  }

  // 选项胶囊（可空——无选项时仅问题 + 补充输入框）
  let selectedPill = null;
  const options = Array.isArray(pending.options) ? pending.options : [];
  if (options.length) {
    const pillsWrap = document.createElement("div");
    pillsWrap.className = "strip-card-options";
    options.forEach((opt) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "strip-option-pill";
      pill.textContent = String(opt);
      pill.addEventListener("click", (e) => {
        e.stopPropagation();
        // 仅切换类名，不触发重渲染（消除卡顿）
        pillsWrap.querySelectorAll(".strip-option-pill").forEach((p) => p.classList.remove("is-selected"));
        pill.classList.add("is-selected");
        selectedPill = String(opt);
      });
      pillsWrap.appendChild(pill);
    });
    card.appendChild(pillsWrap);
  }

  // 补充输入框：内容直接作为工具返回值
  const input = document.createElement("textarea");
  input.className = "strip-card-input";
  input.rows = 2;
  input.placeholder = options.length ? "补充信息（或直接输入选项）…" : "请输入…";
  card.appendChild(input);

  const footer = document.createElement("div");
  footer.className = "strip-card-footer";

  const submitBtn = document.createElement("button");
  submitBtn.type = "button";
  submitBtn.className = "strip-card-btn strip-card-btn--continue";
  submitBtn.textContent = isLast ? "确认" : "继续";
  submitBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    // 优先补充输入框内容（直达工具返回值），否则取选中选项
    const val = input.value.trim() || selectedPill || "";
    if (!val) {
      showToast("请先输入内容或选择选项");
      return;
    }
    _submitPending(pending, "edit", val, submitBtn);
  });

  footer.appendChild(submitBtn);
  card.appendChild(footer);
}

/** 提交决策并自动前进到下一张卡片 */
async function _submitPending(pending, decision, instruction, btnEl) {
  if (!pending || !pending.id) return;
  // 提交视觉反馈：按钮短暂禁用
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.classList.add("is-submitting");
  }
  try {
    await handleHumanAction(pending.id, decision, instruction, null, _activeSessionIdForPending());
  } catch (e) {
    showToast("提交失败: " + (e.message || e));
    if (btnEl) { btnEl.disabled = false; btnEl.classList.remove("is-submitting"); }
    return;
  }
  // 本地立即移除该项（后端快照随后也会同步）；前进到下一张
  const items = stripState.pending.items;
  const idx = items.findIndex((p) => p.id === pending.id);
  if (idx >= 0) items.splice(idx, 1);
  if (stripState.pending.index >= items.length) {
    stripState.pending.index = Math.max(0, items.length - 1);
  }
  if (!items.length) {
    stripState.pending.expanded = false;
    stripState.pending.index = 0;
  }
  renderStrip();
}

/** pending 提交用的 session_id：chat 模式为当前会话；cron 模式为任务 ID */
function _activeSessionIdForPending() {
  if (state.mode === "cron" && state.activeCronTaskId) return state.activeCronTaskId;
  return state.sessionId;
}

// ===== 按钮 toggle：strip ↔ composer =====

/** 隐藏某类通知条，并在输入区生成对应按钮 */
function _dismissStripItem(kind) {
  if (kind === "todo") stripState.todo.dismissed = true;
  else stripState.pending.dismissed = true;
  _addComposerBtn(kind);
  renderStrip();
}

/** 在输入区（画板按钮右侧）动态生成按钮；按加入顺序从左到右 */
function _addComposerBtn(kind) {
  if (_composerBtns.find((b) => b.kind === kind)) return; // 已存在
  const host = $("composerInputBottomLeft") || document.querySelector(".composer-input-bottom-left");
  if (!host) return;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "action-icon-btn strip-composer-btn";
  btn.title = kind === "todo" ? "Todo List" : "人机交互";
  btn.innerHTML = kind === "todo"
    ? '<img src="/image/todolist.svg" alt="Todo" />'
    : '<img src="/image/人机交互.svg" alt="交互" />';
  btn.addEventListener("click", () => {
    // 点击输入区按钮 → 按钮消失、对应通知条重新出现
    _removeComposerBtn(kind);
    if (kind === "todo") stripState.todo.dismissed = false;
    else stripState.pending.dismissed = false;
    renderStrip();
  });

  host.appendChild(btn);
  // 进入动画
  requestAnimationFrame(() => btn.classList.add("is-visible"));
  _composerBtns.push({ kind, btn });
}

function _removeComposerBtn(kind) {
  const idx = _composerBtns.findIndex((b) => b.kind === kind);
  if (idx < 0) return;
  const { btn } = _composerBtns[idx];
  btn.classList.remove("is-visible");
  btn.classList.add("is-leaving");
  setTimeout(() => btn.remove(), 160);
  _composerBtns.splice(idx, 1);
}

function _clearComposerBtns() {
  [..._composerBtns].forEach(({ kind }) => _removeComposerBtn(kind));
}

// ===== 工具函数 =====

function _unescapeNewlines(s) {
  return String(s ?? "").replace(/\\n/g, "\n");
}

/** 参数摘要：优先显示关键参数（file_path/command 等），越界审批只显示一条 */
function _argsSummary(args, oneLine) {
  if (!args || typeof args !== "object") return "";
  // 后端可能包一层 {name, args}
  let inner = args;
  if (args.args && typeof args.args === "object" && args.name) inner = args.args;
  const PRIORITY = ["file_path", "path", "command", "cmd", "url", "dir", "folder", "query", "name", "action"];
  for (const key of PRIORITY) {
    if (inner[key] !== undefined && inner[key] !== null && String(inner[key]).trim()) {
      const v = String(inner[key]);
      return `${key}: ${v.length > 120 ? v.slice(0, 120) + "…" : v}`;
    }
  }
  // 无关键参数：拼接前几个
  const entries = Object.entries(inner).filter(([, v]) => v !== undefined && v !== null);
  if (!entries.length) return "";
  const shown = oneLine ? entries.slice(0, 1) : entries.slice(0, 3);
  return shown.map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`).join("  ");
}

/** 仅清空 todo 通知条（不影响 pending——两类 UI 互相独立） */
export function clearTodoStrip() {
  stripState.todo = { steps: [], doneSteps: [], dismissed: false, expanded: false };
  renderStrip();
}

/** 仅清空 pending 通知条（不影响 todo） */
export function clearPendingStrip() {
  stripState.pending = { items: [], index: 0, dismissed: false, expanded: false };
  renderStrip();
}

/** 清除全部通知条状态（新会话/清空会话时） */
export function clearAllStrips() {
  stripState.todo = { steps: [], doneSteps: [], dismissed: false, expanded: false };
  stripState.pending = { items: [], index: 0, dismissed: false, expanded: false };
  _clearComposerBtns();
  renderStrip();
}
