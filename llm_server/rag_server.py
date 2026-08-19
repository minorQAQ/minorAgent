import os
import argparse
import torch
import torch.nn.functional as F
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List
from modelscope import AutoTokenizer, AutoModel, AutoModelForCausalLM
from transformers import BitsAndBytesConfig

# 自动获取脚本所在目录作为基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 在 load_models() 里添加量化配置
quantization_config = BitsAndBytesConfig(load_in_8bit=True)
# ===================== 模型路径 =====================
EMBED_MODEL_PATH = os.path.join(BASE_DIR, "models", "Qwen", "Qwen3-Embedding-0___6B")
RERANK_MODEL_PATH = os.path.join(BASE_DIR, "models", "Qwen", "Qwen3-Reranker-4B")

# ===================== 服务参数（--api-key / --model-name）=====================
# api_key 为空：不校验（任意值放行）；model_name 为空：不校验请求 model 字段
_model_args: dict = {"api_key": "", "model_name": ""}

def check_api_key(request: Request):
    """校验请求 API Key：服务未配置 key（空）时放行任意值；否则校验 Authorization / X-API-Key。

    校验失败抛出 HTTP 401。
    """
    api_key = _model_args.get("api_key", "")
    if not api_key:
        return
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        provided = header[len("Bearer "):].strip()
    else:
        provided = request.headers.get("X-API-Key", "").strip()
    if provided != api_key:
        raise HTTPException(status_code=401, detail="API Key 无效或缺失")

def check_model_name(model: str | None):
    """校验请求 modelname：服务未配置模型名（空）时放行任意值；否则要求请求 model 匹配。

    校验失败抛出 HTTP 400。
    """
    model_name = _model_args.get("model_name", "")
    if not model_name:
        return
    if str(model or "").strip() != model_name:
        raise HTTPException(status_code=400, detail=f"模型名不匹配: 期望 '{model_name}'，收到 '{model or ''}'")

# ===================== 初始化 FastAPI =====================
app = FastAPI(title="RAG Backend with 8-bit Qwen3 Models")

# ===================== 全局变量（模型、分词器） =====================
embed_tokenizer = None
embed_model = None
rerank_tokenizer = None
rerank_model = None

# ===================== 工具函数 =====================
def last_token_pool(last_hidden_states, attention_mask):
    left_padding = (attention_mask[:, -1].sum() == attention_mask.shape[0])
    if left_padding:
        return last_hidden_states[:, -1]
    else:
        sequence_lengths = attention_mask.sum(dim=1) - 1
        batch_size = last_hidden_states.shape[0]
        return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]

def get_detailed_instruct(task_description: str, query: str) -> str:
    return f'Instruct: {task_description}\nQuery:{query}'

def format_rerank_instruction(instruction, query, doc):
    if instruction is None:
        instruction = 'Given a web search query, retrieve relevant passages that answer the query'
    return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}"

# ===================== 启动时加载模型（8‑bit） =====================
@app.on_event("startup")
def load_models():
    global embed_tokenizer, embed_model, rerank_tokenizer, rerank_model

    # ---------- 加载 Embedding 模型 ----------
    print("Loading Embedding model with 16-bit quantization...")
    embed_tokenizer = AutoTokenizer.from_pretrained(EMBED_MODEL_PATH, padding_side='left')
    embed_model = AutoModel.from_pretrained(
        EMBED_MODEL_PATH,
        #load_in_8bit=True,                # 启用 8-bit 量化
        device_map="auto",                # 自动分配到 GPU
        dtype=torch.float16         # 计算精度保持 fp16
    )
    embed_model.eval()
    print("Embedding model loaded.")

    # ---------- 加载 Reranker 模型 ----------
    print("Loading Reranker model with 8-bit quantization...")
    rerank_tokenizer = AutoTokenizer.from_pretrained(RERANK_MODEL_PATH, padding_side='left')
    rerank_model = AutoModelForCausalLM.from_pretrained(
        RERANK_MODEL_PATH,
        quantization_config=quantization_config,
        device_map="auto",
        dtype=torch.float16
    )
    rerank_model.eval()

    # 预计算 Reranker 所需的固定 tokens
    global token_true_id, token_false_id, prefix_tokens, suffix_tokens, max_rerank_length
    token_false_id = rerank_tokenizer.convert_tokens_to_ids("no")
    token_true_id  = rerank_tokenizer.convert_tokens_to_ids("yes")
    max_rerank_length = 32768

    prefix = "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n"
    suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    prefix_tokens = rerank_tokenizer.encode(prefix, add_special_tokens=False)
    suffix_tokens = rerank_tokenizer.encode(suffix, add_special_tokens=False)

    print("Reranker model loaded.")

# ===================== API 请求体定义 =====================
class EmbedRequest(BaseModel):
    task_description: str = "Given a web search query, retrieve relevant passages that answer the query"
    model: str | None = None            # 可选，服务配置了 --model-name 时须匹配
    queries: List[str]
    documents: List[str]           # 可选，若只查询文本可只传 queries

class EmbedResponse(BaseModel):
    query_embeddings: List[List[float]]
    doc_embeddings: List[List[float]]   # 当传入 documents 时返回

class RerankRequest(BaseModel):
    task_description: str = "Given a web search query, retrieve relevant passages that answer the query"
    model: str | None = None            # 可选，服务配置了 --model-name 时须匹配
    query: str
    documents: List[str]

class RerankResponse(BaseModel):
    scores: List[float]

# ===================== Embedding 端点 =====================
@app.post("/embed", response_model=EmbedResponse)
async def get_embeddings(req: EmbedRequest, request: Request):
    check_api_key(request)
    check_model_name(req.model)
    # 为 query 加上指令，document 不加指令
    instructed_queries = [get_detailed_instruct(req.task_description, q) for q in req.queries]
    # 所有文本拼成一个 batch：先是 queries，后是 documents（如果有）
    input_texts = instructed_queries + req.documents

    # 分词
    batch_dict = embed_tokenizer(
        input_texts,
        padding=True,
        truncation=True,
        return_tensors="pt",
    ).to(embed_model.device)

    with torch.no_grad():
        outputs = embed_model(**batch_dict)
        embeddings = last_token_pool(outputs.last_hidden_state, batch_dict['attention_mask'])
        embeddings = F.normalize(embeddings, p=2, dim=1)

    # 拆分 query 和 document 的嵌入
    nq = len(instructed_queries)
    query_embs = embeddings[:nq].cpu().tolist()
    doc_embs = embeddings[nq:].cpu().tolist() if req.documents else []

    return EmbedResponse(query_embeddings=query_embs, doc_embeddings=doc_embs)

# ===================== Reranker 端点 =====================
@app.post("/rerank", response_model=RerankResponse)
async def rerank_documents(req: RerankRequest, request: Request):
    check_api_key(request)
    check_model_name(req.model)
    # 构造带格式的输入对
    pairs = [
        format_rerank_instruction(req.task_description, req.query, doc)
        for doc in req.documents
    ]

    # 处理输入，添加 prefix/suffix tokens 并 pad
    inputs = rerank_tokenizer(
        pairs,
        padding=False,
        truncation='longest_first',
        return_attention_mask=False,
        max_length=max_rerank_length - len(prefix_tokens) - len(suffix_tokens)
    )
    for i, ele in enumerate(inputs['input_ids']):
        inputs['input_ids'][i] = prefix_tokens + ele + suffix_tokens
    inputs = rerank_tokenizer.pad(inputs, padding=True, return_tensors="pt", max_length=max_rerank_length)
    inputs = {k: v.to(rerank_model.device) for k, v in inputs.items()}

    with torch.no_grad():
        batch_scores = rerank_model(**inputs).logits[:, -1, :]
        true_vector = batch_scores[:, token_true_id]
        false_vector = batch_scores[:, token_false_id]
        scores = torch.stack([false_vector, true_vector], dim=1)
        scores = torch.nn.functional.log_softmax(scores, dim=1)
        scores = scores[:, 1].exp().cpu().tolist()

    return RerankResponse(scores=scores)

# ===================== 健康检查 =====================
@app.get("/health")
def health():
    return {"status": "ok"}


# ======================== 启动入口 ========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen3 RAG Server (Embedding + Reranker)")
    parser.add_argument("--port", type=int, default=8903, help="服务端口（默认 8903）")
    parser.add_argument("--model-name", type=str, default="Qwen3-Embedding-0.6B",
                        help="服务模型名（校验请求 body.model；默认 Qwen3-Embedding-0.6B，留空则不校验）")
    parser.add_argument("--api-key", type=str, default="",
                        help="API Key（校验 Authorization: Bearer <key> 或 X-API-Key；默认空=任意值放行）")
    args = parser.parse_args()

    _model_args["api_key"] = args.api_key
    _model_args["model_name"] = args.model_name

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
