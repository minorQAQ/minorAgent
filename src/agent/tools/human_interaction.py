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


def normalize_human_interaction_args(args: dict) -> dict:
    """规范化 human_interaction 工具参数为固定 schema。

    输入:
        args: 模型传入的原始参数字典。

    输出:
        含 interaction_type、title、prompt、options、suggested_response、questions 的字典；
        interaction_type 限定为 information | selection。
    """
    normalized = dict(args or {})
    normalized["interaction_type"] = str(normalized.get("interaction_type") or "information")
    if normalized["interaction_type"] not in {"information", "selection"}:
        normalized["interaction_type"] = "information"
    normalized["title"] = str(normalized.get("title") or "需要人工处理")
    normalized["prompt"] = str(normalized.get("prompt") or "请处理后继续。")
    normalized["options"] = HumanInteraction.normalize_options(normalized.get("options"))
    normalized["suggested_response"] = str(normalized.get("suggested_response") or "")
    # 规范化 questions 字段
    questions = normalized.get("questions")
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except (json.JSONDecodeError, TypeError):
            questions = None
    if isinstance(questions, list):
        normalized_questions = []
        for q in questions:
            if isinstance(q, dict):
                nq = {
                    "question": str(q.get("question", "")),
                    "options": HumanInteraction.normalize_options(q.get("options")),
                }
                normalized_questions.append(nq)
        normalized["questions"] = normalized_questions if normalized_questions else None
    else:
        normalized["questions"] = None
    return normalized


class HumanInteraction(BaseTool):
    """向人类请求补充信息或选择；调用时阻塞等待前端浮窗应答，答案作为普通工具返回值。"""

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
        if text.startswith("用户拒绝") or text.startswith("用户已跳过"):
            return text
        return f"用户补充信息如下：{text}" if text else "用户没有补充信息"

    @staticmethod
    def build_request_meta(args: dict) -> dict:
        """将规范化后的工具参数构造成前端浮窗渲染数据（与旧 pending_action 形状一致）。"""
        args = normalize_human_interaction_args(args)
        interaction_type = args["interaction_type"]
        default_titles = {
            "information": "请补充信息",
            "selection": "请选择一个选项",
        }
        agent_name = "主Agent"
        try:
            from agent.core.human_request import get_current_agent_name
            _ag = get_current_agent_name()
            agent_name = "主Agent" if _ag in ("", "__main__") else _ag
        except Exception:
            pass
        return {
            "type": "human_interaction",
            "interaction_type": interaction_type,
            "title": args["title"] or default_titles.get(interaction_type, "需要人工处理"),
            "prompt": args["prompt"] or "请处理后继续。",
            "tool_name": "human_interaction",
            "args": {
                "交互类型": interaction_type,
                "说明": args["prompt"] or "请处理后继续。",
                "可选项": args["options"] or [],
            },
            "instruction": args["suggested_response"] or "",
            "options": args["options"] or [],
            "questions": args["questions"] or None,
            "agent_name": agent_name,
            "is_sub_agent": agent_name != "主Agent",
            "resolved": False,
        }

    def _run(
        self,
        interaction_type: str = "information",
        title: str = "需要人工处理",
        prompt: str = "请处理后继续。",
        options: Optional[list[str] | str] = None,
        suggested_response: Optional[str] = None,
        questions: Optional[list[dict]] = None,
    ) -> str:
        try:
            args = {
                "interaction_type": interaction_type,
                "title": title,
                "prompt": prompt,
                "options": options,
                "suggested_response": suggested_response,
                "questions": questions,
            }
            normalized = normalize_human_interaction_args(args)
            from agent.core.human_request import ask_human
            from agent.history.tool_call_recorder import get_current_session
            session_id = get_current_session() or ""
            answer = ask_human(session_id, self.build_request_meta(normalized))
            # 拒绝/跳过：原样返回用户决策文本，让 Agent 自行调整，不结束整轮
            if answer.get("decision") in ("reject", "skip"):
                return f"用户{('拒绝' if answer['decision'] == 'reject' else '已跳过')}此次交互：{answer.get('instruction') or ''}".strip()
            return self.format_result(interaction_type, normalized.get("options") or [], answer.get("instruction") or "")
        except RuntimeError:
            raise  # ABORTED_BY_USER 冒泡到 runtime 统一按暂停处理
        except Exception as e:
            return f"[ERROR] human_interaction 工具执行出错: {str(e)}"

    async def _arun(
        self,
        interaction_type: str = "information",
        title: str = "需要人工处理",
        prompt: str = "请处理后继续。",
        options: Optional[list[str] | str] = None,
        suggested_response: Optional[str] = None,
        questions: Optional[list[dict]] = None,
    ) -> str:
        return await asyncio.to_thread(self._run, interaction_type, title, prompt, options, suggested_response, questions)
