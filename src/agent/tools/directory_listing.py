from __future__ import annotations

import os
import asyncio
from pathlib import Path
from typing import Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model


class DirectoryListing(BaseTool):
    """列出指定目录下的文件和文件夹，帮助 Agent 了解本地文件结构。"""

    args_schema: type[BaseModel] = create_model(
        "DirectoryListingInput",
        path=(
            Optional[str],
            Field(
                default=None,
                description="要查看的目录路径，默认为当前工作目录。"
            ),
        ),
        show_hidden=(
            bool,
            Field(
                default=False,
                description="是否显示隐藏文件（以点开头的文件/文件夹），默认不显示。"
            ),
        ),
    )
    name: str = "directory_listing"
    description: str = (
        "列出指定目录下的所有文件和子目录。可用于探索文件系统、查找文件位置。"
        "仅当需要获取目录内容或确认文件结构时调用，其余情况严禁调用。"
    )

    def _run(self, path: Optional[str] = None, show_hidden: bool = False) -> str:
        try:
            target = Path(path).resolve() if path else Path.cwd()
            if not target.exists():
                return f"路径不存在: {target}"
            if not target.is_dir():
                return f"路径不是目录: {target}"

            items = []
            with os.scandir(target) as entries:
                for entry in entries:
                    if not show_hidden and entry.name.startswith('.'):
                        continue
                    item_type = "DIR" if entry.is_dir() else "FILE"
                    items.append(f"[{item_type}] {entry.name}")

            if not items:
                return f"目录 {target} 为空"
            return f"目录 {target} 的内容:\n" + "\n".join(sorted(items))
        except Exception as e:
            return f"列出目录时出错: {str(e)}"

    async def _arun(self, path: Optional[str] = None, show_hidden: bool = False) -> str:
        return await asyncio.to_thread(self._run, path, show_hidden)
