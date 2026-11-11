# -*- coding: utf-8 -*-
"""M1 检索验证脚本：验证"数据已入库且可被检索到"。

作用：
- 对 cocktails 与 knowledge 两个 collection 做混合检索（稠密 + BM25）
- 用 WeightedRanker 融合两路得分
- 打印 Top-N 命中的关键字段，人工判断召回质量

注意：本脚本是 M2 检索 Agent 的"雏形"。M2 会把这里的逻辑重构为
app/rag/retriever.py 的正式接口（多轮反思 / 重排 / 改写都在那里做）。

运行: python backend/scripts/verify_search.py "青柠 朗姆 薄荷 能调什么"
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from pymilvus import AnnSearchRequest, WeightedRanker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.model_env import resolve_model_dir  # noqa: E402
from app.knowledge.schema import get_client  # noqa: E402
from pymilvus.model.dense import SentenceTransformerEmbeddingFunction  # noqa: E402
from pymilvus.model.sparse import BM25EmbeddingFunction  # noqa: E402

BM25_PARAMS = Path(__file__).resolve().parents[1] / "data" / "processed" / "bm25_params.json"


def build_query_vectors(query: str, dense, bm25):
    """检索文本 -> 稠密 + 稀疏两组向量。BM25 必须用入库时保存的参数。"""
    if not BM25_PARAMS.exists():
        raise SystemExit("未找到 bm25_params.json，请先运行 ingest_knowledge.py")
    from app.rag.hybrid import _sparse_to_dicts
    return {
        "doc_vector": dense.encode_queries([query]),
        "sparse_vector": _sparse_to_dicts(bm25.encode_queries([query]), 1),
    }


def hybrid_search(client, collection: str, qvec: dict, limit: int = 5, output=None):
    reqs = [
        AnnSearchRequest(data=qvec["doc_vector"], anns_field="doc_vector",
                         param={"metric_type": "COSINE", "params": {}}, limit=limit * 4),
        AnnSearchRequest(data=qvec["sparse_vector"], anns_field="sparse_vector",
                         param={"metric_type": "IP", "params": {}}, limit=limit * 4),
    ]
    # 稠密 0.6 + 稀疏 0.4：语义为主、精确命中为辅（权重可在评测阶段调优）
    return client.hybrid_search(
        collection_name=collection, reqs=reqs,
        ranker=WeightedRanker(0.6, 0.4),
        limit=limit,
        output_fields=output or ["name"],
    )[0]


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "青柠 朗姆 薄荷 能调什么"
    client = get_client()

    print(f"[加载嵌入模型] {settings.EMBED_MODEL_PATH} ...")
    dense = SentenceTransformerEmbeddingFunction(model_name=resolve_model_dir(settings.EMBED_MODEL_PATH))
    bm25 = BM25EmbeddingFunction()
    bm25.load(str(BM25_PARAMS))

    qvec = build_query_vectors(query, dense, bm25)
    print(f"查询: {query}\n")

    for coll, out in (
        ("cocktails", ["name", "category", "glass", "alcoholic"]),
        ("knowledge", ["doc_type", "title", "title_cn"]),
    ):
        print(f"===== {coll} =====")
        hits = hybrid_search(client, coll, qvec, limit=5, output=out)
        if not hits:
            print("  (无命中)")
        for h in hits:
            f = h["entity"]
            name = f.get("name") or f.get("title") or f.get("title_cn")
            extra = f.get("category") or f.get("doc_type") or ""
            score = h.get("distance", h.get("score", 0.0))
            print(f"  {score:.4f}  {name}   [{extra}]")
        print()


if __name__ == "__main__":
    main()
