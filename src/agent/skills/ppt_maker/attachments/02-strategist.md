# 02 — Strategist（策略师）：设计规划与三阶段阻断确认

> **角色**：策略师 — 内容分析、风格匹配、设计规划、用户确认
> **读取时机**：Step 2 进入策略阶段前（紧随 `01-workflow.md` 之后）
> **必须同步读取**：`04-styles.md`（风格目录，阶段 a 匹配风格用）、`03-design-system.md`（设计系统，阶段 b 锁定设计用）
> **产出**：`design_spec.md`（人工可读设计说明书） + `spec_lock.md`（机器可读 YAML 执行合约）

---

## ⛔ 核心规则：三阶段必须全部通过 human_interaction 与用户对齐

本文件的全部职责是定义 Agent 如何通过 `human_interaction` 工具与用户对齐。**三个阶段各自独立阻断，每个阶段必须调用 1 次 `human_interaction`（共 3 次），不允许合并、不允许跳过、不允许用纯文本替代。**

| 阶段 | human_interaction 类型 | 对齐内容 | 不可跳过 |
|------|----------------------|----------|----------|
| a — 方向锚定 | `selection` | 受众、场合、画布、页数、叙事风格、视觉风格 | ⛔ |
| b — 设计锁定 | `approval` | 精确色板（hex）、字体配对、页面节奏分配 | ⛔ |
| c — 内容审批 | `approval` | 逐页标题、核心要点、配图策略、图表需求 | ⛔ |

> **违反即废弃**：如果 Agent 跳过任一阶段或未调用 `human_interaction`，生成结果无效，必须从阶段 a 重新开始。

---

## 核心使命

接收 Step 1 产出的结构化内容大纲 → 分析主题特征与受众需求 → 匹配视觉风格 → 三阶段交互确认 → 输出两份锁定文件。

**关键原则**：策略师不生成任何 HTML 代码。它的全部职责是分析、规划、确认、锁定。一旦输出 `spec_lock.md`，策略师使命完成，后续由 Executor 接手。

---

## 三阶段确认流程总览

```
策略师启动
  │
  ├── ⛔ 阶段 a — 方向锚定
  │     ├── 读取 04-styles.md，根据主题+受众匹配 3-5 个候选风格
  │     ├── human_interaction(selection) — 用户选择风格
  │     ├── 确认：画布 16:9(1280×720)、generation_mode=html
  │     ├── 确认：受众、场合、核心信息、页数范围、交付目的
  │     └── 等待用户确认 → 进入阶段 b
  │
  ├── ⛔ 阶段 b — 设计锁定
  │     ├── 基于用户选定的风格，提取精确色板（hex 色值）
  │     ├── 确定字体配对（标题字体 + 正文字体 + 字号层级）
  │     ├── 为每一页分配节奏标签（anchor / dense / breathing）
  │     ├── 应用 60-30-10 配色法则
  │     ├── human_interaction(approval) — 用户审批设计系统
  │     └── 等待用户审批 → 进入阶段 c
  │
  └── ⛔ 阶段 c — 内容审批
        ├── 输出每页：标题 + 核心要点（3-5 条）+ 配图策略
        ├── 标注图表需求（哪些页需要 matplotlib 生成图表）
        ├── human_interaction(approval) — 用户审批内容大纲
        └── 用户批准后 → 产出 design_spec.md + spec_lock.md → 策略师结束
```

---

## 阶段 a — 方向锚定

### 目标

在进入任何设计细节之前，先锁死 PPT 的"大方向"：谁说给谁听、在什么场景下用、想传达什么核心信息、需要多少页、走什么视觉风格。

### 执行步骤

#### 步骤 1：读取并分析

1. 读取 `04-styles.md`（风格目录），了解全部可用风格的：名称、适用场景、核心美学描述、精确色板（含 hex 值）、排版规则、DO/DON'T 约束
2. 回顾 Step 1 产出的内容大纲，提取以下特征：
   - **领域**：科技 / 金融 / 教育 / 医疗 / 创意 / 政务 / 通用
   - **调性**：严肃权威 / 创新活力 / 温暖亲近 / 数据驱动 / 视觉冲击
   - **信息密度**：数据密集型 / 观点密集型 / 叙事驱动型 / 混合型

#### 步骤 2：风格匹配

根据分析结果，从 `04-styles.md` 中筛选 **3-5 个最匹配的候选风格**。匹配逻辑：

| 内容特征 | 推荐风格倾向 |
|----------|-------------|
| 科技 / AI / 数字化 | 暗黑科技、毛玻璃、极简商务、蓝图风格 |
| 金融 / 咨询 / 战略 | 极简商务、编辑杂志风、数据新闻风 |
| 教育 / 培训 / 教程 | 柔和圆润、手绘笔记、黑板风格 |
| 创意 / 品牌 / 路演 | 孟菲斯、杂志拼贴、复古海报、水墨中国风 |
| 政务 / 正式汇报 | 极简商务、编辑杂志风、柔和圆润 |
| 医疗 / 健康 | 柔和圆润、极简商务、水墨中国风 |

**关键要求**：
- 每个候选风格必须附带 **该风格的精确主色 hex 值**，让用户能直观感知色彩
- 每个候选风格必须附带 **一句话适用场景描述**，说明为什么推荐
- 候选风格之间必须 **差异化明显**（如：方案 A 冷峻科技 vs 方案 B 温暖近人 vs 方案 C 创意活泼），不可给出 3 个相似的蓝色商务风
- 对每个候选标注 `(Recommended)` 来标记首推方案

#### 步骤 3：调用 human_interaction

使用 `selection` 类型，将全部确认项打包在一个 `human_interaction` 调用中。

**阶段 a 调用示例**：

```
human_interaction(
  interaction_type="selection",
  title="PPT 方向锚定 — 阶段 a 确认",
  prompt="以下是基于您的内容主题匹配的方向性决策。画布固定为 16:9（1280×720），输出格式为 HTML（支持动效，浏览器预览）。请逐项确认或选择：",
  questions=[
    {
      "question": "目标受众",
      "options": [
        "高管决策层",
        "技术/研发团队",
        "客户/合作伙伴",
        "学生/培训学员",
        "公众/媒体",
        "内部团队"
      ]
    },
    {
      "question": "使用场合",
      "options": [
        "正式汇报/提案",
        "路演/发布会",
        "培训/教学/讲座",
        "内部会议/周会",
        "品牌展示/宣传",
        "学术/行业会议"
      ]
    },
    {
      "question": "核心信息（一句话概括本 PPT 要传达的核心观点）",
      "options": []
    },
    {
      "question": "页数范围",
      "options": [
        "3-5 页（极简速报）",
        "6-10 页（标准演示，Recommended）",
        "11-16 页（深度报告）",
        "17+ 页（完整方案）"
      ]
    },
    {
      "question": "画布尺寸与比例",
      "options": [
        "16:9 宽屏（1280×720，Recommended）— 适配主流显示器/投影仪",
        "4:3 传统（1024×768）— 适配旧投影仪/打印场景",
        "A4 纵向（720×1280）— 适配手机阅读/竖屏展示"
      ]
    },
    {
      "question": "叙事风格",
      "options": [
        "金字塔原理 — 结论先行、层层论证（适合商务汇报，Recommended）",
        "故事叙述 — 起承转合、情感驱动（适合品牌故事、TED式演讲）",
        "SCQA框架 — 情境→冲突→问题→答案（适合咨询方案、问题解决）",
        "数据驱动 — 数据讲述、图表主导（适合分析报告、趋势演示）",
        "黄金圈法则 — Why→How→What（适合愿景宣讲、创业路演）"
      ]
    },
    {
      "question": "视觉风格（当前主题：{主题关键词}，已从风格目录匹配以下差异化方案）",
      "options": [
        "风格 A：极简商务 swiss-minimal — 白底+#1A73E8 科技蓝，洁净理性，适合正式汇报/战略提案 (Recommended)",
        "风格 B：暗黑科技 dark-tech — 深灰底+#00D4FF 电光青，未来感强，适合科技产品/AI 主题",
        "风格 C：柔和圆润 soft-rounded — 浅米底+#FF6B6B 珊瑚粉，亲和温暖，适合培训/内部沟通",
        "风格 D：编辑杂志风 editorial — 奶白底+#1A1A1A 墨黑，大留白强排版，适合品牌/创意提案",
        "风格 E：水墨中国风 ink-wash — 宣纸底+#2C3E50 墨蓝，东方美学，适合文化/教育/传统行业"
      ]
    }
  ]
)
```

#### 步骤 4：处理返回结果

- 获取用户对每个 question 的选择/输入
- 将最终确认的方向锚定值记录下来，**不可在后续阶段更改**
- 选定的风格名称即为后续阶段 b 的设计依据
- 选定的画布尺寸将锁定，不可在后续阶段更改
- **固定值（自动锁定，无需用户选择）**：
  - 生成模式：`html`
  - 输出格式：多文件 `{N}.html`（每页独立 HTML，N 从 1 开始）

---

## 阶段 b — 设计锁定

### 目标

将阶段 a 选定的视觉风格转化为精确的、可执行的设计参数。用户确认后即成为 Executor 的"宪法"——后续所有 HTML 页面的颜色、字体、节奏均不得偏离。

### 执行步骤

#### 步骤 1：提取风格精确色板

从 `04-styles.md` 中读取用户选定风格的完整色板定义，按 **60-30-10 法则** 分配角色：

| 色彩角色 | 占比 | 用途 | palette 字段 |
|----------|------|------|-------------|
| 主色（Primary） | ~60% | 背景面积、大面积色块、页面底色 | `bg` |
| 辅色（Secondary） | ~30% | 卡片背景、区块底色、次要区域 | `secondary` |
| 强调色（Accent） | ~10% | 关键数据、CTA、高亮、标题装饰线 | `accent` |
| 文字主色 | — | 正文、标题 | `text` |
| 弱化文字色 | — | 注释、页码、辅助信息 | `muted` |

**60-30-10 原则解释**：
- 60% 是主导色，定义页面的整体情绪——通常用于背景（`bg`）
- 30% 是辅助色，创造视觉层次——通常用于卡片、区块、次要区域（`secondary`）
- 10% 是强调色，引导视线到最重要的信息——用于关键数字、CTA 按钮、重要标记（`accent`）
- 文字色（`text`、`muted`）不计入 60-30-10 比例，但必须与色板协调

**色板输出格式**（6 色，均为 hex 值）：

```
palette:
  bg: '#FAFBFC'         # 页面背景色（占视觉面积 ~60%）
  primary: '#1A73E8'    # 主品牌色（30% 面积的基调，卡片/区块/标题底色）
  secondary: '#E8F0FE'  # 辅色（浅色变体，用于微妙的区块区分）
  accent: '#FF6D00'     # 强调色（10%，关键元素高亮）
  text: '#1F2937'       # 正文文字色
  muted: '#9CA3AF'      # 弱化文字色（注释、页码、次要标签）
```

#### 步骤 2：确定字体配对

基于风格确定标题字体与正文字体的配对。字体必须为 **系统安全字体**（无需外部加载）。

**可选字体清单**：

| 类别 | 中文字体 | 英文字体 | 安全回退 |
|------|---------|---------|---------|
| 无衬线商务 | 微软雅黑 | Segoe UI, Arial, Helvetica | sans-serif |
| 无衬线现代 | 思源黑体 / PingFang SC | Inter, SF Pro Display | sans-serif |
| 衬线正式 | 宋体 / SimSun | Georgia, Times New Roman | serif |
| 等宽技术 | — | Consolas, Monaco, Courier New | monospace |

**字体配对示例**：

| 场景 | 标题字体 | 正文字体 | 适用风格 |
|------|---------|---------|----------|
| 中文商务 | `'Microsoft YaHei', '微软雅黑', sans-serif` / Bold / 42px | `'Microsoft YaHei', '微软雅黑', sans-serif` / Regular / 18px | swiss-minimal, dark-tech |
| 中文现代 | `'PingFang SC', 'Microsoft YaHei', sans-serif` / Bold / 44px | `'PingFang SC', 'Microsoft YaHei', sans-serif` / Regular / 17px | soft-rounded, glassmorphism |
| 中文正式 | `'SimSun', '宋体', 'STSong', serif` / Bold / 40px | `'SimSun', '宋体', 'STSong', serif` / Regular / 16px | editorial, ink-wash |
| 英文为主 | `'Segoe UI', 'Arial', sans-serif` / Bold / 40px | `'Segoe UI', 'Arial', sans-serif` / Regular / 17px | swiss-minimal, dark-tech |
| 中英混排 | `'Microsoft YaHei', 'PingFang SC', sans-serif` / Bold / 42px | `'Segoe UI', 'Arial', 'Microsoft YaHei', sans-serif` / Regular / 17px | 通用 |

**字号层级（基于 1280×720 画布）**：

| 角色 | 字号范围 | 字重 | 用途 |
|------|---------|------|------|
| H1（封面标题） | 48-64px | Bold 700 | 封面主标题 |
| H2（页面标题） | 36-48px | Bold 700 | 各内容页标题 |
| H3（小节标题） | 24-32px | SemiBold 600 | 页面内的分区标题 |
| Body（正文） | 16-20px | Regular 400 | 正文、列表、要点 |
| Caption（注释） | 12-14px | Regular 400 | 数据来源、页码、脚注 |

**字体规范输出格式**：

```
font:
  title: "'Microsoft YaHei', 'PingFang SC', sans-serif"
  title_weight: 700
  title_size: 44
  body: "'Microsoft YaHei', 'PingFang SC', sans-serif"
  body_weight: 400
  body_size: 17
  caption_size: 13
```

#### 步骤 3：页面节奏分配

为每一页分配节奏标签。节奏标签决定 Executor 生成该页时的信息密度和留白策略。

**三种节奏类型**：

| 标签 | 含义 | 信息密度 | 适用页面类型 | 留白策略 |
|------|------|----------|-------------|----------|
| `anchor` | 锚点页 | 极低 | 封面、结束页、重大过渡页 | 大面积留白，仅有标题+副标题，视觉冲击力优先 |
| `dense` | 密集页 | 高 | 数据分析、方案详情、多要点罗列 | 紧凑但不拥挤，利用色块/卡片分层承载信息 |
| `breathing` | 呼吸页 | 中等 | 概念阐述、故事叙述、单图+要点 | 适度留白，给信息以呼吸空间，节奏舒缓 |

**节奏分配原则**：

1. 封面（第 1 页）和结束页（最后 1 页）必须为 `anchor`
2. 重要过渡页（如目录/章节分隔）建议为 `anchor`
3. 不超过 2 页连续 `dense`（避免信息疲劳）
4. `breathing` 作为缓冲页，穿插在 `dense` 页之间
5. `dense` 页面适合放图表、数据、多要点
6. 整体节奏应如呼吸起伏：anchor → breathing → dense → breathing → anchor

**节奏分布表示例**（8 页 PPT）：

| 页码 | 标题 | 节奏 | 说明 |
|------|------|------|------|
| 1 | 封面 | `anchor` | 强制 anchor |
| 2 | 背景与挑战 | `breathing` | 故事引入，舒缓开局 |
| 3 | 核心方案 | `dense` | 方案要点密集展示 |
| 4 | 数据验证 | `dense` | 数据图表，信息量大 |
| 5 | 案例展示 | `breathing` | 案例+配图，呼吸缓冲 |
| 6 | 实施路线 | `dense` | 时间线/路线图 |
| 7 | 总结 | `breathing` | 提炼要点 |
| 8 | 谢谢 | `anchor` | 强制 anchor |

#### 步骤 4：调用 human_interaction

使用 `approval` 类型，展示完整设计系统供用户审批。

**阶段 b 调用示例**：

```
human_interaction(
  interaction_type="approval",
  title="设计系统锁定 — 阶段 b 审批",
  prompt="基于您选择的「{用户选定的风格名称}」风格，以下是锁定的设计系统。请审批后进入内容大纲确认阶段：\n\n## 配色方案（60-30-10 法则）\n- 背景色（60%）：{bg} — 页面主底色\n- 主色（30%）：{primary} — 卡片/区块底色\n- 强调色（10%）：{accent} — 关键数据/高亮元素\n- 正文文字色：{text}\n- 弱化文字色：{muted}\n\n## 字体方案\n- 标题：{title_font} Bold {title_size}px\n- 正文：{body_font} Regular {body_size}px\n- 注释：{body_font} Regular {caption_size}px\n\n## 页面节奏分配\n{节奏分布表}\n\n## 画布与模式\n- 画布：16:9 / 1280×720\n- 生成模式：HTML（支持 data-anim 动效）\n- 风格：{用户选定的风格名称}",
  suggested_response="设计系统没问题，进入内容大纲审批"
)
```

**注意**：`prompt` 中必须包含色板的实际 hex 色块预览（用 markdown 色块或明确标注 hex 值），让用户能想象最终视觉效果。不要只有文字描述。

---

## 阶段 c — 内容审批

### 目标

展示最终的逐页内容方案，让用户在生成 HTML 之前做最后一轮内容层面的审查和调整。

### 执行步骤

#### 步骤 1：组织内容大纲

将 Step 1 产出的大纲与阶段 a/b 确认的设计参数结合，整理为逐页内容方案。每页包含：

1. **页号**：从 1 开始的序号
2. **页面类型**：封面 / 目录 / 内容 / 过渡 / 数据 / 案例 / 总结 / 结束
3. **节奏标签**：`anchor` / `dense` / `breathing`（来自阶段 b 的分配）
4. **页面标题**：精炼、有冲击力的标题（10-20 字为宜）
5. **核心要点**：3-5 条关键信息，每条 15-30 字
6. **配图策略**：该页是否需要图片、图片用途（背景/插图/配图）、推荐尺寸
7. **图表需求**（可选）：如需数据可视化，标注图表类型（柱状图/折线图/饼图/流程图/雷达图）

#### 步骤 2：配图策略规范 — 【强制使用用户图片】

**核心规则：PPT 中的所有配图必须来自用户提供的图片文件，Agent 不自行生成、不搜索网络图片、不使用占位图。**

在此阶段需要明确：

- **检查用户是否已上传图片**：回顾对话中用户消息是否包含 `[用户上传了图片，文件路径: xxx，尺寸: W×Hpx]` 格式的提示
  - **如果用户已上传图片**：根据提示中的**尺寸信息**自动分析每张图片，将其分配到合适的页面。分类规则：
    - 宽度 ≥ 1280 且高度 ≥ 720 → 适合作为 `bg` 全幅背景图
    - 宽度 ≥ 640 → 适合作为 `hero` 主视觉或 `card` 配图
    - 宽度 < 640 → 适合作为 `icon` 或 `portrait`
  - **如果用户未上传图片**：在内容大纲的配图策略中标注 `image_strategy`，并在阶段 c 审批时提醒用户补充图片
- **每张图片的用途**：
  - `bg`：全幅背景图（尺寸与画布一致）
  - `hero`：封面/过渡页主视觉图（推荐画布宽度的 50%）
  - `card`：内容页卡片配图（推荐 400×280）
  - `icon`：小图标/Logo（推荐 128×128）
  - `portrait`：人物头像（推荐 200×200）
- **图片引用方式**：在 HTML 中使用**绝对路径**引用用户上传的图片（如 `C:/Users/.../xxx.png`），**禁止相对路径**（`./xxx.png`）。交付前运行 `attachments/complete_htmls_to_base64.py` 将外部引用转为 base64 内联，输出 `_complete.html`
- **图片缩放规则**：用户上传的图片尺寸已在消息中提供（如 `[用户上传了图片，文件路径: xxx.png，尺寸: W×Hpx]`）。在 HTML 中使用时：
  - 计算缩放比例：`max_w = 画布宽度 - 内边距`，`max_h = 画布高度 - 内边距`
  - 保持宽高比：`scale = min(max_w / img_w, max_h / img_h)`，最终 `width = img_w * scale`，`height = img_h * scale`
  - 大图（> 画布尺寸）→ 等比缩小适配；小图 → 保持原尺寸，不强行拉伸

#### 步骤 2a：图片确认（阶段 c 审批时）

在阶段 c 审批的内容大纲中，必须明确标注：

1. **已匹配的用户图片**：列出 "第 X 页 → 用户图片 `xxx.jpg`（用途：bg/hero/card）"
2. **尚未提供的图片**：列出 "第 Y 页需要配图（用途：card，推荐 400×280），请补充上传"
3. 在 `spec_lock.md` 的每页定义中记录 `user_image` 字段，Executor 据此引用

#### 步骤 3：图表需求规范

扫描内容大纲，主动识别需要数据可视化的页面。**不等待用户指定**，策略师应主动推荐：

| 数据场景 | 推荐图表类型 |
|----------|-------------|
| 数值对比（多组） | 柱状图 / 分组柱状图 |
| 趋势变化 | 折线图 / 面积图 |
| 占比分布 | 饼图 / 环形图 / 堆叠柱状图 |
| 多维评估 | 雷达图 / 热力图 |
| 流程步骤 | 横向流程图（CSS 实现更佳） |
| 时间线 | 纵向时间轴（CSS 实现更佳） |
| 层级关系 | 树状图 / 组织结构图 |

**图表生成说明**：图表将在 Executor 阶段由 Agent 通过 Python + matplotlib 自动生成 PNG，然后内联 base64 到 HTML 中。图表配色必须与 `spec_lock.md` 的 palette 一致。

#### 步骤 4：调用 human_interaction

> **⛔ 阶段 c 必须使用 `approval` 类型。禁止使用 `selection` 类型、禁止把每页标题放入 `questions` 数组、禁止把大纲条目序列化为 JSON 字符串。**

使用 `approval` 类型，**将完整内容大纲写入 `prompt` 字段**。

**阶段 c 调用示例**：

```
human_interaction(
  interaction_type="approval",
  title="内容大纲审批 — 阶段 c 最终确认",
  prompt="以下是完整的逐页内容方案，请审批。批准后将立即生成 design_spec.md 和 spec_lock.md，并自动进入 HTML 生成阶段。\n\n## 风格：{风格名称}\n## 画布：16:9（1280×720）\n## 总页数：{N} 页\n\n### 第 1 页 · 封面「{封面标题}」(anchor)\n- 主标题：{封面大标题}\n- 副标题：{副标题/日期/作者}\n- 配图：背景图 1280×720（需用户提供）\n\n### 第 2 页 · 背景「{页面标题}」(breathing)\n- 要点 1：{核心信息}\n- 要点 2：{核心信息}\n- 要点 3：{核心信息}\n- 配图：无，纯文字+装饰元素\n\n### 第 3 页 · 数据概览「{页面标题}」(dense)\n- 要点 1：{核心信息}\n- 要点 2：{核心信息}\n- 📊 图表：分组柱状图（matplotlib 生成）— 展示 Q1-Q4 营收对比\n- 配图：无\n\n...（逐页列出）\n\n### 第 {N} 页 · 谢谢 (anchor)\n- 主文案：感谢聆听\n- 配图：无，纯文字+风格装饰\n\n---\n## 📋 用户需提供的图片清单\n- 第 1 页背景图：1280×720（封面全幅背景）\n- 第 5 页配图：400×280（案例卡片配图）\n\n## 📊 需自动生成的图表\n- 第 3 页：分组柱状图（matplotlib）\n- 第 6 页：折线图（matplotlib）",
  suggested_response="内容无误，开始生成 HTML"
)
```

### ⛔ 阶段 c 生成模板（直接填充即可）

> **Agent 在生成阶段 c 的 `human_interaction` 调用时，必须严格使用以下模板。直接复制模板、替换 `{...}` 占位符为实际内容，禁止改动结构。**

```
human_interaction(
  interaction_type="approval",
  title="内容大纲审批 — 阶段 c 最终确认",
  prompt="以下是完整的逐页内容方案，请审批。批准后将立即进入 HTML 生成阶段。

## 风格：{用户选定的风格名称}
## 画布：{宽}×{高}（{画布比例}）
## 配色：{bg} / {primary} / {accent}
## 总页数：{N} 页

---

### 第 1 页 · 封面「{封面主标题}」
**类型**：cover | **节奏**：anchor

- 主标题：{封面大标题，12-20字}
- 副标题：{副标题/日期/作者信息}
- 配图策略：{bg 全幅背景 / hero 主视觉 / none}
{若用户已上传图片，标注}→ 使用用户图片：{文件名}（{W}×{H}px，用途：{bg/hero}）

### 第 2 页 · 「{页面标题}」
**类型**：{content / data / case / transition} | **节奏**：{breathing / dense}

- {核心要点 1}（15-30字）
- {核心要点 2}
- {核心要点 3}
- 配图策略：{card / hero / none}
{若用户已上传图片，标注}→ 使用用户图片：{文件名}（{W}×{H}px，用途：{card/hero}）

### 第 3 页 · 「{页面标题}」
**类型**：{类型} | **节奏**：{节奏}

- {核心要点 1}
- {核心要点 2}
- {核心要点 3}
{若有图表}→ 📊 图表：{图表类型}（matplotlib 生成） — {数据描述}
- 配图策略：{策略}

... {逐页列出所有页面，格式同上}

### 第 {N} 页 · 结束「谢谢观看」
**类型**：end | **节奏**：anchor

- 主文案：{谢谢观看 / 感谢聆听 / Q&A}
- 配图策略：none（纯文字 + 风格装饰元素）

---

## 📋 用户需提供的图片清单
{若用户已上传图片则写"用户已提供以下图片："并逐张列出用途分配；若无则写需求列表}
- 第 X 页：{推荐尺寸}（{用途说明}）
- ...

## 📊 需自动生成的图表
{若内容需要图表则列出；无需图表则写"本次 PPT 无需图表"}
- 第 X 页：{图表类型} — {数据内容简述}
- ...",
  suggested_response="内容无误，开始生成 HTML"
)
```

### ⛔ 模板使用铁律

> **以下规则违反任何一条，生成结果即无效。**

| # | 规则 | 错误示例 | 正确做法 |
|---|------|---------|---------|
| 1 | **必须使用 `approval` 类型** | `interaction_type="selection"` | `interaction_type="approval"` |
| 2 | **禁止使用 `questions` 参数** | `questions=[{"question": "第1页标题是？", ...}]` | 不传 `questions`，所有内容写入 `prompt` |
| 3 | **全量大纲在一个 prompt 中** | 分 3 次 human_interaction 逐段确认 | 一次调用包含所有页面 |
| 4 | **prompt 必须是纯 Markdown 文本** | 把大纲序列化为 JSON 字符串嵌入 | 用 Markdown 标题、列表组织内容 |
| 5 | **每页至少列出 3 条要点** | 只写标题不写要点 | 标题 + 3-5 条要点 + 配图策略 |
| 6 | **必须标注已匹配的用户图片** | 有用户图片但不标注用途 | "使用用户图片：xxx.png（1920×1080，用途：bg）" |
| 7 | **图表需求必须写在对应页** | 图表需求只在末尾总结列出 | 在对应页下写 "📊 图表：..." |
| 8 | **禁止阶段 c 使用 `selection`** | 用 selection 让用户逐页勾选 | 用 `approval`，prompt 中一次性展示全部 |
| 9 | **`suggested_response` 必须填写** | 不填或留空 | 填 "内容无误，开始生成 HTML" |
| 10 | **图片按尺寸自动分配** | 不读用户图片尺寸信息 | 根据实际 W×H 判断用途（bg / hero / card / icon） |

---

## 输出规范

用户通过阶段 c 审批后，立即产出以下两份文件。两份文件必须同时生成，内容一致、互为映照。

---

### 文件 1：`design_spec.md`（人工可读设计说明书）

**存放路径**：`workspace/ppt_{topic}/design_spec.md`

**必须包含以下 10 个章节**：

```markdown
# 设计说明书 — {PPT 主题}

## 1. 项目信息
- 项目名称：{PPT 主题}
- 创建日期：{YYYY-MM-DD}
- Skill 版本：v3.0（HTML-Only）
- 生成模式：html

## 2. 画布与交付
- 画布尺寸：{width}×{height}（{用户选择的比例}）
- 输出格式：多文件 `{N}.html`（每页独立 HTML，可单独在浏览器中打开）
- 动效支持：data-anim 声明式动效系统

## 3. 方向锚定（阶段 a 确认结果）
- 目标受众：{用户选择}
- 使用场合：{用户选择}
- 核心信息：{用户输入的一句话核心观点}
- 页数范围：{用户选择}
- 画布比例：{用户选择}
- 叙事风格：{用户选择}
- 视觉风格：{风格名称}（来自 04-styles.md）
- 风格简述：{该风格的核心美学描述，1-2 句话}

## 4. 配色方案（60-30-10 法则）
| 角色 | 色值 | 占比/用途 |
|------|------|-----------|
| 背景色（bg） | `{hex}` | 页面主底色，~60% 视觉面积 |
| 主色（primary） | `{hex}` | 卡片/区块底色，~30% |
| 辅色（secondary） | `{hex}` | 微妙区块区分 |
| 强调色（accent） | `{hex}` | 关键元素高亮，~10% |
| 文字色（text） | `{hex}` | 正文文字 |
| 弱化色（muted） | `{hex}` | 注释/页码/次要标签 |

## 5. 字体方案
| 角色 | 字体 | 字重 | 字号 |
|------|------|------|------|
| 封面标题 | `{font}` | Bold 700 | {size}px |
| 页面标题（H2） | `{font}` | Bold 700 | {size}px |
| 小节标题（H3） | `{font}` | SemiBold 600 | {size}px |
| 正文（Body） | `{font}` | Regular 400 | {size}px |
| 注释（Caption） | `{font}` | Regular 400 | {size}px |

## 6. 页面节奏分配
| 页码 | 标题 | 页面类型 | 节奏 | 说明 |
|------|------|----------|------|------|
| 1 | {标题} | 封面 | anchor | 大面积留白，主标题居中 |
| 2 | {标题} | 内容 | breathing | ... |
| ... | ... | ... | ... | ... |

## 7. 内容大纲
（逐页详细：标题、核心要点 3-5 条、配图策略、图表需求）

## 8. 图片需求清单（用户提供）
| 序号 | 所在页 | 用途 | 推荐尺寸 | 说明 |
|------|--------|------|----------|------|
| 1 | 第 1 页 | bg（封面背景） | 1280×720 | 尽量高清、与主题相关 |
| ... | ... | ... | ... | ... |

## 9. 图表需求清单（Agent 自动生成）
| 序号 | 所在页 | 图表类型 | 数据内容 | 配色约束 |
|------|--------|----------|----------|----------|
| 1 | 第 3 页 | 分组柱状图 | Q1-Q4 营收对比 | 使用 palette 中的 primary + accent |
| ... | ... | ... | ... | ... |

## 10. 技术约束
- 禁止 `<script>` 标签（除动效引擎 + 键盘导航）
- ⛔ 禁止 CSS `@keyframes`，动效必须用 data-anim 系统
- 禁止外部 CDN 引用
- 所有颜色来自本设计说明书 palette
- 画布尺寸锁定（16:9=1280×720 / 4:3=1024×768），禁止 1920×1080
- 图片引用必须使用绝对路径，禁止相对路径 `./xxx.png`
- 根容器内所有元素 `position:absolute` 显式定位
- 动效通过 data-anim 声明式属性驱动
- 图片内联 base64（交付前运行固化脚本）
- 遵循 06-html-standards.md 全部约束
```

---

### 文件 2：`spec_lock.md`（机器可读 YAML 执行合约）

**存放路径**：`workspace/ppt_{topic}/spec_lock.md`

**这是 Executor 生成 HTML 时的唯一数据源。Executor 每页生成前必须重读此文件。**

```yaml
# spec_lock.md — 机器可读执行合约
# 此文件由 Strategist 在阶段 c 审批通过后生成。
# Executor 必须在每页生成前重新读取此文件。
# 禁止手动编辑此文件——任何设计变更应回到 Strategist 阶段重新确认。

meta:
  project_name: "{PPT 主题}"
  created_at: "{YYYY-MM-DD}"
  skill_version: "3.0.0"
  spec_version: "1.0"

canvas:
  width: {由用户阶段a选择}     # 1280 或 1024 或 720
  height: {由用户阶段a选择}    # 720 或 768 或 1280
  aspect_ratio: "{16:9 | 4:3 | 9:16}"  # 用户选择的画布比例
  generation_mode: "html"

palette:
  bg: "{hex}"           # 页面背景色，60% 视觉面积
  primary: "{hex}"      # 主色，卡片/区块
  secondary: "{hex}"    # 辅色，微妙区分
  accent: "{hex}"       # 强调色，10% 关键高亮
  text: "{hex}"         # 正文文字
  muted: "{hex}"        # 弱化文字

font:
  title: "{font_stack}"       # 标题字体 CSS font-family 值
  title_weight: 700
  title_size_px: {number}
  body: "{font_stack}"        # 正文字体 CSS font-family 值
  body_weight: 400
  body_size_px: {number}
  caption_size_px: {number}

style:
  name: "{风格名称}"          # 来自 04-styles.md 的风格 ID
  category: "{风格类目}"       # 企业/产品 | 编辑/出版 | 表现力/印刷 | 手绘/画笔 | 特殊

narrative_style: "{用户阶段a选择的叙事风格}"   # 金字塔原理 | 故事叙述 | SCQA框架 | 数据驱动 | 黄金圈法则

pages:
  - num: 1
    type: "cover"
    rhythm: "anchor"
    title: "{页面标题}"
    subtitle: "{副标题（可选）}"
    key_points:
      - "{核心要点 1（封面通常无要点，可为副标题或日期）}"
    image_strategy: "{bg | hero | card | icon | none}"
    user_image: ""             # 用户提供图片的文件名，如 "cover_bg.jpg"；无图片则为空
    chart: false

  - num: 2
    type: "content"
    rhythm: "breathing"
    title: "{页面标题}"
    key_points:
      - "{核心要点 1}"
      - "{核心要点 2}"
      - "{核心要点 3}"
    image_strategy: "none"
    chart: false

  - num: 3
    type: "data"
    rhythm: "dense"
    title: "{页面标题}"
    key_points:
      - "{核心要点 1}"
      - "{核心要点 2}"
    image_strategy: "none"
    chart:
      type: "bar"              # bar | line | pie | radar | scatter
      title: "{图表标题}"
      data_description: "{数据描述——Executor 据此构造 matplotlib 数据}"
      color_palette: ["primary", "accent", "secondary"]  # 引用 palette 中的角色名

  # ... 更多页面 ...

  - num: {N}
    type: "end"
    rhythm: "anchor"
    title: "感谢聆听"
    key_points: []
    image_strategy: "none"
    chart: false
```

### spec_lock.md 字段规范说明

#### pages 数组每项字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `num` | int | ✅ | 页码，从 1 开始递增 |
| `type` | string | ✅ | 页面类型：`cover` / `toc` / `content` / `data` / `case` / `transition` / `summary` / `end` |
| `rhythm` | string | ✅ | 节奏标签：`anchor` / `dense` / `breathing` |
| `title` | string | ✅ | 页面标题（精炼，10-20 字） |
| `subtitle` | string | ❌ | 副标题（仅 cover/transition 类型可能使用） |
| `key_points` | string[] | ✅ | 核心要点数组，3-5 条；cover/end 可空 |
| `image_strategy` | string | ✅ | 配图策略：`bg` / `hero` / `card` / `icon` / `portrait` / `none`。若为 `none` 以外的值，需用户在内容审批阶段确认是否提供图片 |
| `user_image` | string | ❌ | 用户实际提供的图片文件名（如 `cover_bg.jpg`），存放在 `workspace/ppt_{topic}/images/` 目录。无图片时为空字符串 |
| `chart` | object / false | ✅ | 图表定义对象或无图表时填 `false` |

#### chart 对象字段（chart 不为 false 时）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | ✅ | 图表类型：`bar` / `line` / `pie` / `radar` / `scatter` |
| `title` | string | ✅ | 图表标题 |
| `data_description` | string | ✅ | 自然语言数据描述，Executor 据此构造 matplotlib 数据（如："2023-2026 年各产品线营收：产品A 从 120 增长到 280，产品B 从 80 增长到 190，产品C 从 60 增长到 140"） |
| `color_palette` | string[] | ✅ | 引用 palette 中的角色名（如 `["primary", "accent", "secondary"]`），Executor 据此取色 |

---

## human_interaction 工具通用调用规范

> **⛔ 这是 Strategist 阶段最重要的参考章节。Agent 必须严格遵循以下规范调用 `human_interaction` 工具。**

### 三种类型与适用场景

| 类型 | 核心参数 | 适用场景 | 何时用 |
|------|----------|----------|--------|
| `selection` | `title`, `prompt`, `questions`（含 `options` 数组） | 用户在多个候选方案中做选择 | 阶段 a（方向锚定——风格、受众、场合、页数等有多选性质的问题） |
| `approval` | `title`, `prompt`, `suggested_response` | 用户审批/确认后继续推进 | 阶段 b（设计锁定审批）、阶段 c（内容大纲审批） |
| `information` | `title`, `prompt`, `suggested_response` | 需要用户补充自由文本信息 | 用户未提供足够信息时请求补充（如核心信息、主题描述等） |

### 通用约束

1. **每阶段只调用 1 次 human_interaction**：将该阶段所有待确认项打包在一个调用中，禁止拆分多次调用。
2. **必须提供候选值**：`selection` 类型的每个 question 必须提供 `options` 数组（至少 2 个选项），`information` 类型可以留空 options。
3. **必须标注推荐值**：在有推荐值时标注 `(Recommended)`，帮助用户快速决策。
4. **必须等待返回**：调用 `human_interaction` 后，**必须阻塞等待**工具返回结果，不可在返回前执行任何后续代码、读取文件或生成内容。
5. **用户选择即真理**：后续阶段必须基于用户的实际选择（而非 Agent 的原始推荐）进行推导。如阶段 b 必须基于阶段 a 用户选定的风格提取色板，而非 Agent 首推风格。
6. **options 值必须具体**：不要写"待定"、"用户自定义"、"其他"等模糊选项。所有选项必须是具体、可执行的选择。
7. **prompt 必须包含足够上下文**：让用户在不读任何其他文件的情况下理解每个选项的含义。关键信息（如色板 hex 值、风格简述）需要在 prompt 中直接展示。
8. **⛔ 禁止用其他方式替代 human_interaction**：不得使用 `tool_call(confirm)`、纯文本"请确认"、`ask_user` 或任何其他非 `human_interaction` 的机制来获取用户反馈。

---

## 附录：三阶段 human_interaction 快速参考

> **Agent 在执行 PPT 策略师阶段时，直接复制对应阶段的模板，替换 `{...}` 为实际内容即可。**

---

### 阶段 a — 方向锚定（selection）

```
human_interaction(
  interaction_type="selection",
  title="PPT 方向确认",
  prompt="请确认以下方向性决策（推荐项已标注 Recommended）：",
  questions=[
    {"question": "目标受众", "options": ["高管决策层", "技术/研发团队", "客户/合作伙伴", "内部团队"]},
    {"question": "使用场合", "options": ["正式汇报/提案", "路演/发布会", "培训/教学", "内部会议"]},
    {"question": "页数范围", "options": ["3-5页 极简", "6-10页 标准 (Recommended)", "11-16页 深度"]},
    {"question": "画布尺寸", "options": ["16:9 宽屏 1280×720 (Recommended)", "4:3 传统 1024×768", "A4纵向 720×1280"]},
    {"question": "视觉风格（主题：{主题关键词}）", "options": [
      "{风格A} — {hex主色} {一句话描述} (Recommended)",
      "{风格B} — {hex主色} {一句话描述}",
      "{风格C} — {hex主色} {一句话描述}"
    ]}
  ]
)
```

**规则**：每个 question 必有 options 数组。风格选项从 04-styles.md 匹配 3-5 个，附带主色 hex 值。

---

### 阶段 b — 设计锁定（approval）

```
human_interaction(
  interaction_type="approval",
  title="设计系统确认",
  prompt="基于您选择的「{风格名称}」风格，设计系统如下：

## 配色（60-30-10）
- 背景(60%): {bg_hex}  ■
- 主色(30%): {primary_hex}  ■
- 强调(10%): {accent_hex}  ■
- 正文: {text_hex} / 弱化: {muted_hex}

## 字体
- 标题: {title_font} Bold {title_size}px
- 正文: {body_font} Regular {body_size}px

## 页面节奏
| 页码 | 标题 | 节奏 |
|------|------|------|
| 1 | {封面标题} | anchor |
| 2 | {标题} | {breathing/dense} |
| ... | ... | ... |
| {N} | 谢谢观看 | anchor |

确认后立即锁定，后续生成不可更改。",
  suggested_response="确认，开始内容大纲"
)
```

**规则**：色板 hex 值必须从 04-styles.md 提取，用 ■ 色块或 hex 值直接展示。不可仅文字描述。

---

### 阶段 c — 内容审批（approval）⛔

```
human_interaction(
  interaction_type="approval",
  title="内容大纲确认",
  prompt="以下是逐页内容方案，确认后立即生成 HTML：

## 风格：{风格名称} | 画布：{W}×{H} | 共 {N} 页

### 第 1 页 · 封面「{主标题}」
**cover | anchor**
- 主标题：{12-20字}
- 副标题：{信息}
- 配图：{bg / hero / none} {若用户已传图}→ 用户图片 {文件名}（{W}×{H}，用途：{bg}）

### 第 2 页 · 「{页面标题}」
**{content/data} | {breathing/dense}**
- {要点1}
- {要点2}
- {要点3}
- 配图：{策略}
{有图表}→ 📊 {图表类型} — {数据描述}

... {逐页列出，格式同上}

### 第 {N} 页 · 结束
**end | anchor**
- 主文案：谢谢观看 / Q&A

---
## 📋 图片清单
{列出已匹配的用户图片或需要的图片}

## 📊 图表清单
{列出需自动生成的图表或"无"}",
  suggested_response="确认，开始生成 HTML"
)
```

**⛔ 铁律**：必须用 `approval`，禁止 `selection`、禁止 `questions` 参数。全部大纲写入 `prompt`。

---
