# 01 — 总调度：HTML 幻灯片生成工作流总览

> **角色**：主调度器（Master Orchestrator）
> **读取时机**：任何幻灯片生成任务启动时，**最先读取此文件**
> **职责**：定义完整的 3 步串行流水线、全局执行纪律、角色切换协议。本 Skill 仅输出 HTML，无 SVG、无 PPTX。

---

## ⛔ 最重要规则：用户对齐

**Step 2（Strategist）是唯一的用户交互阻断点。此步骤中的所有决策必须通过 `human_interaction` 工具与用户对齐，Agent 不得自行决策。具体包括 3 个阶段，每个阶段必须独立调用 `human_interaction` 并等待用户确认。**

违反此规则的后果：生成的 PPT 风格、内容、配色可能与用户预期严重偏离，导致返工。

---

## 核心流水线

```
用户请求
  │
  ├── Step 1: 源内容收集 ──────────── 读取/研究用户素材 → 结构化内容大纲
  │
  ├── Step 2: Strategist 策略师阶段 ⛔ BLOCKING（三阶段用户确认）
  │     ├── 阶段 a — 方向锚定（受众/场合/主题/页数/视觉风格）
  │     │    └── human_interaction(selection) → 展示 3-5 匹配风格
  │     ├── 阶段 b — 设计锁定（配色/字体/页面节奏分配）
  │     │    └── human_interaction(approval) → 确认色板 + 字体 + 节奏
  │     └── 阶段 c — 内容审批（逐页标题 + 要点 + 配图策略）
  │          └── human_interaction(approval) → 确认内容大纲
  │          └── 产出：design_spec.md + spec_lock.md
  │
  ├── Step 3: Executor 执行师阶段 ──── 生成图表 → 逐页编写独立 HTML
  │     ├── 每页生成前重读 spec_lock.md
  │     ├── 参考 layouts/ 与 templates/ 模板
  │     ├── 图表用 matplotlib 生成 PNG → 内联 base64
  │     ├── 每页为独立 HTML 文件（1.html、2.html、...）
  │     └── {N}.html
  │
  └── Step 4: QA & 交付 ──────────── 质量检查 → 图片内联固化 → 交付清单
```

3 个生成步骤**严格串行**，每步的输出是下一步的输入。Step 2 是唯一阻断点，用户确认后 Step 3-4 自动化推进。

---

## 全局执行纪律（12 条铁律）

| # | 规则 | 详细说明 |
|---|------|----------|
| 1 | **串行执行** | 步骤必须按 1→2→3→4 顺序执行，不可跳跃、不可并行。同一步骤内的子任务可并行。 |
| 2 | **BLOCKING = 硬停止** | 标记 ⛔ 的阶段必须等待用户通过 `human_interaction` 显式确认。确认前不可执行任何后续代码或输出。**这是硬性规则，违反即废弃当前生成结果。** |
| 3 | **禁止跨阶段捆绑** | Strategist 的三个阶段（a/b/c）各自独立等待确认，不可在一个 `human_interaction` 调用中打包多个阶段。 |
| 4 | **入口前验证（GATE）** | 每步进入前必须检查前置条件是否满足。条件不满足时向用户说明缺失项并等待。 |
| 5 | **禁止推测执行** | 不要在等待用户确认期间"提前准备"后续步骤的内容、颜色、布局或代码。所有生成动作必须在对应的确认返回后开始。 |
| 6 | **禁止子代理生成页面** | HTML 页面必须由当前主 Agent 端到端完成。不可委托子代理、不可脚本批量生成 HTML 代码。 |
| 7 | **逐页顺序生成** | 页面必须一页一页生成，禁止批量、禁止并行。生成每页前必须先重读 `spec_lock.md`。 |
| 8 | **每页重读 spec_lock** | 每生成一个 HTML 页面之前，必须重新读取 `spec_lock.md` 以获取最新的锁定设计规范。这是防止 Agent 上下文窗口偏移造成风格漂移的关键措施。 |
| 9 | **颜色唯一来源** | HTML 中使用的任何颜色必须来自 `spec_lock.md` 中 `palette` 字段定义的色板。禁止自行引入新颜色、禁止使用浏览器默认色。 |
| 10 | **HTML Only — 无 SVG / 无 PPTX** | 本 Skill 仅输出 HTML 文件。不生成 SVG、不转换 PPTX。如果用户需要 PPTX 格式，向用户说明当前 Skill 版本仅支持 HTML 输出。 |
| 11 | **⛔ 必须使用 human_interaction 工具** | 任何需要用户选择、确认、补充信息的位置，**必须**调用 `human_interaction` 工具（`selection` / `approval` / `information` 三种类型）。**禁止以纯文本回复代替工具调用。禁止使用 `tool_call(confirm)` 或任何其他机制替代。** |
| 12 | **生成模式恒为 html，多文件输出** | `generation_mode` 始终为 `html`。每页输出为独立 HTML 文件（1.html、2.html、...），每个文件自包含可独立打开。画布尺寸由用户在阶段 a 选择（16:9 / 4:3 / A4纵向）。 |

---

## 三步详解

### Step 1 — 源内容收集

**目标**：将用户提供的所有素材整理为结构化的 Markdown 内容大纲。

**处理逻辑**：
- 用户上传了文件（文档/大纲/笔记）→ 阅读理解，提取关键信息，整理为层级化大纲
- 用户仅提供主题、无详细材料 → 基于主题进行知识检索，整理为覆盖核心要点的 Markdown 大纲
- 用户提供了零散想法/要点 → 归类、补充逻辑链条，组织为连贯的大纲

**输出规范**：
- 使用 Markdown 标题层级（`#` / `##` / `###`）表示信息层次
- 每个一级标题对应一个候选页面
- 在要点旁标注推断的页面节奏类型（anchor / dense / breathing）（初步判断，后续策略师阶段会精调）

**GATE**：必须产出至少 3 个以上候选页面的结构化大纲，方可进入 Step 2。

---

### Step 2 — Strategist 策略师阶段 ⛔ BLOCKING — 必须通过 human_interaction 与用户对齐

> **进入前必须先读取 `02-strategist.md` + `04-styles.md`**

这是整个流水线中**唯一需要用户交互的阻断步骤**。Agent **不得跳过、不得自行决策、不得用任何其他方式替代 `human_interaction` 调用**。策略师需要完成三阶段确认，每阶段必须独立调用 `human_interaction` 并等待用户响应，最终产出两份文件：

- `design_spec.md`：人类可读的设计说明书
- `spec_lock.md`：机器可读的 YAML 执行合约

三个阶段各自独立阻塞：

| 阶段 | 目标 | human_interaction 类型 | 关键输入文件 |
|------|------|------------------------|-------------|
| a — 方向锚定 | 确定受众、场合、主题方向、页数范围、视觉风格 | `selection` | `04-styles.md`（从中匹配 3-5 个风格可选） |
| b — 设计锁定 | 确定配色色板（含 hex）、字体配对、页面节奏分配 | `approval` | `04-styles.md` 中选中风格的精确色板 |
| c — 内容审批 | 逐页确认标题、关键要点、配图/图表策略 | `approval`（⛔ 禁止用 selection） | Step 1 产出的内容大纲 |

**每阶段约束**：
- 阶段 a：必须从 `04-styles.md` 风格目录中根据用户需求匹配 **3-5 个候选风格**，每个风格附带精确色板预览（hex 色块），通过 `human_interaction(selection)` 展示。
- 阶段 b：基于阶段 a 用户选定的风格，提取其精确配色、字体规范。输出页面节奏分配表（anchor / dense / breathing），通过 `human_interaction(approval)` 锁定。
- 阶段 c：**⛔ 必须使用 `approval` 类型**。将完整内容大纲（逐页标题 + 要点 + 配图策略）写入 `prompt` 字段。**禁止使用 `selection` 类型、禁止把每页标题放入 `questions` 数组。**

**⛔ 三阶段全部确认完毕后，产出 `design_spec.md` 和 `spec_lock.md`，然后自动进入 Step 3。**

---

### Step 3 — Executor 执行师阶段

> **进入前必须先读取 `07-executor.md` + `06-html-standards.md` + `05-layout-patterns.md`**
> **如有动画需求，还需读取 `08-animation-system.md`**
> **如有图表需求，还需读取图表生成参考（matplotlib）**

**核心流程**：

1. **⛔ 创建项目子目录**：`terminal_execute mkdir workspace/ppt_{topic}`
2. **生成图表**（如有）：用 Python + matplotlib 生成图表 PNG，保存至项目子目录
3. **逐页生成 HTML section**：
   - 每生成一页前，**必须先重读 `spec_lock.md`**
   - 根据 `spec_lock.md` 中该页的 `rhythm` 标签，参考 `05-layout-patterns.md` 选择对应布局
   - 将图表 PNG 转为 base64 内联进 HTML
   - 根据 `08-animation-system.md` 为页面元素添加 `data-anim` 声明式动效属性
   - 每页生成为独立 HTML 文件
4. **生成演讲备注**（可选）：每页的备注信息统一写入 `speaker_notes.md`

**硬约束**：
- 禁止子代理生成页面
- 必须逐页顺序生成
- 每页前重读 spec_lock.md
- 所有颜色来自 spec_lock.md palette
- HTML 中禁止 `<script>` 标签（除动效引擎 + 键盘导航）
- ⛔ 禁止 CSS `@keyframes`，动效必须用 data-anim 系统
- 禁止外部 CDN 引用
- 画布尺寸锁定（16:9=1280×720 / 4:3=1024×768），禁止 1920×1080
- 图片引用必须使用绝对路径，禁止相对路径 `./xxx.png`
- 根容器内所有元素 `position:absolute` 显式定位
- 每页输出为独立文件 `{N}.html`（**纯数字，禁止 `1_cover.html` 等**）

---

### Step 4 — QA & 交付

> **进入前必须先读取 `09-quality-checklist.md`**

**质检清单**：
- 所有页面生成完毕（页数与 spec_lock.md 一致）
- ⛔ 画布尺寸校验：每页根 div 宽高是否与 spec_lock.md canvas 完全一致（16:9 检查 1280×720）
- 每页颜色使用来自 palette，无越权颜色
- 无 `<script>` 标签（除动效引擎 + 键盘导航）
- ⛔ 无 CSS `@keyframes` 定义
- 图片引用全部使用绝对路径，无 `./xxx.png` 相对路径
- 无外部 CDN 引用（字体、图标、样式均内联或使用系统安全字体）
- 每页 HTML 文件可在浏览器中独立打开
- 动画属性 data-anim 正确声明，动效不重叠冲突
- 图片已内联为 base64

**交付**：
- 使用 `doc_tool create` 逐页写出 `{N}.html`
- 运行 `python {SKILL_DIR}/attachments/complete_htmls_to_base64.py {workspace_dir}` 将外部图片引用转为 base64，产出 `{N}_complete.html`
- 向用户汇报最终交付：`{N}_complete.html`（所有图片已内联，每页可在浏览器中独立打开预览）
- 提示用户打开 `{N}_complete.html` 即可逐页浏览全部幻灯片

---

## 角色切换协议

每次角色切换时，**必须先完整读取对应角色文档**，不可凭记忆执行。

| 切换到 | 必须先读取 |
|--------|-----------|
| Strategist | `02-strategist.md` |
| 风格匹配（Strategist 阶段 a） | `04-styles.md` |
| 设计系统参考（Strategist 阶段 b） | `03-design-system.md` |
| Executor | `07-executor.md` + `06-html-standards.md` + `05-layout-patterns.md` |
| 动效引擎（Executor） | `08-animation-system.md` |
| QA & 交付 | `09-quality-checklist.md` |
| 图片内联固化 | `attachments/complete_htmls_to_base64.py`（运行即可） |

---

## 入口路由

根据用户意图选择执行路径：

| 用户意图 | 执行路径 |
|----------|----------|
| 从零生成幻灯片（有主题/素材） | 完整 1→2→3→4 流水线 |
| 只有主题无材料 | Step 1 知识检索 → 完整后续 |
| 仅生成设计规范（不产出 HTML） | Step 1-2，止于 design_spec.md |
| 从已有 spec_lock 继续生成 | 跳过 Step 1-2，直接 Step 3-4 |
| 修改已有 HTML 某页 | 用户指定页面编号 → 重读 spec_lock.md → 重新生成该页 |
| 调整配色/风格 | 回到 Step 2 阶段 b 重新锁定设计 |

---

## 附件清单

| 文件 | 角色/职责 | 何时读取 |
|------|-----------|----------|
| `01-workflow.md` | **总调度**（当前文件） | 任务启动时（最先读） |
| `02-strategist.md` | **策略师** — 三阶段确认流程 | Step 2 进入前 |
| `03-design-system.md` | 设计系统 — 配色规则、字体层级、排版规范、卡片系统 | Strategist 阶段 b + Executor |
| `04-styles.md` | **风格目录** — 15+ 预设视觉风格及精确色板 | Strategist 阶段 a |
| `05-layout-patterns.md` | 布局模式 — 各页面类型的 HTML 布局模板与节奏定义 | Executor 开始前 |
| `06-html-standards.md` | HTML 技术约束 — 画布尺寸、CSS 能力边界、禁止项 | Executor 每页生成时 |
| `07-executor.md` | **执行师** — 逐页 HTML 生成指南、动效策略、图表处理 | Executor 进入时 |
| `08-animation-system.md` | 动效系统 — data-anim 声明式动画属性与内置动效引擎 | Executor 生成需要动效时 |
| `09-quality-checklist.md` | 质检清单 — HTML 质量检查项与交付规范 | QA 阶段 |
| `templates/` | 模板库 — 预置 HTML 模板（封面、过渡页、内容页、结束页） | Executor 参考复用 |
| `attachments/complete_htmls_to_base64.py` | 固化脚本 — 将外部图片引用转为 base64 内联 | 交付前最后一步 |
