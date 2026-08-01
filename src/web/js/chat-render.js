// chat-render.js -- 消息渲染 / 流式输出 / 音频气泡（新版：无气泡 + 媒体行 + agent-run-block）

import { $, escapeHtml, getTextFromContent, getMediaParts, isAudioOnlyAssistantMessage, clamp, formatAudioDuration, getAudioBubbleWidth, codeBlockNode, inferUploadKind, dedupePendingFiles } from './utils.js';
import { state } from './state.js';
import {
  showImagePreview,
  renderUserFileCard,
  attachHorizontalScroll,
  showFilePreviewDialog,
} from './toolcalls.js';

let rollbackChatFn = null;
export function setRollbackChatFn(fn) { rollbackChatFn = fn; }

let renderPersistentToolCallsFn = null;

export function setRenderPersistentToolCalls(fn) { renderPersistentToolCallsFn = fn; }

const chatMessages = $("chatMessages");
const chatPlaceholder = $("chatPlaceholder");

function scrollChatToBottom() {
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function renderAttachmentChips() {
  const imagesArea = $("inputInlineImages");
  const chipsArea = $("inputInlineChips");
  const wrap = $("inputInlineArea");
  if (!imagesArea || !chipsArea || !wrap) return;

  // 去重（防御性：确保无重复条目）
  state.pendingFiles = dedupePendingFiles(state.pendingFiles);

  // 清除自身渲染的元素（非 ref 类型）
  imagesArea.querySelectorAll(".input-inline-img-thumb-wrap:not(.ref-img-thumb-wrap)").forEach((wrapEl) => {
    const imgEl = wrapEl.querySelector("img");
    if (imgEl && imgEl._blobUrl) URL.revokeObjectURL(imgEl._blobUrl);
    wrapEl.remove();
  });
  chipsArea.querySelectorAll(".chip, .chip--folder").forEach((el) => el.remove());
  chipsArea.querySelectorAll(".ref-chip").forEach((el) => el.remove());
  imagesArea.querySelectorAll(".ref-img-thumb-wrap").forEach((el) => el.remove());

  let hasContent = false;
  const imageFiles = [];
  const folderItems = [];
  const otherFiles = [];
  const refImages = [];
  const refFiles = [];
  const refFolderItems = [];

  state.pendingFiles.forEach((f, i) => {
    if (f.__isRef) {
      if (f.type === 'ref/image') refImages.push({ file: f, idx: i });
      else if (f.type === 'ref/folder') refFolderItems.push({ file: f, idx: i });
      else refFiles.push({ file: f, idx: i });
    } else {
      const kind = inferUploadKind(f);
      if (kind === "folder") folderItems.push({ file: f, idx: i });
      else if (kind === "image") imageFiles.push({ file: f, idx: i });
      else otherFiles.push({ file: f, idx: i });
    }
  });

  // 上传/拖放图片缩略图
  imageFiles.forEach(({ file, idx }) => {
    const url = URL.createObjectURL(file);
    const wrapEl = document.createElement("div");
    wrapEl.className = "input-inline-img-thumb-wrap";
    const img = document.createElement("img");
    img.className = "input-inline-img-thumb";
    img.src = url;
    img._blobUrl = url;
    img._pendingIdx = idx;
    img.title = file.name;
    img.addEventListener("click", () => {
      // 点击图片本身 → 打开预览浮窗
      showImagePreview(url);
    });
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "input-inline-img-del";
    delBtn.setAttribute("aria-label", "移除");
    delBtn.title = "移除";
    delBtn.textContent = "\u00D7";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.pendingFiles = state.pendingFiles.filter((_, j) => j !== idx);
      renderAttachmentChips();
    });
    wrapEl.appendChild(img);
    wrapEl.appendChild(delBtn);
    imagesArea.appendChild(wrapEl);
    hasContent = true;
  });

  // edit 模式拖拽的图片引用缩略图
  refImages.forEach(({ file, idx }) => {
    const wrapEl = document.createElement("div");
    wrapEl.className = "input-inline-img-thumb-wrap ref-img-thumb-wrap";
    const img = document.createElement("img");
    img.className = "input-inline-img-thumb ref-img-thumb";
    img.src = "";
    img.title = file.refName || file.name;
    img.addEventListener("click", () => {
      // 点击图片本身 → 打开预览浮窗（src 由 _loadRefImageSrc 异步加载）
      if (img.src && img.src !== location.href && !img.src.endsWith("/image/文档按钮.svg")) {
        showImagePreview(img.src);
      }
    });
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "input-inline-img-del";
    delBtn.setAttribute("aria-label", "移除");
    delBtn.title = "移除";
    delBtn.textContent = "\u00D7";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.pendingFiles = state.pendingFiles.filter((_, j) => j !== idx);
      if (file.refPath) {
        state.pendingRefs = state.pendingRefs.filter((r) => r.path !== file.refPath);
      }
      renderAttachmentChips();
    });
    wrapEl.appendChild(img);
    wrapEl.appendChild(delBtn);
    imagesArea.appendChild(wrapEl);
    hasContent = true;
    _loadRefImageSrc(img, file);
  });

  // 文件夹气泡
  folderItems.forEach(({ file, idx }) => {
    const chip = document.createElement("span");
    chip.className = "chip chip--folder";
    chip.innerHTML = `<img src="/image/文件夹.svg" alt="" class="chip-icon" /> ${escapeHtml(file.name)} <button type="button" aria-label="移除">\u00D7</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pendingFiles = state.pendingFiles.filter((_, j) => j !== idx);
      renderAttachmentChips();
    });
    chipsArea.appendChild(chip);
    hasContent = true;
  });

  // edit 模式拖拽的文件夹引用 chips（显示单个文件夹 UI，不展开内容）
  refFolderItems.forEach(({ file, idx }) => {
    const chip = document.createElement("span");
    chip.className = "ref-chip ref-chip--folder";
    chip.innerHTML = `<img src="/image/文件夹.svg" alt="" class="ref-chip-icon" /> <span class="ref-chip-label">${escapeHtml(file.refName || file.name)}</span> <button type="button" class="ref-chip-close" aria-label="移除">\u00D7</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pendingFiles = state.pendingFiles.filter((_, j) => j !== idx);
      if (file.refPath !== undefined) {
        state.pendingRefs = state.pendingRefs.filter((r) => !(r.isFolder && r.path === file.refPath));
      }
      renderAttachmentChips();
    });
    chipsArea.appendChild(chip);
    hasContent = true;
  });

  // 上传/拖放文件 chips
  otherFiles.forEach(({ file, idx }) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `<img src="/image/文档按钮.svg" alt="" class="chip-icon" /> ${escapeHtml(file.name)} <button type="button" aria-label="移除">\u00D7</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pendingFiles = state.pendingFiles.filter((_, j) => j !== idx);
      renderAttachmentChips();
    });
    chipsArea.appendChild(chip);
    hasContent = true;
  });

  // edit 模式拖拽的文件引用 chips
  refFiles.forEach(({ file, idx }) => {
    const chip = document.createElement("span");
    chip.className = "ref-chip";
    chip.innerHTML = `<img src="/image/文档按钮.svg" alt="" class="ref-chip-icon" /> <span class="ref-chip-label">${escapeHtml(file.refName || file.name)}</span> <button type="button" class="ref-chip-close" aria-label="移除">\u00D7</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pendingFiles = state.pendingFiles.filter((_, j) => j !== idx);
      if (file.refPath) {
        state.pendingRefs = state.pendingRefs.filter((r) => r.path !== file.refPath);
      }
      renderAttachmentChips();
    });
    chipsArea.appendChild(chip);
    hasContent = true;
  });

  if (hasContent || imagesArea.children.length > 0 || chipsArea.children.length > 0) {
    wrap.classList.add("has-content");
  } else {
    wrap.classList.remove("has-content");
  }
}

async function _loadRefImageSrc(img, file) {
  // 非 Electron 环境下无法读取文件，尝试直接用路径
  if (file.refPath && file.refPath.startsWith("data:")) {
    img.src = file.refPath;
    return;
  }
  try {
    const { readBinaryFile } = await import('./electron-api.js');
    if (file.refPath) {
      const res = await readBinaryFile(file.refPath, state._docRootPath);
      if (res && res.status === 'ok' && res.data) {
        img.src = `data:${res.mime || 'image/png'};base64,${res.data}`;
        return;
      }
    }
  } catch {}
  // 回退
  img.src = '/image/文档按钮.svg';
  img.style.width = '24px';
  img.style.height = '24px';
  img.style.objectFit = 'contain';
}

function renderMarkdownToFragment(text) {
  const raw = String(text ?? "");
  const html = window.marked
    ? window.marked.parse(raw, { breaks: false, gfm: true })
    : (() => { const s = String(raw); return escapeHtml(s).replace(/ /g, "&nbsp;").replace(/\t/g, "&nbsp;&nbsp;&nbsp;&nbsp;").replace(/\n/g, "<br>"); })();
  const safeHtml = window.DOMPurify ? window.DOMPurify.sanitize(html) : html;
  const tpl = document.createElement("template");
  tpl.innerHTML = safeHtml;

  tpl.content.querySelectorAll("pre code").forEach((codeEl) => {
    const pre = codeEl.parentElement;
    if (!pre) return;
    const rawCode = codeEl.textContent || "";
    const cls = codeEl.className || "";
    const m = cls.match(/language-([\w-]+)/);
    const wrap = codeBlockNode(m ? m[1] : "text", rawCode);
    pre.replaceWith(wrap);
  });
  return tpl.content.cloneNode(true);
}

function splitMarkdownStreamBlocks(text) {
  const raw = String(text ?? "");
  const lines = raw.split("\n");
  const blocks = [];
  let current = [];
  let inFence = false;

  function flushCurrent() {
    if (current.length === 0) return;
    blocks.push(current.join("\n"));
    current = [];
  }

  for (const line of lines) {
    const trimmed = line.trimStart();
    const isFence = trimmed.startsWith("```");

    if (isFence) {
      current.push(line);
      if (inFence) {
        flushCurrent();
        inFence = false;
      } else {
        flushCurrent();
        inFence = true;
        current = [line];
      }
      continue;
    }

    if (inFence) {
      current.push(line);
      continue;
    }

    if (line.trim() === "") {
      current.push(line);
      flushCurrent();
      continue;
    }

    const looksLikeList = /^\s*([-*+]\s|\d+\.\s|>\s)/.test(line);
    if (looksLikeList) {
      current.push(line);
      continue;
    }

    const prev = current[current.length - 1] || "";
    const prevLooksLikeList = /^\s*([-*+]\s|\d+\.\s|>\s)/.test(prev);
    if (prevLooksLikeList && line.trim() !== "") {
      current.push(line);
      continue;
    }

    current.push(line);
  }

  flushCurrent();
  return blocks;
}

function renderMarkdownBlock(text, isStreaming = false) {
  const raw = String(text ?? "");
  const d = document.createElement("div");
  d.className = "msg-prose markdown-body" + (isStreaming ? " markdown-body--streaming" : "");
  d.appendChild(renderMarkdownToFragment(raw));
  return d;
}

function fillAssistantBubbleImmediate(bubble, text) {
  const t = text == null ? "" : String(text);
  bubble.classList.add("msg-bubble--rich", "markdown-body");
  bubble.textContent = "";
  bubble.appendChild(renderMarkdownToFragment(t));
}

async function pseudoStreamAssistant(bubble, full) {
  const t = full == null ? "" : String(full);
  bubble.classList.add("msg-bubble--rich", "markdown-body");
  bubble.textContent = "";

  const n = t.length;
  const charsPerSec = 85;
  const totalMs = Math.min(12000, Math.max(400, (n / charsPerSec) * 1000));
  const t0 = performance.now();
  let lastSnapshot = "";

  return new Promise((resolve) => {
    function frame(now) {
      const elapsed = now - t0;
      const p = Math.min(1, elapsed / totalMs);
      const k = Math.min(n, Math.floor(p * n));
      const snapshot = t.slice(0, k);

      if (snapshot !== lastSnapshot) {
        lastSnapshot = snapshot;
        const blocks = splitMarkdownStreamBlocks(snapshot);
        bubble.textContent = "";
        blocks.forEach((block, idx) => {
          const isLast = idx === blocks.length - 1;
          const stillOpenFence = (block.match(/```/g) || []).length % 2 === 1;
          bubble.appendChild(renderMarkdownBlock(block, isLast || stillOpenFence));
        });
        scrollChatToBottom();
      }

      if (p < 1) {
        requestAnimationFrame(frame);
      } else {
        bubble.textContent = "";
        bubble.appendChild(renderMarkdownToFragment(t));
        scrollChatToBottom();
        resolve();
      }
    }
    requestAnimationFrame(frame);
  });
}

function renderAudioBubble(part, options = {}) {
  const {
    autoplay = false,
    compact = false,
    messageMeta = null,
    role = "assistant",
    allowAutoplay = false,
  } = options;

  const wrap = document.createElement("div");
  wrap.className = "audio-pill-wrap" + (compact ? " audio-pill-wrap--compact" : "") + (role === "user" ? " audio-pill-wrap--user" : " audio-pill-wrap--assistant");

  const durationSeconds = part && part.duration_seconds != null
    ? part.duration_seconds
    : (messageMeta && messageMeta.audio_duration_seconds != null ? messageMeta.audio_duration_seconds : null);
  const durationLabel = formatAudioDuration(durationSeconds);
  const bubbleWidth = getAudioBubbleWidth(durationSeconds);
  const displayName = role === "user" ? "语音" : (part.name || "语音消息");

  const button = document.createElement("button");
  button.type = "button";
  button.className = `audio-pill audio-pill--${role}`;
  if (bubbleWidth) button.style.width = bubbleWidth;
  button.innerHTML = `
    <span class="audio-pill-progress" aria-hidden="true"></span>
    <span class="audio-pill-tail" aria-hidden="true"></span>
    <span class="audio-pill-main">
      <span class="audio-pill-icon">\u25B6</span>
      <span class="audio-pill-wave" aria-hidden="true">
        <span></span><span></span><span></span><span></span><span></span><span></span>
      </span>
      <span class="audio-pill-text${role === "user" ? " audio-pill-text--muted" : ""}">${escapeHtml(displayName)}</span>
    </span>
    <span class="audio-pill-side">
      <span class="audio-pill-duration">0.0\u2033 / ${escapeHtml(durationLabel || "语音")}</span>
    </span>
  `;

  const audio = new Audio(part.url);
  audio.preload = "metadata";
  const iconEl = button.querySelector(".audio-pill-icon");
  const durationEl = button.querySelector(".audio-pill-duration");
  const progressEl = button.querySelector(".audio-pill-progress");
  let resolvedDuration = Number(durationSeconds);

  function updateProgressUi() {
    const total = Number.isFinite(resolvedDuration) && resolvedDuration > 0 ? resolvedDuration : audio.duration;
    const current = audio.currentTime || 0;
    const currentLabel = formatAudioDuration(current) || "0.0\u2033";
    const totalLabel = formatAudioDuration(total) || durationLabel || "语音";
    if (durationEl) durationEl.textContent = role === "user" ? totalLabel : `${currentLabel} / ${totalLabel}`;
    if (progressEl && Number.isFinite(total) && total > 0) {
      const percent = clamp((current / total) * 100, 0, 100);
      progressEl.style.setProperty("--audio-progress", `${percent}%`);
    }
  }

  function syncDurationFromAudio() {
    const runtimeDuration = audio.duration;
    if (Number.isFinite(runtimeDuration) && runtimeDuration > 0) {
      resolvedDuration = runtimeDuration;
      const runtimeWidth = getAudioBubbleWidth(runtimeDuration);
      if (runtimeWidth) button.style.width = runtimeWidth;
    }
    updateProgressUi();
  }

  function setPlayingUi(playing) {
    button.classList.toggle("is-playing", playing);
    if (iconEl) iconEl.textContent = playing ? "\u275A\u275A" : "\u25B6";
    button.setAttribute("aria-pressed", playing ? "true" : "false");
    button.title = playing ? "暂停播放" : "播放语音";
    if (!playing && state.activeAudioController && state.activeAudioController.audio === audio) {
      state.activeAudioController = null;
    }
  }

  audio.addEventListener("loadedmetadata", syncDurationFromAudio);
  audio.addEventListener("durationchange", syncDurationFromAudio);
  audio.addEventListener("timeupdate", updateProgressUi);
  audio.addEventListener("play", () => {
    if (state.activeAudioController && state.activeAudioController.audio !== audio) {
      try { state.activeAudioController.audio.pause(); } catch { /* ignore */ }
    }
    state.activeAudioController = { audio, button };
    setPlayingUi(true);
    updateProgressUi();
  });
  audio.addEventListener("pause", () => {
    setPlayingUi(false);
    updateProgressUi();
  });
  audio.addEventListener("ended", () => {
    audio.currentTime = 0;
    setPlayingUi(false);
    updateProgressUi();
  });

  button.addEventListener("click", async () => {
    try {
      if (!audio.paused) {
        audio.pause();
        return;
      }
      if (state.activeAudioController && state.activeAudioController.audio !== audio) {
        try { state.activeAudioController.audio.pause(); } catch { /* ignore */ }
      }
      await audio.play();
    } catch { /* ignore */ }
  });

  wrap.appendChild(button);
  updateProgressUi();

  const shouldAutoplay = allowAutoplay !== false && Boolean(
    autoplay || part.autoplay || (messageMeta && messageMeta.autoplay)
  );

  if (shouldAutoplay) {
    queueMicrotask(async () => {
      try {
        if (state.activeAudioController && state.activeAudioController.audio !== audio) {
          try { state.activeAudioController.audio.pause(); } catch { /* ignore */ }
        }
        await audio.play();
      } catch {
        setPlayingUi(false);
        updateProgressUi();
      }
    });
  }

  return wrap;
}

/* ===== 用户图片缩略图（用于 user-media-row） ===== */
function renderUserImageThumb(url, name) {
  const img = document.createElement("img");
  img.className = "user-media-thumb";
  img.src = url;
  img.alt = name || "图片";
  img.title = name || "点击查看大图";
  img.loading = "lazy";
  img.addEventListener("click", (e) => {
    e.stopPropagation();
    showImagePreview(url);
  });
  // 自定义拖拽：阻止浏览器创建通用名称的 File，传递原始信息
  img.addEventListener("dragstart", (e) => {
    e.dataTransfer.clearData();  // 清除浏览器默认数据（会生成名为 "image.png" 的 File）
    e.dataTransfer.setData("application/x-chat-image", url);
    e.dataTransfer.setData("text/plain", name || url.split("/").pop() || "图片");
    e.dataTransfer.effectAllowed = "copy";
  });
  return img;
}

/* ===== 用户媒体行：图片或文件水平排列 + 渐变隐藏 + 滚轮滑动 ===== */
function renderUserMediaRow(items, options = {}) {
  if (!items || items.length === 0) return null;
  const row = document.createElement("div");
  row.className = "user-media-row";
  items.forEach((item) => row.appendChild(item));
  attachHorizontalScroll(row);
  return row;
}

/* ===== 从消息 content 中提取图片/文件/文本分组 ===== */
function groupUserContentParts(content) {
  const images = [];
  const files = [];
  const texts = [];
  if (Array.isArray(content)) {
    content.forEach((part) => {
      if (!part) return;
      if (part.type === "text" && typeof part.text === "string") {
        if (part.text.trim()) texts.push(part.text);
      } else if (part.type === "image" && part.url) {
        images.push(part);
      } else if (part.type === "file") {
        files.push(part);
      } else if (part.type === "audio") {
        // 用户上传的音频文件按普通文件展示
        files.push(part);
      }
    });
  } else if (typeof content === "string") {
    if (content.trim()) texts.push(content);
  }
  return { images, files, texts };
}

/* ===== 渲染用户消息内容（无气泡，文本 + 图片行 + 文件行 + 文件夹行） ===== */
function renderUserContent(content, baseOptions = {}) {
  const wrap = document.createElement("div");
  wrap.className = "msg-bubble msg-bubble--user";
  const { images, files, texts } = groupUserContentParts(content);

  // 文本：提取 @folder: 和 @file: 引用，渲染为独立气泡
  const folderRefs = [];
  const fileRefs = [];
  const cleanTexts = [];
  if (texts.length > 0) {
    const fullText = texts.join("\n");
    const refRegex = /@(folder|file):([^\n]+)/g;
    let lastIndex = 0;
    let match;
    while ((match = refRegex.exec(fullText)) !== null) {
      // 收集引用前的文本
      const before = fullText.substring(lastIndex, match.index).trim();
      if (before) cleanTexts.push(before);
      lastIndex = refRegex.lastIndex;
      const refType = match[1]; // "folder" or "file"
      const refPath = match[2].trim();
      if (refType === "folder") {
        folderRefs.push(refPath);
      } else {
        fileRefs.push(refPath);
      }
    }
    // 收集剩余文本
    const after = fullText.substring(lastIndex).trim();
    if (after) cleanTexts.push(after);
  }

  // 渲染剩余文本（去除 @folder:/@file: 引用后）
  if (cleanTexts.length > 0) {
    const textEl = document.createElement("div");
    textEl.className = "msg-text";
    textEl.textContent = cleanTexts.join("\n");
    wrap.appendChild(textEl);
  }

  // 去重：避免同一文件既作为附件 part 又作为 @file:/@folder: 文本引用重复渲染。
  // 同名（按 basename 大小写无关）只保留首个：图片 > 文件 > @file: 引用卡片。
  // 这样「上传/拖拽的文件 + 同名 @file: 引用」不会出现两个一模一样的文件 UI。
  const _basename = (p) => (p || '').replace(/[\\/]/g, '/').split('/').pop() || '';
  const _renderedNames = new Set();
  const dedupedImages = images.filter((p) => {
    const key = (p.name || _basename(p.url) || '').toLowerCase();
    if (!key || _renderedNames.has(key)) return false;
    _renderedNames.add(key);
    return true;
  });
  const dedupedFiles = files.filter((p) => {
    const key = (p.name || _basename(p.url) || '').toLowerCase();
    if (!key || _renderedNames.has(key)) return false;
    _renderedNames.add(key);
    return true;
  });
  const dedupedFileRefs = fileRefs.filter((fp) => {
    const key = _basename(fp).toLowerCase();
    if (!key || _renderedNames.has(key)) return false;
    _renderedNames.add(key);
    return true;
  });

  // 图片行
  if (dedupedImages.length > 0) {
    const imgItems = dedupedImages.map((p) => renderUserImageThumb(p.url, p.name));
    const row = renderUserMediaRow(imgItems);
    if (row) wrap.appendChild(row);
  }

  // 文件行
  if (dedupedFiles.length > 0) {
    const fileItems = dedupedFiles.map((p) => renderUserFileCard(p.url, p.name, { preview: true }));
    const row = renderUserMediaRow(fileItems);
    if (row) wrap.appendChild(row);
  }

  // 文件夹引用气泡（@folder:path）
  if (folderRefs.length > 0) {
    const folderItems = folderRefs.map((fp) => renderUserFolderRefCard(fp));
    const row = renderUserMediaRow(folderItems);
    if (row) wrap.appendChild(row);
  }

  // 文件引用气泡（@file:path）
  if (dedupedFileRefs.length > 0) {
    const fileRefItems = dedupedFileRefs.map((fp) => renderUserFileRefCard(fp));
    const row = renderUserMediaRow(fileRefItems);
    if (row) wrap.appendChild(row);
  }

  return wrap;
}

/** 渲染用户消息中的文件夹引用卡片 */
function renderUserFolderRefCard(folderPath) {
  const card = document.createElement("div");
  card.className = "user-file-card user-folder-card";
  card.draggable = true;
  card.title = folderPath;

  // 拖拽：支持从聊天区拖拽文件夹引用到输入区
  card.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("application/doc-path", folderPath);
    e.dataTransfer.setData("application/doc-folder", "1");
    e.dataTransfer.setData("text/plain", folderPath.replace(/\\/g, "/").split("/").pop() || folderPath);
    e.dataTransfer.effectAllowed = "copy";
  });

  const icon = document.createElement("img");
  icon.className = "user-file-card-icon";
  icon.src = "/image/\u6587\u4EF6\u5939.svg";   // 文件夹.svg
  icon.alt = "\u6587\u4EF6\u5939";

  const info = document.createElement("div");
  info.className = "user-file-card-info";

  const nameEl = document.createElement("span");
  nameEl.className = "user-file-name";
  const safeName = folderPath.replace(/\\/g, "/").split("/").pop() || folderPath;
  nameEl.textContent = safeName;
  nameEl.title = folderPath;

  const extEl = document.createElement("span");
  extEl.className = "user-file-ext";
  extEl.textContent = "folder";

  info.appendChild(nameEl);
  info.appendChild(extEl);
  card.appendChild(icon);
  card.appendChild(info);
  return card;
}

/** 渲染用户消息中的文件引用卡片 */
function renderUserFileRefCard(filePath) {
  const card = document.createElement("div");
  card.className = "user-file-card";

  const icon = document.createElement("img");
  icon.className = "user-file-card-icon";
  icon.src = "/image/\u6587\u6863\u6309\u94AE.svg";   // 文档按钮.svg
  icon.alt = "\u6587\u4EF6";

  const info = document.createElement("div");
  info.className = "user-file-card-info";

  const nameEl = document.createElement("span");
  nameEl.className = "user-file-name";
  const safeName = filePath.replace(/\\/g, "/").split("/").pop() || filePath;
  nameEl.textContent = safeName;
  nameEl.title = filePath;

  const extEl = document.createElement("span");
  extEl.className = "user-file-ext";
  const dotIdx = safeName.lastIndexOf(".");
  extEl.textContent = dotIdx >= 0 ? safeName.slice(dotIdx + 1).toLowerCase() : "file";

  info.appendChild(nameEl);
  info.appendChild(extEl);
  card.appendChild(icon);
  card.appendChild(info);
  return card;
}

/* ===== 从工具文件 URL 中提取文件名 ===== */
function extractToolFileName(url) {
  if (!url) return "文件";
  // 处理 /api/tool-file?path=/foo/bar.txt&session=xxx 格式
  try {
    const u = new URL(url, window.location.origin);
    const pathParam = u.searchParams.get("path");
    if (pathParam) {
      const name = pathParam.replace(/\\/g, "/").split("/").pop();
      if (name) return decodeURIComponent(name);
    }
  } catch {
    // URL 解析失败，回退到字符串处理
  }
  // 回退：取最后一个 / 之后、? 之前的部分
  const clean = url.split("?")[0];
  const name = clean.replace(/\\/g, "/").split("/").pop();
  return name ? decodeURIComponent(name) : "文件";
}

/* ===== 从工具调用列表中提取最终产出物（sendfile 返回文件 + image_gen 返回图片） ===== */
function extractFinalAssets(toolCalls) {
  if (!Array.isArray(toolCalls) || toolCalls.length === 0) {
    return { images: [], files: [], folders: [] };
  }
  const images = [];
  const files = [];
  const folders = [];

  const collectFromCall = (call) => {
    if (!call) return;
    const name = String(call.name || "").trim();
    // image_gen：收集 result_images
    if (name === "image_gen" && Array.isArray(call.result_images)) {
      call.result_images.forEach((url) => {
        if (typeof url === "string" && url) images.push({ url, name: "image_gen.png" });
      });
    }
    // sendfile：收集 result_download_files / result_file_info / result_images
    if (name === "sendfile" || name === "send_file") {
      // result_file_info 优先（有正确文件名），仅在无 result_file_info 时用 result_download_files
      const fileInfos = Array.isArray(call.result_file_info) ? call.result_file_info : [];
      if (fileInfos.length > 0) {
        fileInfos.forEach((fi) => {
          if (fi && fi.file_path && fi.file_name) {
            if (fi.file_type === "folder") {
              // 文件夹：展示为文件夹卡片
              folders.push({ path: fi.file_path, name: fi.file_name });
            } else if (fi.file_type === "image") {
              // 图片：展示为缩略图预览
              const imgUrl = `/api/tool-file?path=${encodeURIComponent(fi.file_path)}&session=${encodeURIComponent(call.turn_id || '')}`;
              images.push({ url: imgUrl, name: fi.file_name });
            } else {
              const apiUrl = `/api/tool-file?path=${encodeURIComponent(fi.file_path)}&session=${encodeURIComponent(call.turn_id || '')}`;
              files.push({ url: apiUrl, name: fi.file_name });
            }
          }
        });
      } else {
        // 无 result_file_info 时：先尝试 result_images（send_file 发送的图片可能走这条路径）
        if (Array.isArray(call.result_images) && call.result_images.length > 0) {
          call.result_images.forEach((url) => {
            if (typeof url === "string" && url) images.push({ url, name: "send_file_image.png" });
          });
        }
        const dlFiles = Array.isArray(call.result_download_files) ? call.result_download_files : [];
        dlFiles.forEach((url) => {
          if (typeof url === "string" && url) {
            files.push({ url, name: extractToolFileName(url) });
          }
        });
      }
    }
    // 嵌套子 agent 调用：递归
    if ((name === "call_subagent" || name === "agent_call") && Array.isArray(call.sub_tool_calls)) {
      call.sub_tool_calls.forEach(collectFromCall);
    }
  };
  toolCalls.forEach(collectFromCall);

  return { images, files, folders };
}

/* ===== 渲染最终回复下方的产出物（图片 + 文件卡片） ===== */
function renderFinalAssets(toolCalls) {
  const { images, files, folders } = extractFinalAssets(toolCalls);
  if (images.length === 0 && files.length === 0 && folders.length === 0) return null;

  const wrap = document.createElement("div");
  wrap.className = "final-assets";

  const label = document.createElement("div");
  label.className = "final-assets-label";
  label.textContent = "生成文件";
  wrap.appendChild(label);

  if (images.length > 0) {
    const imgItems = images.map((p) => renderUserImageThumb(p.url, p.name));
    const row = renderUserMediaRow(imgItems);
    if (row) wrap.appendChild(row);
  }

  if (folders.length > 0) {
    const folderItems = folders.map((p) => renderUserFolderRefCard(p.path || p.name));
    const row = renderUserMediaRow(folderItems);
    if (row) wrap.appendChild(row);
  }

  if (files.length > 0) {
    const fileItems = files.map((p) => renderUserFileCard(p.url, p.name, { preview: true }));
    const row = renderUserMediaRow(fileItems);
    if (row) wrap.appendChild(row);
  }

  return wrap;
}

/* ===== 渲染 assistant 消息内容（agent-run-block + 文本 + 产出物 + 媒体） ===== */
function renderAssistantContent(msg, allowAutoplay = false) {
  const wrap = document.createElement("div");
  wrap.className = "msg-bubble";

  const meta = msg.meta || {};
  const toolCalls = Array.isArray(meta.tool_calls) ? meta.tool_calls : [];

  // 1. Agent 运行过程（默认折叠，运行结束后展示）
  if (toolCalls.length > 0 && renderPersistentToolCallsFn) {
    // 传入轮次级计时元数据（duration/started_at）
    const turnMeta = meta.turn_meta || {};
    const tcList = renderPersistentToolCallsFn(toolCalls, {
      duration: turnMeta.duration != null ? Number(turnMeta.duration) : undefined,
    });
    if (tcList) {
      // 执行结束后默认折叠，用户可点击折叠条展开
      wrap.appendChild(tcList);
    }
  }

  // 2. 文本回复（追加到子容器中，不能用 fillAssistantBubbleImmediate 因为它会 textContent="" 清除工具调用列表）
  const c = msg.content;
  const isAudioOnly = isAudioOnlyAssistantMessage(msg);
  if (!isAudioOnly) {
    if (typeof c === "string" && c.trim()) {
      const textDiv = document.createElement("div");
      textDiv.className = "msg-prose markdown-body";
      textDiv.appendChild(renderMarkdownToFragment(c));
      wrap.appendChild(textDiv);
    } else if (Array.isArray(c)) {
      const textParts = c.filter((part) => part && part.type === "text" && typeof part.text === "string");
      if (textParts.length > 0) {
        const text = textParts.map((part) => part.text || "").join("\n");
        const textDiv = document.createElement("div");
        textDiv.className = "msg-prose markdown-body";
        textDiv.appendChild(renderMarkdownToFragment(text));
        wrap.appendChild(textDiv);
      }
    }
  }

  // 3. 最终产出物（sendfile / image_gen 返回的文件/图片）
  if (toolCalls.length > 0) {
    const assets = renderFinalAssets(toolCalls);
    if (assets) wrap.appendChild(assets);
  }

  // 4. 媒体 part（TTS 音频等）
  if (Array.isArray(c)) {
    const mediaParts = c.filter((part) => part && part.type !== "text");
    const baseOptions = {
      messageMeta: meta,
      role: "assistant",
      allowAutoplay: allowAutoplay,
      compact: true,
    };
    mediaParts.forEach((p) => {
      wrap.appendChild(renderContentPart(p, baseOptions));
    });
  }

  return wrap;
}

function renderContentPart(part, options = {}) {
  if (typeof part === "string") {
    const div = document.createElement("div");
    div.className = "msg-text";
    div.textContent = part;
    return div;
  }
  if (!part || typeof part !== "object") {
    const div = document.createElement("div");
    div.className = "msg-text";
    div.textContent = String(part);
    return div;
  }
  if (part.type === "text") {
    const div = document.createElement("div");
    div.className = "msg-text";
    div.textContent = part.text || "";
    return div;
  }
  if (part.type === "image" && part.url) {
    const img = document.createElement("img");
    img.src = part.url;
    img.alt = "\u56FE\u7247";
    img.style.cursor = "pointer";
    img.title = "\u70B9\u51FB\u67E5\u770B\u5927\u56FE";
    img.addEventListener("click", (e) => {
      e.stopPropagation();
      showImagePreview(part.url);
    });
    return img;
  }
  if (part.type === "audio" && part.url) {
    return renderAudioBubble(part, options);
  }
  if (part.type === "file") {
    // 助手消息中的文件 part（理论上不会出现，但兜底）
    return renderUserFileCard(part.url, part.name, { preview: true });
  }
  const div = document.createElement("div");
  div.className = "msg-text";
  div.textContent = JSON.stringify(part);
  return div;
}

function renderMessage(msg, allowAutoplay = false) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + (msg.role === "user" ? "user" : "assistant") + (isAudioOnlyAssistantMessage(msg) ? " msg--audio-only" : "");

  const baseOptions = {
    messageMeta: msg.meta || null,
    role: msg.role === "user" ? "user" : "assistant",
    allowAutoplay: allowAutoplay,
  };

  if (msg.role === "user") {
    // 用户消息：回退按钮 + 内容（无气泡）
    const rollbackBtn = document.createElement("button");
    rollbackBtn.className = "chat-rollback-btn";
    rollbackBtn.textContent = "\u21A9";
    rollbackBtn.title = "回退到此消息";
    rollbackBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!chatMessages) return;
      const children = Array.from(chatMessages.children);
      const idx = children.indexOf(wrap);
      if (idx < 0) return;
      if (rollbackChatFn) {
        rollbackChatFn(idx);
      }
    });
    wrap.appendChild(rollbackBtn);

    const contentEl = renderUserContent(msg.content, baseOptions);
    wrap.appendChild(contentEl);
  } else {
    // 助手消息
    const contentEl = renderAssistantContent(msg, allowAutoplay);
    wrap.appendChild(contentEl);
    if (msg.meta && msg.meta.pending_action) {
      // pending_action 不再内嵌在气泡中，由 pending-overlay 浮窗展示
    }
  }

  return wrap;
}

function renderMessages(messages, allowAutoplay = false) {
  if (!chatMessages || !chatPlaceholder) return;
  const list = messages || [];
  // 清理所有 typingEl 的计时器，防止内存泄漏
  chatMessages.querySelectorAll(".tool-call-list-wrap").forEach((w) => {
    if (typeof w._stopTimer === "function") w._stopTimer();
  });
  chatMessages.innerHTML = "";

  state.lastRenderedMessages.length = 0;
  const snapshot = list.length ? JSON.parse(JSON.stringify(list)) : [];
  state.lastRenderedMessages.push(...snapshot);
  const has = list.length > 0;
  chatPlaceholder.hidden = has;
  chatMessages.hidden = !has;
  if (!has) {
    // 确保无消息时隐藏：内联 display:none 优先级高于 CSS 类设定，不依赖 [hidden] 规则
    chatMessages.style.display = "none";
    // 设置为居中状态
    import('../app.js').then((m) => m.setComposerCentered(true));
    return;
  }
  // 有消息时清除内联 display，让 CSS flex 布局生效
  chatMessages.style.display = "";
  list.forEach((m) => chatMessages.appendChild(renderMessage(m, allowAutoplay)));
  scrollChatToBottom();
  // 取消居中状态
  import('../app.js').then((m) => m.setComposerCentered(false));
}

function appendThinkingIndicator() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant msg-typing";
  wrap.setAttribute("aria-live", "polite");
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  // 三点加载动画，首次工具调用或 AI 回复后消失
  const dots = document.createElement("div");
  dots.className = "typing-dots";
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("span");
    dot.textContent = ".";
    dots.appendChild(dot);
  }
  bubble.appendChild(dots);
  wrap.appendChild(bubble);
  chatMessages.appendChild(wrap);
  scrollChatToBottom();
  return wrap;
}

function showPendingActionInThinking(typingEl, msg) {
  if (!typingEl || !msg || !msg.meta || !msg.meta.pending_action) return false;
  // pending_action 由 pending-overlay 浮窗展示

  const snapshot = JSON.parse(JSON.stringify(msg));
  state.lastRenderedMessages.push(snapshot);
  scrollChatToBottom();
  return true;
}

async function streamAssistantMessage(msg) {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant" + (isAudioOnlyAssistantMessage(msg) ? " msg--audio-only" : "");
  chatMessages.appendChild(wrap);
  chatPlaceholder.hidden = true;
  chatMessages.hidden = false;

  const meta = msg.meta || {};
  const toolCalls = Array.isArray(meta.tool_calls) ? meta.tool_calls : [];

  // 1. Agent 运行过程（执行结束，默认折叠，可展开）
  if (toolCalls.length > 0 && renderPersistentToolCallsFn) {
    const turnMeta = meta.turn_meta || {};
    const tcList = renderPersistentToolCallsFn(toolCalls, {
      duration: turnMeta.duration != null ? Number(turnMeta.duration) : undefined,
    });
    if (tcList) {
      wrap.appendChild(tcList);
    }
  }

  // 2. 文本回复（伪流式）
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  wrap.appendChild(bubble);

  const parts = Array.isArray(msg.content) ? msg.content : [{ type: "text", text: String(msg.content || "") }];
  const textParts = parts.filter((part) => part && part.type === "text" && typeof part.text === "string");
  const mediaParts = parts.filter((part) => !part || part.type !== "text");

  if (textParts.length > 0) {
    await pseudoStreamAssistant(bubble, textParts.map((part) => part.text || "").join("\n"));
  }

  // 3. 最终产出物（sendfile / image_gen 返回的文件/图片）
  if (toolCalls.length > 0) {
    const assets = renderFinalAssets(toolCalls);
    if (assets) wrap.appendChild(assets);
  }

  // 4. 媒体 part（TTS 音频等）
  const mediaOptions = {
    autoplay: true,
    compact: textParts.length === 0,
    messageMeta: meta,
    role: "assistant",
    allowAutoplay: true,
  };
  mediaParts.forEach((part) => {
    bubble.appendChild(renderContentPart(part, mediaOptions));
  });

  if (textParts.length === 0 && mediaParts.length > 0) {
    bubble.textContent = "";
    mediaParts.forEach((part) => {
      bubble.appendChild(renderContentPart(part, mediaOptions));
    });
  }

  if (msg.meta && msg.meta.pending_action) {
    // pending_action 不再内嵌在气泡中，由 pending-overlay 浮窗展示
  }

  scrollChatToBottom();
}

/* ===== 语音转文字中占位（用户语音输入时） ===== */
function renderVoiceTranscribingPlaceholder() {
  if (!chatMessages) return null;
  // 确保聊天区域可见（即使之前没有消息）
  if (chatPlaceholder) chatPlaceholder.hidden = true;
  chatMessages.hidden = false;
  chatMessages.style.display = "";
  const wrap = document.createElement("div");
  wrap.className = "msg user";
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble msg-bubble--user";
  const indicator = document.createElement("span");
  indicator.className = "voice-transcribing";
  indicator.textContent = "语音转文字中";
  bubble.appendChild(indicator);
  wrap.appendChild(bubble);
  chatMessages.appendChild(wrap);
  scrollChatToBottom();
  // 取消居中状态
  import('../app.js').then((m) => m.setComposerCentered(false)).catch(() => {});
  return wrap;
}

export {
  scrollChatToBottom,
  renderAttachmentChips,
  renderMarkdownToFragment, splitMarkdownStreamBlocks, renderMarkdownBlock,
  fillAssistantBubbleImmediate, pseudoStreamAssistant,
  renderAudioBubble, renderContentPart,
  renderUserMediaRow, renderUserImageThumb,
  renderUserContent, renderAssistantContent,
  renderFinalAssets, extractFinalAssets,
  renderMessage, renderMessages,
  appendThinkingIndicator, showPendingActionInThinking,
  streamAssistantMessage,
  renderVoiceTranscribingPlaceholder,
};
