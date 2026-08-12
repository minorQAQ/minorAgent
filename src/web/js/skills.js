// skills.js -- Skills 管理面板（创建/编辑/删除/导入 zip 或文件夹）
// 导入流程：前端先解析（zip 走后端 /api/skills/parse，文件夹纯前端解析），
// 填充编辑器并展示附件树（一级子目录，不深入展开），点击保存后才落盘。

import { $, escapeHtml, withClickGuard } from './utils.js';
import { showConfirm } from './dialog.js';
import { api } from './api.js';
import { state } from './state.js';

const skillsListEl = $("skillsList");
const skillEditorOverlay = $("skillEditorOverlay");
const skillEditorTitle = $("skillEditorTitle");
const skillNameInput = $("skillNameInput");
const skillDescInput = $("skillDescInput");
const skillTagsInput = $("skillTagsInput");
const skillContentInput = $("skillContentInput");
const skillAttachmentsList = $("skillAttachmentsList");
const skillFileInput = $("skillFileInput");
const skillEditorStatus = $("skillEditorStatus");
const skillEditorSave = $("skillEditorSave");
const skillEditorCancel = $("skillEditorCancel");
const skillEditorClose = $("skillEditorClose");
const skillEnableCheck = $("skillEnableCheck");

// 导入临时状态：kind = "zip" | "folder"；folder 时 files 为 {相对路径: File}
let _pendingImport = null;

function setSkillEditorStatus(msg, type) {
  if (!skillEditorStatus) return;
  skillEditorStatus.textContent = msg;
  skillEditorStatus.className = "skill-editor-status" + (type ? " " + type : "");
}

function openSkillEditor(skillNameToEdit) {
  state.editingSkillName = skillNameToEdit || "";
  state.editingSkillAttachments.length = 0;
  _pendingImport = null;

  if (state.editingSkillName) {
    skillEditorTitle.textContent = "编辑 Skill: " + state.editingSkillName;
    skillNameInput.value = state.editingSkillName;
    skillNameInput.disabled = true;
    api("/api/skills/" + encodeURIComponent(state.editingSkillName)).then((res) => {
      const s = res.skill;
      skillDescInput.value = s.description || "";
      skillTagsInput.value = (s.tags || []).join(", ");
      skillContentInput.value = s.content || "";
      skillEnableCheck.checked = s.enable !== false;
      state.editingSkillAttachments.push(...(s.attachment_files || []));
      renderSkillAttachments();
    }).catch((e) => {
      setSkillEditorStatus("加载失败: " + e.message, "error");
    });
  } else {
    skillEditorTitle.textContent = "创建 Skill";
    skillNameInput.value = "";
    skillNameInput.disabled = false;
    skillDescInput.value = "";
    skillTagsInput.value = "";
    skillContentInput.value = "";
    skillEnableCheck.checked = true;
    renderSkillAttachments();
  }
  setSkillEditorStatus("");
  skillEditorOverlay.hidden = false;
}

function closeSkillEditor() {
  skillEditorOverlay.hidden = true;
  state.editingSkillName = "";
  state.editingSkillAttachments.length = 0;
  _pendingImport = null;
}

/** 渲染附件 chips；导入预览模式下：zip 只读展示，folder 可移除 */
function renderSkillAttachments() {
  if (!skillAttachmentsList) return;
  skillAttachmentsList.innerHTML = "";
  state.editingSkillAttachments.forEach((fname) => {
    const chip = document.createElement("span");
    chip.className = "skill-attachment-item";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = fname;
    chip.appendChild(nameSpan);
    const isFolderPreview = _pendingImport && _pendingImport.kind === "folder";
    const isZipPreview = _pendingImport && _pendingImport.kind === "zip";
    if (isZipPreview) {
      // zip 导入预览：附件随包原样落盘，不可单独删除
      chip.title = "导入后随 zip 原样保存";
      skillAttachmentsList.appendChild(chip);
      return;
    }
    const delBtn = document.createElement("button");
    delBtn.textContent = "\u00D7";
    delBtn.title = "删除附件";
    delBtn.addEventListener("click", async () => {
      if (!await showConfirm("确定删除附件 " + fname + " ？")) return;
      if (isFolderPreview && _pendingImport) {
        // 文件夹导入预览：仅从待上传集合移除
        delete _pendingImport.files[fname];
        const idx = state.editingSkillAttachments.indexOf(fname);
        if (idx >= 0) state.editingSkillAttachments.splice(idx, 1);
        renderSkillAttachments();
        return;
      }
      try {
        await api("/api/skills/" + encodeURIComponent(state.editingSkillName) + "/attachments/" + encodeURIComponent(fname), { method: "DELETE" });
        const idx = state.editingSkillAttachments.indexOf(fname);
        if (idx >= 0) state.editingSkillAttachments.splice(idx, 1);
        renderSkillAttachments();
        setSkillEditorStatus("附件已删除", "success");
      } catch (e) {
        setSkillEditorStatus("删除失败: " + e.message, "error");
      }
    });
    chip.appendChild(delBtn);
    skillAttachmentsList.appendChild(chip);
  });
}

async function saveSkill() {
  const name = (skillNameInput.value || "").trim();
  if (!name) {
    setSkillEditorStatus("名称不能为空", "error");
    return;
  }
  setSkillEditorStatus("正在保存...", "");
  const tags = skillTagsInput.value;
  const enable = skillEnableCheck.checked ? "true" : "false";

  // zip 导入：整包提交给 /api/skills/import（附件保持原相对路径）
  if (_pendingImport && _pendingImport.kind === "zip" && _pendingImport.file) {
    const fd = new FormData();
    fd.append("file", _pendingImport.file);
    fd.append("name", name);
    fd.append("description", skillDescInput.value);
    fd.append("content", skillContentInput.value);
    fd.append("tags", tags);
    fd.append("enable", enable);
    try {
      await api("/api/skills/import", { method: "POST", body: fd });
      setSkillEditorStatus("导入成功", "success");
      state.editingSkillName = name;
      skillNameInput.disabled = true;
      _pendingImport = null;
      await renderSkills();
      return;
    } catch (e) {
      setSkillEditorStatus("导入失败: " + e.message, "error");
      return;
    }
  }

  const formData = new FormData();
  formData.append("name", name);
  formData.append("description", skillDescInput.value);
  formData.append("content", skillContentInput.value);
  formData.append("tags", tags);
  formData.append("enable", enable);

  try {
    await api("/api/skills", { method: "POST", body: formData });
    if (state.editingSkillName && state.editingSkillName !== name) {
      try { await api("/api/skills/" + encodeURIComponent(state.editingSkillName), { method: "DELETE" }); } catch {}
    }
    // 文件夹导入：逐个上传附件（filename 携带相对路径，如 templates/x.py）
    if (_pendingImport && _pendingImport.kind === "folder" && _pendingImport.files) {
      for (const [rel, file] of Object.entries(_pendingImport.files)) {
        const fd = new FormData();
        fd.append("file", file, rel);
        await api("/api/skills/" + encodeURIComponent(name) + "/attachments", { method: "POST", body: fd });
      }
    }
    setSkillEditorStatus("保存成功", "success");
    state.editingSkillName = name;
    skillNameInput.disabled = true;
    _pendingImport = null;
    await renderSkills();
  } catch (e) {
    setSkillEditorStatus("保存失败: " + e.message, "error");
  }
}

async function deleteSkill(name) {
  if (!await showConfirm("确定删除 Skill \"" + name + "\" 及其所有附件？此操作不可恢复。")) return;
  try {
    await api("/api/skills/" + encodeURIComponent(name), { method: "DELETE" });
    await renderSkills();
    const setStatus = (await import('./settings.js')).setStatus;
    if (setStatus) setStatus("Skill 已删除", "success");
  } catch (e) {
    console.error("删除 Skill 失败:", e);
  }
}

async function renderSkills() {
  if (!skillsListEl) return;
  try {
    const res = await api("/api/skills");
    state.cachedSkills.length = 0;
    state.cachedSkills.push(...(res.skills || []));
  } catch (e) {
    skillsListEl.innerHTML = '<p style="color:#dc2626;">加载 Skills 失败: ' + escapeHtml(e.message) + '</p>';
    return;
  }

  skillsListEl.innerHTML = "";
  if (state.cachedSkills.length === 0) {
    skillsListEl.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:2rem;">暂无 Skill。<br>点击"+ 创建 Skill"或"导入 Skill"开始。</p>';
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
      badge.textContent = "已禁用";
      h4.appendChild(badge);
    }
    const actions = document.createElement("div");
    actions.className = "skill-card-actions";
    const editBtn = document.createElement("button");
    editBtn.className = "btn btn-secondary";
    editBtn.style.cssText = "padding:0.2rem 0.5rem;font-size:0.75rem;";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => openSkillEditor(skill.name));
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-danger";
    delBtn.style.cssText = "padding:0.2rem 0.5rem;font-size:0.75rem;";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", () => deleteSkill(skill.name));
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    header.appendChild(h4);
    header.appendChild(actions);

    const desc = document.createElement("div");
    desc.className = "skill-card-desc";
    desc.textContent = skill.description || "(无描述)";

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
    card.appendChild(tagsWrap);
    if (attachWrap) card.appendChild(attachWrap);
    skillsListEl.appendChild(card);
  });
}

// ---------- 导入 ----------

/** 解析 skill.md 头部 frontmatter（仅 name/description，其余丢弃；支持 > 折叠多行） */
function parseSkillMdFrontmatter(md) {
  let name = "";
  let description = "";
  let body = md;
  const m = md.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (m) {
    body = md.slice(m[0].length);
    const collected = {};
    let curKey = null;
    m[1].split(/\r?\n/).forEach((line) => {
      if (!line.trim()) return;
      const kv = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
      if (kv) {
        curKey = kv[1].toLowerCase();
        collected[curKey] = [kv[2].trim()];
      } else if (curKey === "name" || curKey === "description") {
        if (line.startsWith(" ") || line.startsWith("\t")) {
          (collected[curKey] || (collected[curKey] = [])).push(line.trim());
        }
      }
    });
    const nameVals = (collected.name || []).filter(Boolean);
    if (nameVals.length) name = nameVals[0].replace(/^["']|["']$/g, "");
    const descVals = (collected.description || []).filter(Boolean);
    if (descVals.length) description = descVals.join(" ").replace(/^["']|["']$/g, "");
  }
  return { name, description, body };
}

/** 打开导入菜单（zip / 文件夹 二选一） */
function bindImportMenu() {
  const importBtn = $("importSkillBtn");
  const zipInput = $("importSkillZipInput");
  const folderInput = $("importSkillFolderInput");
  if (!importBtn) return;
  let menu = null;

  const closeMenu = () => { if (menu && menu.parentNode) menu.parentNode.removeChild(menu); menu = null; };
  document.addEventListener("click", (e) => {
    if (menu && !menu.contains(e.target) && e.target !== importBtn) closeMenu();
  });

  importBtn.addEventListener("click", withClickGuard((e) => {
    e.stopPropagation();
    if (menu) { closeMenu(); return; }
    menu = document.createElement("div");
    menu.className = "skill-import-menu";
    const zipItem = document.createElement("button");
    zipItem.type = "button";
    zipItem.textContent = "从 zip 导入";
    zipItem.addEventListener("click", (ev) => {
      ev.stopPropagation();
      closeMenu();
      if (zipInput) zipInput.click();
    });
    const folderItem = document.createElement("button");
    folderItem.type = "button";
    folderItem.textContent = "从文件夹导入";
    folderItem.addEventListener("click", (ev) => {
      ev.stopPropagation();
      closeMenu();
      if (folderInput) folderInput.click();
    });
    menu.appendChild(zipItem);
    menu.appendChild(folderItem);
    importBtn.parentNode.appendChild(menu);
  }));

  // zip：后端解析（不落盘），填充编辑器 + 展示附件树
  if (zipInput) {
    zipInput.addEventListener("change", withClickGuard(async () => {
      const file = zipInput.files && zipInput.files[0];
      zipInput.value = "";
      if (!file) return;
      setSkillEditorStatus("正在解析 zip...", "");
      try {
        const fd = new FormData();
        fd.append("file", file);
        const res = await api("/api/skills/parse", { method: "POST", body: fd });
        if (!res.found || !res.skill) {
          setSkillEditorStatus(res.error || "未找到 skill.md/SKILL.md", "error");
          return;
        }
        const s = res.skill;
        openSkillEditor("");
        skillNameInput.value = s.name || "";
        skillDescInput.value = s.description || "";
        skillContentInput.value = s.content || "";
        state.editingSkillAttachments.length = 0;
        state.editingSkillAttachments.push(...(s.attachments || []));
        _pendingImport = { kind: "zip", file, attachments: s.attachments || [] };
        renderSkillAttachments();
        setSkillEditorStatus("解析完成：请核对名称/描述/内容后点击保存（附件随 zip 原样保存）", "");
        skillEditorOverlay.hidden = false;
      } catch (err) {
        setSkillEditorStatus("解析失败: " + (err.message || err), "error");
      }
    }));
  }

  // 文件夹：纯前端解析（webkitRelativePath）
  if (folderInput) {
    folderInput.addEventListener("change", withClickGuard(async () => {
      const files = Array.from(folderInput.files || []);
      folderInput.value = "";
      if (files.length === 0) return;

      // 定位一级目录下的 skill.md/SKILL.md
      let skillMdFile = null;
      const mdFiles = files.filter((f) => f.webkitRelativePath.split("/").length <= 2 && /^skill\.md$/i.test(f.name));
      if (mdFiles.length === 0) {
        setSkillEditorStatus("未在一级子目录下找到 skill.md/SKILL.md", "error");
        return;
      }
      skillMdFile = mdFiles[0];
      const mdText = await skillMdFile.text();
      const { name, description, body } = parseSkillMdFrontmatter(mdText);

      // 附件：一级子目录下除 skill.md 之外的树（不深入展开，子文件夹折叠为 "文件夹名/"）
      const dirName = skillMdFile.webkitRelativePath.split("/")[0];
      const filesByRel = {};
      const seenFirstLevel = new Set();
      files.forEach((f) => {
        const parts = f.webkitRelativePath.split("/");
        if (parts[0] !== dirName) return;
        if (parts.length === 2 && /^skill\.md$/i.test(f.name)) return; // 跳过 skill.md
        if (parts.length === 2) {
          filesByRel[parts[1]] = f;
          seenFirstLevel.add(parts[1]);
        } else if (parts.length > 2) {
          // 子文件夹内的文件：折叠为 "子文件夹/" 一级展示，仍按完整相对路径上传
          filesByRel[parts.slice(1).join("/")] = f;
          seenFirstLevel.add(parts[1] + "/");
        }
      });

      openSkillEditor("");
      skillNameInput.value = name || dirName;
      skillDescInput.value = description || "";
      skillContentInput.value = body || "";
      state.editingSkillAttachments.length = 0;
      state.editingSkillAttachments.push(...Array.from(seenFirstLevel).sort());
      _pendingImport = { kind: "folder", files: filesByRel };
      renderSkillAttachments();
      setSkillEditorStatus("解析完成：请核对名称/描述/内容后点击保存（附件将上传到 skill 文件夹下）", "");
      skillEditorOverlay.hidden = false;
    }));
  }
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
  if (skillEditorSave) skillEditorSave.addEventListener("click", withClickGuard(saveSkill));

  const skillEnableLabel = $("skillEnableLabel");
  if (skillEnableLabel && skillEnableCheck) {
    skillEnableLabel.addEventListener("click", () => { skillEnableCheck.click(); });
  }

  if (skillFileInput) {
    skillFileInput.addEventListener("change", async () => {
      if (!state.editingSkillName) {
        setSkillEditorStatus("请先保存 Skill 后再上传附件", "error");
        skillFileInput.value = "";
        return;
      }
      const files = skillFileInput.files;
      if (!files || files.length === 0) return;
      setSkillEditorStatus("正在上传...", "");
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
        setSkillEditorStatus("上传成功 " + successCount + " 个文件", "success");
      } else {
        setSkillEditorStatus("上传: " + successCount + " 成功, " + failCount + " 失败", "error");
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
  setSkillEditorStatus, bindSkillEditorEvents, bindImportMenu,
};
