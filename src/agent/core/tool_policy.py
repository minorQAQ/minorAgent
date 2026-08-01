"""工具执行安全策略：直接执行 vs 需人工确认。

系统定位:
    在 ``core/routing.should_continue`` 中决定图是否进入 ToolNode，
    或在遇到需确认工具时提前结束图执行，交由 UI 与 ``runtime`` 处理。

自动执行规则 (auto_execute_rules):
    对于权限为 ``confirm`` 的工具，可通过 tool_config.json 中的
    ``auto_execute_rules`` 定义参数条件，匹配时自动升级为 ``direct``。
    每条规则格式: ``{"parameter": "action", "operator": "equals", "value": "query"}``
    含义: 当工具调用的 ``action`` 参数等于 ``"query"`` 时，跳过确认直接执行。

可扩展性:
    - 可增加 operator 类型（contains、in、regex）。
    - 可返回 ``Literal["direct", "confirm", "deny"]`` 支持完全禁止类工具。
"""
from __future__ import annotations

from typing import Literal

# 从 tool_config.json 加载的自动执行规则缓存
_AUTO_EXECUTE_RULES_CACHE: dict[str, list[dict]] | None = None
# 从 tool_config.json 加载的工具权限缓存
_TOOL_PERMISSIONS_CACHE: dict[str, str] | None = None


def _get_tool_permissions() -> dict[str, str]:
    """懒加载 tool_config.json 中各工具的 permission 字段。

    返回:
        {tool_name: "direct"|"confirm"} 映射；加载失败返回空字典。
    """
    global _TOOL_PERMISSIONS_CACHE
    if _TOOL_PERMISSIONS_CACHE is not None:
        return _TOOL_PERMISSIONS_CACHE
    try:
        from agent.core.config_manager import load_tool_configs
        configs = load_tool_configs()
        _TOOL_PERMISSIONS_CACHE = {}
        for c in configs:
            if c.enabled:
                _TOOL_PERMISSIONS_CACHE[c.name] = c.permission
    except Exception:
        _TOOL_PERMISSIONS_CACHE = {}
    return _TOOL_PERMISSIONS_CACHE


def _get_auto_execute_rules() -> dict[str, list[dict]]:
    """懒加载 tool_config.json 中的 auto_execute_rules。

    返回:
        {tool_name: [rule, ...]} 映射；加载失败返回空字典。
    """
    global _AUTO_EXECUTE_RULES_CACHE
    if _AUTO_EXECUTE_RULES_CACHE is not None:
        return _AUTO_EXECUTE_RULES_CACHE
    try:
        from agent.core.config_manager import load_tool_configs
        configs = load_tool_configs()
        _AUTO_EXECUTE_RULES_CACHE = {}
        for c in configs:
            if c.enabled and c.auto_execute_rules:
                _AUTO_EXECUTE_RULES_CACHE[c.name] = c.auto_execute_rules
    except Exception:
        _AUTO_EXECUTE_RULES_CACHE = {}
    return _AUTO_EXECUTE_RULES_CACHE


def reload_auto_execute_rules() -> None:
    """清除缓存，下次 classify 时重新从 JSON 加载。"""
    global _AUTO_EXECUTE_RULES_CACHE, _TOOL_PERMISSIONS_CACHE
    _AUTO_EXECUTE_RULES_CACHE = None
    _TOOL_PERMISSIONS_CACHE = None


def _match_auto_execute_rule(rule: dict, args: dict) -> bool:
    """检查工具调用的 args 是否匹配单条自动执行规则。

    输入:
        rule: {"parameter": str, "operator": str, "value": str}
        args: 工具调用的参数 dict。

    输出:
        匹配则返回 True。

    支持的 operator:
        - "equals": 参数值（转为字符串后）完全等于 rule value。
        - "exists": 参数存在（不为 None/空字符串）即匹配，忽略 value。
    """
    param = rule.get("parameter", "")
    op = rule.get("operator", "equals")
    if op == "exists":
        actual = args.get(param)
        return actual is not None and actual != ""
    expected = str(rule.get("value", ""))
    actual = str(args.get(param, ""))
    if op == "equals":
        return actual == expected
    return False


def classify_tool_execution(tool_name: str | None, args: dict) -> Literal["direct", "confirm"]:
    """判定工具调用是否可在图内自动执行。

    判定优先级:
        1. 空名称 / human_interaction → 强制 confirm
        2. tool_config.json 中 permission == "direct" → direct
        3. tool_config.json 中 auto_execute_rules 匹配 → direct
        4. 其余 → confirm

    注意:
        参数提取时使用安全默认值，避免 KeyError 或 None 导致的误判。
    """
    if not tool_name:
        return "confirm"
    # human_interaction 必须人工确认，不可绕过
    if tool_name == "human_interaction":
        return "confirm"

    # 读取 tool_config.json 中的权限（含 safe_tools 默认 direct，用户可改）
    permissions = _get_tool_permissions()
    if permissions.get(tool_name) == "direct":
        return "direct"

    # 检查 JSON 配置的 auto_execute_rules
    rules = _get_auto_execute_rules().get(tool_name)
    if rules:
        for rule in rules:
            if _match_auto_execute_rule(rule, args):
                return "direct"

    # 未匹配默认需确认
    return "confirm"
