"""skill_router 工具：根据用户 query 调用大模型智能匹配并返回相关 skill 指南。

系统定位:
    作为 Agent 工具集的一员，当用户任务可能匹配已有 skill 时，
    调用此工具获取对应的操作指南，指引 Agent 更高效地完成任务。

调用方式:
    skill_router(query="用户原始问题或任务描述")
"""
from __future__ import annotations

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from agent.skills import load_all_skill_metas, load_all_skill_contents, SKILLS_DIR
from agent.memory.system_prompt import (
    SKILL_ROUTER_PROMPT,
    SKILL_ROUTER_NO_MATCH_MSG,
    SKILL_ROUTER_EMPTY_MSG,
    SKILL_ROUTER_NO_QUERY_MSG,
    SKILL_ROUTER_NO_SKILLS_MSG,
)


class SkillRouter(BaseTool):
    """Skill 路由工具：输入 query，调用大模型筛选匹配的 skill 并返回其指南全文。

    工作流程:
        1. 收集所有已安装 skill 的 skill.json 元信息
        2. 构建 prompt，将所有 skill 摘要 + query 送给大模型做语义匹配
        3. 解析大模型返回的 skill name 列表
        4. 按 name 加载对应 skill.md 并返回
    """

    name: str = "skill_router"
    description: str = (
        "Skill 路由工具。根据用户的 query（问题或任务描述），从已安装的 skill 中智能匹配"
        "最相关的操作指南，并返回指南全文。\n"
        "参数说明：\n"
        "- query: 用户的原始问题或任务描述，用于匹配 skill。\n"
        "使用场景：\n"
        "- 当用户任务可能已有对应的操作指南时，调用此工具获取指南。\n"
        "- 当不确定如何完成某项任务时，先查是否有相关 skill。\n"
        "调用后，你会获得匹配 skill 的完整指南内容，请据此执行任务。"
    )

    args_schema: type[BaseModel] = create_model(
        "SkillRouterInput",
        query=(str, Field(description="用户的问题或任务描述，用于匹配相关 skill。")),
    )

    def _run(self, query: str) -> str:
        if not query or not query.strip():
            return SKILL_ROUTER_NO_QUERY_MSG

        metas = load_all_skill_metas()
        contents = load_all_skill_contents()

        if not metas:
            return SKILL_ROUTER_NO_SKILLS_MSG

        # 构建 skill 摘要列表（仅含 JSON 中的元信息，不含 skill.md）
        skill_lines = []
        for name, meta in metas.items():
            tags_str = ", ".join(meta.get("tags", []))
            skill_lines.append(
                f"- name: {name}\n"
                f"  description: {meta.get('description', '')}\n"
                f"  tags: {tags_str}"
            )
        skills_block = "\n".join(skill_lines)

        prompt = SKILL_ROUTER_PROMPT.format(query=query, skills_block=skills_block)

        matched_names = self._call_llm(prompt)

        if not matched_names:
            # LLM 匹配失败 → 回退到关键词匹配
            matched_names = self._keyword_match(query, metas)

        if not matched_names:
            return SKILL_ROUTER_NO_MATCH_MSG

        # 按匹配到的 name 加载对应 skill.md
        skill_dir_str = str(SKILLS_DIR.resolve()).replace("\\", "/")
        parts = []
        for name in matched_names:
            if name not in contents:
                continue
            meta = metas.get(name, {})
            content = contents[name]
            # 将 {SKILL_DIR} 替换为实际 skills 目录路径
            content = content.replace("{SKILL_DIR}", skill_dir_str + "/" + name)
            parts.append(
                f"## Skill: {name}\n"
                f"描述: {meta.get('description', '')}\n\n"
                f"{content}\n"
            )

        if not parts:
            return SKILL_ROUTER_EMPTY_MSG

        header = f"skill_router: 从 {len(matched_names)} 个 skill 中匹配到以下指南：\n\n"

        return header + "\n---\n".join(parts)

    def _call_llm(self, prompt: str) -> list[str] | None:
        """调用大模型解析 prompt，返回匹配的 skill name 列表。

        优先使用主 Agent 配置的 LLM（get_default_llm），回退到 models[0] 兜底。

        输出:
            匹配的 name 列表；解析失败或模型返回 NONE 时返回 None。
        """
        from agent.core.llm import get_default_llm
        from langchain_core.messages import HumanMessage

        try:
            response = get_default_llm().invoke([HumanMessage(content=prompt)])
            text = response.content if isinstance(response.content, str) else str(response.content)
            text = text.strip()
        except Exception as e:
            print(f"[SkillRouter] LLM 调用失败: {e}，回退到关键词匹配")
            return None

        if not text or text.upper() == "NONE":
            return None

        names = [line.strip() for line in text.split("\n") if line.strip()]
        return names if names else None

    def _keyword_match(self, query: str, metas: dict) -> list[str] | None:
        """关键词回退匹配：当 LLM 不可用时，基于 query 与 skill 的 name/tags/description
        做简单的关键词交集匹配。

        输出:
            匹配的 name 列表（按标签命中数降序）；无匹配返回 None。
        """
        import re
        query_lower = query.lower()
        scored = []

        for name, meta in metas.items():
            score = 0
            # 检查 skill name 是否直接出现在 query 中
            if name.lower() in query_lower:
                score += 3
            # 检查 tags
            for tag in meta.get("tags", []):
                if tag.lower() in query_lower:
                    score += 2
            # 检查 description 中的词是否出现在 query 中
            desc = meta.get("description", "")
            desc_words = set(re.findall(r'[\u4e00-\u9fff]+|\w+', desc.lower()))
            query_words = set(re.findall(r'[\u4e00-\u9fff]+|\w+', query_lower))
            common = desc_words & query_words
            score += len(common)

            if score > 0:
                scored.append((name, score))

        if not scored:
            return None

        # 按分数降序，返回 top 3
        scored.sort(key=lambda x: x[1], reverse=True)
        print(f"[SkillRouter] 关键词匹配结果: {[n for n, _ in scored[:3]]}")
        return [name for name, _ in scored[:3]]

    async def _arun(self, query: str) -> str:
        import asyncio
        return await asyncio.to_thread(self._run, query)
