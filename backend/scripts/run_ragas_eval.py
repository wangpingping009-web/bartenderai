# -*- coding: utf-8 -*-
"""RAGAS 评测（M6 评分+数据看板）：评估检索 + 生成质量。

用法（需 .env 配好 LLM key + Milvus 已灌数据）：
  python backend/scripts/run_ragas_eval.py [--limit 5]

评估维度（RAGAS 核心指标）：
- faithfulness     答案是否忠实于检索上下文（不编造）
- answer_relevancy 答案是否切题
- context_precision 检索命中是否精准
- context_recall   是否召回了所有必要信息

输出：每个样本分数 + 汇总，并写入 usage_log 同库的 eval_runs 表。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# ---- ragas × langchain-community 版本兼容桩 ----
# ragas 0.4.x 顶层 import `langchain_community.chat_models.vertexai.ChatVertexAI`，
# 但 langchain-community 0.4.x 已移除该模块（我们配套 langchain 1.3）。
# ragas 只在 MULTIPLE_COMPLETION_SUPPORTED 里对它有 isinstance 判断，
# 我们走 OpenAI 兼容接口（DeepSeek/Qwen）永不命中 vertexai 分支，
# 因此注入一个空桩类让 import 通过即可。
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_VERTEX_STUB = types.ModuleType("langchain_community.chat_models.vertexai")


class _ChatVertexAI:  # noqa: N801 桩类，仅让 isinstance 恒为 False
    pass


_VERTEX_STUB.ChatVertexAI = _ChatVertexAI
sys.modules.setdefault("langchain_community.chat_models.vertexai", _VERTEX_STUB)

from app.core.config import settings  # noqa: E402
from app.core.model_env import apply_hf_endpoint  # noqa: E402
apply_hf_endpoint()

# 评测样例（真实场景问题）：带 reference 标准答案（ground truth）。
# RAGAS 的 context_precision / context_recall 需要 reference 列才能算召回/精度。
_SAMPLE_QUERIES = [
    {
        "question": "玛格丽特的经典配方是什么？",
        "reference": "玛格丽特（Margarita）用龙舌兰、君度橙酒、青柠汁和盐边杯调制，将材料与冰摇匀后滤入盐边玛格丽特杯。",
    },
    {
        "question": "青柠汁用完了，可以用什么替代？",
        "reference": "青柠汁可以按 1:1 用柠檬汁替代；不同酸度可 1 青柠汁 ≈ 3/4 柠檬汁 + 1/4 醋微调。",
    },
    {
        "question": "怎么判断一杯酒该摇还是该搅？",
        "reference": "含果汁、蛋清、糖浆、乳制品等需充分融合与充气的用摇和法（Shake）；纯烈酒、风味利口酒等材料清澈的可直接用搅拌法（Stir）避免过度稀释。",
    },
    {
        "question": "白朗姆和黑朗姆能互换吗？",
        "reference": "白朗姆清爽、黑朗姆浓郁带焦糖香；两者可互换但风味差异明显，配方要求特定朗姆时应按风味调整用量。",
    },
    {
        "question": "新手调酒需要哪些必备材料？",
        "reference": "新手必备：基酒（如伏特加/威士忌）、几款利口酒、青柠/柠檬、糖浆、冰块、摇酒壶、量酒器和滤冰器。",
    },
]


def run_eval(limit: int = 5) -> dict:
    """执行 RAGAS 评测：检索 → 生成 → 打分。"""
    from ragas import evaluate
    from ragas.metrics import (answer_relevancy, context_precision,
                               context_recall, faithfulness)

    from datasets import Dataset
    from app.rag.retriever import multi_round_retrieve
    from app.core.llm import get_llm

    llm = get_llm(temperature=0)
    queries = _SAMPLE_QUERIES[:limit]

    records = []
    for item in queries:
        q = item["question"]
        res = multi_round_retrieve(q)
        contexts = [(d.content_cn or d.content or d.title) for d in res.docs][:3]
        context_str = "\n\n".join(contexts) if contexts else "(无命中)"
        answer = llm.invoke(
            f"根据以下资料回答，只依据资料内容：\n{context_str}\n\n问题：{q}"
        ).content
        records.append({
            "question": q,
            "answer": answer,
            "contexts": contexts,
            "reference": item["reference"],
        })
        print(f"[{len(records)}/{len(queries)}] {q}")

    ds = Dataset.from_list(records)

    # 评测 LLM：ragas 0.4 默认用 OpenAI 客户端打分（要 OPENAI_API_KEY）。
    # 这里显式绑定 DeepSeek 的 OpenAI 兼容 client，打 split 也能走同一 key。
    from ragas.llms import llm_factory
    from openai import OpenAI
    judge_client = OpenAI(base_url=settings.DEEPSEEK_BASE_URL,
                          api_key=settings.DEEPSEEK_API_KEY)
    judge_llm = llm_factory(model=settings.DEEPSEEK_MODEL, provider="openai",
                            client=judge_client)

    # 评测嵌入：answer_relevancy 需要 embed_query / embed_documents（ragas 0.4.3
    # 内部仍用旧 langchain 接口，而新版 ragas 自带的 HuggingFaceEmbeddings 只有
    # embed_texts —— 会 AttributeError）。自定义包装类，用本地 bge-m3 实现这
    # 两个旧接口，模型走 resolve_model_dir 本地目录，不联网。
    from app.core.model_env import resolve_model_dir

    class _LocalBgeEmbeddings:
        def __init__(self, model_path: str):
            from sentence_transformers import SentenceTransformer
            self._m = SentenceTransformer(model_path)

        def embed_query(self, text: str) -> list[float]:
            return self._m.encode(text, normalize_embeddings=True).tolist()

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            vecs = self._m.encode(texts, normalize_embeddings=True)
            return [v.tolist() for v in vecs]

    judge_embed = _LocalBgeEmbeddings(resolve_model_dir(settings.EMBED_MODEL_PATH))

    score = evaluate(ds, metrics=[
        faithfulness, answer_relevancy, context_precision, context_recall,
    ], llm=judge_llm, embeddings=judge_embed)

    # ragas 0.4.3 的 EvaluationResult 用 .scores（list[dict]）而非 .to_dict()
    # 每项是 {metric_name: 分数}，横向聚合取均值。
    all_scores: dict[str, list[float]] = {}
    for row in score.scores:
        for k, v in row.items():
            if isinstance(v, (int, float)) and not str(k).startswith("_"):
                all_scores.setdefault(k, []).append(float(v))
    result = {k: round(sum(v) / len(v), 4) for k, v in all_scores.items()}
    print("\nRAGAS 评分：", json.dumps(result, ensure_ascii=False, indent=2))
    _persist(result, len(records))
    return result


def _persist(scores: dict, n: int) -> None:
    """把评测结果写入 DB（数据看板数据源）。"""
    from app.db.database import db
    try:
        with db() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS eval_runs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "sample_count INTEGER NOT NULL,"
                "scores_json TEXT NOT NULL,"
                "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
            )
            conn.execute(
                "INSERT INTO eval_runs (sample_count, scores_json) VALUES (?, ?)",
                (n, json.dumps(scores, ensure_ascii=False)),
            )
    except Exception as e:
        print(f"[warn] 评测结果落库失败: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="评测多少条问题")
    args = parser.parse_args()
    run_eval(max(1, min(args.limit, 10)))
