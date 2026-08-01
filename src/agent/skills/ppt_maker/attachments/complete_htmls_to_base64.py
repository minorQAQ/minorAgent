#!/usr/bin/env python3
"""
complete_htmls_to_base64.py

将 HTML 文件中的外部图片引用转换为 base64 内嵌 Data URI。
适用于 ppt_maker 技能生成的 HTML 演示文稿。

用法:
    python complete_htmls_to_base64.py workspace/ppt_my_topic/
    python complete_htmls_to_base64.py workspace/ppt_my_topic/ --force

功能:
    - 查找目录中所有 .html 文件
    - 将 <img src="..."> 中的外部图片路径替换为 data URI
    - 将 style 属性中 url('...') 的外部图片路径替换为 data URI
    - 跳过以 _complete.html 结尾的文件
    - 输出文件命名为 {原文件名}_complete.html
"""

import os
import sys
import re
import base64
import argparse
from pathlib import Path

# 支持的图片格式及对应 MIME 类型
MIME_TYPES = {
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.webp': 'image/webp',
    '.svg':  'image/svg+xml',
    '.bmp':  'image/bmp',
    '.ico':  'image/x-icon',
}

# 匹配 <img> 标签的 src 属性（非 data URI）
IMG_SRC_PATTERN = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*["\'])(?!data:)([^"\']+?)(["\'])',
    re.IGNORECASE
)

# 匹配 url('...') 引用（非 data URI），在 style 属性内
URL_PATTERN = re.compile(
    r'(url\s*\(\s*["\']?)(?!data:)([^"\')\s]+?)(["\']?\s*\))',
    re.IGNORECASE
)


def is_data_uri(path: str) -> bool:
    """检查路径是否已经是 data URI"""
    return path.startswith('data:')


def is_external_url(path: str) -> bool:
    """检查路径是否为外部 URL"""
    return path.startswith('http://') or path.startswith('https://')


def get_mime_type(file_path: str) -> str:
    """根据文件扩展名获取 MIME 类型"""
    ext = os.path.splitext(file_path)[1].lower()
    return MIME_TYPES.get(ext, 'application/octet-stream')


def image_to_base64(image_path: str) -> str:
    """将图片文件转换为 base64 字符串"""
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        return base64.b64encode(image_data).decode('ascii')
    except FileNotFoundError:
        print(f"  ⚠  警告: 文件不存在 - {image_path}")
        return None
    except PermissionError:
        print(f"  ⚠  警告: 无权限读取 - {image_path}")
        return None
    except Exception as e:
        print(f"  ⚠  警告: 读取失败 - {image_path} ({e})")
        return None


def make_data_uri(image_path: str, base64_data: str) -> str:
    """构造 data URI"""
    mime = get_mime_type(image_path)
    return f'data:{mime};base64,{base64_data}'


def replace_img_src(match: re.Match, base_dir: str) -> str:
    """替换 img 标签中的 src 为 data URI"""
    prefix = match.group(1)
    src_path = match.group(2)
    suffix = match.group(3)

    # 跳过已处理的
    if is_data_uri(src_path):
        return match.group(0)

    # 跳过外部 URL
    if is_external_url(src_path):
        return match.group(0)

    # 解析相对路径
    full_image_path = os.path.normpath(os.path.join(base_dir, src_path))

    base64_data = image_to_base64(full_image_path)
    if base64_data is None:
        return match.group(0)  # 保留原样

    data_uri = make_data_uri(full_image_path, base64_data)
    return f'{prefix}{data_uri}{suffix}'


def replace_url_in_style(match: re.Match, base_dir: str) -> str:
    """替换 style 属性中 url() 引用为 data URI"""
    prefix = match.group(1)
    url_path = match.group(2)
    suffix = match.group(3)

    # 跳过已处理的
    if is_data_uri(url_path):
        return match.group(0)

    # 跳过外部 URL
    if is_external_url(url_path):
        return match.group(0)

    # 解析相对路径
    full_image_path = os.path.normpath(os.path.join(base_dir, url_path))

    base64_data = image_to_base64(full_image_path)
    if base64_data is None:
        return match.group(0)

    data_uri = make_data_uri(full_image_path, base64_data)
    return f'{prefix}{data_uri}{suffix}'


def process_html_file(html_path: str, force: bool = False) -> bool:
    """
    处理单个 HTML 文件，将外部图片转换为 base64。

    返回 True 表示成功处理，False 表示跳过或失败。
    """
    base_name = os.path.basename(html_path)
    dir_name = os.path.dirname(html_path)

    # 跳过已完成的文件
    if base_name.endswith('_complete.html'):
        print(f"  ⏭  跳过（已是 _complete 文件）: {base_name}")
        return False

    output_path = os.path.join(
        dir_name,
        f'{os.path.splitext(base_name)[0]}_complete.html'
    )

    # 检查是否已存在
    if os.path.exists(output_path) and not force:
        print(f"  ⏭  跳过（输出已存在，使用 --force 覆盖）: {os.path.basename(output_path)}")
        return False

    # 读取 HTML 内容
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    base_dir = dir_name

    # 替换 <img src="...">
    new_content, img_count = IMG_SRC_PATTERN.subn(
        lambda m: replace_img_src(m, base_dir), content
    )
    img_replaced = img_count

    # 替换 url('...')
    new_content, url_count = URL_PATTERN.subn(
        lambda m: replace_url_in_style(m, base_dir), new_content
    )
    url_replaced = url_count

    total_replaced = img_replaced + url_replaced

    # 写入输出文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"  ✓ 已处理: {base_name} -> {os.path.basename(output_path)}")
    print(f"    - <img> 替换: {img_replaced} 处")
    print(f"    - url() 替换: {url_replaced} 处")
    print(f"    - 总计: {total_replaced} 处")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='将 HTML 文件中的外部图片引用转换为 base64 Data URI'
    )
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='包含 HTML 文件的目录路径（默认: 当前目录）'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='强制覆盖已存在的 _complete.html 文件'
    )
    args = parser.parse_args()

    target_dir = os.path.abspath(args.directory)

    if not os.path.isdir(target_dir):
        print(f"✗ 错误: 目录不存在 - {target_dir}")
        sys.exit(1)

    print(f"📁 目标目录: {target_dir}")
    print(f"🔍 扫描 HTML 文件...\n")

    # 查找所有 .html 文件
    html_files = sorted(
        str(p) for p in Path(target_dir).glob('*.html')
        if not str(p).endswith('_complete.html')
    )

    if not html_files:
        print("⚠  未找到需要处理的 HTML 文件")
        return

    print(f"找到 {len(html_files)} 个 HTML 文件\n")

    # 处理每个文件
    success_count = 0
    skip_count = 0

    for html_file in html_files:
        result = process_html_file(html_file, force=args.force)
        if result:
            success_count += 1
        else:
            skip_count += 1

    # 汇总
    print(f"\n{'='*50}")
    print(f"📊 处理完成:")
    print(f"   - 成功: {success_count} 个文件")
    print(f"   - 跳过: {skip_count} 个文件")
    print(f"   - 输出目录: {target_dir}")

    # 列出所有生成的 _complete.html 文件
    complete_files = sorted(
        str(p) for p in Path(target_dir).glob('*_complete.html')
    )
    if complete_files:
        print(f"\n📦 生成的 _complete.html 文件:")
        for cf in complete_files:
            print(f"   - {os.path.basename(cf)}")


if __name__ == '__main__':
    main()
