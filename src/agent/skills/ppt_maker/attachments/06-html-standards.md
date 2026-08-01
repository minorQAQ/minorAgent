# 06 — HTML 技术约束与规范

> **角色**：HTML 路线硬约束手册 — 画布结构、CSS 能力边界、字体栈、动效引擎
> **读取时机**：HTML 路线 Executor 阶段编写 HTML 前
> **参考来源**：oh-my-ppt 的 data-anim 动效体系 + CSS 规范

---

## 一、画布与容器规范

### ⛔ 画布尺寸强制校验

> **这是本文件最重要的规则。画布尺寸错误是最高优先级禁止项。**

| 用户选择 | 根 div 强制宽高 | 禁止值 |
|----------|---------------|--------|
| 16:9 | `width:1280px;height:720px` | 1920×1080、1366×768、2560×1440 等一切非 1280×720 的值 |
| 4:3 | `width:1024px;height:768px` | 800×600、1600×1200 等一切非 1024×768 的值 |
| A4纵向 | `width:720px;height:1280px` | 595×842 等一切非 720×1280 的值 |

**画布硬约束**：
- 所有页面必须使用完全相同的根 div 尺寸，禁止页间尺寸不一致
- Agent 不得自行决定画布尺寸，必须严格使用上表中的值
- 生成每页 HTML 前必须确认根 div 尺寸与上表一致

### 根容器模板

每页 HTML 必须是一个**自包含的 HTML 文档**（含 `<html>` `<head>` `<body>`），根 div 尺寸锁死 1280×720：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="ppt-page" content="{N}">
<meta name="ppt-total" content="{T}">
</head>
<body style="margin:0;padding:0;display:flex;align-items:center;justify-content:center;
            min-height:100vh;background:#E5E7EB;">

<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <!-- 页面内容 -->
</div>

</body>
</html>
```

### 格式对照

| 格式 | 宽 × 高 | 根 div style |
|------|---------|-------------|
| `ppt169` | 1280 × 720 | `width:1280px;height:720px` |
| `ppt43` | 1024 × 768 | `width:1024px;height:768px` |

### 硬约束汇总

| # | 规则 | 说明 |
|---|------|------|
| 1 | 根 div 尺寸固定 | `width:1280px;height:720px;position:relative;overflow:hidden` |
| 2 | 所有内容必须在 1280×720 内 | 超出部分被 `overflow:hidden` 裁剪 |
| 3 | 禁止 `position:fixed` / `position:sticky` | 页面在固定尺寸容器内渲染 |
| 4 | 优先 `position:absolute` 或 `flex`/`grid` | 精确控制元素位置 |
| 5 | 文本中的 `&` 必须转义为 `&amp;` | XML/HTML 解析器强制要求 |
| 6 | 所有样式在单个 `<style>` 块或内联 `style` 中 | 禁止外部 CSS / `<link>` / `@import` |

---

## 二、CSS 规则

### CSS 组织方式

样式写在根 div 内的 `<style>` 标签中，**只能在 `<style>` 中定义 CSS 自定义属性（`:root`）和通用类**。具体元素的样式使用内联 `style="..."`。

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC;
      --primary: #1A73E8;
      --secondary: #4285F4;
      --accent: #FF6D00;
      --text: #1F2937;
      --muted: #6B7280;
      --card-bg: #FFFFFF;
      --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <h1 style="font-size:48px;color:var(--text);">标题</h1>
</div>
```

### CSS 自定义属性清单

| 变量名 | 用途 | 示例值 |
|--------|------|--------|
| `--bg` | 页面背景色 | `#FAFBFC` |
| `--primary` | 主色（标题栏、主按钮、强调区） | `#1A73E8` |
| `--secondary` | 辅色（次要区域、图表副系列） | `#4285F4` |
| `--accent` | 强调色（高亮、关键数字、CTA） | `#FF6D00` |
| `--text` | 正文颜色 | `#1F2937` |
| `--muted` | 弱化色（副文本、脚注） | `#6B7280` |
| `--card-bg` | 卡片背景色 | `#FFFFFF` |
| `--card-shadow` | 卡片阴影 | `0 2px 12px rgba(0,0,0,0.08)` |
| `--border-color` | 边框/分割线颜色 | `#E5E7EB` |

### CSS 能力边界

| ✅ 支持 | ❌ 禁止 |
|---------|--------|
| `flexbox` / `display:grid` | **`@keyframes` / CSS animation — ⛔ 最高优先级禁止** |
| `linear-gradient` / `radial-gradient` | `@font-face` / 自定义字体 |
| `box-shadow` / `border-radius` | `position:fixed` / `position:sticky` |
| `transform` (2D: `translate`, `rotate`, `scale`, `skew`) | EXIF 图片引用（CDN、Google Fonts） |
| `opacity` / `rgba` / `hsla` | `<link>` / `@import` 外部样式表 |
| `filter`（仅 `blur`） | 非标准 CSS（`-webkit-` 前缀仅限 `backdrop-filter`） |
| `clip-path`（基础形状） | CSS `calc()` 的复杂嵌套 |
| `backdrop-filter: blur()` | `position:absolute` 嵌套超过 4 层 |
| `text-shadow` | 非图片 `filter`（如 `contrast`、`hue-rotate`） |

---

## 三、HTML 结构规范

### 结构层级

- 推荐 **≤ 4 层嵌套**（根 div → 区块 → 子元素 → 文本）
- 扁平优先，避免深层 div 嵌套
- 每个逻辑区块用独立 `<div>` 包裹

### 语义标签

| 标签 | 用途 |
|------|------|
| `<section>` | 页面大区块（不常用） |
| `<div>` | 通用容器 |
| `<h1>` ~ `<h6>` | 标题层级 |
| `<p>` | 段落文本 |
| `<span>` | 内联文本 / 小型装饰 |
| `<img>` | 图片 |

### 禁止元素

| 标签 | 原因 |
|------|------|
| `<script>` | 除动效引擎 + 键盘导航外的任何 JS 禁止 |
| `<iframe>` | 安全风险 + 不可控渲染 |
| `<video>` / `<audio>` | 静态 PPT 不需要多媒体 |
| `<canvas>` | 不需要动态绘图 |
| `<form>` / `<input>` | 非交互式页面 |
| `<link>` | 禁止外部资源引用 |

### 闭合规则

- 每个标签必须正确闭合
- 自闭合标签写为 `<img ... />` 或 `<img ...>`
- 属性值用双引号 `"..."` 包裹

---

## 四、图片规范

### ⛔ 图片路径强制规则

> **所有图片引用必须使用绝对路径，绝对禁止相对路径。**

```html
<!-- ✅ 正确：绝对路径 -->
<img src="C:/Users/86166/Desktop/Agent_Learning_minor/Agent/src/agent/history/sessions/20260724_134021/tranformer_20260724_134021_1.png"
     style="width:540px;height:360px;object-fit:contain;" alt="图表">

<!-- ✅ 正确：背景图绝对路径 -->
<div style="background-image:url('C:/Users/.../bg.png');background-size:cover;background-position:center;"></div>

<!-- ❌ 错误：相对路径 — 绝对禁止 -->
<img src="./tranformer.png" ...>
<img src="../images/xxx.png" ...>
<div style="background-image:url('./bg.png');">
```

**为什么要绝对路径**：
- PPT 的 HTML 文件在 `workspace/ppt_{topic}/`，用户图片在 `sessions/{session_id}/`，二者目录不同，相对路径无法解析
- `attachments/complete_htmls_to_base64.py` 脚本需要绝对路径才能正确读取图片文件并转为 base64

### 引用方式

```html
<!-- 图片引用使用绝对路径 -->
<img src="C:/Users/.../chart_1.png" style="width:540px;height:360px;object-fit:contain;" alt="图表">

<!-- 背景图使用绝对路径 -->
<div style="background-image:url('C:/Users/.../bg.png');background-size:cover;background-position:center;"></div>
```

### 图片容器规范

```html
<!-- 填充容器 -->
<div style="width:560px;height:400px;border-radius:16px;overflow:hidden;">
  <img src="./image.jpg" style="width:100%;height:100%;object-fit:cover;" alt="描述">
</div>
```

| 属性 | 推荐值 | 说明 |
|------|--------|------|
| `object-fit` | `cover`（填充）/ `contain`（图表） | 控制缩放方式 |
| 容器 | 必须有显式 `width` × `height` | 避免布局抖动 |
| `border-radius` | 16px | 图片容器圆角 |

### 图片路径

- **生成时**：使用**绝对路径**引用图片（如 `C:/Users/.../xxx.png`），禁止相对路径
- **交付前**：用 `attachments/complete_htmls_to_base64.py` 将外部引用转为内联 base64 Data URI
- **禁止**：手写 `data:image/...;base64,...`、禁止相对路径 `./xxx.png`

---

## 五、字体规范

### 系统安全字体栈

| 类别 | 字体栈 |
|------|--------|
| 中文无衬线 | `"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif` |
| 英文无衬线 | `"Inter", "Calibri", "Segoe UI", sans-serif` |
| 衬线 | `"Noto Serif SC", "Georgia", "Times New Roman", serif` |
| 等宽 | `"Consolas", "Fira Code", "Courier New", monospace` |

### 字号层级

| 角色 | 字号 | 字重 | 用途 |
|------|------|------|------|
| Hero 标题 | 56-64px | Bold (700) | 封面超大标题 |
| 主标题 | 48px | Bold (700) | 封面/过渡页标题 |
| 章节标题 | 42px | Bold (700) | 章节过渡页 |
| 页面标题 | 32px | Bold (700) | 内容页标题 |
| 副标题 | 24-28px | Regular (400) | 副标题 |
| 卡片标题 | 18-22px | Bold (700) | 卡片 / 面板标题 |
| 正文 | 15-16px | Regular (400) | 正文描述 |
| KPI 数值 | 36px | Bold (700) | KPI 指标数字 |
| 大字 | 80-96px | Bold (700) | breathing 大字 |
| 脚注 | 12-14px | Regular (400) | 来源 / 日期 |

### 行高规范

| 场景 | line-height |
|------|-------------|
| 标题 | `1.2` ~ `1.3` |
| 正文 | `1.5` ~ `1.7` |
| 脚注 | `1.4` |

---

## 六、动效引擎 + 键盘翻页导航（data-anim 系统）

> 每页 HTML 中**必须**在根 div 内包含以下脚本。这是**整个文档中唯一允许的** `<script>` 标签，包含动效引擎和键盘翻页导航。

### 动效引擎 + 导航脚本

```html
<script>
(function(){
  // ===== 动效引擎 =====
  const els=document.querySelectorAll('[data-anim]');
  const staggerEls=document.querySelectorAll('[data-anim-stagger]');
  const seqEls=document.querySelectorAll('[data-anim-sequence]');
  let clickGroup=0;
  const groups={};

  function initEl(el){
    const anim=el.getAttribute('data-anim')||'fade-in';
    const dur=el.getAttribute('data-anim-duration')||'0.6s';
    el.style.transition=`opacity ${dur} ease, transform ${dur} ease, clip-path ${dur} ease`;
    el.style.opacity='0';
    if(anim.includes('up')) el.style.transform='translateY(30px)';
    else if(anim.includes('left')) el.style.transform='translateX(-60px)';
    else if(anim.includes('right')) el.style.transform='translateX(60px)';
    else if(anim==='scale-in'||anim==='zoom-in') el.style.transform='scale(0.8)';
    else if(anim==='wipe-right') el.style.clipPath='inset(0 100% 0 0)';
    else el.style.transform='translateY(0)';
  }

  function showEl(el){
    el.style.opacity='1';
    el.style.transform='translate(0,0) scale(1)';
    el.style.clipPath='inset(0 0 0 0)';
  }

  els.forEach(el=>{
    initEl(el);
    const grp=el.getAttribute('data-anim-click-group');
    if(grp){ if(!groups[grp]) groups[grp]=[]; groups[grp].push(el); return; }
    const delay=parseFloat(el.getAttribute('data-anim-delay')||'0')*1000;
    setTimeout(()=>showEl(el),delay+50);
  });

  staggerEls.forEach(container=>{
    const children=container.querySelectorAll('[data-anim]');
    children.forEach((ch,i)=>{ initEl(ch); setTimeout(()=>showEl(ch),i*50+100); });
  });

  seqEls.forEach(container=>{
    const children=container.querySelectorAll('[data-anim]');
    let total=0;
    children.forEach(ch=>{
      const d=parseFloat(ch.getAttribute('data-anim-duration')||'0.6')*1000;
      const delay=parseFloat(ch.getAttribute('data-anim-delay')||'0')*1000;
      initEl(ch); total+=delay; setTimeout(()=>showEl(ch),total+100); total+=d;
    });
  });

  document.addEventListener('click',()=>{
    clickGroup++;
    (groups[clickGroup]||[]).forEach(el=>showEl(el));
  });

  // ===== 键盘翻页导航 =====
  var metaPage=document.querySelector('meta[name="ppt-page"]');
  var metaTotal=document.querySelector('meta[name="ppt-total"]');
  if(metaPage&&metaTotal){
    var cur=parseInt(metaPage.getAttribute('content'));
    var tot=parseInt(metaTotal.getAttribute('content'));
    if(!isNaN(cur)&&!isNaN(tot)&&tot>1){
      var ov=null;
      function showOv(dir){
        if(!ov){
          ov=document.createElement('div');
          ov.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;pointer-events:none;z-index:99999;background:rgba(0,0,0,0.25);opacity:0;transition:opacity 0.2s;font-size:36px;color:#fff;font-family:sans-serif;letter-spacing:2px;';
          document.body.appendChild(ov);
        }
        ov.textContent=dir==='prev'?'\u25C0 '+cur+' / '+tot:(cur+1)+' / '+tot+' \u25B6';
        ov.style.opacity='1';
        setTimeout(function(){ov.style.opacity='0';},500);
      }
      document.addEventListener('keydown',function(e){
        if(e.key==='ArrowRight'||e.key==='Right'){
          e.preventDefault();
          if(cur<tot){showOv('next');setTimeout(function(){window.location.href=(cur+1)+'.html';},150);}
        }else if(e.key==='ArrowLeft'||e.key==='Left'){
          e.preventDefault();
          if(cur>1){showOv('prev');setTimeout(function(){window.location.href=(cur-1)+'.html';},150);}
        }
      });
    }
  }
})();
</script>
```

### 支持属性一览

| 属性 | 值 | 说明 |
|------|-----|------|
| `data-anim` | `"fade-up"` | 动效类型（见下表） |
| `data-anim-delay` | `"0.3s"` | 延迟（秒），默认 `0` |
| `data-anim-duration` | `"0.8s"` | 时长（秒），默认 `0.6s` |
| `data-anim-stagger` | 无需值，仅存在即生效 | 容器上：子元素依次出现（50ms 间隔） |
| `data-anim-sequence` | 无需值，仅存在即生效 | 容器上：子元素逐个出现（完成后再下一个） |
| `data-anim-click-group` | `"1"` | 点击分组：页面点击后该组元素同时出现 |

### 动效类型表

| 值 | 初始状态 | 最终状态 | 视觉效果 |
|----|----------|----------|----------|
| `fade-up` | opacity:0, translateY(30px) | opacity:1, translateY(0) | 从下方淡入 30px |
| `fade-in` | opacity:0 | opacity:1 | 简单淡入 |
| `scale-in` | opacity:0, scale(0.8) | opacity:1, scale(1) | 缩放 + 淡入 |
| `slide-left` | opacity:0, translateX(-60px) | opacity:1, translateX(0) | 从左侧滑入 60px |
| `slide-right` | opacity:0, translateX(60px) | opacity:1, translateX(0) | 从右侧滑入 60px |
| `wipe-right` | clip-path: inset(0 100% 0 0) | clip-path: inset(0 0 0 0) | 从左到右揭示 |
| `zoom-in` | opacity:0, scale(0.5) | opacity:1, scale(1) | 从小放大进入 |
| `pulse-soft` | opacity:0, scale(0.9) | opacity:1, scale(1) | 轻柔脉冲（CTA 用） |

### 动效使用原则

1. **每页 ≤ 6 个独立 data-anim 元素**
2. **列表/卡片优先用 `data-anim-stagger`**，不逐个设 delay
3. **封面/章节页 1 个 hero 动效 + 次级动效**
4. **breathing 页面 ≤ 2 个动效元素**
5. **dense 页面：标题 → stagger 卡片 → 补充**
6. **`wipe-right` 仅用于线/条元素**（如下划线、装饰条、底部色条）
7. **`pulse-soft` 仅用于 CTA 或关键数字**，不滥用

---

## 七、禁止事项清单

| 类别 | 禁止项 | 替代方案 |
|------|--------|----------|
| **脚本** | `<script>`（除动效引擎 + 键盘导航外） | 无 |
| **样式** | 外部 CSS `<link>` / `@import` | `<style>` 块 + 内联 `style` |
| **字体** | `@font-face` / Google Fonts / CDN 字体 | 系统安全字体栈 |
| **定位** | `position:fixed` / `position:sticky` | `position:absolute` |
| **媒体** | `<iframe>` / `<video>` / `<audio>` | 静态 `<img>` |
| **动画** | CSS `animation` / `@keyframes` | `data-anim` 动效引擎 |
| **特殊字符** | 裸 `&` | 转义为 `&amp;` |
| **图片** | 相对路径（`./xxx.png`）、手写 base64 Data URI | 绝对路径 + 交付前固化脚本 |
| **嵌套** | > 4 层 div 嵌套 | 扁平化结构 |
| **filter** | `contrast` / `hue-rotate` / `saturate` 等 | 仅用 `blur` |
| **画布** | 1920×1080、1366×768 等非标准尺寸 | 仅 1280×720（16:9）/ 1024×768（4:3）/ 720×1280（A4纵向） |
| **布局** | 依赖 flex/grid/文档流自动排列 | 全部 `position:absolute` 显式定位 |
