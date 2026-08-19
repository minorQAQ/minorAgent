from __future__ import annotations

import json
import asyncio
from typing import Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field


class HumanInteractionInput(BaseModel):
    title: str = Field(default="需要人工处理", description="展示给人类的交互标题。")
    prompt: str = Field(default="请处理后继续。", description="需要人类理解并响应的具体问题。")
    options: Optional[list[str] | str] = Field(
        default=None,
        description="可选项。优先传字符串数组；JSON 字符串或逗号分隔会被自动解析。"
                    "可空——人类也可直接在补充输入框中输入任意信息。",
    )


def normalize_human_interaction_args(args: dict) -> dict:
    """规范化 human_interaction 工具参数为固定 schema（title / prompt / options）。"""
    normalized = dict(args or {})
    normalized["title"] = str(normalized.get("title") or "需要人工处理")
    normalized["prompt"] = str(normalized.get("prompt") or "请处理后继续。")
    normalized["options"] = HumanInteraction.normalize_options(normalized.get("options"))
    return normalized


class HumanInteraction(BaseTool):
    """向人类请求补充信息或选择；调用时阻塞等待前端通知条应答，答案作为普通工具返回值。"""

    args_schema: type[BaseModel] = HumanInteractionInput
    name: str = "human_interaction"
    description: str = (
        "当任务缺少关键信息或需要人类选择路径时调用。"
        "通过 options 提供可选项（可空），人类可以从选项中选择，"
        "也可在补充输入框中输入任意信息——输入内容将直接作为本工具的返回值。"
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
    def format_result(response: str) -> str:
        """将用户输入（选中的选项或补充输入框内容）直接作为工具返回值。"""
        text = (response or "").strip()
        return text or "用户未提供信息"

    @staticmethod
    def build_request_meta(args: dict) -> dict:
        """将规范化后的工具参数构造成前端通知条渲染数据。"""
        args = normalize_human_interaction_args(args)
        agent_name = "主Agent"
        try:
            from agent.core.human_request import get_current_agent_name
            _ag = get_current_agent_name()
            agent_name = "主Agent" if _ag in ("", "__main__") else _ag
        except Exception:
            pass
        return {
            "type": "human_interaction",
            "title": args["title"] or "需要人工处理",
            "prompt": args["prompt"] or "请处理后继续。",
            "tool_name": "human_interaction",
            "args": {
                "说明": args["prompt"] or "请处理后继续。",
                "可选项": args["options"] or [],
            },
            "options": args["options"] or [],
            "agent_name": agent_name,
            "is_sub_agent": agent_name != "主Agent",
            "resolved": False,
        }

    def _run(
        self,
        title: str = "需要人工处理",
        prompt: str = "请处理后继续。",
        options: Optional[list[str] | str] = None,
    ) -> str:
        try:
            args = {
                "title": title,
                "prompt": prompt,
                "options": options,
            }
            normalized = normalize_human_interaction_args(args)
            from agent.core.human_request import ask_human
            from agent.history.tool_call_recorder import get_current_session
            session_id = get_current_session() or ""
            answer = ask_human(session_id, self.build_request_meta(normalized))
            # 拒绝/跳过：原样返回用户决策文本，让 Agent 自行调整，不结束整轮
            if answer.get("decision") in ("reject", "skip"):
                return f"用户{('拒绝' if answer['decision'] == 'reject' else '已跳过')}此次交互：{answer.get('instruction') or ''}".strip()
            return self.format_result(answer.get("instruction") or "")
        except RuntimeError:
            raise  # ABORTED_BY_USER 冒泡到 runtime 统一按暂停处理
        except Exception as e:
            return f"[ERROR] human_interaction 工具执行出错: {str(e)}"

    async def _arun(
        self,
        title: str = "需要人工处理",
        prompt: str = "请处理后继续。",
        options: Optional[list[str] | str] = None,
    ) -> str:
        return await asyncio.to_thread(self._run, title, prompt, options)
