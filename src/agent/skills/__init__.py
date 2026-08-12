"""Skill 管理器：负责 skill 的增删改查、附件管理及 zip 导入。

每个 skill 是一个文件夹，位于 Skills 目录下，结构如下::

    skills/
      {skill_name}/
        skill.json    - 基本信息与描述（name/description/tags/enable）
        skill.md      - 主体内容（指南）
        ...           - 可选附件（直接放在 skill 文件夹下，不强制 attachments/ 子目录）

系统定位:
    为 skill_router 工具和前端 API 提供统一的数据读写接口。

可扩展性:
    可增加标签过滤、导出等功能。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent

# 视为元数据而非附件的文件（附件列举时排除）
_SKILL_META_FILES = {"skill.json", "skill.md", "SKILL.md"}


def _ensure_skills_dir() -> None:
    """确保 skills 目录存在。"""
    os.makedirs(SKILLS_DIR, exist_ok=True)


# ---------- Skill 信息数据类 ----------
class SkillInfo:
    """单个 Skill 的基本信息（不含 version/author）。"""
    name: str
    description: str
    tags: list[str]
    enable: bool

    def __init__(self, name: str = "", description: str = "", tags: list[str] | None = None,
                 enable: bool = True):
        self.name = name
        self.description = description
        self.tags = tags or []
        self.enable = enable

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "enable": self.enable,
        }

    @classmethod
    def from_dict(cls, d: dict, name: str = "") -> "SkillInfo":
        return cls(
            name=d.get("name", name),
            description=d.get("description", ""),
            tags=d.get("tags", []),
            enable=d.get("enable", True),
        )


# ---------- 元数据清理（历史遗留的 version/author 不再保留） ----------

def _strip_legacy_meta(meta: dict, json_path: Path | None = None) -> dict:
    """从元数据中剥离历史遗留的 version/author 字段（"不保留"语义）。

    若 json_path 提供且文件确含这两个字段，则原地重写文件完成物理清理。
    """
    changed = False
    for key in ("version", "author"):
        if key in meta:
            meta.pop(key, None)
            changed = True
    if changed and json_path is not None:
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    return meta


# ---------- CRUD ----------

def list_skills() -> list[dict]:
    """列出所有 skill 的基本信息（不含主体内容）。

    输出:
        list[dict]: 每项含 name, description, tags, has_attachments, attachment_files
    """
    _ensure_skills_dir()
    result = []
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        json_path = entry / "skill.json"
        if not json_path.is_file():
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        meta = _strip_legacy_meta(meta, json_path)
        meta["name"] = entry.name
        meta.setdefault("description", "")
        meta.setdefault("tags", [])
        meta.setdefault("enable", True)
        attachment_files = _list_attachments(entry.name)
        meta["has_attachments"] = bool(attachment_files)
        meta["attachment_files"] = attachment_files
        result.append(meta)
    return result


def get_skill(name: str) -> dict | None:
    """获取单个 skill 的完整信息（含主体内容和附件列表）。

    输出:
        dict 或 None，字段: name, description, tags, enable,
        content (skill.md 内容), attachment_files
    """
    skill_dir = SKILLS_DIR / name
    if not skill_dir.is_dir():
        return None
    json_path = skill_dir / "skill.json"
    md_path = skill_dir / "skill.md"

    meta = {}
    if json_path.is_file():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    meta = _strip_legacy_meta(meta, json_path)

    content = ""
    if md_path.is_file():
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            pass

    return {
        "name": name,
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "enable": meta.get("enable", True),
        "content": content,
        "attachment_files": _list_attachments(name),
    }


def create_or_update_skill(name: str, description: str = "", content: str = "",
                           tags: list[str] | None = None, enable: bool = True) -> bool:
    """创建或更新一个 skill。

    输入:
        name: skill 名称（即文件夹名）。
        description: 简述。
        content: skill.md 的内容。
        tags: 标签列表（可选，便于分级筛选）。
        enable: 是否启用此 skill，默认 True。

    输出:
        成功返回 True。
    """
    _ensure_skills_dir()
    if not name or not name.strip():
        return False
    name = name.strip().replace(" ", "_")
    skill_dir = SKILLS_DIR / name
    os.makedirs(skill_dir, exist_ok=True)

    # 写 skill.json（不保留 version/author）
    meta = {
        "name": name,
        "description": description,
        "tags": tags or [],
        "enable": enable,
    }
    json_path = skill_dir / "skill.json"
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError:
        return False

    # 写 skill.md
    md_path = skill_dir / "skill.md"
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        return False

    return True


def delete_skill(name: str) -> bool:
    """删除一个 skill 及其所有附件。

    输出:
        存在且删除成功返回 True，不存在返回 False。
    """
    skill_dir = SKILLS_DIR / name
    if not skill_dir.is_dir():
        return False
    shutil.rmtree(skill_dir, ignore_errors=True)
    return True


# ---------- 附件管理（以 skill 目录为根，不强制 attachments/ 子目录） ----------

def _skill_dir(skill_name: str) -> Path:
    return SKILLS_DIR / skill_name


def _list_attachments(skill_name: str) -> list[str]:
    """列出某 skill 的所有附件相对路径（排除 skill.json/skill.md）。"""
    sd = _skill_dir(skill_name)
    if not sd.is_dir():
        return []
    result = []
    for root, dirs, files in os.walk(sd):
        # 跳过 __pycache__ 等缓存目录
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if fname in _SKILL_META_FILES and root == str(sd):
                continue
            rel = os.path.relpath(os.path.join(root, fname), sd)
            result.append(rel.replace("\\", "/"))
    result.sort()
    return result


def _safe_relpath(filename: str) -> str | None:
    """规范化附件相对路径并做穿越防护；非法返回 None。"""
    safe = filename.replace("\\", "/").strip("/")
    if not safe or safe.startswith("/") or ".." in safe.split("/"):
        return None
    return safe


def add_attachment(skill_name: str, filename: str, content_bytes: bytes) -> bool:
    """上传/更新一个附件文件到 skill。

    输入:
        skill_name: skill 名称。
        filename: 附件文件名（可包含相对子路径，如 "scripts/run.py"）。
        content_bytes: 文件二进制内容。

    输出:
        成功返回 True。
    """
    sd = _skill_dir(skill_name)
    if not sd.is_dir():
        return False
    safe_name = _safe_relpath(filename)
    if safe_name is None or safe_name.lower() in _SKILL_META_FILES:
        return False
    target = sd / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "wb") as f:
            f.write(content_bytes)
        return True
    except OSError:
        return False


def delete_attachment(skill_name: str, filename: str) -> bool:
    """删除某 skill 下的一个附件。

    输出:
        存在且删除成功返回 True。
    """
    sd = _skill_dir(skill_name)
    safe_name = _safe_relpath(filename)
    if safe_name is None:
        return False
    target = sd / safe_name
    if not target.is_file():
        return False
    try:
        os.remove(target)
        # 移除空父目录
        parent = target.parent
        while parent != sd and parent != SKILLS_DIR:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True
    except OSError:
        return False


def get_attachment_bytes(skill_name: str, filename: str) -> bytes | None:
    """获取附件文件的二进制内容。"""
    sd = _skill_dir(skill_name)
    safe_name = _safe_relpath(filename)
    if safe_name is None:
        return None
    target = sd / safe_name
    if not target.is_file():
        return None
    try:
        with open(target, "rb") as f:
            return f.read()
    except OSError:
        return None


# ---------- zip 导入（前端先解析展示，点保存后才落盘） ----------

def _parse_frontmatter(md: str) -> tuple[dict, str]:
    """解析 skill.md 头部的 frontmatter，仅保留 name/description，其余丢弃。

    支持 ``description: >`` 折叠多行风格与普通单行 ``key: value``。

    输入:
        md: skill.md 全文。

    输出:
        (meta, body)；meta 含 name/description（可能为空），body 为 frontmatter 之后的正文。
    """
    if not md.startswith("---"):
        return {}, md
    end = md.find("\n---", 3)
    if end == -1:
        return {}, md
    head = md[3:end]
    body = md[end + 4:].lstrip("\n")

    meta: dict[str, list[str]] = {}
    cur_key: str | None = None
    for line in head.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if key in ("name", "description"):
                cur_key = key
                meta[key] = [val]
            else:
                cur_key = None  # 其余字段直接丢弃
        elif cur_key in ("name", "description") and (line.startswith(" ") or line.startswith("\t")):
            # 折叠/续行（description: > 后缩进的各行）
            meta[cur_key].append(line.strip())

    result = {}
    for key in ("name", "description"):
        vals = [v for v in meta.get(key, []) if v]
        if not vals:
            result[key] = ""
            continue
        if key == "name":
            result[key] = vals[0].strip().strip("\"'")
        else:
            # description 折叠续行以空格连接
            result[key] = " ".join(vals).strip().strip("\"'")
    return result, body


def _find_skill_md_in_zip(zf: zipfile.ZipFile) -> tuple[str | None, str | None]:
    """在 zip 中定位 skill.md/SKILL.md（一级子目录下优先，根目录兜底）。

    输出:
        (entry_name, top_dir)；top_dir 为共同的一级目录前缀（可能为空）。
    """
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        return None, None
    # 根目录下的 skill.md
    for n in names:
        if "/" not in n and n.lower() == "skill.md":
            return n, ""
    # 一级子目录下的 skill.md（{dir}/skill.md）
    for n in names:
        parts = n.split("/")
        if len(parts) == 2 and parts[1].lower() == "skill.md":
            return n, parts[0]
    return None, None


def parse_skill_zip(zip_bytes: bytes) -> dict | None:
    """解析 skill zip 包（不落盘），提取 name/description/content 与附件列表。

    输入:
        zip_bytes: zip 文件字节。

    输出:
        {"name", "description", "content", "attachments": [相对路径...]}；
        未找到 skill.md/SKILL.md 时返回 None。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return None
    with zf:
        md_entry, top_dir = _find_skill_md_in_zip(zf)
        if md_entry is None:
            return None
        try:
            md_text = zf.read(md_entry).decode("utf-8", errors="replace")
        except KeyError:
            return None
        meta, body = _parse_frontmatter(md_text)
        # 附件：一级子目录下除 skill.md/skill.json 之外的其余文件（不深入展开子目录内部）
        attachments = []
        for n in zf.namelist():
            if n.endswith("/") or n == md_entry:
                continue
            parts = n.split("/")
            if top_dir:
                if parts[0] != top_dir:
                    continue
                rel = "/".join(parts[1:])
            else:
                rel = n
            if rel.lower() in ("skill.md", "skill.json"):
                continue
            attachments.append(rel)
        attachments.sort()
        return {
            "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "content": body,
            "attachments": attachments,
        }


def import_skill_zip(name: str, zip_bytes: bytes, description: str = "",
                     content: str = "", tags: list[str] | None = None,
                     enable: bool = True) -> bool:
    """导入 skill zip 包到 skills 目录（含附件，保持原相对路径）。

    输入:
        name: skill 名称（前端解析后用户可修改）。
        zip_bytes: zip 文件字节。
        description/content/tags/enable: 用户在前端编辑后的覆盖值；
            content 为空时使用 zip 内 skill.md 原文。

    输出:
        成功返回 True。
    """
    if not name or not name.strip():
        return False
    name = name.strip().replace(" ", "_")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return False
    with zf:
        md_entry, top_dir = _find_skill_md_in_zip(zf)
        if md_entry is None:
            return False
        try:
            md_text = zf.read(md_entry).decode("utf-8", errors="replace")
        except KeyError:
            return False
        meta, body = _parse_frontmatter(md_text)
        final_content = content if content else body
        final_description = description if description else meta.get("description", "")

    skill_dir = SKILLS_DIR / name
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)
    os.makedirs(skill_dir, exist_ok=True)

    ok = create_or_update_skill(name, final_description, final_content, tags or [], enable)
    if not ok:
        return False

    # 提取附件（跳过 skill.md/skill.json；剥离一级目录前缀；穿越防护）
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        with zf:
            for n in zf.namelist():
                if n.endswith("/") or n == md_entry:
                    continue
                parts = n.split("/")
                if top_dir:
                    if parts[0] != top_dir:
                        continue
                    rel = "/".join(parts[1:])
                else:
                    rel = n
                if rel.lower() in ("skill.md", "skill.json") or not rel:
                    continue
                safe = _safe_relpath(rel)
                if safe is None:
                    continue
                target = skill_dir / safe
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "wb") as f:
                    f.write(zf.read(n))
    except (zipfile.BadZipFile, OSError):
        pass
    return True


# ---------- 供 skill_router 使用的批量加载 ----------

def load_all_skill_contents() -> dict[str, str]:
    """加载所有 **启用** skill 的 skill.md 内容，键为 skill 名称。

    skill.json 中 enable 为 false 的 skill 会被跳过。

    输出:
        {skill_name: markdown_content, ...}
    """
    _ensure_skills_dir()
    result = {}
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        # 检查 skill.json 中的 enable 字段（默认视为启用，兼容旧数据）
        json_path = entry / "skill.json"
        if json_path.is_file():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("enable") is False:
                    continue
            except (json.JSONDecodeError, OSError):
                pass
        md_path = entry / "skill.md"
        if not md_path.is_file():
            continue
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                result[entry.name] = f.read()
        except OSError:
            pass
    return result


def load_all_skill_metas() -> dict[str, dict]:
    """加载所有 **启用** skill 的 skill.json 元信息，键为 skill 名称。

    skill.json 中 enable 为 false 的 skill 会被跳过。

    输出:
        {skill_name: {name, description, tags, enable}, ...}
    """
    _ensure_skills_dir()
    result = {}
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        json_path = entry / "skill.json"
        if not json_path.is_file():
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        # 跳过禁用的 skill
        if meta.get("enable") is False:
            continue
        meta = _strip_legacy_meta(meta, json_path)
        meta["name"] = entry.name
        meta.setdefault("description", "")
        meta.setdefault("tags", [])
        meta.setdefault("enable", True)
        result[entry.name] = meta
    return result
