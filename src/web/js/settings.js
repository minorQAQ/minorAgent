// settings.js -- 设置面板：Agent / Tool / Env / GUI / Models / Theme

import { $, escapeHtml, makeId, showToast, withClickGuard } from './utils.js';
import { showConfirm } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';
import { THEMES, getCurrentTheme, applyTheme, getBgImage, setBgImage, getBgBlur, setBgBlur, getBgVignette, setBgVignette, FONT_PRESETS, FONT_SIZE_PRESETS, getFontSetting, setFontSetting } from './themes.js';
import { LANGS, setLanguage } from './i18n.js';

let renderSkillsFn = null;
export function setRenderSkills(fn) { renderSkillsFn = fn; }

const settingsOverlay = $("settingsOverlay");
const settingsCloseBtn = $("settingsCloseBtn");
const settingsCancelBtn = $("settingsCancelBtn");
const settingsStatus = $("settingsStatus");
const agentsListEl = $("agentsList");
const toolsListEl = $("toolsList");
const envListEl = $("envList");
const guiMonitorsGrid = $("guiMonitorsGrid");
const addAgentBtn = $("addAgentBtn");

export function setStatus(msg, type) {
  if (!settingsStatus) return;
  settingsStatus.textContent = msg;
  settingsStatus.className = "settings-status" + (type ? " " + type : "");
  if (type === "success" || type === "error") {
    setTimeout(() => { if (settingsStatus.textContent === msg) setStatus(""); }, 3000);
  }
}

function openSettings() {
  if (!settingsOverlay) return;
  settingsOverlay.hidden = false;
  loadAllConfigs().catch((e) => setStatus("加载配置失败: " + e.message, "error"));
}

function closeSettings() {
  if (!settingsOverlay) return;
  settingsOverlay.hidden = true;
  setStatus("");
  // 重新加载模型下拉列表（用户可能在设置中新增了模型）
  import('../app.js').then((m) => { if (m.refreshModelSelect) m.refreshModelSelect(); }).catch(() => {});
}

// Tab 切换
document.querySelectorAll(".settings-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const target = tab.getAttribute("data-tab");
    document.querySelectorAll(".settings-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".settings-panel").forEach((p) => p.hidden = p.getAttribute("data-panel") !== target);
    if (target === "agent") renderAgentConfigs();
    else if (target === "tool") renderToolConfigs();
    else if (target === "env") renderEnvConfig();
    else if (target === "skills" && renderSkillsFn) renderSkillsFn();
    else if (target === "other") renderGuiConfig();
    else if (target === "theme") renderThemePanel();
  });
});

async function loadAllConfigs() {
  const [agentRes, toolRes, envRes, guiRes] = await Promise.all([
    api("/api/config/agents"),
    api("/api/config/tools"),
    api("/api/config/env"),
    api("/api/config/gui"),
  ]);
  state.cachedAgentConfigs.length = 0;
  state.cachedAgentConfigs.push(...(agentRes.agents || []));
  state.cachedToolConfigs.length = 0;
  state.cachedToolConfigs.push(...(toolRes.tools || []));
  // Mutate cachedEnvConfig in place instead of reassigning
  for (const key of Object.keys(state.cachedEnvConfig)) delete state.cachedEnvConfig[key];
  Object.assign(state.cachedEnvConfig, envRes.env || {});
  // 记录当前已生效的存储后端基线，供保存时检测切换
  state._lastAppliedBackend = state.cachedEnvConfig.STORAGE_BACKEND || "json";
  state.cachedModels.length = 0;
  state.cachedModels.push(...(envRes.models || []));
  Object.assign(state.cachedGuiConfig, {
    monitors: guiRes.monitors || [],
    selected_name: guiRes.selected_name || "",
    gui_model_id: guiRes.gui_model_id || "",
    models: guiRes.models || [],
  });
  state.registeredToolNames.length = 0;
  state.registeredToolNames.push(...(toolRes.registered_tool_names || []));
  window._toolParameters = toolRes.tool_parameters || {};
  window._forcedPermissions = toolRes.forced_permissions || {};
  renderAgentConfigs();
  renderToolConfigs();
  renderEnvConfig();
  if (renderSkillsFn) renderSkillsFn();
  renderGuiConfig();
}

// ===== Agent 配置渲染 =====
function renderAgentConfigs() {
  if (!agentsListEl) return;
  agentsListEl.innerHTML = "";
  state.cachedAgentConfigs.forEach((agent, idx) => {
    agentsListEl.appendChild(buildAgentCard(agent, idx));
  });
}

function getModelLabel(modelId) {
  if (!modelId) return "\u2014 \u672A\u9009\u62E9 \u2014";
  const m = state.cachedModels.find((mod) => mod.id === modelId);
  return m ? `${m.name} (${m.model})` : modelId;
}

function makeField(label, type, value, onChange) {
  const div = document.createElement("div");
  div.className = "setting-field";
  const lbl = document.createElement("label");
  lbl.textContent = label;
  let input;
  if (type === "textarea") {
    input = document.createElement("textarea");
    input.rows = 3;
  } else {
    input = document.createElement("input");
    input.type = type;
  }
  input.value = value ?? "";
  input.addEventListener("input", () => onChange(input.value));
  if (type === "number") input.step = "any";
  div.appendChild(lbl);
  div.appendChild(input);
  return div;
}

function buildAgentCard(agent, idx) {
  const card = document.createElement("div");
  card.className = "agent-config-card";
  card.dataset.index = idx;

  const header = document.createElement("div");
  header.className = "agent-card-header";
  const h4 = document.createElement("h4");
  h4.textContent = `Agent: ${agent.name || "(\u672A\u547D\u540D)"}`;
  header.appendChild(h4);
  // 主 Agent 不可删除
  if (agent.role !== "main") {
    const removeBtn = document.createElement("button");
    removeBtn.className = "agent-card-remove";
    removeBtn.textContent = "\u2715";
    removeBtn.title = "\u5220\u9664\u6B64 Agent";
    removeBtn.addEventListener("click", () => {
      state.cachedAgentConfigs.splice(idx, 1);
      renderAgentConfigs();
    });
    header.appendChild(removeBtn);
  }

  const nameField = makeField("\u540D\u79F0", "text", agent.name || "", (v) => { agent.name = v; });
  const descField = makeField("\u80FD\u529B\u63CF\u8FF0 (description)", "text", agent.description || "", (v) => { agent.description = v; });
  const maxIterField = makeField("\u6700\u5927\u8FED\u4EE3\u6B21\u6570", "number", agent.max_iterations || 200, (v) => { agent.max_iterations = parseInt(v) || 200; });
  const spField = makeField("\u7CFB\u7EDF\u63D0\u793A\u8BCD (system_prompt)", "textarea", agent.system_prompt || "", (v) => { agent.system_prompt = v; });

  // LLM 模型选择
  const llmField = document.createElement("div");
  llmField.className = "setting-field";
  const llmLabel = document.createElement("label");
  llmLabel.textContent = "LLM \u6A21\u578B";
  const llmRow = document.createElement("div");
  llmRow.style.cssText = "display:flex;gap:0.4rem;align-items:center;";
  const llmSelect = document.createElement("select");
  llmSelect.style.cssText = "flex:1;";
  const emptyOpt = document.createElement("option");
  emptyOpt.value = "";
  emptyOpt.textContent = "\u2014 \u672A\u9009\u62E9 \u2014";
  llmSelect.appendChild(emptyOpt);
  state.cachedModels.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.name} (${m.model})`;
    if (m.id === agent.llm_model_id) opt.selected = true;
    llmSelect.appendChild(opt);
  });
  if (!state.cachedModels.some((m) => m.id === agent.llm_model_id) && agent.llm_model_id) {
    const opt = document.createElement("option");
    opt.value = agent.llm_model_id;
    opt.textContent = agent.llm_model_id + " (\u5DF2\u5220\u9664)";
    opt.selected = true;
    llmSelect.appendChild(opt);
  }
  llmSelect.addEventListener("change", () => { agent.llm_model_id = llmSelect.value; });
  llmRow.appendChild(llmSelect);
  llmField.appendChild(llmLabel);
  llmField.appendChild(llmRow);

  // 工具选择
  const toolsField = document.createElement("div");
  toolsField.className = "setting-field";
  const toolsLabel = document.createElement("label");
  toolsLabel.textContent = "\u5DE5\u5177\u5217\u8868";
  toolsField.appendChild(toolsLabel);

  const selectedToolsList = document.createElement("div");
  selectedToolsList.style.cssText = "display:flex;flex-wrap:wrap;gap:0.25rem;margin-bottom:0.35rem;min-height:1.5rem;";

  function renderSelectedTools() {
    selectedToolsList.innerHTML = "";
    (agent.tools || []).forEach((tname) => {
      const chip = document.createElement("span");
      chip.style.cssText = "display:inline-flex;align-items:center;gap:0.2rem;padding:0.15rem 0.4rem;background:rgba(79,70,229,0.12);border-radius:6px;font-size:0.78rem;";
      chip.textContent = tname;
      const delBtn = document.createElement("span");
      delBtn.textContent = "\u00D7";
      delBtn.style.cssText = "cursor:pointer;color:#991b1b;font-weight:700;margin-left:0.15rem;";
      delBtn.title = "\u79FB\u9664\u6B64\u5DE5\u5177";
      delBtn.addEventListener("click", () => {
        agent.tools = (agent.tools || []).filter((t) => t !== tname);
        renderSelectedTools();
      });
      chip.appendChild(delBtn);
      selectedToolsList.appendChild(chip);
    });
  }
  renderSelectedTools();
  toolsField.appendChild(selectedToolsList);

  const addToolRow = document.createElement("div");
  addToolRow.style.cssText = "display:flex;gap:0.4rem;align-items:center;";
  const toolSelect = document.createElement("select");
  toolSelect.style.cssText = "flex:1;";
  const emptyToolOpt = document.createElement("option");
  emptyToolOpt.value = "";
  emptyToolOpt.textContent = "\u9009\u62E9\u5DE5\u5177...";
  toolSelect.appendChild(emptyToolOpt);
  state.registeredToolNames.forEach((tname) => {
    if (!(agent.tools || []).includes(tname)) {
      const opt = document.createElement("option");
      opt.value = tname;
      opt.textContent = tname;
      toolSelect.appendChild(opt);
    }
  });
  const addToolBtn = document.createElement("button");
  addToolBtn.type = "button";
  addToolBtn.className = "btn btn-ghost";
  addToolBtn.style.cssText = "padding:0.2rem 0.6rem;font-size:0.78rem;white-space:nowrap;";
  addToolBtn.textContent = "+ \u6DFB\u52A0";
  addToolBtn.addEventListener("click", () => {
    const val = toolSelect.value;
    if (!val) return;
    if (!agent.tools) agent.tools = [];
    if (!agent.tools.includes(val)) {
      agent.tools.push(val);
      renderSelectedTools();
      Array.from(toolSelect.options).forEach((o) => { if (o.value === val) o.remove(); });
      toolSelect.value = "";
    }
  });
  addToolRow.appendChild(toolSelect);
  addToolRow.appendChild(addToolBtn);
  toolsField.appendChild(addToolRow);

  const trajField = makeField("\u77ED\u671F\u8BB0\u5FC6\u8F6E\u6570 (trajectory_rounds)", "number", agent.trajectory_rounds ?? 3, (v) => { agent.trajectory_rounds = parseInt(v) || 3; });

  card.appendChild(header);
  card.appendChild(nameField);
  if (idx !== 0) card.appendChild(descField);
  card.appendChild(maxIterField);
  card.appendChild(spField);
  card.appendChild(llmField);
  card.appendChild(trajField);

  // 启用开关（主 Agent 不可关闭）
  if (idx !== 0) {
    const enabledWrap = document.createElement("div");
    enabledWrap.className = "toggle-row";
    const toggleLabel = document.createElement("label");
    toggleLabel.className = "toggle-switch";
    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = agent.enabled !== false;
    toggleInput.addEventListener("change", () => { agent.enabled = toggleInput.checked; });
    const toggleSlider = document.createElement("span");
    toggleSlider.className = "toggle-slider";
    toggleLabel.appendChild(toggleInput);
    toggleLabel.appendChild(toggleSlider);
    const enabledLabel = document.createElement("span");
    enabledLabel.className = "toggle-label";
    enabledLabel.textContent = "激活";
    enabledLabel.addEventListener("click", () => { toggleInput.click(); });
    enabledWrap.appendChild(toggleLabel);
    enabledWrap.appendChild(enabledLabel);
    const metaRow = document.createElement("div");
    metaRow.className = "setting-field";
    metaRow.style.cssText = "display:flex;gap:1rem;align-items:center;flex-wrap:wrap;";
    metaRow.appendChild(enabledWrap);
    card.appendChild(metaRow);
  }

  card.appendChild(toolsField);
  return card;
}

// ===== Tool 配置渲染 =====
function renderToolConfigs() {
  if (!toolsListEl) return;
  toolsListEl.innerHTML = "";
  state.cachedToolConfigs.forEach((tool, idx) => {
    toolsListEl.appendChild(buildToolCard(tool, idx));
  });
}

function buildToolCard(tool, idx) {
  const card = document.createElement("div");
  card.className = "tool-config-card" + (tool.enabled === false ? " disabled" : "");

  const title = document.createElement("h4");
  const enabledCheck = document.createElement("input");
  enabledCheck.type = "checkbox";
  enabledCheck.checked = tool.enabled !== false;
  enabledCheck.addEventListener("change", () => {
    tool.enabled = enabledCheck.checked;
    card.classList.toggle("disabled", !tool.enabled);
  });
  title.appendChild(enabledCheck);
  title.appendChild(document.createTextNode(` ${tool.display_name || tool.name}`));

  const desc = document.createElement("div");
  desc.className = "tool-card-desc";
  desc.textContent = tool.description || "";

  const row = document.createElement("div");
  row.className = "tool-card-row";

  const forcedPerm = (window._forcedPermissions || {})[tool.name];
  const permLabel = document.createElement("label");
  permLabel.textContent = "\u6743\u9650: ";
  permLabel.style.fontSize = "0.82rem";
  permLabel.style.fontWeight = "600";
  const permSelect = document.createElement("select");
  permSelect.innerHTML = '<option value="direct">\u76F4\u63A5\u6267\u884C</option><option value="confirm">\u9700\u786E\u8BA4</option>';
  permSelect.value = tool.permission || "confirm";
  if (forcedPerm) {
    permSelect.disabled = true;
    permSelect.value = forcedPerm;
    tool.permission = forcedPerm;
    permLabel.textContent = "\u6743\u9650\uFF08\u9501\u5B9A\uFF09: ";
  }
  row.appendChild(permLabel);
  row.appendChild(permSelect);

  // 超时输入框（工具执行超时秒数，默认 300）
  const timeoutLabel = document.createElement("label");
  timeoutLabel.textContent = "  超时(s): ";
  timeoutLabel.style.fontSize = "0.82rem";
  timeoutLabel.style.fontWeight = "600";
  const timeoutInput = document.createElement("input");
  timeoutInput.type = "number";
  timeoutInput.min = "1";
  timeoutInput.step = "1";
  timeoutInput.value = tool.timeout != null ? tool.timeout : 300;
  timeoutInput.style.width = "5rem";
  timeoutInput.title = "工具执行超时（秒），超时后返回\"工具执行超时\"";
  timeoutInput.addEventListener("change", () => {
    const v = parseFloat(timeoutInput.value);
    tool.timeout = (Number.isFinite(v) && v > 0) ? v : 300;
    timeoutInput.value = tool.timeout;
  });
  row.appendChild(timeoutLabel);
  row.appendChild(timeoutInput);

  card.appendChild(title);
  card.appendChild(desc);
  card.appendChild(row);

  // 自动执行规则
  const toolParams = (window._toolParameters || {})[tool.name] || [];
  const hasParams = toolParams.length > 0;
  const rulesWrap = document.createElement("div");

  function updateRulesVisibility() {
    const visible = !forcedPerm && tool.permission === "confirm" && hasParams;
    rulesWrap.hidden = !visible;
  }

  if (hasParams) {
    rulesWrap.className = "auto-rules-section";
    const rulesLabel = document.createElement("div");
    rulesLabel.style.cssText = "font-size:0.78rem;font-weight:600;color:#475569;margin:0.5rem 0 0.3rem;";
    rulesLabel.textContent = "\u81EA\u52A8\u6267\u884C\u89C4\u5219\uFF08\u6EE1\u8DB3\u4EFB\u4E00\u6761\u4EF6\u5219\u8DF3\u8FC7\u786E\u8BA4\uFF09:";
    rulesWrap.appendChild(rulesLabel);

    const rulesList = document.createElement("div");
    rulesList.className = "auto-rules-list";

    const renderRules = () => {
      rulesList.innerHTML = "";
      (tool.auto_execute_rules || []).forEach((rule, ri) => {
        const ruleRow = document.createElement("div");
        ruleRow.className = "auto-rule-row";
        ruleRow.style.cssText = "display:flex;align-items:center;gap:0.3rem;margin-bottom:0.25rem;flex-wrap:wrap;";

        const paramLabel = document.createElement("span");
        paramLabel.style.cssText = "font-size:0.74rem;font-weight:600;";
        paramLabel.textContent = "\u5F53";
        ruleRow.appendChild(paramLabel);

        const paramSelect = document.createElement("select");
        paramSelect.style.cssText = "flex:0 0 auto;min-width:0;";
        toolParams.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.name;
          opt.textContent = p.name;
          if (p.type) opt.title = `\u7C7B\u578B: ${p.type}`;
          if (p.name === (rule.parameter || "")) opt.selected = true;
          paramSelect.appendChild(opt);
        });
        if (rule.parameter && !toolParams.some((p) => p.name === rule.parameter)) {
          const opt = document.createElement("option");
          opt.value = rule.parameter;
          opt.textContent = rule.parameter;
          opt.selected = true;
          paramSelect.appendChild(opt);
        }
        paramSelect.addEventListener("change", () => { rule.parameter = paramSelect.value; });
        ruleRow.appendChild(paramSelect);

        const opLabel = document.createElement("span");
        opLabel.style.cssText = "font-size:0.74rem;";
        opLabel.textContent = "=";
        ruleRow.appendChild(opLabel);

        const valInput = document.createElement("input");
        valInput.type = "text";
        valInput.value = rule.value || "";
        valInput.placeholder = "\u671F\u671B\u503C";
        valInput.style.cssText = "flex:1;min-width:80px;border:1px solid rgba(148,163,184,0.5);border-radius:6px;padding:0.2rem 0.35rem;font-size:0.8rem;";
        valInput.addEventListener("input", () => { rule.value = valInput.value; });
        ruleRow.appendChild(valInput);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.style.cssText = "border:none;background:none;cursor:pointer;color:#991b1b;font-size:0.9rem;padding:0 0.2rem;";
        delBtn.textContent = "\u00D7";
        delBtn.title = "\u5220\u9664\u6B64\u89C4\u5219";
        delBtn.addEventListener("click", () => {
          tool.auto_execute_rules = (tool.auto_execute_rules || []).filter((_, i) => i !== ri);
          renderRules();
        });
        ruleRow.appendChild(delBtn);

        rulesList.appendChild(ruleRow);
      });
    };
    renderRules();

    const addRuleRow = document.createElement("div");
    addRuleRow.style.cssText = "margin-top:0.35rem;";
    const addRuleBtn = document.createElement("button");
    addRuleBtn.type = "button";
    addRuleBtn.className = "btn btn-ghost";
    addRuleBtn.style.cssText = "padding:0.15rem 0.5rem;font-size:0.75rem;";
    addRuleBtn.textContent = "+ \u6DFB\u52A0\u89C4\u5219";
    addRuleBtn.addEventListener("click", () => {
      const defaultParam = toolParams[0].name;
      tool.auto_execute_rules = [...(tool.auto_execute_rules || []), { parameter: defaultParam, operator: "equals", value: "" }];
      renderRules();
    });
    addRuleRow.appendChild(addRuleBtn);
    rulesWrap.appendChild(rulesList);
    rulesWrap.appendChild(addRuleRow);
  }

  card.appendChild(rulesWrap);
  updateRulesVisibility();

  permSelect.addEventListener("change", () => {
    tool.permission = permSelect.value;
    updateRulesVisibility();
  });

  return card;
}

// ===== GUI 显示器配置渲染 =====
function renderGuiConfig() {
  if (!guiMonitorsGrid) return;
  guiMonitorsGrid.innerHTML = "";

  const monitors = state.cachedGuiConfig.monitors || [];
  if (monitors.length === 0) {
    const hint = document.createElement("p");
    hint.style.cssText = "color:#94a3b8;font-size:0.8rem;text-align:center;padding:1rem;";
    hint.textContent = "\u672A\u68C0\u6D4B\u5230\u663E\u793A\u5668\uFF0C\u8BF7\u786E\u8BA4 screeninfo \u5E93\u5DF2\u5B89\u88C5\u3002";
    guiMonitorsGrid.appendChild(hint);
    return;
  }

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  monitors.forEach((m) => {
    minX = Math.min(minX, m.x);
    minY = Math.min(minY, m.y);
    maxX = Math.max(maxX, m.x + m.width);
    maxY = Math.max(maxY, m.y + m.height);
  });
  const totalW = maxX - minX;
  const totalH = maxY - minY;
  const containerW = 560;
  const containerH = 360;
  const scale = Math.min(containerW / totalW, containerH / totalH, 1);

  const matrixWrap = document.createElement("div");
  matrixWrap.style.cssText = `position:relative;width:${containerW}px;height:${containerH}px;margin:0 auto;border:1px solid rgba(79,70,229,0.25);border-radius:10px;background:rgba(0,0,0,0.2);overflow:hidden;`;

  monitors.forEach((m) => {
    const left = (m.x - minX) * scale;
    const top = (m.y - minY) * scale;
    const w = m.width * scale;
    const h = m.height * scale;
    const isSelected = m.name === state.cachedGuiConfig.selected_name || (!state.cachedGuiConfig.selected_name && m.is_primary);

    const box = document.createElement("div");
    box.className = "gui-monitor-box" + (isSelected ? " gui-monitor-box--selected" : "");
    box.style.cssText = `position:absolute;left:${left}px;top:${top}px;width:${w}px;height:${h}px;border:2px solid ${isSelected ? "#4f46e5" : "rgba(148,163,184,0.4)"};border-radius:6px;background:${isSelected ? "rgba(79,70,229,0.12)" : "rgba(255,255,255,0.03)"};cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;transition:all 0.15s;`;
    box.title = `${m.name}\n${m.width}x${m.height}${m.is_primary ? " (\u4E3B\u663E\u793A\u5668)" : ""}`;

    const nameEl = document.createElement("span");
    nameEl.style.cssText = `font-size:${Math.max(9, w / 14)}px;color:${isSelected ? "#e0e7ff" : "#94a3b8"};text-align:center;line-height:1.2;pointer-events:none;`;
    nameEl.textContent = (m.name || "Unknown").substring(0, 20) + (m.name && m.name.length > 20 ? "\u2026" : "");
    const resEl = document.createElement("span");
    resEl.style.cssText = `font-size:${Math.max(8, w / 18)}px;color:${isSelected ? "#a5b4fc" : "#64748b"};pointer-events:none;`;
    resEl.textContent = `${m.width}x${m.height}`;
    const priTag = document.createElement("span");
    priTag.style.cssText = `font-size:${Math.max(7, w / 22)}px;color:#cbd5e1;pointer-events:none;`;
    priTag.textContent = m.is_primary ? "\u4E3B\u5C4F" : "";

    box.appendChild(nameEl);
    box.appendChild(resEl);
    box.appendChild(priTag);

    box.addEventListener("click", () => {
      state.cachedGuiConfig.selected_name = m.name;
      renderGuiConfig();
    });

    box.addEventListener("mouseenter", () => {
      box.style.borderColor = "#818cf8";
      box.style.background = "rgba(79,70,229,0.08)";
    });
    box.addEventListener("mouseleave", () => {
      if (!isSelected || m.name !== state.cachedGuiConfig.selected_name) {
        box.style.borderColor = isSelected ? "#4f46e5" : "rgba(148,163,184,0.4)";
        box.style.background = isSelected ? "rgba(79,70,229,0.12)" : "rgba(255,255,255,0.03)";
      }
    });

    matrixWrap.appendChild(box);
  });

  guiMonitorsGrid.appendChild(matrixWrap);

  const selectedInfo = document.createElement("p");
  selectedInfo.style.cssText = "text-align:center;color:#a5b4fc;font-size:0.78rem;margin-top:0.6rem;";
  const selMon = monitors.find((m) => m.name === state.cachedGuiConfig.selected_name) || monitors.find((m) => m.is_primary);
  selectedInfo.textContent = selMon ? `\u5F53\u524D GUI \u64CD\u4F5C\u533A\u57DF: ${selMon.name} (${selMon.width}x${selMon.height})` : "\u5F53\u524D GUI \u64CD\u4F5C\u533A\u57DF: \u5168\u5C4F";
  guiMonitorsGrid.appendChild(selectedInfo);

  // GUI 模型选择
  const modelSection = document.createElement("div");
  modelSection.style.cssText = "margin-top:1.2rem;border-top:1px solid rgba(148,163,184,0.2);padding-top:0.8rem;";

  const modelLabel = document.createElement("label");
  modelLabel.textContent = "GUI \u89C6\u89C9\u5B9A\u4F4D\u6A21\u578B";
  modelLabel.style.cssText = "display:block;font-size:0.85rem;font-weight:600;color:#1e293b;margin-bottom:0.4rem;";

  const modelHint = document.createElement("p");
  modelHint.style.cssText = "color:#94a3b8;font-size:0.72rem;margin:0 0 0.5rem;";
  modelHint.textContent = "\u4E0D\u6307\u5B9A\u5219\u9ED8\u8BA4\u4F7F\u7528\u5F53\u524D Agent \u7684\u4E3B\u6A21\u578B\u3002";

  const modelSelectRow = document.createElement("div");
  modelSelectRow.style.cssText = "display:flex;gap:0.4rem;align-items:center;";

  const modelSelect = document.createElement("select");
  modelSelect.style.cssText = "flex:1;border:1px solid rgba(148,163,184,0.5);border-radius:8px;padding:0.35rem 0.5rem;font-size:0.82rem;background:rgba(255,255,255,0.8);color:var(--text);cursor:pointer;";

  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "\u2014 \u4F7F\u7528 Agent \u4E3B\u6A21\u578B \u2014";
  defaultOpt.selected = !state.cachedGuiConfig.gui_model_id;
  modelSelect.appendChild(defaultOpt);

  const guiModels = state.cachedGuiConfig.models || [];
  guiModels.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.name} (${m.model})`;
    if (m.id === state.cachedGuiConfig.gui_model_id) opt.selected = true;
    modelSelect.appendChild(opt);
  });
  if (state.cachedGuiConfig.gui_model_id && !guiModels.some((m) => m.id === state.cachedGuiConfig.gui_model_id)) {
    const opt = document.createElement("option");
    opt.value = state.cachedGuiConfig.gui_model_id;
    opt.textContent = state.cachedGuiConfig.gui_model_id + " (\u5DF2\u5220\u9664)";
    opt.selected = true;
    modelSelect.appendChild(opt);
  }

  modelSelect.addEventListener("change", () => {
    state.cachedGuiConfig.gui_model_id = modelSelect.value;
  });

  modelSelectRow.appendChild(modelSelect);
  modelSection.appendChild(modelLabel);
  modelSection.appendChild(modelHint);
  modelSection.appendChild(modelSelectRow);
  guiMonitorsGrid.appendChild(modelSection);
}

// ===== Env 配置渲染 =====
// 环境变量解释（鼠标悬停变量名时显示）
const ENV_DESC = {
  WORKING_DIR: "项目工作目录，Agent 产生的文件默认存放位置。",
  WORKSPACE_DIR: "工作空间目录（相对 WORKING_DIR），留空则使用 WORKING_DIR。",
  USER_PYTHON_PATH: "自定义 Python 解释器路径，供终端/脚本执行使用。",
  STREAMING_TTS_URL: "语音合成（TTS）服务地址。",
  ASR_BASE_URL: "语音识别（ASR）服务地址。",
  RAG_BASE_URL: "RAG 检索服务地址。",
  IMAGE_GEN_URL: "图片生成服务地址。",
  WEB_SEARCH_API_KEY: "网络搜索 API Key。",
  WEB_SEARCH_ENGINE: "网络搜索引擎（如 tavily）。",
  LLM_CONTEXT_WINDOW: "LLM 上下文窗口大小（token），压缩阈值按窗口比例计算。",
  COMPRESS_RATE: "上下文压缩阈值比例（0~1），token 用量超过 窗口×该值 时触发压缩。",
  IMG_SIZE: "工具截图/图片缩放边长（像素），用于控制 token 消耗。",
  RAG_CHUNK_SIZE: "RAG 文档分块大小（字符）。",
  RAG_CHUNK_OVERLAP: "RAG 分块重叠大小（字符）。",
  GROUNDING_WIDTH: "GUI 定位图像宽度（像素）。",
  GROUNDING_HEIGHT: "GUI 定位图像高度（像素）。",
  LOOP_DETECT_REPEATED_TOOL_WARN: "同一工具连续重复调用超过该次数时输出警告。",
  SEND_FILE_SIZE_LIMIT: "发送文件大小上限（MB）。",
  STORAGE_BACKEND: "存储后端：json（本地文件）或 mysql（数据库）。",
  MYSQL_HOST: "MySQL 主机地址。",
  MYSQL_PORT: "MySQL 端口。",
  MYSQL_USER: "MySQL 用户名。",
  MYSQL_PASSWORD: "MySQL 密码。",
  MYSQL_DATABASE: "MySQL 数据库名。",
  EMAIL_ADDRESS: "邮箱地址（邮件发送账号）。",
  EMAIL_AUTH_CODE: "邮箱 SMTP 授权码。",
  CRON_TIME_PERIOD_MINUTES: "定时任务冲突检测的时间段长度（分钟）。",
  LLM_BASE_URL: "LLM 服务地址。",
  LLM_API_KEY: "LLM API Key。",
  LLM_MODEL: "LLM 模型名。",
  LLM_TIMEOUT: "LLM 请求超时（秒）。",
};

// 构建 MySQL 连接配置子区块（仅在 STORAGE_BACKEND=mysql 时渲染）
function buildMysqlConfigSection() {
  const section = document.createElement("div");
  section.className = "env-mysql-section";

  const title = document.createElement("div");
  title.className = "env-mysql-section-title";
  title.textContent = "MySQL 连接配置";
  section.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "env-mysql-grid";

  const fields = [
    { key: "MYSQL_HOST", label: "主机 (host)", type: "text", title: ENV_DESC.MYSQL_HOST },
    { key: "MYSQL_PORT", label: "端口 (port)", type: "number", title: ENV_DESC.MYSQL_PORT },
    { key: "MYSQL_USER", label: "用户名 (user)", type: "text", title: ENV_DESC.MYSQL_USER },
    { key: "MYSQL_PASSWORD", label: "密码 (password)", type: "password", title: ENV_DESC.MYSQL_PASSWORD },
    { key: "MYSQL_DATABASE", label: "数据库 (database)", type: "text", title: ENV_DESC.MYSQL_DATABASE },
  ];

  fields.forEach((f) => {
    const wrap = document.createElement("div");
    wrap.className = "env-mysql-field";
    const lbl = document.createElement("label");
    lbl.textContent = f.label;
    if (f.title) lbl.title = f.title;
    lbl.setAttribute("for", `envMysql_${f.key}`);
    const inp = document.createElement("input");
    inp.id = `envMysql_${f.key}`;
    inp.type = f.type;
    if (f.type === "number") inp.step = "1";
    inp.value = state.cachedEnvConfig[f.key] ?? "";
    inp.addEventListener("input", () => { state.cachedEnvConfig[f.key] = inp.value; });
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    grid.appendChild(wrap);
  });

  section.appendChild(grid);
  return section;
}

/**
 * 给环境变量行右侧添加 "?" 帮助按钮（点击显示 ENV_DESC 说明的 popover，含连击保护）。
 * @param {HTMLElement} row - .env-config-item 行容器
 * @param {string} key - 环境变量名
 */
let _envHelpDocListenerBound = false;
function attachEnvHelp(row, key) {
  const desc = ENV_DESC[key] || "该环境变量的用途暂无说明";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "env-help-btn";
  btn.textContent = "?";
  btn.title = "查看说明";
  const pop = document.createElement("div");
  pop.className = "env-help-popover";
  pop.textContent = desc;
  pop.hidden = true;
  btn.addEventListener("click", withClickGuard((e) => {
    e.stopPropagation();
    document.querySelectorAll(".env-help-popover").forEach((p) => { if (p !== pop) p.hidden = true; });
    pop.hidden = !pop.hidden;
  }));
  row.appendChild(btn);
  row.appendChild(pop);

  if (!_envHelpDocListenerBound) {
    _envHelpDocListenerBound = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest(".env-help-btn, .env-help-popover")) return;
      document.querySelectorAll(".env-help-popover").forEach((p) => { p.hidden = true; });
    });
  }
  return btn;
}

function renderEnvConfig() {
  if (!envListEl) return;
  envListEl.innerHTML = "";

  // 模型管理区
  const modelsSection = document.createElement("div");
  modelsSection.style.cssText = "margin-bottom:1.5rem;";

  const modelsHeader = document.createElement("div");
  modelsHeader.className = "settings-section-title";
  const modelsTitle = document.createElement("h4");
  modelsTitle.textContent = "LLM \u6A21\u578B\u5217\u8868";
  const addModelBtn = document.createElement("button");
  addModelBtn.type = "button";
  addModelBtn.className = "btn btn-primary";
  addModelBtn.textContent = "+ \u6DFB\u52A0\u6A21\u578B";
  addModelBtn.addEventListener("click", () => openModelModal(-1));
  modelsHeader.appendChild(modelsTitle);
  modelsHeader.appendChild(addModelBtn);
  modelsSection.appendChild(modelsHeader);

  if (state.cachedModels.length === 0) {
    const emptyHint = document.createElement("p");
    emptyHint.style.cssText = "color:#94a3b8;font-size:0.8rem;";
    emptyHint.textContent = "\u6682\u65E0\u6A21\u578B\uFF0C\u8BF7\u6DFB\u52A0\u81F3\u5C11\u4E00\u4E2A LLM \u6A21\u578B\u3002";
    modelsSection.appendChild(emptyHint);
  } else {
    const table = document.createElement("div");
    table.className = "model-table";
    const thead = document.createElement("div");
    thead.className = "model-table-head";
    thead.innerHTML = '<span class="col-name">\u540D\u79F0</span><span class="col-model">Model</span><span class="col-url">Base URL</span><span class="col-actions" style="justify-content:flex-end;color:inherit;font-size:inherit;">\u64CD\u4F5C</span>';
    table.appendChild(thead);
    state.cachedModels.forEach((m, mi) => {
      const row = document.createElement("div");
      row.className = "model-table-row";
      row.innerHTML = `<span class="col-name" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</span>
        <span class="col-model" title="${escapeHtml(m.model)}">${escapeHtml(m.model)}</span>
        <span class="col-url" title="${escapeHtml(m.base_url)}">${escapeHtml(m.base_url)}</span>`;
      const actions = document.createElement("span");
      actions.className = "col-actions";
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.textContent = "\u7F16\u8F91";
      editBtn.addEventListener("click", () => openModelModal(mi));
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "danger";
      delBtn.textContent = "\u5220\u9664";
      delBtn.addEventListener("click", async () => {
        if (!await showConfirm(`\u786E\u5B9A\u5220\u9664\u6A21\u578B "${m.name}"\uFF1F`)) return;
        state.cachedModels.splice(mi, 1);
        state.cachedAgentConfigs.forEach((a) => { if (a.llm_model_id === m.id) a.llm_model_id = ""; });
        api("/api/config/models", { method: "POST", body: JSON.stringify({ models: state.cachedModels }) }).catch(() => {});
        api("/api/config/reload", { method: "POST", body: JSON.stringify({}) }).catch(() => {});
        renderEnvConfig();
        renderAgentConfigs();
      });
      actions.appendChild(editBtn);
      actions.appendChild(delBtn);
      row.appendChild(actions);
      table.appendChild(row);
    });
    modelsSection.appendChild(table);
  }
  envListEl.appendChild(modelsSection);

  // 模型编辑弹窗
  const modalOverlay = document.createElement("div");
  modalOverlay.className = "model-modal-overlay";
  modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModelModal(); });
  const modalBox = document.createElement("div");
  modalBox.className = "model-modal-box";
  modalBox.innerHTML = '<h3>\u6A21\u578B\u914D\u7F6E</h3>';
  const modalBody = document.createElement("div");
  modalBody.className = "model-modal-body";
  const modalFields = {};
  ["name", "model", "api_key", "base_url", "timeout"].forEach((key) => {
    const div = document.createElement("div");
    div.className = "modal-field";
    const lbl = document.createElement("label");
    lbl.textContent = { name: "\u663E\u793A\u540D\u79F0", model: "\u6A21\u578B\u540D (model)", api_key: "API Key", base_url: "Base URL", timeout: "Timeout (\u79D2)" }[key];
    const inp = document.createElement("input");
    inp.type = key === "timeout" ? "number" : key === "api_key" ? "password" : "text";
    if (key === "timeout") inp.step = "any";
    div.appendChild(lbl);
    div.appendChild(inp);
    modalFields[key] = inp;
    modalBody.appendChild(div);
  });
  // 深度思考改由 composer 的思考档位（low/high/xhigh/max/ultra）全局控制，此处不再提供开关
  modalBody.appendChild(document.createComment("thinking-toggle-removed"));
  modalBox.appendChild(modalBody);
  const modalActions = document.createElement("div");
  modalActions.className = "model-modal-actions";
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "btn btn-secondary";
  cancelBtn.textContent = "\u53D6\u6D88";
  cancelBtn.addEventListener("click", closeModelModal);
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn btn-primary";
  saveBtn.textContent = "\u4FDD\u5B58";
  saveBtn.addEventListener("click", async () => {
    const data = {
      id: state.editingModelIdx >= 0 && state.cachedModels[state.editingModelIdx] ? state.cachedModels[state.editingModelIdx].id : makeId(),
      name: modalFields.name.value.trim(),
      model: modalFields.model.value.trim(),
      api_key: modalFields.api_key.value.trim(),
      base_url: modalFields.base_url.value.trim(),
      timeout: parseFloat(modalFields.timeout.value) || 60,
      max_retries: 0,
    };
    if (!data.name || !data.model) { showToast("\u540D\u79F0\u548C\u6A21\u578B\u540D\u4E0D\u80FD\u4E3A\u7A7A"); return; }
    if (state.editingModelIdx >= 0) {
      state.cachedModels[state.editingModelIdx] = data;
    } else {
      state.cachedModels.push(data);
    }
    await api("/api/config/models", { method: "POST", body: JSON.stringify({ models: state.cachedModels }) });
    await api("/api/config/reload", { method: "POST", body: JSON.stringify({}) });
    closeModelModal();
    renderEnvConfig();
    renderAgentConfigs();
    import('../app.js').then((m) => { if (m.refreshModelSelect) m.refreshModelSelect(); }).catch(() => {});
    setStatus("\u6A21\u578B\u5DF2\u4FDD\u5B58", "success");
  });
  modalActions.appendChild(cancelBtn);
  modalActions.appendChild(saveBtn);
  modalBox.appendChild(modalActions);
  modalOverlay.appendChild(modalBox);
  envListEl.appendChild(modalOverlay);

  window._modelModalOverlay = modalOverlay;
  window._modelModalFields = modalFields;

  const divider = document.createElement("div");
  divider.style.cssText = "border-top:1px solid rgba(148,163,184,0.25);margin:1rem 0;";
  envListEl.appendChild(divider);

  const otherTitle = document.createElement("h4");
  otherTitle.textContent = "\u5176\u4ED6\u73AF\u5883\u53D8\u91CF";
  otherTitle.style.cssText = "margin:0 0 0.65rem;font-size:0.92rem;font-weight:700;color:#1e293b;";
  envListEl.appendChild(otherTitle);

  const DIR_PICKER_KEYS = new Set(["WORKING_DIR", "WORKSPACE_DIR"]);
  const FILE_PICKER_KEYS = new Set(["USER_PYTHON_PATH"]);

  const entries = Object.entries(state.cachedEnvConfig);
  entries.forEach(([key, val]) => {
    // MYSQL_* 由存储后端区块统一渲染（仅选 mysql 时显示）
    if (key.startsWith("MYSQL_")) return;

    const row = document.createElement("div");
    row.className = "env-config-item";
    const lbl = document.createElement("label");
    lbl.textContent = key;
    if (ENV_DESC[key]) lbl.title = ENV_DESC[key];

    // 定时任务存储后端：用下拉选择而非纯文本框
    if (key === "STORAGE_BACKEND") {
      lbl.textContent = "Storage Backend";
      if (ENV_DESC.STORAGE_BACKEND) lbl.title = ENV_DESC.STORAGE_BACKEND;
      const sel = document.createElement("select");
      const optJson = document.createElement("option");
      optJson.value = "json"; optJson.textContent = "JSON（本地文件）";
      const optMysql = document.createElement("option");
      optMysql.value = "mysql"; optMysql.textContent = "MySQL（数据库）";
      sel.appendChild(optJson);
      sel.appendChild(optMysql);
      sel.value = (val === "mysql") ? "mysql" : "json";
      sel.addEventListener("change", () => {
        state.cachedEnvConfig[key] = sel.value;
        // 重新渲染以显隐 MySQL 连接配置区块
        renderEnvConfig();
      });
      row.appendChild(lbl);
      row.appendChild(sel);
      attachEnvHelp(row, key);
      // 选 mysql 时紧随其后渲染连接配置区块
      if (sel.value === "mysql") {
        const mysqlSection = buildMysqlConfigSection();
        row.appendChild(mysqlSection);
      }
      envListEl.appendChild(row);
      return;
    }

    // 定时任务时间段长度：数字输入 + 「应用」按钮（热更新调度器 + 持久化）
    if (key === "CRON_TIME_PERIOD_MINUTES") {
      lbl.textContent = "Cron Period (minutes)";
      if (ENV_DESC.CRON_TIME_PERIOD_MINUTES) lbl.title = ENV_DESC.CRON_TIME_PERIOD_MINUTES;
      const wrap = document.createElement("div");
      wrap.style.cssText = "display:flex;gap:0.5rem;align-items:center;flex:1;";
      const numInp = document.createElement("input");
      numInp.type = "number";
      numInp.step = "1";
      numInp.min = "1";
      numInp.style.cssText = "flex:1;";
      numInp.value = val ?? 30;
      numInp.addEventListener("input", () => { state.cachedEnvConfig[key] = numInp.value; });
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "btn btn-primary";
      applyBtn.style.cssText = "white-space:nowrap;";
      applyBtn.textContent = "应用";
      applyBtn.addEventListener("click", async () => {
        const v = parseFloat(numInp.value);
        if (!(v > 0)) { showToast("时间段长度必须为正数"); return; }
        try {
          const res = await api("/api/cron/period", { method: "POST", body: JSON.stringify({ period_minutes: v }) });
          state.cachedEnvConfig[key] = String(res.period_minutes);
          numInp.value = res.period_minutes;
          showToast(`时间段长度已设为 ${res.period_minutes} 分钟`);
        } catch (e) {
          showToast("应用失败: " + (e.message || e));
        }
      });
      wrap.appendChild(numInp);
      wrap.appendChild(applyBtn);
      row.appendChild(lbl);
      row.appendChild(wrap);
      attachEnvHelp(row, key);
      envListEl.appendChild(row);
      return;
    }

    const inp = document.createElement("input");
    inp.type = "text";
    inp.value = val ?? "";
    inp.addEventListener("input", () => { state.cachedEnvConfig[key] = inp.value; });
    row.appendChild(lbl);
    row.appendChild(inp);

    if (DIR_PICKER_KEYS.has(key)) {
      const dirBtn = document.createElement("button");
      dirBtn.type = "button";
      dirBtn.className = "btn btn-ghost dir-pick-btn";
      dirBtn.textContent = "\u9009\u62E9";
      dirBtn.title = "\u9009\u62E9\u6587\u4EF6\u5939";
      dirBtn.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/pick-folder");
          const data = await res.json();
          if (data.path) {
            inp.value = data.path;
            state.cachedEnvConfig[key] = data.path;
          }
        } catch (_) {}
      });
      row.appendChild(dirBtn);
    }

    if (FILE_PICKER_KEYS.has(key)) {
      const fileBtn = document.createElement("button");
      fileBtn.type = "button";
      fileBtn.className = "btn btn-ghost dir-pick-btn";
      fileBtn.textContent = "\u9009\u62E9";
      fileBtn.title = "\u9009\u62E9 Python \u53EF\u6267\u884C\u6587\u4EF6";
      fileBtn.addEventListener("click", async () => {
        try {
          if (window.electronAPI && window.electronAPI.pickPython) {
            const res = await window.electronAPI.pickPython();
            if (res.path) {
              inp.value = res.path;
              state.cachedEnvConfig[key] = res.path;
            }
          }
        } catch (_) {}
      });
      row.appendChild(fileBtn);
    }

    attachEnvHelp(row, key);

    envListEl.appendChild(row);
  });
}

function openModelModal(idx) {
  state.editingModelIdx = idx;
  const overlay = window._modelModalOverlay;
  const fields = window._modelModalFields;
  if (!overlay || !fields) return;
  if (idx >= 0 && state.cachedModels[idx]) {
    const m = state.cachedModels[idx];
    fields.name.value = m.name || "";
    fields.model.value = m.model || "";
    fields.api_key.value = m.api_key || "";
    fields.base_url.value = m.base_url || "";
    fields.timeout.value = m.timeout || 60;
  } else {
    fields.name.value = "";
    fields.model.value = "";
    fields.api_key.value = "";
    fields.base_url.value = "";
    fields.timeout.value = 60;
  }
  overlay.classList.add("show");
}

function closeModelModal() {
  const overlay = window._modelModalOverlay;
  if (overlay) overlay.classList.remove("show");
}

// 添加 Agent
if (addAgentBtn) {
  addAgentBtn.addEventListener("click", () => {
    const isFirst = state.cachedAgentConfigs.length === 0;
    state.cachedAgentConfigs.push({
      name: "new_agent",
      description: "",
      system_prompt: isFirst ? "" : "你是一个专用的子 Agent，负责执行主 Agent 委派给你的特定任务。请根据任务描述高效完成工作，并返回清晰的结果。",
      max_iterations: 200,
      llm: { model: "", api_key: "", base_url: "", timeout: 60, max_retries: 0 },
      llm_model_id: state.cachedModels.length > 0 ? state.cachedModels[0].id : "",
      tools: [],
      enabled: true,
      trajectory_rounds: 3,
    });
    renderAgentConfigs();
  });
}

// 设置面板事件绑定
const settingsBtn = $("settingsBtn");
if (settingsBtn) settingsBtn.addEventListener("click", openSettings);
if (settingsCloseBtn) settingsCloseBtn.addEventListener("click", closeSettings);
if (settingsCancelBtn) settingsCancelBtn.addEventListener("click", closeSettings);
if (settingsOverlay) {
  settingsOverlay.addEventListener("click", (e) => {
    if (e.target === settingsOverlay) closeSettings();
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && settingsOverlay && !settingsOverlay.hidden) closeSettings();
});

// 保存回调
document.querySelectorAll(".settings-save-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const saveType = btn.getAttribute("data-save");
    // 记录保存前的存储后端基线，用于保存后检测切换并重载会话
    const prevBackend = state._lastAppliedBackend || "json";
    setStatus("\u6B63\u5728\u4FDD\u5B58...", "");
    try {
      if (saveType === "agents") {
        const agents = state.cachedAgentConfigs.map((a, i) => ({
          name: a.name,
          description: a.description || "",
          system_prompt: a.system_prompt,
          max_iterations: a.max_iterations,
          llm_model_id: a.llm_model_id || "",
          tools: a.tools || [],
          enabled: i === 0 ? true : (a.enabled !== false),
          role: i === 0 ? "main" : "sub",
          trajectory_rounds: a.trajectory_rounds ?? 3,
        }));
        await api("/api/config/agents", { method: "POST", body: JSON.stringify({ agents }) });
        await api("/api/config/reload", { method: "POST", body: JSON.stringify({}) });
      } else if (saveType === "tools") {
        const tools = state.cachedToolConfigs.map((t) => ({
          name: t.name,
          display_name: t.display_name,
          description: t.description,
          permission: t.permission,
          auto_execute_rules: t.auto_execute_rules || [],
          enabled: t.enabled,
          timeout: t.timeout != null ? t.timeout : 300,
        }));
        await api("/api/config/tools", { method: "POST", body: JSON.stringify({ tools }) });
        await api("/api/config/reload", { method: "POST", body: JSON.stringify({}) });
      } else if (saveType === "env") {
        await api("/api/config/models", { method: "POST", body: JSON.stringify({ models: state.cachedModels }) });
        await api("/api/config/env", { method: "POST", body: JSON.stringify({ env: state.cachedEnvConfig }) });
        await api("/api/config/reload", { method: "POST", body: JSON.stringify({}) });
        refreshNickname();
      } else if (saveType === "gui") {
        await api("/api/config/gui", { method: "POST", body: JSON.stringify({ gui_monitor_name: state.cachedGuiConfig.selected_name, gui_model_id: state.cachedGuiConfig.gui_model_id || "" }) });
      }
      await loadAllConfigs();
      // 存储后端切换检测：数据源变了，需重新拉取会话列表与消息
      const newBackend = state._lastAppliedBackend || "json";
      if (newBackend !== prevBackend) {
        try {
          const mod = await import("./sessions.js");
          if (mod && typeof mod.bootstrap === "function") {
            await mod.bootstrap();
            const label = newBackend === "mysql" ? "MySQL（数据库）" : "JSON（本地文件）";
            setStatus(`存储后端已切换为 ${label}，会话列表已刷新。`, "success");
            return;
          }
        } catch (_) {
          /* 重载失败不影响保存结果 */
        }
      }
      setStatus("\u4FDD\u5B58\u6210\u529F\uFF01\u914D\u7F6E\u5DF2\u5B9E\u65F6\u751F\u6548\u3002", "success");
    } catch (e) {
      setStatus("\u4FDD\u5B58\u5931\u8D25: " + e.message, "error");
    }
  });
});

// ===== 主题/语言面板 =====
function renderThemePanel() {
  const grid = $("themeGrid");
  const langSelect = $("langSelect");
  if (!grid) return;

  const current = getCurrentTheme();
  grid.innerHTML = "";

  const swatches = {
    "vscode-dark": ["#1e1e1e","#007acc","#d4d4d4","#f44747","#6a9955"],
    "vscode-light": ["#ffffff","#005fb8","#1e1e1e","#f44747","#6a9955"],
    "solarized-light": ["#fdf6e3","#268bd2","#586e75","#dc322f","#859900"],
    "github-light": ["#ffffff","#0366d6","#24292e","#d73a49","#28a745"],
    "cyber-neon": ["#0a0e14","#00f0ff","#c9d1d9","#ff477e","#00e5ff"],
    "deep-space-indigo": ["#16162a","#7c83ff","#e2e8f0","#f472b6","#a78bfa"],
    "warm-terracotta": ["#fdf7f0","#c8553d","#4a3528","#e07b5a","#d4a574"],
    "pixel-gold": ["#1a140c","#ffc83d","#f5e6c8","#ff8c00","#d4af37"],
    "neo-brutalist": ["#ffffff","#111111","#000000","#ff4444","#00cc00"],
    "glassmorphism-aurora": ["#f0e6fa","#9d4edd","#2d2440","#ff70a6","#c77dff"],
    "beige-cream": ["#faf5e8","#7fa67a","#3d4a3a","#d4956b","#8db580"],
    "khaki-klein": ["#f5f1e0","#002fa7","#2b2b2b","#0055ff","#c4a35a"],
  };

  Object.entries(THEMES).forEach(([id, theme]) => {
    const card = document.createElement("div");
    card.className = "theme-card" + (id === current ? " theme-card--active" : "");
    card.addEventListener("click", () => {
      applyTheme(id);
      grid.querySelectorAll(".theme-card").forEach((c) => c.classList.remove("theme-card--active"));
      card.classList.add("theme-card--active");
    });

    const sw = swatches[id] || ["#333","#666","#999","#ef4444","#22c55e"];
    card.innerHTML = `
      <div class="theme-card-swatch">
        ${sw.map((c) => `<span style="background:${c}"></span>`).join("")}
      </div>
      <div class="theme-card-name">${theme.name}</div>
    `;
    grid.appendChild(card);
  });

  // 语言选择
  if (langSelect) {
    langSelect.innerHTML = "";
    const curLang = (() => { try { return localStorage.getItem("minor_language") || "zh-CN"; } catch { return "zh-CN"; } })();
    Object.entries(LANGS).forEach(([id, lang]) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = lang.name;
      if (id === curLang) opt.selected = true;
      langSelect.appendChild(opt);
    });
    langSelect.onchange = () => setLanguage(langSelect.value);
  }

  // 自定义背景图
  const bgInput = $("bgImageInput");
  const bgApplyBtn = $("bgImageApplyBtn");
  const bgResetBtn = $("bgImageResetBtn");
  const bgStatus = $("bgPreviewStatus");
  const bgPickerBtn = $("bgImagePickerBtn");
  const bgFileInput = $("bgImageFileInput");
  if (bgInput) {
    bgInput.value = getBgImage();
    const applyBg = () => {
      const url = bgInput.value.trim();
      setBgImage(url);  // 存储原始路径（可读），applyBgImage 内部自动转换
      if (bgStatus) {
        bgStatus.textContent = url ? "背景已更新 ✓" : "已恢复默认背景";
        bgStatus.style.color = url ? "#22c55e" : "#6a6a6a";
      }
    };
    if (bgApplyBtn) bgApplyBtn.onclick = applyBg;
    if (bgResetBtn) {
      bgResetBtn.onclick = () => {
        bgInput.value = "";
        applyBg();
      };
    }
    // 回车也应用
    bgInput.onkeydown = (e) => { if (e.key === 'Enter') applyBg(); };
    
    // 图片选择器按钮点击事件
    if (bgPickerBtn && bgFileInput) {
      bgPickerBtn.onclick = () => {
        bgFileInput.click();
      };
      
      // 文件选择事件
      bgFileInput.onchange = (e) => {
        const file = e.target.files?.[0];
        if (file) {
          // 使用文件路径（Electron 环境）或创建临时 URL（Web 环境）
          if (window.electronAPI && window.electronAPI.getFilePath) {
            // Electron 环境：获取文件路径
            const filePath = window.electronAPI.getFilePath(file);
            bgInput.value = filePath;
            applyBg();
          } else {
            // Web 环境：创建临时 URL
            const reader = new FileReader();
            reader.onload = (event) => {
              bgInput.value = event.target?.result || "";
              applyBg();
            };
            reader.readAsDataURL(file);
          }
        }
        // 清空 input 以便重复选择同一文件
        bgFileInput.value = "";
      };
    }
  }

  // 背景模糊度
  const blurSlider = $("bgBlurSlider");
  const blurVal = $("bgBlurVal");
  if (blurSlider) {
    const curBlur = getBgBlur();
    blurSlider.value = curBlur !== "" ? parseFloat(curBlur) : 0;
    if (blurVal) blurVal.textContent = blurSlider.value + "px";
    blurSlider.oninput = () => {
      if (blurVal) blurVal.textContent = blurSlider.value + "px";
      setBgBlur(blurSlider.value > 0 ? blurSlider.value : "");
    };
  }

  // 背景暗角
  const vignetteSlider = $("bgVignetteSlider");
  const vignetteVal = $("bgVignetteVal");
  if (vignetteSlider) {
    const curVig = getBgVignette();
    vignetteSlider.value = curVig !== "" ? parseFloat(curVig) : 0;
    if (vignetteVal) vignetteVal.textContent = Math.round(vignetteSlider.value * 100) + "%";
    vignetteSlider.oninput = () => {
      if (vignetteVal) vignetteVal.textContent = Math.round(vignetteSlider.value * 100) + "%";
      setBgVignette(vignetteSlider.value > 0 ? String(vignetteSlider.value) : "");
    };
  }

  // 字体设置
  const fontSelect = $("fontFamilySelect");
  const fontSizeSelect = $("fontSizeSelect");
  if (fontSelect) {
    fontSelect.innerHTML = "";
    const curFont = getFontSetting('family') || '';
    let curFontId = 'system';
    Object.entries(FONT_PRESETS).forEach(([id, p]) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = p.name;
      if (p.family === curFont || (id === 'system' && !curFont)) opt.selected = true;
      fontSelect.appendChild(opt);
    });
    fontSelect.onchange = () => setFontSetting('family', FONT_PRESETS[fontSelect.value]?.family || '');
  }
  if (fontSizeSelect) {
    fontSizeSelect.innerHTML = "";
    const curSize = getFontSetting('size') || '';
    Object.entries(FONT_SIZE_PRESETS).forEach(([val, label]) => {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = label;
      if (val === curSize || (val === '14px' && !curSize)) opt.selected = true;
      fontSizeSelect.appendChild(opt);
    });
    fontSizeSelect.onchange = () => setFontSetting('size', fontSizeSelect.value);
  }
}

/**
 * 刷新欢迎区的昵称显示（保存 env 配置后调用）。
 */
async function refreshNickname() {
  const greeting = document.getElementById("welcomeGreeting");
  if (!greeting) return;
  try {
    const data = await api("/api/config/env");
    const env = data.env || {};
    const nickname = env.USER_NICKNAME || data.USER_NICKNAME || "";
    if (nickname) {
      greeting.textContent = `欢迎您，${nickname}`;
    }
  } catch {
    // keep current
  }
}

export { openSettings, closeSettings, loadAllConfigs, renderAgentConfigs, renderToolConfigs, renderGuiConfig, renderEnvConfig, openModelModal, closeModelModal, makeField, getModelLabel, buildAgentCard, buildToolCard, renderThemePanel };
