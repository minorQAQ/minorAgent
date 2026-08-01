// file-preview.js -- 文件浮窗预览（替代原 edit 模式下的 Monaco 编辑器）
// 点击文件树中的文件或聊天中的文件卡片时弹窗查看内容

import { $, escapeHtml } from './utils.js';

const IMG_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico']);
const HTML_EXTS = new Set(['.html', '.htm']);
const TEXT_EXTS = new Set(['.txt', '.json', '.md', '.py', '.js', '.ts', '.css', '.xml', '.yaml', '.yml', '.toml',
  '.csv', '.log', '.env', '.ini', '.cfg', '.sh', '.bat', '.ps1', '.sql', '.r', '.go', '.rs', '.rb',
  '.php', '.swift', '.kt', '.scala', '.cpp', '.c', '.h', '.java', '.m', '.svg']);

let _currentFilePath = null;
let _currentContent = null;

/** 判断是否为图片（非SVG） */
function isImage(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && IMG_EXTS.has(ext.substring(dot));
}

/** 判断HTML */
function isHtml(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && HTML_EXTS.has(ext.substring(dot));
}

/** 判断文本文件 */
function isTextFile(fileName) {
  const ext = (fileName || '').toLowerCase();
  const dot = ext.lastIndexOf('.');
  return dot >= 0 && TEXT_EXTS.has(ext.substring(dot));
}

/**
 * 打开文件预览浮窗
 * @param {string} filePath - 文件路径
 * @param {string} fileName - 文件名
 * @param {string} content - 文件内容（文本）或 base64 data URL（图片）
 * @param {object} opts - { status: 'new'|'modified'|'deleted'|'', onDownload: fn }
 */
export function openFilePreview(filePath, fileName, content, opts = {}) {
  _currentFilePath = filePath;
  _currentContent = content;

  const overlay = $('filePreviewOverlay');
  const nameEl = $('filePreviewName');
  const statusEl = $('filePreviewStatus');
  const body = $('filePreviewBody');
  const downloadBtn = $('filePreviewDownload');

  if (!overlay || !body) return;

  // 设置文件名
  if (nameEl) nameEl.textContent = fileName || filePath;

  // 设置状态标签
  if (statusEl) {
    statusEl.className = 'file-preview-status';
    const status = opts.status || '';
    if (status) {
      statusEl.textContent = status === 'new' ? '新增' : status === 'modified' ? '已修改' : '已删除';
      statusEl.classList.add(`file-preview-status--${status}`);
    } else {
      statusEl.textContent = '';
    }
  }

  // 下载按钮
  if (downloadBtn) {
    downloadBtn.onclick = () => {
      if (opts.onDownload) {
        opts.onDownload(filePath, fileName, content);
      } else {
        _downloadFile(fileName, content);
      }
    };
  }

  // 渲染内容
  body.innerHTML = '';
  if (isImage(fileName)) {
    _renderImage(body, content, fileName);
  } else if (isHtml(fileName) && !opts.asText) {
    _renderPlainText(body, content);
  } else if (isTextFile(fileName)) {
    _renderPlainText(body, content);
  } else if (content && content.startsWith && content.startsWith('data:')) {
    _renderImage(body, content, fileName);
  } else {
    _renderPlainText(body, content || '(空文件)');
  }

  overlay.hidden = false;
  document.body.style.overflow = 'hidden';

  // 点击背景关闭
  overlay.onclick = (e) => {
    if (e.target === overlay) closeFilePreview();
  };

  // ESC 关闭
  document.addEventListener('keydown', _onEscClose);
}

/** 关闭文件预览 */
export function closeFilePreview() {
  const overlay = $('filePreviewOverlay');
  if (overlay) overlay.hidden = true;
  document.body.style.overflow = '';
  document.removeEventListener('keydown', _onEscClose);
  _currentFilePath = null;
  _currentContent = null;
}

function _onEscClose(e) {
  if (e.key === 'Escape') closeFilePreview();
}

function _renderImage(body, content, fileName) {
  const img = document.createElement('img');
  img.src = content;
  img.alt = fileName;
  img.style.maxWidth = '100%';
  img.style.display = 'block';
  img.style.margin = '0 auto';
  body.appendChild(img);
}

function _renderPlainText(body, content) {
  const text = content || '';
  const lines = text.split('\n');

  const wrap = document.createElement('div');
  wrap.className = 'fp-code-wrap';

  // 行号列
  const lineNos = document.createElement('div');
  lineNos.className = 'fp-line-nos';
  for (let i = 1; i <= lines.length; i++) {
    const span = document.createElement('span');
    span.textContent = i;
    lineNos.appendChild(span);
  }

  // 代码列（每行独立 span，可精确选中）
  const codeLines = document.createElement('div');
  codeLines.className = 'fp-code-lines';
  lines.forEach((line, i) => {
    const span = document.createElement('span');
    span.setAttribute('data-line', i + 1);
    span.textContent = line || '\u00A0';
    codeLines.appendChild(span);
  });

  wrap.appendChild(lineNos);
  wrap.appendChild(codeLines);
  body.appendChild(wrap);

  // 右键菜单：引用选中行
  codeLines.addEventListener('contextmenu', (e) => _onCodeContextMenu(e));
}

function _onCodeContextMenu(e) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.toString().trim()) return;

  // 找到选中区域的起止行
  const range = sel.getRangeAt(0);
  const startEl = range.startContainer?.parentElement?.closest?.('[data-line]');
  const endEl = range.endContainer?.parentElement?.closest?.('[data-line]');
  if (!startEl || !endEl) return;

  const s = parseInt(startEl.getAttribute('data-line'));
  const endLine = parseInt(endEl.getAttribute('data-line'));
  if (isNaN(s) || isNaN(endLine)) return;

  const minLine = Math.min(s, endLine);
  const maxLine = Math.max(s, endLine);

  e.preventDefault();
  _showCodeRefMenu(e.clientX, e.clientY, minLine, maxLine);
}

function _showCodeRefMenu(x, y, startLine, endLine) {
  const existing = document.querySelector('.fp-context-menu');
  if (existing) existing.remove();

  const menu = document.createElement('div');
  menu.className = 'doc-context-menu fp-context-menu';
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.style.position = 'fixed';
  menu.style.zIndex = '1100';

  const label = startLine === endLine ? `L${startLine}` : `L${startLine}-L${endLine}`;

  const item = document.createElement('div');
  item.className = 'doc-context-menu-item';
  item.textContent = `\u{1F517} 引用选中内容 (${label})`;
  item.addEventListener('click', () => {
    const filePath = _currentFilePath;
    if (filePath) {
      import('./edit-mode.js').then(m => m.addDocRef(filePath, startLine, endLine)).catch(() => {});
    }
    menu.remove();
    closeFilePreview();
  });
  menu.appendChild(item);

  document.body.appendChild(menu);

  const closeHandler = (ev) => {
    if (!menu.contains(ev.target)) {
      menu.remove();
      document.removeEventListener('click', closeHandler);
    }
  };
  setTimeout(() => document.addEventListener('click', closeHandler), 0);
}

function _downloadFile(fileName, content) {
  let url, type;
  if (content && content.startsWith && content.startsWith('data:')) {
    url = content;
  } else {
    const blob = new Blob([content || ''], { type: 'text/plain;charset=utf-8' });
    url = URL.createObjectURL(blob);
  }
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (!content?.startsWith?.('data:')) URL.revokeObjectURL(url);
}

/** 绑定关闭按钮 */
export function bindFilePreviewEvents() {
  const closeBtn = $('filePreviewClose');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeFilePreview);
  }
}
