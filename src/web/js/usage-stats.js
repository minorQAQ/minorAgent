// usage-stats.js -- Token 用量活跃度卡
// GitHub 风格矩阵（横=周一到周日，竖=周，近半年）+ 点击方块切换为
// 该日按小时柱状图（同一柱内按模型分深浅）。颜色随主题：0 级灰色(--border)，
// 1~5 级基于 --accent 的透明度阶梯。

import { api } from './api.js';

const GRID_DAYS = 182;   // 最近半年
const WEEKS = 26;        // 182 / 7

let _rgb = null;         // 缓存的 --accent RGB
let _usage = null;       // 最近一次 /api/stats/usage 数据
let _view = "matrix";    // matrix | bars
let _selectedDate = "";  // 柱状图选中的日期 YYYY-MM-DD
let _models = [];        // 全局模型列表（按用量降序，用于柱内分色稳定）

function _accentRgb() {
  if (_rgb) return _rgb;
  let hex = "";
  try {
    hex = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  } catch { /* ignore */ }
  if (!hex) hex = "#4f8ff7";
  hex = hex.replace("#", "");
  if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
  const n = parseInt(hex, 16);
  if (Number.isNaN(n)) { _rgb = [79, 143, 247]; return _rgb; }
  _rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return _rgb;
}

/** 等级颜色：0 返回 null（走 CSS 灰色 var(--border)），1~5 为 accent 透明度阶梯 */
function _levelColor(level) {
  if (level <= 0) return null;
  const [r, g, b] = _accentRgb();
  const alpha = 0.18 + level * 0.16;   // 0.34 ~ 0.98
  return `rgba(${r}, ${g}, ${b}, ${Math.min(alpha, 0.98)})`;
}

/** 模型在柱内的深浅（0.35 ~ 0.95，模型越多区分度越大） */
function _modelColor(index, count) {
  const [r, g, b] = _accentRgb();
  const alpha = count <= 1 ? 0.85 : 0.35 + (index / Math.max(count - 1, 1)) * 0.6;
  return `rgba(${r}, ${g}, ${b}, ${Math.min(alpha, 0.95)})`;
}

function _fmtDate(d) {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/** 所在周的周一（JS getDay 0=周日，转周一=0） */
function _startOfWeek(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - dow);
  return x;
}

/** 按非 0 用量的分位数计算 total -> level(0..5) 的映射函数 */
function _buildLeveler(totals) {
  const vals = [...new Set(totals.filter((t) => t > 0))].sort((a, b) => a - b);
  if (!vals.length) return () => 0;
  const p = (q) => vals[Math.min(vals.length - 1, Math.floor(vals.length * q))];
  // 去重后取 5 个严格递增的阈值
  const thresholds = [];
  for (const q of [0.25, 0.5, 0.75, 0.9, 1]) {
    const v = p(q);
    if (!thresholds.length || v > thresholds[thresholds.length - 1]) thresholds.push(v);
  }
  return (t) => {
    if (t <= 0) return 0;
    let lvl = 1;
    for (let i = 0; i < thresholds.length; i++) if (t >= thresholds[i]) lvl = i + 2;
    return Math.min(lvl, 5);
  };
}

const DOW_NAMES = ["一", "二", "三", "四", "五", "六", "日"];

/** 按周组织 182 天网格（GitHub 风格）：columns[0] 最老、columns[25] 最新（最右），
 *  每列 7 格 = 周一到周日（周一在最上）。每列 label 为月份（每月首周显示 "M月"）。 */
function _buildColumns(days) {
  const dayMap = {};
  (days || []).forEach((d) => { dayMap[d.date] = d.total || 0; });
  const today = new Date();
  const todayKey = _fmtDate(today);
  const lastMonday = _startOfWeek(today);
  const columns = [];
  let lastMonth = -1;
  for (let w = WEEKS - 1; w >= 0; w--) {
    const weekStart = new Date(lastMonday.getTime() - w * 7 * 86400000);
    const cells = [];
    for (let dow = 0; dow < 7; dow++) {
      const d = new Date(weekStart.getTime() + dow * 86400000);
      const key = _fmtDate(d);
      cells.push({ date: key, total: dayMap[key] || 0, future: key > todayKey });
    }
    const m = weekStart.getMonth();
    columns.push({
      label: m !== lastMonth ? `${m + 1}月` : "",
      startDate: _fmtDate(weekStart),
      cells,
    });
    lastMonth = m;
  }
  return columns;
}

function _card() {
  return document.getElementById("usageCard");
}

async function _loadUsage() {
  try {
    const data = await api("/api/stats/usage");
    _usage = data || {};
    _models = Object.entries((data && data.by_model) || {})
      .sort((a, b) => b[1] - a[1])
      .map(([m]) => m);
  } catch {
    _usage = null;
  }
}

function _renderMatrix() {
  const card = _card();
  if (!card) return;
  _view = "matrix";
  card.innerHTML = "";

  const header = document.createElement("div");
  header.className = "usage-card-header";
  const title = document.createElement("span");
  title.textContent = "Token 活跃度（近半年，点击方块查看每小时用量）";
  header.appendChild(title);

  const legend = document.createElement("div");
  legend.className = "usage-legend";
  legend.innerHTML = '<span>少</span>' +
    '<span class="legend-cell"></span>' +
    '<span class="legend-cell legend-cell--l2"></span>' +
    '<span class="legend-cell legend-cell--l4"></span>' +
    '<span class="legend-cell legend-cell--l5"></span>' +
    '<span>多</span>';
  header.appendChild(legend);
  card.appendChild(header);

  const body = document.createElement("div");
  body.className = "usage-matrix-body";

  if (!_usage || !Array.isArray(_usage.days) || _usage.days.length === 0) {
    const empty = document.createElement("div");
    empty.className = "usage-empty";
    empty.textContent = "暂无 Token 用量记录，发送消息后这里会出现你的活跃度。";
    body.appendChild(empty);
    card.appendChild(body);
    return;
  }

  // 等级色样（legend 与格子一致，随主题）
  card.querySelectorAll(".legend-cell").forEach((el) => {
    const lvl = el.classList.contains("legend-cell--l2") ? 2 : el.classList.contains("legend-cell--l4") ? 4 : el.classList.contains("legend-cell--l5") ? 5 : 1;
    const color = _levelColor(lvl);
    if (color) el.style.background = color;
  });

  const leveler = _buildLeveler(_usage.days.map((d) => d.total || 0));
  const columns = _buildColumns(_usage.days);

  // 网格：第一列星期标签 + 26 列周；第一行月标签
  const grid = document.createElement("div");
  grid.className = "usage-grid";

  // 第一行：空角 + 每列月标签
  const corner = document.createElement("div");
  corner.className = "usage-dow-label";
  grid.appendChild(corner);
  columns.forEach((col) => {
    const lbl = document.createElement("div");
    lbl.className = "usage-col-label";
    lbl.textContent = col.label;
    lbl.title = col.startDate;
    grid.appendChild(lbl);
  });

  // 7 行：星期标签 + 26 格（横=周，竖=周一到周日，周一在最上）
  for (let dow = 0; dow < 7; dow++) {
    const dowLabel = document.createElement("div");
    dowLabel.className = "usage-dow-label";
    dowLabel.textContent = DOW_NAMES[dow];
    grid.appendChild(dowLabel);
    columns.forEach((col) => {
      const cell = col.cells[dow];
      const el = document.createElement("div");
      el.className = "usage-cell" + (cell.future ? " usage-cell--empty" : "");
      if (cell.future) {
        grid.appendChild(el);
        return;
      }
      const lvl = leveler(cell.total);
      const color = _levelColor(lvl);
      if (color) el.style.background = color;
      // 任意日期都可点击查看当天每小时柱状图（0 值日期显示空态）
      el.title = `${cell.date} · ${cell.total.toLocaleString()} tokens`;
      el.addEventListener("click", () => _renderBars(cell.date));
      grid.appendChild(el);
    });
  }

  body.appendChild(grid);
  card.appendChild(body);
}

function _renderBars(date) {
  const card = _card();
  if (!card) return;
  _view = "bars";
  _selectedDate = date;
  card.innerHTML = "";

  const hours = (_usage && _usage.hours && _usage.hours[date]) || {};
  const header = document.createElement("div");
  header.className = "usage-card-header";

  const title = document.createElement("span");
  title.textContent = `${date} · 每小时 Token 用量（同柱按模型分色）`;

  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "usage-back-btn";
  backBtn.title = "返回矩阵";
  backBtn.style.display = "inline-flex";   // 柱状图视图下显示（CSS 默认隐藏）
  const backIcon = document.createElement("img");
  backIcon.src = "/image/撤回.svg";
  backIcon.alt = "返回矩阵";
  backIcon.className = "usage-back-icon";
  backBtn.appendChild(backIcon);
  backBtn.addEventListener("click", () => _renderMatrix());
  header.appendChild(title);
  header.appendChild(backBtn);
  card.appendChild(header);

  const body = document.createElement("div");
  body.className = "usage-bars-wrap";

  const entries = Object.entries(hours).map(([h, byModel]) => {
    let total = 0;
    const parts = [];
    // 柱内模型顺序与全局一致（用量多的排下），深浅递增
    _models.forEach((m) => {
      const v = byModel[m] || 0;
      if (v > 0) parts.push({ model: m, value: v });
    });
    // 未在全局列表中的模型（异常）兜底
    Object.entries(byModel).forEach(([m, v]) => {
      if (v > 0 && !_models.includes(m)) parts.push({ model: m, value: v });
    });
    total = parts.reduce((s, p) => s + p.value, 0);
    return { hour: h, total, parts };
  });

  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "usage-empty";
    empty.textContent = "这一天没有 Token 用量记录。";
    body.appendChild(empty);
    card.appendChild(body);
    return;
  }

  const maxTotal = Math.max(...entries.map((e) => e.total), 1);
  const barsRow = document.createElement("div");
  barsRow.className = "usage-bars";

  // 24 小时补齐空柱（视觉连续）
  for (let h = 0; h < 24; h++) {
    const key = String(h).padStart(2, "0");
    const e = entries.find((x) => x.hour === key);
    const bar = document.createElement("div");
    bar.className = "usage-bar";
    if (!e) {
      bar.style.background = "transparent";
      bar.title = `${key}:00 · 0 tokens`;
      barsRow.appendChild(bar);
      continue;
    }
    bar.style.background = "rgba(0,0,0,0.03)";
    const segTotal = e.total;
    const heightPct = (segTotal / maxTotal) * 100;
    const segContainer = document.createElement("div");
    segContainer.style.cssText = `height:${Math.max(heightPct, 1)}%;display:flex;flex-direction:column;justify-content:flex-end;`;
    e.parts.forEach((p, idx) => {
      const seg = document.createElement("div");
      seg.style.cssText = `background:${_modelColor(idx, e.parts.length)};flex:${p.value};`;
      seg.title = `${key}:00 · ${p.model} ${p.value.toLocaleString()} tokens`;
      segContainer.appendChild(seg);
    });
    bar.appendChild(segContainer);
    bar.title = `${key}:00 · 共 ${segTotal.toLocaleString()} tokens`;
    barsRow.appendChild(bar);
  }
  body.appendChild(barsRow);

  const axis = document.createElement("div");
  axis.className = "usage-bar-axis";
  [0, 6, 12, 18, 23].forEach((h) => {
    const s = document.createElement("span");
    s.textContent = `${h}:00`;
    axis.appendChild(s);
  });
  body.appendChild(axis);

  const legend = document.createElement("div");
  legend.className = "usage-legend";
  legend.style.marginTop = "0.5rem";
  if (_models.length > 1) {
    legend.innerHTML = _models.map((m, i) =>
      `<span class="legend-cell" style="background:${_modelColor(i, _models.length)};display:inline-block"></span><span>${m}</span>`
    ).join("<span style='width:0.6rem'></span>");
  } else {
    legend.textContent = "模型：" + (_models[0] || "未知");
  }
  body.appendChild(legend);

  card.appendChild(body);
}

/**
 * 加载并渲染活跃度卡（保持当前视图：矩阵 / 柱状图的选中日期）。
 * 仅当欢迎区可见时渲染；渲染完成后取消卡的 hidden，使其显示。
 */
export async function refreshUsageCard() {
  const card = _card();
  if (!card) return;
  const welcome = document.getElementById("welcomeView");
  if (welcome && welcome.hidden) return;
  await _loadUsage();
  if (_view === "bars" && _selectedDate) _renderBars(_selectedDate);
  else _renderMatrix();
  card.hidden = false;
}

/**
 * 初始化：绑定主题切换重绘；若欢迎区可见则加载一次。
 */
export async function initUsageCard() {
  document.addEventListener("theme-changed", () => {
    _rgb = null;
    refreshUsageCard();
  });
  refreshUsageCard();
}
