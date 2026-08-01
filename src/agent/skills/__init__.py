"""Skill 管理器：负责 skill 的增删改查及附件管理。

每个 skill 是一个文件夹，位于 Skills 目录下，结构如下::

    skills/
      {skill_name}/
        skill.json    - 基本信息与描述
        skill.md      - 主体内容（指南）
        attachments/  - 可选附件（.py/.docx/.csv/.xlsx 等）

系统定位:
    为 skill_router 工具和前端 API 提供统一的数据读写接口。

可扩展性:
    可增加版本校验、导入/导出、标签过滤等功能。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent


def _ensure_skills_dir() -> None:
    """确保 skills 目录存在。"""
    os.makedirs(SKILLS_DIR, exist_ok=True)


# ---------- Skill 信息数据类 ----------
class SkillInfo:
    """单个 Skill 的基本信息。"""
    name: str
    description: str
    version: str
    author: str
    tags: list[str]
    enable: bool

    def __init__(self, name: str = "", description: str = "", version: str = "1.0.0",
                 author: str = "", tags: list[str] | None = None, enable: bool = True):
        self.name = name
        self.description = description
        self.version = version
        self.author = author
        self.tags = tags or []
        self.enable = enable

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "enable": self.enable,
        }

    @classmethod
    def from_dict(cls, d: dict, name: str = "") -> "SkillInfo":
        return cls(
            name=d.get("name", name),
            description=d.get("description", ""),
            version=d.get("version", "1.0.0"),
            author=d.get("author", ""),
            tags=d.get("tags", []),
            enable=d.get("enable", True),
        )


# ---------- CRUD ----------

def list_skills() -> list[dict]:
    """列出所有 skill 的基本信息（不含主体内容）。

    输出:
        list[dict]: 每项含 name, description, version, author, tags, has_attachments
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
        meta["name"] = entry.name
        meta.setdefault("description", "")
        meta.setdefault("version", "1.0.0")
        meta.setdefault("author", "")
        meta.setdefault("tags", [])
        meta.setdefault("enable", True)
        # 检查是否有附件
        attach_dir = entry / "attachments"
        meta["has_attachments"] = attach_dir.is_dir() and bool(list(attach_dir.iterdir()))
        meta["attachment_files"] = _list_attachments(entry.name)
        result.append(meta)
    return result


def get_skill(name: str) -> dict | None:
    """获取单个 skill 的完整信息（含主体内容和附件列表）。

    输出:
        dict 或 None，字段: name, description, version, author, tags,
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
        "version": meta.get("version", "1.0.0"),
        "author": meta.get("author", ""),
        "tags": meta.get("tags", []),
        "enable": meta.get("enable", True),
        "content": content,
        "attachment_files": _list_attachments(name),
    }


def create_or_update_skill(name: str, description: str = "", content: str = "",
                           version: str = "0.0", author: str = "minor",
                           tags: list[str] | None = None, enable: bool = True) -> bool:
    """创建或更新一个 skill。

    输入:
        name: skill 名称（即文件夹名）。
        description: 简述。
        content: skill.md 的内容。
        version: 版本号。
        author: 作者。
        tags: 标签列表。
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

    # 写 skill.json
    meta = {
        "name": name,
        "description": description,
        "version": version,
        "author": author,
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


# ---------- 附件管理 ----------

def _attachments_dir(skill_name: str) -> Path:
    return SKILLS_DIR / skill_name / "attachments"


def _list_attachments(skill_name: str) -> list[str]:
    """列出某 skill 的所有附件文件名。"""
    ad = _attachments_dir(skill_name)
    if not ad.is_dir():
        return []
    result = []
    for root, dirs, files in os.walk(ad):
        for fname in files:
            rel = os.path.relpath(os.path.join(root, fname), ad)
            result.append(rel.replace("\\", "/"))
    result.sort()
    return result


def add_attachment(skill_name: str, filename: str, content_bytes: bytes) -> bool:
    """上传/更新一个附件文件到 skill。

    输入:
        skill_name: skill 名称。
        filename: 附件文件名（可包含相对子路径，如 "scripts/run.py"）。
        content_bytes: 文件二进制内容。

    输出:
        成功返回 True。
    """
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        return False
    ad = _attachments_dir(skill_name)
    os.makedirs(ad, exist_ok=True)
    # 安全检查：防止路径穿越
    safe_name = filename.replace("\\", "/").strip("/")
    if ".." in safe_name:
        return False
    target = ad / safe_name
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
    ad = _attachments_dir(skill_name)
    safe_name = filename.replace("\\", "/").strip("/")
    if ".." in safe_name:
        return False
    target = ad / safe_name
    if not target.is_file():
        return False
    try:
        os.remove(target)
        # 移除空父目录
        parent = target.parent
        while parent != ad and parent != SKILLS_DIR:
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
    ad = _attachments_dir(skill_name)
    safe_name = filename.replace("\\", "/").strip("/")
    if ".." in safe_name:
        return None
    target = ad / safe_name
    if not target.is_file():
        return None
    try:
        with open(target, "rb") as f:
            return f.read()
    except OSError:
        return None


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
        {skill_name: {name, description, version, author, tags, enable}, ...}
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
        meta["name"] = entry.name
        meta.setdefault("description", "")
        meta.setdefault("version", "0.0")
        meta.setdefault("author", "minor")
        meta.setdefault("tags", [])
        meta.setdefault("enable", True)
        result[entry.name] = meta
    return result
