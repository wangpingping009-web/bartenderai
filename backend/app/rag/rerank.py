# -*- coding: utf-8 -*-
"""BGE-Rerank 重排序：对混合检索结果做精排。

为什么需要重排（对应 REQUIREMENTS 3.2）:
- 混合检索（稠密+BM25）负责"召回"：宁多勿漏，返回 Top-20 左右
- 但召回的粗排序分数（COSINE + IP 融合）并不代表真正的相关性
- BGE-Reranker 是"cross-encoder"：把 query 与每条文档拼一起整体编码，
  能捕捉细粒度语义相关性，精排后取 Top-N 喂给 LLM，质量显著更高

用法:
  检索 Agent 先召回 limit*3~4 条，交给 rerank 精排，再取 limit 条。
"""
from __future__ import annotations

from functools import lru_cache

from app.core.model_env import apply_hf_endpoint, resolve_model_dir
apply_hf_endpoint()   # 下载 bge-reranker 前先走国内镜像（关键！）

from app.core.config import settings
from app.rag.hybrid import RetrievedDoc


@lru_cache(maxsize=1)
def _get_reranker():
    """加载 BGE-Reranker（cross-encoder）。首次运行联网下载，之后缓存。

    用 FlagEmbedding 还是 sentence_transformers CrossEncoder？
    - FlagEmbedding 是 BGE 官方库，功能全但依赖较重
    - sentence_transformers 的 CrossEncoder 同样支持 bge-reranker 权重，
      依赖更轻，这里优先它（两者 API 略有差异，已做适配）
    """
    from sentence_transformers import CrossEncoder
    return CrossEncoder(resolve_model_dir(settings.RERANK_MODEL_PATH), max_length=512)


def rerank(query: str, docs: list[RetrievedDoc], top_n: int | None = None) -> list[RetrievedDoc]:
    """对 docs 按与 query 的相关性精排，返回新列表（不修改原列表）。

    Args:
        query:  原始查询（改写/拆解后的查询也可以，但建议用最接近用户意图的）
        docs:   混合检索的召回结果
        top_n:  返回条数；None 表示全部精排后返回
    """
    if not docs:
        return []

    reranker = _get_reranker()
    # cross-encoder 打分: 必须把英文名(title)拼进 doc——中文查询"玛格丽特"
    # 需要靠 doc 里的 "Margarita" 对齐（bge-reranker 是多语 cross-encoder）。
    # 只传中文正文会导致中文名恰好出现在别家配方里的文档被误判高相关
    # （实测 The Philosopher 因正文含"玛格丽塔杯"压过真正的 Margarita）。
    pairs = [(query, d.evidence_text()) for d in docs]
    scores = reranker.predict(pairs)

    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    result = [d for d, _ in ranked]
    if top_n is not None:
        result = result[:top_n]

    # 把重排分数回写到 doc（供引用排序 / 调试）
    score_map = {id(d): s for d, s in ranked}
    for d in result:
        d.score = float(score_map[id(d)])
    return result


def _fingerprint(doc: RetrievedDoc) -> set[str]:
    """Cheap semantic fingerprint for MMR after cross-encoder reranking."""
    from app.rag.hybrid import _tokens
    if doc.collection == "cocktails":
        ingredients = doc.meta.get("ingredients") or []
        if isinstance(ingredients, str):
            import json
            try:
                ingredients = json.loads(ingredients)
            except json.JSONDecodeError:
                ingredients = []
        ingredient_names = " ".join(
            str(item.get("canonical") or item.get("name") or "")
            for item in ingredients if isinstance(item, dict)
        )
        return _tokens(" ".join(filter(None, [
            ingredient_names, str(doc.meta.get("category") or ""),
            str(doc.meta.get("glass") or ""),
        ])))
    return _tokens(doc.evidence_text(700))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def diversify(docs: list[RetrievedDoc], top_n: int,
              lambda_mult: float = 0.72) -> list[RetrievedDoc]:
    """Maximal marginal relevance over reranked results.

    The top result is always preserved. Remaining slots trade relevance for
    evidence diversity, preventing five near-identical citrus sours from being
    shown as five meaningfully different recommendations.
    """
    if top_n <= 0 or not docs:
        return []
    if len(docs) <= 1:
        return docs[:top_n]
    values = [float(doc.score) for doc in docs]
    low, high = min(values), max(values)
    relevance = {
        id(doc): ((float(doc.score) - low) / (high - low)) if high > low else 1.0
        for doc in docs
    }
    fingerprints = {id(doc): _fingerprint(doc) for doc in docs}
    selected = [docs[0]]
    remaining = list(docs[1:])
    while remaining and len(selected) < top_n:
        def mmr(doc: RetrievedDoc) -> tuple[float, float]:
            redundancy = max(
                _jaccard(fingerprints[id(doc)], fingerprints[id(chosen)])
                for chosen in selected
            )
            score = lambda_mult * relevance[id(doc)] - (1 - lambda_mult) * redundancy
            return score, relevance[id(doc)]

        choice = max(remaining, key=mmr)
        selected.append(choice)
        remaining.remove(choice)
    return selected


def rerank_and_diversify(query: str, docs: list[RetrievedDoc], top_n: int,
                         use_cross_encoder: bool = True) -> list[RetrievedDoc]:
    """One production ranking surface shared by every retrieval round."""
    if not docs:
        return []
    pool = rerank(query, docs, top_n=None) if use_cross_encoder else sorted(
        docs, key=lambda item: item.score, reverse=True)
    # Exact lookups prioritize relevance. Open recommendations spend more of
    # the ranking budget on variety.
    from app.rag.hybrid import analyze_query
    profile = analyze_query(query)
    lambda_mult = 0.88 if profile.exact_named_recipe else 0.66 if profile.intent == "recommendation" else 0.76
    return diversify(pool, top_n=top_n, lambda_mult=lambda_mult)
