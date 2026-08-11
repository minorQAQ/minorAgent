"""ChatQwen：基于 OpenAI 兼容 API 的多模态 LangChain 聊天模型。

系统定位:
    项目默认 LLM 单例 ``llm``，被 agents 绑定工具，并承担：
    - 用户消息预处理（附件、ASR、图片 data URL）
    - 非标准 tool_call XML/JSON 解析
    - Vision 描述接口

依赖:
    env_utils 中的 LLM_* / ASR_BASE_URL

可扩展性:
    - 可子类化覆盖 _preprocess_messages、_create_chat_result
    - 流式、重试、限流可在 _generate 层扩展
"""
import os
from typing import Any, List, Dict, Optional
from pydantic import Field
import re, json

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolCall
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

from agent.utils.env_utils import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT
from agent.utils.agent_utils import assistant_text, Documents_process, audio_file_to_text, make_attachment_text
from agent.utils.image_utils import image_path_to_openai_image_url_part, image_bytes_to_openai_image_url_part, IMAGE_FILE_EXTENSIONS
from agent.memory.system_prompt import VISION_SYSTEM_PROMPT

class ChatQwen(ChatOpenAI):
    """Qwen 系列模型的 LangChain 封装，扩展多模态能力。

    系统定位:
        agents/main_agent 的 llm 与 bind_tools 基底。

    可扩展性:
        新增厂商响应字段时在 _create_chat_result 中适配。
    """

    def __init__(self, **kwargs: Any) -> None:
        """从环境变量或 kwargs 初始化 OpenAI 兼容客户端。

        输入:
            kwargs: 可覆盖 model、api_key、base_url、timeout、max_retries。

        输出:
            无。

        系统定位:
            模块级 ``llm = ChatQwen()`` 单例构造。

        可扩展性:
            可增加 default_headers、proxy 等 ChatOpenAI 参数。
        """
        # 允许调用方覆盖 extra_body：
        #   - None（默认）：使用禁用思考的默认值
        #   - 空 dict {}：清空 extra_body，恢复模型原生行为（含思考模式）
        #   - 非空 dict：直接使用传入值
        custom_extra_body = kwargs.pop("extra_body", None)
        if custom_extra_body is None:
            extra_body = {
                "chat_template_kwargs": {"enable_thinking": False},
                "thinking": {"type": "disabled"},
            }
        else:
            extra_body = custom_extra_body

        super().__init__(
            model=kwargs.pop("model", os.environ.get("LLM_MODEL", "")),
            api_key=kwargs.pop("api_key", os.environ.get("LLM_API_KEY", "")),
            base_url=kwargs.pop("base_url", os.environ.get("LLM_BASE_URL", "")),
            timeout=kwargs.pop("timeout", float(os.environ.get("LLM_TIMEOUT", 60))),
            max_retries=kwargs.pop("max_retries", 0),
            extra_body=extra_body,
            **kwargs
        )
    @staticmethod
    def _process_image_content(part: Dict[str, Any]) -> Dict[str, Any]:
        """将 image_url 块中的本地路径或字节转为 data URL。

        输入: OpenAI 风格 content part dict。
        输出: 处理后的 part 或失败时 text 占位。
        系统定位: _preprocess_messages 多模态分支。
        可扩展性: 委托 image_utils，保持单一图片处理逻辑。
        """
        image_type = part.get("type")
        if image_type != "image_url":
            return part
        image_url = part.get("image_url", {})
        url = image_url.get("url", "")
        if url.startswith(("http://", "https://", "data:")):
            return part
        if isinstance(url, str) and os.path.exists(url):
            ext = os.path.splitext(url)[1].lower()
            if ext in IMAGE_FILE_EXTENSIONS:
                result = image_path_to_openai_image_url_part(url)
                return result if result else {"type": "text", "text": "[图片处理失败]"}
        if isinstance(url, bytes):
            result = image_bytes_to_openai_image_url_part(url)
            return result if result else {"type": "text", "text": "[图片处理失败]"}
        return part

    def _audio_to_text(self, audio_path: str) -> str:
        """调用 ASR 服务将音频转为文本。委托至 agent_utils.audio_file_to_text。

        输入: audio_path 本地音频文件。
        输出: 识别文本字符串。
        """
        return audio_file_to_text(audio_path)

    def _preprocess_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """入模前统一处理：JSON 列表、附件、ASR、图片、文档解析。

        输入: LangChain BaseMessage 列表。
        输出: 规范化后的新消息列表（不修改原列表）。
        系统定位: _generate 调用 super()._generate 之前的适配层。
        可扩展性: 新增 part.type 时在此增加分支。
        """
        new_messages = []
        for msg in messages:
            if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
                text = msg.content.strip()
                if text.startswith("[") and text.endswith("]"):
                    try:
                        possible_list = json.loads(text)
                        if isinstance(possible_list, list):
                            msg = HumanMessage(content=possible_list, additional_kwargs=msg.additional_kwargs)
                    except (json.JSONDecodeError, ValueError):
                        pass
            if isinstance(msg, HumanMessage) and isinstance(msg.content, dict):
                # 尝试从 dict 中提取文本，否则序列化为字符串
                text = msg.content.get("text") or msg.content.get("content") or ""
                if text:
                    msg = HumanMessage(content=str(text), additional_kwargs=msg.additional_kwargs)
                else:
                    msg = HumanMessage(content=json.dumps(msg.content, ensure_ascii=False), additional_kwargs=msg.additional_kwargs)
            elif isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                new_content: List[Dict[str, Any] | str] = []
                for part in msg.content:
                    if isinstance(part, dict):
                        if part.get("type") == "audio":
                            audio_path = part.get("audio_path")
                            if audio_path:
                                normalized = audio_path.replace("\\", "/")
                                try:
                                    text = self._audio_to_text(audio_path)
                                    new_content.append({"type": "text", "text": make_attachment_text("音频", normalized, text)})
                                except Exception as e:
                                    new_content.append({"type": "text", "text": make_attachment_text("音频", normalized, f"[语音识别失败: {e}]")})
                        elif part.get("type") == "image_url":
                            image_url = part.get("image_url", {})
                            url = image_url.get("url", "")
                            # 若为本地文件路径，注入路径 + 尺寸文本供 Agent 工具引用（如 PPT Skill 使用用户图片）
                            if isinstance(url, str) and os.path.exists(url) and not url.startswith(("http://", "https://", "data:")):
                                ext = os.path.splitext(url)[1].lower()
                                if ext in IMAGE_FILE_EXTENSIONS:
                                    normalized_path = url.replace("\\", "/")
                                    try:
                                        from PIL import Image as PILImage
                                        with PILImage.open(url) as img:
                                            w, h = img.size
                                        new_content.append({"type": "text", "text": make_attachment_text("图片", normalized_path, f"{w}×{h}px")})
                                    except Exception:
                                        new_content.append({"type": "text", "text": make_attachment_text("图片", normalized_path)})
                            new_content.append(self._process_image_content(part))
                        elif part.get("type") == "text":
                            text = (part.get("text") or "").strip()
                            if text:
                                new_content.append({"type": "text", "text": text})
                        elif part.get("path") or (part.get("file") or {}).get("path"):
                            file_path = part.get("path") or (part.get("file") or {}).get("path")
                            if isinstance(file_path, str) and os.path.isfile(file_path):
                                ext = os.path.splitext(file_path)[1].lower()
                                normalized_path = file_path.replace("\\", "/")
                                if ext in IMAGE_FILE_EXTENSIONS:
                                    new_content.append(self._process_image_content({"type": "image_url", "image_url": {"url": file_path}}))
                                else:
                                    # 非图片附件只注入文件路径提示，内容由 Agent 通过 doc_tool 读取
                                    new_content.append({"type": "text", "text": make_attachment_text("附件文件", normalized_path)})
                        else:
                            text = assistant_text(part)
                            if text:
                                new_content.append({"type": "text", "text": text})
                    elif isinstance(part, str):
                        text = part.strip()
                        if text:
                            new_content.append(text)
                if len(new_content) == 1 and isinstance(new_content[0], str):
                    msg = HumanMessage(content=new_content[0], additional_kwargs=msg.additional_kwargs)
                else:
                    msg = HumanMessage(content=new_content, additional_kwargs=msg.additional_kwargs)
            new_messages.append(msg)
        return new_messages

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """LangChain 生成入口：预处理 -> API 调用。

        输入:
            messages: 对话消息。
            stop: 停止词。
            run_manager: LangChain callback manager。

        输出:
            ChatResult。

        系统定位:
            所有 invoke/stream 最终经过此方法。

        可扩展性:
            可在此注入 token 统计回调、链路追踪 span。
        """
        messages = self._preprocess_messages(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _create_chat_result(self, response, generation_info=None) -> ChatResult:
        """解析 API 响应：reasoning 合并、XML/JSON tool_call 提取。

        输入:
            response: OpenAI 兼容 API 原始响应。
            generation_info: LangChain 生成元信息。

        输出:
            ChatResult，AIMessage 可能含 tool_calls。

        系统定位:
            兼容非 OpenAI 标准 tool_calls 格式的关键适配点。

        可扩展性:
            新增模型格式时在 regex/JSON 分支扩展。
        """
        result = super()._create_chat_result(response, generation_info)
        try:
            dumped = response if isinstance(response, dict) else response.model_dump(exclude={"choices": {"__all__": {"message": {"parsed"}}}})
            for i, choice in enumerate(dumped.get("choices") or []):
                if i >= len(result.generations):
                    break
                lc_msg = result.generations[i].message
                msg = choice.get("message") or {}
                ak = lc_msg.additional_kwargs
                # 优先处理 reasoning 内容
                merged = ""
                for key in ("reasoning_content", "reasoning_details", "reasoning"):
                    merged = assistant_text(msg.get(key))
                    if merged:
                        break
                if merged:
                    ak.setdefault("reasoning_content", merged)
                raw_content = assistant_text(msg.get("content"))
                if not raw_content and merged:
                    lc_msg.content = merged
                elif raw_content:
                    lc_msg.content = raw_content

                content_text = lc_msg.content if isinstance(lc_msg.content, str) else ""

                # 匹配 <tool_call>...</tool_call> 块
                pattern = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>', re.DOTALL)
                matches = pattern.findall(content_text)
                if matches:
                    tool_calls = []
                    for idx, match in enumerate(matches):
                        # 先尝试 JSON 解析（兼容旧格式）
                        try:
                            call_data = json.loads(match)
                            tool_calls.append({
                                "id": f"call_{idx}",
                                "type": "function",
                                "function": {
                                    "name": call_data.get("name", ""),
                                    "arguments": json.dumps(call_data.get("arguments", {}))
                                }
                            })
                            continue   # 解析成功，跳过 XML 尝试
                        except json.JSONDecodeError:
                            pass

                        # 再尝试 XML 解析
                        func_match = re.search(r'<function=(\w+)>', match)
                        if not func_match:
                            continue
                        func_name = func_match.group(1)

                        params = {}
                        for param_match in re.finditer(r'<parameter=(\w+)>\s*(.*?)\s*</parameter>', match, re.DOTALL):
                            key = param_match.group(1)
                            value = param_match.group(2).strip()
                            # 可选：智能类型转换，先保持简单
                            params[key] = value

                        tool_calls.append({
                            "id": f"call_{idx}",
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": json.dumps(params)
                            }
                        })

                    if tool_calls:
                        ak["tool_calls"] = tool_calls
                        # 构造 LangChain 的 ToolCall 对象列表
                        lc_tool_calls = []
                        for idx, tc in enumerate(tool_calls):
                            lc_tool_calls.append(
                                ToolCall(
                                    id=tc["id"],
                                    name=tc["function"]["name"],
                                    args=json.loads(tc["function"]["arguments"])
                                )
                            )
                        lc_msg.tool_calls = lc_tool_calls
                        # 清理内容中的 XML/JSON 工具调用痕迹
                        cleaned = pattern.sub("", content_text).strip()
                        lc_msg.content = cleaned if cleaned else ""
        except Exception:
            pass
        return result

    def describe_image(self, image_path_or_url: str, prompt: str = "请详细描述这张图片的内容。") -> str:
        """Vision 便捷接口：单张图片 + 提示词 -> 文本描述。

        输入:
            image_path_or_url: 路径或 http(s)/data URL。
            prompt: 用户侧提示。

        输出:
            模型描述文本。

        系统定位:
            工具或测试脚本直接调用，不经 LangGraph。

        可扩展性:
            可返回结构化 JSON（物体列表等）。
        """
        messages = [
            SystemMessage(content=[{"type": "text", "text": VISION_SYSTEM_PROMPT}]),
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": image_path_or_url}},
                {"type": "text", "text": prompt}
            ])
        ]
        result = self.invoke(messages)
        return result.content

    def describe_image_bytes(self, image_bytes: bytes, prompt: str = "请详细描述这张图片的内容。") -> str:
        """Vision 便捷接口：内存图片字节 -> 文本描述。

        输入:
            image_bytes: 图片二进制。
            prompt: 提示词。

        输出:
            描述文本；处理失败返回固定错误文案。

        系统定位:
            截屏、工具 artifact 等无路径场景。

        可扩展性:
            与 describe_image 共用 VISION_SYSTEM_PROMPT。
        """
        img_part = image_bytes_to_openai_image_url_part(image_bytes)
        if img_part is None:
            return "图片处理失败"
        messages = [
            SystemMessage(content=[{"type": "text", "text": VISION_SYSTEM_PROMPT}]),
            HumanMessage(content=[img_part, {"type": "text", "text": prompt}])
        ]
        result = self.invoke(messages)
        return result.content

llm = ChatQwen()

def get_default_llm():
    """获取默认 LLM 实例，优先使用主 Agent 配置的模型。

    系统定位:
        skill_router、GUI tool 等内部组件需要一个"兜底 LLM"来做推理。
        该函数会先尝试获取主 Agent Runtime 的 LLM（由 agent_config.json 驱动），
        若获取失败（模块未加载/主 Runtime 不存在）则回退到 models[0] 的默认 ChatQwen。

    输出:
        ChatQwen 实例。
    """
    try:
        from agent.agents.agent_runtime import get_main_agent_runtime
        main_rt = get_main_agent_runtime()
        if main_rt and main_rt.llm:
            return main_rt.llm
    except Exception:
        pass
    return llm


def reload_llm() -> None:
    """热重载：重新从环境变量创建 LLM 实例。"""
    global llm
    llm = ChatQwen()

