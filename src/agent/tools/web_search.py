from __future__ import annotations

import os
from typing import Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model


def _read_config(key: str, default: str = "") -> str:
    """从 env_config.json 读取配置项。"""
    try:
        from agent.core.config_manager import load_env_config
        config = load_env_config()
        if isinstance(config, dict):
            return str(config.get(key, default))
    except Exception:
        pass
    return os.environ.get(key, default)


class WebSearch(BaseTool):

    args_schema: type[BaseModel] = create_model("Input_type", query=(str, Field(description="搜索查询内容")))
    name: str = "web_search"
    description: str = (
        "一个网络搜索工具，可以根据用户的查询返回相关的搜索结果。"
        "仅当需要查询近期知识或已有知识无法解答需要联网查询时调用，其余任何情况严禁调用。"
    )

    def _get_engine_type(self) -> str:
        return _read_config("WEB_SEARCH_ENGINE", "tavily").strip().lower()

    def _get_api_key(self) -> str:
        return _read_config("WEB_SEARCH_API_KEY", "")

    def _search_tavily(self, query: str) -> list[dict]:
        from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
        wrapper = TavilySearchAPIWrapper(tavily_api_key=self._get_api_key())
        results = wrapper.results(query)
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")} for r in (results or [])]

    def _search_firecrawl(self, query: str) -> list[dict]:
        try:
            from firecrawl import FirecrawlApp
        except ImportError:
            return [{"title": "错误", "url": "", "content": "Firecrawl SDK 未安装。请运行: pip install firecrawl-py"}]
        app = FirecrawlApp(api_key=self._get_api_key())
        resp = app.search(query, params={"limit": 10})
        if isinstance(resp, dict) and "data" in resp:
            items = resp["data"]
        elif isinstance(resp, list):
            items = resp
        else:
            items = []
        return [{"title": r.get("title", r.get("metadata", {}).get("title", "")),
                 "url": r.get("url", r.get("metadata", {}).get("sourceURL", "")),
                 "content": r.get("description", r.get("markdown", r.get("content", "")))} for r in items]

    def _search_volcengine(self, query: str) -> list[dict]:
        # 火山引擎全网搜索 API (通过 HTTP 直调)
        # 文档: https://www.volcengine.com/docs/84313/1528527
        api_key = self._get_api_key()
        if not api_key:
            return [{"title": "配置错误", "url": "", "content": "火山引擎搜索需要 WEB_SEARCH_API_KEY 作为 API Key"}]
        try:
            import requests
        except ImportError:
            return [{"title": "错误", "url": "", "content": "requests 未安装"}]
        try:
            resp = requests.post(
                "https://open.volcengineapi.com",
                json={
                    "Action": "SearchWeb",
                    "Version": "2024-01-01",
                    "Query": query,
                    "Count": 10,
                },
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                },
                timeout=15,
            )
            data = resp.json()
            items = data.get("Response", {}).get("Result", {}).get("Items", [])
            return [{"title": r.get("Title", ""), "url": r.get("URL", ""), "content": r.get("Snippet", "")} for r in items]
        except Exception as e:
            return [{"title": "搜索失败", "url": "", "content": str(e)}]

    def _format_results(self, results: list[dict]) -> str:
        if not results:
            return "未找到相关搜索结果。"
        lines = []
        for i, item in enumerate(results, 1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            content = item.get("content", "")
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   URL: {url}")
            if content:
                lines.append(f"   {content}")
            lines.append("")
        return "\n".join(lines).strip()

    def _run(self, query: str) -> str:
        engine = self._get_engine_type()
        try:
            if engine == "tavily":
                results = self._search_tavily(query)
            elif engine == "firecrawl":
                results = self._search_firecrawl(query)
            elif engine == "volcengine":
                results = self._search_volcengine(query)
            else:
                return f"不支持的搜索引擎: {engine}。可选: tavily, firecrawl, volcengine"
            return self._format_results(results)
        except Exception as e:
            return f"执行网络搜索时出错: {str(e)}"

    async def _arun(self, query: str) -> str:
        return self._run(query)
