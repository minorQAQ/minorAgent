# 08 — 动画系统（Animation System）：声明式动效引擎与动效目录

> **角色**：HTML 路线动画系统完整参考 — 定义 `data-anim` 声明式动画的全部类型、属性、引擎脚本与使用规范
> **读取时机**：Executor 阶段为 HTML 页面添加动效时
> **前置依赖**：本文件包含每页 HTML 中唯一允许的 `<script>` 标签（动画引擎），直接嵌入使用

---

## 一、动画引擎脚本（完整版）

以下是每页 HTML 末尾必须嵌入的**唯一** `<script>` 标签。引擎约 45 行（压缩后约 35 行），负责解析 `data-anim` 属性并驱动所有 CSS 过渡动画。

### 1.1 引擎源码（可读版）

```javascript
(function() {
  const ANIM_ATTR   = 'data-anim';
  const VISIBLE_CLS = 'anim-visible';
  const STAGGER     = 'data-anim-stagger';
  const SEQUENCE    = 'data-anim-sequence';
  const CLICK_GROUP = 'data-anim-click-group';

  // 初始状态映射：每种动效的起始 CSS
  const initMap = {
    'fade-up':      'transform:translateY(30px);opacity:0;',
    'fade-in':      'opacity:0;',
    'scale-in':     'transform:scale(0.85);opacity:0;',
    'slide-left':   'transform:translateX(-60px);opacity:0;',
    'slide-right':  'transform:translateX(60px);opacity:0;',
    'wipe-right':   'clip-path:inset(0 100% 0 0);opacity:0;',
    'zoom-in':      'transform:scale(0.5);opacity:0;',
    'pulse-soft':   ''
  };

  const clickGroups = {};
  const DEFAULT_DURATION = 0.6;
  const EASE = 'cubic-bezier(0.16, 1, 0.3, 1)';

  // 为元素设置初始状态 + transition
  document.querySelectorAll('[' + ANIM_ATTR + ']').forEach(function(el) {
    var anim = el.getAttribute(ANIM_ATTR);
    if (!anim || !initMap[anim]) return;

    var delay    = parseFloat(el.getAttribute('data-anim-delay') || '0');
    var duration = parseFloat(el.getAttribute('data-anim-duration') || String(DEFAULT_DURATION));
    var trigger  = el.getAttribute('data-anim-trigger') || 'load';

    el.style.cssText +=
      'transition: all ' + duration + 's ' + EASE + ';' +
      initMap[anim];

    // pulse-soft 用 CSS animation 实现（唯一例外）
    if (anim === 'pulse-soft') {
      el.style.cssText += 'animation: pulse-soft-kf 1.5s ease-in-out infinite;';
    }

    if (trigger === 'click') {
      var group = el.getAttribute(CLICK_GROUP);
      if (group) {
        clickGroups[group] = clickGroups[group] || [];
        clickGroups[group].push({ el: el, delay: delay });
      }
    } else {
      // load 触发：按延迟激活
      setTimeout(function() {
        el.classList.add(VISIBLE_CLS);
      }, delay * 1000);
    }
  });

  // --- Stagger：父容器子元素依次激活 ---
  document.querySelectorAll('[' + STAGGER + ']').forEach(function(parent) {
    var gap = parseFloat(parent.getAttribute(STAGGER) || '0.08');
    Array.from(parent.children).filter(function(c) {
      return c.hasAttribute(ANIM_ATTR);
    }).forEach(function(child, i) {
      var existing = parseFloat(child.getAttribute('data-anim-delay') || '0');
      child.setAttribute('data-anim-delay', String(existing + i * gap));
    });
  });

  // --- Sequence：子元素逐个触发（前一个 transitionend 触发下一个） ---
  document.querySelectorAll('[' + SEQUENCE + ']').forEach(function(parent) {
    Array.from(parent.children).filter(function(c) {
      return c.hasAttribute(ANIM_ATTR);
    }).forEach(function(child, i) {
      if (i > 0) child.style.visibility = 'hidden';
      child.addEventListener('transitionend', function handler() {
        if (i + 1 < parent.children.length) {
          var next = parent.children[i + 1];
          next.style.visibility = 'visible';
          next.classList.add(VISIBLE_CLS);
        }
      }, { once: true });
    });
  });

  // --- Click Group：页面点击逐组触发 ---
  document.addEventListener('click', function() {
    Object.values(clickGroups).forEach(function(group) {
      if (group.length > 0) {
        var item = group.shift();
        setTimeout(function() {
          item.el.classList.add(VISIBLE_CLS);
        }, item.delay * 1000);
      }
    });
  });
})();
```

### 1.2 引擎源码（压缩版，可直接嵌入 HTML）

```html
<script>
(function(){const S="data-anim";const V="anim-visible";const G="data-anim-stagger";const Q="data-anim-sequence";const C="data-anim-click-group";const D={};const M={"fade-up":"transform:translateY(30px);opacity:0;","fade-in":"opacity:0;","scale-in":"transform:scale(0.85);opacity:0;","slide-left":"transform:translateX(-60px);opacity:0;","slide-right":"transform:translateX(60px);opacity:0;","wipe-right":"clip-path:inset(0 100% 0 0);opacity:0;","zoom-in":"transform:scale(0.5);opacity:0;","pulse-soft":""};document.querySelectorAll("["+S+"]").forEach(e=>{const a=e.getAttribute(S);if(!a||!M[a])return;const d=parseFloat(e.getAttribute("data-anim-delay")||"0");const r=parseFloat(e.getAttribute("data-anim-duration")||"0.6");const t=e.getAttribute("data-anim-trigger")||"load";e.style.cssText+="transition:all "+r+"s cubic-bezier(0.16,1,0.3,1);"+M[a];if(a==="pulse-soft"){e.style.cssText+="animation:pulse-soft-kf 1.5s ease-in-out infinite"}if(t==="click"){const g=e.getAttribute(C);if(g){D[g]=D[g]||[];D[g].push({el:e,delay:d})}}else{setTimeout(()=>{e.classList.add(V)},d*1000)}});document.querySelectorAll("["+G+"]").forEach(p=>{const g=parseFloat(p.getAttribute(G)||"0.08");Array.from(p.children).filter(c=>c.hasAttribute(S)).forEach((c,i)=>{const ce=parseFloat(c.getAttribute("data-anim-delay")||"0");c.setAttribute("data-anim-delay",String(ce+i*g))})});document.querySelectorAll("["+Q+"]").forEach(p=>{Array.from(p.children).filter(c=>c.hasAttribute(S)).forEach((c,i)=>{if(i>0)c.style.visibility="hidden";c.addEventListener("transitionend",function h(){if(i+1<p.children.length){const n=p.children[i+1];n.style.visibility="visible";n.classList.add(V)}},{once:true})})});document.addEventListener("click",()=>{Object.values(D).forEach(g=>{if(g.length>0){const n=g.shift();setTimeout(()=>n.el.classList.add(V),n.delay*1000)}})})})();
</script>
```

### 1.3 引擎工作原理

```
页面加载
  │
  ├─ 扫描所有带 data-anim 属性的元素
  │     ├─ 设置初始状态（opacity:0 + 起始 transform/clip-path）
  │     ├─ 设置 CSS transition（duration + easing）
  │     └─ 根据 trigger 决定激活时机
  │
  ├─ 扫描 data-anim-stagger 容器
  │     └─ 为子元素追加递增 delay（默认 80ms 间隔）
  │
  ├─ 扫描 data-anim-sequence 容器
  │     └─ 监听 transitionend，触发下一个子元素
  │
  ├─ 扫描 data-anim-click-group
  │     └─ 注册到 clickGroups，按页面点击逐组弹出
  │
  └─ 激活方式：为元素添加 .anim-visible 类 → CSS transition 接管过渡
```

---

## 二、完整动效目录

每种动效都有一个 `data-anim` 标识值、对应的 CSS 初始状态和 `.anim-visible` 目标状态。

### 2.1 fade-up — 上浮淡入

最通用的入场动效，适用于标题、卡片、正文段落。

**初始状态 CSS：**
```css
[data-anim="fade-up"] {
  opacity: 0;
  transform: translateY(30px);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="fade-up"].anim-visible {
  opacity: 1;
  transform: translateY(0);
}
```

**使用示例：**
```html
<h1 data-anim="fade-up" data-anim-duration="0.8s">主标题从下方浮入</h1>
<p  data-anim="fade-up" data-anim-delay="0.2s">副标题延迟 0.2 秒</p>
```

---

### 2.2 fade-in — 纯淡入

仅透明度变化，无位移。适用于已有定位的元素、图片、图表。

**初始状态 CSS：**
```css
[data-anim="fade-in"] {
  opacity: 0;
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="fade-in"].anim-visible {
  opacity: 1;
}
```

**使用示例：**
```html
<img data-anim="fade-in" data-anim-delay="0.4s"
     src="./chart_1.png" style="width:1080px;height:360px;" alt="图表">
```

---

### 2.3 scale-in — 缩放淡入

从 0.85 倍放大至 1 倍同时淡入。适用于封面标题、KPI 数字、核心数据。

**初始状态 CSS：**
```css
[data-anim="scale-in"] {
  opacity: 0;
  transform: scale(0.85);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="scale-in"].anim-visible {
  opacity: 1;
  transform: scale(1);
}
```

**使用示例：**
```html
<!-- 封面 Hero 标题 -->
<h1 data-anim="scale-in" data-anim-duration="0.8s"
    style="font-size:56px;font-weight:bold;">年度战略报告</h1>

<!-- KPI 数字 -->
<span data-anim="scale-in" data-anim-delay="0.2s"
      style="font-size:96px;font-weight:bold;color:var(--primary);">86%</span>
```

---

### 2.4 slide-left — 左侧滑入

从左侧 60px 外滑入同时淡入。适用于时间线节点、列表项。

**初始状态 CSS：**
```css
[data-anim="slide-left"] {
  opacity: 0;
  transform: translateX(-60px);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="slide-left"].anim-visible {
  opacity: 1;
  transform: translateX(0);
}
```

**使用示例：**
```html
<!-- 时间线节点 -->
<div data-anim="slide-left" style="display:flex;align-items:flex-start;">
  <span style="font-size:16px;color:var(--primary);">2024 Q3</span>
  <div style="flex:1;">里程碑内容描述</div>
</div>
```

---

### 2.5 slide-right — 右侧滑入

从右侧 60px 外滑入同时淡入。适用于封面 Split 布局左侧文字、列表项。

**初始状态 CSS：**
```css
[data-anim="slide-right"] {
  opacity: 0;
  transform: translateX(60px);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="slide-right"].anim-visible {
  opacity: 1;
  transform: translateX(0);
}
```

**使用示例：**
```html
<!-- 对比布局左侧方案 -->
<div data-anim="slide-right" data-anim-duration="0.7s"
     style="flex:1;background:var(--card-bg);border-radius:16px;">
  <h3>方案 A</h3>
  <p>方案 A 的优势描述</p>
</div>
```

---

### 2.6 wipe-right — 从左到右擦除揭示

使用 `clip-path` 实现从左到右的擦除效果。适用于装饰线、底部色条、分隔线。

**初始状态 CSS：**
```css
[data-anim="wipe-right"] {
  opacity: 0;
  clip-path: inset(0 100% 0 0);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="wipe-right"].anim-visible {
  opacity: 1;
  clip-path: inset(0 0 0 0);
}
```

**使用示例：**
```html
<!-- 章节过渡页装饰线 -->
<div data-anim="wipe-right" data-anim-delay="0.35s" data-anim-duration="0.6s"
     style="width:200px;height:4px;background:var(--primary);border-radius:2px;"></div>

<!-- 封面底部色条 -->
<div data-anim="wipe-right" data-anim-duration="0.8s"
     style="position:absolute;bottom:0;left:0;width:1280px;height:140px;
            background:linear-gradient(135deg,var(--primary),var(--secondary));"></div>
```

---

### 2.7 zoom-in — 放大淡入

从 0.5 倍大幅缩放至 1 倍，冲击力强。适用于 breathing 页面大字、核心结论。

**初始状态 CSS：**
```css
[data-anim="zoom-in"] {
  opacity: 0;
  transform: scale(0.5);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
```

**.anim-visible 目标状态：**
```css
[data-anim="zoom-in"].anim-visible {
  opacity: 1;
  transform: scale(1);
}
```

**使用示例：**
```html
<!-- breathing 大字页 -->
<p data-anim="zoom-in" data-anim-duration="1s"
   style="font-size:96px;font-weight:bold;color:var(--primary);">
  86%
</p>
```

---

### 2.8 pulse-soft — 柔和脉冲（强调动效）

唯一使用 CSS `@keyframes` 的动效（引擎自动注入）。适用于 CTA 按钮、关键行动点。

**CSS @keyframes（引擎自动生成）：**
```css
@keyframes pulse-soft-kf {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.03); }
}
```

**初始状态：** 无特殊初始状态

**使用示例：**
```html
<!-- CTA 按钮 -->
<div data-anim="pulse-soft"
     style="padding:14px 40px;background:var(--accent);color:#FFFFFF;
            border-radius:999px;font-size:18px;font-weight:bold;
            display:inline-block;cursor:pointer;">
  立即体验
</div>
```

> **注意**：`pulse-soft` 是持续动效，不等待 `trigger`，页面加载即开始无限循环。不计入页面动效总数上限。

---

## 三、时序属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `data-anim-delay` | 数字（秒） | `0` | 动效延迟触发的时间，如 `"0.3"` 表示 0.3 秒后开始 |
| `data-anim-duration` | 数字（秒） | `0.6` | 动效过渡的持续时间，如 `"0.8"` 表示持续 0.8 秒 |
| `data-anim-trigger` | 字符串 | `"load"` | 触发方式：`"load"` 自动触发 / `"click"` 手动触发（配合 click-group） |

### 3.1 delay 堆叠示例

```html
<!-- 标题先出，副标题 0.2s 后出，作者 0.6s 后出 -->
<h1 data-anim="fade-up" data-anim-duration="0.8s">主标题</h1>
<p  data-anim="fade-up" data-anim-delay="0.2s">副标题</p>
<p  data-anim="fade-up" data-anim-delay="0.6s"
    style="font-size:14px;color:var(--muted);">作者 / 日期</p>
```

### 3.2 duration 建议值

| 场景 | 推荐 duration | 说明 |
|------|--------------|------|
| 卡片/列表项 | `0.5s` | 快速入场，不拖沓 |
| 页面标题 | `0.6s` | 标准节奏 |
| 封面标题 | `0.8s` | 营造仪式感 |
| breathing 大字 | `1s` | 沉浸式出场 |
| wipe-right 色条 | `0.6s` ~ `0.8s` | 擦除动画略慢更有质感 |

---

## 四、组合属性

### 4.1 data-anim-stagger — 级联错峰

在**父容器**上设置，子元素按固定间隔依次激活。适用于卡片网格、KPI 行、列表。

| 属性 | 值 | 说明 |
|------|-----|------|
| `data-anim-stagger` | 数字（秒） | 每个子元素之间增加的延迟，推荐 `0.08`（80ms） |

**使用示例：**
```html
<!-- 4 张卡片以 80ms 间隔依次淡入 -->
<div data-anim-stagger>
  <div data-anim="fade-up">卡片 1 — 0ms 激活</div>
  <div data-anim="fade-up">卡片 2 — 80ms 激活</div>
  <div data-anim="fade-up">卡片 3 — 160ms 激活</div>
  <div data-anim="fade-up">卡片 4 — 240ms 激活</div>
</div>
```

**引擎行为：** 引擎将子元素已有的 `data-anim-delay` 值与 `i × gap` 相加，重写 delay 属性。

**注意：** 仅有 `data-anim` 属性的直接子元素参与 stagger，不含 `data-anim` 的子元素被跳过。

---

### 4.2 data-anim-sequence — 逐个触发

在**父容器**上设置，子元素严格按顺序逐个出现：前一个动画的 `transitionend` 事件触发下一个。适用于逐步展示的教学页、步骤页。

| 属性 | 值 | 说明 |
|------|-----|------|
| `data-anim-sequence` | 无值 | 标记即可，子元素逐个触发 |

**使用示例：**
```html
<!-- 3 个步骤逐个出现，前一个完成后触发下一个 -->
<div data-anim-sequence>
  <div data-anim="fade-up" data-anim-duration="0.5s">步骤 1：需求分析</div>
  <div data-anim="fade-up" data-anim-duration="0.5s">步骤 2：方案设计</div>
  <div data-anim="fade-up" data-anim-duration="0.5s">步骤 3：落地实施</div>
</div>
```

**引擎行为：** 除第一个子元素外，其余子元素初始 `visibility: hidden`。监听每个子元素的 `transitionend` 事件，依次设置下一个子元素 `visibility: visible` 并添加 `.anim-visible`。

**注意：** `data-anim-sequence` 与 `data-anim-stagger` 不可同时使用于同一容器。sequence 更适用于内容需要观众逐条阅读的场景。

---

### 4.3 data-anim-click-group — 点击分组

元素按组编号，页面每次点击触发下一组元素出现。适用于演讲者手动控制节奏的演示。

| 属性 | 值 | 说明 |
|------|-----|------|
| `data-anim-click-group` | 数字字符串 | 组编号，如 `"1"`、`"2"`。同组元素首次点击同时出现 |
| `data-anim-trigger` | `"click"` | 必须配合设置为 `"click"` |

**使用示例：**
```html
<!-- 第 1 次点击：出现要点 A -->
<div data-anim="fade-up" data-anim-trigger="click"
     data-anim-click-group="1">要点 A：市场趋势分析</div>

<!-- 第 2 次点击：出现要点 B 和图表 -->
<div data-anim="fade-up" data-anim-trigger="click"
     data-anim-click-group="2">要点 B：竞品对比</div>
<img data-anim="fade-in" data-anim-trigger="click"
     data-anim-click-group="2" src="./chart_1.png" alt="对比图表">

<!-- 第 3 次点击：出现结论 -->
<div data-anim="scale-in" data-anim-trigger="click"
     data-anim-click-group="3">结论：推荐方案 B</div>
```

**引擎行为：** 页面加载时所有 click 触发元素保持初始隐藏状态。每次页面点击，从 `clickGroups` 取出编号最小的未处理组，为该组所有元素添加 `.anim-visible`。

---

## 五、CSS 过渡定义速查

| 动效类型 | transition 属性 | easing | .anim-visible 目标 |
|----------|----------------|--------|-------------------|
| `fade-up` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1; transform:translateY(0)` |
| `fade-in` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1` |
| `scale-in` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1; transform:scale(1)` |
| `slide-left` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1; transform:translateX(0)` |
| `slide-right` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1; transform:translateX(0)` |
| `wipe-right` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1; clip-path:inset(0 0 0 0)` |
| `zoom-in` | `all 0.6s` | `cubic-bezier(0.16, 1, 0.3, 1)` | `opacity:1; transform:scale(1)` |
| `pulse-soft` | — | `ease-in-out` (keyframes) | 循环缩放 1→1.03→1 |

**缓动函数说明：**
```
cubic-bezier(0.16, 1, 0.3, 1)
        ↑                ↑
    快速启动          柔和收尾
```

该缓动曲线是"ease-out"的增强版——元素快速进入视野，在接近终点时柔和减速。适合演示场景的入场动效，避免线性过渡的生硬感。

---

## 六、完整使用示例

### 6.1 封面页（anchor，≤2 动效）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:var(--body-font);">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
      --title-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
      --body-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
    }
  </style>

  <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
              height:580px;text-align:center;">
    <h1 data-anim="fade-up" data-anim-duration="0.8s"
        style="font-size:48px;font-weight:bold;color:var(--text);margin:0;
               font-family:var(--title-font);">
      数字化转型战略报告
    </h1>
    <p data-anim="fade-up" data-anim-delay="0.2s"
       style="font-size:24px;color:var(--muted);margin:16px 0 0 0;">
      2025 年度规划与路线图
    </p>
  </div>

  <div data-anim="wipe-right" data-anim-duration="0.8s"
       style="position:absolute;bottom:0;left:0;width:1280px;height:140px;
              background:linear-gradient(135deg,var(--primary),var(--secondary));">
    <p data-anim="fade-up" data-anim-delay="0.6s"
       style="position:absolute;bottom:24px;left:80px;font-size:14px;
              color:rgba(255,255,255,0.85);margin:0;">
      战略规划部 / 2025.07
    </p>
  </div>

  <script>/* 动画引擎脚本 */</script>
</div>
```

### 6.2 内容页 — 2×2 Cards（dense，5 动效）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:var(--body-font);">
  <style>
    :root { /* 色值省略，替换为 spec_lock palette */ }
  </style>

  <!-- 标题：1 个动效 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:80px;font-size:32px;font-weight:bold;
             color:var(--text);margin:0;">
    核心能力矩阵
  </h2>

  <!-- 4 张卡片：stagger 级联，4 个动效 -->
  <div data-anim-stagger
       style="position:absolute;top:110px;left:80px;width:1120px;
              display:grid;grid-template-columns:repeat(2,548px);
              grid-template-rows:repeat(2,260px);gap:24px;">
    <div data-anim="fade-up" style="background:var(--card-bg);...">卡片 1</div>
    <div data-anim="fade-up" style="background:var(--card-bg);...">卡片 2</div>
    <div data-anim="fade-up" style="background:var(--card-bg);...">卡片 3</div>
    <div data-anim="fade-up" style="background:var(--card-bg);...">卡片 4</div>
  </div>

  <!-- 共 5 个动效元素，未超过 dense 上限 6 -->
  <script>/* 动画引擎脚本 */</script>
</div>
```

### 6.3 breathing — Big Number + Label（1 动效）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:var(--body-font);">
  <style>
    :root { /* 色值省略 */ }
  </style>

  <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
              text-align:center;">
    <p data-anim="scale-in" data-anim-duration="1s"
       style="font-size:96px;font-weight:bold;color:var(--primary);margin:0;">
      86%
    </p>
    <p style="font-size:24px;color:var(--muted);margin:16px 0 0 0;">
      客户满意度达标率
    </p>
  </div>

  <script>/* 动画引擎脚本 */</script>
</div>
```

---

## 七、设计约束

| # | 约束 | 说明 |
|---|------|------|
| 1 | **每页 ≤6 个独立 data-anim 元素** | stagger 父容器不计入，子元素各自计数；pulse-soft 不计入 |
| 2 | **动画引擎脚本是页面中唯一的 `<script>` 标签** | 禁止任何其他 JavaScript（事件绑定、库引用、内联脚本等） |
| 3 | **禁止 CSS @keyframes** | 除 `pulse-soft-kf`（引擎自动注入）外，不定义任何关键帧动画 |
| 4 | **禁止 CSS animation 属性** | 除 `pulse-soft-kf` 外，不使用 `animation` 属性；所有动效走 `transition` |
| 5 | **动画初始状态由引擎 JS 设置** | 不需在 CSS 中手写初始 `opacity:0` 或初始 `transform`，引擎注入 |
| 6 | **.anim-visible 类由引擎自动添加** | 不要在 HTML 或 CSS 中手动添加此 class |
| 7 | **stagger 与 sequence 互斥** | 同一父容器不可同时使用 `data-anim-stagger` 和 `data-anim-sequence` |
| 8 | **锚定 spec_lock.md 的 rhythm 选择动效策略** | anchor→fade-up/wipe-right、dense→stagger+fade-up/scale-in、breathing→scale-in/zoom-in |

---

## 八、动效选择决策树

```
页面 rhythm 是什么？
  │
  ├─ anchor（封面/章节过渡）
  │     ├─ 封面标题  → fade-up 或 scale-in（duration: 0.8s）
  │     ├─ 副标题    → fade-up（delay: +0.2s）
  │     ├─ 装饰色条  → wipe-right（duration: 0.8s）
  │     └─ 作者/日期 → fade-up（delay: +0.6s）
  │
  ├─ dense（内容页）
  │     ├─ 页面标题  → fade-up（无 delay）
  │     ├─ 卡片网格  → data-anim-stagger + 子卡片 fade-up
  │     ├─ KPI 指标  → data-anim-stagger + 子项 scale-in
  │     ├─ 列表要点  → data-anim-stagger + 子项 slide-left/slide-right
  │     └─ 图表/图片 → fade-in 或 fade-up（delay: 0.3-0.4s）
  │
  └─ breathing（金句/大字）
        ├─ 金句文字  → fade-up（duration: 0.8s）
        ├─ 大字数字  → scale-in 或 zoom-in（duration: 1s）
        └─ 标签说明  → 不动效（静态出现）
```

---

## 九、常见问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 动效不触发 | 未嵌入动画引擎 `<script>` | 确认每页末尾有引擎脚本 |
| 所有元素同时出现 | 未使用 `data-anim-stagger` | 在父容器添加 `data-anim-stagger` 属性 |
| stagger 间隔过大/过小 | gap 值不匹配 | 调整 `data-anim-stagger` 值（默认 0.08s，可设为 0.12 或 0.05） |
| 点击触发不工作 | `data-anim-trigger` 未设为 `"click"` | 同时设置 `data-anim-trigger="click"` 和 `data-anim-click-group="N"` |
| wipe-right 无效 | 元素使用了 `overflow:visible` 之外的 clip-path 不兼容布局 | 确保 wipe-right 元素为独立块级元素，不在 flex/grid 深层嵌套 |
| 移动端卡顿 | transition 同时涉及 `transform` 和 `opacity` 以外的属性 | 动效仅使用 `transform` + `opacity` + `clip-path`，均属 GPU 加速属性 |
