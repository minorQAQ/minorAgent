"""工具调用规范化、工具执行与 JSON 安全转换。

系统定位:
    位于 Agent 工具链与人工确认（HITL）之间的适配层，被 ``core/routing``、
    ``core/runtime``、``core/approvals``、``tools/agent_call`` 调用，
    负责：归一化工具调用对象、安全执行工具并构造 ToolMessage、JSON 安全转换。

可扩展性:
    - 新增工具参数格式时，可在 ``normalize_tool_call`` 中扩展 args 解析逻辑。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any
from uuid import UUID


def _invoke_with_timeout(tool, tool_call_input: dict, timeout: float) -> Any:
    """在 daemon 线程中执行 tool.invoke，超时返回 None。

    超时后工作线程仍在后台运行（Python 无法强杀线程），结果被丢弃。
    工具内部抛出的异常会在主线程 re-raise（保留 SubAgentPendingError 冒泡）。

    输入:
        tool: LangChain BaseTool 实例。
        tool_call_input: 传给 tool.invoke 的输入字典。
        timeout: 超时秒数。

    输出:
        tool.invoke 的返回值；超时返回 None。
    """
    container: dict = {}

    def _worker():
        try:
            container["result"] = tool.invoke(tool_call_input)
        except BaseException as e:  # noqa: BLE001 - 需透传 SubAgentPendingError 等所有异常
            container["error"] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return None  # 超时
    if "error" in container:
        raise container["error"]
    return container.get("result")


def invoke_tool_and_build_message(tool, tool_name: str, tool_args: dict, tool_call_id: str = "", timeout: float | None = None) -> tuple[str, str | None]:
    """调用工具并返回 (content, artifact) 以便构造 ToolMessage。

    统一处理 BaseTool.invoke 的三种返回形式（ToolMessage / tuple / str），
    消除 runtime.py 与 agent_call.py 中的重复代码。

    输入:
        tool: LangChain BaseTool 实例。
        tool_name: 工具名。
        tool_args: 工具参数字典。
        tool_call_id: 工具调用 ID。
        timeout: 执行超时（秒）；None 时从工具配置查询（默认 300）。

    输出:
        (content: str, artifact: Any | None)。超时返回 ("工具执行超时（{n}s）", None)。

    系统定位:
        由 ``core/runtime`` 和 ``tools/agent_call`` 在需要手动 invoke 工具时调用。
    """
    from langchain_core.messages import ToolMessage

    tool_call_input = {
        "name": tool_name,
        "args": tool_args,
        "id": tool_call_id or "",
        "type": "tool_call",
    }
    # 获取超时值：显式传入 > 配置查询 > 默认 300
    if timeout is None:
        try:
            from agent.core.config_manager import get_tool_timeout, DEFAULT_TOOL_TIMEOUT
            timeout = get_tool_timeout(tool_name) or DEFAULT_TOOL_TIMEOUT
        except Exception:
            timeout = 300.0
    result = _invoke_with_timeout(tool, tool_call_input, timeout)
    if result is None:
        return f"工具执行超时（{int(timeout)}s）", None
    if isinstance(result, ToolMessage):
        content = str(result.content) if result.content else ""
        artifact = getattr(result, "artifact", None)
        return content, artifact
    if isinstance(result, tuple):
        content = str(result[0]) if result[0] else ""
        artifact = result[1] if len(result) > 1 else None
        return content, artifact
    return str(result), None


def json_safe(value: Any) -> Any:
    """将任意 Python 对象递归转换为 JSON 可序列化结构。

    功能描述:
        尝试直接序列化；若遇到不可序列化类型，则递归处理 dict/list/tuple，
        UUID 转字符串、datetime 转 isoformat、其余类型转为字符串。

    输入:
        value: 任意 Python 对象。

    输出:
        JSON 兼容的 dict / list / str / 基本类型；结构与原值对应。

    系统定位:
        供 ``core/approvals.build_approval_meta`` 在展示待确认工具参数时使用，
        避免 UI 层因不可序列化对象而报错。

    可扩展性:
        可为 Decimal、Enum 等类型增加专用分支，而非一律 ``str()``。
    """
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(v) for v in value]
        return str(value)


def normalize_tool_call(tool_call: Any) -> dict[str, Any]:
    """将 LangChain ToolCall 或原始 dict 规范化为统一字典。

    功能描述:
        兼容 dict 与对象两种来源，解析 args（支持 JSON 字符串），
        输出固定字段 ``id``、``name``、``args``。

    输入:
        tool_call: LangChain ``ToolCall`` 对象，或含 name/args/id 的 dict。

    输出:
        ``{"id": str|None, "name": str|None, "args": dict}``。

    系统定位:
        ``core/routing`` 在判断工具执行策略和提取待确认项时统一调用，
        屏蔽不同 LLM 返回格式的差异。

    可扩展性:
        可在此增加参数校验、默认值填充，或对接 JSON Schema 校验。
    """
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        args = tool_call.get("args") or {}
        call_id = tool_call.get("id")
    else:
        name = getattr(tool_call, "name", None)
        args = getattr(tool_call, "args", {}) or {}
        call_id = getattr(tool_call, "id", None)
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {"raw": args}
    return {"id": call_id, "name": name, "args": args or {}}


def extract_reasoning_text(msg: Any) -> str:
    """提取 AIMessage 的思考内容：优先 content，其次 additional_kwargs.reasoning_content。

    功能描述:
        部分模型（如 Qwen enable_thinking）将思维链放在 ``additional_kwargs.reasoning_content``
        而非 ``content``。本函数统一兼容两种情况，返回去除首尾空白后的文本（无内容返回 ""）。

    输入:
        msg: AIMessage 对象（需有 content / additional_kwargs 属性）。

    输出:
        思考内容文本（已 strip），无内容时返回空字符串。

    系统定位:
        供 ``core/nodes`` 提取反思内容、``history/tool_call_recorder`` 提取思维链展示文本。
    """
    content = getattr(msg, "content", "")
    if content and isinstance(content, str) and content.strip():
        return content.strip()
    extra = getattr(msg, "additional_kwargs", None) or {}
    rc = extra.get("reasoning_content") if isinstance(extra, dict) else None
    if rc and isinstance(rc, str) and rc.strip():
        return rc.strip()
    return ""


def format_args_summary(args: dict, max_len: int = 80) -> str:
    """将工具参数 dict 序列化为截断的 JSON 字符串摘要。

    功能描述:
        ``json.dumps`` 后按 ``max_len`` 截断并追加 "..."。``default=str`` 保证
        不可序列化对象也能输出（如 Enum、自定义类）。

    输入:
        args: 工具参数字典。
        max_len: 最大长度，超出则截断。

    输出:
        截断后的 JSON 字符串。

    系统定位:
        供 ``core/loop_detector`` 死循环检测、``history/tool_call_recorder`` 工具调用记录展示。
    """
    s = json.dumps(args, ensure_ascii=False, default=str)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s

