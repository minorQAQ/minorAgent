// utils.js -- 纯工具函数

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function formatAudioDuration(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n < 10) return `${n.toFixed(1)}″`;
  return `${Math.round(n)}″`;
}

function getAudioBubbleWidth(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) return null;
  const width = 132 + Math.sqrt(n) * 46;
  return `${Math.round(clamp(width, 148, 312))}px`;
}

function inferUploadKind(file) {
  const name = String(file?.name || "").toLowerCase();
  const type = String(file?.type || "").toLowerCase();
  const filePath = String(file?.path || "").toLowerCase();
  if (type.startsWith("folder/")) return "folder";
  // SVG 不作为图片处理（按普通文本文件渲染）；排除 image/svg+xml
  const isSvg = /\.svg$/.test(name) || /\.svg$/.test(filePath) || type.indexOf("svg") >= 0;
  if (!isSvg && (type.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|ico)$/.test(name) || /\.(png|jpe?g|gif|webp|bmp|ico)$/.test(filePath))) return "image";
  if (type.startsWith("audio/") || /\.(wav|mp3|m4a|flac|ogg|webm|aac)$/.test(name)) return "audio";
  return "file";
}

function getTextFromContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

function getMediaParts(content) {
  if (!Array.isArray(content)) return [];
  return content.filter((part) => part && part.type !== "text");
}

function isAudioOnlyAssistantMessage(msg) {
  if (!msg || msg.role !== "assistant") return false;
  const text = getTextFromContent(msg.content);
  const mediaParts = getMediaParts(msg.content);
  const hasOnlyAudioMedia = mediaParts.length > 0 && mediaParts.every((part) => part.type === "audio" && part.url);
  return hasOnlyAudioMedia && !text;
}

function buildOptimisticUserContent(text, fileParts) {
  const parts = [];
  (fileParts || []).forEach((filePart) => {
    if (filePart && filePart.kind === "image" && filePart.url) {
      parts.push({ type: "image", url: filePart.url, name: filePart.name || "图片" });
    } else if (filePart && filePart.kind === "audio" && filePart.url) {
      parts.push({ type: "audio", url: filePart.url, name: filePart.name || "音频" });
    } else if (filePart && filePart.kind === "folder") {
      parts.push({ type: "folder", name: filePart.name || "文件夹" });
    } else if (filePart && filePart.name) {
      parts.push({ type: "file", name: filePart.name });
    }
  });
  const t = (text || "").trim();
  if (t) parts.push({ type: "text", text: t });
  if (parts.length === 0) return null;
  if (parts.length === 1 && parts[0].type === "text") return parts[0].text;
  return parts;
}

function revokeBlobUrlStack(urlStack) {
  (urlStack || []).forEach((u) => {
    try { URL.revokeObjectURL(u); } catch { /* ignore */ }
  });
  urlStack.length = 0;
}

function makeId() {
  return Math.random().toString(36).substring(2, 10);
}

function codeBlockNode(lang, code) {
  const raw = code.replace(/\n$/, "");
  const wrap = document.createElement("div");
  wrap.className = "code-block-wrap";
  const head = document.createElement("div");
  head.className = "code-block-head";
  const langSpan = document.createElement("span");
  langSpan.className = "code-block-lang";
  langSpan.textContent = (lang && lang.trim()) || "text";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "code-block-copy";
  btn.textContent = "复制全部";
  btn.addEventListener("click", () => {
    navigator.clipboard.writeText(raw).catch(() => {});
  });
  head.appendChild(langSpan);
  head.appendChild(btn);
  const pre = document.createElement("pre");
  const codeEl = document.createElement("code");
  codeEl.textContent = raw;
  pre.appendChild(codeEl);
  wrap.appendChild(head);
  wrap.appendChild(pre);
  return wrap;
}

/**
 * 显示一个 3 秒自动消失的浮窗通知。
 * @param {string} text - 通知文字。
 */
function showToast(text) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const item = document.createElement("div");
  item.className = "toast-item";
  item.textContent = text;
  container.appendChild(item);
  setTimeout(() => {
    if (item.parentNode) item.parentNode.removeChild(item);
  }, 3100);
}

/**
 * 为 pendingFiles 去重：
 * - 普通 File 对象：按 name + size + lastModified 比较
 * - __isRef 引用：按 refPath 比较
 * - 文件夹占位：按 name + type 比较
 */
function dedupePendingFiles(files) {
  const seen = new Set();
  return files.filter((f) => {
    let key;
    if (f.__isRef) {
      // 包含 type 以区分 ref/file、ref/image、ref/folder
      key = 'ref:' + (f.type || '') + ':' + (f.refPath || '');
    } else if (f.type && f.type.startsWith('folder/')) {
      key = 'folder:' + (f.name || '');
    } else if (f instanceof File) {
      key = (f.name || '') + '|' + (f.size || 0);
    } else {
      key = 'other:' + JSON.stringify(f);
    }
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * 通用连击保护：在 timeWindow 毫秒内忽略重复触发。
 * 用于按钮/选项等一次性交互，防止双击导致重复请求或重复弹窗。
 * @param {Function} fn - 要执行的函数（可用 async）
 * @param {number} ms - 保护时间窗（毫秒），默认 400
 * @returns {Function} 包裹后的函数
 */
function withClickGuard(fn, ms = 400) {
  let lastAt = 0;
  let running = false;
  return function (...args) {
    const now = Date.now();
    if (running || now - lastAt < ms) return;
    lastAt = now;
    const result = fn.apply(this, args);
    if (result && typeof result.then === "function") {
      running = true;
      return result.finally(() => { running = false; });
    }
    return result;
  };
}

/**
 * 关闭除 keepEl 外的所有内联下拉面板（.inline-drop-panel），保证同时只开一个。
 * @param {HTMLElement|null} keepEl - 保持打开的面板元素
 */
function closeInlinePanelsExcept(keepEl) {
  document.querySelectorAll(".inline-drop-panel").forEach((p) => {
    if (p === keepEl) return;
    p.hidden = true;
    if (p._trigger) p._trigger.classList.remove("is-open");
  });
}

export {
  $,
  escapeHtml,
  clamp, formatAudioDuration, getAudioBubbleWidth,
  inferUploadKind,
  getTextFromContent, getMediaParts, isAudioOnlyAssistantMessage,
  buildOptimisticUserContent, revokeBlobUrlStack,
  makeId, codeBlockNode,
  showToast,
  dedupePendingFiles,
  withClickGuard,
  closeInlinePanelsExcept,
};
