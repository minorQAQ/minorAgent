// pending-overlay.js -- 待确认浮窗（HumanInteraction + ToolCall 确认）
// 直接接收后端 API 返回的 pending_actions 数组，按 agent_name 分组展示。
// 与 Todo 浮窗并排显示。

import { $, escapeHtml, showToast } from './utils.js';
import { state } from './state.js';
import { handleHumanAction } from './pending.js';

function _updateBadge(show) {
  try {
    import('./action-bar.js').then(m => m.setActionBadge('pending', show));
  } catch {}
}

/**
 * 将字符串中的 \\n 转为实际换行符（修复 LLM 输出双转义问题）
 */
function unescapeNewlines(s) {
  if (!s) return s;
  return String(s).replace(/\\n/g, '\n').replace(/\\t/g, '\t');
}

/**
 * 构建 pending 浮窗：按 agent_name 分组，每个 agent 一个分组区。
 * @param {Array} pendingActions - 后端返回的未解决 pending_action 列表
 * @returns {HTMLElement|null}
 */
function buildPendingOverlay(pendingActions) {
  clearPendingOverlay();
  if (!pendingActions || !pendingActions.length) return null;

  // 按 agent_name 分组（保留出现顺序）
  const groups = {};
  const groupOrder = [];
  pendingActions.forEach((p) => {
    const name = p.agent_name || "主Agent";
    if (!groups[name]) { groups[name] = []; groupOrder.push(name); }
    groups[name].push(p);
  });

  const overlay = document.createElement("div");
  overlay.className = "pending-overlay";

  const header = document.createElement("div");
  header.className = "pending-overlay-header";
  header.textContent = "\u270D\uFE0F 需要确认";
  header.addEventListener("click", () => {
    overlay.classList.toggle("pending-overlay--collapsed");
  });
  overlay.appendChild(header);

  const body = document.createElement("div");
  body.className = "pending-overlay-body";

  let hasSelectionBatch = false;

  groupOrder.forEach((name) => {
    const items = groups[name];
    const isSub = items.some((p) => p.is_sub_agent);

    const group = document.createElement("div");
    group.className = "pending-overlay-agent-group";

    const groupHeader = document.createElement("div");
    groupHeader.className = "pending-overlay-agent-header";
    groupHeader.textContent = name;
    group.appendChild(groupHeader);

    items.forEach((pending) => {
      if (pending.type === "human_interaction" && (pending.interaction_type || "information") === "selection") {
        hasSelectionBatch = true;
      }
      group.appendChild(buildPendingCard(pending, isSub));
    });

    body.appendChild(group);
  });

  overlay.appendChild(body);

  // 全局提交按钮（仅当存在 selection 类型时显示，用于批量确认）
  if (hasSelectionBatch) {
    const submitRow = document.createElement("div");
    submitRow.className = "pending-overlay-submit-row";
    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "pending-overlay-submit-btn";
    submitBtn.textContent = "确认全部选择";
    submitBtn.addEventListener("click", () => submitAllPending(overlay, pendingActions));
    submitRow.appendChild(submitBtn);
    overlay.appendChild(submitRow);
  }

  state._currentPendingOverlay = overlay;
  return overlay;
}

/**
 * 创建决策按钮
 * @param {string} label
 * @param {string} decision - approve | reject | skip | edit
 * @param {string} cls - 按钮附加类名
 * @param {Function} onClick
 */
function makeDecisionBtn(label, decision, cls, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `pending-overlay-btn pending-overlay-btn--${decision} ${cls || ""}`.trim();
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

/**
 * 为单个 pending_action 构建卡片
 * @param {Object} pending - pending_action 数据
 * @param {boolean} isSubAgent - 是否属于子 Agent
 */
function buildPendingCard(pending, isSubAgent) {
  const card = document.createElement("div");
  card.className = "pending-overlay-card";
  card.setAttribute("data-pending-id", pending.id);

  const pendingType = pending.type || "human_interaction";
  const interactionType = pending.interaction_type || "information";

  // 标题栏（不折叠，纯展示）
  const cardHeader = document.createElement("div");
  cardHeader.className = "pending-overlay-card-header";
  const icon = pendingType === "tool_call" ? "\u{1F527}" : "\u{1F4DD}";
  const titleText = pending.title || (pendingType === "tool_call" ? `待确认执行工具：${pending.tool_name || ""}` : "需要确认");
  cardHeader.innerHTML = `<span class="pending-overlay-card-icon">${icon}</span><span class="pending-overlay-card-title">${escapeHtml(titleText)}</span>`;
  card.appendChild(cardHeader);

  // 内容区
  const cardBody = document.createElement("div");
  cardBody.className = "pending-overlay-card-body";

  if (pending.prompt) {
    const promptEl = document.createElement("div");
    promptEl.className = "pending-overlay-prompt";
    promptEl.textContent = unescapeNewlines(pending.prompt);
    cardBody.appendChild(promptEl);
  }

  // ===== tool_call 类型：展示参数（只读）+ 决策按钮 =====
  if (pendingType === "tool_call") {
    // 工作空间越界审批提示（访问策略注入的 policy_note）
    if (pending.policy_note) {
      const noteEl = document.createElement("div");
      noteEl.className = "pending-overlay-note";
      noteEl.textContent = "⚠️ 越界操作待审批：" + unescapeNewlines(pending.policy_note);
      cardBody.appendChild(noteEl);
    }
    // 参数 JSON（只读）
    if (pending.args !== undefined && pending.args !== null) {
      let argsStr;
      try {
        argsStr = typeof pending.args === "string" ? pending.args : JSON.stringify(pending.args, null, 2);
      } catch (_) {
        argsStr = String(pending.args);
      }
      const argsEl = document.createElement("div");
      argsEl.className = "pending-overlay-tool-args";
      argsEl.textContent = argsStr;
      cardBody.appendChild(argsEl);
    }
    // 指令输入（可选，用于 approve 时附带说明）
    const textarea = document.createElement("textarea");
    textarea.className = "pending-overlay-textarea";
    textarea.placeholder = "可选：补充指令...";
    textarea.value = pending.instruction || "";
    textarea.rows = 2;
    textarea.setAttribute("data-field", "instruction");
    cardBody.appendChild(textarea);

    // 按钮行：主Agent = 同意/拒绝/跳过；子Agent = 确认/跳过
    const btnRow = document.createElement("div");
    btnRow.className = "pending-overlay-btn-row";
    const onDecide = (decision) => () => {
      const val = textarea.value.trim();
      submitSingle(pending.id, decision, val, card);
    };
    btnRow.appendChild(makeDecisionBtn(isSubAgent ? "确认" : "同意", "approve", "", onDecide("approve")));
    if (!isSubAgent) {
      btnRow.appendChild(makeDecisionBtn("拒绝", "reject", "", onDecide("reject")));
    }
    btnRow.appendChild(makeDecisionBtn("跳过", "skip", "", onDecide("skip")));
    cardBody.appendChild(btnRow);

    card.appendChild(cardBody);
    return card;
  }

  // ===== human_interaction 类型 =====
  if (interactionType === "information") {
    // 文本输入
    const inputRow = document.createElement("div");
    inputRow.className = "pending-overlay-input-row";

    const textarea = document.createElement("textarea");
    textarea.className = "pending-overlay-textarea";
    textarea.placeholder = "在这里补充信息...";
    textarea.value = pending.instruction || "";
    textarea.rows = 3;
    textarea.setAttribute("data-field", "instruction");
    inputRow.appendChild(textarea);

    const sendBtn = document.createElement("button");
    sendBtn.type = "button";
    sendBtn.className = "pending-overlay-send-btn";
    sendBtn.textContent = "确认";
    sendBtn.addEventListener("click", () => {
      const val = textarea.value.trim();
      if (!val) return;
      submitSingle(pending.id, "approve", val, card);
    });
    inputRow.appendChild(sendBtn);

    cardBody.appendChild(inputRow);
  } else if (interactionType === "selection") {
    if (pending.questions && Array.isArray(pending.questions) && pending.questions.length > 0) {
      pending.questions.forEach((q) => {
        const qBlock = document.createElement("div");
        qBlock.className = "pending-overlay-question";

        const qHeader = document.createElement("div");
        qHeader.className = "pending-overlay-question-header";
        qHeader.innerHTML = `<span class="pending-overlay-q-icon">\u2753</span><span>${escapeHtml(q.question || "")}</span>`;
        qHeader.addEventListener("click", () => {
          qBlock.classList.toggle("pending-overlay-question--collapsed");
        });
        qBlock.appendChild(qHeader);

        const qBody = document.createElement("div");
        qBody.className = "pending-overlay-question-body";

        if (q.options && Array.isArray(q.options)) {
          const pillsRow = document.createElement("div");
          pillsRow.className = "pending-overlay-option-pills";

          q.options.forEach((opt) => {
            const pill = document.createElement("button");
            pill.type = "button";
            pill.className = "pending-overlay-option-pill";
            pill.textContent = String(opt);
            pill.addEventListener("click", () => {
              const prevSelected = pillsRow.querySelector(".pending-overlay-option-pill--selected");
              if (prevSelected === pill) {
                pill.classList.remove("pending-overlay-option-pill--selected");
                return;
              }
              if (prevSelected) prevSelected.classList.remove("pending-overlay-option-pill--selected");
              pill.classList.add("pending-overlay-option-pill--selected");
            });
            pillsRow.appendChild(pill);
          });
          qBody.appendChild(pillsRow);
        }

        // "其他" 输入
        const otherRow = document.createElement("div");
        otherRow.className = "pending-overlay-other-row";
        const otherInput = document.createElement("input");
        otherInput.type = "text";
        otherInput.className = "pending-overlay-other-input";
        otherInput.placeholder = "其他自定义...";
        otherRow.appendChild(otherInput);
        qBody.appendChild(otherRow);

        qBlock.appendChild(qBody);
        cardBody.appendChild(qBlock);
      });
    } else {
      // 简单选项列表
      const pillsRow = document.createElement("div");
      pillsRow.className = "pending-overlay-option-pills";
      (pending.options || []).forEach((opt) => {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "pending-overlay-option-pill";
        pill.textContent = String(opt);
        pill.addEventListener("click", () => {
          const prev = pillsRow.querySelector(".pending-overlay-option-pill--selected");
          if (prev === pill) { pill.classList.remove("pending-overlay-option-pill--selected"); return; }
          if (prev) prev.classList.remove("pending-overlay-option-pill--selected");
          pill.classList.add("pending-overlay-option-pill--selected");
        });
        pillsRow.appendChild(pill);
      });
      cardBody.appendChild(pillsRow);
    }
  }

  // 人机交互卡片统一提供"拒绝"按钮：与手动暂停一致，拒绝后暂停本轮运行
  if (pendingType === "human_interaction") {
    const rejectRow = document.createElement("div");
    rejectRow.className = "pending-overlay-btn-row";
    rejectRow.appendChild(makeDecisionBtn("拒绝", "reject", "", () => {
      submitSingle(pending.id, "reject", "", card);
    }));
    cardBody.appendChild(rejectRow);
  }

  card.appendChild(cardBody);
  return card;
}

/**
 * 收集所有 selection 类型 pending 的答案并提交
 */
function submitAllPending(overlay, pendingActions) {
  const results = {};

  pendingActions.forEach((pending) => {
    if (pending.type === "tool_call") return;
    const card = overlay.querySelector(`[data-pending-id="${pending.id}"]`);
    if (!card) return;

    const interactionType = pending.interaction_type || "information";
    if (interactionType === "information") {
      const textarea = card.querySelector(".pending-overlay-textarea");
      results[pending.id] = textarea ? textarea.value.trim() : "";
    } else if (interactionType === "selection") {
      if (pending.questions && Array.isArray(pending.questions)) {
        const qResponses = {};
        const questionBlocks = card.querySelectorAll(".pending-overlay-question");
        pending.questions.forEach((q, qIdx) => {
          const qBlock = questionBlocks[qIdx];
          if (!qBlock) return;
          const otherInput = qBlock.querySelector(".pending-overlay-other-input");
          let answer = otherInput ? otherInput.value.trim() : "";
          if (!answer) {
            const selectedPill = qBlock.querySelector(".pending-overlay-option-pill--selected");
            if (selectedPill) answer = selectedPill.textContent || "";
          }
          qResponses[q.question || ""] = answer;
        });
        results[pending.id] = JSON.stringify(qResponses);
      } else {
        const selectedPill = card.querySelector(".pending-overlay-option-pill--selected");
        results[pending.id] = selectedPill ? selectedPill.textContent || "" : "";
      }
    }
  });

  const submitNext = (idx) => {
    if (idx >= pendingActions.length) return;
    const pending = pendingActions[idx];
    if (pending.type === "tool_call") { submitNext(idx + 1); return; }
    const card = overlay.querySelector(`[data-pending-id="${pending.id}"]`);
    const answer = results[pending.id] || "";
    const instruction = typeof answer === "string" ? answer : JSON.stringify(answer);
    handleHumanAction(pending.id, "edit", instruction, card).then(() => {
      if (card) card.classList.add("pending-overlay-card--resolved");
      setTimeout(() => submitNext(idx + 1), 100);
    }).catch((e) => {
      showToast(e.message || String(e));
    });
  };

  submitNext(0);
}

/**
 * 单独提交一个 pending_action
 */
function submitSingle(approvalId, decision, instruction, card) {
  handleHumanAction(approvalId, decision, instruction, card).then(() => {
    if (card) card.classList.add("pending-overlay-card--resolved");
  }).catch((e) => {
    showToast(e.message || String(e));
  });
}

/**
 * 更新浮窗：直接接收 pending_actions 数组
 * @param {Array|null} pendingActions - API 响应的 pending_actions 数组
 */
function updatePendingOverlay(pendingActions) {
  _updateBadge(!!(pendingActions && pendingActions.length));
  if (!pendingActions || !pendingActions.length) {
    clearPendingOverlay();
    return;
  }
  const overlay = buildPendingOverlay(pendingActions);
  if (!overlay) return;

  const container = getOverlayContainer();
  if (!container) return;
  const existing = container.querySelector(".pending-overlay");
  if (existing && existing !== overlay) existing.remove();
  if (!overlay.parentNode) container.appendChild(overlay);
  updateOverlayLayout();
}

/**
 * 清除 pending 浮窗
 */
function clearPendingOverlay() {
  _updateBadge(false);
  state._pendingHumanAction = false;
  if (state._currentPendingOverlay) {
    state._currentPendingOverlay.hidden = true;
  }
  document.querySelectorAll(".pending-overlay").forEach((el) => el.hidden = true);
  updateOverlayLayout();
}

function togglePendingOverlay() {
  if (state._currentPendingOverlay) {
    state._currentPendingOverlay.hidden = !state._currentPendingOverlay.hidden;
  } else {
    const el = document.querySelector(".pending-overlay");
    if (el) {
      el.hidden = !el.hidden;
      state._currentPendingOverlay = el;
    }
  }
}

/**
 * 获取 overlay 挂载容器（与 todo overlay 相同层级）
 */
function getOverlayContainer() {
  const chatMessages = $("chatMessages");
  const container = chatMessages ? (chatMessages.closest(".chat-area") || chatMessages.parentElement) : null;
  if (!container) {
    return document.body;
  }
  return container;
}

/**
 * 更新 overlay 布局（与 todo 浮窗并排）
 */
function updateOverlayLayout() {
  const todoOverlay = document.querySelector(".todo-list-overlay");
  const pendingOverlay = document.querySelector(".pending-overlay");
  const todoVisible = todoOverlay && !todoOverlay.hidden;
  const pendingVisible = pendingOverlay && !pendingOverlay.hidden;

  if (todoVisible && pendingVisible) {
    todoOverlay.classList.add("todo-list-overlay--dual");
    pendingOverlay.classList.add("pending-overlay--dual");
  } else {
    if (todoOverlay) todoOverlay.classList.remove("todo-list-overlay--dual");
    if (pendingOverlay) pendingOverlay.classList.remove("pending-overlay--dual");
  }
}

export {
  buildPendingOverlay,
  updatePendingOverlay,
  clearPendingOverlay,
  togglePendingOverlay,
  updateOverlayLayout,
};
