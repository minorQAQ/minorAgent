# 07 — Executor（执行师）：HTML 页面生成指南

> **角色**：HTML 执行师 — 将 spec_lock.md 的设计合约转化为逐页 HTML 页面
> **读取时机**：Step 3（HTML 路线）进入执行阶段前
> **前置依赖**：`05-layout-patterns.md`（布局模式参考）、`08-animation-system.md`（动画引擎脚本与动效目录）

---

## ⛔ Executor 阶段原则

Executor 阶段原则上自动化执行，不主动打断用户。但若在生成过程中遇到以下情况，**必须暂停并使用 `human_interaction` 与用户对齐**：

| 情况 | human_interaction 类型 | 示例 |
|------|----------------------|------|
| spec_lock.md 中某页信息不足以生成 | `information` | 配图策略标了 `hero` 但用户未提供图片，询问用户是否补充或改为纯文字 |
| 图表数据描述模糊，matplotlib 无法确定具体数值 | `information` | "Q1-Q4 营收对比"但未给出具体数字，询问用户数据 |
| 生成过程中发现 spec_lock 内容有矛盾 | `approval` | 某页被标记为 `anchor` 但分配了 80+ 字内容，请求用户调整 |
| 用户中途要求修改已生成的页面 | `approval` | 展示修改方案，用户审批后重新生成该页 |

> **禁止 Executor 自行猜测或填写缺失数据。遇到不确定的情况必须回到用户侧对齐。**

---

## 核心使命

读取 `spec_lock.md` → 生成图表（如有） → 逐页手写 HTML → 每页内嵌 CSS 变量与动画引擎 → 质量检查

---

## 一、生成前检查清单

在生成第一页 HTML 之前，必须完成以下检查：

### 1.1 读取 spec_lock.md

确认以下信息已锁定：

| 检查项 | 来源字段 | 说明 |
|--------|----------|------|
| 画布格式 | `canvas` | 确认 `{width}×{height}`，不可偏离（16:9=1280×720 / 4:3=1024×768 / A4纵向=720×1280） |
| 色板十六进制值 | `palette` | 确认 `bg`、`primary`、`secondary`、`accent`、`text`、`muted` 的全部 6 个 hex 值 |
| 字体栈 | `fonts` | 确认 `title_font` 和 `body_font` 的具体 font-family 字符串，必须以系统安全字体结尾 |
| 页面节奏 | `pages[].rhythm` | 识别每页的 rhythm 标签（`anchor` / `dense` / `breathing`），据此匹配布局 |
| 每页内容 | `pages[].title`、`pages[].key_points` | 确认标题文案与要点的具体内容 |
| 图表需求 | `pages[].chart` | 确认哪些页面需要图表、图表数据来源 |

### 1.1.1 ⛔ 画布尺寸自检（每页生成前必须执行）

在生成每页 HTML 的根 div 之前，**必须执行以下自检**：

```
确认 spec_lock.md canvas 值：
  □ 16:9 → 根 div 必须是 width:1280px;height:720px
  □ 4:3  → 根 div 必须是 width:1024px;height:768px
  □ A4纵向 → 根 div 必须是 width:720px;height:1280px
  □ 禁止使用 1920×1080 或任何非标准尺寸
  □ 所有页面根 div 尺寸必须完全一致
```

**自检未通过 → 禁止生成 HTML。**

### 1.2 确认色板与 CSS 变量映射

将 `spec_lock.md` 的 palette 字段映射为 `:root` 中的 CSS 自定义属性：

```
palette.bg       →  --bg
palette.primary  →  --primary
palette.secondary→  --secondary
palette.accent   →  --accent
palette.text     →  --text
palette.muted    →  --muted
```

衍生变量（按需推导，不纳入 spec_lock）：
- `--card-bg`：浅色主题为 `#FFFFFF`，若 bg 为白色则取 `#FFFFFF`
- `--card-shadow`：`0 2px 12px rgba(0,0,0,0.08)`
- `--border-color`：`#E5E7EB`（浅色）或从 bg 推深 2 级

### 1.3 确认字体栈

```css
--title-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
--body-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
```

字体栈必须以系统安全字体结尾（`sans-serif` / `serif` / `monospace`），**不使用任何 CDN 加载的外部字体**。

### 1.4 识别页面节奏与布局匹配

| rhythm | 含义 | 信息量 | 匹配布局（来自 05-layout-patterns.md） |
|--------|------|--------|---------------------------------------|
| `anchor` | 封面/章节过渡页 | ≤30 字 | Cover Hero Centered / Cover Split / Section Divider |
| `dense` | 内容/数据页 | ≤80 字 | 2×2 Cards / KPI Dashboard / Left Text Right Image / Top Image Bottom Text / 3-Column Feature / Timeline / Comparison |
| `breathing` | 金句/大字页 | ≤20 字 | Quote Centered / Big Number + Label |

---

## 二、图表生成（当页面需要图表时）

### 2.1 何时需要图表

当 `spec_lock.md` 中该页标注了 `chart` 字段，或 key_points 中包含"趋势""对比""占比""分布"等数据描述时。

### 2.2 生成流程

1. **编写 Python 脚本** → 使用 matplotlib，配色严格取自 spec_lock.md palette：
   - 主系列用 `primary`
   - 副系列用 `secondary`
   - 强调数据用 `accent`
   - 网格线/坐标轴用 `muted`
   - 背景用 `bg`

2. **脚本模板**（`workspace/ppt_{topic}/gen_chart_{N}.py`）：

```python
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
matplotlib.rcParams['axes.unicode_minus'] = False

# === 色值取自 spec_lock.md palette ===
PRIMARY   = "#1A73E8"
SECONDARY = "#4285F4"
ACCENT    = "#FF6D00"
MUTED     = "#6B7280"
BG        = "#FAFBFC"

fig, ax = plt.subplots(figsize=(10.8, 3.6), dpi=100)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

# ... 绘图逻辑 ...

ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_color(MUTED)
ax.spines['bottom'].set_color(MUTED)
ax.tick_params(colors=MUTED)

plt.tight_layout()
plt.savefig('chart_{N}.png', dpi=120, bbox_inches='tight', facecolor=BG)
```

3. **运行脚本**：
   ```bash
   cd workspace/ppt_{topic} && python gen_chart_{N}.py
   ```

4. **在 HTML 中引用**：
   ```html
   <img src="./chart_{N}.png"
        style="width:1080px;height:360px;object-fit:contain;" alt="图表">
   ```

### 2.3 图表尺寸约束

| 布局类型 | 图表宽 × 高 | 说明 |
|----------|------------|------|
| KPI Dashboard 底部 | 1080×360 | 占画布下半部分 |
| Left Text Right Image 右侧 | 560×520 | 与左侧文字等高 |
| Top Image Bottom Text 顶部 | 1280×360 | 全宽半高 |

---

## 三、逐页生成流程

### 3.1 每页生成前（必须）

**重新读取 `spec_lock.md`**，获取该页的 rhythm、title、key_points。这是防止上下文漂移导致风格不一致的关键措施。

### 3.2 生成步骤

```
┌─ Step A: 读取 spec_lock.md 中该页信息
│
├─ Step B: 根据 rhythm 标签，从 05-layout-patterns.md 选择匹配布局
│          anchor    → 封面/过渡布局（第 1-3 模板）
│          dense     → 内容布局（第 4-10 模板）
│          breathing → 金句/大字布局（第 11-12 模板）
│
├─ Step C: 编写独立 HTML 文件
│          1. 替换所有占位文案为 spec_lock 中的真实内容
│          2. 在 <head> 中设置 meta ppt-page="{N}" 和 meta ppt-total="{T}"
│          3. 在 <style> 块的 :root 中写入 palette 的 hex 色值
│          4. 根据 spec_lock 的字号规范调整 font-size
│          5. 为需要动效的元素添加 data-anim 属性
│          6. 在 </div> 之前嵌入动效引擎 + 键盘导航 <script>
│
├─ Step D: 如该页需要图表 → 先生成图表 PNG，再在 HTML 中引用
│
└─ Step E: 使用 doc_tool create 输出独立文件 `{N}.html`

### 3.3 ⛔ 文件命名铁律

> **文件名只能是纯数字。这是硬性规则，违反即无效。**

| ✅ 正确 | ❌ 绝对禁止 |
|--------|------------|
| `1.html` | `1_cover.html`、`1_封面.html`、`01.html`、`page1.html` |
| `2.html` | `2_TOC.html`、`2_目录.html` |
| `3.html` | `3_transformer_architecture.html` |
| ... | 任何包含数字以外的字符 |

**为什么必须纯数字**：键盘导航脚本通过 `meta[name="ppt-page"]` 获取当前页码，用 `(cur+1)+'.html'` 构造下一页 URL。如果文件名不是纯数字（如 `1_cover.html`），导航将失效。

每页是一个**自包含的完整 HTML 文档**（含 `<html>` `<head>` `<body>`），文件命名为 `{N}.html`（N 从 1 开始，纯数字无后缀），输出到 `workspace/ppt_{topic}/` 目录。

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="ppt-page" content="{N}">
  <meta name="ppt-total" content="{T}">
  <title>第 {N} 页</title>
  <style>
    :root {
      --bg: {hex}; --primary: {hex}; --secondary: {hex};
      --accent: {hex}; --text: {hex}; --muted: {hex};
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
      --title-font: '{font}'; --body-font: '{font}';
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    .ppt-root {
      width: 1280px; height: 720px; position: relative;
      overflow: hidden; background: var(--bg);
      font-family: var(--body-font);
    }
  </style>
</head>
<body style="display:flex;justify-content:center;align-items:center;
            min-height:100vh;background:#e0e0e0;">
  <div class="ppt-root">
    <!-- 页面内容 -->
  </div>
  <script>
    /* 动效引擎 + 键盘导航 */
  </script>
</body>
</html>
```

每个文件可在浏览器中直接打开预览。通过键盘左右方向键可在页面间切换。无需单文件组装、无需 CSS 页间切换、无需可见导航按钮。

---

## 四、按节奏的动画策略

### 4.1 anchor（封面/章节页）— ≤2 个动效元素

| 页面类型 | 动效方案 | data-anim 示例 |
|----------|---------|---------------|
| 封面 Hero | 标题 `fade-up` + 副标题 `fade-up`（延迟 0.2s） | `data-anim="fade-up"` |
| 封面 Split | 左文字 `slide-right` + 右装饰区 `fade-up`（延迟 0.3s） | `data-anim="slide-right"` |
| 章节过渡 | 编号 `fade-up` + 标题 `fade-up`（延迟 0.15s） + 装饰线 `wipe-right`（延迟 0.35s） | `data-anim="wipe-right"` |

**原则**：封面动效营造仪式感，延迟错开形成层次；副标题始终比主标题晚 0.15-0.2s。

### 4.2 dense（内容页）— ≤6 个动效元素

| 页面类型 | 动效方案 | data-anim 示例 |
|----------|---------|---------------|
| 2×2 Cards | 父容器 `data-anim-stagger` + 子卡片 `fade-up` | 父: `data-anim-stagger`，子: `data-anim="fade-up"` |
| KPI Dashboard | 父容器 `data-anim-stagger` + KPI 卡片 `scale-in` + 图表 `fade-up` | 子: `data-anim="scale-in"`，图表: `data-anim="fade-up" data-anim-delay="0.4s"` |
| 左文右图 | 文字要点 `slide-right`（stagger），图片 `fade-up`（延迟 0.3s） | 子: `data-anim="slide-right"` |
| 时间线 | 父容器 `data-anim-stagger` + 节点 `slide-left` | 父: `data-anim-stagger`，子: `data-anim="slide-left"` |
| 对比 | 左侧 `slide-right` + 右侧 `slide-left`（延迟 0.2s） + VS 标识 `scale-in`（延迟 0.5s） | 左: `data-anim="slide-right"`，右: `data-anim="slide-left" data-anim-delay="0.2s"` |

**原则**：
- 页面标题最先出现（`fade-up`，无延迟）
- 卡片/列表用 `data-anim-stagger` 实现级联出场（80ms 间隔）
- 图表/图片用 `fade-up` 延迟 0.3-0.4s 出场
- stagger 容器不计入独立动效数量，子元素各自计数

### 4.3 breathing（金句/大字页）— ≤1 个动效元素

| 页面类型 | 动效方案 | data-anim 示例 |
|----------|---------|---------------|
| 居中金句 | 金句 `fade-up`（慢速 0.8s） | `data-anim="fade-up" data-anim-duration="0.8s"` |
| 大字 + 标签 | 数字 `scale-in`（延迟 0.2s，慢速 1s） | `data-anim="scale-in" data-anim-delay="0.2s" data-anim-duration="1s"` |

**原则**：breathing 页面讲究留白与沉浸感，动效极少但持续时长可适当拉长。

---

## 五、每页动效上限

| rhythm | 最大动效数 | 说明 |
|--------|-----------|------|
| `anchor` | ≤2 | 封面标题 + 副标题；或标题 + 装饰线 |
| `dense` | ≤6 | 标题(1) + stagger 卡片(≤4) + 图表/图片(1) |
| `breathing` | ≤1 | 金句或大字，单一焦点 |

> **注意**：`data-anim-stagger` 容器自身不计入动效数，但其中通过 `data-anim` 标记的子元素各自计数。例如：stagger 容器内含 4 个 `data-anim="fade-up"` 卡片，计为 4 个动效。

---

## 六、CSS 变量替换规范

### 6.1 每页 HTML 的 `<style>` 块必须以 `:root` 声明开头

```html
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
    --title-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
    --body-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
  }
</style>
```

### 6.2 色值必须与 spec_lock.md 完全一致

直接从 `spec_lock.md` 的 `palette` 字段复制 hex 值，不允许自行调整、加深、变亮、或使用其他色值。

### 6.3 独立 HTML 文档模板

每页输出为一个**自包含的完整 HTML 文档**：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>第 {N} 页</title>
  <style>
    :root {
      --bg: {hex}; --primary: {hex}; --secondary: {hex};
      --accent: {hex}; --text: {hex}; --muted: {hex};
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
      --title-font: '{font}'; --body-font: '{font}';
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    .ppt-root {
      width: 1280px; height: 720px; position: relative;
      overflow: hidden; background: var(--bg);
      font-family: var(--body-font);
    }
  </style>
</head>
<body style="display:flex;justify-content:center;align-items:center;
            min-height:100vh;background:#e0e0e0;">
  <div class="ppt-root">
    <!-- 页面内容 — 使用 var(--xxx) 引用色值 -->
  </div>
  <script>
    /* 动画引擎 */
  </script>
</body>
</html>
```

---

## 七、输出
### 7.1 最终输出
每页输出为独立 HTML 文件：`workspace/ppt_{topic}/{N}.html`（N 从 1 到总页数）。每个文件为自包含的完整 HTML 文档。
### 7.2 输出流程
1. 逐页使用 doc_tool create 写出 {N}.html
2. 运行 `python {SKILL_DIR}/attachments/complete_htmls_to_base64.py {workspace_dir}` 产出 `{N}_complete.html`
3. 交付所有 {N}_complete.html 文件

### 7.3 图片缩放规则

用户上传的图片尺寸已在消息中提供。在 HTML 中使用时：

```css
/* 根据 spec_lock.md canvas 和图片原始尺寸计算缩放 */
--canvas-w: {spec_lock canvas width};
--canvas-h: {spec_lock canvas height};
--padding: 48px;
--max-img-w: calc(var(--canvas-w) - 2 * var(--padding));
--max-img-h: calc(var(--canvas-h) - 2 * var(--padding));
```

**缩放公式**：`scale = min(max_img_w / original_w, max_img_h / original_h)`
- 若 scale < 1：等比缩小，`width = original_w * scale`，`height = original_h * scale`
- 若 scale >= 1：保持原尺寸，不拉伸

```html
<!-- 示例：原图 1920×1080，画布 1280×720 -->
<!-- scale = min(1184/1920, 624/1080) = min(0.617, 0.578) = 0.578 -->
<!-- width = 1920 * 0.578 = 1109, height = 1080 * 0.578 = 624 -->
<img src="./user_image.png" style="width:1109px;height:624px;object-fit:contain;" alt="配图">
```

---

## 八、禁止事项

| # | 禁止项 | 原因 |
|---|--------|------|
| 1 | 生成 SVG | 当前 Skill 仅输出 HTML，不涉及 SVG |
| 2 | 使用系统安全字体之外的任何字体 | 无 CDN、无 Google Fonts、无 @font-face，仅限系统预装字体 |
| 3 | 添加任何 CDN 链接（字体、图标、CSS 框架） | 页面必须完全自包含，零外部依赖 |
| 4 | 超出动效上限 | anchor≤2 / dense≤6 / breathing≤1 |
| 5 | 偏离 spec_lock.md 色板 | 所有 hex 值必须是 palette 中定义的值，禁止自行引入新色 |
| 6 | 使用外部模板文件 | 仅能参考 05-layout-patterns.md 中的布局模式，不可引用外部 HTML 文件 |
| 7 | 使用动画引擎 + 键盘导航之外的 JavaScript | 每页只能有一个 `<script>` 标签，内容为动效引擎 + 键盘导航脚本（来自 06-html-standards.md） |
| 8 | **⛔ 使用 CSS @keyframes** | **最高优先级禁止**。所有动效通过 `data-anim` + CSS `transition` 实现，禁止定义任何 `@keyframes` 关键帧动画 |
| 9 | 子代理生成页面 | HTML 页面必须由当前主 Agent 端到端逐个完成 |
| 10 | 批量 / 并行生成页面 | 必须逐页顺序生成，每页生成前重读 spec_lock.md |
| 11 | **⛔ 使用错误画布尺寸** | 16:9 只能是 1280×720，禁止 1920×1080；4:3 只能是 1024×768；A4纵向只能是 720×1280 |
| 12 | **⛔ 使用相对路径引用图片** | 所有 `<img src>` 和 `background-image:url()` 必须使用绝对路径，禁止 `./xxx.png` |
| 13 | **依赖 flex/grid/文档流布局** | 根容器内所有元素必须 `position:absolute;top:{N}px;left:{N}px;` 显式定位 |
| 14 | **⛔ 文件名使用非纯数字** | 文件名只能是 `1.html`、`2.html`、...。绝对禁止 `1_cover.html`、`01.html`、`page1.html` 等 |

---

## 九、完整生成示例（dense → 2×2 Cards）

以下为一页完整的 `dense` 类型页面的生成示例，展示所有规范如何落地：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="ppt-page" content="2">
  <meta name="ppt-total" content="6">
  <title>第 2 页</title>
</head>
<body style="margin:0;padding:0;display:flex;align-items:center;justify-content:center;
            min-height:100vh;background:#E5E7EB;">
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:var(--body-font);">
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
      --title-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
      --body-font: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:80px;font-size:32px;font-weight:bold;
             color:var(--text);margin:0;font-family:var(--title-font);">
    核心能力矩阵
  </h2>

  <!-- 2×2 卡片网格 — stagger 级联动效 -->
  <div data-anim-stagger
       style="position:absolute;top:110px;left:80px;width:1120px;
              display:grid;grid-template-columns:repeat(2,548px);
              grid-template-rows:repeat(2,260px);gap:24px;">

    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--primary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">🚀</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;
                 font-family:var(--title-font);">快速部署</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        一键自动化部署流水线，分钟级完成全链路发布，支持灰度与回滚。
      </p>
    </div>

    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--secondary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">📊</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;
                 font-family:var(--title-font);">实时监控</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        多维指标大盘，异常秒级告警，覆盖基础设施到业务层全链路。
      </p>
    </div>

    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--accent);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">🔒</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;
                 font-family:var(--title-font);">安全合规</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        内置权限管控与审计追踪，满足等保三级与 SOC2 合规要求。
      </p>
    </div>

    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--primary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">⚡</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;
                 font-family:var(--title-font);">弹性伸缩</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        基于流量预测的自动扩缩容，资源利用率提升 40% 以上。
      </p>
    </div>
  </div>

  <script>
    /* 动效引擎 + 键盘导航脚本（完整内容见 06-html-standards.md 第六节） */
  </script>
</div>
</body>
</html>
```

> 以上示例中画布为 1280×720，`:root` 中色值需替换为 spec_lock.md 的 palette，标题与卡片内容替换为 spec_lock.md 的真实文案。`meta[name="ppt-page"]` 和 `meta[name="ppt-total"]` 需填入该页的实际页码和总页数。
