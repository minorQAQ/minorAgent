// access-mode.js -- 工作空间访问模式选择器（限制访问 / 权限审查 / 完全访问）
// 模式持久化在后端 workspace_config.json（/api/workspace/access-mode），
// 由 agent/core/workspace_policy.py 消费，控制 doc_tool / terminal_execute 的越界处理。
// 触发器为彩色图标按钮（每种模式一个 SVG），面板内为三色文字选项。
// 交互通过 document 级事件委托实现，对元素绑定时序零依赖，并带连击保护。

import { $, showToast, closeInlinePanelsExcept } from './utils.js';
import { api } from './api.js';
import { state } from './state.js';

const MODE_LABELS = {
  restricted: "限制访问",
  approval: "权限审查",
  full: "完全访问",
};

const MODE_ICONS = {
  restricted: "/image/限制访问.svg",
  approval: "/image/权限审查.svg",
  full: "/image/完全访问.svg",
};

const MODE_TITLES = {
  restricted: "限制访问：越界操作直接拦截",
  approval: "权限审查：越界操作需人工审批",
  full: "完全访问：不做越界审查",
};

let _panelOpen = false;
let _switching = false;
let _lastSelectAt = 0;
let _lastTriggerAt = 0;

/** 初始化访问模式（bootstrap 后调用）：从后端加载并同步图标/下拉框 */
export async function initAccessMode() {
  try {
    const data = await api("/api/workspace");
    if (data.access_mode && MODE_LABELS[data.access_mode]) {
      state.accessMode = data.access_mode;
    }
  } catch { /* ignore */ }
  syncAccessModeUI();
}

/** 将图标、触发器标题与下拉选中态同步到 state.accessMode */
export function syncAccessModeUI() {
  const trigger = $("accessModeTrigger");
  const icon = $("accessModeIcon");
  const panel = $("accessModePanel");
  if (!trigger || !panel) return;
  const mode = MODE_LABELS[state.accessMode] ? state.accessMode : "restricted";
  panel.querySelectorAll(".inline-drop-item").forEach((el) => {
    el.classList.toggle("is-selected", el.dataset.value === mode);
  });
  if (icon) icon.src = MODE_ICONS[mode];
  trigger.title = MODE_TITLES[mode] || "工作空间访问模式";
  trigger.dataset.value = mode;
}

/** 绑定事件：document 级委托（触发器开关面板 + 选项点击），含连击保护 */
export function bindAccessModeEvents() {
  document.addEventListener("click", (e) => {
    const wrap = $("accessModeWrap");
    const panel = $("accessModePanel");
    if (!wrap || !panel) return;
    const target = e.target;

    // 触发器点击：开关面板（带连击保护）
    if (target.closest && target.closest("#accessModeTrigger")) {
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

    // 面板选项点击：切换模式（带连击保护）
    if (target.closest && target.closest("#accessModePanel .inline-drop-item")) {
      const item = target.closest("#accessModePanel .inline-drop-item");
      selectMode(item.dataset.value);
      return;
    }

    // 面板外点击 → 关闭
    if (!wrap.contains(target)) {
      closePanel();
    }
  });
}

function closePanel() {
  const panel = $("accessModePanel");
  if (panel) panel.hidden = true;
  _panelOpen = false;
}

/** 切换访问模式并持久化（连击/重复提交保护） */
async function selectMode(mode) {
  if (!MODE_LABELS[mode] || _switching) return;
  const now = Date.now();
  if (now - _lastSelectAt < 500) return;
  _lastSelectAt = now;
  _switching = true;
  try {
    const data = await api("/api/workspace/access-mode", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    if (data && data.mode) {
      state.accessMode = data.mode;
    }
  } catch (e) {
    closePanel();
    syncAccessModeUI();
    showToast(e.message || String(e));
    return;
  } finally {
    _switching = false;
  }
  closePanel();
  syncAccessModeUI();
  showToast(`工作空间访问模式已切换为「${MODE_LABELS[state.accessMode]}」`);
}
