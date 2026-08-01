# 03 — HTML演示设计系统

> **适用路线**：HTML 路线（`generation_mode = "html"`）
> **角色**：HTML 演示的完整视觉设计规范 — 定义所有视觉参数的取值空间、层级关系与设计决策依据
> **读取时机**：Strategist 阶段锁定设计方案时；Executor 阶段逐页生成 HTML 前
> **设计灵感**：oh-my-ppt 项目 — 纯 HTML/CSS 驱动的演示生成系统

---

## 一、色彩系统

### 1.1 60-30-10 色彩法则

经典室内设计色彩比例，确保视觉平衡与层次感：

| 角色 | 占比 | 用途 | 示例 |
|------|------|------|------|
| **主色 (Primary)** | 60% | 页面背景、大面积色块、卡片底色 | 幻灯片底色、大面积区域填充 |
| **辅色 (Secondary)** | 30% | 卡片、侧边栏、区块背景、次要装饰 | 信息卡片、图标底色、分割区域 |
| **强调色 (Accent)** | 10% | CTA 按钮、关键数据、高亮文本、图标 | 核心数字、行动号召、重点标记 |

**硬性规则**：每页 Accent 色使用不超过页面面积的 10%，避免强调色滥用导致视觉焦点分散。

### 1.2 6-角色色板结构

每套配色方案必须完整定义以下 6 个色值，以 CSS 自定义属性形式组织：

| 色值角色 | CSS 变量名 | 职责说明 |
|----------|-----------|----------|
| `bg` | `--color-bg` | 页面根背景色，决定整体明暗基调 |
| `primary` | `--color-primary` | 主色调，用于标题栏、主要区块、主按钮 |
| `secondary` | `--color-secondary` | 辅助色，用于次级区域、图表辅助系列、侧边栏 |
| `accent` | `--color-accent` | 强调色，用于关键数据高亮、CTA、活跃状态 |
| `text` | `--color-text` | 正文文字色，确保与背景对比度 ≥ 4.5:1 (WCAG AA) |
| `muted` | `--color-muted` | 弱化文字色，用于副文本、脚注、辅助线、占位符 |

**CSS 实现准则**：

```css
:root {
  --color-bg: #FFFFFF;
  --color-primary: #1A73E8;
  --color-secondary: #E8F0FE;
  --color-accent: #FF6D00;
  --color-text: #1F2937;
  --color-muted: #9CA3AF;
}
```

**衍生色值**（按需自动推导，不纳入核心色板）：
- `--color-primary-hover`：primary 加深 10%
- `--color-primary-light`：primary 透明度降至 15%
- `--color-text-inverse`：深色背景上的反白文字，通常取 `--color-bg`

### 1.3 行业色彩参考

以下为各行业场景的色彩倾向指南，用于 Strategist 阶段匹配用户场景：

| 行业 / 场景 | 主色调倾向 | 辅色搭配 | 强调色点缀 |
|-------------|-----------|----------|-----------|
| **科技 / AI** | 蓝 `#1A73E8`、深蓝 `#0D47A1` | 浅蓝灰 `#E3F2FD` | 青 `#00BCD4`、电光紫 `#7C4DFF` |
| **金融 / 商务** | 藏蓝 `#1B3A5C`、深灰 `#37474F` | 米白 `#F5F0E8` | 金 `#C8A951`、铜 `#B8860B` |
| **医疗 / 健康** | 绿 `#2E7D32`、蓝绿 `#009688` | 薄荷绿 `#E8F5E9` | 白 `#FFFFFF`、珊瑚 `#FF6B6B` |
| **教育 / 培训** | 橙 `#F57C00`、蓝 `#1976D2` | 奶油 `#FFF8E1` | 黄 `#FFC107`、绿 `#4CAF50` |
| **环保 / 能源** | 绿 `#4CAF50`、森林绿 `#2E7D32` | 大地色 `#F1F8E9` | 天蓝 `#29B6F6` |
| **政府 / 政务** | 红 `#C62828`、深蓝 `#1A237E` | 浅灰 `#ECEFF1` | 金 `#FFD700` |
| **零售 / 消费** | 暖橙 `#FF7043`、粉 `#E91E63` | 浅粉 `#FCE4EC` | 黄 `#FFEB3B` |
| **制造 / 工业** | 灰蓝 `#455A64`、铁灰 `#607D8B` | 浅灰 `#ECEFF1` | 橙 `#FF6D00` |

### 1.4 中性色阶 (Neutral Scale)

7 级中性色阶，从纯白到近黑，覆盖所有灰阶需求：

| 级数 | 色值 | CSS 变量名 | 典型用途 |
|------|------|-----------|----------|
| N0 | `#FFFFFF` | `--neutral-0` | 纯白背景、卡片表面 |
| N1 | `#F9FAFB` | `--neutral-1` | 极浅灰背景（日间模式默认） |
| N2 | `#F3F4F6` | `--neutral-2` | 卡片悬浮背景、分割区 |
| N3 | `#E5E7EB` | `--neutral-3` | 边框、分割线 |
| N4 | `#9CA3AF` | `--neutral-4` | 弱化文字、占位符 |
| N5 | `#6B7280` | `--neutral-5` | 副标题、辅助说明 |
| N6 | `#1F2937` | `--neutral-6` | 正文主文字（浅色背景） |
| N7 | `#111827` | `--neutral-7` | 最深文字、深色强调 |

**使用规则**：
- 浅色主题：文字层级 N7 → N6 → N5 → N4，背景层级 N0 → N1 → N2
- 深色主题：背景层级 N7 → N6 → N5，文字层级 N0 → N1 → N2 → N3

---

## 二、字体系统

### 2.1 字体层级 (Typography Hierarchy)

基于 **1280×720px** 标准画布定义，共 7 个层级：

| 层级 | 字号范围 | 字重 | 行高 | 用途场景 |
|------|---------|------|------|----------|
| **Hero Title** (英雄标题) | 56-64px | Bold (700) | 1.1 | 封面页主标题、年度数字、核心主张 |
| **Page Title** (页面标题) | 42-48px | Bold (700) | 1.2 | 内容页顶部标题、章节标题 |
| **Section Title** (段落标题) | 32-36px | SemiBold (600) | 1.3 | 页面内分区标题、卡片标题 |
| **Subtitle** (副标题) | 24-28px | Medium (500) | 1.4 | 封面副标题、章节导语 |
| **Body** (正文) | 16-18px | Regular (400) | 1.6 | 段落正文、列表项、表格内容 |
| **Caption** (说明文字) | 14px | Regular (400) | 1.5 | 图表标签、图片来源标注 |
| **Annotation** (注释) | 12px | Regular (400) | 1.4 | 脚注、数据来源、页脚 |

**字号缩放规则**：
- 内容密集页（dense）：整体字号下调 1 级（Hero→Page Title，Page Title→Section Title，以此类推）
- 呼吸感页（breathing）：整体字号上调 0.5 级，扩大留白

### 2.2 字体系列推荐 (Font Pairings)

字体系列按语言和使用场景分类：

| 分类 | 首选字体 | 备选字体 | CSS font-family |
|------|---------|---------|-----------------|
| **中文无衬线** | 微软雅黑 | Noto Sans SC, PingFang SC | `"Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif` |
| **中文衬线** | Noto Serif SC | 宋体, SimSun | `"Noto Serif SC", "SimSun", "STSong", serif` |
| **英文无衬线** | Inter | Calibri, Roboto, Helvetica Neue | `"Inter", "Calibri", "Roboto", "Helvetica Neue", sans-serif` |
| **英文衬线** | Merriweather | Georgia, Times New Roman | `"Merriweather", "Georgia", "Times New Roman", serif` |
| **等宽 (Monospace)** | Consolas | Fira Code, Source Code Pro, Courier New | `"Consolas", "Fira Code", "Source Code Pro", "Courier New", monospace` |

**经典配对组合**：

| 配对方案 | 标题字体 | 正文字体 | 适用风格 |
|----------|---------|---------|----------|
| **现代企业** | Inter Bold + 微软雅黑 | Inter Regular + 微软雅黑 | corporate-clean, tech-startup |
| **编辑风雅** | Merriweather Bold + Noto Serif SC | Georgia Regular + 微软雅黑 | editorial-elegance, luxury-gold |
| **极简几何** | Inter ExtraLight → Bold 切换 | Inter Regular | neo-minimal, nord-cool |
| **活力创意** | 微软雅黑 Bold (加大字距) | Inter Regular | vibrant-creative, bold-impact |
| **东方典雅** | Noto Serif SC Bold | 微软雅黑 Light | chinese-ink |

### 2.3 字体加载策略

HTML 演示中的字体加载优先级：

1. **第一优先级（Web Safe）**：`"Microsoft YaHei"`, `"SimHei"`, `"Arial"` — 零延迟，系统内置
2. **第二优先级（Google Fonts CDN）**：`Inter`, `Noto Sans SC`, `Noto Serif SC`, `Merriweather`, `Fira Code` — 通过 `<link>` 标签异步加载
3. **第三优先级（CSS Fallback）**：泛类回退 (`sans-serif`, `serif`, `monospace`)

**HTML 引用示例**：
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Noto+Sans+SC:wght@300;400;500;600;700&family=Noto+Serif+SC:wght@400;600;700&family=Merriweather:wght@400;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
```

---

## 三、间距系统 (Spacing System)

### 3.1 基础单位

以 **8px** 为最小单位（8px grid），所有间距值均为 8 的倍数。

### 3.2 间距尺度

| Token 名称 | 值 | CSS 变量 | 用途 |
|------------|----|----------|------|
| `space-xs` | 8px | `--space-xs` | 紧密元素间距（图标与文字、标签内边距） |
| `space-sm` | 16px | `--space-sm` | 元素间距（列表项间距、按钮组间隔） |
| `space-md` | 24px | `--space-md` | 标准组件间距（卡片间距、段落间距） |
| `space-lg` | 32px | `--space-lg` | 大间距（区块间距、卡片内边距常规值） |
| `space-xl` | 48px | `--space-xl` | 超大间距（页面标题与内容区、主要分区） |
| `space-2xl` | 64px | `--space-2xl` | 页面级间距（封面标题与副标题之间） |
| `space-3xl` | 96px | `--space-3xl` | 极端留白（封面底部留白、过渡页中央留白） |

### 3.3 间距应用规范

| 应用场景 | 推荐间距 | 说明 |
|----------|---------|------|
| 页面整体内边距 | `--space-lg` (32px) ~ `--space-xl` (48px) | 1280×720 画布的安全边距 |
| 卡片内边距 (padding) | `--space-lg` (32px) ~ 40px | 确保卡片内容呼吸感 |
| 卡片之间间距 | `--space-md` (24px) | 网格布局中相邻卡片间距 |
| 标题与正文间距 | `--space-sm` (16px) | 标题后紧接着的正文段落 |
| 段落之间间距 | `--space-md` (24px) | 正文段落之间的垂直间距 |
| 列表项间距 | `--space-sm` (16px) | 无序/有序列表项之间 |
| 图标与文字间距 | `--space-xs` (8px) | 内联图标与相邻文字 |

---

## 四、卡片设计规范 (Card Design)

### 4.1 圆角规范 (Border Radius)

| 圆角级别 | 值 | CSS 变量 | 适用场景 |
|----------|----|----------|----------|
| 无圆角 | 0px | `--radius-none` | 表格、数据面板、严谨风格 |
| 微圆角 | 4px | `--radius-sm` | 按钮、输入框、标签 |
| 标准圆角 | 8px | `--radius-md` | 标准卡片、信息展示 |
| 柔和圆角 | 12px | `--radius-lg` | 卡片（默认推荐）、大容器 |
| 圆润卡片 | 16px | `--radius-xl` | 柔和风格卡片、特色区块 |
| 全圆角 | 9999px | `--radius-full` | 药丸按钮、头像、标签徽章 |

### 4.2 阴影系统 (Shadow System)

| 阴影级别 | CSS Box-Shadow | 使用场景 |
|----------|---------------|----------|
| **无阴影 (none)** | `none` | 扁平设计、极简风格 |
| **柔和阴影 (soft)** | `0 1px 3px 0 rgba(0,0,0,0.08), 0 1px 2px 0 rgba(0,0,0,0.06)` | 微弱层级提示、标准卡片 |
| **中等阴影 (medium)** | `0 4px 6px -1px rgba(0,0,0,0.08), 0 2px 4px -2px rgba(0,0,0,0.05)` | 悬浮卡片、重点强调 |
| **深度阴影 (raised)** | `0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.04)` | 模态层、最高层级元素 |

**暗色模式阴影**：暗色背景下阴影不可见，改用边框 (`border: 1px solid var(--neutral-5)`) 替代阴影来区分层次。

### 4.3 边框选项

| 选项 | 值 | 用途 |
|------|----|------|
| 无边框 | `none` | 默认卡片 |
| 细边框 | `1px solid var(--neutral-3)` | 浅色背景卡片轮廓 |
| 强调左边框 | `4px solid var(--color-accent)` | 引用卡片、提示卡片 |
| 渐变边框 | 通过 `border-image` 或伪元素实现 | 特殊视觉风格（赛博朋克、科技风） |

---

## 五、页面节奏标签 (Page Rhythm Tags)

每页幻灯片根据内容密度和沟通目标，标记为以下三种节奏之一：

### 5.1 标签定义

| 标签 | 名称 | 最大字符数 | 留白策略 | 典型页面类型 |
|------|------|-----------|----------|-------------|
| `anchor` | 锚点页 | ≤ 30 字符 | 大量留白（上下各 ≥ 96px） | 封面、结束页、重大过渡 |
| `dense` | 密集页 | ≤ 80 字符 | 紧凑布局，减少间距 | 数据图表页、对比分析、要点罗列 |
| `breathing` | 呼吸页 | ≤ 20 字符 | 宽松布局，优先留白 | 引言页、过渡页、金句页、大图展示 |

### 5.2 节奏策略

| 标签 | 字号策略 | 间距策略 | 装饰策略 |
|------|---------|----------|----------|
| **anchor** | 使用 Hero Title (56-64px) | 上下均使用 `--space-3xl` (96px) | 可加装饰线、大图标点缀 |
| **dense** | 整体下调 1 级 | 卡片间距 `--space-md`，内边距 `--space-sm` | 去装饰化，信息效率优先 |
| **breathing** | 整体上调 0.5 级 | 区块间距 `--space-2xl`起 | 装饰性留白本身就是设计元素 |

### 5.3 节奏序列建议

一份优秀的演示应形成「锚 → 呼吸 → 密集 (×N) → 呼吸 → 锚」的节奏曲线：

```
封面(anchor) → 目录(breathing) → 内容页(dense) × 3~8 → 过渡(breathing) → 内容页(dense) × 3~8 → 总结(breathing) → 结束(anchor)
```

---

## 六、图标策略 (Icon Strategy)

### 6.1 优先级排序

| 优先级 | 方案 | 说明 | 示例 |
|--------|------|------|------|
| **🥇 Emoji** | 系统原生 Emoji | 零依赖、跨平台一致、天然彩色 | 🚀 📊 💡 🎯 ⚡ 🔥 💎 🌟 |
| **🥈 Unicode 符号** | 几何/箭头/数学符号 | 单色、简洁、无版权 | ● ○ ◆ ◇ ▶ ▸ → ← ↑ ↓ ✔ ✖ ★ ☆ |
| **🥉 内联 SVG** | 手写 `<svg>` 标签 | 可控颜色/大小、不失真 | 自定义图标、品牌 Logo |

### 6.2 严格禁止

- ❌ 不使用任何外部图标库（Font Awesome、Material Icons、Feather 等）
- ❌ 不通过 CDN 引用图标字体
- ❌ 不使用 `<img>` 标签加载外部图标图片

### 6.3 内联 SVG 图标模板

```html
<!-- 标准图标 (24x24) -->
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <circle cx="12" cy="12" r="10"/>
  <path d="M12 6v6l4 2"/>
</svg>
```

### 6.4 常用业务 Emoji 速查

| 类别 | Emoji |
|------|-------|
| **增长/向上** | 📈 📊 🚀 ⬆️ 💹 🏆 |
| **目标/战略** | 🎯 🧭 🗺️ 🏁 🔭 |
| **技术/创新** | 💻 🤖 ⚙️ 🔬 💡 🧬 |
| **安全/稳定** | 🛡️ 🔒 ✅ 🏗️ ⚓ |
| **团队/合作** | 👥 🤝 🧩 🌐 🔗 |
| **时间/效率** | ⏱️ ⚡ 🕐 📅 🔄 |
| **金钱/商业** | 💰 💎 📋 💼 🏦 |
| **提醒/警告** | ⚠️ ❗ 🔔 💬 📌 |

---

## 七、网格系统 (Grid System)

### 7.1 12列网格

基于 1280px 画布宽度，定义 12 列等分网格：

| 列数 | 宽度 | 典型用途 |
|------|------|----------|
| 12/12 | 1280px | 全宽横幅、封面背景 |
| 8/12 | ~853px | 主要内容区（居中） |
| 6/12 | 640px | 半宽布局（并排） |
| 4/12 | ~427px | 三列卡片、特性展示 |
| 3/12 | 320px | 四列图标/数据指标 |
| 2/12 | ~213px | 六列标签/徽章 |

### 7.2 CSS Grid 实现

```css
/* 12列网格容器 */
.slide-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: var(--space-md);  /* 24px 列间距 */
  width: 1280px;
  padding: 0 var(--space-xl);  /* 48px 外边距 */
}

/* 常用跨度 */
.span-12 { grid-column: span 12; }
.span-8  { grid-column: span 8; }
.span-6  { grid-column: span 6; }
.span-4  { grid-column: span 4; }
.span-3  { grid-column: span 3; }
```

### 7.3 响应式注意事项

HTML 演示虽以 1280×720 为目标，但在不同屏幕预览时：

- 使用 `max-width: 1280px; max-height: 720px` 限制幻灯片容器
- 使用 `aspect-ratio: 16 / 9` 保持画布比例
- 小屏幕上通过 `transform: scale()` 或 `object-fit` 缩放适应视口

---

## 八、视觉层级原则 (Visual Hierarchy Principles)

### 8.1 四大原则

| 原则 | 解释 | 实现手段 |
|------|------|----------|
| **对比 (Contrast)** | 重要元素与背景形成明显差异 | 字号差 ≥ 1.5×、色差 ≥ 3:1 对比度、字重差异 |
| **尺度 (Scale)** | 通过尺寸建立信息重要性排序 | Hero 56-64px → Body 16-18px，比例约 3:1~4:1 |
| **邻近 (Proximity)** | 相关信息物理邻近，无关信息物理分离 | 同组间距 8-16px，异组间距 24-48px |
| **对齐 (Alignment)** | 建立清晰视觉流线，减少杂乱 | 左对齐为主（中文场景）、网格对齐、基线对齐 |

### 8.2 Z型阅读路径

对于 1280×720 画布，观众的视线遵循 Z 型路径：

```
左上(标题/Logo) ──────────────→ 右上(关键数据/日期)
     ↓                                  ↓
左下(辅助内容/图表) ←────────── 右下(CTA/结论)
```

**设计指导**：
- **左上角**：放置页面标题或核心主张（第一眼落点）
- **右上角**：放置关键数字、日期、Logo
- **底部区域**：放置图表、详细内容、CTA 按钮
- **右下角**：行动号召或核心结论（视线终点）

### 8.3 留白策略

| 留白类型 | 定义 | 配比指导 |
|----------|------|----------|
| **主动留白** | 刻意为之的空区域，引导视线、凸显孤立元素 | anchor/breathing 页 ≥ 40% |
| **被动留白** | 元素间的自然间距 | 所有页面通用，≥ 16px |

---

## 九、动效体系 (Animation System)

HTML 路线支持通过 CSS `data-anim` 属性声明交互动效。

### 9.1 动效类型

| 类型 | `data-anim` 值 | 描述 | 推荐节奏 |
|------|---------------|------|----------|
| 淡入 | `fade-in` | 元素从不透明到出现 | anchor, breathing |
| 上浮淡入 | `fade-up` | 从下方 20px 淡入滑入 | 所有页面通用 |
| 缩放淡入 | `scale-in` | 从 0.8× 缩放至 1× 并淡入 | 封面 Hero 标题 |
| 左滑入 | `slide-left` | 从左侧滑入 | 列表项次第出现 |
| 右滑入 | `slide-right` | 从右侧滑入 | 图片/图表呈现 |
| 弹出 | `pop` | 弹性缩放出现 | 关键数字强调 |

### 9.2 动效时序

通过 `data-anim-delay` 控制延迟（单位：ms），实现逐元素次第出现：

```html
<h1 data-anim="fade-up" data-anim-delay="0">标题</h1>
<p  data-anim="fade-up" data-anim-delay="200">副标题</p>
<div data-anim="scale-in" data-anim-delay="500">关键数字</div>
```

### 9.3 动效纪律

- 每页动效总数 ≤ 6 个元素
- 动效总时长 ≤ 1.2 秒
- 密集页（dense）：禁用动效或仅保留 1 个元素动效
- 呼吸页（breathing）：可用 3-5 个元素动效
- 锚点页（anchor）：可充分使用动效营造仪式感

---

## 十、CSS 自定义属性总览

所有设计系统中定义的 CSS 变量，应在 HTML 的 `:root` 中统一声明：

```css
:root {
  /* === 色彩 === */
  --color-bg: #FFFFFF;
  --color-primary: #1A73E8;
  --color-secondary: #E8F0FE;
  --color-accent: #FF6D00;
  --color-text: #1F2937;
  --color-muted: #9CA3AF;

  /* === 中性色阶 === */
  --neutral-0: #FFFFFF;
  --neutral-1: #F9FAFB;
  --neutral-2: #F3F4F6;
  --neutral-3: #E5E7EB;
  --neutral-4: #9CA3AF;
  --neutral-5: #6B7280;
  --neutral-6: #1F2937;
  --neutral-7: #111827;

  /* === 间距 === */
  --space-xs: 8px;
  --space-sm: 16px;
  --space-md: 24px;
  --space-lg: 32px;
  --space-xl: 48px;
  --space-2xl: 64px;
  --space-3xl: 96px;

  /* === 圆角 === */
  --radius-none: 0px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 9999px;

  /* === 字号 === */
  --font-hero: 56px;
  --font-page-title: 42px;
  --font-section-title: 32px;
  --font-subtitle: 24px;
  --font-body: 16px;
  --font-caption: 14px;
  --font-annotation: 12px;

  /* === 字体 === */
  --font-sans-cn: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
  --font-sans-en: "Inter", "Calibri", "Roboto", sans-serif;
  --font-serif: "Merriweather", "Noto Serif SC", Georgia, serif;
  --font-mono: "Consolas", "Fira Code", "Courier New", monospace;

  /* === 过渡 === */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --duration-fast: 0.2s;
  --duration-normal: 0.4s;
  --duration-slow: 0.6s;
}
```

---

## 十一、画布规范 (Canvas Spec)

| 属性 | 值 | 说明 |
|------|----|------|
| 画布尺寸 | 1280 × 720 px | 标准 16:9 比例 |
| 安全区域 | 内边距 48px (四边) | 确保关键内容不被裁切 |
| 有效内容区 | 1184 × 624 px | 安全区内可放置内容的区域 |
| 最小字号 | 12px | 任何文字不得小于此值 |
| 最大内容密度 | ≤ 80 中文字符/页 | dense 页上限；anchor 页 ≤ 30 字符 |

---
