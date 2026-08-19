// layout.js -- 侧栏 / 背景 / 标题栏 / 响应式

import { $ } from './utils.js';
import { state, STORAGE_DOF, STORAGE_VIG, STORAGE_HEADER_COLLAPSED } from './state.js';

const appRoot = $("app");
const mainPanel = $("mainPanel");
const menuBtn = $("menuBtn");
const drawerBackdrop = $("drawerBackdrop");
const bgImageLayer = $("bgImageLayer");
const headerToggleBtn = $("headerToggleBtn");
const dofRange = $("dofRange");
const dofValue = $("dofValue");
const vignetteRange = $("vignetteRange");
const vignetteValue = $("vignetteValue");

const STORAGE_SIDEBAR_W = "minor_sidebar_width";
const SIDEBAR_MIN_W = 150;
const SIDEBAR_MAX_W = 420;

function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = collapsed;
  if (!appRoot) return;
  appRoot.classList.toggle("sidebar-collapsed", collapsed);
}

function setDrawerOpen(open) {
  if (!appRoot) return;
  appRoot.classList.toggle("drawer-open", open);
  if (menuBtn) menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
  if (drawerBackdrop) drawerBackdrop.setAttribute("aria-hidden", open ? "false" : "true");
}

function updateMobileLayout() {
  if (!appRoot) return;
  const mobile = window.matchMedia("(max-width: 768px)").matches;
  appRoot.classList.toggle("is-mobile", mobile);
  if (!mobile) setDrawerOpen(false);
}

function closeDrawerIfMobile() {
  if (!appRoot) return;
  if (appRoot.classList.contains("is-mobile")) setDrawerOpen(false);
}

// ===== 标题栏 =====
function setHeaderCollapsed(collapsed) {
  if (!mainPanel || !headerToggleBtn) return;
  mainPanel.classList.toggle("header-collapsed", collapsed);
  headerToggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  headerToggleBtn.title = collapsed ? "展开标题栏" : "收起标题栏";
  headerToggleBtn.textContent = collapsed ? "\u25BE" : "\u25B4";
  try {
    localStorage.setItem(STORAGE_HEADER_COLLAPSED, collapsed ? "1" : "0");
  } catch { /* ignore */ }
}

function loadHeaderPref() {
  if (!mainPanel || !headerToggleBtn) return;
  try {
    if (localStorage.getItem(STORAGE_HEADER_COLLAPSED) === "1") setHeaderCollapsed(true);
  } catch { /* ignore */ }
}

// ===== 背景控制 =====
function applyBgVars() {
  const dofPx = dofRange ? String(dofRange.value) : "0";
  const vig = vignetteRange ? Number(vignetteRange.value) / 100 : 0.35;
  document.documentElement.style.setProperty("--bg-dof", `${dofPx}px`);
  document.documentElement.style.setProperty("--bg-vignette", String(Math.max(0, Math.min(1, vig))));
  if (dofValue) dofValue.textContent = `${dofPx} px`;
  if (vignetteValue) vignetteValue.textContent = `${vignetteRange ? vignetteRange.value : 35} %`;
  applyBackgroundFit();
}

function loadBgPrefs() {
  try {
    const d = localStorage.getItem(STORAGE_DOF);
    if (d != null && dofRange) dofRange.value = d;
    const v = localStorage.getItem(STORAGE_VIG);
    if (v != null && vignetteRange) vignetteRange.value = v;
  } catch { /* ignore */ }
  applyBgVars();
}

let bgNaturalW = 0;
let bgNaturalH = 0;
let bgFitTimer = null;

function backgroundImageHref() {
  try {
    return new URL("image/background.jpg", window.location.href).href;
  } catch {
    return "image/background.jpg";
  }
}

function readDofPx() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--bg-dof").trim();
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : 0;
}

function applyBackgroundFit() {
  if (!bgImageLayer || !bgNaturalW || !bgNaturalH) return;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const s = Math.max(vw / bgNaturalW, vh / bgNaturalH);
  const dof = readDofPx();
  const bleed = 1 + Math.min(Math.max(dof, 0), 24) * 0.018;
  const bw = bgNaturalW * s * bleed;
  const bh = bgNaturalH * s * bleed;
  bgImageLayer.style.backgroundSize = `${bw}px ${bh}px`;
  bgImageLayer.style.backgroundPosition = "center center";
}

function scheduleBackgroundFit() {
  if (bgFitTimer) clearTimeout(bgFitTimer);
  bgFitTimer = setTimeout(() => {
    bgFitTimer = null;
    applyBackgroundFit();
  }, 100);
}

function wireBackgroundImage() {
  if (!bgImageLayer) return;
  const href = backgroundImageHref();
  bgImageLayer.style.backgroundImage = `url(${JSON.stringify(href)})`;
  const probe = new Image();
  probe.onload = () => {
    bgNaturalW = probe.naturalWidth;
    bgNaturalH = probe.naturalHeight;
    if (bgNaturalW > 0 && bgNaturalH > 0) applyBackgroundFit();
  };
  probe.onerror = () => {
    bgNaturalW = 0;
    bgNaturalH = 0;
    bgImageLayer.style.backgroundSize = "cover";
  };
  probe.src = href;
}

function onResizeLayout() {
  updateMobileLayout();
  scheduleBackgroundFit();
}

// 初始化背景与标题栏
loadBgPrefs();
loadHeaderPref();

if (dofRange) {
  dofRange.addEventListener("input", () => {
    applyBgVars();
    applyBackgroundFit();
    try { localStorage.setItem(STORAGE_DOF, dofRange.value); } catch { /* ignore */ }
  });
}
if (vignetteRange) {
  vignetteRange.addEventListener("input", () => {
    applyBgVars();
    try { localStorage.setItem(STORAGE_VIG, vignetteRange.value); } catch { /* ignore */ }
  });
}

window.addEventListener("resize", onResizeLayout);
updateMobileLayout();
wireBackgroundImage();

// ===== 侧栏拖动调整宽度 =====
function initSidebarResize() {
  const sidebar = document.getElementById("sidebar");
  const handle = document.getElementById("sidebarResizeHandle");
  if (!sidebar || !handle) return;

  // 恢复保存的宽度
  try {
    const saved = localStorage.getItem(STORAGE_SIDEBAR_W);
    if (saved) {
      const w = parseInt(saved, 10);
      if (w >= SIDEBAR_MIN_W && w <= SIDEBAR_MAX_W) {
        document.documentElement.style.setProperty("--sidebar-w", w + "px");
      }
    }
  } catch { /* ignore */ }

  let dragging = false;
  let startX = 0;
  let startW = 0;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    if (appRoot && appRoot.classList.contains("sidebar-collapsed")) return;
    dragging = true;
    startX = e.clientX;
    startW = sidebar.getBoundingClientRect().width;
    // 拖动时禁用 transition 以保证流畅
    sidebar.style.transition = "none";
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });

  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    let newW = startW + dx;
    newW = Math.max(SIDEBAR_MIN_W, Math.min(SIDEBAR_MAX_W, newW));
    document.documentElement.style.setProperty("--sidebar-w", newW + "px");
  });

  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    // 恢复 transition
    sidebar.style.transition = "";
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    // 保存宽度
    const finalW = sidebar.getBoundingClientRect().width;
    try { localStorage.setItem(STORAGE_SIDEBAR_W, String(Math.round(finalW))); } catch { /* ignore */ }
  });
}

initSidebarResize();

if (headerToggleBtn) {
  headerToggleBtn.addEventListener("click", () => {
    setHeaderCollapsed(!mainPanel.classList.contains("header-collapsed"));
  });
}

export {
  setSidebarCollapsed, setDrawerOpen, closeDrawerIfMobile,
};
