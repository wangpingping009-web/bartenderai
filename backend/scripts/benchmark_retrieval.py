# -*- coding: utf-8 -*-
"""Compare BM25, dense, hybrid and hybrid+rerank on the fixed validation set."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.evalset import fixed_eval_set
from app.rag.hybrid import HybridRetriever
from app.rag.rerank import rerank
from app.rag.retriever import _collections_for_query
from app.rag.retriever import assess_evidence

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "processed" / "retrieval_benchmark.json"


def _dense(retriever: HybridRetriever, query: str, limit: int):
    vector = retriever._encode([query])["doc_vector"]
    docs = []
    for collection in ("cocktails", "knowledge"):
        fields = (["pk", "name", "name_cn", "category", "glass", "alcoholic", "instructions",
                   "instructions_zh", "ingredients", "ingredients_text", "source", "version"]
                  if collection == "cocktails" else
                  ["pk", "doc_type", "title", "title_cn", "content", "content_cn", "source", "version"])
        hits = retriever._get_client().search(
            collection_name=collection, data=vector, anns_field="doc_vector", limit=limit,
            search_params={"metric_type": "COSINE", "params": {}}, output_fields=fields,
        )[0]
        docs.extend(retriever._to_doc(collection, hit) for hit in hits)
    return sorted(docs, key=lambda item: item.score, reverse=True)[:limit]


def _metrics(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row["relevant"]]
    no_answer = [row for row in rows if not row["relevant"]]
    recall = sum(bool(set(row["retrieved"]) & set(row["relevant"])) for row in answerable) / len(answerable)
    reciprocal, ndcg = [], []
    for row in answerable:
        rank = next((i + 1 for i, key in enumerate(row["retrieved"][:5]) if key in row["relevant"]), None)
        reciprocal.append(1 / rank if rank else 0)
        ndcg.append(1 / math.log2(rank + 1) if rank else 0)
    return {"recall_at_5": round(recall, 4), "mrr_at_5": round(statistics.mean(reciprocal), 4),
            "ndcg_at_5": round(statistics.mean(ndcg), 4),
            "no_answer_precision": round(sum(not row["retrieved"] for row in no_answer) / len(no_answer), 4),
            "p95_ms": round(sorted(row["latency_ms"] for row in rows)[math.ceil(len(rows) * .95) - 1], 1)}


def benchmark(modes: list[str]) -> dict:
    retriever = HybridRetriever()
    report = {"sample_count": len(fixed_eval_set()), "modes": {}}
    for mode in modes:
        rows = []
        for case in fixed_eval_set():
            started = time.perf_counter()
            if mode == "bm25":
                docs = retriever._local_search(case["query"], 5,
                                               _collections_for_query(case["query"]))
            elif mode == "dense":
                docs = _dense(retriever, case["query"], 5)
            else:
                docs = retriever._milvus_search(case["query"], 20 if mode == "hybrid_rerank" else 5)
                if mode == "hybrid_rerank":
                    docs = rerank(case["query"], docs, top_n=5)
            # No-answer accuracy uses the same calibrated production gate for
            # every retrieval mode; raw top-k presence is not evidence quality.
            if not assess_evidence(case["query"], docs).enough:
                docs = []
            rows.append({**case, "retrieved": [f"{doc.collection}:{doc.pk}" for doc in docs],
                         "latency_ms": (time.perf_counter() - started) * 1000})
        report["modes"][mode] = _metrics(rows)
        print(mode, json.dumps(report["modes"][mode], ensure_ascii=False))
    candidates = [(name, values) for name, values in report["modes"].items() if values["p95_ms"] <= 3000]
    if candidates:
        report["recommended"] = max(candidates, key=lambda item: item[1]["ndcg_at_5"])[0]
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", choices=["bm25", "dense", "hybrid", "hybrid_rerank"],
                        default=["bm25", "dense", "hybrid", "hybrid_rerank"])
    args = parser.parse_args()
    benchmark(args.modes)
