"""PPT 读取与预览工具：自主实现 PPTX 解析，不依赖外部 ppt-master 项目。
支持:
  - pptx → SVG: 将 PPTX 每页转为自包含 SVG（扁平渲染，用于前端预览）

渲染范围（聚焦核心功能）:
  - 形状: rect, roundRect, ellipse, line, text, image, path, polygon, group
  - 填充: solidFill, noFill
  - 描边: 基础线色/线宽
  - 文本: 水平文本框 + 基础 run 属性

说明:
  原先的 svg → pptx 制作路线已移除（项目不走 SVG 路线制作 PPT），
  仅保留 PPT 读取/解析与预览渲染逻辑。
"""

from __future__ import annotations

import base64
import os
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ============================================================
# 1. 常量 & 命名空间
# ============================================================

EMU_PER_INCH = 914400
EMU_PER_PX = 9525
HUNDREDTHS_PT_PER_PX = 75
ANGLE_UNIT = 60000

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_SVG = "http://www.w3.org/2000/svg"

NS_MAP = {"a": NS_A, "p": NS_P, "r": NS_R, "rel": NS_REL, "svg": NS_SVG}


def _ns(tag: str) -> str:
    """为不带前缀的标签加上默认命名空间前缀。"""
    if tag.startswith("{"):
        return tag
    return f"{{{NS_MAP.get(tag.split(':')[0], NS_SVG)}}}{tag.split(':', 1)[-1]}"


def _etree_fromstring(xml_str: str) -> ET.Element:
    """注册命名空间后解析 XML 字符串。"""
    for prefix, uri in NS_MAP.items():
        ET.register_namespace(prefix, uri)
    return ET.fromstring(xml_str)


# ============================================================
# 2. 工具函数
# ============================================================

def emu_to_px(emu: float | str | None, default: float = 0.0) -> float:
    if emu is None:
        return default
    return float(emu) / EMU_PER_PX


def px_to_emu(px: float) -> int:
    return int(round(px * EMU_PER_PX))


def fmt_num(val: float, ndigits: int = 2) -> str:
    s = f"{val:.{ndigits}f}"
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


# ============================================================
# 3. 颜色解析（简化版：srgb + scheme）
# ============================================================

def _resolve_srgb(color_elem: ET.Element) -> str | None:
    """解析 a:srgbClr → '#RRGGBB'。"""
    val = color_elem.get("val", "")
    if len(val) == 6:
        return f"#{val}"
    return None


def _find_color_elem(parent: ET.Element) -> ET.Element | None:
    for child in parent:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if tag in ("srgbClr", "schemeClr", "sysClr", "prstClr"):
            return child
    return None


def _resolve_color(color_elem: ET.Element | None,
                   scheme_map: dict[str, str]) -> tuple[str | None, float]:
    if color_elem is None:
        return None, 1.0
    tag = color_elem.tag.split("}", 1)[-1] if "}" in color_elem.tag else color_elem.tag
    alpha_elem = color_elem.find(f"{{{NS_A}}}alpha")
    alpha = float(alpha_elem.get("val")) / 100000.0 if alpha_elem is not None else 1.0
    if tag == "srgbClr":
        return _resolve_srgb(color_elem), alpha
    elif tag == "schemeClr":
        name = color_elem.get("val", "")
        mapped = scheme_map.get(name, name)
        return scheme_map.get(mapped), alpha
    elif tag == "sysClr":
        return color_elem.get("lastClr"), alpha
    return None, alpha


def _parse_color_simple(elem: ET.Element, scheme_map: dict[str, str]) -> str | None:
    """从元素中解析第一个颜色值，简化为返回 hex 字符串或 None。"""
    color_elem = _find_color_elem(elem)
    hex_c, _ = _resolve_color(color_elem, scheme_map)
    return hex_c


# ============================================================
# 4. OOXML 加载器 (pptx → 内部结构)
# ============================================================

@dataclass
class _PartRef:
    path: str
    xml: ET.Element
    rels: dict[str, tuple[str, str]] = field(default_factory=dict)  # rid → (type, target)


@dataclass
class _SlideRef:
    index: int  # 1-based
    part: _PartRef
    layout: _PartRef | None
    master: _PartRef | None


class OoxmlPackage:
    """读取 PPTX ZIP，提取 slide/layout/master 链。"""

    def __init__(self, pptx_path: Path):
        self._zf = zipfile.ZipFile(pptx_path, "r")
        self._names = set(self._zf.namelist())
        self.slide_size_px = (1280.0, 720.0)
        self._slides: list[_SlideRef] = []
        self._layouts: dict[str, _PartRef] = {}
        self._masters: dict[str, _PartRef] = {}
        self._theme_for_master: dict[str, _PartRef] = {}
        self._load()

    def _read_xml(self, path: str) -> ET.Element | None:
        if path not in self._names:
            return None
        return ET.fromstring(self._zf.read(path))

    def _read_rels(self, part_path: str) -> dict[str, tuple[str, str]]:
        rels_dir = os.path.dirname(part_path)
        rels_path = os.path.join(rels_dir, "_rels",
                                 os.path.basename(part_path) + ".rels").replace("\\", "/")
        if rels_path not in self._names:
            return {}
        xml = self._read_xml(rels_path)
        if xml is None:
            return {}
        rels = {}
        for rel in xml:
            rid = rel.get("Id", "")
            typ = rel.get("Type", "")
            target = rel.get("Target", "")
            # 解析相对路径
            if not target.startswith("/") and not target.startswith("ppt/"):
                target = os.path.normpath(os.path.join(rels_dir, target)).replace("\\", "/")
            rels[rid] = (typ, target)
        return rels

    def _read_root_rels(self) -> dict[str, tuple[str, str]]:
        """读取根关系文件 _rels/.rels（不能使用 _read_rels，因为 .rels 自身无子 rels）。"""
        rels_path = "_rels/.rels"
        xml = self._read_xml(rels_path)
        if xml is None:
            return {}
        rels = {}
        for rel in xml:
            rid = rel.get("Id", "")
            typ = rel.get("Type", "")
            target = rel.get("Target", "")
            if target.startswith("/"):
                target = target.lstrip("/")
            rels[rid] = (typ, target)
        return rels

    def _load(self):
        # 加载 presentation.xml
        pres_rel = self._read_root_rels()
        pres_target = None
        for _rid, (typ, target) in pres_rel.items():
            if "officeDocument" in typ or "presentation" in typ:
                pres_target = target.lstrip("/")
                break
        if not pres_target:
            raise ValueError("找不到 presentation.xml")

        pres_xml = self._read_xml(pres_target)
        if pres_xml is None:
            raise ValueError(f"无法读取 {pres_target}")
        # 幻灯片尺寸
        sld_sz = pres_xml.find(f"{{{NS_P}}}sldSz")
        if sld_sz is not None:
            self.slide_size_px = (emu_to_px(sld_sz.get("cx", 0)), emu_to_px(sld_sz.get("cy", 0)))

        # 加载幻灯片
        sld_rels = self._read_rels(pres_target)
        slide_targets: list[tuple[int, str]] = []
        # 按顺序列出所有 slide
        for sld_id in pres_xml.findall(f"{{{NS_P}}}sldIdLst/{{{NS_P}}}sldId"):
            rid = sld_id.get(f"{{{NS_R}}}id", "")
            if rid in sld_rels:
                slide_targets.append((len(slide_targets) + 1, sld_rels[rid][1].lstrip("/")))

        for idx, sld_path in slide_targets:
            sld_xml = self._read_xml(sld_path)
            if sld_xml is None:
                continue
            sld_part = _PartRef(sld_path, sld_xml, self._read_rels(sld_path))
            layout = self._resolve_related(sld_part, "slideLayout")
            master = None
            if layout:
                master = self._resolve_related(layout, "slideMaster")
            self._slides.append(_SlideRef(idx, sld_part, layout, master))

    def _resolve_related(self, part: _PartRef, rel_type_keyword: str) -> _PartRef | None:
        for _rid, (typ, target) in part.rels.items():
            if rel_type_keyword in typ:
                path = target.lstrip("/")
                xml = self._read_xml(path)
                if xml is not None:
                    ref = _PartRef(path, xml, self._read_rels(path))
                    # 缓存
                    if "Layout" in rel_type_keyword:
                        self._layouts[path] = ref
                    elif "Master" in rel_type_keyword:
                        self._masters[path] = ref
                    return ref
        return None

    def resolve_theme(self, master: _PartRef | None) -> dict[str, str]:
        """从 master 解析主题色。返回 {scheme_name: '#RRGGBB'}。"""
        if master is None:
            return {}
        for _rid, (typ, target) in master.rels.items():
            if "theme" in typ:
                theme_xml = self._read_xml(target.lstrip("/"))
                if theme_xml is None:
                    return {}
                scheme = theme_xml.find(f"{{{NS_A}}}themeElements/{{{NS_A}}}clrScheme")
                if scheme is None:
                    return {}
                result = {}
                for child in scheme:
                    tag = child.tag.split("}", 1)[-1]
                    srgb = child.find(f"{{{NS_A}}}srgbClr")
                    if srgb is not None:
                        result[tag] = _resolve_srgb(srgb) or ""
                return result
        return {}

    def iter_slides(self) -> Iterator[_SlideRef]:
        yield from self._slides

    def read_media(self, part_path: str) -> bytes | None:
        path = part_path.lstrip("/").replace("ppt/media/", "ppt/media/") if not part_path.startswith("ppt/") else part_path
        if path in self._names:
            return self._zf.read(path)
        return None

    def close(self):
        self._zf.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ============================================================
# 5. Xfrm 坐标变换
# ============================================================

@dataclass
class Xfrm:
    x: float = 0.0; y: float = 0.0; w: float = 0.0; h: float = 0.0
    rot: float = 0.0; flip_h: bool = False; flip_v: bool = False
    ch_x: float = 0.0; ch_y: float = 0.0; ch_w: float = 0.0; ch_h: float = 0.0

    def to_svg_transform(self) -> str | None:
        parts = []
        if self.rot:
            cx = self.x + self.w / 2
            cy = self.y + self.h / 2
            parts.append(f"rotate({fmt_num(self.rot)} {fmt_num(cx)} {fmt_num(cy)})")
        if self.flip_h or self.flip_v:
            sx = -1 if self.flip_h else 1
            sy = -1 if self.flip_v else 1
            cx = self.x + self.w / 2
            cy = self.y + self.h / 2
            parts.append(f"translate({fmt_num(cx)} {fmt_num(cy)}) scale({sx} {sy}) translate({fmt_num(-cx)} {fmt_num(-cy)})")
        return " ".join(parts) if parts else None


def parse_xfrm(xfrm_elem: ET.Element, is_group: bool = False) -> Xfrm:
    xf = Xfrm()
    off = xfrm_elem.find(f"{{{NS_A}}}off")
    if off is not None:
        xf.x = emu_to_px(off.get("x", 0))
        xf.y = emu_to_px(off.get("y", 0))
    ext = xfrm_elem.find(f"{{{NS_A}}}ext")
    if ext is not None:
        xf.w = emu_to_px(ext.get("cx", 0))
        xf.h = emu_to_px(ext.get("cy", 0))
    if is_group:
        ch_off = xfrm_elem.find(f"{{{NS_A}}}chOff")
        if ch_off is not None:
            xf.ch_x = emu_to_px(ch_off.get("x", 0))
            xf.ch_y = emu_to_px(ch_off.get("y", 0))
        ch_ext = xfrm_elem.find(f"{{{NS_A}}}chExt")
        if ch_ext is not None:
            xf.ch_w = emu_to_px(ch_ext.get("cx", 0))
            xf.ch_h = emu_to_px(ch_ext.get("cy", 0))
    rot = xfrm_elem.get("rot")
    if rot:
        xf.rot = float(rot) / ANGLE_UNIT
    xf.flip_h = xfrm_elem.get("flipH", "0") == "1"
    xf.flip_v = xfrm_elem.get("flipV", "0") == "1"
    return xf


# ============================================================
# 6. 预设几何 → SVG 元素 (pptx→svg)
# ============================================================

def _convert_prst_geom(prst: str, xf: Xfrm) -> tuple[str, dict[str, str]]:
    """将预设几何转为 SVG 标签名 + 属性字典。"""
    tag = "rect"
    attrs = {"x": fmt_num(xf.x), "y": fmt_num(xf.y),
             "width": fmt_num(xf.w), "height": fmt_num(xf.h)}
    if prst == "rect":
        tag = "rect"
    elif prst == "roundRect":
        tag = "rect"
        # 默认圆角 = min(w,h) * 0.05
        rx = min(xf.w, xf.h) * 0.05
        attrs["rx"] = fmt_num(rx)
        attrs["ry"] = fmt_num(rx)
    elif prst == "ellipse":
        tag = "ellipse"
        attrs = {"cx": fmt_num(xf.x + xf.w / 2), "cy": fmt_num(xf.y + xf.h / 2),
                 "rx": fmt_num(xf.w / 2), "ry": fmt_num(xf.h / 2)}
    elif prst == "line":
        tag = "line"
        attrs = {"x1": fmt_num(xf.x), "y1": fmt_num(xf.y),
                 "x2": fmt_num(xf.x + xf.w), "y2": fmt_num(xf.y + xf.h),
                 "stroke": "#000", "stroke-width": "1"}
    return tag, attrs


# ============================================================
# 7. 填充 → SVG 属性 (pptx→svg)
# ============================================================

def _resolve_fill_svg(sp_pr: ET.Element, scheme_map: dict[str, str]) -> dict[str, str]:
    """从 spPr 中解析填充，返回 SVG 样式属性。"""
    # noFill
    if sp_pr.find(f"{{{NS_A}}}noFill") is not None:
        return {"fill": "none"}
    # solidFill
    solid = sp_pr.find(f"{{{NS_A}}}solidFill")
    if solid is not None:
        color = _parse_color_simple(solid, scheme_map)
        if color:
            return {"fill": color}
    return {"fill": "#CCCCCC"}  # 默认灰色


# ============================================================
# 8. 图片 → SVG (pptx→svg)
# ============================================================

def _convert_picture(pic_elem: ET.Element, xf: Xfrm, media_data: bytes,
                     media_name: str) -> tuple[str, dict[str, bytes]]:
    """将 <p:pic> 转为 SVG <image> 元素。"""
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
                ".svg": "image/svg+xml"}
    ext = os.path.splitext(media_name)[1].lower()
    mime = mime_map.get(ext, "image/png")
    data_url = f"data:{mime};base64,{base64.b64encode(media_data).decode('ascii')}"
    svg = (f'<image x="{fmt_num(xf.x)}" y="{fmt_num(xf.y)}" '
           f'width="{fmt_num(xf.w)}" height="{fmt_num(xf.h)}" '
           f'href="{data_url}" preserveAspectRatio="none"/>')
    return svg, {}


# ============================================================
# 9. 文本框 → SVG (pptx→svg)
# ============================================================

def _convert_txbody(tx_body: ET.Element, xf: Xfrm,
                    scheme_map: dict[str, str]) -> str:
    """将 <p:txBody> 转为 SVG <text> 元素。"""
    body_pr = tx_body.find(f"{{{NS_A}}}bodyPr")
    l_ins = emu_to_px(body_pr.get("lIns", 0)) if body_pr is not None else 0
    t_ins = emu_to_px(body_pr.get("tIns", 0)) if body_pr is not None else 0
    r_ins = emu_to_px(body_pr.get("rIns", 0)) if body_pr is not None else 0
    b_ins = emu_to_px(body_pr.get("bIns", 0)) if body_pr is not None else 0

    inner_x = xf.x + l_ins
    inner_y = xf.y + t_ins
    inner_w = xf.w - l_ins - r_ins
    inner_h = xf.h - t_ins - b_ins

    anchor = body_pr.get("anchor", "t") if body_pr is not None else "t"
    wrap = body_pr.get("wrap", "square") if body_pr is not None else "square"

    paragraphs = tx_body.findall(f"{{{NS_A}}}p")
    tspans: list[str] = []

    for para_idx, para in enumerate(paragraphs):
        p_pr = para.find(f"{{{NS_A}}}pPr")
        align = p_pr.get("algn", "l") if p_pr is not None else "l"
        text_anchor_map = {"l": "start", "ctr": "middle", "r": "end"}
        text_anchor = text_anchor_map.get(align, "start")

        runs = para.findall(f"{{{NS_A}}}r")
        para_text_parts: list[str] = []
        font_size = 14
        font_family = "sans-serif"
        font_weight = "normal"
        font_style = "normal"
        fill = "#000000"

        for run in runs:
            r_pr = run.find(f"{{{NS_A}}}rPr")
            if r_pr is not None:
                sz = r_pr.get("sz")
                if sz:
                    font_size = float(sz) / 100.0
                b = r_pr.get("b")
                if b and b != "0":
                    font_weight = "bold"
                i = r_pr.get("i")
                if i and i != "0":
                    font_style = "italic"
                latin = r_pr.find(f"{{{NS_A}}}latin")
                if latin is not None and latin.get("typeface"):
                    font_family = latin.get("typeface")
                ea = r_pr.find(f"{{{NS_A}}}ea")
                if ea is not None and ea.get("typeface"):
                    font_family = ea.get("typeface")
                color_elem = _find_color_elem(r_pr)
                if color_elem is not None:
                    c, _ = _resolve_color(color_elem, scheme_map)
                    if c:
                        fill = c

            t_elem = run.find(f"{{{NS_A}}}t")
            if t_elem is not None and t_elem.text:
                para_text_parts.append(t_elem.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

        para_text = "".join(para_text_parts)
        if not para_text:
            continue

        style = f"font-size:{fmt_num(font_size)}px;font-family:{font_family};font-weight:{font_weight};font-style:{font_style};fill:{fill};"
        if wrap == "none":
            style += "white-space:pre;"

        # 计算 y 位置
        line_height = font_size * 1.25
        y_pos = inner_y + font_size + para_idx * line_height
        x_pos = inner_x if align == "l" else (inner_x + inner_w / 2 if align == "ctr" else inner_x + inner_w)

        # 截断到形状高度
        max_para = max(0, int(inner_h / line_height)) if inner_h > 0 else 100
        if para_idx >= max_para:
            break

        tspans.append(
            f'<text x="{fmt_num(x_pos)}" y="{fmt_num(y_pos)}" '
            f'text-anchor="{text_anchor}" style="{style}">{para_text}</text>'
        )

    return "\n".join(tspans) if tspans else ""


# ============================================================
# 10. 形状遍历 (pptx→svg)
# ============================================================

@dataclass
class ShapeNode:
    kind: str   # "shape" | "picture" | "group" | "graphic"
    xml: ET.Element
    xfrm: Xfrm
    name: str = ""
    hidden: bool = False
    children: list["ShapeNode"] = field(default_factory=list)


def walk_sp_tree(sp_tree: ET.Element) -> list[ShapeNode]:
    nodes: list[ShapeNode] = []
    for child in sp_tree:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if tag in ("sp", "cxnSp"):
            sp_pr = child.find(f"{{{NS_A}}}spPr")
            xfrm_elem = sp_pr.find(f"{{{NS_A}}}xfrm") if sp_pr is not None else None
            xf = parse_xfrm(xfrm_elem) if xfrm_elem is not None else Xfrm()
            nv = child.find(f"{{{NS_P}}}nvSpPr")
            name = ""
            if nv is not None:
                c_nv = nv.find(f"{{{NS_P}}}cNvPr")
                if c_nv is not None:
                    name = c_nv.get("name", "")
                hidden = c_nv is not None and nv.find(f"{{{NS_P}}}cNvPr") is not None and \
                    nv.find(f"{{{NS_P}}}cNvPr").get("hidden", "0") == "1"
            else:
                hidden = False
            nodes.append(ShapeNode("shape", child, xf, name, hidden))
        elif tag == "pic":
            sp_pr = child.find(f"{{{NS_A}}}spPr")
            xfrm_elem = sp_pr.find(f"{{{NS_A}}}xfrm") if sp_pr is not None else None
            xf = parse_xfrm(xfrm_elem) if xfrm_elem is not None else Xfrm()
            nv = child.find(f"{{{NS_P}}}nvPicPr")
            name = ""
            if nv is not None:
                c_nv = nv.find(f"{{{NS_P}}}cNvPr")
                if c_nv is not None:
                    name = c_nv.get("name", "")
            nodes.append(ShapeNode("picture", child, xf, name, False))
        elif tag == "grpSp":
            sp_pr = child.find(f"{{{NS_A}}}spPr")
            xfrm_elem = sp_pr.find(f"{{{NS_A}}}xfrm") if sp_pr is not None else None
            xf = parse_xfrm(xfrm_elem, is_group=True) if xfrm_elem is not None else Xfrm()
            children = walk_sp_tree(child)
            nodes.append(ShapeNode("group", child, xf, "", False, children))
        elif tag == "graphicFrame":
            sp_pr = child.find(f"{{{NS_A}}}spPr")
            xfrm_elem = sp_pr.find(f"{{{NS_A}}}xfrm") if sp_pr is not None else None
            xf = parse_xfrm(xfrm_elem) if xfrm_elem is not None else Xfrm()
            nodes.append(ShapeNode("graphic", child, xf, "graphicFrame", False))
    return nodes


# ============================================================
# 11. 幻灯片组装 → SVG (pptx→svg 主入口)
# ============================================================

@dataclass
class SlideSvgResult:
    index: int
    svg: str
    media_files: dict[str, bytes] = field(default_factory=dict)


@dataclass
class PptxToSvgResult:
    slides: list[SlideSvgResult] = field(default_factory=list)
    canvas_px: tuple[float, float] = (1280.0, 720.0)
    theme_colors: dict[str, str] = field(default_factory=dict)


def convert_pptx_to_svg(pptx_path: Path) -> PptxToSvgResult:
    """将 .pptx 文件每页转为自包含 SVG。

    返回 PptxToSvgResult，其中 slides 列表每项含 index + svg 字符串 + media_files。
    """
    result = PptxToSvgResult()

    with OoxmlPackage(pptx_path) as pkg:
        result.canvas_px = pkg.slide_size_px
        cw, ch = pkg.slide_size_px

        for slide in pkg.iter_slides():
            scheme = pkg.resolve_theme(slide.master)
            result.theme_colors = scheme

            svg_parts: list[str] = []
            media: dict[str, bytes] = {}

            # 背景
            bg = slide.part.xml.find(f"{{{NS_P}}}cSld/{{{NS_P}}}bg")
            bg_color = "#FFFFFF"
            if bg is not None:
                bg_pr = bg.find(f"{{{NS_P}}}bgPr")
                if bg_pr is not None:
                    solid = bg_pr.find(f"{{{NS_A}}}solidFill")
                    if solid is not None:
                        c = _parse_color_simple(solid, scheme)
                        if c:
                            bg_color = c
            svg_parts.append(f'<rect width="{fmt_num(cw)}" height="{fmt_num(ch)}" fill="{bg_color}"/>')

            # 遍历形状树
            sp_tree = slide.part.xml.find(f"{{{NS_P}}}cSld/{{{NS_P}}}spTree")
            if sp_tree is not None:
                nodes = walk_sp_tree(sp_tree)
                for node in nodes:
                    node_svg = _convert_node(node, slide, pkg, scheme)
                    if node_svg:
                        svg_parts.append(node_svg)

            # 组装 SVG
            svg_header = (
                f'<svg xmlns="{NS_SVG}" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="0 0 {fmt_num(cw)} {fmt_num(ch)}" '
                f'width="{fmt_num(cw)}" height="{fmt_num(ch)}">'
            )
            svg_footer = "</svg>"
            full_svg = svg_header + "\n" + "\n".join(svg_parts) + "\n" + svg_footer

            result.slides.append(SlideSvgResult(slide.index, full_svg, media))

    return result


def _convert_node(node: ShapeNode, slide: _SlideRef, pkg: OoxmlPackage,
                  scheme: dict[str, str]) -> str | None:
    if node.hidden:
        return None

    if node.kind == "shape":
        return _convert_shape_to_svg(node, scheme)
    elif node.kind == "picture":
        return _convert_pic_to_svg(node, slide, pkg)
    elif node.kind == "group":
        return _convert_group_to_svg(node, slide, pkg, scheme)
    elif node.kind == "graphic":
        return f'<rect x="{fmt_num(node.xfrm.x)}" y="{fmt_num(node.xfrm.y)}" width="{fmt_num(node.xfrm.w)}" height="{fmt_num(node.xfrm.h)}" fill="none" stroke="#CCC" stroke-dasharray="4"/>'
    return None


def _convert_shape_to_svg(node: ShapeNode, scheme: dict[str, str]) -> str | None:
    sp_pr = node.xml.find(f"{{{NS_A}}}spPr")
    if sp_pr is None:
        return None

    # 几何
    prst = sp_pr.find(f"{{{NS_A}}}prstGeom")
    cust = sp_pr.find(f"{{{NS_A}}}custGeom")
    if prst is not None:
        prst_name = prst.get("prst", "rect")
        geom_tag, geom_attrs = _convert_prst_geom(prst_name, node.xfrm)
    elif cust is not None:
        # 自定义几何降级为矩形
        geom_tag, geom_attrs = _convert_prst_geom("rect", node.xfrm)
    else:
        geom_tag, geom_attrs = _convert_prst_geom("rect", node.xfrm)

    # 填充 + 文本
    fill_attrs = _resolve_fill_svg(sp_pr, scheme)
    all_attrs = {**geom_attrs, **fill_attrs}

    # 变换（旋转/翻转）
    xform = node.xfrm.to_svg_transform()
    group_open = f'<g transform="{xform}">' if xform else "<g>"

    # 描边
    ln = sp_pr.find(f"{{{NS_A}}}ln")
    if ln is not None:
        w = ln.get("w")
        if w:
            all_attrs["stroke-width"] = fmt_num(emu_to_px(w, 1))
        color_elem = _find_color_elem(ln)
        if color_elem is not None:
            c, _ = _resolve_color(color_elem, scheme)
            if c:
                all_attrs["stroke"] = c
        else:
            all_attrs["stroke"] = "#000000"

    parts: list[str] = [group_open]

    # 渲染几何
    attr_str = " ".join(f'{k}="{v}"' for k, v in all_attrs.items())
    parts.append(f'<{geom_tag} {attr_str}/>')

    # 文本 (txBody 可能在 p: 或 a: 命名空间下)
    tx_body = node.xml.find(f"{{{NS_P}}}txBody") or node.xml.find(f"{{{NS_A}}}txBody")
    if tx_body is not None:
        text_svg = _convert_txbody(tx_body, node.xfrm, scheme)
        if text_svg:
            parts.append(text_svg)

    parts.append("</g>")
    return "\n".join(parts)


def _convert_pic_to_svg(node: ShapeNode, slide: _SlideRef, pkg: OoxmlPackage) -> str | None:
    # 找到 blipFill 的内嵌图片
    blip_fill = node.xml.find(f"{{{NS_A}}}spPr/{{{NS_A}}}blipFill")
    if blip_fill is None:
        blip_fill = node.xml.find(f"{{{NS_P}}}blipFill")
    if blip_fill is None:
        return f'<rect x="{fmt_num(node.xfrm.x)}" y="{fmt_num(node.xfrm.y)}" width="{fmt_num(node.xfrm.w)}" height="{fmt_num(node.xfrm.h)}" fill="#EEE"/>'

    blip = blip_fill.find(f"{{{NS_A}}}blip")
    if blip is None:
        return None

    embed = blip.get(f"{{{NS_R}}}embed", "")
    if not embed or embed not in slide.part.rels:
        return None

    _typ, target = slide.part.rels[embed]
    media_data = pkg.read_media(target)
    if media_data is None:
        return None

    media_name = os.path.basename(target)
    svg, _ = _convert_picture(node.xml, node.xfrm, media_data, media_name)

    xform = node.xfrm.to_svg_transform()
    return f'<g transform="{xform}">{svg}</g>' if xform else f'<g>{svg}</g>'


def _convert_group_to_svg(node: ShapeNode, slide: _SlideRef, pkg: OoxmlPackage,
                          scheme: dict[str, str]) -> str | None:
    xform = node.xfrm.to_svg_transform()
    parts = [f'<g transform="{xform}">' if xform else "<g>"]
    for child in node.children:
        child_svg = _convert_node(child, slide, pkg, scheme)
        if child_svg:
            parts.append(child_svg)
    parts.append("</g>")
    return "\n".join(parts)
