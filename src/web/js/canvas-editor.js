// canvas-editor.js -- 画板编辑器浮窗
// 支持：画笔/矩形/圆形/直线/文字/橡皮擦，颜色粗细可调
// 交互：Ctrl+滚轮缩放画布，中键拖动平移，文字可拖拽/缩放/旋转
// 撤销/重做针对绘制层（bg 层不动），文字独立管理，确定时合并导出

import { state } from './state.js';
import { dedupePendingFiles, showToast } from './utils.js';

const MAX_HISTORY = 50;

let _st = null;       // 编辑器状态
let _overlay = null;  // 浮窗 DOM
let _bgCanvas, _drawCanvas, _textLayer, _canvasWrap;
let _bgCtx, _drawCtx;

/**
 * 打开画板编辑器
 * @param {Object} opts
 *   mode: 'edit' | 'create'
 *   imageSrc: String (edit 模式底图 URL)
 *   originalIdx: Number (edit 模式原图在 pendingFiles 的索引，-1 表示无原图)
 *   originalName: String
 *   width: Number (create 模式画布宽度)
 *   height: Number (create 模式画布高度)
 */
export function openCanvasEditor(opts = {}) {
  // 已存在则先关闭
  if (_overlay) closeCanvasEditor();

  _st = {
    mode: opts.mode || 'create',
    canvasW: opts.width || 1536,
    canvasH: opts.height || 768,
    scale: 1,
    offsetX: 0,
    offsetY: 0,
    tool: 'brush',
    color: '#000000',
    lineWidth: 3,
    isDrawing: false,
    isPanning: false,
    panStart: { x: 0, y: 0 },
    panOrigin: { x: 0, y: 0 },
    startX: 0,
    startY: 0,
    snapshot: null,
    history: [],
    redoStack: [],
    textObjects: [],
    textCounter: 0,
    originalIdx: typeof opts.originalIdx === 'number' ? opts.originalIdx : -1,
    originalName: opts.originalName || '',
    imageSrc: opts.imageSrc || null,
    bgReady: false,
  };

  _buildOverlay();
  document.body.appendChild(_overlay);
  _overlay.hidden = false;
  document.body.style.overflow = 'hidden';

  _initCanvas();
  _bindEvents();
  _updateZoomLabel();

  // edit 模式加载底图
  if (_st.mode === 'edit' && _st.imageSrc) {
    _loadBgImage(_st.imageSrc);
  } else {
    // create 模式白色背景
    _bgCtx.fillStyle = '#ffffff';
    _bgCtx.fillRect(0, 0, _st.canvasW, _st.canvasH);
    _st.bgReady = true;
    _pushHistory();
  }
}

/** 关闭画板编辑器（不保存） */
export function closeCanvasEditor() {
  document.removeEventListener('keydown', _onKeyDown);
  if (_overlay && _overlay.parentNode) {
    _overlay.parentNode.removeChild(_overlay);
  }
  _overlay = null;
  _bgCanvas = _drawCanvas = _textLayer = _canvasWrap = null;
  _bgCtx = _drawCtx = null;
  _st = null;
  document.body.style.overflow = '';
}

// ==================== DOM 构建 ====================

function _buildOverlay() {
  _overlay = document.createElement('div');
  _overlay.className = 'canvas-editor-overlay';
  _overlay.innerHTML = `
    <div class="canvas-editor-dialog">
      <div class="canvas-editor-header">
        <span class="canvas-editor-title" id="ceTitle">${_st.mode === 'edit' ? '修改图片' : '画板'}</span>
        <div class="canvas-editor-actions">
          <button type="button" class="ce-btn ce-btn--icon" id="ceUndoBtn" title="撤销 (Undo)">↶</button>
          <button type="button" class="ce-btn ce-btn--icon" id="ceRedoBtn" title="重做 (Redo)">↷</button>
          <button type="button" class="ce-btn" id="ceClearBtn" title="清空绘制层">清空</button>
          <span class="ce-actions-sep"></span>
          <button type="button" class="ce-btn ce-btn--ghost" id="ceCloseBtn" title="关闭不保存">关闭</button>
          <button type="button" class="ce-btn ce-btn--primary" id="ceConfirmBtn">确定</button>
        </div>
      </div>
      <div class="canvas-editor-toolbar">
        <div class="ce-tool-group">
          <button type="button" class="ce-tool-btn is-active" data-tool="brush" title="画笔">🖌</button>
          <button type="button" class="ce-tool-btn" data-tool="rect" title="矩形">▭</button>
          <button type="button" class="ce-tool-btn" data-tool="circle" title="圆形">○</button>
          <button type="button" class="ce-tool-btn" data-tool="line" title="直线">╱</button>
          <button type="button" class="ce-tool-btn" data-tool="text" title="文字">T</button>
          <button type="button" class="ce-tool-btn" data-tool="eraser" title="橡皮擦">⌫</button>
        </div>
        <div class="ce-tool-group">
          <label class="ce-label">颜色</label>
          <input type="color" id="ceColorInput" value="#000000" class="ce-color-input">
        </div>
        <div class="ce-tool-group">
          <label class="ce-label">粗细</label>
          <input type="range" id="ceSizeRange" min="1" max="40" value="3" class="ce-size-range">
          <span class="ce-size-val" id="ceSizeVal">3</span>
        </div>
        <div class="ce-tool-group ce-tool-group--info">
          <span class="ce-zoom-val" id="ceZoomVal">100%</span>
          <span class="ce-hint">Ctrl+滚轮缩放 · 中键拖动画布</span>
        </div>
      </div>
      <div class="canvas-editor-canvas-area" id="ceCanvasArea">
        <div class="canvas-editor-canvas-wrap" id="ceCanvasWrap">
          <canvas id="ceBgCanvas"></canvas>
          <canvas id="ceDrawCanvas"></canvas>
          <div id="ceTextLayer" class="canvas-text-layer"></div>
        </div>
      </div>
    </div>
  `;
}

// ==================== 初始化 ====================

function _initCanvas() {
  _bgCanvas = _overlay.querySelector('#ceBgCanvas');
  _drawCanvas = _overlay.querySelector('#ceDrawCanvas');
  _textLayer = _overlay.querySelector('#ceTextLayer');
  _canvasWrap = _overlay.querySelector('#ceCanvasWrap');

  _bgCanvas.width = _st.canvasW;
  _bgCanvas.height = _st.canvasH;
  _drawCanvas.width = _st.canvasW;
  _drawCanvas.height = _st.canvasH;
  _canvasWrap.style.width = _st.canvasW + 'px';
  _canvasWrap.style.height = _st.canvasH + 'px';
  _textLayer.style.width = _st.canvasW + 'px';
  _textLayer.style.height = _st.canvasH + 'px';

  _bgCtx = _bgCanvas.getContext('2d');
  _drawCtx = _drawCanvas.getContext('2d');

  // 初始适配视口（让画布居中并缩放到可见区域）
  _fitToView();
}

function _fitToView() {
  const area = _overlay.querySelector('#ceCanvasArea');
  if (!area) return;
  const rect = area.getBoundingClientRect();
  const sx = (rect.width - 40) / _st.canvasW;
  const sy = (rect.height - 40) / _st.canvasH;
  _st.scale = Math.min(sx, sy, 1);
  _st.offsetX = (rect.width - _st.canvasW * _st.scale) / 2;
  _st.offsetY = (rect.height - _st.canvasH * _st.scale) / 2;
  _applyTransform();
}

function _applyTransform() {
  _canvasWrap.style.transform = `translate(${_st.offsetX}px, ${_st.offsetY}px) scale(${_st.scale})`;
  _updateZoomLabel();
}

function _updateZoomLabel() {
  const el = _overlay.querySelector('#ceZoomVal');
  if (el) el.textContent = Math.round(_st.scale * 100) + '%';
}

// ==================== 事件绑定 ====================

function _bindEvents() {
  // 顶部按钮
  _overlay.querySelector('#ceCloseBtn').addEventListener('click', closeCanvasEditor);
  _overlay.querySelector('#ceConfirmBtn').addEventListener('click', _onConfirm);
  _overlay.querySelector('#ceUndoBtn').addEventListener('click', _onUndo);
  _overlay.querySelector('#ceRedoBtn').addEventListener('click', _onRedo);
  _overlay.querySelector('#ceClearBtn').addEventListener('click', _onClear);

  // 工具切换
  _overlay.querySelectorAll('.ce-tool-btn').forEach((btn) => {
    btn.addEventListener('click', () => _setTool(btn.dataset.tool));
  });

  // 颜色/粗细
  _overlay.querySelector('#ceColorInput').addEventListener('input', (e) => {
    _st.color = e.target.value;
  });
  const sizeRange = _overlay.querySelector('#ceSizeRange');
  const sizeVal = _overlay.querySelector('#ceSizeVal');
  sizeRange.addEventListener('input', (e) => {
    _st.lineWidth = parseInt(e.target.value, 10);
    sizeVal.textContent = _st.lineWidth;
  });

  // 画布交互（绘制 + 缩放 + 平移）
  _drawCanvas.addEventListener('mousedown', _onCanvasMouseDown);
  _drawCanvas.addEventListener('contextmenu', (e) => e.preventDefault());
  _overlay.querySelector('#ceCanvasArea').addEventListener('wheel', _onWheel, { passive: false });
  _overlay.querySelector('#ceCanvasArea').addEventListener('mousedown', _onAreaMiddleDown);

  // 文字层点击空白处取消选中
  _textLayer.addEventListener('mousedown', (e) => {
    if (e.target === _textLayer) {
      _deselectAllText();
    }
  });

  // 点击背景关闭
  _overlay.addEventListener('click', (e) => {
    if (e.target === _overlay) closeCanvasEditor();
  });

  // ESC 关闭
  _overlay.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      // 编辑中的文字先失焦
      const editing = _textLayer.querySelector('.canvas-text-content[contenteditable="true"]');
      if (editing && document.activeElement === editing) {
        editing.blur();
        return;
      }
      closeCanvasEditor();
    }
  });

  // Delete 键删除选中文字
  document.addEventListener('keydown', _onKeyDown);
}

function _onKeyDown(e) {
  if (!_overlay || _overlay.hidden) return;
  if (e.key === 'Delete' || e.key === 'Backspace') {
    // 文字编辑中不拦截
    const editing = _textLayer.querySelector('.canvas-text-content[contenteditable="true"]');
    if (editing && document.activeElement === editing) return;
    const sel = _textLayer.querySelector('.canvas-text-obj.is-selected');
    if (sel) {
      e.preventDefault();
      _deleteTextObject(sel);
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    if (e.shiftKey) _onRedo(); else _onUndo();
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
    e.preventDefault();
    _onRedo();
  }
}

// ==================== 工具切换 ====================

function _setTool(tool) {
  _st.tool = tool;
  _overlay.querySelectorAll('.ce-tool-btn').forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.tool === tool);
  });
  // 切换光标
  const cursors = {
    brush: 'crosshair', eraser: 'cell', rect: 'crosshair',
    circle: 'crosshair', line: 'crosshair', text: 'text',
  };
  _drawCanvas.style.cursor = cursors[tool] || 'default';
  _deselectAllText();
}

// ==================== 坐标转换 ====================

function _screenToCanvas(clientX, clientY) {
  const rect = _drawCanvas.getBoundingClientRect();
  // rect 已反映 CSS transform 后的位置和尺寸
  const x = (clientX - rect.left) * (_st.canvasW / rect.width);
  const y = (clientY - rect.top) * (_st.canvasH / rect.height);
  return { x, y };
}

// ==================== 缩放与平移 ====================

function _onWheel(e) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    _st.scale = Math.max(0.1, Math.min(8, _st.scale * factor));
    _applyTransform();
  }
}

function _onAreaMiddleDown(e) {
  if (e.button !== 1) return; // 中键
  e.preventDefault();
  _st.isPanning = true;
  _st.panStart = { x: e.clientX, y: e.clientY };
  _st.panOrigin = { x: _st.offsetX, y: _st.offsetY };
  document.addEventListener('mousemove', _onAreaMiddleMove);
  document.addEventListener('mouseup', _onAreaMiddleUp);
}

function _onAreaMiddleMove(e) {
  if (!_st.isPanning) return;
  _st.offsetX = _st.panOrigin.x + (e.clientX - _st.panStart.x);
  _st.offsetY = _st.panOrigin.y + (e.clientY - _st.panStart.y);
  _applyTransform();
}

function _onAreaMiddleUp() {
  _st.isPanning = false;
  document.removeEventListener('mousemove', _onAreaMiddleMove);
  document.removeEventListener('mouseup', _onAreaMiddleUp);
}

// ==================== 绘制 ====================

function _onCanvasMouseDown(e) {
  // 中键不触发绘制（交给平移）
  if (e.button === 1) return;
  // 右键不绘制
  if (e.button === 2) return;

  const { x, y } = _screenToCanvas(e.clientX, e.clientY);
  _st.startX = x;
  _st.startY = y;
  _st.isDrawing = true;

  if (_st.tool === 'text') {
    _st.isDrawing = false;
    _addTextObject(x, y);
    return;
  }

  // 保存快照用于图形预览
  if (_st.tool === 'rect' || _st.tool === 'circle' || _st.tool === 'line') {
    _st.snapshot = _drawCtx.getImageData(0, 0, _st.canvasW, _st.canvasH);
  }

  if (_st.tool === 'brush' || _st.tool === 'eraser') {
    _drawCtx.beginPath();
    _drawCtx.moveTo(x, y);
    _drawCtx.lineCap = 'round';
    _drawCtx.lineJoin = 'round';
    // 画笔实时绘制单点
    if (_st.tool === 'brush') {
      _drawCtx.globalCompositeOperation = 'source-over';
      _drawCtx.strokeStyle = _st.color;
    } else {
      _drawCtx.globalCompositeOperation = 'destination-out';
      _drawCtx.strokeStyle = 'rgba(0,0,0,1)';
    }
    _drawCtx.lineWidth = _st.lineWidth;
    // 单点也绘制（避免点击无痕迹）
    _drawCtx.lineTo(x + 0.01, y + 0.01);
    _drawCtx.stroke();
  }

  document.addEventListener('mousemove', _onCanvasMouseMove);
  document.addEventListener('mouseup', _onCanvasMouseUp);
}

function _onCanvasMouseMove(e) {
  if (!_st.isDrawing) return;
  const { x, y } = _screenToCanvas(e.clientX, e.clientY);

  if (_st.tool === 'brush' || _st.tool === 'eraser') {
    _drawCtx.lineTo(x, y);
    _drawCtx.stroke();
  } else if (_st.tool === 'rect' || _st.tool === 'circle' || _st.tool === 'line') {
    // 恢复快照后预览
    _drawCtx.putImageData(_st.snapshot, 0, 0);
    _drawCtx.globalCompositeOperation = 'source-over';
    _drawCtx.strokeStyle = _st.color;
    _drawCtx.lineWidth = _st.lineWidth;
    _drawCtx.lineCap = 'round';
    _drawCtx.lineJoin = 'round';
    _drawCtx.beginPath();
    if (_st.tool === 'rect') {
      _drawCtx.rect(_st.startX, _st.startY, x - _st.startX, y - _st.startY);
    } else if (_st.tool === 'circle') {
      const cx = (_st.startX + x) / 2;
      const cy = (_st.startY + y) / 2;
      const rx = Math.abs(x - _st.startX) / 2;
      const ry = Math.abs(y - _st.startY) / 2;
      _drawCtx.ellipse(cx, cy, Math.max(0.1, rx), Math.max(0.1, ry), 0, 0, Math.PI * 2);
    } else if (_st.tool === 'line') {
      _drawCtx.moveTo(_st.startX, _st.startY);
      _drawCtx.lineTo(x, y);
    }
    _drawCtx.stroke();
  }
}

function _onCanvasMouseUp() {
  if (!_st.isDrawing) return;
  _st.isDrawing = false;
  _drawCtx.globalCompositeOperation = 'source-over';
  document.removeEventListener('mousemove', _onCanvasMouseMove);
  document.removeEventListener('mouseup', _onCanvasMouseUp);
  _pushHistory();
}

// ==================== 撤销 / 重做 ====================

function _pushHistory() {
  if (!_drawCtx) return;
  try {
    const data = _drawCtx.getImageData(0, 0, _st.canvasW, _st.canvasH);
    _st.history.push(data);
    if (_st.history.length > MAX_HISTORY) _st.history.shift();
    _st.redoStack = [];
  } catch (err) {
    // 忽略
  }
}

function _onUndo() {
  if (_st.history.length <= 1) {
    // 撤销到初始状态：清空绘制层
    if (_st.history.length === 1) {
      _st.redoStack.push(_drawCtx.getImageData(0, 0, _st.canvasW, _st.canvasH));
      _st.history.pop();
      _drawCtx.clearRect(0, 0, _st.canvasW, _st.canvasH);
    }
    return;
  }
  _st.redoStack.push(_st.history.pop());
  const prev = _st.history[_st.history.length - 1];
  _drawCtx.putImageData(prev, 0, 0);
}

function _onRedo() {
  if (_st.redoStack.length === 0) return;
  const next = _st.redoStack.pop();
  _st.history.push(next);
  _drawCtx.putImageData(next, 0, 0);
}

function _onClear() {
  _pushHistory();
  _drawCtx.clearRect(0, 0, _st.canvasW, _st.canvasH);
  _pushHistory();
}

// ==================== 文字对象 ====================

function _addTextObject(x, y) {
  const id = ++_st.textCounter;
  const obj = {
    id,
    x, y,
    text: '双击编辑',
    fontSize: 32,
    color: _st.color,
    rotation: 0,
  };
  const el = _createTextEl(obj);
  obj.el = el;
  _textLayer.appendChild(el);
  _st.textObjects.push(obj);
  _selectText(obj);
  // 立即进入编辑
  const content = el.querySelector('.canvas-text-content');
  if (content) {
    content.focus();
    // 全选文字
    const range = document.createRange();
    range.selectNodeContents(content);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }
}

function _createTextEl(obj) {
  const el = document.createElement('div');
  el.className = 'canvas-text-obj';
  el.dataset.id = obj.id;
  el.style.left = obj.x + 'px';
  el.style.top = obj.y + 'px';
  el.style.transform = `rotate(${obj.rotation}deg)`;

  const content = document.createElement('div');
  content.className = 'canvas-text-content';
  content.contentEditable = 'false';
  content.textContent = obj.text;
  content.style.color = obj.color;
  content.style.fontSize = obj.fontSize + 'px';
  el.appendChild(content);

  // 旋转 handle（顶部）
  const rotHandle = document.createElement('div');
  rotHandle.className = 'canvas-text-handle canvas-text-handle--rotate';
  rotHandle.title = '旋转';
  el.appendChild(rotHandle);

  // 缩放 handle（右下）
  const scaleHandle = document.createElement('div');
  scaleHandle.className = 'canvas-text-handle canvas-text-handle--scale';
  scaleHandle.title = '缩放';
  el.appendChild(scaleHandle);

  // 删除 handle（右上）
  const delHandle = document.createElement('div');
  delHandle.className = 'canvas-text-handle canvas-text-handle--delete';
  delHandle.title = '删除';
  delHandle.textContent = '×';
  el.appendChild(delHandle);

  // ---- 事件 ----
  // 选中
  el.addEventListener('mousedown', (e) => {
    if (e.target.classList.contains('canvas-text-handle')) return;
    if (content.contentEditable === 'true') return; // 编辑中不拖动
    e.stopPropagation();
    _selectText(obj);
    _startDragText(e, obj);
  });

  // 双击编辑
  content.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    content.contentEditable = 'true';
    content.focus();
    const range = document.createRange();
    range.selectNodeContents(content);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  });

  // 失焦保存
  content.addEventListener('blur', () => {
    content.contentEditable = 'false';
    obj.text = content.textContent;
  });

  // 阻止编辑时按键冒泡触发画板快捷键
  content.addEventListener('keydown', (e) => {
    e.stopPropagation();
  });

  // 旋转
  rotHandle.addEventListener('mousedown', (e) => {
    e.stopPropagation();
    e.preventDefault();
    _startRotateText(e, obj);
  });

  // 缩放
  scaleHandle.addEventListener('mousedown', (e) => {
    e.stopPropagation();
    e.preventDefault();
    _startScaleText(e, obj);
  });

  // 删除
  delHandle.addEventListener('click', (e) => {
    e.stopPropagation();
    _deleteTextObject(el);
  });

  return el;
}

function _startDragText(e, obj) {
  const startClient = { x: e.clientX, y: e.clientY };
  const startObj = { x: obj.x, y: obj.y };
  const onMove = (ev) => {
    const dx = (ev.clientX - startClient.x) / _st.scale;
    const dy = (ev.clientY - startClient.y) / _st.scale;
    obj.x = startObj.x + dx;
    obj.y = startObj.y + dy;
    obj.el.style.left = obj.x + 'px';
    obj.el.style.top = obj.y + 'px';
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

function _startRotateText(e, obj) {
  const rect = obj.el.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const startAngle = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
  const startRot = obj.rotation;
  const onMove = (ev) => {
    const angle = Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI;
    obj.rotation = startRot + (angle - startAngle);
    obj.el.style.transform = `rotate(${obj.rotation}deg)`;
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

function _startScaleText(e, obj) {
  const startClient = { x: e.clientX, y: e.clientY };
  const startSize = obj.fontSize;
  const onMove = (ev) => {
    const delta = (ev.clientX - startClient.x + ev.clientY - startClient.y) / _st.scale;
    obj.fontSize = Math.max(8, Math.min(200, startSize + delta * 0.5));
    const content = obj.el.querySelector('.canvas-text-content');
    if (content) content.style.fontSize = obj.fontSize + 'px';
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

function _selectText(obj) {
  _deselectAllText();
  obj.el.classList.add('is-selected');
}

function _deselectAllText() {
  if (!_textLayer) return;
  _textLayer.querySelectorAll('.canvas-text-obj.is-selected').forEach((el) => el.classList.remove('is-selected'));
}

function _deleteTextObject(el) {
  const id = parseInt(el.dataset.id, 10);
  _st.textObjects = _st.textObjects.filter((t) => t.id !== id);
  el.remove();
}

// ==================== 底图加载 ====================

function _loadBgImage(src) {
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    // 画布尺寸适配图片
    _st.canvasW = img.naturalWidth;
    _st.canvasH = img.naturalHeight;
    _bgCanvas.width = _st.canvasW;
    _bgCanvas.height = _st.canvasH;
    _drawCanvas.width = _st.canvasW;
    _drawCanvas.height = _st.canvasH;
    _canvasWrap.style.width = _st.canvasW + 'px';
    _canvasWrap.style.height = _st.canvasH + 'px';
    _textLayer.style.width = _st.canvasW + 'px';
    _textLayer.style.height = _st.canvasH + 'px';
    _bgCtx.drawImage(img, 0, 0);
    _st.bgReady = true;
    _fitToView();
    _pushHistory();
  };
  img.onerror = () => {
    showToast('底图加载失败');
    _bgCtx.fillStyle = '#ffffff';
    _bgCtx.fillRect(0, 0, _st.canvasW, _st.canvasH);
    _st.bgReady = true;
    _pushHistory();
  };
  img.src = src;
}

// ==================== 确定导出 ====================

function _onConfirm() {
  // 1. 把文字渲染到 drawCanvas
  _st.textObjects.forEach((t) => {
    if (!t.text) return;
    _drawCtx.save();
    _drawCtx.translate(t.x, t.y);
    _drawCtx.rotate(t.rotation * Math.PI / 180);
    _drawCtx.font = `${t.fontSize}px sans-serif`;
    _drawCtx.fillStyle = t.color;
    _drawCtx.textBaseline = 'top';
    // 多行支持
    const lines = t.text.split('\n');
    lines.forEach((line, i) => {
      _drawCtx.fillText(line, 0, i * t.fontSize * 1.2);
    });
    _drawCtx.restore();
  });

  // 2. 合并 bg + draw
  const merged = document.createElement('canvas');
  merged.width = _st.canvasW;
  merged.height = _st.canvasH;
  const mctx = merged.getContext('2d');
  mctx.drawImage(_bgCanvas, 0, 0);
  mctx.drawImage(_drawCanvas, 0, 0);

  // 3. 导出 dataURL → File
  const dataUrl = merged.toDataURL('image/png');
  const blob = _dataUrlToBlob(dataUrl);
  let name;
  if (_st.mode === 'edit' && _st.originalName) {
    const base = _st.originalName.replace(/\.[^.]+$/, '');
    name = `${base}_edited.png`;
  } else {
    name = `canvas_${Date.now()}.png`;
  }
  const file = new File([blob], name, { type: 'image/png' });

  // 4. 更新 pendingFiles
  if (_st.mode === 'edit' && _st.originalIdx >= 0 && _st.originalIdx < state.pendingFiles.length) {
    state.pendingFiles[_st.originalIdx] = file;
  } else {
    state.pendingFiles = dedupePendingFiles([...state.pendingFiles, file]);
  }

  // 5. 重新渲染附件区（动态 import 避免循环依赖）
  import('./chat-render.js').then((m) => {
    if (m.renderAttachmentChips) m.renderAttachmentChips();
  }).catch(() => {});

  // 6. 关闭
  closeCanvasEditor();
  showToast('图像已保存到附件区');
}

function _dataUrlToBlob(dataUrl) {
  const arr = dataUrl.split(',');
  const mime = arr[0].match(/:(.*?);/)[1];
  const bstr = atob(arr[1]);
  let n = bstr.length;
  const u8 = new Uint8Array(n);
  while (n--) u8[n] = bstr.charCodeAt(n);
  return new Blob([u8], { type: mime });
}
