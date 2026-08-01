# 04 — HTML演示视觉风格目录

> **适用路线**：HTML 路线（`generation_mode = "html"`）
> **角色**：18 种预设视觉风格完整索引 — 提供即用配色、字体配对与设计原则
> **读取时机**：Strategist 阶段需要匹配用户场景锁定 `visual_style` 时
> **使用方式**：从下方目录中选择最匹配用户需求的风格，将其色板、字体、布局原则应用于 HTML 生成

---

## 风格速查矩阵

| # | Style ID | 中文名 | 明暗 | 适合场景 | 一句话描述 |
|---|----------|--------|------|----------|-----------|
| 1 | `corporate-clean` | 企业洁净 | 浅 | 商业汇报、年度总结、咨询方案 | 专业可信赖的蓝色商务风 |
| 2 | `dark-tech` | 暗夜科技 | 深 | 技术发布会、AI主题、开发者大会 | 深邃科技感，发光元素点亮暗背景 |
| 3 | `warm-professional` | 温暖专业 | 浅 | 内部培训、团队分享、人力资源 | 暖色调拉近距离，不失专业 |
| 4 | `glassmorphism` | 毛玻璃 | 浅/彩 | 产品发布、设计展示、品牌页面 | 多层半透明卡片，梦幻层次感 |
| 5 | `editorial-elegance` | 编辑风雅 | 浅 | 品牌手册、文化刊物、高端提案 | 衬线字体 + 大量留白，杂志质感 |
| 6 | `neo-minimal` | 新极简 | 浅 | 设计提案、创意方案、极简品牌 | 极度克制，单一强调色点睛 |
| 7 | `vibrant-creative` | 活力创意 | 浅/彩 | 营销提案、创意脑暴、活动策划 | 高饱和撞色，能量四射 |
| 8 | `cyberpunk-neon` | 赛博霓虹 | 深 | 游戏发布、Web3、前瞻科技 | 霓虹灯 + 暗黑背景，街头科幻 |
| 9 | `chinese-ink` | 水墨中国 | 浅 | 文化讲座、中式品牌、国学课程 | 墨色为骨，留白为韵，东方极致 |
| 10 | `nord-cool` | 北欧清冷 | 浅 | 数据报告、学术研究、架构设计 | 冷色调理性克制，信息密度友好 |
| 11 | `natural-organic` | 自然有机 | 浅 | ESG报告、环保品牌、健康生活 | 大地色系 + 圆角，亲和自然 |
| 12 | `bold-impact` | 大胆冲击 | 浅/深 | 融资路演、战略发布、品牌宣言 | 极高对比度，超大字号，一句话震撼 |
| 13 | `soft-pastel` | 柔和粉彩 | 浅 | 亲子教育、女性社区、生活方式 | 马卡龙色系，圆润可爱，零攻击性 |
| 14 | `luxury-gold` | 奢华金 | 深 | 高端品牌、VIP邀请、奢侈品 | 暗底金线，衬线字体，顶级质感 |
| 15 | `tech-startup` | 科技创业 | 浅 | 创业路演、产品Demo Day、SaaS | 白底渐变光，年轻乐观，未来感 |
| 16 | `cream-white` | 米白雅致 | 浅 | 生活美学、日系品牌、婚礼策划 | 暖米白+奶茶棕，手工纸质感 |
| 17 | `cream-green` | 奶油抹茶 | 浅 | 健康餐食、茶文化、瑜伽冥想 | 抹茶绿+奶油底，清新治愈 |
| 18 | `cinematic-teal-orange` | 电影感青橙 | 深 | 影视提案、创意叙事、摄影作品 | 暗青+琥珀橙，好莱坞调色 |

---

## 一、corporate-clean（企业洁净）

### Style: corporate-clean
- **Display Name**：企业洁净
- **Keywords**：专业、信赖、秩序、高效、克制的蓝
- **Best For**：企业年度汇报、咨询方案交付、B2B销售演示、董事会报告、财务分析
- **Aesthetic**：
  经典商务美学 — 以沉稳的藏蓝为骨架，浅灰蓝为辅，营造可信赖、有条理的专业氛围。大面积白色背景确保信息传达清晰无误，蓝色强调色用于引导视线至关键数据与结论。整体气质如同高级管理咨询顾问的着装：精致合身，不张扬，但每一处细节都经得起审视。

  视觉节奏偏向理性均衡 — 图表与数据是主角，装饰退居幕后。卡片以微阴影托起，边框极细乃至不可见，营造"漂浮的信息岛"感。

- **Palette**：
  - `bg`: `#FFFFFF`
  - `primary`: `#1B3A5C`
  - `secondary`: `#E8EEF4`
  - `accent`: `#2563EB`
  - `text`: `#1F2937`
  - `muted`: `#6B7280`

- **Typography**：`Inter Bold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 严格 12 列网格对齐，内容绝不游离网格
  2. 每页标题使用断言式结论（金字塔模式天然契合）
  3. 数据图表占据视觉重心，文字充当辅助注释
  4. 卡片统一使用 `--radius-lg` (12px) + `soft` 阴影
  5. 左右结构优先：左侧标题/要点，右侧图表/数据

- **Animation Style**：`fade-up` 为主，`slide-left` 用于列表项次第出现，延迟 150ms 递增。封面可用 `scale-in` 营造开场仪式感。

- **DO**：
  - ✅ 大量使用图表和数据可视化
  - ✅ 每页标题即核心结论
  - ✅ 保持充足的数据标注和来源说明
  - ✅ 蓝色作为唯一强调色，忌多色分散注意力

- **DON'T**：
  - ❌ 不要使用渐变背景
  - ❌ 不要超过 2 种强调色
  - ❌ 不要使用装饰性插图和无关图标
  - ❌ 不要使用衬线字体（影响数据可读性）

---

## 二、dark-tech（暗夜科技）

### Style: dark-tech
- **Display Name**：暗夜科技
- **Keywords**：科技感、深邃、发光、未来、极客
- **Best For**：技术发布会、AI/ML主题分享、开发者大会演讲、网络安全报告、前沿趋势
- **Aesthetic**：
  深不见底的暗蓝黑色背景如同一块无限延伸的科技画布，上面的内容仿佛浮在夜空中。青色和电光蓝作为发光强调色，在暗背景上产生类似 HUD（抬头显示器）的视觉联想。卡片与元素边界以半透明细线勾勒，配合微妙的发光阴影 (`box-shadow` 扩散)，营造"屏幕内"的沉浸科技体验。

  整体气质冷静而自信 — 像深夜的数据中心，只有必要的信号灯在闪烁，每一束光都有明确目的。

- **Palette**：
  - `bg`: `#0B1120`
  - `primary`: `#1E3A5F`
  - `secondary`: `#17263B`
  - `accent`: `#00D4FF`
  - `text`: `#E2E8F0`
  - `muted`: `#64748B`

- **Typography**：`Inter SemiBold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 暗背景 + 发光元素为核心视觉特征
  2. 使用 `box-shadow: 0 0 20px rgba(0,212,255,0.3)` 模拟发光效果
  3. 卡片背景使用半透明深色 (`rgba(23,38,59,0.7)`)
  4. 边框使用 `1px solid rgba(0,212,255,0.15)` 的细线
  5. 代码块、数据指标使用等宽字体 (`Consolas`) 强化技术感

- **Animation Style**：`fade-up` + 微弱的 `scale-in` 组合，延迟 200ms 递增。关键数据可用 `pop` 弹性动画。可添加 `typewriter` 逐字效果用于代码或关键声明。

- **DO**：
  - ✅ 大量留黑，让发光元素成为焦点
  - ✅ 使用细线网格或点阵装饰背景（科技网格线）
  - ✅ 数据指标做大字号发光处理
  - ✅ 代码片段用等宽字体 + 语法高亮风格的色彩

- **DON'T**：
  - ❌ 不要使用大面积白色或亮色背景块
  - ❌ 不要使用暖色系（破坏冷静科技氛围）
  - ❌ 不要过度阴影 — 用发光 (glow) 代替传统阴影
  - ❌ 不要使用衬线字体

---

## 三、warm-professional（温暖专业）

### Style: warm-professional
- **Display Name**：温暖专业
- **Keywords**：亲切、人性化、暖色调、团队、信赖感
- **Best For**：内部培训、团队建设汇报、人力资源展示、企业文化宣导、客户成功案例
- **Aesthetic**：
  以奶油色和暖灰为基底，用陶土色和焦橙色作为强调 — 仿佛冬日里的一杯热咖啡或一盏暖灯。相比 corporate-clean 的冷峻理性，warm-professional 通过色调的温度感拉近与观众的心理距离，适合"人对人"而非"数据对数据"的沟通场景。

  卡片带有柔和圆角和大面积内边距，文字排版宽松，整体节奏舒缓 — 像一场舒适的炉边对话而非高压会议室报告。

- **Palette**：
  - `bg`: `#FFFBF5`
  - `primary`: `#D4A574`
  - `secondary`: `#FEF0E3`
  - `accent`: `#E07B3C`
  - `text`: `#3D3226`
  - `muted`: `#A09180`

- **Typography**：`Inter SemiBold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 暖色背景避免纯白 (`#FFFBF5` 带微暖底)
  2. 卡片使用 `--radius-xl` (16px) + 柔和阴影
  3. 图文搭配：人物照片/插画与要点文字交替
  4. 列表项使用圆形或柔和的图标标记
  5. 页面内边距慷慨（≥ 48px），营造呼吸感

- **Animation Style**：`fade-up` 为主，延迟 250ms — 节奏从容不迫。避免快节奏动效。

- **DO**：
  - ✅ 使用暖色渐变微调背景（从 `#FFFBF5` 到 `#FEF0E3`）
  - ✅ 大面积的留白和宽松排版
  - ✅ 使用人物相关的 Emoji（👥 🤝 💬）作为点缀
  - ✅ 数据用较大字号呈现，避免密密麻麻的表格

- **DON'T**：
  - ❌ 不要使用冷蓝/冷绿色系
  - ❌ 不要使用锐角边框或直角卡片
  - ❌ 不要过度使用动画（保持安静平和）
  - ❌ 不要让文字密度过高

---

## 四、glassmorphism（毛玻璃）

### Style: glassmorphism
- **Display Name**：毛玻璃
- **Keywords**：通透、层次、梦幻、现代、半透明
- **Best For**：产品发布演示、设计成果展示、品牌形象页、创意提案、App功能展示
- **Aesthetic**：
  以柔和的紫蓝渐变或多彩渐变铺满背景，前景卡片使用半透明磨砂玻璃效果 (`backdrop-filter: blur()` + 半透明白色/深色背景)。多层卡片相互交叠时，透过上层的毛玻璃隐约看到下层内容与背景色彩，形成丰富而梦幻的视觉深度。

  这种风格天生具有"现代设计感"和"精致感" — 仿佛在透过高级玻璃橱窗观看展品，每一层都增加了维度和趣味。

- **Palette**：
  - `bg`: `#F0F0FF`（渐变底层：`linear-gradient(135deg, #E8E0F0, #E0E8F8, #E0F0F0)`）
  - `primary`: `#7C5CBF`
  - `secondary`: `rgba(255,255,255,0.60)`
  - `accent`: `#FF6B9D`
  - `text`: `#2D1B69`
  - `muted`: `#8B7BAF`

- **Typography**：`Inter SemiBold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 背景必须使用多色渐变（≥ 2 色，通常 3 色）或彩色形状装饰
  2. 卡片核心 CSS：`background: rgba(255,255,255,0.60); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.5); border-radius: 16px;`
  3. 卡片可适度交叠排列，使用 `translate` 制造偏移
  4. 强调元素（按钮、关键数字）使用纯色块，与毛玻璃形成对比
  5. 装饰性彩色光晕圆形散布在背景中 (`border-radius: 50%; filter: blur(60px)`)

- **Animation Style**：`fade-up` + 微弱的 `scale-in` (0.95→1)，延迟 200ms。卡片悬停时可轻微上浮并增强阴影。

- **DO**：
  - ✅ 多层毛玻璃卡片制造深度感
  - ✅ 背景使用有机形状的光晕装饰
  - ✅ 适度使用圆角 (16px+)
  - ✅ 关键数据用不透明的强烈色彩打破毛玻璃的柔和感

- **DON'T**：
  - ❌ 不要在毛玻璃卡片上放密集文字（降低可读性）
  - ❌ 不要使用高饱和纯色做卡片背景
  - ❌ 不要过度叠层（≤ 3 层交叠）
  - ❌ 不要忘记 `backdrop-filter` 的浏览器兼容性降级方案

---

## 五、editorial-elegance（编辑风雅）

### Style: editorial-elegance
- **Display Name**：编辑风雅
- **Keywords**：典雅、杂志感、衬线、留白、克制
- **Best For**：品牌手册、文化刊物、高端提案书、设计哲学阐述、年度文化总结
- **Aesthetic**：
  如同翻开一本精心排版的独立杂志 — 衬线字体是绝对主角，无衬线仅用于辅助标注。色彩极度克制，以黑、白和暖灰构成基调，仅用一抹低调的强调色（如深蓝灰或暗红）在关键处点睛。大量留白并非浪费，而是给予文字呼吸的空间，让每一句话都显得重要。

  整体气质安静而自信 — 不靠色彩吸引注意，而是靠内容本身的力度和排版的美感。图片以黑白或低饱和呈现，文字排版本身就是装饰。

- **Palette**：
  - `bg`: `#FAFAF8`
  - `primary`: `#2C2C2C`
  - `secondary`: `#F0EDE8`
  - `accent`: `#8B4513`
  - `text`: `#1A1A1A`
  - `muted`: `#8C8C8C`

- **Typography**：`Merriweather Bold + Noto Serif SC Bold` | `Merriweather Regular + 微软雅黑 Light`

- **Layout Principles**：
  1. 页标题使用衬线字体 (Merriweather / Noto Serif SC)，正文字号偏大 (18-20px)
  2. 非对称布局：文字块偏离中心，留出大面积空白
  3. 装饰元素极简 — 一根细线、一个页码，足矣
  4. 图片黑白处理或低饱和滤镜
  5. 拉大字距 (`letter-spacing: 0.04em`)，增强呼吸感

- **Animation Style**：`fade-in` 仅淡入，无位移 — 保持静谧气质。延迟 300ms 以上，徐徐呈现。

- **DO**：
  - ✅ 衬线字体做标题，字重对比强烈 (Bold vs Light)
  - ✅ 留白面积 ≥ 50%
  - ✅ 使用细线 (`1px solid`) 做视觉分割
  - ✅ 文字排版本身就是设计

- **DON'T**：
  - ❌ 不要使用高饱和色彩
  - ❌ 不要使用阴影和圆角卡片
  - ❌ 不要使用 Emoji 或花哨图标
  - ❌ 不要让任何元素"拥挤"

---

## 六、neo-minimal（新极简）

### Style: neo-minimal
- **Display Name**：新极简
- **Keywords**：极致简洁、几何、单一强调色、留白、建筑感
- **Best For**：设计提案、创意方案、极简品牌展示、架构概览、概念阐述
- **Aesthetic**：
  回归设计的本质 — 去掉一切可去掉的，留下的每一个像素都有其存在的必要性。以纯白为画布，黑色文字为唯一信息载体，仅用一种高饱和强调色（通常是鲜明的珊瑚橙或电光蓝）在关键处画龙点睛。几何形状（圆、方、线条）是唯一的视觉装饰。

  整体气质冷静果敢 — 像现代主义建筑的室内，白墙、清水混凝土，一把亮色椅子就是全场的焦点。这种风格的"大胆"恰恰来自它的"克制"。

- **Palette**：
  - `bg`: `#FFFFFF`
  - `primary`: `#000000`
  - `secondary`: `#F5F5F5`
  - `accent`: `#FF5A45`
  - `text`: `#1A1A1A`
  - `muted`: `#A0A0A0`

- **Typography**：`Inter ExtraLight → Bold 切换` | `Inter Regular`

- **Layout Principles**：
  1. 单一强调色原则：全篇只用 1 个 accent 色（如珊瑚橙 `#FF5A45`）
  2. 大色块几何装饰：圆圈、矩形色块、粗线条
  3. 文字字号极端对比：Hero 64px ↔ Body 14px
  4. 网格对齐严苛，元素绝不对偏
  5. 大面积留白 (≥ 60%)

- **Animation Style**：`fade-up` 简洁利落，延迟 180ms。几何色块可用 `scale-in` 从 0 弹入。

- **DO**：
  - ✅ 用大面积纯色块做视觉冲击
  - ✅ 极端字号对比 (64px vs 14px)
  - ✅ 几何形状做装饰（圆形、矩形、线条）
  - ✅ 每个页面只强调 1 个核心信息

- **DON'T**：
  - ❌ 不要使用渐变
  - ❌ 不要使用阴影（扁平至极）
  - ❌ 不要使用超过 1 个强调色
  - ❌ 不要让内容超过 30 字（这是极简，不是密集）

---

## 七、vibrant-creative（活力创意）

### Style: vibrant-creative
- **Display Name**：活力创意
- **Keywords**：高饱和、渐变、能量、大胆、年轻
- **Best For**：营销提案、创意脑暴会、活动策划方案、品牌Campaign、社交媒体报告
- **Aesthetic**：
  不惧色彩 — 高饱和度的橙、紫、粉、青在页面上碰撞、融合，渐变是传递能量的主要手段。背景可能是从紫到橙的暖色渐变，卡片可能是半透明的彩色玻璃效果，文字可能是白色反白在彩色块上。

  整体气质热烈奔放 — 像创意团队的头脑风暴墙，每一张便签都是荧光色，每一笔涂鸦都充满能量。这不是给保守派准备的设计，这是给敢于说"让我们试试这个大胆的想法"的人准备的。

- **Palette**：
  - `bg`: `#FFF5F0`
  - `primary`: `#FF6B35`
  - `secondary`: `#FFE0D3`
  - `accent`: `#7C3AED`
  - `text`: `#2D1B15`
  - `muted`: `#C49585`

- **Typography**：`Inter Bold + 微软雅黑 Bold` | `Inter Medium + 微软雅黑`

- **Layout Principles**：
  1. 大胆使用双色或三色渐变 (`linear-gradient(135deg, #FF6B35, #FF3D8E)`)
  2. 卡片使用大圆角 (16px) + 彩色边框
  3. 文字可以在彩色色块上使用反白
  4. 装饰元素可以使用有机波浪形状
  5. 不对称布局，打破网格限制

- **Animation Style**：`pop` 弹性动画为首选，`scale-in` + `fade-up` 组合，延迟 120ms — 快节奏、有活力。

- **DO**：
  - ✅ 使用高饱和渐变做大标题背景
  - ✅ 大胆撞色（橙×紫、粉×青、黄×蓝）
  - ✅ 不规则布局打破沉闷
  - ✅ 使用表情丰富的 Emoji

- **DON'T**：
  - ❌ 不要使用灰色或低饱和色
  - ❌ 不要让页面出现大面积白色空白
  - ❌ 不要使用正式/严肃的语气（风格不配）
  - ❌ 不要所有元素对齐网格 — 刻意破格是风格的一部分

---

## 八、cyberpunk-neon（赛博霓虹）

### Style: cyberpunk-neon
- **Display Name**：赛博霓虹
- **Keywords**：霓虹灯、暗黑、赛博朋克、未来都市、故障艺术
- **Best For**：游戏发布会、Web3/区块链项目、科幻主题活动、电音派对、次世代产品
- **Aesthetic**：
  黑夜 + 霓虹灯 — 这是赛博朋克视觉的核心公式。深黑或极暗紫的底色上，洋红 (`#FF2D95`)、电青 (`#00F0FF`)、硫黄 (`#FFE600`) 作为霓虹管道的三种颜色，以细线、发光文字和几何边框的形式出现。网格线和斜线装饰让人联想到雨夜霓虹都市的街道。

  整体气质叛逆而前卫 — 像《银翼杀手》的视觉语言被搬进了演示文稿。发光文字似乎悬浮在潮湿的暗夜空气中，每一个像素都在宣告"我们是未来"。

- **Palette**：
  - `bg`: `#0A0A0A`
  - `primary`: `#1A0030`
  - `secondary`: `#110022`
  - `accent`: `#FF2D95`
  - `text`: `#F0E6FF`
  - `muted`: `#6B5080`

- **Typography**：`Inter Bold + 微软雅黑` | `Consolas + 微软雅黑`

- **Layout Principles**：
  1. 暗黑背景 + 霓虹色 (洋红 `#FF2D95` / 电青 `#00F0FF` / 硫黄 `#FFE600`)
  2. 文字发光效果：`text-shadow: 0 0 10px currentColor, 0 0 30px currentColor`
  3. 边框使用霓虹发光：`border: 2px solid #FF2D95; box-shadow: 0 0 10px #FF2D95, inset 0 0 10px rgba(255,45,149,0.2)`
  4. 背景叠加网格线或斜线图案 (CSS `repeating-linear-gradient`)
  5. 可添加故障艺术效果 (clip-path 动画、text-shadow 重影)

- **Animation Style**：`fade-up` + 霓虹闪烁 (`@keyframes neon-flicker`)，延迟 100ms。可添加故障抖动 (`@keyframes glitch-skew`) 用于标题。

- **DO**：
  - ✅ 霓虹文字发光效果是标志性特征，务必使用
  - ✅ 暗色背景叠加网格线
  - ✅ 使用等宽字体做代码/数据展示
  - ✅ 三种霓虹色交替使用，保持视觉丰富

- **DON'T**：
  - ❌ 不要使用白色或浅色背景
  - ❌ 不要使用传统阴影（发光代替阴影）
  - ❌ 不要使用衬线字体
  - ❌ 不要过度使用故障效果（1-2 处足够）

---

## 九、chinese-ink（水墨中国）

### Style: chinese-ink
- **Display Name**：水墨中国
- **Keywords**：东方、水墨、留白、禅意、中国红
- **Best For**：文化讲座、中式品牌展示、国学课程、茶道/书法活动、传统节庆
- **Aesthetic**：
  以宣纸般的米白为底色，浓淡墨色为文字与骨架，中国红 (`#C41E3A`) 仅用于印章、标题点缀或关键标记 — 如同一幅水墨画上的朱砂印，克制而贵重。装饰元素以晕染墨点、枯笔线条、竹节纹样为主，通过 CSS 的 `radial-gradient` 和 `opacity` 模拟水墨的浓淡干湿。

  整体气质沉静内敛 — 不争不抢，以"少即是多"、"空即是满"的东方哲学驾驭视觉。留白不是空白，而是想象的空间。

- **Palette**：
  - `bg`: `#F8F4ED`
  - `primary`: `#2C2C2C`
  - `secondary`: `#EBE5D9`
  - `accent`: `#C41E3A`
  - `text`: `#3A3A3A`
  - `muted`: `#A09888`

- **Typography**：`Noto Serif SC Bold` | `Noto Serif SC Regular + 微软雅黑 Light`

- **Layout Principles**：
  1. 宣纸底色 (`#F8F4ED`) + 墨色文字
  2. 竖排文字可选（CSS `writing-mode: vertical-rl`），还原中式排版
  3. 中国红 (`#C41E3A`) 仅用于印章大小的小面积点缀
  4. 使用 `radial-gradient` 制作墨点晕染效果
  5. 大面积留白，文字集中在一侧（如左上或右中）

- **Animation Style**：`fade-in` 缓慢淡入，延迟 400ms — 如水墨在宣纸上缓缓晕开。可配合 `@keyframes ink-spread` 模拟墨迹扩散。

- **DO**：
  - ✅ 衬线字体是灵魂，务必使用 Noto Serif SC
  - ✅ 留白占总面积 50% 以上
  - ✅ 使用墨色渐变模拟浓淡
  - ✅ 中国红克制使用（≤ 3% 面积）

- **DON'T**：
  - ❌ 不要使用无衬线字体做标题
  - ❌ 不要使用渐变背景（破坏宣纸质感）
  - ❌ 不要使用 Emoji（破坏东方意境）
  - ❌ 不要使用阴影和发光效果

---

## 十、nord-cool（北欧清冷）

### Style: nord-cool
- **Display Name**：北欧清冷
- **Keywords**：理性、清冷、Nord调色板、学术、克制
- **Best For**：数据报告、学术研究展示、架构设计文档、技术方案、科学演讲
- **Aesthetic**：
  基于著名的 Nord 调色板，以冰霜蓝灰 (`#ECEFF4`) 为背景，极夜蓝 (`#2E3440`) 为文字，霜蓝 (`#5E81AC`、`#88C0D0`) 和冷绿 (`#A3BE8C`) 为辅助色系。整体色调像北极圈的晨曦 — 清冷、干净、没有一丝多余的温度。

  这是一种高度理性、数据友好型的风格 — 低饱和冷色调对长时间阅读最为友好，不会视觉疲劳，同时通过色彩的温度感暗示客观和中立。

- **Palette**：
  - `bg`: `#ECEFF4`
  - `primary`: `#2E3440`
  - `secondary`: `#D8DEE9`
  - `accent`: `#5E81AC`
  - `text`: `#2E3440`
  - `muted`: `#81A1C1`

- **Typography**：`Inter Regular + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 严格网格对齐，所有元素边界清晰
  2. 图表使用 Nord 调色板衍生的 6 色数据系列
  3. 卡片无阴影或仅微弱阴影，依赖边框区分层次
  4. 代码块使用 `#2E3440` 深色背景 + Nord 语法高亮
  5. 信息密集但留白充足，确保可读性

- **Animation Style**：`fade-up` 简洁，延迟 150ms。无弹性、无晃动 — 保持理性。

- **DO**：
  - ✅ 严格遵循 Nord 调色板，不引入额外颜色
  - ✅ 数据可视化优先
  - ✅ 使用等宽字体展示代码
  - ✅ 图表色系使用 Nord 衍生色

- **DON'T**：
  - ❌ 不要使用暖色系
  - ❌ 不要使用高饱和色彩
  - ❌ 不要使用弹性动画或炫酷特效
  - ❌ 不要让装饰元素占据空间

---

## 十一、natural-organic（自然有机）

### Style: natural-organic
- **Display Name**：自然有机
- **Keywords**：大地色、有机形状、亲和、可持续、温暖
- **Best For**：ESG报告、环保品牌展示、健康生活方案、户外活动、有机食品
- **Aesthetic**：
  从森林、土壤、苔藓和秋叶中提取色彩 — 墨绿 (`#386641`)、苔绿 (`#6A994E`)、暖棕 (`#BC6C25`)、奶油 (`#FEFAE0`)。这些色彩本身就传达了可持续、健康和温暖的品牌联想。配合大圆角 (20px+)、有机波浪形状和植物相关 Emoji (🌿🌱🍃)，每个页面都像一片自然栖息地。

  整体气质亲和接地 — 没有凌厉的直线，没有冷冰冰的数据面板，一切元素都像被自然之手打磨过，柔软、圆润、有温度。

- **Palette**：
  - `bg`: `#FEFAE0`
  - `primary`: `#386641`
  - `secondary`: `#E9F5DB`
  - `accent`: `#BC6C25`
  - `text`: `#2D3A1E`
  - `muted`: `#8B9A6E`

- **Typography**：`Inter SemiBold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 大圆角 (`--radius-xl` 16px+)，柔和卡片
  2. 使用有机波浪形状 (`border-radius` 非对称) 作为装饰
  3. 自然意象 Emoji (🌿🌱🍃🌍💚) 作为图标
  4. 卡片使用暖色背景而非白色
  5. 图片使用圆角裁剪或圆形遮罩

- **Animation Style**：`fade-up` 为主，延迟 250ms — 柔和舒缓的节奏。波浪装饰可用 `@keyframes wave` 轻微浮动。

- **DO**：
  - ✅ 使用大地色系，远离冷蓝/冷灰
  - ✅ 大圆角和有机形状
  - ✅ 自然类 Emoji 点缀
  - ✅ 图文结合，自然摄影优先

- **DON'T**：
  - ❌ 不要使用纯黑文字（用深棕/深绿替代）
  - ❌ 不要使用直角和锐利边框
  - ❌ 不要使用霓虹色或荧光色
  - ❌ 不要让数据图表过于冰冷（暖色系列）

---

## 十二、bold-impact（大胆冲击）

### Style: bold-impact
- **Display Name**：大胆冲击
- **Keywords**：超大字体、极简文字、高对比、宣言式、震撼
- **Best For**：融资路演核心页、品牌宣言、战略发布会、创业Pitch关键帧、广告Campaign
- **Aesthetic**：
  "少到极致，大到惊人" — 每个页面只承载 1 个核心信息，用 72-96px 的超大字号占据画面 60% 以上面积。配色是极端的二元对立：黑底白字或白底黑字，加一个高饱和的强调色（如正红 `#FF003C` 或亮黄 `#FFEA00`）在唯一的关键词上爆发出全部能量。

  这不是信息传递，这是视觉宣言。每一页都像一张独立的海报，合在一起就是一场视觉上的"重低音轰炸"。

- **Palette**：
  - `bg`: `#000000`
  - `primary`: `#000000`
  - `secondary`: `#1A1A1A`
  - `accent`: `#FF003C`
  - `text`: `#FFFFFF`
  - `muted`: `#888888`

- **Typography**：`Inter Black (900) + 微软雅黑 Bold` | `Inter Bold + 微软雅黑 Bold`

- **Layout Principles**：
  1. 每页只放 1 个核心信息，字号 72-120px
  2. 文字占据画面 60-80% 面积
  3. 强调色仅用于 1-2 个关键词
  4. 其他元素（Logo、页码）缩小至 12-14px 放在角落
  5. 可以跨页拆分一个长句，形成叙事节奏

- **Animation Style**：`scale-in` 从 0 弹入 (0→1.05→1)，延迟 100ms — 冲击力最大化。配合 `pop` 弹性动画于关键词。

- **DO**：
  - ✅ 超大字号 (72px+) 是核心特征
  - ✅ 每页 ≤ 10 个字
  - ✅ 高对比度黑白 + 一个高饱和强调色
  - ✅ 跨页叙事：一句话拆成多页

- **DON'T**：
  - ❌ 不要在页面上放超过 15 个字
  - ❌ 不要使用渐变背景
  - ❌ 不要使用卡片、图表等复合元素
  - ❌ 不要添加装饰性元素（字本身即是装饰）

---

## 十三、soft-pastel（柔和粉彩）

### Style: soft-pastel
- **Display Name**：柔和粉彩
- **Keywords**：马卡龙色、圆润、可爱、亲和、零攻击性
- **Best For**：亲子教育、女性社区、生活方式品牌、甜品/烘焙、幼儿园/早教
- **Aesthetic**：
  马卡龙色系 — 樱花粉 (`#FFD1DC`)、薄荷绿 (`#B5EAD7`)、宝宝蓝 (`#C7CEEA`)、奶油黄 (`#FFF1B0`)、薰衣草紫 (`#E2D1F9`) — 柔和得仿佛加了柔光滤镜。所有元素都使用大圆角 (16-24px)，卡片像棉花糖一样蓬松柔软，阴影轻柔如羽毛。

  整体气质甜美可亲 — 没有任何尖锐的边角，没有任何刺眼的色彩，像走进一家精致的法式甜品店，一切都让人心情愉悦。

- **Palette**：
  - `bg`: `#FFF9FB`
  - `primary`: `#FFD1DC`
  - `secondary`: `#FFEBF0`
  - `accent`: `#FF8FAB`
  - `text`: `#5D4E53`
  - `muted`: `#C4A8B0`

- **Typography**：`Inter SemiBold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 全圆角 (16-24px)，无直角
  2. 柔和渐变背景 (从粉到蓝到紫的极淡渐变)
  3. 卡片使用蓬松的大 padding (40px+)
  4. 装饰使用圆形、云朵形状
  5. 柔和阴影：`box-shadow: 0 4px 20px rgba(255,143,171,0.15)`

- **Animation Style**：`fade-up` + 轻微 `scale-in` (0.95→1)，延迟 250ms — 缓缓的、柔软的呈现。可配合 `@keyframes float` 轻微浮动。

- **DO**：
  - ✅ 马卡龙色系，避免任何高饱和色
  - ✅ 大圆角 + 柔和阴影
  - ✅ 可爱风格 Emoji (🌸💕✨🎀🍰)
  - ✅ 宽松排版，大量 padding

- **DON'T**：
  - ❌ 不要使用纯黑文字（用柔和的深棕/深粉代替）
  - ❌ 不要使用直角和锐利边框
  - ❌ 不要让信息密度高
  - ❌ 不要使用冷色调（保持暖粉基调）

---

## 十四、luxury-gold（奢华金）

### Style: luxury-gold
- **Display Name**：奢华金
- **Keywords**：奢华、金色、暗底、高级、专属
- **Best For**：高端品牌展示、VIP邀请函、奢侈品推介、私人会所、高端地产
- **Aesthetic**：
  极暗的底色（近乎纯黑或深棕黑）之上，金色 (`#D4AF37` / `#C5A55A`) 是唯一的"光源"。衬线字体以金色呈现，搭配精细的金色分割线 (`1px solid gold`)，如同一张烫金的高级信纸被放置在黑丝绒之上。

  整体气质尊贵克制 — 不需要解释自己有多贵，金色本身就说明了一切。字距拉大 (`letter-spacing: 0.08em`)，留白慷慨，每个字都值得被注视。

- **Palette**：
  - `bg`: `#0D0D0D`
  - `primary`: `#1A1A1A`
  - `secondary`: `#222222`
  - `accent`: `#D4AF37`
  - `text`: `#E8E0D0`
  - `muted`: `#8A8068`

- **Typography**：`Merriweather Bold + Noto Serif SC Bold` | `Merriweather Regular + 微软雅黑 Light`

- **Layout Principles**：
  1. 极暗背景 (`#0D0D0D`) + 金色文字与装饰线
  2. 衬线字体是必需条件
  3. 金色分割线 (`1px solid #D4AF37`) 作为唯一点缀
  4. 文字居中或非对称偏移，大面积留黑
  5. 字距拉大 (`letter-spacing: 0.06em~0.12em`)

- **Animation Style**：`fade-in` 缓慢淡入，延迟 350ms — 如天鹅绒幕布缓缓拉开。金色元素可用 `@keyframes gold-shimmer` 模拟金属光泽流动。

- **DO**：
  - ✅ 金色 (`#D4AF37`) 作为唯一强调色
  - ✅ 衬线字体，字距拉大
  - ✅ 极暗背景，大面积留黑
  - ✅ 金色细线作为视觉装饰

- **DON'T**：
  - ❌ 不要使用白色或浅色背景
  - ❌ 不要使用无衬线字体
  - ❌ 不要引入金色以外的彩色
  - ❌ 不要让信息密度过高

---

## 十五、tech-startup（科技创业）

### Style: tech-startup
- **Display Name**：科技创业
- **Keywords**：现代、乐观、紫蓝渐变、年轻、SaaS
- **Best For**：创业路演、SaaS产品Demo、创新提案、增长报告、孵化器Demo Day
- **Aesthetic**：
  明亮的白色背景上，一条从紫 (`#7C3AED`) 到蓝 (`#3B82F6`) 到青 (`#06B6D4`) 的渐变色带作为贯穿全篇的视觉线索 — 可以是标题下的强调条、卡片的顶部边框、关键数据的颜色或背景的装饰光晕。这种渐变配色自 2020 年代以来已成为"科技创业"的视觉代名词：乐观、成长、连接、未来。

  整体气质年轻自信 — 像一家刚获得 A 轮融资的初创公司，PPT 里散发着"我们在改变世界"的能量。

- **Palette**：
  - `bg`: `#FFFFFF`
  - `primary`: `#7C3AED`
  - `secondary`: `#F5F3FF`
  - `accent`: `#06B6D4`
  - `text`: `#1E1B4B`
  - `muted`: `#94A3B8`

- **Typography**：`Inter Bold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 白底 + 紫→蓝→青渐变作为贯穿主题的视觉线索
  2. 卡片顶部/左侧使用渐变边框 (`border-top: 3px solid transparent; border-image: linear-gradient(...)`)
  3. 关键数据使用渐变文字 (`background-clip: text`)
  4. 装饰性渐变光晕圆形散布在角落
  5. 右上角放置 Logo，页面底部渐变条收尾

- **Animation Style**：`fade-up` + `scale-in` 组合，延迟 150ms — 有活力但不急躁。封面可使用渐变流动动画 (`@keyframes gradient-shift`)。

- **DO**：
  - ✅ 紫蓝青渐变色带作为视觉主线
  - ✅ 白色背景保持干净
  - ✅ 数据指标做大字号 + 渐变文字
  - ✅ 使用 🚀⚡💡 等科技创业 Emoji

- **DON'T**：
  - ❌ 不要使用暗色背景（区别于 dark-tech）
  - ❌ 不要在渐变之外引入其他强色
  - ❌ 不要让渐变过度使用（每页 ≤ 3 处渐变元素）
  - ❌ 不要使用衬线字体

---

## 十六、cream-white（米白雅致）

### Style: cream-white
- **Display Name**：米白雅致
- **Keywords**：米白、温柔、雅致、纯净、日系
- **Best For**：生活美学提案、日系品牌展示、婚礼策划、高端下午茶、SPA/护肤品牌
- **Aesthetic**：
  以温暖的米白色为基底，搭配奶茶棕和燕麦色，营造如同手工纸或亚麻布般的自然肌理感。整体色调如同冬日暖阳透过白纱窗帘洒在原木桌面 — 柔和、安静、有温度但不甜腻。没有刺眼的白，也没有沉闷的灰，每一个色块都经过"加一点暖"的处理。

  排版宽松有致，卡片边缘如同手工撕纸般微微毛边，大量留白让文字呼吸。适合传递"品质感"和"匠心"而非"效率"和"数据"的场景。

- **Palette**：
  - `bg`: `#FDF8F0`
  - `primary`: `#C9A87C`
  - `secondary`: `#F5EDE0`
  - `accent`: `#B8860B`
  - `text`: `#4A3728`
  - `muted`: `#B0A090`

- **Typography**：`Georgia + 宋体` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 米白底色 (`#FDF8F0`) 带微暖底，避免冷白
  2. 卡片背景使用比底色略深的暖灰 (`#F5EDE0`)
  3. 细线装饰使用金色/棕色 (`#C9A87C`)，如烫金线条
  4. 大面积留白（≥ 50%），信息集中在中央或左侧
  5. 图片使用暖色调滤镜或黑白+暖棕调色

- **Animation Style**：`fade-in` 缓慢淡入，延迟 300ms — 如轻纱缓落。静且慢，不急不躁。

- **DO**：
  - ✅ 大面积米白+暖棕配色
  - ✅ 衬线字体做标题（优雅感）
  - ✅ 细金线/棕线做装饰分割
  - ✅ 使用 🕯️🌾✨ 等温暖意象
  - ✅ 图片加暖色叠加层 (`background-color: rgba(201,168,124,0.15)`)

- **DON'T**：
  - ❌ 不要使用纯白 (`#FFFFFF`) 底色
  - ❌ 不要使用冷色调（蓝/绿/紫）
  - ❌ 不要使用霓虹色或高饱和色
  - ❌ 不要让文字密度过高

---

## 十七、cream-green（奶油绿）

### Style: cream-green
- **Display Name**：奶油抹茶
- **Keywords**：抹茶绿、奶油、清新、自然、治愈
- **Best For**：健康餐食品牌、茶文化展示、瑜伽/冥想、有机农场、环保手作
- **Aesthetic**：
  如同抹茶拿铁般的温柔配色 — 以奶油黄绿为底，抹茶绿为主色，搭配淡薄荷和燕麦白。整体色调清新但不刺眼，有绿色植物的活力但加了一层奶油滤镜变得柔和可亲。仿佛坐在阳光明媚的庭院里喝着抹茶，微风拂过绿植。

  圆角是标配 (16-20px)，卡片微微浮起，装饰元素以小叶片、圆点、细波纹为主。整个页面散发出"天然、健康、慢生活"的信号。

- **Palette**：
  - `bg`: `#FAFAF0`
  - `primary`: `#8B9E6B`
  - `secondary`: `#EDF2E8`
  - `accent`: `#D4A853`
  - `text`: `#3D4A35`
  - `muted`: `#9AAA8A`

- **Typography**：`Inter SemiBold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 奶油黄绿底色 (`#FAFAF0`)，带微妙绿意
  2. 抹茶绿主色 (`#8B9E6B`) 用于标题、卡片标题栏
  3. 淡奶油辅助色 (`#EDF2E8`) 用于卡片背景
  4. 大圆角 (16-20px)，柔和阴影
  5. 装饰用小叶片 🍃 或圆点阵列

- **Animation Style**：`fade-up`，延迟 220ms — 轻柔上浮，如叶片轻落。

- **DO**：
  - ✅ 抹茶绿+奶油底配色
  - ✅ 大圆角+柔和阴影
  - ✅ 自然意象装饰（🍃🌿🍵）
  - ✅ 宽松排版，充足留白

- **DON'T**：
  - ❌ 不要使用纯黑文字（用深绿代替）
  - ❌ 不要使用高饱和绿（荧光绿/霓虹绿）
  - ❌ 不要使用锐利边角和直角卡片
  - ❌ 不要引入暖红/暖橙（破坏绿色基调）

---

## 十八、cinematic-teal-orange（电影感青橙）

### Style: cinematic-teal-orange
- **Display Name**：电影感青橙
- **Keywords**：青橙调色、电影感、对比、叙事、戏剧性
- **Best For**：品牌微电影提案、影视项目路演、创意故事叙述、摄影作品集、年度回顾
- **Aesthetic**：
  灵感来自好莱坞 Teal & Orange 经典调色 — 暗青（深蓝绿）为背景底色，琥珀橙为强调高光，形成经典的互补色对撞。这种配色自《变形金刚》《疯狂的麦克斯》以来已成为"电影感"的视觉代名词：暗部偏青蓝，高光偏暖橙，画面自带戏剧张力和叙事感。

  文字以暖白 (`#F5EDE0`) 反白在暗青色背景上，强调数据/标题用琥珀橙 (`#F7931E`) 点亮。装饰线条模仿电影画幅的宽银幕比例，分割线使用青到橙的渐变。

- **Palette**：
  - `bg`: `#0D2628`
  - `primary`: `#1A3C40`
  - `secondary`: `#1E3335`
  - `accent`: `#F7931E`
  - `text`: `#F5EDE0`
  - `muted`: `#7A8A8B`

- **Typography**：`Inter Bold + 微软雅黑` | `Inter Regular + 微软雅黑`

- **Layout Principles**：
  1. 暗青底色 (`#0D2628`) + 暖白文字 (`#F5EDE0`)
  2. 琥珀橙 (`#F7931E`) 用于关键强调 — 不超过 10% 面积
  3. 宽银幕比例装饰条（顶部/底部 60px 高的暗色条）
  4. 文字排版有电影字幕般的精致感 — 字距略大 (`letter-spacing: 0.03em`)
  5. 卡片使用半透明暗色背景 (`rgba(26,60,64,0.6)`) + 细边框

- **Animation Style**：`fade-up` 为主，延迟 180ms — 序幕般徐徐展开。可使用 `wipe-right` 模拟电影画幅展开效果。

- **DO**：
  - ✅ 暗青+琥珀橙互补色对撞
  - ✅ 宽银幕装饰条（上/下黑边）
  - ✅ 暖白文字反白在暗底上
  - ✅ 标题字距略大 (`letter-spacing: 0.04em`)
  - ✅ 使用 🎬🎥✨ 等电影意象

- **DON'T**：
  - ❌ 不要使用白色或浅色背景
  - ❌ 不要在橙色之外引入其他暖色（红/粉/紫）
  - ❌ 不要使用衬线字体（不适合电影风格）
  - ❌ 不要让信息密度过高（保持电影海报般的大气）

---

## 附录：风格选择决策树

```
用户场景是面向...
├── 企业/商务/正式汇报
│   ├── 数据重型 → corporate-clean
│   ├── 品牌/文化 → editorial-elegance
│   └── 高端/奢侈 → luxury-gold
├── 科技/互联网
│   ├── 深色/未来感 → dark-tech
│   ├── 创业/年轻 → tech-startup
│   ├── 游戏/Web3 → cyberpunk-neon
│   └── 理性/学术 → nord-cool
├── 温暖/人文/团队
│   ├── 专业但亲和 → warm-professional
│   └── 环保/自然 → natural-organic
├── 创意/设计/营销
│   ├── 大胆/冲击 → bold-impact
│   ├── 活力/多彩 → vibrant-creative
│   ├── 梦幻/层次 → glassmorphism
│   └── 极简/克制 → neo-minimal
├── 柔和/女性/生活
│   ├── 甜美/亲和 → soft-pastel
│   └── 优雅/品质 → cream-white
├── 中式/传统/文化
│   └── 东方/禅意 → chinese-ink
├── 自然/健康/环保
│   ├── 大地色/可持续 → natural-organic
│   └── 清新/治愈 → cream-green
└── 影视/叙事/创意
    └── 戏剧性/电影感 → cinematic-teal-orange
```

---
