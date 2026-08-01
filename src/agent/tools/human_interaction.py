from __future__ import annotations

import json
import asyncio
from typing import Optional, Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, Field


class HumanInteractionInput(BaseModel):
    interaction_type: Literal["information", "selection"] = Field(
        default="information",
        description="交互类型：information=人工补充信息，selection=人工选择。",
    )
    title: str = Field(default="需要人工处理", description="展示给人类的交互标题。")
    prompt: str = Field(default="请处理后继续。", description="需要人类理解并响应的具体问题或说明。")
    options: Optional[list[str] | str] = Field(
        default=None,
        description="selection 可选项。优先传字符串数组；如果传 JSON 字符串，系统会自动解析。",
    )
    suggested_response: Optional[str] = Field(default=None, description="可选的建议回复、默认选择或默认审批意见。")
    questions: Optional[list[dict]] = Field(
        default=None,
        description="selection 类型时的问题列表。每项含 question(问题文本) 和 options(该问题的选项列表)。"
                    "支持多个问题，每个问题有独立选项及一个可编辑的'其他'输入框。"
                    "例：[{'question': '问题1', 'options': ['A', 'B']}, {'question': '问题2', 'options': ['是', '否']}]",
    )


class HumanInteraction(BaseTool):
    """向人类请求补充信息或选择；实际 UI 确认由图级人工干预层承接。"""

    args_schema: type[BaseModel] = HumanInteractionInput
    name: str = "human_interaction"
    description: str = (
        "当任务缺少关键信息或需要人类选择路径时调用。"
        "两种类型分别是：information=请求人类补充缺失信息；selection=让人类在多个选项中选择且可编辑，"
        "可通过 questions 字段支持多个问题（每问题含 question 和 options）。"
        "工具返回必须被视为用户原始意图的纯字符串反馈。其余情况严禁调用。"
    )

    @staticmethod
    def normalize_options(options: Optional[list[str] | str]) -> list[str]:
        """将 options 参数规范化为字符串列表（支持 JSON 与逗号分隔）。"""
        if options is None:
            return []
        if isinstance(options, str):
            raw = options.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return [str(parsed)]
        return [str(item) for item in options]

    @staticmethod
    def format_result(interaction_type: str, options: list[str] | None = None, response: str = "") -> str:
        """根据交互类型与用户决策生成结果文本。

        供 ``_run``（工具直接执行时的默认结果）与 ``approvals.human_interaction_result``
        （用户确认后的真实结果）共用，消除重复的分支逻辑。

        输入:
            interaction_type: information | selection。
            options: selection 的可选项（用于默认值）。
            response: 用户输入的文本（补充信息、选择项、建议回复等）。

        输出:
            供 ToolMessage 使用的文本内容。
        """
        text = (response or "").strip()
        if interaction_type == "selection":
            # response 可能是 JSON 格式的多问题答案: {"问题1": "答案", ...}
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        lines = []
                        for q, a in parsed.items():
                            lines.append(f"  - {q}: {a}")
                        return "用户选择：\n" + "\n".join(lines) if lines else "用户选择：（无）"
                except json.JSONDecodeError:
                    pass
            selected = text or (options[0] if options else "")
            return f"用户选择：{selected}" if selected else "用户选择："
        return f"用户补充信息如下：{text}" if text else "用户没有补充信息"

    def _run(
        self,
        interaction_type: str = "information",
        title: str = "需要人工处理",
        prompt: str = "请处理后继续。",
        options: Optional[list[str] | str] = None,
        suggested_response: Optional[str] = None,
    ) -> str:
        try:
            normalized_options = self.normalize_options(options)
            return self.format_result(interaction_type, normalized_options, suggested_response or "")
        except Exception as e:
            return f"[ERROR] human_interaction 工具执行出错: {str(e)}"

    async def _arun(
        self,
        interaction_type: str = "information",
        title: str = "需要人工处理",
        prompt: str = "请处理后继续。",
        options: Optional[list[str] | str] = None,
        suggested_response: Optional[str] = None,
    ) -> str:
        return await asyncio.to_thread(self._run, interaction_type, title, prompt, options, suggested_response)
