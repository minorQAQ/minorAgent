# agent/tools/tool_rag.py
from __future__ import annotations

import asyncio
import json
import re
import hashlib
import os
from datetime import datetime
from typing import List, Optional, Literal, Union, Tuple

import chromadb
import requests
from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.utils.env_utils import RAG_BASE_URL, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP
from agent.utils.agent_utils import Documents_process
from agent.core.llm import llm

# ---------- 前置函数----------
ENDING_PUNCTUATION = set(".!?。！？…\"'”’）;:；：…")


def has_ending_punctuation(text: str) -> bool:
    """判断文本是否以句末标点结尾（空文本视为已结束）。"""
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] in ENDING_PUNCTUATION


def pre_process(text_content: str, list_image_byte: List[bytes]) -> Tuple[str, List[bytes]]:
    """合并图文行并为 <image> 占位符生成 Vision 描述，供 RAG 入库前预处理。"""
    lines = text_content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 情形1：当前行是 <image>...</image>
        if stripped.startswith('<image>') and stripped.endswith('</image>'):
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.strip()
                # 如果下一行不是 <image> 且没有结束标点，合并
                if (next_stripped and
                        not has_ending_punctuation(next_stripped) and
                        not next_stripped.startswith('<image>')):
                    merged = f'<image>{next_stripped}</image>'
                    new_lines.append(merged)
                    i += 2
                    continue
            new_lines.append(line)
            i += 1
        # 情形2：当前行是普通文本，没有结束标点
        elif (stripped and
              not has_ending_punctuation(stripped) and
              not stripped.startswith('<image>')):
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.strip()
                # 如果下一行是 <image>...</image>，合并
                if next_stripped.startswith('<image>') and next_stripped.endswith('</image>'):
                    merged = f'<image>{stripped}</image>'
                    new_lines.append(merged)
                    i += 2
                    continue
            new_lines.append(line)
            i += 1
        else:
            new_lines.append(line)
            i += 1

    merged_text = '\n'.join(new_lines)

    # 替换 <image> 内容：插入图片描述
    pattern = re.compile(r'<image>(.*?)</image>', re.DOTALL)
    matches = list(pattern.finditer(merged_text))
    result_parts = []
    last_end = 0
    for idx, match in enumerate(matches):
        result_parts.append(merged_text[last_end:match.start()])
        inner = match.group(1).strip()
        if idx < len(list_image_byte):
            try:
                description = llm.describe_image_bytes(
                    list_image_byte[idx],
                    prompt="""你是一名专业的图像理解助手,现在需要你为即将加入向量库的图片做文字分析以便于用户更迅速、更高效、较准确地查询到此图片。
                            首先请用客观、准确的中文描述用户提供的图片，覆盖主要物体、场景、人物动作、界面元素、图表数据与清晰可读的文字；
                            涉及到你认识的具体品牌、时间、地点、人物、影视剧、物品等特定内容时请直接命名说明；看不清的内容请如实说明，不要臆测。
                            其次请为此图片设想出3到5个可能会问及的客观问题,放在末尾处。"""
                )
            except Exception:
                description = "图片描述生成失败"
        else:
            description = ""
        if inner:
            new_inner = f"{inner}\n{description}" if description else inner
        else:
            new_inner = description
        result_parts.append(f"<image>{new_inner}</image>")
        last_end = match.end()
    result_parts.append(merged_text[last_end:])
    final_text = ''.join(result_parts)
    return final_text, list_image_byte


# ---------- 存储路径、客户端 ----------
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), '..', 'memory', 'chroma_rag_db')
# 统一的图片存储目录
IMAGE_STORE_DIR = os.path.join(CHROMA_PERSIST_DIR, "images")

_chroma_client = None
_global_collection = None
GLOBAL_COLLECTION_NAME = "rag_global"


def get_chroma_client():
    """获取或懒初始化 Chroma 持久化客户端单例。"""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return _chroma_client


def get_global_collection():
    """获取或创建全局 RAG 向量集合（cosine 空间）。"""
    global _global_collection
    if _global_collection is None:
        client = get_chroma_client()
        try:
            _global_collection = client.get_collection(
                name=GLOBAL_COLLECTION_NAME, embedding_function=None
            )
        except Exception:
            _global_collection = client.create_collection(
                name=GLOBAL_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
    return _global_collection


def embed_texts(queries: List[str], documents: List[str] = None) -> tuple:
    """调用 RAG 嵌入服务，返回 (query_embeddings, doc_embeddings)。"""
    payload = {
        "task_description": "Given a web search query, retrieve relevant passages that answer the query",
        "queries": queries,
        "documents": documents or []
    }
    try:
        resp = requests.post(f"{RAG_BASE_URL}/embed", json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["query_embeddings"], data.get("doc_embeddings", [])
    except Exception as e:
        raise RuntimeError(f"Embedding 请求失败: {e}")


def rerank_documents(query: str, documents: List[str]) -> List[float]:
    """调用 RAG 重排序服务，返回与 documents 对齐的相关度分数列表。"""
    payload = {
        "task_description": "Given a web search query, retrieve relevant passages that answer the query",
        "query": query,
        "documents": documents
    }
    try:
        resp = requests.post(f"{RAG_BASE_URL}/rerank", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["scores"]
    except Exception as e:
        raise RuntimeError(f"Reranker 请求失败: {e}")


def split_into_chunks(input_data) -> List[dict]:
    """将文本/图文元组切分为 chunk 列表，图片与表格块标记为 protected。"""
    if isinstance(input_data, str):
        text = input_data
        image_bytes_list = []
    elif isinstance(input_data, tuple) and len(input_data) == 2:
        text, image_bytes_list = input_data
    else:
        text = ""
        image_bytes_list = []

    pattern = re.compile(r'(<image>[\s\S]*?</image>|<table>[\s\S]*?</table>)')
    parts = pattern.split(text)
    all_chunks = []
    image_index = 0
    for part in parts:
        if not part:
            continue
        if (part.startswith('<image>') and part.endswith('</image>')) or \
                (part.startswith('<table>') and part.endswith('</table>')):
            chunk_info = {"content": part, "is_protected": True}
            if part.startswith('<image>') and image_index < len(image_bytes_list):
                chunk_info["image_bytes"] = image_bytes_list[image_index]
                image_index += 1
            all_chunks.append(chunk_info)
        else:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=RAG_CHUNK_SIZE,
                chunk_overlap=RAG_CHUNK_OVERLAP,
                separators=["\n\n", "\n", "。", "！", "？", "；", "，", ".", "!", "?", ";", ",", " ", ""]
            )
            split_parts = splitter.split_text(part)
            all_chunks.extend([{"content": p, "is_protected": False} for p in split_parts])
    return all_chunks


# ---------- RAGTool ----------
class RAGTool(BaseTool):
    name: str = "rag_tool"
    description: str = (
        "个人知识库管理工具，支持增删查及列出所有来源操作。\n"
        "参数说明：\n"
        "- action_type: 操作类型，必填。可选：'query'(查询), 'add_document'(添加文档), 'clear'(清除), 'list_sources'(列出所有来源)。\n"
        "- content: 查询内容(用于query) 或 直接文本内容(用于add_document，与source二选一)。\n"
        "- source: 文件路径(用于add_document，与content二选一)。\n"
        "- filter: 过滤条件(用于query或clear)。\n"
        "使用示例：\n"
        "- 查询：action_type='query', content='用户问题'\n"
        "- 添加文本：action_type='add_document', content='知识文本'\n"
        "- 添加文件：action_type='add_document', source='/path/to/file.pdf'\n"
        "- 清除：action_type='clear', filter='某个来源'\n"
        "- 列出所有来源：action_type='list_sources'"
    )

    args_schema: type[BaseModel] = create_model(
        "RAGInput",
        action_type=(Literal["query", "add_document", "clear", "list_sources"], Field(..., description="操作类型")),
        content=(Optional[str], Field(None, description="查询内容或直接添加的文本内容")),
        source=(Optional[Union[str, List[str]]], Field(None, description="文件路径（字符串或列表），用于添加文档")),
        filter=(Optional[Union[str, List[str]]], Field(None, description="过滤条件，用于查询或清除"))
    )

    # ========== 关键改动：声明返回内容和 artifact ==========
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    def _run(
        self,
        action_type: str,
        content: Optional[str] = None,
        source: Optional[Union[str, List[str]]] = None,
        filter: Optional[Union[str, List[str]]] = None
    ) -> Tuple[str, Union[dict, list]]:
        """统一返回 (text, artifact) 元组"""
        try:
            if action_type == "query":
                return self._handle_query(content, filter)
            elif action_type == "add_document":
                return self._handle_add(content, source)
            elif action_type == "clear":
                return self._handle_clear(filter)
            elif action_type == "list_sources":
                return self._handle_list_sources()
            else:
                return f"未知操作: {action_type}", {}
        except Exception as e:
            return f"RAG 工具执行出错: {str(e)}", {}

    async def _arun(self, **kwargs) -> Tuple[str, Union[dict, list]]:
        return await asyncio.to_thread(self._run, **kwargs)

    def _get_batch_chunks(self, coll, batch_id: str) -> dict:
        """按 batch_id 拉取同批次全部 chunk，以 chunk_index 为键索引。"""
        res = coll.get(where={"batch_id": batch_id})
        batch_chunks = {}
        if res and res["metadatas"] and res["documents"]:
            for meta, doc in zip(res["metadatas"], res["documents"]):
                chunk_idx = meta.get("chunk_index")
                if chunk_idx is not None:
                    batch_chunks[chunk_idx] = {
                        "content": doc,
                        "is_image": meta.get("is_image", False),
                        "is_table": meta.get("is_table", False),
                        "is_protected": meta.get("is_protected", False),
                        "image_path": meta.get("image_path", "")
                    }
        return batch_chunks

    # ---------- 查询（返回 artifact）----------
    def _handle_query(self, query: str, filter: Optional[Union[str, List[str]]]) -> Tuple[str, list]:
        """向量检索 + rerank，返回拼接文本与图片 artifact 列表。"""
        if not query:
            return "查询内容不能为空。", []

        # 1. 获取查询向量
        q_embs, _ = embed_texts(queries=[query])
        query_vector = q_embs[0]

        # 2. 检索
        coll = get_global_collection()
        where = None
        if filter:
            if isinstance(filter, str):
                where = {"source": {"$contains": filter}}
            elif isinstance(filter, list) and len(filter) > 0:
                where = {"source": {"$contains": filter[0]}}

        res = coll.query(
            query_embeddings=[query_vector],
            n_results=10,
            where=where
        )

        if not res["ids"] or not res["ids"][0]:
            return "未在知识库中找到相关内容。", []

        ids = res["ids"][0]
        docs = res["documents"][0]
        metas = res["metadatas"][0]

        all_results = []
        seen = set()
        for i, d, m in zip(ids, docs, metas):
            if d not in seen:
                seen.add(d)
                all_results.append({"id": i, "document": d, "metadata": m})

        unique_results = all_results[:10]

        # 3. Reranker
        docs_for_rerank = [r["document"] for r in unique_results]
        scores = rerank_documents(query, docs_for_rerank)

        sorted_items = sorted(
            zip(unique_results, scores),
            key=lambda x: x[1],
            reverse=True
        )[:3]

        if not sorted_items:
            return "Reranker 未返回有效结果。", []

        outputs = []
        all_image_bytes = []  # 收集图片字节

        for item, score in sorted_items:
            meta = item["metadata"]
            is_image = meta.get("is_image", False)
            is_table = meta.get("is_table", False)
            batch_id = meta.get("batch_id")
            chunk_index = meta.get("chunk_index")

            batch_chunks = self._get_batch_chunks(coll, batch_id) if batch_id else {}

            # 拼接上下文（前、当前、后）
            context_parts = []
            for idx_offset in [-1, 0, 1]:
                current_idx = chunk_index + idx_offset
                if current_idx in batch_chunks:
                    chunk = batch_chunks[current_idx]
                    context_parts.append(chunk["content"])
                    # 如果是图片块，从文件读取字节
                    if chunk["is_image"] and chunk.get("image_path"):
                        img_path = chunk["image_path"]
                        if os.path.isfile(img_path):
                            try:
                                with open(img_path, "rb") as f:
                                    all_image_bytes.append(f.read())
                            except Exception:
                                pass

            context_text = "\n\n".join(context_parts)

            # 格式化文本输出
            if is_image:
                outputs.append(
                    f"【图片数据 - 来源：{meta.get('source', '未知来源')}（相关度 {score:.3f}）】\n[图片数据已获取]")
            elif is_table:
                outputs.append(
                    f"【表格数据 - 来源：{meta.get('source', '未知来源')}（相关度 {score:.3f}）】\n{context_text}")
            else:
                outputs.append(
                    f"【文本数据 - 来源：{meta.get('source', '未知来源')}（相关度 {score:.3f}）】\n{context_text}")

        final_text = "\n\n".join(outputs)

        # 去重图片字节，并按每个图片单独打包成一个 dict，放入 artifact 列表
        unique_image_bytes = list(dict.fromkeys(all_image_bytes))  # 保持顺序去重
        artifact = [{"image_bytes": img_bytes} for img_bytes in unique_image_bytes]

        return final_text, artifact

    # ---------- 添加文档 ----------
    def _handle_add(self, content: Optional[str], source: Optional[Union[str, List[str]]]) -> Tuple[str, dict]:
        """解析文本或文件、分块嵌入后写入 Chroma 全局集合。"""
        if not content and not source:
            return "必须提供 content 或 source。", {}
        if content and source:
            return "content 和 source 只能提供一个。", {}

        # 统一 batch_id，整个添加操作共享
        timestamp = datetime.now().isoformat()
        batch_id = hashlib.md5(timestamp.encode()).hexdigest()

        # 收集所有文档的 chunk 信息
        all_chunks_meta = []  # (text, src_desc, is_protected, image_path)
        file_errors = []

        # 处理直接文本输入
        if content:
            processed_text, processed_images = pre_process(content, [])
            chunk_infos = split_into_chunks((processed_text, processed_images))
            base_dir = IMAGE_STORE_DIR
            base_name = f"direct_{batch_id[:8]}"
            source_desc_prefix = "直接输入"

            image_idx = 0
            for idx, chunk_info in enumerate(chunk_infos):
                text = chunk_info["content"]
                img_bytes = chunk_info.get("image_bytes")
                is_protected = chunk_info.get("is_protected", False)
                src_desc = f"{source_desc_prefix} (chunk {idx + 1}/{len(chunk_infos)})"

                image_path = ""
                if text.startswith('<image>') and text.endswith('</image>') and img_bytes is not None:
                    os.makedirs(base_dir, exist_ok=True)
                    image_path = os.path.join(base_dir, f"{base_name}_image{image_idx}.jpg")
                    try:
                        with open(image_path, "wb") as f:
                            f.write(img_bytes)
                    except Exception as e:
                        return f"图片保存失败: {e}", {}
                    image_idx += 1

                all_chunks_meta.append((text, src_desc, is_protected, image_path))

        # 处理文件输入（字符串或列表）
        elif source:
            # 统一为列表处理
            source_files = [source] if isinstance(source, str) else source
            for file_path in source_files:
                if not os.path.isfile(file_path):
                    file_errors.append(f"文件不存在: {file_path}")
                    continue

                try:
                    raw_text, image_list = Documents_process.process(file_path)
                except Exception as e:
                    file_errors.append(f"处理文件失败 {file_path}: {e}")
                    continue

                processed_text, processed_images = pre_process(raw_text, image_list)
                chunk_infos = split_into_chunks((processed_text, processed_images))
                if not chunk_infos:
                    file_errors.append(f"文件内容为空: {file_path}")
                    continue

                base_dir = os.path.dirname(file_path)
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                source_desc_prefix = os.path.basename(file_path)

                image_idx = 0
                for idx, chunk_info in enumerate(chunk_infos):
                    text = chunk_info["content"]
                    img_bytes = chunk_info.get("image_bytes")
                    is_protected = chunk_info.get("is_protected", False)
                    src_desc = f"{source_desc_prefix} (chunk {idx + 1}/{len(chunk_infos)})"

                    image_path = ""
                    if text.startswith('<image>') and text.endswith('</image>') and img_bytes is not None:
                        os.makedirs(IMAGE_STORE_DIR, exist_ok=True)
                        image_path = os.path.join(IMAGE_STORE_DIR, f"{base_name}_image{image_idx}.jpg")
                        try:
                            with open(image_path, "wb") as f:
                                f.write(img_bytes)
                        except Exception as e:
                            file_errors.append(f"图片保存失败 ({file_path}): {e}")
                            # 即便图片保存失败，文本块仍可入库，继续执行
                        image_idx += 1

                    all_chunks_meta.append((text, src_desc, is_protected, image_path))

        if not all_chunks_meta:
            error_msg = "没有可用内容添加到知识库。"
            if file_errors:
                error_msg += " 错误详情: " + "; ".join(file_errors)
            return error_msg, {}

        # 统一写入 Chroma：分配连续 chunk_index
        total_chunks = len(all_chunks_meta)
        doc_texts = [m[0] for m in all_chunks_meta]
        _, doc_embs = embed_texts(queries=["dummy"], documents=doc_texts)

        coll = get_global_collection()
        ids, embeddings, metadatas, documents = [], [], [], []

        for idx, (text, src_desc, is_protected, image_path) in enumerate(all_chunks_meta):
            uid = hashlib.md5(f"{timestamp}_{text[:80]}_{idx}".encode()).hexdigest()
            ids.append(uid)
            embeddings.append(doc_embs[idx])

            metadata = {
                "source": src_desc,
                "timestamp": timestamp,
                "batch_id": batch_id,
                "chunk_index": idx,  # 全局连续索引
                "total_chunks": total_chunks,
                "is_image": text.startswith('<image>') and text.endswith('</image>'),
                "is_table": text.startswith('<table>') and text.endswith('</table>'),
                "is_protected": is_protected
            }
            if image_path:
                metadata["image_path"] = image_path

            metadatas.append(metadata)
            documents.append(text)

        coll.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)

        result_msg = f"成功添加 {total_chunks} 条知识块到全局知识库。"
        if file_errors:
            result_msg += " 部分文件处理出错: " + "; ".join(file_errors)

        return result_msg, {}

    # ---------- 清除 ----------
    def _handle_clear(self, filter: Optional[Union[str, List[str]]]) -> Tuple[str, dict]:
        """按 source 过滤条件删除知识库记录及关联图片文件。"""
        if not filter:
            return "清除操作必须提供 filter 条件。", {}

        coll = get_global_collection()

        # 处理 filter：若为 JSON 字符串化的列表，尝试解析
        if isinstance(filter, str):
            try:
                parsed = json.loads(filter)
                if isinstance(parsed, list):
                    filter = parsed
            except (json.JSONDecodeError, ValueError):
                pass

        # 统一为列表
        if isinstance(filter, str):
            filter_terms = [filter]
        elif isinstance(filter, list):
            filter_terms = [f for f in filter if f]
        else:
            return "无效的过滤条件。", {}

        if not filter_terms:
            return "清除操作必须提供 filter 条件。", {}

        # 获取所有文档，在 Python 侧做子串匹配（避免 ChromaDB $contains 对中文的兼容问题）
        try:
            all_data = coll.get()
        except Exception as e:
            return f"获取知识库数据失败: {e}", {}

        if not all_data or not all_data["ids"]:
            return "知识库中暂无数据。", {}

        ids_to_delete = []
        for i, meta in enumerate(all_data.get("metadatas", [])):
            source = meta.get("source", "")
            # 任一 filter_terms 是 source 的子串即匹配
            if any(term in source for term in filter_terms):
                ids_to_delete.append(all_data["ids"][i])

        if not ids_to_delete:
            return f"未找到匹配 '{filter_terms[0] if len(filter_terms) == 1 else str(filter_terms)}' 的记录。", {}

        # 清理关联的图片文件
        for i, meta in enumerate(all_data.get("metadatas", [])):
            if all_data["ids"][i] in ids_to_delete:
                img_path = meta.get("image_path", "")
                if img_path and os.path.isfile(img_path):
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass

        coll.delete(ids=ids_to_delete)
        return f"已从全局知识库中删除 {len(ids_to_delete)} 条记录。", {}

    # ---------- 列出所有来源 ----------
    def _handle_list_sources(self) -> Tuple[str, dict]:
        """获取知识库中所有不重复的 source 信息"""
        coll = get_global_collection()
        try:
            all_data = coll.get()  # 获取全部文档的元数据
        except Exception as e:
            return f"获取知识库数据失败: {e}", {}

        if not all_data or not all_data["metadatas"]:
            return "知识库中暂无数据。", {}

        sources = set()
        for meta in all_data["metadatas"]:
            src = meta.get("source", "未知来源")
            sources.add(src)

        sorted_sources = sorted(sources)
        text = "知识库中的来源列表：\n" + "\n".join(f"- {s}" for s in sorted_sources)
        return text, {}