// think-level.js -- 思考模式档位选择（low / high / xhigh / max / ultra）
// 档位同时决定运行模式与深度思考：
//   low=agent+不思考  high=plan+不思考  xhigh=agent+思考  max=plan+思考
//   ultra 为未来 react→审批图预留占位（暂按 agent+思考 处理）
// 会话级变量：持久化在各会话 session_meta.json 的 thinking_level
// （POST /api/sessions/{id}/thinking-level），由 llm.Multimodel_LLM 每轮
// 按当前会话动态解析 extra_body，仅作用于该会话。
// 交互通过 document 级事件委托实现（触发器开关 + 档位点击 + 滑条拖动）。

import { $, showToast, closeInlinePanelsExcept } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';

export const THINK_LEVELS = ["low", "high", "xhigh", "max", "ultra"];

const THINK_LEVEL_TIPS = {
  low: "low：agent 模式，不开启深度思考",
  high: "high：plan 模式，不开启深度思考",
  xhigh: "xhigh：agent 模式 + 深度思考",
  max: "max：plan 模式 + 深度思考",
  ultra: "ultra：预留占位（未来 react→审批图）",
};

/** 根据思考档位派生运行模式（low/xhigh/ultra→agent，high/max→plan） */
export function getAgentModeFromLevel(level) {
  const lv = THINK_LEVELS.includes(level) ? level : "low";
  return lv === "high" || lv === "max" ? "plan" : "agent";
}

/** 档位是否启用深度思考 */
export function getThinkingEnabled(level) {
  const lv = THINK_LEVELS.includes(level) ? level : "low";
  return lv === "xhigh" || lv === "max" || lv === "ultra";
}

let _panelOpen = false;
let _dragging = false;
let _committing = false;
let _lastCommitAt = 0;
let _lastTriggerAt = 0;

/** 初始化思考档位（bootstrap 后调用）：state.thinkingLevel 已由会话数据同步 */
export function initThinkLevel() {
  if (!THINK_LEVELS.includes(state.thinkingLevel)) {
    state.thinkingLevel = "low";
  }
  renderLabels();
  syncThinkLevelUI();
}

/** 渲染 5 档标签（横向布局：flex space-between，与滑条档位对齐） */
function renderLabels() {
  const container = $("thinkModeLabels");
  if (!container) return;
  container.innerHTML = "";
  THINK_LEVELS.forEach((lv) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "think-mode-label";
    item.dataset.value = lv;
    item.textContent = lv;
    item.title = THINK_LEVEL_TIPS[lv] || lv;
    container.appendChild(item);
  });
}

/** 将滑条手柄/填充/标签选中态同步到 state.thinkingLevel（横向：左=low 右=ultra） */
export function syncThinkLevelUI() {
  const handle = $("thinkModeHandle");
  const fill = $("thinkModeFill");
  const labels = document.querySelectorAll(".think-mode-label");
  const trigger = $("thinkModeTrigger");
  if (!handle || !fill) return;
  const idx = Math.max(0, THINK_LEVELS.indexOf(state.thinkingLevel));
  const pct = (idx / (THINK_LEVELS.length - 1)) * 100;
  handle.style.left = `${pct}%`;
  fill.style.width = `${pct}%`;
  labels.forEach((el) => {
    el.classList.toggle("is-active", el.dataset.value === state.thinkingLevel);
  });
  if (trigger) {
    trigger.title = THINK_LEVEL_TIPS[state.thinkingLevel] || "思考模式";
    trigger.dataset.value = state.thinkingLevel;
    // 按钮右侧小字：当前思考等级
    const badge = trigger.querySelector(".think-mode-badge");
    if (badge) badge.textContent = state.thinkingLevel;
  }
}

/** 绑定事件：document 级委托（触发器开关 + 档位点击 + 滑条拖动） */
export function bindThinkModeEvents() {
  document.addEventListener("click", (e) => {
    const wrap = $("thinkModeWrap");
    const panel = $("thinkModePanel");
    if (!wrap || !panel) return;
    const target = e.target;

    // 触发器点击：开关面板（带连击保护）
    if (target.closest && target.closest("#thinkModeTrigger")) {
      const now = Date.now();
      if (now - _lastTriggerAt < 300) return;
      _lastTriggerAt = now;
      if (_panelOpen) {
        closePanel();
        return;
      }
      closeInlinePanelsExcept(panel);
      panel.hidden = false;
      _panelOpen = true;
      return;
    }

    // 档位标签点击：立即选择并提交
    if (target.closest && target.closest(".think-mode-label")) {
      const lv = target.closest(".think-mode-label").dataset.value;
      if (!THINK_LEVELS.includes(lv)) return;
      state.thinkingLevel = lv;
      syncThinkLevelUI();
      commitLevel(lv);
      return;
    }

    // 面板外点击 → 关闭
    if (!wrap.contains(target)) {
      closePanel();
    }
  });

  // 滑条：Pointer Events 拖动（含触摸），松手提交（横向坐标 clientX）
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest || !e.target.closest("#thinkModeTrack")) return;
    const track = $("thinkModeTrack");
    if (!track) return;
    e.preventDefault();
    _dragging = true;
    track.setPointerCapture(e.pointerId);
    setLevelFromPointer(e.clientX);
  });
  document.addEventListener("pointermove", (e) => {
    if (!_dragging) return;
    setLevelFromPointer(e.clientX);
  });
  const endDrag = (e) => {
    if (!_dragging) return;
    _dragging = false;
    const track = $("thinkModeTrack");
    if (track) {
      try { track.releasePointerCapture(e.pointerId); } catch { /* ignore */ }
    }
    commitLevel(state.thinkingLevel);
  };
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
}

function closePanel() {
  const panel = $("thinkModePanel");
  if (panel) panel.hidden = true;
  _panelOpen = false;
}

function setLevelFromPointer(clientX) {
  const track = $("thinkModeTrack");
  if (!track) return;
  const rect = track.getBoundingClientRect();
  // 横向滑条：左端=low(0%)，右端=ultra(100%)
  const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  const idx = Math.round(pct * (THINK_LEVELS.length - 1));
  state.thinkingLevel = THINK_LEVELS[idx];
  syncThinkLevelUI();
}

/** 提交档位到当前会话（会话级变量，存于该会话 session_meta.json） */
async function commitLevel(level) {
  if (_committing) return;
  const now = Date.now();
  if (now - _lastCommitAt < 500) return;
  _lastCommitAt = now;
  _committing = true;
  try {
    const sid = state.sessionId || "";
    if (!sid) { showToast("当前无会话，无法保存思考档位"); return; }
    const data = await api(`/api/sessions/${encodeURIComponent(sid)}/thinking-level`, {
      method: "POST",
      body: JSON.stringify({ level }),
    });
    if (data && data.level) {
      state.thinkingLevel = data.level;
      syncThinkLevelUI();
      showToast(`思考模式已切换为「${data.level}」（仅当前会话）`);
    }
  } catch (e) {
    showToast(e.message || String(e));
  } finally {
    _committing = false;
  }
}
