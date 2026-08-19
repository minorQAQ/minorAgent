"""终端命令执行工具：在本地终端中执行 shell 命令并返回结果。

支持的操作：
- 执行任意终端命令（如 python script.py、pip install xxx、dir 等）
- 可指定工作目录
- 自动返回 stdout 和 stderr
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field


class TerminalExecuteInput(BaseModel):
    command: str = Field(..., description="要在终端中执行的命令，例如 'python script.py' 或 'dir'")
    working_dir: Optional[str] = Field(
        None,
        description="命令执行的工作目录（绝对路径）。不指定则使用当前工作目录。",
    )
    timeout: int = Field(
        120,
        description="命令执行的超时时间（秒），默认 120 秒。pip install 等耗时操作建议至少 120 秒。",
    )
    use_venv: bool = Field(
        True,
        description="是否在虚拟环境中执行命令。默认 True，会自动激活配置的虚拟环境。设为 False 则使用系统级环境。",
    )


class TerminalExecute(BaseTool):
    args_schema: type[BaseModel] = TerminalExecuteInput
    name: str = "terminal_execute"
    description: str = (
        "终端命令执行工具。在本地终端（PowerShell）中执行 shell 命令并返回执行结果。\n\n"
        "【支持的操作】\n"
        "- 执行 Python 脚本: python script.py\n"
        "- 安装依赖: pip install xxx\n"
        "- 运行程序: node app.js、javac Test.java 等\n"
        "- 文件操作: dir、copy、move 等\n"
        "- 其他任意终端命令\n\n"
        "【参数说明】\n"
        "- command: 必填，要执行的命令字符串\n"
        "- working_dir: 可选，命令执行的工作目录\n"
        "- timeout: 超时时间（秒），默认 120 秒\n\n"
        "【数据作图标准流程】（本工具替代 data_plot，用于基于已入库数据库数据作图）\n"
        "当用户要求对已入库的数据画图/出图表时，按以下流程用本工具执行一个 Python 脚本：\n"
        "1. 查库：脚本内连接数据库（MySQL 或 SQLite）。连接参数从 env_config.json 的\n"
        "   工具数据库配置（TOOL_DB_*）读取，或直接\n"
        "   `from agent.core.db import load_tool_db_config` 获取；执行只读 SELECT 取数。\n"
        "2. 画图：用 matplotlib。脚本开头必须 `import matplotlib; matplotlib.use('Agg')`\n"
        "   （无头模式，避免弹窗阻塞）；中文需设字体\n"
        "   `plt.rcParams['font.sans-serif']=['SimHei','Microsoft YaHei','DejaVu Sans']`、\n"
        "   `plt.rcParams['axes.unicode_minus']=False`，否则中文乱码。\n"
        "3. 保存：PNG 存到 workspace 目录\n"
        "   (`from agent.utils.env_utils import get_workspace_dir`)。\n"
        "4. 脚本只 print 关键信息（行数、保存路径），勿打印全量数据——stdout 超 4000 字符会被截断。\n"
        "5. 画完后调 send_file 工具把 PNG 发给用户下载/预览。\n"
        "建议先用 doc_tool 或 Write 把脚本落盘为 .py，再 `python xxx.py` 执行，便于调试与复用。\n\n"
        "【注意】\n"
        "- 命令将在 PowerShell 中执行，默认启用虚拟环境（use_venv=True，自动注入 venv 的 PATH）\n"
        "- stdout/stderr 各最多返回 4000 字符，超长会截断\n"
        "- 有默认 120 秒超时，防止命令卡死\n"
        "- 谨慎执行高危命令（如删除、格式化等），工具会如实执行你的指令"
    )

    def _run(
        self,
        command: str,
        working_dir: Optional[str] = None,
        timeout: int = 120,
        use_venv: bool = True,
    ) -> str:
        try:
            # 如果未指定 working_dir，优先使用运行时选中的工作空间，回退到 env_config 默认值
            if not working_dir:
                try:
                    from agent.memory.system_prompt import _current_workspace_dir
                    from agent.utils.env_utils import get_workspace_dir
                    if _current_workspace_dir and os.path.isdir(_current_workspace_dir):
                        working_dir = _current_workspace_dir
                    else:
                        working_dir = get_workspace_dir()
                except Exception:
                    pass

            cwd = working_dir if working_dir else os.getcwd()

            if not os.path.isdir(cwd):
                return f"[ERROR] 工作目录不存在: {cwd}"

            # 构建完整命令：如果启用 venv，将虚拟环境 Scripts 目录注入 PATH 最前
            full_command = command
            if use_venv:
                scripts_dir = self._get_venv_scripts_dir()
                if scripts_dir:
                    # PowerShell: 将 Scripts 目录添加为 PATH 前缀，确保 python/pip 优先使用 venv 版本
                    full_command = f'$env:PATH = "{scripts_dir};" + $env:PATH; {command}'

            # 使用 Popen + communicate 避免管道缓冲区填满导致死锁
            proc = subprocess.Popen(
                ["powershell", "-Command", full_command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                encoding="gbk",
                errors="replace",
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return (
                    f"[ERROR] 命令执行超时（{timeout}秒），已强制终止\n"
                    f"命令: {command}\n"
                    f"工作目录: {cwd}\n"
                    f"--- 超时前已获取的部分输出 ---\n"
                    f"stdout: {(stdout or '').strip()[-500:]}\n"
                    f"stderr: {(stderr or '').strip()[-500:]}"
                )

            returncode = proc.returncode
            stdout = stdout.strip()
            stderr = stderr.strip()

            # 限制输出长度，防止返回过大导致 LLM 上下文爆炸
            max_output = 4000
            if len(stdout) > max_output:
                stdout = stdout[:max_output] + f"\n...(已截断，共 {len(stdout)} 字符)"
            if len(stderr) > max_output:
                stderr = stderr[:max_output] + f"\n...(已截断，共 {len(stderr)} 字符)"

            parts = [f"=== 命令执行结果 ==="]
            parts.append(f"工作目录: {cwd}")
            parts.append(f"命令: {command}")
            parts.append(f"退出码: {returncode}")

            if stdout:
                parts.append(f"\n--- stdout ---\n{stdout}")
            if stderr:
                parts.append(f"\n--- stderr ---\n{stderr}")
            if not stdout and not stderr:
                parts.append("\n(无输出)")

            return "\n".join(parts)

        except FileNotFoundError:
            return f"[ERROR] 找不到 PowerShell，请确认系统环境正常"
        except Exception as e:
            return f"[ERROR] terminal_execute 执行出错: {str(e)}"

    @staticmethod
    def _get_venv_scripts_dir() -> str:
        """获取虚拟环境的 Scripts 目录路径（用于 PATH 注入）。
        
        优先从 USER_PYTHON_PATH 反推，其次自动发现项目级 myenv。
        例如 "C:\\myenv\\Scripts\\python.exe" → "C:\\myenv\\Scripts"
        """
        try:
            from agent.utils.env_utils import get_venv_dir
            venv_dir = get_venv_dir()
            if venv_dir:
                scripts = os.path.join(venv_dir, "Scripts")
                if os.path.isdir(scripts):
                    return scripts
        except Exception:
            pass
        # 自动发现：项目根目录下的 myenv
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "myenv", "Scripts"),
            os.path.join(os.getcwd(), "myenv", "Scripts"),
        ]
        for c in candidates:
            c = os.path.abspath(c)
            if os.path.isdir(c) and os.path.isfile(os.path.join(c, "python.exe")):
                return c
        return ""

    async def _arun(self, **kwargs) -> str:
        import asyncio
        return await asyncio.to_thread(self._run, **kwargs)
