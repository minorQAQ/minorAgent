#!/usr/bin/env python3
"""
merge_to_deck.py

将 ppt_maker 生成的多个独立 HTML 文件（1.html, 2.html, ...）合并为单个 deck 格式 HTML。
合并后支持键盘（← →）翻页 + 鼠标点击前进 + 触摸滑动，同时兼容 fange-ai-toolbox 编辑器。

用法:
    python merge_to_deck.py workspace/ppt_my_topic/
    python merge_to_deck.py workspace/ppt_my_topic/ --output my_deck.html
    python merge_to_deck.py workspace/ppt_my_topic/ --complete   # 使用 _complete.html 文件

输出:
    单个 deck.html，每个原页面作为 <section class="slide"> 嵌入
"""

import os
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path


def find_html_files(directory: str, use_complete: bool = False) -> list:
    """查找目录下所有纯数字命名的 HTML 文件，按页码排序。"""
    html_dir = Path(directory)
    if not html_dir.is_dir():
        # 尝试 workspace 下查找
        workspace = Path(os.getcwd()) / "workspace" / directory
        if workspace.is_dir():
            html_dir = workspace
        else:
            raise FileNotFoundError(f"目录不存在: {directory}")

    suffix = "_complete.html" if use_complete else ".html"
    files = []
    for f in sorted(html_dir.iterdir(), key=lambda x: x.name):
        name = f.name
        if use_complete:
            if name.endswith(suffix):
                try:
                    num = int(name.replace(suffix, ""))
                    files.append((num, str(f)))
                except ValueError:
                    pass
        else:
            # 匹配纯数字 .html（如 1.html, 2.html），排除 _complete 等
            m = re.match(r'^(\d+)\.html$', name)
            if m:
                files.append((int(m.group(1)), str(f)))
    files.sort(key=lambda x: x[0])
    return files


def extract_root_content(html: str) -> str:
    """
    提取页面核心内容。
    优先提取 .ppt-root 或 body > div（1280x720 容器）的内部内容，
    去掉外层的 body 灰底包装和独立 script。
    """
    # 1) 尝试匹配 <div class="ppt-root"> ... </div> 或 <div style="...1280...720..." ...>
    ppt_root_re = re.compile(
        r'<div[^>]*\b(?:class\s*=\s*["\']ppt-root["\']|style\s*=\s*["\'][^"\']*width\s*:\s*1280px[^"\']*height\s*:\s*720px[^"\']*)'
        r'[^>]*>(.*?)</div>\s*(?:<script[\s\S]*?</script>\s*)?\s*</body>',
        re.DOTALL | re.IGNORECASE
    )
    m = ppt_root_re.search(html)
    if m:
        inner = m.group(1)
        # 去掉页面内嵌的 <script>（动效引擎+导航），deck 统一管理
        inner = re.sub(r'<script[\s\S]*?</script>', '', inner, flags=re.DOTALL)
        return inner.strip()

    # 2) 回退：提取 <body> 内第一个宽高固定的 div 的内容
    body_re = re.compile(r'<body[^>]*>(.*?)</body>', re.DOTALL | re.IGNORECASE)
    m = body_re.search(html)
    if not m:
        return ""

    body = m.group(1)
    # 找第一个 1280x720 的 div（可能嵌套在灰色背景 div 内）
    container_re = re.compile(
        r'<div[^>]*style\s*=\s*["\'][^"\']*width\s*:\s*1280px[^"\']*height\s*:\s*720px[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
        re.DOTALL | re.IGNORECASE
    )
    m2 = container_re.search(body)
    if m2:
        inner = m2.group(1)
        inner = re.sub(r'<script[\s\S]*?</script>', '', inner, flags=re.DOTALL)
        return inner.strip()

    # 3) 最后回退：body 内去掉 script 后的全部内容
    body_clean = re.sub(r'<script[\s\S]*?</script>', '', body, flags=re.DOTALL)
    return body_clean.strip()


def extract_css_variables(html: str) -> str:
    """提取 :root 中的 CSS 变量定义。"""
    m = re.search(r':root\s*\{([^}]*)\}', html, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def scope_css_rules(css_text: str, slide_id: str) -> str:
    """给 CSS 规则加上 slide 作用域前缀，避免不同页面间的样式冲突。"""
    def scope_rule(match):
        rule = match.group(0)
        brace_pos = rule.index('{')
        selector_text = rule[:brace_pos]
        body_text = rule[brace_pos:]

        parts = [s.strip() for s in selector_text.split(',')]
        scoped_parts = []
        for part in parts:
            if not part:
                continue
            scoped = f'#{slide_id} {part}'
            # body.loaded 针对的是 deck 的 <body>，需放在 #slide-N 外面
            scoped = re.sub(rf'^#{slide_id}\s+body\.loaded\b', f'body.loaded #{slide_id}', scoped)
            scoped_parts.append(scoped)

        return ', '.join(scoped_parts) + ' ' + body_text

    result = re.sub(r'([^{}]+\{[^{}]*\})', lambda m: scope_rule(m) + '\n', css_text)
    return result.strip()


def build_deck(html_dir: str, use_complete: bool = False, title: str = None) -> str:
    """构建合并后的 deck HTML。"""
    files = find_html_files(html_dir, use_complete)
    if not files:
        raise ValueError(f"在 {html_dir} 中未找到 HTML 文件")

    total = len(files)
    slides_html = []
    css_variables = ""
    if title is None:
        title = datetime.now().strftime("演示文稿 %Y-%m-%d %H:%M:%S")

    for idx, (num, filepath) in enumerate(files, 1):
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        # 使用第一个页面的 CSS 变量作为全局变量
        if not css_variables:
            css_variables = extract_css_variables(html)

        content = extract_root_content(html)
        if not content:
            print(f"  [警告] {filepath}: 未能提取内容，跳过")
            continue

        # 提取页面内的 <style> 块（保留非 :root 的样式）
        style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
        page_styles = ""
        for sb in style_blocks:
            # 去掉 :root 块（已全局统一），去掉 body {} 规则（deck 自行管理）
            cleaned = re.sub(r':root\s*\{[^}]*\}', '', sb, re.DOTALL)
            cleaned = re.sub(r'\bbody\s*\{[^}]*\}', '', cleaned, flags=re.DOTALL)
            cleaned = cleaned.strip()
            if cleaned:
                page_styles += cleaned + "\n"

        # 给 CSS 规则加上 slide 作用域，避免不同页面同名 class 冲突
        slide_id = f"slide-{idx}"
        if page_styles:
            page_styles = scope_css_rules(page_styles, slide_id)

        slide = f'<section class="slide" id="slide-{idx}" data-slide="{idx}">\n'
        if page_styles:
            slide += f"  <style>\n{page_styles}  </style>\n"
        slide += f"  {content}\n"
        slide += "</section>"

        slides_html.append(slide)

    if not slides_html:
        raise ValueError("未能提取任何页面内容")

    # 构建完整 deck
    root_block = f":root {{\n  {css_variables}\n}}" if css_variables.strip() else ""

    deck = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
{root_block}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
  background: #1a1a2e;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  overflow: hidden;
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif;
}}

#deck {{
  position: relative;
  width: 1280px;
  height: 720px;
}}

.slide {{
  position: absolute;
  top: 0;
  left: 0;
  width: 1280px;
  height: 720px;
  overflow: hidden;
  background: var(--bg, #FAFBFC);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.35s ease;
}}

.slide.active {{
  opacity: 1;
  pointer-events: auto;
  z-index: 1;
}}

/* 页码指示器 */
#page-indicator {{
  position: fixed;
  bottom: 20px;
  right: 30px;
  color: rgba(255,255,255,0.5);
  font-size: 14px;
  font-family: 'Consolas', 'Fira Code', monospace;
  z-index: 100;
  transition: opacity 0.3s;
  pointer-events: none;
}}

/* 翻页提示箭头 */
#nav-hint {{
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(255,255,255,0.2);
  font-size: 48px;
  z-index: 100;
  pointer-events: none;
  transition: opacity 0.3s;
}}
#nav-hint.left  {{ left: 20px; }}
#nav-hint.right {{ right: 20px; }}
</style>
</head>
<body class="loaded">

<div id="deck">
{chr(10).join(slides_html)}
</div>

<div id="page-indicator">1 / {total}</div>
<div id="nav-hint" class="left">◀</div>
<div id="nav-hint" class="right">▶</div>

<script>
(function() {{
  var slides = document.querySelectorAll('.slide');
  var total = slides.length;
  if (total === 0) return;

  var current = 0;
  var indicator = document.getElementById('page-indicator');
  var hintL = document.getElementById('nav-hint').parentElement
    ? document.querySelector('#nav-hint.left')
    : null;
  var hintR = document.querySelector('#nav-hint.right');

  // ===== 动效引擎（按 slide 隔离） =====
  function triggerAnimations(slide) {{
    // 找到 slide 内所有 data-anim 元素
    var els = slide.querySelectorAll('[data-anim]');
    var staggerContainers = slide.querySelectorAll('[data-anim-stagger]');
    var seqContainers = slide.querySelectorAll('[data-anim-sequence]');
    var clickGroups = {{}};

    // 初始化：设置初始状态
    els.forEach(function(el) {{
      var anim = el.getAttribute('data-anim') || 'fade-up';
      var dur = el.getAttribute('data-anim-duration') || '0.6s';
      el.style.transition = 'opacity ' + dur + ' ease, transform ' + dur + ' ease, clip-path ' + dur + ' ease';
      el.style.opacity = '0';
      if (anim.includes('up')) el.style.transform = 'translateY(30px)';
      else if (anim.includes('left')) el.style.transform = 'translateX(-60px)';
      else if (anim.includes('right')) el.style.transform = 'translateX(60px)';
      else if (anim === 'scale-in' || anim === 'zoom-in') el.style.transform = 'scale(0.8)';
      else if (anim === 'wipe-right') el.style.clipPath = 'inset(0 100% 0 0)';
      else if (anim === 'pulse-soft') el.style.transform = 'scale(0.9)';
      else el.style.transform = 'translateY(0)';
    }});

    function showEl(el) {{
      el.style.opacity = '1';
      el.style.transform = 'translate(0,0) scale(1)';
      el.style.clipPath = 'inset(0 0 0 0)';
    }}

    // 延迟出现（非 stagger/sequence/click-group 的元素）
    els.forEach(function(el) {{
      if (el.closest('[data-anim-stagger]') || el.closest('[data-anim-sequence]') || el.getAttribute('data-anim-click-group')) return;
      var delay = parseFloat(el.getAttribute('data-anim-delay') || '0') * 1000;
      setTimeout(function() {{ showEl(el); }}, delay + 30);
    }});

    // stagger 容器
    staggerContainers.forEach(function(container) {{
      var children = container.querySelectorAll('[data-anim]');
      children.forEach(function(ch, i) {{
        setTimeout(function() {{ showEl(ch); }}, i * 50 + 80);
      }});
    }});

    // sequence 容器
    seqContainers.forEach(function(container) {{
      var children = container.querySelectorAll('[data-anim]');
      var totalDelay = 0;
      children.forEach(function(ch) {{
        var d = parseFloat(ch.getAttribute('data-anim-duration') || '0.6') * 1000;
        var delay = parseFloat(ch.getAttribute('data-anim-delay') || '0') * 1000;
        totalDelay += delay;
        setTimeout(function() {{ showEl(ch); }}, totalDelay + 80);
        totalDelay += d;
      }});
    }});

    // 点击分组
    els.forEach(function(el) {{
      var grp = el.getAttribute('data-anim-click-group');
      if (grp) {{
        if (!clickGroups[grp]) clickGroups[grp] = [];
        clickGroups[grp].push(el);
      }}
    }});

    // 返回 clickGroups 引用，供点击事件使用
    slide._clickGroups = clickGroups;
    slide._clickGroupIdx = 0;
  }}

  // ===== 翻页逻辑 =====
  function goToSlide(idx) {{
    if (idx < 0 || idx >= total || idx === current) return;

    // 隐藏当前
    slides[current].classList.remove('active');
    slides[current]._clickGroupIdx = 0;

    // 重置当前 slide 的动效状态（以便再次进入时重新播放）
    var prevEls = slides[current].querySelectorAll('[data-anim]');
    prevEls.forEach(function(el) {{
      el.style.opacity = '';
      el.style.transform = '';
      el.style.clipPath = '';
      el.style.transition = '';
    }});

    // 显示目标
    current = idx;
    slides[current].classList.add('active');
    triggerAnimations(slides[current]);

    // 更新 UI
    indicator.textContent = (current + 1) + ' / ' + total;

    // 首尾隐藏对应方向箭头
    if (hintL) hintL.style.opacity = current === 0 ? '0' : '0.2';
    if (hintR) hintR.style.opacity = current === total - 1 ? '0' : '0.2';
  }}

  function nextSlide() {{ goToSlide(current + 1); }}
  function prevSlide() {{ goToSlide(current - 1); }}

  // ===== 事件监听 =====

  // 键盘
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowRight' || e.key === 'Right' || e.key === 'ArrowDown' || e.key === 'Down' || e.key === ' ') {{
      e.preventDefault();
      nextSlide();
    }} else if (e.key === 'ArrowLeft' || e.key === 'Left' || e.key === 'ArrowUp' || e.key === 'Up') {{
      e.preventDefault();
      prevSlide();
    }} else if (e.key === 'Home') {{
      e.preventDefault();
      goToSlide(0);
    }} else if (e.key === 'End') {{
      e.preventDefault();
      goToSlide(total - 1);
    }}
  }});

  // 鼠标点击（点击 slide 区域 → 前进；非 slide 区域已有键盘，不额外处理）
  document.addEventListener('click', function(e) {{
    // 先处理当前 slide 的 click-group 动效
    var activeSlide = slides[current];
    if (activeSlide._clickGroups) {{
      activeSlide._clickGroupIdx++;
      var group = activeSlide._clickGroups[activeSlide._clickGroupIdx];
      if (group) {{
        group.forEach(function(el) {{
          el.style.opacity = '1';
          el.style.transform = 'translate(0,0) scale(1)';
          el.style.clipPath = 'inset(0 0 0 0)';
        }});
        return; // 还有 click-group 待展示，不翻页
      }}
    }}
    // 所有 click-group 播完 → 翻到下一页
    nextSlide();
  }});

  // 触摸滑动（移动端）
  var touchStartX = 0, touchStartY = 0;
  document.addEventListener('touchstart', function(e) {{
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  }});
  document.addEventListener('touchend', function(e) {{
    var dx = e.changedTouches[0].clientX - touchStartX;
    var dy = e.changedTouches[0].clientY - touchStartY;
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 40) {{
      if (dx < 0) nextSlide();
      else prevSlide();
    }}
  }});

  // ===== 启动：显示第一页 =====
  slides[0].classList.add('active');
  triggerAnimations(slides[0]);
  indicator.textContent = '1 / ' + total;
  if (hintL) hintL.style.opacity = '0';
  if (hintR) hintR.style.opacity = total > 1 ? '0.2' : '0';

}})();
</script>

</body>
</html>'''

    return deck


def main():
    parser = argparse.ArgumentParser(
        description="将 ppt_maker 生成的多个 HTML 合并为单文件 deck",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python merge_to_deck.py workspace/ppt_my_topic/
  python merge_to_deck.py workspace/ppt_my_topic/ --output my_deck.html
  python merge_to_deck.py workspace/ppt_my_topic/ --complete
        """
    )
    parser.add_argument("directory", help="HTML 文件所在目录")
    parser.add_argument("--output", "-o", default=None,
                        help="输出文件名（默认: deck.html，放在输入目录下）")
    parser.add_argument("--title", "-t", default=None,
                        help="deck 标题（默认: 当前时间戳）")
    parser.add_argument("--complete", action="store_true",
                        help="使用 _complete.html 文件（而非原始 .html）")
    args = parser.parse_args()

    html_dir = Path(args.directory)
    if not html_dir.is_dir():
        workspace = Path(os.getcwd()) / "workspace" / args.directory
        if workspace.is_dir():
            html_dir = workspace
        else:
            print(f"错误: 目录不存在: {args.directory}")
            sys.exit(1)

    output_path = args.output or str(html_dir / "deck.html")
    if not os.path.isabs(output_path):
        output_path = str(html_dir / output_path)

    try:
        print(f"合并目录: {html_dir}")
        deck = build_deck(str(html_dir), args.complete, args.title)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(deck)
        print(f"已生成: {output_path}")
        print(f"共 {deck.count('<section class=\"slide\"')} 页")
        print()
        print("操作方式:")
        print("  键盘 ← →   翻页")
        print("  键盘 ↑ ↓   翻页")
        print("  键盘 Space  下一页")
        print("  键盘 Home   首页")
        print("  键盘 End    末页")
        print("  鼠标点击    下一页")
        print("  触摸滑动    翻页（移动端）")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
