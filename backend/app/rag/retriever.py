# -*- coding: utf-8 -*-
"""检索 Agent 的核心编排：把改写/拆解/混合检索/重排串成完整链路。

对应 REQUIREMENTS 3.2 检索链路 + 多轮反思检索原则:

```
用户查询
  → 查询改写(有历史时)          query_rewrite.py
  → 判断是否拆解(复杂问题)        query_decompose.py
  → 混合检索(每路子查询)          hybrid.py
  → BGE-Rerank 精排               rerank.py
  → 阅读反思: 信息是否足够?
     不足 → 改写查询再检索(限3轮)   multi_round_retrieve()
  → 返回带引用来源的结果
```

本模块提供两个入口:
- `retrieve_once()`:  单次检索（供其他 Agent 简单调用）
- `multi_round_retrieve()`: 多轮反思检索（检索 Agent 的 reAct 循环的核心，
  也是"搜索-阅读-反思-再搜索"闭环的落地）
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

from app.core.config import settings
from app.core.llm import get_llm
from app.rag.hybrid import RetrievedDoc, get_retriever
from app.rag.query_decompose import decompose_query
from app.rag.query_rewrite import rewrite_query
from app.rag.rerank import rerank_and_diversify

# 检索硬约束（防 token 失控，见 REQUIREMENTS）
MAX_ROUNDS = settings.RETRIEVE_MAX_ROUNDS
MIN_ANGLES = settings.RETRIEVE_MIN_ANGLES


@dataclass
class RetrievalResult:
    """一次检索的完整结果（含过程信息，供 SSE 事件流展示/可观测）。"""
    query: str                                  # 改写后的主查询
    sub_queries: list[str] = field(default_factory=list)   # 拆解后的子查询
    rounds: int = 0                             # 实际反思轮数
    docs: list[RetrievedDoc] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    is_retrieved: bool = True                   # 是否有可用结果
    fallback_reason: str = ""                   # 兜底原因（LLM 兜底/公网时填充）
    events: list[str] = field(default_factory=list)  # SSE 事件流用
    confidence: float = 0.0
    field_coverage: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    retrieval_mode: str = "unavailable"             # milvus_hybrid / local_bm25

    def add_event(self, evt: str) -> None:
        self.events.append(evt)


@dataclass
class EvidenceAssessment:
    enough: bool
    confidence: float
    field_coverage: float
    missing_fields: list[str] = field(default_factory=list)
    reason: str = ""


def _has_amounts(doc: RetrievedDoc) -> bool:
    ingredients = doc.meta.get("ingredients") or []
    if isinstance(ingredients, str):
        import json
        try:
            ingredients = json.loads(ingredients)
        except json.JSONDecodeError:
            ingredients = []
    rows = [item for item in ingredients if isinstance(item, dict)]
    measured = sum(bool(str(item.get("amount") or "").strip()) for item in rows)
    # Source datasets often omit one top-up or garnish amount. The evidence is
    # still amount-bearing when every primary ingredient and >=75% overall are measured.
    return len(rows) >= 2 and measured >= max(2, math.ceil(len(rows) * .75))


def assess_evidence(query: str, docs: list[RetrievedDoc]) -> EvidenceAssessment:
    """Calibrate evidence by intent, field completeness and explicit filters."""
    from app.rag.hybrid import _STOPWORDS, _tokens, analyze_query, matches_filters

    if not docs:
        return EvidenceAssessment(False, 0.0, 0.0, ["evidence"], "没有检索证据")
    profile = analyze_query(query)
    recipe_docs = [doc for doc in docs if doc.collection == "cocktails"]
    knowledge_docs = [doc for doc in docs if doc.collection == "knowledge"]
    required: list[str] = []
    if profile.exact_named_recipe:
        required.append("named_recipe")
    if profile.intent in {"exact_recipe", "recommendation", "ingredient"}:
        required.append("ingredients")
    if re.search(r"材料|用量|多少|几毫升|配方", query):
        required.append("amounts")
    if re.search(r"怎么调|如何调|做法|步骤|制作|调制", query):
        required.append("steps")
    if profile.intent == "recommendation" or (
            profile.intent != "knowledge" and re.search(r"甜|酸|苦|酒感|清爽|浓郁", query)):
        required.append("flavor")
    if profile.intent == "knowledge":
        required.append("knowledge_content")
    required = list(dict.fromkeys(required)) or ["content"]

    query_lower = query.lower()
    named_hit = any(
        any(name and str(name).lower() in query_lower for name in (
            doc.title, doc.meta.get("name"), doc.meta.get("name_cn")))
        for doc in recipe_docs
    )
    checks = {
        "named_recipe": named_hit,
        "ingredients": any(bool(doc.meta.get("ingredients")) for doc in recipe_docs),
        "amounts": any(_has_amounts(doc) for doc in recipe_docs),
        "steps": any(bool((doc.content_cn or doc.content or "").strip())
                     for doc in (knowledge_docs if profile.intent == "knowledge" else recipe_docs)),
        "flavor": any(bool(doc.meta.get("flavor")) for doc in recipe_docs),
        "knowledge_content": any(len((doc.content_cn or doc.content or "").strip()) >= 30
                                 for doc in knowledge_docs),
        "content": any(bool((doc.content_cn or doc.content or "").strip()) for doc in docs),
    }
    missing = [name for name in required if not checks.get(name, False)]
    field_coverage = sum(checks.get(name, False) for name in required) / max(1, len(required))

    query_tokens = _tokens(query) - _STOPWORDS
    evidence_tokens: set[str] = set()
    for doc in docs[:5]:
        evidence_tokens |= _tokens(doc.evidence_text())
    lexical_coverage = (len(query_tokens & evidence_tokens) / len(query_tokens)) if query_tokens else 0.0
    filtered = [doc for doc in recipe_docs if matches_filters(doc, profile.filters)]
    has_constraints = profile.filters != type(profile.filters)()
    constraint_score = float(bool(filtered)) if has_constraints else 0.0

    if profile.intent == "recommendation":
        requested_many = bool(re.search(r"(?:多推荐|推荐|给我)\s*[二三四五六七八九十2-9]", query))
        candidate_score = min(1.0, len(filtered or recipe_docs) / (3 if requested_many else 1))
    else:
        candidate_score = 0.0

    # Complete fields are useful only after relevance has been established.
    # Previously a structurally complete but unrelated recipe scored 0.80 even
    # with zero lexical overlap, which let nonsense questions cite real drinks.
    if profile.exact_named_recipe:
        intent_support = float(named_hit)
    elif profile.intent == "recommendation":
        explicit_request = bool(re.search(r"推荐|想喝|来一杯|能调什么|适合我|给我选|口味", query))
        concise_preference = bool(has_constraints and len(query) <= 40 and not re.search(
            r"为什么|比例|公式|标准|发明|预测|是谁|保证|治疗|治好", query,
        ))
        intent_support = float(bool(recipe_docs) and (explicit_request or concise_preference))
    elif profile.intent == "ingredient":
        intent_support = float(bool(filtered) and bool(profile.filters.required_all_ingredients
                                                       or profile.filters.required_any_ingredients))
    elif profile.intent == "knowledge":
        intent_support = float(bool(knowledge_docs) and lexical_coverage >= 0.30)
    else:
        intent_support = float(lexical_coverage >= 0.40)
    semantic_score = min(1.0, lexical_coverage * 3)
    confidence = 0.50 * field_coverage + 0.25 * semantic_score \
        + 0.15 * intent_support + 0.10 * max(constraint_score, candidate_score)
    if profile.exact_named_recipe and not named_hit:
        confidence = min(confidence, 0.25)
    enough = not missing and confidence >= 0.72
    reason = ("字段与约束覆盖充分" if enough else
              "仍缺少: " + "、".join(missing or ["问题关键语义覆盖"]))
    return EvidenceAssessment(enough, round(confidence, 4), round(field_coverage, 4), missing, reason)


def _attach_assessment(result: RetrievalResult, query: str) -> None:
    assessment = assess_evidence(query, result.docs)
    result.confidence = assessment.confidence
    result.field_coverage = assessment.field_coverage
    result.missing_fields = assessment.missing_fields
    result.add_event(
        f"证据校准: confidence={assessment.confidence:.2f}, "
        f"field_coverage={assessment.field_coverage:.2f}"
    )


def _refined_query(query: str, missing: list[str]) -> str:
    labels = {
        "ingredients": "材料", "amounts": "准确用量", "steps": "调制步骤",
        "flavor": "风味", "knowledge_content": "原理与操作要点",
        "named_recipe": "标准中英文配方名",
    }
    suffix = " ".join(labels.get(item, item) for item in missing)
    return f"{query} {suffix}".strip()


# ---------- 反思判断（LLM 决定"信息是否足够"）----------

_REFLECT_PROMPT = """你是一个检索质量评估器。基于用户问题与已检索到的知识片段，判断信息是否足够回答用户问题。

用户问题：{query}

已检索到的知识片段：
{docs}

判断要求：
1. 若已检索到的片段能覆盖用户问题的关键方面（材料/做法/知识要点），则足够
2. 对于口味/偏好/推荐类问题（"想喝…""有什么推荐""喜欢…口味"），
   只要候选配方里已有明确可推荐的酒款（含名称），即判定足够，无需再搜
3. 若明显缺少关键信息（如配方没有做法、推荐没有具体酒），则不足
4. 你的回答要简短（1句话内），输出 JSON：{{"enough": true/false, "reason": "简短原因", "refined_query": "若不足，给出下一步更聚焦的检索查询；若足够则为空"}}"""


def _reflect_body(d: RetrievedDoc) -> str:
    """反思评估用的文档正文。

    配方优先给"材料+用量"（ingredients_text），而不是只给步骤。实测仅给
    instructions_zh 时，反思对"XX的经典配方是什么？"这类问法会误判信息不足
    ——第一轮已正确命中经典 Margarita（含材料/用量），却仍触发第二轮重搜，
    反把好结果挤出。材料+步骤都给，评估才有依据。
    """
    if d.collection == "cocktails":
        ing = d.meta.get("ingredients_text")
        if ing:
            step = d.content_cn or d.content or ""
            return f"{ing} | 步骤: {step[:200]}"
    return d.content_cn or d.content or ""


def _reflect(query: str, docs: list[RetrievedDoc],
             assessment: EvidenceAssessment | None = None) -> tuple[bool, str]:
    """反思：判断现有检索结果是否足够。返回 (enough, refined_query)。"""
    if not docs:
        return False, query  # 无结果必然不足，用原查询再试
    doc_text = "\n\n".join(
        f"[{i}] {d.title}: {_reflect_body(d)}" for i, d in enumerate(docs[:5])
    )
    try:
        llm = get_llm(temperature=0, max_tokens=256)
        resp = llm.invoke(_REFLECT_PROMPT.format(query=query, docs=doc_text))
        import json
        data = json.loads(resp.content)
        return bool(data.get("enough")), data.get("refined_query", "") or query
    except Exception:
        assessment = assessment or assess_evidence(query, docs)
        return assessment.enough, _refined_query(query, assessment.missing_fields)


# ---------- 对外接口 ----------

def retrieve_once(query: str, limit: int = 5,
                  extra_variants: list[str] | None = None,
                  decompose: bool = True) -> RetrievalResult:
    """单次检索：先直接检索原始查询，候选充足则跳过拆解；不足再拆解补充。

    性能优化（实测省 ~5s）：
    - 大多数查询（含配方名/材料/专名）用原始查询直接检索就能命中充足候选，
      不需要 LLM 拆解（decompose 每次调用 2-20s，取决于供应商波动）。
    - 仅当首轮候选不足（开放/语义模糊查询）才走 decompose 多路补充召回，
      保证开放查询的召回覆盖不降。

    extra_variants: 额外的检索变体（如改写器抽出的 keywords）。
    中英混排场景尤其关键：改写成"玛格丽特鸡尾酒的做法是什么"后，
    BM25 中文"玛格丽特"匹配不到英文 "Margarita"，但 keywords 里的
    "Margarita" 能精确命中。合并进检索变体可显著提升召回。

    decompose=False: 跳过查询拆解（多轮反思里第 2 轮起 refined_query 已聚焦）。
    """
    res = RetrievalResult(query=query)
    res.add_event(f"正在检索: {query}")

    retriever = get_retriever()
    collections = _collections_for_query(query)

    def _search(sq: str, k: int) -> list[RetrievedDoc]:
        return retriever.search(sq, limit=limit * k, collections=collections)

    # 1. 首轮：直接用原始查询检索（Milvus ~0.3s / 本地兜底内存检索）
    first = _search(query, 5)
    res.retrieval_mode = ("local_bm25" if getattr(retriever, "_milvus_down", False)
                          else "milvus_hybrid")
    mode_label = "本地 BM25" if res.retrieval_mode == "local_bm25" else "Milvus 混合检索"
    res.add_event(f"{mode_label} '{query}' -> {len(first)} 条候选")

    # 2. 候选充足 → 直接精排收尾（跳过 decompose LLM，大多数查询走这里）
    if len(first) >= limit:
        res.sub_queries = [query]
        seen: dict[str, RetrievedDoc] = {f"{d.collection}:{d.pk}": d for d in first}
        if getattr(retriever, "_milvus_down", False):
            reranked = rerank_and_diversify(query, list(seen.values()), top_n=limit,
                                            use_cross_encoder=False)
        else:
            reranked = rerank_and_diversify(query, list(seen.values()), top_n=limit)
        res.docs = reranked
        res.references = [d.to_reference() for d in reranked]
        res.add_event(f"重排后保留 Top-{len(reranked)}")
        res.is_retrieved = bool(reranked)
        _attach_assessment(res, query)
        if not reranked:
            res.fallback_reason = "no_hit_in_knowledge_base"
        return res

    # 3. 候选不足（开放/模糊查询）：拆解多路补充召回
    sub_queries = decompose_query(query) if decompose else [query]
    if extra_variants:
        sub_queries = list(dict.fromkeys(sub_queries + extra_variants))
    res.sub_queries = sub_queries
    if len(sub_queries) > 1:
        res.add_event(f"问题已拆解为 {len(sub_queries)} 个子查询")

    # 候选池按问题类型分流（性能优化，不损召回）：
    # - 单一子查询用宽池 limit*5：专名变体噪声需要宽召回才进得了重排阶段
    # - 多子查询用窄池 limit*3：rerank 是 CPU 大头，减候选省时间
    candidate_k = 5 if len(sub_queries) == 1 else 3

    def _search_variant(sq: str) -> list[RetrievedDoc]:
        return _search(sq, candidate_k)

    candidates: list[RetrievedDoc] = list(first)  # 首轮候选并入，不丢
    if len(sub_queries) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as ex:
            results = list(ex.map(_search_variant, sub_queries))
        for sq, docs in zip(sub_queries, results):
            candidates.extend(docs)
            res.add_event(f"{mode_label} '{sq}' -> {len(docs)} 条候选")
    else:
        for sq in sub_queries:
            docs = _search_variant(sq)
            candidates.extend(docs)
            res.add_event(f"{mode_label} '{sq}' -> {len(docs)} 条候选")
    res.add_event(f"共 {len(candidates)} 条候选")

    # 去重 + 重排（Milvus 不可达时本地兜底已按关键词分排序，跳过 CPU 重的 rerank）
    seen = {f"{d.collection}:{d.pk}": d for d in candidates}
    if getattr(retriever, "_milvus_down", False):
        reranked = rerank_and_diversify(query, list(seen.values()), top_n=limit,
                                        use_cross_encoder=False)
    else:
        reranked = rerank_and_diversify(query, list(seen.values()), top_n=limit)

    res.docs = reranked
    res.references = [d.to_reference() for d in reranked]
    res.add_event(f"重排后保留 Top-{len(reranked)}")
    res.is_retrieved = bool(reranked)
    _attach_assessment(res, query)
    if not reranked:
        res.fallback_reason = "no_hit_in_knowledge_base"
    return res


def _collections_for_query(query: str) -> tuple[str, ...]:
    """Route explicit recipe and educational intents before retrieval."""
    knowledge = any(word in query for word in (
        "替代", "互换", "换", "区别", "原理", "技法", "摇还是",
        "怎么摇", "怎么搅", "摇和", "搅拌", "捣压", "分层", "泡沫",
        "杯沿", "杯具", "工具", "新手", "保存", "安全", "酒驾", "为什么",
        "怎么办", "不使用", "比例", "公式", "标准", "发明", "起源", "历史",
        "是谁", "预测", "保证", "治疗", "治好", "失眠", "哪种",
    ))
    recipes = any(word in query for word in (
        "配方", "做法", "怎么调", "如何调", "推荐", "来一杯", "能调", "材料", "用量",
    ))
    if knowledge and not recipes:
        return ("knowledge",)
    if recipes and not knowledge:
        return ("cocktails",)
    return ("cocktails", "knowledge")


def multi_round_retrieve(query: str, history: list[dict] | None = None,
                         limit: int = 5) -> RetrievalResult:
    """多轮反思检索：搜索-阅读-反思-再搜索 闭环。

    - 改写（有历史时）
    - 单轮检索
    - 反思：不够 → 用 refined_query 再检索（最多 MAX_ROUNDS 轮）
    """
    # 1. 改写
    original_query = query
    rw = rewrite_query(query, history)
    query = rw.rewritten
    if not rw.needs_retrieve:
        return RetrievalResult(query=query, is_retrieved=False,
                               fallback_reason="no_retrieve_needed")
    res = RetrievalResult(query=query)
    if history and rw.rewritten != original_query:
        res.add_event(f"查询已改写: {rw.rewritten}")
    # Deterministic bilingual aliases are cheap and always available.
    extra_variants = [k for k in rw.keywords if k.strip() and k != query] or None

    current_query = query
    res.rounds = 1
    for r in range(MAX_ROUNDS):
        res.add_event(f"[第 {r + 1} 轮检索] {current_query}")
        # 第 2 轮起 refined_query 已聚焦，跳过拆解（省一次 LLM ~4.5s）
        partial = retrieve_once(current_query, limit=limit,
                                extra_variants=extra_variants,
                                decompose=(r == 0))
        res.retrieval_mode = partial.retrieval_mode
        # 合并本轮结果。注意：每轮重排的分数基准是"该轮查询"，跨轮直接比
        # 分数不公平（第2轮对"配方 材料 用量"打的高分未必对原问题更相关）。
        # 合并后统一用【原查询】重排再截断，保证后轮真正更相关的文档才能上位。
        merged = {f"{d.collection}:{d.pk}": d for d in res.docs + partial.docs}
        if len(merged) > limit:
            use_cross_encoder = not getattr(get_retriever(), "_milvus_down", False)
            res.docs = rerank_and_diversify(query, list(merged.values()), top_n=limit,
                                            use_cross_encoder=use_cross_encoder)
        else:
            res.docs = sorted(merged.values(), key=lambda x: x.score, reverse=True)
        res.references = [d.to_reference() for d in res.docs]

        assessment = assess_evidence(query, res.docs)
        res.confidence = assessment.confidence
        res.field_coverage = assessment.field_coverage
        res.missing_fields = assessment.missing_fields
        res.add_event(
            f"证据校准: confidence={assessment.confidence:.2f}, "
            f"field_coverage={assessment.field_coverage:.2f}"
        )
        if assessment.enough:
            enough, refined = True, query
        else:
            enough, refined = _reflect(query, res.docs, assessment)
        if enough or r == MAX_ROUNDS - 1:
            res.add_event("信息已足够" if enough else "已达最大检索轮数")
            break
        res.add_event(f"信息不足({refined})，继续检索")
        current_query = refined
        res.rounds += 1

    final_assessment = assess_evidence(query, res.docs)
    res.confidence = final_assessment.confidence
    res.field_coverage = final_assessment.field_coverage
    res.missing_fields = final_assessment.missing_fields
    # Weak partial matches are not evidence. Returning an empty set is safer
    # than letting downstream Agents cite a semantically unrelated document.
    if res.docs and not final_assessment.enough:
        res.docs = []
        res.references = []
        res.fallback_reason = "insufficient_evidence"
    res.is_retrieved = bool(res.docs)
    if not res.docs and not res.fallback_reason:
        res.fallback_reason = "no_hit_in_knowledge_base"
    return res
