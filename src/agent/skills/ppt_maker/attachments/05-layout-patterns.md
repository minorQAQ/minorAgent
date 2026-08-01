# 05 — HTML 布局模式指南

> **角色**：HTML 路线专属布局参考手册 — 每种模式提供完整 HTML 模板（1280×720 画布）
> **读取时机**：HTML 路线 Executor 阶段规划每页布局时
> **参考来源**：oh-my-ppt 项目布局体系 + CSS 原生能力

---

## 通用 CSS 变量声明

所有模板共享以下 CSS 自定义属性（定义在 `<style>` 块中，按主题替换色值）：

```css
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
```

> 实际使用中根据 `spec_lock.md` 的 palette 替换色值。

---

## 一、anchor 页面（封面 / 过渡页，≤30 字）

### 1. Cover — Hero Centered（封面 — 大标题居中 + 底部色条）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 主标题 & 副标题 -->
  <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
              height:580px;text-align:center;">
    <h1 data-anim="fade-up" data-anim-duration="0.8s"
        style="font-size:48px;font-weight:bold;color:var(--text);margin:0;letter-spacing:0.02em;">
      主标题在此
    </h1>
    <p data-anim="fade-up" data-anim-delay="0.2s"
       style="font-size:24px;color:var(--muted);margin:16px 0 0 0;">
      副标题或一句话描述
    </p>
  </div>

  <!-- 底部装饰色条 -->
  <div data-anim="wipe-right" data-anim-duration="0.8s"
       style="position:absolute;bottom:0;left:0;width:1280px;height:140px;
              background:linear-gradient(135deg,var(--primary),var(--secondary));">
    <p style="position:absolute;bottom:24px;left:80px;font-size:14px;color:rgba(255,255,255,0.85);margin:0;"
       data-anim="fade-up" data-anim-delay="0.6s">
      作者 / 日期
    </p>
  </div>
</div>
```

**设计要点**：
- 标题 48px Bold，副标题 24px muted
- 底部色条 140px 高，用 `linear-gradient` 主色→辅色
- data-anim 顺序：标题 → 副标题(+0.2s) → 作者(+0.6s)，色条用 `wipe-right`

---

### 2. Cover — Split（封面 — 左文右图）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 左侧文字区 580px -->
  <div style="position:absolute;top:0;left:0;width:580px;height:720px;
              display:flex;flex-direction:column;justify-content:center;padding-left:80px;">
    <h1 data-anim="slide-right" data-anim-duration="0.7s"
        style="font-size:48px;font-weight:bold;color:var(--text);margin:0 0 16px 0;">
      主标题
    </h1>
    <p data-anim="slide-right" data-anim-delay="0.15s"
       style="font-size:24px;color:var(--muted);margin:0 0 32px 0;">
      副标题内容
    </p>
    <div data-anim="fade-up" data-anim-delay="0.4s">
      <p style="font-size:14px;color:var(--muted);margin:0;">作者姓名</p>
      <p style="font-size:14px;color:var(--muted);margin:4px 0 0 0;">2026-07</p>
    </div>
  </div>

  <!-- 右侧图片/装饰区 700px -->
  <div data-anim="fade-up" data-anim-delay="0.3s"
       style="position:absolute;top:0;right:0;width:700px;height:720px;
              background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);">
    <div style="display:flex;align-items:center;justify-content:center;height:100%;">
      <span style="font-size:120px;opacity:0.3;color:#FFFFFF;">◆</span>
    </div>
  </div>
</div>
```

**设计要点**：
- 左侧 580px 文字区，右侧 700px 图片/装饰区
- 文字区用 flex 垂直居中，`slide-right` 动效
- 右侧可用纯色渐变 + 装饰图标，或替换为 `<img>` 背景图

---

### 3. Section Divider（章节过渡页）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <div style="display:flex;flex-direction:column;justify-content:center;
              height:720px;padding-left:160px;">
    <!-- 章节编号 — 大字 muted -->
    <span data-anim="fade-up"
          style="font-size:64px;font-weight:bold;color:var(--muted);opacity:0.15;margin-bottom:8px;">
      02
    </span>
    <!-- 章节标题 -->
    <h1 data-anim="fade-up" data-anim-delay="0.15s"
        style="font-size:42px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">
      章节标题
    </h1>
    <!-- 装饰线 -->
    <div data-anim="wipe-right" data-anim-delay="0.35s" data-anim-duration="0.6s"
         style="width:200px;height:4px;background:var(--primary);border-radius:2px;margin-bottom:16px;"></div>
    <!-- 副标题 -->
    <p data-anim="fade-up" data-anim-delay="0.5s"
       style="font-size:24px;color:var(--muted);margin:0;">
      章节副标题或简要说明
    </p>
  </div>
</div>
```

**设计要点**：
- 章节编号 64px、opacity:0.15 做背景大字
- 装饰线 200×4px，用 `wipe-right` 揭示动效
- 左侧 160px padding 留白，整体靠左对齐

---

## 二、dense 页面（内容页，≤80 字）

### 4. 2×2 Cards（四宫格卡片）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:80px;font-size:32px;font-weight:bold;
             color:var(--text);margin:0;">
    页面标题
  </h2>

  <!-- 2×2 卡片网格 -->
  <div data-anim-stagger
       style="position:absolute;top:110px;left:80px;width:1120px;
              display:grid;grid-template-columns:repeat(2,548px);
              grid-template-rows:repeat(2,260px);gap:24px;">
    <!-- 卡片 1 -->
    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--primary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">📊</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">卡片标题 1</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        卡片内容描述文字，简要说明此板块的核心要点与关键信息。
      </p>
    </div>

    <!-- 卡片 2 -->
    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--secondary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">🚀</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">卡片标题 2</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        卡片内容描述文字，简要说明此板块的核心要点与关键信息。
      </p>
    </div>

    <!-- 卡片 3 -->
    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--accent);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">⚡</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">卡片标题 3</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        卡片内容描述文字，简要说明此板块的核心要点与关键信息。
      </p>
    </div>

    <!-- 卡片 4 -->
    <div data-anim="fade-up"
         style="background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
                padding:32px;display:flex;flex-direction:column;">
      <div style="width:48px;height:48px;border-radius:12px;background:var(--primary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:20px;">
        <span style="font-size:24px;color:#FFFFFF;">🔒</span>
      </div>
      <h3 style="font-size:20px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">卡片标题 4</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
        卡片内容描述文字，简要说明此板块的核心要点与关键信息。
      </p>
    </div>
  </div>
</div>
```

**设计要点**：
- 卡片 548×260，24px 间隙，border-radius:16px
- 图标区 48×48，border-radius:12px
- `data-anim-stagger` 让 4 张卡片依次淡入（50ms 间隔）
- 卡片内边距 32px，标题 20px Bold，正文 16px

---

### 5. KPI Dashboard（3×1 KPI 指标 + 底部图表）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:80px;font-size:32px;font-weight:bold;
             color:var(--text);margin:0;">
    核心指标概览
  </h2>

  <!-- 3 个 KPI 卡片 -->
  <div data-anim-stagger
       style="position:absolute;top:110px;left:80px;width:1120px;
              display:flex;gap:40px;">

    <!-- KPI 1 -->
    <div data-anim="scale-in"
         style="flex:1;height:120px;background:var(--card-bg);border-radius:16px;
                box-shadow:var(--card-shadow);padding:24px 32px;
                display:flex;flex-direction:column;justify-content:center;
                border-left:4px solid var(--primary);">
      <span style="font-size:36px;font-weight:bold;color:var(--primary);">+23.5%</span>
      <span style="font-size:14px;color:var(--muted);margin-top:8px;">同比增长率</span>
    </div>

    <!-- KPI 2 -->
    <div data-anim="scale-in"
         style="flex:1;height:120px;background:var(--card-bg);border-radius:16px;
                box-shadow:var(--card-shadow);padding:24px 32px;
                display:flex;flex-direction:column;justify-content:center;
                border-left:4px solid var(--secondary);">
      <span style="font-size:36px;font-weight:bold;color:var(--secondary);">1,856</span>
      <span style="font-size:14px;color:var(--muted);margin-top:8px;">活跃项目数</span>
    </div>

    <!-- KPI 3 -->
    <div data-anim="scale-in"
         style="flex:1;height:120px;background:var(--card-bg);border-radius:16px;
                box-shadow:var(--card-shadow);padding:24px 32px;
                display:flex;flex-direction:column;justify-content:center;
                border-left:4px solid var(--accent);">
      <span style="font-size:36px;font-weight:bold;color:var(--accent);">8.5/10</span>
      <span style="font-size:14px;color:var(--muted);margin-top:8px;">客户满意度</span>
    </div>
  </div>

  <!-- 底部图表区域 -->
  <div data-anim="fade-up" data-anim-delay="0.4s"
       style="position:absolute;top:270px;left:80px;width:1120px;height:400px;
              background:var(--card-bg);border-radius:16px;box-shadow:var(--card-shadow);
              display:flex;align-items:center;justify-content:center;">
    <img src="./chart_1.png"
         style="width:1080px;height:360px;object-fit:contain;" alt="趋势图表">
  </div>
</div>
</div>
```

**设计要点**：
- KPI 卡片 380×120，40px 间距，左侧 4px 彩色边框做视觉锚点
- 数值 36px Bold 彩色，标签 14px muted
- 底部图表区 1120×400，内嵌图表图片
- 卡片用 `scale-in` 动效，`data-anim-stagger` 依次出现

---

### 6. Left Text / Right Image（左文右图）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:80px;font-size:32px;font-weight:bold;
             color:var(--text);margin:0;">
    页面标题
  </h2>

  <!-- 左侧文字区 -->
  <div data-anim-stagger
       style="position:absolute;top:120px;left:80px;width:540px;">
    <div data-anim="slide-right"
         style="display:flex;align-items:flex-start;margin-bottom:28px;">
      <span style="flex-shrink:0;width:8px;height:8px;border-radius:50%;background:var(--primary);
                   margin-top:6px;margin-right:16px;"></span>
      <div>
        <h3 style="font-size:18px;font-weight:bold;color:var(--text);margin:0 0 6px 0;">要点标题 1</h3>
        <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
          要点描述文字，展开说明此要点的具体内容与细节。
        </p>
      </div>
    </div>

    <div data-anim="slide-right"
         style="display:flex;align-items:flex-start;margin-bottom:28px;">
      <span style="flex-shrink:0;width:8px;height:8px;border-radius:50%;background:var(--secondary);
                   margin-top:6px;margin-right:16px;"></span>
      <div>
        <h3 style="font-size:18px;font-weight:bold;color:var(--text);margin:0 0 6px 0;">要点标题 2</h3>
        <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
          要点描述文字，展开说明此要点的具体内容与细节。
        </p>
      </div>
    </div>

    <div data-anim="slide-right"
         style="display:flex;align-items:flex-start;margin-bottom:28px;">
      <span style="flex-shrink:0;width:8px;height:8px;border-radius:50%;background:var(--accent);
                   margin-top:6px;margin-right:16px;"></span>
      <div>
        <h3 style="font-size:18px;font-weight:bold;color:var(--text);margin:0 0 6px 0;">要点标题 3</h3>
        <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.6;">
          要点描述文字，展开说明此要点的具体内容与细节。
        </p>
      </div>
    </div>
  </div>

  <!-- 右侧图片区 -->
  <div data-anim="fade-up" data-anim-delay="0.3s"
       style="position:absolute;top:120px;right:60px;width:560px;height:520px;
              border-radius:16px;overflow:hidden;box-shadow:var(--card-shadow);">
    <img src="./image_1.png"
         style="width:100%;height:100%;object-fit:cover;" alt="配图">
  </div>
</div>
</div>
```

**设计要点**：
- 左侧文字区 540px，右侧图片 560×520（含 60px 右边距）
- 要点用 8px 圆点 + 标题(18px) + 描述(16px)的组合
- 图片容器用 `border-radius:16px;overflow:hidden;` 做圆角裁剪
- 文字用 `data-anim-stagger` + `slide-right` 依次滑入

---

### 7. Top Image / Bottom Text（上图下文）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 顶部图片区 -->
  <div data-anim="fade-up"
       style="position:absolute;top:0;left:0;width:1280px;height:360px;
              overflow:hidden;background:var(--border-color);">
    <img src="./image_1.png"
         style="width:100%;height:100%;object-fit:cover;" alt="配图">
  </div>

  <!-- 底部文字区 -->
  <div style="position:absolute;top:400px;left:0;width:1280px;padding:0 80px;">
    <h2 data-anim="slide-right"
        style="font-size:32px;font-weight:bold;color:var(--text);margin:0 0 24px 0;">
      页面标题
    </h2>

    <!-- 三列要点 -->
    <div data-anim-stagger
         style="display:flex;gap:32px;">
      <div data-anim="fade-up"
           style="flex:1;background:var(--card-bg);border-radius:12px;
                  box-shadow:var(--card-shadow);padding:24px;">
        <h3 style="font-size:18px;font-weight:bold;color:var(--primary);margin:0 0 8px 0;">
          要点 1
        </h3>
        <p style="font-size:15px;color:var(--muted);margin:0;line-height:1.5;">
          相关描述内容，简洁明了。
        </p>
      </div>
      <div data-anim="fade-up"
           style="flex:1;background:var(--card-bg);border-radius:12px;
                  box-shadow:var(--card-shadow);padding:24px;">
        <h3 style="font-size:18px;font-weight:bold;color:var(--secondary);margin:0 0 8px 0;">
          要点 2
        </h3>
        <p style="font-size:15px;color:var(--muted);margin:0;line-height:1.5;">
          相关描述内容，简洁明了。
        </p>
      </div>
      <div data-anim="fade-up"
           style="flex:1;background:var(--card-bg);border-radius:12px;
                  box-shadow:var(--card-shadow);padding:24px;">
        <h3 style="font-size:18px;font-weight:bold;color:var(--accent);margin:0 0 8px 0;">
          要点 3
        </h3>
        <p style="font-size:15px;color:var(--muted);margin:0;line-height:1.5;">
          相关描述内容，简洁明了。
        </p>
      </div>
    </div>
  </div>
</div>
</div>
```

**设计要点**：
- 图片区 1280×360（占画布 50%高度），`object-fit:cover`
- 下方文字区 320px 高度，标题 32px + 三列卡片
- 卡片 border-radius:12px，padding:24px，15px 正文

---

### 8. 3-Column Feature（三列特性展示）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:52px;left:50%;transform:translateX(-50%);
             font-size:32px;font-weight:bold;color:var(--text);margin:0;text-align:center;">
    核心特性
  </h2>

  <!-- 三列 -->
  <div data-anim-stagger
       style="position:absolute;top:160px;left:0;width:1280px;
              display:flex;justify-content:center;gap:40px;padding:0 80px;">

    <!-- 列 1 -->
    <div data-anim="fade-up"
         style="flex:0 0 340px;display:flex;flex-direction:column;align-items:center;text-align:center;">
      <div style="width:80px;height:80px;border-radius:20px;background:var(--primary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:24px;">
        <span style="font-size:36px;">🏆</span>
      </div>
      <h3 style="font-size:22px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">特性标题</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.7;">
        关于此特性的详细描述，说明其价值与使用场景，让观众快速理解核心优势。
      </p>
    </div>

    <!-- 列 2 -->
    <div data-anim="fade-up"
         style="flex:0 0 340px;display:flex;flex-direction:column;align-items:center;text-align:center;">
      <div style="width:80px;height:80px;border-radius:20px;background:var(--secondary);
                  display:flex;align-items:center;justify-content:center;margin-bottom:24px;">
        <span style="font-size:36px;">⚙️</span>
      </div>
      <h3 style="font-size:22px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">特性标题</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.7;">
        关于此特性的详细描述，说明其价值与使用场景，让观众快速理解核心优势。
      </p>
    </div>

    <!-- 列 3 -->
    <div data-anim="fade-up"
         style="flex:0 0 340px;display:flex;flex-direction:column;align-items:center;text-align:center;">
      <div style="width:80px;height:80px;border-radius:20px;background:var(--accent);
                  display:flex;align-items:center;justify-content:center;margin-bottom:24px;">
        <span style="font-size:36px;">🔐</span>
      </div>
      <h3 style="font-size:22px;font-weight:bold;color:var(--text);margin:0 0 12px 0;">特性标题</h3>
      <p style="font-size:16px;color:var(--muted);margin:0;line-height:1.7;">
        关于此特性的详细描述，说明其价值与使用场景，让观众快速理解核心优势。
      </p>
    </div>
  </div>
</div>
</div>
```

**设计要点**：
- 每列 340px 宽，40px 间距，`flex:0 0 340px` 防止收缩
- 图标区 80×80，border-radius:20px，彩色背景 + emoji 图标
- 标题居中、描述居中，22px 标题 + 16px 正文
- `data-anim-stagger` 控制三列依次出现

---

### 9. Timeline（时间线）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:80px;font-size:32px;font-weight:bold;
             color:var(--text);margin:0;">
    发展历程
  </h2>

  <!-- 时间线容器 -->
  <div data-anim-stagger
       style="position:absolute;top:140px;left:140px;width:1060px;">

    <!-- 节点 1 -->
    <div data-anim="slide-left" style="display:flex;align-items:flex-start;margin-bottom:32px;">
      <!-- 时间标识 -->
      <div style="flex-shrink:0;width:100px;text-align:right;padding-right:24px;">
        <span style="font-size:16px;font-weight:bold;color:var(--primary);">2022 Q1</span>
      </div>
      <!-- 时间线枢纽 -->
      <div style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;margin-right:24px;">
        <div style="width:16px;height:16px;border-radius:50%;background:var(--primary);
                    border:3px solid var(--bg);box-shadow:0 0 0 2px var(--primary);"></div>
        <div style="width:2px;flex:1;min-height:60px;background:var(--border-color);"></div>
      </div>
      <!-- 内容卡片 -->
      <div style="flex:1;background:var(--card-bg);border-radius:12px;
                  box-shadow:var(--card-shadow);padding:20px 24px;">
        <h3 style="font-size:18px;font-weight:bold;color:var(--text);margin:0 0 6px 0;">里程碑标题</h3>
        <p style="font-size:15px;color:var(--muted);margin:0;">关键事件描述，发生了什么以及带来的影响。</p>
      </div>
    </div>

    <!-- 节点 2 -->
    <div data-anim="slide-left" style="display:flex;align-items:flex-start;margin-bottom:32px;">
      <div style="flex-shrink:0;width:100px;text-align:right;padding-right:24px;">
        <span style="font-size:16px;font-weight:bold;color:var(--secondary);">2023 Q3</span>
      </div>
      <div style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;margin-right:24px;">
        <div style="width:16px;height:16px;border-radius:50%;background:var(--secondary);
                    border:3px solid var(--bg);box-shadow:0 0 0 2px var(--secondary);"></div>
        <div style="width:2px;flex:1;min-height:60px;background:var(--border-color);"></div>
      </div>
      <div style="flex:1;background:var(--card-bg);border-radius:12px;
                  box-shadow:var(--card-shadow);padding:20px 24px;">
        <h3 style="font-size:18px;font-weight:bold;color:var(--text);margin:0 0 6px 0;">里程碑标题</h3>
        <p style="font-size:15px;color:var(--muted);margin:0;">关键事件描述，发生了什么以及带来的影响。</p>
      </div>
    </div>

    <!-- 节点 3 -->
    <div data-anim="slide-left" style="display:flex;align-items:flex-start;margin-bottom:32px;">
      <div style="flex-shrink:0;width:100px;text-align:right;padding-right:24px;">
        <span style="font-size:16px;font-weight:bold;color:var(--accent);">2025 Q1</span>
      </div>
      <div style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;margin-right:24px;">
        <div style="width:16px;height:16px;border-radius:50%;background:var(--accent);
                    border:3px solid var(--bg);box-shadow:0 0 0 2px var(--accent);"></div>
        <div style="width:2px;flex:1;min-height:60px;background:var(--border-color);"></div>
      </div>
      <div style="flex:1;background:var(--card-bg);border-radius:12px;
                  box-shadow:var(--card-shadow);padding:20px 24px;">
        <h3 style="font-size:18px;font-weight:bold;color:var(--text);margin:0 0 6px 0;">里程碑标题</h3>
        <p style="font-size:15px;color:var(--muted);margin:0;">关键事件描述，发生了什么以及带来的影响。</p>
      </div>
    </div>
  </div>
</div>
</div>
```

**设计要点**：
- 垂直时间线，时间标签(100px) → 圆点枢纽(16px) → 连接线(2px) → 内容卡片
- 每个节点一个彩色圆点，border + box-shadow 实现双环效果
- 卡片 border-radius:12px，padding:20px 24px
- `data-anim-stagger` + `slide-left` 动效

---

### 10. Comparison（2-Column 对比）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 页面标题 -->
  <h2 data-anim="fade-up"
      style="position:absolute;top:40px;left:50%;transform:translateX(-50%);
             font-size:32px;font-weight:bold;color:var(--text);margin:0;">
    方案对比
  </h2>

  <!-- 两列对比 -->
  <div style="position:absolute;top:120px;left:80px;width:1120px;display:flex;gap:40px;">

    <!-- 方案 A -->
    <div data-anim="slide-right" data-anim-duration="0.7s"
         style="flex:1;background:var(--card-bg);border-radius:16px;
                box-shadow:var(--card-shadow);overflow:hidden;">
      <!-- 方案头部 -->
      <div style="background:linear-gradient(135deg,var(--primary),var(--secondary));
                  padding:28px 32px;text-align:center;">
        <h3 style="font-size:22px;font-weight:bold;color:#FFFFFF;margin:0;">方案 A</h3>
        <p style="font-size:14px;color:rgba(255,255,255,0.8);margin:6px 0 0 0;">传统方案</p>
      </div>
      <!-- 方案内容 -->
      <div style="padding:32px;">
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:var(--primary);font-size:20px;margin-right:12px;">✓</span>
          <span style="font-size:16px;color:var(--text);">优势点描述 1</span>
        </div>
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:var(--primary);font-size:20px;margin-right:12px;">✓</span>
          <span style="font-size:16px;color:var(--text);">优势点描述 2</span>
        </div>
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:#DC2626;font-size:20px;margin-right:12px;">✗</span>
          <span style="font-size:16px;color:var(--muted);">劣势点描述 1</span>
        </div>
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:#DC2626;font-size:20px;margin-right:12px;">✗</span>
          <span style="font-size:16px;color:var(--muted);">劣势点描述 2</span>
        </div>
      </div>
    </div>

    <!-- 方案 B -->
    <div data-anim="slide-left" data-anim-duration="0.7s" data-anim-delay="0.2s"
         style="flex:1;background:var(--card-bg);border-radius:16px;
                box-shadow:var(--card-shadow);overflow:hidden;">
      <!-- 方案头部 -->
      <div style="background:linear-gradient(135deg,var(--accent),#F57C00);
                  padding:28px 32px;text-align:center;">
        <h3 style="font-size:22px;font-weight:bold;color:#FFFFFF;margin:0;">方案 B</h3>
        <p style="font-size:14px;color:rgba(255,255,255,0.8);margin:6px 0 0 0;">推荐方案</p>
      </div>
      <!-- 方案内容 -->
      <div style="padding:32px;">
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:var(--accent);font-size:20px;margin-right:12px;">✓</span>
          <span style="font-size:16px;color:var(--text);">优势点描述 1</span>
        </div>
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:var(--accent);font-size:20px;margin-right:12px;">✓</span>
          <span style="font-size:16px;color:var(--text);">优势点描述 2</span>
        </div>
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:var(--accent);font-size:20px;margin-right:12px;">✓</span>
          <span style="font-size:16px;color:var(--text);">优势点描述 3</span>
        </div>
        <div style="display:flex;align-items:center;margin-bottom:20px;">
          <span style="color:var(--accent);font-size:20px;margin-right:12px;">✓</span>
          <span style="font-size:16px;color:var(--text);">优势点描述 4</span>
        </div>
      </div>
    </div>
  </div>

  <!-- VS 分隔标识 -->
  <div data-anim="scale-in" data-anim-delay="0.5s"
       style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
              width:56px;height:56px;border-radius:50%;background:var(--text);
              display:flex;align-items:center;justify-content:center;
              box-shadow:0 4px 16px rgba(0,0,0,0.2);">
    <span style="font-size:18px;font-weight:bold;color:#FFFFFF;">VS</span>
  </div>
</div>
</div>
```

**设计要点**：
- 两列均分 1120px 宽度，40px 间隙
- 每列头部用渐变背景(28px padding)，下方 32px padding 内容区
- ✓/✗ 标记用彩色，✗ 用 #DC2626 红色
- 中间圆形 VS 标识，`scale-in` 动效增强对比感
- 两列分别用 `slide-right` / `slide-left` 动画从两侧滑入

---

## 三、breathing 页面（过渡 / 金句，≤20 字）

### 11. Quote / Centered（居中金句）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Noto Serif SC','Georgia','Times New Roman',serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 左侧装饰线 -->
  <div data-anim="wipe-right" data-anim-duration="0.6s"
       style="position:absolute;top:50%;left:160px;width:4px;height:0;
              transform:translateY(-50%);"></div>

  <!-- 引号装饰 -->
  <div data-anim="fade-in" data-anim-delay="0.2s"
       style="position:absolute;top:160px;left:50%;transform:translateX(-50%);
              font-size:120px;color:var(--primary);opacity:0.08;line-height:1;">
    &ldquo;
  </div>

  <!-- 核心金句 -->
  <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
              text-align:center;max-width:960px;">
    <p data-anim="fade-up" data-anim-duration="0.8s"
       style="font-size:36px;font-weight:bold;color:var(--text);margin:0;line-height:1.6;
              font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
      核心金句或关键结论，简短而有力。
    </p>
    <p data-anim="fade-up" data-anim-delay="0.4s"
       style="font-size:18px;color:var(--muted);margin:24px 0 0 0;
              font-family:'Microsoft YaHei',sans-serif;">
      &mdash; 来源或作者
    </p>
  </div>
</div>
</div>
```

**设计要点**：
- 衬线字体 `Noto Serif SC` 增强文艺感
- 超大引号 120px opacity:0.08 做背景装饰
- 金句 36px Bold，来源 18px muted
- 极简装饰，核心靠字重与间距传递力量感

---

### 12. Big Number + Label（大字 + 标签）

```html
<div style="width:1280px;height:720px;position:relative;overflow:hidden;
            background:var(--bg);font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif;">
  <style>
    :root {
      --bg: #FAFBFC; --primary: #1A73E8; --secondary: #4285F4;
      --accent: #FF6D00; --text: #1F2937; --muted: #6B7280;
      --card-bg: #FFFFFF; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
      --border-color: #E5E7EB;
    }
  </style>

  <!-- 背景装饰圆 -->
  <div data-anim="scale-in" data-anim-duration="1s"
       style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
              width:360px;height:360px;border-radius:50%;
              background:radial-gradient(circle,var(--primary) 0%,transparent 70%);
              opacity:0.08;"></div>

  <!-- 大字 + 描述 -->
  <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
              text-align:center;">
    <p data-anim="scale-in" data-anim-delay="0.2s"
       style="font-size:96px;font-weight:bold;color:var(--primary);margin:0;line-height:1;">
      86%
    </p>
    <p data-anim="fade-up" data-anim-delay="0.5s"
       style="font-size:24px;color:var(--muted);margin:16px 0 0 0;letter-spacing:0.05em;">
      关键指标标签描述
    </p>
  </div>
</div>
</div>
```

**设计要点**：
- 大字 80-96px Bold，颜色用 primary 或 accent
- 背景可选 radial-gradient 大圆增加层次感
- 标签 24px muted，字间距略宽松
- 数字用 `scale-in`，标签用 `fade-up` 延迟出现

---

## 四、卡片设计规范速查

| 属性 | 值 |
|------|-----|
| 圆角 (border-radius) | 12px（小型）/ 16px（标准卡片） |
| 阴影 (box-shadow) | `0 2px 12px rgba(0,0,0,0.08)` |
| 卡片内边距 | 24px ~ 32px |
| 图标区尺寸 | 48×48（小型）/ 80×80（大型） |
| 图标圆角 | 12px（小型）/ 20px（大型） |
| 卡片间距 | 24px（紧凑）/ 40px（宽松） |
| 边框 | 1px solid var(--border-color) 或省略 |

---

## 五、动效使用原则（HTML 路线）

1. **每页 ≤6 个独立 data-anim 元素**
2. **列表/卡片优先用 `data-anim-stagger`**，不逐个设 delay
3. **封面/章节页：1 个 hero 动效 → 次级动效**
4. **breathing 页面：≤2 个动效元素**
5. **dense 页面动效顺序：页面标题 → 卡片 stagger → 底部补充**
6. **锚定到 spec_lock.md 的 rhythm 标签**选择对应布局

---

## 六、字号层级速查

| 角色 | 字号 | 字重 | 用途 |
|------|------|------|------|
| Hero 标题 | 56-64px | Bold | 封面超大标题 |
| 主标题 | 48px | Bold | 封面/过渡页标题 |
| 章节标题 | 42px | Bold | 章节过渡页 |
| 页面标题 | 32px | Bold | 内容页标题 |
| 副标题 | 24px | Regular | 副标题 |
| 卡片标题 | 18-22px | Bold | 卡片/面板标题 |
| 正文 | 15-16px | Regular | 正文描述 |
| KPI 数值 | 36px | Bold | KPI 指标数字 |
| 大字 | 80-96px | Bold | breathing 大字 |
| 脚注 | 12-14px | Regular | 来源/日期 |
