// skills.js -- Skills 管理面板

import { $, escapeHtml } from './utils.js';
import { showConfirm } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';

const skillsListEl = $("skillsList");
const skillEditorOverlay = $("skillEditorOverlay");
const skillEditorTitle = $("skillEditorTitle");
const skillNameInput = $("skillNameInput");
const skillDescInput = $("skillDescInput");
const skillVersionInput = $("skillVersionInput");
const skillAuthorInput = $("skillAuthorInput");
const skillTagsInput = $("skillTagsInput");
const skillContentInput = $("skillContentInput");
const skillAttachmentsList = $("skillAttachmentsList");
const skillFileInput = $("skillFileInput");
const skillEditorStatus = $("skillEditorStatus");
const skillEditorSave = $("skillEditorSave");
const skillEditorCancel = $("skillEditorCancel");
const skillEditorClose = $("skillEditorClose");
const skillEnableCheck = $("skillEnableCheck");

function setSkillEditorStatus(msg, type) {
  if (!skillEditorStatus) return;
  skillEditorStatus.textContent = msg;
  skillEditorStatus.className = "skill-editor-status" + (type ? " " + type : "");
}

function openSkillEditor(skillNameToEdit) {
  state.editingSkillName = skillNameToEdit || "";
  state.editingSkillAttachments.length = 0;

  if (state.editingSkillName) {
    skillEditorTitle.textContent = "\u7F16\u8F91 Skill: " + state.editingSkillName;
    skillNameInput.value = state.editingSkillName;
    skillNameInput.disabled = true;
    api("/api/skills/" + encodeURIComponent(state.editingSkillName)).then((res) => {
      const s = res.skill;
      skillDescInput.value = s.description || "";
      skillVersionInput.value = s.version || "1.0.0";
      skillAuthorInput.value = s.author || "";
      skillTagsInput.value = (s.tags || []).join(", ");
      skillContentInput.value = s.content || "";
      skillEnableCheck.checked = s.enable !== false;
      state.editingSkillAttachments.push(...(s.attachment_files || []));
      renderSkillAttachments();
    }).catch((e) => {
      setSkillEditorStatus("\u52A0\u8F7D\u5931\u8D25: " + e.message, "error");
    });
  } else {
    skillEditorTitle.textContent = "\u521B\u5EFA Skill";
    skillNameInput.value = "";
    skillNameInput.disabled = false;
    skillDescInput.value = "";
    skillVersionInput.value = "1.0.0";
    skillAuthorInput.value = "";
    skillTagsInput.value = "";
    skillContentInput.value = "";
    skillEnableCheck.checked = true;
    state.editingSkillAttachments.length = 0;
    renderSkillAttachments();
  }
  setSkillEditorStatus("");
  skillEditorOverlay.hidden = false;
}

function closeSkillEditor() {
  skillEditorOverlay.hidden = true;
  state.editingSkillName = "";
  state.editingSkillAttachments.length = 0;
}

function renderSkillAttachments() {
  if (!skillAttachmentsList) return;
  skillAttachmentsList.innerHTML = "";
  state.editingSkillAttachments.forEach((fname) => {
    const chip = document.createElement("span");
    chip.className = "skill-attachment-item";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = fname;
    const delBtn = document.createElement("button");
    delBtn.textContent = "\u00D7";
    delBtn.title = "\u5220\u9664\u9644\u4EF6";
    delBtn.addEventListener("click", async () => {
      if (!await showConfirm("\u786E\u5B9A\u5220\u9664\u9644\u4EF6 " + fname + " \uFF1F")) return;
      try {
        await api("/api/skills/" + encodeURIComponent(state.editingSkillName) + "/attachments/" + encodeURIComponent(fname), { method: "DELETE" });
        const idx = state.editingSkillAttachments.indexOf(fname);
        if (idx >= 0) state.editingSkillAttachments.splice(idx, 1);
        renderSkillAttachments();
        setSkillEditorStatus("\u9644\u4EF6\u5DF2\u5220\u9664", "success");
      } catch (e) {
        setSkillEditorStatus("\u5220\u9664\u5931\u8D25: " + e.message, "error");
      }
    });
    chip.appendChild(nameSpan);
    chip.appendChild(delBtn);
    skillAttachmentsList.appendChild(chip);
  });
}

async function saveSkill() {
  const name = (skillNameInput.value || "").trim();
  if (!name) {
    setSkillEditorStatus("\u540D\u79F0\u4E0D\u80FD\u4E3A\u7A7A", "error");
    return;
  }
  setSkillEditorStatus("\u6B63\u5728\u4FDD\u5B58...", "");
  const formData = new FormData();
  formData.append("name", name);
  formData.append("description", skillDescInput.value);
  formData.append("content", skillContentInput.value);
  formData.append("version", skillVersionInput.value);
  formData.append("author", skillAuthorInput.value);
  formData.append("tags", skillTagsInput.value);
  formData.append("enable", skillEnableCheck.checked ? "true" : "false");

  try {
    await api("/api/skills", { method: "POST", body: formData });
    if (state.editingSkillName && state.editingSkillName !== name) {
      try { await api("/api/skills/" + encodeURIComponent(state.editingSkillName), { method: "DELETE" }); } catch {}
    }
    setSkillEditorStatus("\u4FDD\u5B58\u6210\u529F", "success");
    state.editingSkillName = name;
    skillNameInput.disabled = true;
    await renderSkills();
  } catch (e) {
    setSkillEditorStatus("\u4FDD\u5B58\u5931\u8D25: " + e.message, "error");
  }
}

async function deleteSkill(name) {
  if (!await showConfirm("\u786E\u5B9A\u5220\u9664 Skill \"" + name + "\" \u53CA\u5176\u6240\u6709\u9644\u4EF6\uFF1F\u6B64\u64CD\u4F5C\u4E0D\u53EF\u6062\u590D\u3002")) return;
  try {
    await api("/api/skills/" + encodeURIComponent(name), { method: "DELETE" });
    await renderSkills();
    const setStatus = (await import('./settings.js')).setStatus;
    if (setStatus) setStatus("Skill \u5DF2\u5220\u9664", "success");
  } catch (e) {
    console.error("\u5220\u9664 Skill \u5931\u8D25:", e);
  }
}

async function renderSkills() {
  if (!skillsListEl) return;
  try {
    const res = await api("/api/skills");
    state.cachedSkills.length = 0;
    state.cachedSkills.push(...(res.skills || []));
  } catch (e) {
    skillsListEl.innerHTML = '<p style="color:#dc2626;">\u52A0\u8F7D Skills \u5931\u8D25: ' + escapeHtml(e.message) + '</p>';
    return;
  }

  skillsListEl.innerHTML = "";
  if (state.cachedSkills.length === 0) {
    skillsListEl.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:2rem;">\u6682\u65E0 Skill\u3002<br>\u70B9\u51FB"+ \u521B\u5EFA Skill"\u5F00\u59CB\u521B\u5EFA\u4F60\u7684\u7B2C\u4E00\u4E2A\u64CD\u4F5C\u6307\u5357\u3002</p>';
    return;
  }

  state.cachedSkills.forEach((skill) => {
    const card = document.createElement("div");
    card.className = "skill-card";

    const header = document.createElement("div");
    header.className = "skill-card-header";
    const h4 = document.createElement("h4");
    h4.textContent = skill.name;
    if (skill.enable === false) {
      const badge = document.createElement("span");
      badge.style.cssText = "font-size:0.65rem;color:#dc2626;background:rgba(220,38,38,0.1);padding:0.1rem 0.4rem;border-radius:999px;margin-left:0.4rem;font-weight:400;";
      badge.textContent = "\u5DF2\u7981\u7528";
      h4.appendChild(badge);
    }
    const actions = document.createElement("div");
    actions.className = "skill-card-actions";
    const editBtn = document.createElement("button");
    editBtn.className = "btn btn-secondary";
    editBtn.style.cssText = "padding:0.2rem 0.5rem;font-size:0.75rem;";
    editBtn.textContent = "\u7F16\u8F91";
    editBtn.addEventListener("click", () => openSkillEditor(skill.name));
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-danger";
    delBtn.style.cssText = "padding:0.2rem 0.5rem;font-size:0.75rem;";
    delBtn.textContent = "\u5220\u9664";
    delBtn.addEventListener("click", () => deleteSkill(skill.name));
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    header.appendChild(h4);
    header.appendChild(actions);

    const desc = document.createElement("div");
    desc.className = "skill-card-desc";
    desc.textContent = skill.description || "(\u65E0\u63CF\u8FF0)";

    const meta = document.createElement("div");
    meta.className = "skill-card-meta";
    meta.innerHTML = (skill.version ? '<span>v' + escapeHtml(skill.version) + '</span>' : '') +
      (skill.author ? '<span>by ' + escapeHtml(skill.author) + '</span>' : '');

    const tagsWrap = document.createElement("div");
    tagsWrap.className = "skill-card-tags";
    (skill.tags || []).forEach((tag) => {
      const tagEl = document.createElement("span");
      tagEl.className = "skill-tag";
      tagEl.textContent = tag;
      tagsWrap.appendChild(tagEl);
    });

    let attachWrap = null;
    if (skill.attachment_files && skill.attachment_files.length > 0) {
      attachWrap = document.createElement("div");
      attachWrap.className = "skill-card-attachments";
      skill.attachment_files.forEach((fname) => {
        const chip = document.createElement("span");
        chip.className = "skill-attachment-chip";
        chip.textContent = fname;
        attachWrap.appendChild(chip);
      });
    }

    card.appendChild(header);
    card.appendChild(desc);
    card.appendChild(meta);
    card.appendChild(tagsWrap);
    if (attachWrap) card.appendChild(attachWrap);
    skillsListEl.appendChild(card);
  });
}

function bindSkillEditorEvents() {
  const addSkillBtn = $("addSkillBtn");
  if (addSkillBtn) addSkillBtn.addEventListener("click", () => openSkillEditor(""));
  if (skillEditorClose) skillEditorClose.addEventListener("click", closeSkillEditor);
  if (skillEditorCancel) skillEditorCancel.addEventListener("click", closeSkillEditor);
  if (skillEditorOverlay) {
    skillEditorOverlay.addEventListener("click", (e) => {
      if (e.target === skillEditorOverlay) closeSkillEditor();
    });
  }
  if (skillEditorSave) skillEditorSave.addEventListener("click", saveSkill);

  const skillEnableLabel = $("skillEnableLabel");
  if (skillEnableLabel && skillEnableCheck) {
    skillEnableLabel.addEventListener("click", () => { skillEnableCheck.click(); });
  }

  if (skillFileInput) {
    skillFileInput.addEventListener("change", async () => {
      if (!state.editingSkillName) {
        setSkillEditorStatus("\u8BF7\u5148\u4FDD\u5B58 Skill \u540E\u518D\u4E0A\u4F20\u9644\u4EF6", "error");
        skillFileInput.value = "";
        return;
      }
      const files = skillFileInput.files;
      if (!files || files.length === 0) return;
      setSkillEditorStatus("\u6B63\u5728\u4E0A\u4F20...", "");
      let successCount = 0;
      let failCount = 0;
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        try {
          await api("/api/skills/" + encodeURIComponent(state.editingSkillName) + "/attachments", { method: "POST", body: fd });
          if (!state.editingSkillAttachments.includes(file.name)) {
            state.editingSkillAttachments.push(file.name);
          }
          successCount++;
        } catch {
          failCount++;
        }
      }
      skillFileInput.value = "";
      renderSkillAttachments();
      if (failCount === 0) {
        setSkillEditorStatus("\u4E0A\u4F20\u6210\u529F " + successCount + " \u4E2A\u6587\u4EF6", "success");
      } else {
        setSkillEditorStatus("\u4E0A\u4F20: " + successCount + " \u6210\u529F, " + failCount + " \u5931\u8D25", "error");
      }
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && skillEditorOverlay && !skillEditorOverlay.hidden) {
      const settingsOverlay = $("settingsOverlay");
      if (settingsOverlay && !settingsOverlay.hidden) {
        closeSkillEditor();
      }
    }
  });
}

export {
  renderSkills, openSkillEditor, closeSkillEditor,
  saveSkill, deleteSkill, renderSkillAttachments,
  setSkillEditorStatus, bindSkillEditorEvents,
};
