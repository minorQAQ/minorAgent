import requests
import json

# 服务地址
BASE_URL = "http://0.0.0.0:8903"

def print_separator(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def test_health():
    print_separator("Health Check")
    resp = requests.get(f"{BASE_URL}/health")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")

def test_embed():
    print_separator("Embedding Test")
    payload = {
        "task_description": "Given a web search query, retrieve relevant passages that answer the query",
        "queries": [
            "What is the capital of France?",
            "How to train a cat?"
        ],
        "documents": [
            "Paris is the capital of France.",
            "Cats can be trained using positive reinforcement."
        ]
    }
    print(">>> Request Body:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    resp = requests.post(f"{BASE_URL}/embed", json=payload)
    print(f"<<< Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        # 只打印向量长度和前面几个值，避免刷屏
        print(f"<<< Response Keys: {list(data.keys())}")
        print(f"Number of query embeddings: {len(data['query_embeddings'])}")
        print(f"Dimension of each query embedding: {len(data['query_embeddings'][0])}")
        print(f"First query embedding (first 5 values): {data['query_embeddings'][0][:5]}")
        print(f"Number of doc embeddings: {len(data['doc_embeddings'])}")
        if data['doc_embeddings']:
            print(f"Dimension of each doc embedding: {len(data['doc_embeddings'][0])}")
            print(f"First doc embedding (first 5 values): {data['doc_embeddings'][0][:5]}")
        else:
            print("No document embeddings returned.")
        # 如果需要完整输出，取消下面注释（会打印大量浮点数）
        # print(f"<<< Full Response:\n{json.dumps(data, indent=2)}")
    else:
        print(f"Error: {resp.text}")

def test_rerank():
    print_separator("Reranker Test")
    payload = {
        "task_description": "Given a web search query, retrieve relevant passages that answer the query",
        "query": "What is the capital of France?",
        "documents": [
            "Paris is the capital of France.",
            "Cats are often difficult to train.",
            "Lyon is a city in France."
        ]
    }
    print(">>> Request Body:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    resp = requests.post(f"{BASE_URL}/rerank", json=payload)
    print(f"<<< Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"<<< Response Keys: {list(data.keys())}")
        print(f"Scores: {data['scores']}")
        # 打印完整响应
        # print(f"<<< Full Response:\n{json.dumps(data, indent=2)}")
    else:
        print(f"Error: {resp.text}")

if __name__ == "__main__":
    test_health()
    test_embed()
    test_rerank()
