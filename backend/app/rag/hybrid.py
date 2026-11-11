# -*- coding: utf-8 -*-
"""混合检索：向量 + BM25 → WeightedRanker 融合。

对应 REQUIREMENTS 3.2 检索链路中的"混合检索 → RRF 融合"环节。

设计要点:
- 检索不是只跑一次: 支持一个"查询变体列表"（query_variants），
  这为 M2 的多轮反思检索 / 多维拆解提供基础——每轮可以传入多个改写/拆解结果
- 稠密权重 0.6 / 稀疏权重 0.4: 语义为主、专名精确命中为辅，
  权重是超参，RAGAS 评测阶段（M6）会基于评测集调优
- 返回带字段信息: 引用来源展示(M2 审校/引用)需要 title/name 等原文
"""
from __future__ import annotations

import copy
import json
import math
import re
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.model_env import apply_hf_endpoint, resolve_model_dir
apply_hf_endpoint()   # 下载 bge-m3 前先走国内镜像（关键！）

from app.core.config import settings

# BM25 fit 参数：入库时保存，检索时必须 load 同一份，否则词汇统计错位
BM25_PARAMS_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "bm25_params.json"

# 稠密/稀疏融合权重（可在评测阶段调优）
DENSE_WEIGHT = 0.6
SPARSE_WEIGHT = 0.4


@dataclass
class RetrievedDoc:
    """一条检索命中，供 Agent / 引用展示使用。"""
    collection: str              # cocktails / knowledge
    pk: str                      # 主键（配方 id 或知识卡片 id）
    title: str                   # 展示名（配方名 / 卡片标题）
    score: float                 # 融合后的分数
    content: str = ""            # 正文（供 LLM 阅读）
    content_cn: str = ""         # 中文正文
    meta: dict = field(default_factory=dict)  # 其他字段（category/glass/abv...）

    def to_reference(self) -> str:
        """格式化成"引用来源"文本（前端展示 / 审校校验用）。"""
        return f"[{self.collection}:{self.pk}] {self.title} (score={self.score:.3f})"

    def to_citation(self) -> dict:
        return {"source_type": self.collection, "id": self.pk, "title": self.title,
                "score": round(float(self.score), 4), "version": self.meta.get("version", 1),
                "url": self.meta.get("url") or None}

    def evidence_text(self, limit: int = 1200) -> str:
        """One evidence representation shared by reranking and answer generation."""
        if self.collection == "cocktails":
            ingredients = self.meta.get("ingredients") or []
            if isinstance(ingredients, str):
                try:
                    ingredients = json.loads(ingredients)
                except json.JSONDecodeError:
                    ingredients = []
            ingredient_text = "、".join(
                f"{item.get('name', '')} {item.get('amount', '')}".strip()
                for item in ingredients if isinstance(item, dict))
            name_en = self.meta.get("name") or ""
            flavor = self.meta.get("flavor") or {}
            return (
                f"名称: {self.title}" + (f" / {name_en}" if name_en and name_en != self.title else "") + "\n"
                f"材料与用量: {ingredient_text}\n"
                f"类别: {self.meta.get('category') or ''}\n"
                f"杯具: {self.meta.get('glass') or ''}\n"
                f"酒精度: {self.meta.get('abv') or 0}% ABV\n"
                f"风味: {json.dumps(flavor, ensure_ascii=False)}\n"
                f"步骤: {self.content_cn or self.content}"
            )[:limit]
        return f"标题: {self.title}\n内容: {self.content_cn or self.content}"[:limit]


@dataclass(frozen=True)
class SearchFilters:
    """Post-retrieval constraints derived only from explicit user language."""

    required_all_ingredients: tuple[str, ...] = ()
    required_any_ingredients: tuple[str, ...] = ()
    excluded_ingredients: tuple[str, ...] = ()
    max_abv: float | None = None
    min_strong: float | None = None
    min_sweet: float | None = None
    max_sweet: float | None = None
    min_sour: float | None = None
    max_sour: float | None = None

    def signature(self) -> str:
        return json.dumps({
            "all": self.required_all_ingredients, "any": self.required_any_ingredients,
            "not": self.excluded_ingredients, "max_abv": self.max_abv,
            "min_strong": self.min_strong, "min_sweet": self.min_sweet,
            "max_sweet": self.max_sweet, "min_sour": self.min_sour,
            "max_sour": self.max_sour,
        }, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class QueryProfile:
    intent: str
    dense_weight: float
    sparse_weight: float
    filters: SearchFilters = SearchFilters()
    exact_named_recipe: bool = False


@lru_cache(maxsize=1)
def _recipe_aliases() -> tuple[str, ...]:
    try:
        from app.services.recipe_catalog import all_recipes
        return tuple(dict.fromkeys(
            str(alias).strip().lower()
            for recipe in all_recipes()
            for alias in recipe.get("aliases") or []
            if str(alias).strip()
        ))
    except Exception:
        return ()


def _contains_named_recipe(query: str) -> bool:
    lowered = (query or "").lower()
    for alias in _recipe_aliases():
        if not alias:
            continue
        if re.search(r"[a-z0-9]", alias):
            min_length = 2 if any(char.isdigit() for char in alias) else 3
            if len(alias) >= min_length and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
                return True
        elif len(alias) >= 2 and alias in lowered:
            return True
    return False


def _ingredient_mentions(text: str) -> list[str]:
    # Use the same longest-span domain dictionary as inventory and dialogue
    # parsing. This prevents RAG filters from turning "淡奶油" into both
    # light cream and cream while another Agent sees only one ingredient.
    from app.services.deterministic_chat import extract_inventory_mentions
    return extract_inventory_mentions(text)


def analyze_query(query: str) -> QueryProfile:
    """Choose hybrid weights and explicit metadata constraints by query type."""
    text = query or ""
    relationship_question = bool(re.search(
        r"比例|公式|标准|发明|发明人|起源|历史|是谁|预测|保证|治(?:疗|好)|安全用量|哪种",
        text,
    ))
    exact = _contains_named_recipe(text) and not relationship_question
    knowledge = bool(re.search(
        r"替代|互换|换成|直接换|能否?换|能不能换|用什么换|什么能换|区别|原理|为什么|技法|怎么摇|怎么搅|摇和|搅拌|"
        r"捣压|分层|泡沫|杯沿|杯具|工具|新手|保存|安全|酒驾|怎么办|不使用|"
        r"比例|公式|标准|发明|起源|历史|是谁|预测|保证|治(?:疗|好)|失眠|哪种",
        text,
    ))
    recommend = bool(re.search(r"推荐|想喝|来一杯|能调什么|适合我|给我选", text))
    inventory = bool(re.search(r"库存|手边|手上|家里有|我有|用.+(?:调|做)", text))
    taste = bool(re.search(r"甜|酸|苦|清爽|浓郁|酒感|低度|低酒精", text))

    if exact:
        intent, dense, sparse = "exact_recipe", 0.35, 0.65
    elif knowledge:
        intent, dense, sparse = "knowledge", 0.72, 0.28
    elif recommend or taste:
        intent, dense, sparse = "recommendation", 0.68, 0.32
    elif _ingredient_mentions(text):
        intent, dense, sparse = "ingredient", 0.45, 0.55
    else:
        intent, dense, sparse = "general", DENSE_WEIGHT, SPARSE_WEIGHT

    # Exact recipe and educational questions must not be filtered by a user's
    # taste wording (for example "Margarita 为什么这么酸").
    if exact or knowledge:
        return QueryProfile(intent, dense, sparse, exact_named_recipe=exact)

    mentions = _ingredient_mentions(text)
    base_spirits = tuple(item for item in mentions if item in {
        "gin", "vodka", "rum", "white rum", "dark rum", "tequila",
        "whiskey", "whisky", "bourbon", "brandy", "cognac",
    })
    forbidden: list[str] = []
    for fragment in re.findall(r"(?:不要|不用|别用|不含|不能用)([^，、。；！？!?,]{1,28})", text):
        forbidden.extend(_ingredient_mentions(fragment))
    forbidden = list(dict.fromkeys(forbidden))
    positive = tuple(item for item in mentions if item not in forbidden)

    required_all = positive if inventory and bool(re.search(r"能调|用.+(?:调|做)|按.+库存", text)) else ()
    required_any = () if required_all else base_spirits
    moderate_sour = bool(re.search(
        r"不太酸|不是很酸|不要太酸|别太酸|中低酸|微酸|"
        r"酸.{0,8}(?:不|别|不要).{0,3}(?:很|太)?酸",
        text,
    ))
    filters = SearchFilters(
        required_all_ingredients=required_all,
        required_any_ingredients=required_any,
        excluded_ingredients=tuple(forbidden),
        max_abv=18.0 if re.search(r"低度|低酒精|不要太烈|不烈", text) else None,
        min_strong=4.0 if re.search(r"有酒味|酒感|喝得出酒|烈一点", text) else None,
        min_sweet=3.0 if "甜" in text and not re.search(r"不甜|不要甜", text) else None,
        max_sweet=5.0 if re.search(
            r"不太甜|不是很甜|不要太甜|别太甜|中低甜|微甜|甜.{0,5}(?:不|别|不要).{0,3}太?甜",
            text,
        ) else None,
        min_sour=2.0 if moderate_sour else None,
        max_sour=(2.0 if re.search(r"不酸|不要酸|别酸", text) else
                  4.0 if moderate_sour else None),
    )
    return QueryProfile(intent, dense, sparse, filters, exact_named_recipe=exact)


_TERM_EXPANSIONS = (
    (re.compile(r"干摇|dry\s*shake", re.I), "摇和法 shake 蛋清 充气 蛋白质 泡沫"),
    (re.compile(r"摇和|摇酒|shake", re.I), "摇和法 shake 雪克壶 充气 稀释"),
    (re.compile(r"搅拌|stir", re.I), "搅拌法 stir 吧勺 清澈 稀释"),
    (re.compile(r"捣压|muddle", re.I), "捣压法 muddle 香草 水果 精油"),
    (re.compile(r"分层|layer", re.I), "分层法 layer 密度 勺背"),
    (re.compile(r"杯沿|盐边|糖边|rim", re.I), "杯沿裹料 rim salt sugar garnish"),
    (re.compile(r"双重过滤|double\s*strain", re.I), "双重过滤 double strain 细滤网"),
)


def deterministic_query_variants(query: str) -> list[str]:
    """Domain aliases that are cheaper and safer than an LLM rewrite."""
    variants = []
    for pattern, expansion in _TERM_EXPANSIONS:
        if pattern.search(query or ""):
            variants.append(f"{query} {expansion}")
    return list(dict.fromkeys(variants))


def _doc_ingredients(doc: RetrievedDoc) -> set[str]:
    from app.services.recipe_catalog import canonical

    values = doc.meta.get("ingredients") or []
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            values = []
    return {
        canonical(str(item.get("canonical") or item.get("name") or ""))
        for item in values if isinstance(item, dict)
    }


def matches_filters(doc: RetrievedDoc, filters: SearchFilters) -> bool:
    if doc.collection != "cocktails":
        return not any((filters.required_all_ingredients, filters.required_any_ingredients,
                        filters.excluded_ingredients, filters.max_abv is not None,
                        filters.min_strong is not None, filters.min_sweet is not None,
                        filters.max_sweet is not None, filters.min_sour is not None,
                        filters.max_sour is not None))
    ingredients = _doc_ingredients(doc)
    if filters.required_all_ingredients and not set(filters.required_all_ingredients) <= ingredients:
        return False
    if filters.required_any_ingredients and not (set(filters.required_any_ingredients) & ingredients):
        return False
    if filters.excluded_ingredients and set(filters.excluded_ingredients) & ingredients:
        return False
    abv = float(doc.meta.get("abv") or 0)
    flavor = doc.meta.get("flavor") or {}
    if filters.max_abv is not None and abv > filters.max_abv:
        return False
    if filters.min_strong is not None and float(flavor.get("strong") or 0) < filters.min_strong:
        return False
    if filters.min_sweet is not None and float(flavor.get("sweet") or 0) < filters.min_sweet:
        return False
    if filters.max_sweet is not None and float(flavor.get("sweet") or 0) > filters.max_sweet:
        return False
    if filters.min_sour is not None and float(flavor.get("sour") or 0) < filters.min_sour:
        return False
    if filters.max_sour is not None and float(flavor.get("sour") or 0) > filters.max_sour:
        return False
    return True


def _sparse_to_dicts(sparse_matrix, n: int) -> list[dict]:
    """scipy 稀疏矩阵 → [{token_id: weight}]，Milvus 稀疏向量查询格式。

    新版本 scipy 返回 coo_array，直接喂给 AnnSearchRequest 会报
    "sparse array length is ambiguous"。统一转 CSR 拿 .indices/.data。
    """
    out = []
    for i in range(n):
        row = sparse_matrix[i].tocsr()
        out.append({int(j): float(v) for j, v in zip(row.indices, row.data)})
    return out


class HybridRetriever:
    """混合检索器：管理嵌入模型 + BM25 参数 + Milvus 查询。

    实例化一次、多处复用（模型加载慢）。Milvus 未就绪时构造不报错，
    只在真正 search 时才需要连接。
    """

    def __init__(self) -> None:
        # 不要在构造检索器时加载约 2GB 的 embedding 模型。
        # Milvus 不可用时会走本地 JSON 检索，此时根本不需要该模型。
        self._dense = None
        self._bm25 = None
        # 注意: 若 BM25 参数不存在(还没入库), load 失败; 真正 search 前会再校验
        self._bm25_ready = BM25_PARAMS_PATH.exists()
        self._client = None
        # Milvus 失败熔断：首次连接失败后直接走本地检索，不再每次等待连接超时
        self._milvus_down = False

    def _get_dense(self):
        """仅在确认要走 Milvus 向量检索时加载 embedding 模型。"""
        if self._dense is None:
            from pymilvus.model.dense import SentenceTransformerEmbeddingFunction
            embed_path = resolve_model_dir(settings.EMBED_MODEL_PATH)
            self._dense = SentenceTransformerEmbeddingFunction(model_name=embed_path)
        return self._dense

    def _get_bm25(self):
        """Load the Milvus sparse encoder only for a real Milvus query."""
        if self._bm25 is None:
            from pymilvus.model.sparse import BM25EmbeddingFunction
            self._bm25 = BM25EmbeddingFunction()
            if BM25_PARAMS_PATH.exists():
                self._bm25.load(str(BM25_PARAMS_PATH))
        return self._bm25

    @staticmethod
    def _cocktail_doc(raw: dict, score: float) -> RetrievedDoc:
        source = raw.get("source", "thecocktaildb")
        pk = str(raw.get("id") or raw.get("pk") or raw.get("name", ""))
        url = raw.get("url") or raw.get("source_url")
        if not url and source == "thecocktaildb" and pk.isdigit():
            url = f"https://www.thecocktaildb.com/drink/{pk}"
        return RetrievedDoc(
            collection="cocktails", pk=pk,
            title=raw.get("name_cn") or raw.get("name", ""), score=float(score),
            content=raw.get("instructions", raw.get("instructions_en", "")),
            content_cn=raw.get("instructions_zh", ""),
            meta={"category": raw.get("category"), "glass": raw.get("glass"),
                  "alcoholic": raw.get("alcoholic"), "ingredients": raw.get("ingredients"),
                  "ingredients_text": raw.get("ingredients_text"), "version": raw.get("version", 1),
                  "source": source, "url": url, "abv": raw.get("abv"),
                  "flavor": raw.get("flavor"), "name": raw.get("name"), "name_cn": raw.get("name_cn")},
        )

    @staticmethod
    def _knowledge_doc(raw: dict, score: float) -> RetrievedDoc:
        return RetrievedDoc(
            collection="knowledge", pk=str(raw.get("id") or raw.get("pk") or raw.get("title", "")),
            title=raw.get("title_cn") or raw.get("title", ""), score=float(score),
            content=raw.get("content", ""), content_cn=raw.get("content_cn", ""),
            meta={"doc_type": raw.get("doc_type"), "title": raw.get("title"),
                  "version": raw.get("version", 1), "source": raw.get("source", "curated"),
                  "url": raw.get("url") or raw.get("source_url")},
        )

    # -- 内部: 惰性连接 Milvus（首次 search 才连接）--
    def _get_client(self):
        if self._client is None:
            from app.knowledge.schema import get_client
            self._client = get_client()
        return self._client

    # -- 编码 --
    def _encode(self, texts: list[str]) -> dict:
        """一组查询文本 -> 稠密+稀疏向量。稀疏转 dict 格式（Milvus 兼容）。"""
        if not self._bm25_ready:
            raise RuntimeError("BM25 参数未就绪，请先运行 ingest_knowledge.py 入库")
        return {
            "doc_vector": self._get_dense().encode_queries(texts),
            "sparse_vector": _sparse_to_dicts(self._get_bm25().encode_queries(texts), len(texts)),
        }

    # -- 单集合混合检索 --
    def _search_collection(self, collection: str, qvec: dict, limit: int,
                           output_fields: list[str], profile: QueryProfile) -> list[RetrievedDoc]:
        from pymilvus import AnnSearchRequest, WeightedRanker
        reqs = [
            AnnSearchRequest(data=qvec["doc_vector"], anns_field="doc_vector",
                             param={"metric_type": "COSINE", "params": {}}, limit=limit * 4),
            AnnSearchRequest(data=qvec["sparse_vector"], anns_field="sparse_vector",
                             param={"metric_type": "IP", "params": {}}, limit=limit * 4),
        ]
        raw = self._get_client().hybrid_search(
            collection_name=collection, reqs=reqs,
            ranker=WeightedRanker(profile.dense_weight, profile.sparse_weight),
            limit=limit, output_fields=output_fields,
        )[0]
        return [self._to_doc(collection, h) for h in raw]

    @staticmethod
    def _to_doc(collection: str, hit: dict) -> RetrievedDoc:
        e = hit["entity"]
        # pymilvus 3.x 用 distance 作为融合分（score 字段已改名）
        score = hit.get("distance", hit.get("score", 0.0))
        return HybridRetriever._entity_to_doc(collection, e, score)

    @staticmethod
    def _entity_to_doc(collection: str, e: dict, score: float) -> RetrievedDoc:
        """把 Milvus 实体 dict 转成 RetrievedDoc（search 与 query 共用）。"""
        if collection == "cocktails":
            ingredients = e.get("ingredients") or []
            if isinstance(ingredients, str):
                try:
                    ingredients = json.loads(ingredients)
                except json.JSONDecodeError:
                    ingredients = []
            flavor = e.get("flavor_profile") or {}
            if isinstance(flavor, str):
                try:
                    flavor = json.loads(flavor)
                except json.JSONDecodeError:
                    flavor = {}
            source = e.get("source", "thecocktaildb")
            pk = str(e.get("pk", ""))
            url = e.get("url") or (f"https://www.thecocktaildb.com/drink/{pk}"
                                   if source == "thecocktaildb" and pk.isdigit() else None)
            return RetrievedDoc(
                collection=collection, pk=e.get("pk", ""),
                title=e.get("name_cn") or e.get("name", ""), score=float(score),
                content=e.get("instructions", ""),
                content_cn=e.get("instructions_zh", ""),
                meta={"category": e.get("category"), "glass": e.get("glass"),
                      "alcoholic": e.get("alcoholic"), "ingredients": ingredients,
                      "ingredients_text": e.get("ingredients_text"), "version": e.get("version", 1),
                      "source": source, "url": url, "name": e.get("name"),
                      "name_cn": e.get("name_cn"), "abv": e.get("abv"), "flavor": flavor},
            )
        # knowledge: 基酒/技法/替代
        return RetrievedDoc(
            collection=collection, pk=e.get("pk", ""),
            title=e.get("title_cn") or e.get("title", ""), score=float(score),
            content=e.get("content", ""), content_cn=e.get("content_cn", ""),
            meta={"doc_type": e.get("doc_type"), "title": e.get("title"),
                  "version": e.get("version", 1), "source": e.get("source", "curated")},
        )

    # -- 按引用回取（跨上下文传递中间产物）--
    def get_by_references(self, references: list[str]) -> list[RetrievedDoc]:
        """按引用来源（`[collection:pk] title`）回取完整结构化文档。

        为什么需要：检索 Agent 的 reAct 工具在 LangGraph 内部上下文/线程执行，
        ContextVar 的 set 传不回调用方（实测 retrieved 恒空）。改用引用回取，
        调用方从工具返回文本里解析引用，再按 pk 从 Milvus 拿回全字段文档。
        确定性、无跨线程状态、天然并发安全。

        Milvus 不可达时自动降级到本地 JSON 回取（_local_get_by_references）。
        """
        if self._milvus_down:
            return self._local_get_by_references(references)
        try:
            return self._milvus_get_by_references(references)
        except Exception:
            self._milvus_down = True
            return self._local_get_by_references(references)

    def _milvus_get_by_references(self, references: list[str]) -> list[RetrievedDoc]:
        _COCKTAIL_FIELDS = ["pk", "name", "name_cn", "category", "glass", "alcoholic",
                             "instructions", "instructions_zh", "ingredients",
                             "ingredients_text", "abv", "flavor_profile", "tags",
                             "source", "version"]
        _KNOWLEDGE_FIELDS = ["pk", "doc_type", "title", "title_cn",
                             "content", "content_cn"]
        client = self._get_client()
        out: dict[str, RetrievedDoc] = {}
        for ref in references:
            m = re.match(r"\[([^:\]]+):([^\]]+)\]", ref)
            if not m:
                continue
            coll, pk = m.group(1), m.group(2)
            if coll not in ("cocktails", "knowledge"):
                continue
            res = client.query(
                collection_name=coll,
                filter=f'pk == "{pk}"',
                output_fields=_COCKTAIL_FIELDS if coll == "cocktails" else _KNOWLEDGE_FIELDS,
            )
            if res:
                out[f"{coll}:{pk}"] = self._entity_to_doc(coll, res[0], 0.0)
        # 保持引用给出的顺序（回取可能乱序）
        ordered: list[RetrievedDoc] = []
        for ref in references:
            m = re.match(r"\[([^:\]]+):([^\]]+)\]", ref)
            if m:
                key = f"{m.group(1)}:{m.group(2)}"
                if key in out:
                    ordered.append(out[key])
        return ordered or list(out.values())

    # -- 对外检索 --
    def search(self, query: str, limit: int = 5, query_variants: list[str] | None = None,
               collections: tuple[str, ...] = ("cocktails", "knowledge"),
               profile: QueryProfile | None = None) -> list[RetrievedDoc]:
        """对单个查询（或一组查询变体）做混合检索。

        query_variants 用于 M2 的多轮反思/多维拆解：
        传入多个改写后的查询，分别检索后合并去重，提升召回覆盖。

        Milvus 不可达（未启动/连接失败）时自动降级到本地文件检索
        （_local_search：基于 data/processed/cocktails.json + data/knowledge/*.json
        的关键词打分），保证"无 Docker 也能检索"，避免整条 Agent 链路空转。
        首次失败后熔断（_milvus_down），后续直接走本地，不等待连接超时。

        结果按 (query, limit) 缓存 TTL=5min：多轮对话中相似问题直接复用，
        省一次 Milvus 往返 + rerank CPU（返回深拷贝，防 rerank 改分污染缓存）。
        """
        if not _is_supported_query(query):
            return []
        profile = profile or analyze_query(query)
        auto_variants = deterministic_query_variants(query)
        variants = list(dict.fromkeys([*(query_variants or []), *auto_variants])) or None
        cache_key = (f"{query}|{limit}|{','.join(collections)}|{variants}|"
                     f"{profile.dense_weight:.2f}:{profile.sparse_weight:.2f}|{profile.filters.signature()}")
        now = time.time()
        with _search_cache_lock:
            hit = _search_cache.get(cache_key)
            if hit and now - hit[0] < _SEARCH_CACHE_TTL:
                return copy.deepcopy(hit[1])
        if not self._milvus_down:
            try:
                with socket.create_connection((settings.MILVUS_HOST, settings.MILVUS_PORT), timeout=0.2):
                    pass
            except OSError:
                self._milvus_down = True
        if self._milvus_down:
            docs = self._local_search(query, limit, collections, profile.filters)
        else:
            try:
                docs = self._milvus_search(query, limit, variants, collections, profile)
                # Structured post-filters can remove a small Milvus over-fetch
                # even though matching recipes exist deeper in the catalog.
                # Re-run against the same normalized local evidence before
                # declaring a genuine no-result.
                if not docs and profile.filters != SearchFilters():
                    docs = self._local_search(query, limit, collections, profile.filters)
            except Exception:
                self._milvus_down = True
                docs = self._local_search(query, limit, collections, profile.filters)
        with _search_cache_lock:
            _search_cache[cache_key] = (now, docs)
            if len(_search_cache) > 256:  # 防无限膨胀
                _search_cache.clear()
        return copy.deepcopy(docs)

    def _milvus_search(self, query: str, limit: int = 5,
                       query_variants: list[str] | None = None,
                       collections: tuple[str, ...] = ("cocktails", "knowledge"),
                       profile: QueryProfile | None = None) -> list[RetrievedDoc]:
        profile = profile or analyze_query(query)
        variants = list(dict.fromkeys([query, *(query_variants or [])]))
        # Scores from different query variants are not calibrated to one scale.
        # Fuse ranks instead: documents supported by several formulations should
        # outrank a one-off high score from only one expansion.
        fused: dict[str, dict] = {}
        for variant_index, v in enumerate(variants):
            qvec = self._encode([v])
            for coll in collections:
                fields = ["pk", "name", "name_cn", "category", "glass", "alcoholic",
                          "instructions", "instructions_zh", "ingredients", "ingredients_text",
                          "abv", "flavor_profile", "tags", "source", "version"] \
                    if coll == "cocktails" else \
                    ["pk", "doc_type", "title", "title_cn", "content", "content_cn"]
                # Post-filtering needs an over-fetched pool because ingredients
                # and flavor constraints are stored as structured JSON fields.
                fetch_limit = limit * 4 if profile.filters != SearchFilters() else limit
                ranked_docs = self._search_collection(coll, qvec, fetch_limit, fields, profile)
                for rank, doc in enumerate(ranked_docs, 1):
                    if not matches_filters(doc, profile.filters):
                        continue
                    key = f"{doc.collection}:{doc.pk}"
                    entry = fused.setdefault(key, {"doc": doc, "rrf": 0.0,
                                                   "best": float(doc.score)})
                    # Original user wording has full weight; deterministic or
                    # decomposed variants contribute slightly less.
                    variant_weight = 1.0 if variant_index == 0 else 0.82
                    entry["rrf"] += variant_weight / (60 + rank)
                    if float(doc.score) > entry["best"]:
                        entry["best"] = float(doc.score)
                        entry["doc"] = doc
        ranked_entries = sorted(
            fused.values(), key=lambda item: (item["rrf"], item["best"]), reverse=True,
        )
        ranked = []
        for item in ranked_entries:
            doc = item["doc"]
            doc.score = float(item["rrf"] * 100)
            ranked.append(doc)
        return ranked[:limit]

    # -- 本地文件检索兜底（Milvus 不可达时）--
    def _local_search(self, query: str, limit: int = 5,
                      collections: tuple[str, ...] = ("cocktails", "knowledge"),
                      filters: SearchFilters | None = None) -> list[RetrievedDoc]:
        """Use a real in-memory BM25 index when Milvus is unavailable."""
        if not _is_supported_query(query):
            return []
        expanded = " ".join([query, *deterministic_query_variants(query)])
        qt = _tokens(expanded) - _STOPWORDS
        if not qt:
            return []
        index = _load_local_index()
        filters = filters or analyze_query(query).filters
        profile = analyze_query(query)
        avgdl = index["avgdl"] or 1.0
        scored: list[tuple[float, RetrievedDoc]] = []
        for entry in index["entries"]:
            if entry["doc"].collection not in collections:
                continue
            if not matches_filters(entry["doc"], filters):
                continue
            score = _structured_filter_score(entry["doc"], filters)
            for token in qt:
                freq = entry["tf"].get(token, 0)
                if not freq:
                    continue
                idf = index["idf"].get(token, 0.0)
                denominator = freq + 1.5 * (1 - 0.75 + 0.75 * entry["length"] / avgdl)
                score += idf * (freq * 2.5) / denominator
            if query.lower() in entry["title"].lower():
                score += 4.0
            if profile.exact_named_recipe and entry["doc"].collection == "cocktails":
                names = [entry["doc"].title, entry["doc"].meta.get("name"),
                         entry["doc"].meta.get("name_cn")]
                if any(name and str(name).lower() in query.lower() for name in names):
                    score += 12.0
            if score > 0:
                entry["doc"].score = score
                scored.append((score, copy.deepcopy(entry["doc"])))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return []
        return [d for _, d in scored[:limit]]

    def _local_get_by_references(self, references: list[str]) -> list[RetrievedDoc]:
        """本地兜底回取：按 collection:pk 从 JSON 索引里取回结构化文档。"""
        kb = _load_local_kb()
        by_key: dict[str, dict] = {}
        for c in kb["cocktails"]:
            by_key[f"cocktails:{c.get('id')}"] = c
        for k in kb["knowledge"]:
            by_key[f"knowledge:{k.get('id')}"] = k
        out: list[RetrievedDoc] = []
        for ref in references:
            m = re.match(r"\[([^:\]]+):([^\]]+)\]", ref)
            if not m:
                continue
            raw = by_key.get(f"{m.group(1)}:{m.group(2)}")
            if raw is None:
                continue
            out.append(self._cocktail_doc(raw, 0.0) if m.group(1) == "cocktails"
                       else self._knowledge_doc(raw, 0.0))
        return out


_retriever: HybridRetriever | None = None

# 检索结果缓存：同 query 在 TTL 内复用（多轮对话/追问相似问题时省一次 Milvus 往返 + rerank）
_search_cache: dict[str, tuple[float, list[RetrievedDoc]]] = {}
_search_cache_lock = threading.Lock()
_SEARCH_CACHE_TTL = 300.0  # 5 分钟


def get_retriever() -> HybridRetriever:
    """全局共享一个 HybridRetriever（模型只加载一次）。"""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


# ---------- 本地文件检索兜底的辅助设施 ----------

_LOCAL_KB: dict | None = None
_LOCAL_INDEX: dict | None = None
_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
# 泛查询停用词：只含这些词的查询没有实义，交给"Top 配方兜底"而不是空结果
_STOPWORDS = {
    "推荐", "想喝", "来一杯", "来杯", "帮我", "一杯", "什么", "能调", "可以",
    "做法", "怎么", "如何", "一个", "有的", "没有", "给我", "一下", "看看",
    "今晚", "喝点", "喝什么", "那种", "好看", "请问",
}

_OUT_OF_SCOPE = {
    "股票", "股价", "身份证", "实时座位", "治疗", "治愈疾病", "ISO 编号",
    "火星", "月球重力", "量子泡沫", "未成年人每天", "官方安全剂量", "不存在的",
}

_UNSAFE_SCOPE_RE = re.compile(
    r"(?:清洁剂|消毒剂|未知化学品).{0,12}(?:调酒|苦精|饮用|用量)|"
    r"(?:儿童|未成年人).{0,12}(?:烈酒|高度酒|酒精)|"
    r"(?:鸡尾酒|烈酒|酒精).{0,12}(?:治疗|治好|治愈|保证.*(?:失眠|疾病|感冒))"
)


def _is_supported_query(query: str) -> bool:
    """Reject clearly out-of-domain or unsafe queries before lexical matching."""
    return (not any(marker.lower() in query.lower() for marker in _OUT_OF_SCOPE)
            and not _UNSAFE_SCOPE_RE.search(query or ""))


def _load_local_kb() -> dict:
    """加载本地知识库 JSON（data/processed/cocktails.json + data/knowledge/*.json），进程内缓存。"""
    global _LOCAL_KB
    if _LOCAL_KB is not None:
        return _LOCAL_KB
    base = Path(__file__).resolve().parents[2] / "data"
    cocktails: list[dict] = []
    p = base / "processed" / "cocktails.json"
    if p.exists():
            from app.services.recipe_catalog import all_recipes
            cocktails = all_recipes()
    knowledge: list[dict] = []
    for name in ("base_spirits", "starter_guide", "substitutions",
                 "techniques", "themes"):
        kp = base / "knowledge" / f"{name}.json"
        if kp.exists():
            with open(kp, encoding="utf-8") as f:
                knowledge.extend(x for x in json.load(f) if isinstance(x, dict))
    _LOCAL_KB = {"cocktails": cocktails, "knowledge": knowledge}
    return _LOCAL_KB


def _tokens(text: str) -> set[str]:
    """轻量分词：英文词（小写）+ 中文连续片段（长片段补 2-gram），用于关键词打分。"""
    if not text:
        return set()
    toks = set(w.lower() for w in re.findall(r"[a-z0-9]{2,}", text))
    for seg in _CJK_RE.findall(text):
        toks.add(seg)
        if len(seg) >= 3:
            toks.update(seg[i:i + 2] for i in range(len(seg) - 1))
    return toks


def _load_local_index() -> dict:
    """Build a weighted BM25 index once from the same evidence fields used downstream."""
    global _LOCAL_INDEX
    if _LOCAL_INDEX is not None:
        return _LOCAL_INDEX
    kb = _load_local_kb()
    entries = []
    for raw in kb["cocktails"]:
        title = " ".join(raw.get("aliases") or [raw.get("name") or ""])
        ingredients = " ".join(
            f"{item.get('name') or ''} {item.get('name_zh') or ''} {item.get('amount') or ''}"
            for item in raw.get("ingredients") or [])
        body = " ".join(filter(None, [raw.get("instructions"), raw.get("instructions_en"),
                                      raw.get("category"), raw.get("glass"),
                                      json.dumps(raw.get("flavor") or {}, ensure_ascii=False)]))
        entries.append(_index_entry(HybridRetriever._cocktail_doc(raw, 0), title, ingredients, body))
    for raw in kb["knowledge"]:
        title = " ".join(filter(None, [raw.get("title"), raw.get("title_cn")]))
        body = " ".join(filter(None, [raw.get("content"), raw.get("content_cn"), " ".join(raw.get("tags") or [])]))
        entries.append(_index_entry(HybridRetriever._knowledge_doc(raw, 0), title, "", body))
    document_frequency = Counter()
    for entry in entries:
        document_frequency.update(entry["tf"].keys())
    count = max(1, len(entries))
    idf = {token: math.log(1 + (count - freq + 0.5) / (freq + 0.5))
           for token, freq in document_frequency.items()}
    _LOCAL_INDEX = {"entries": entries, "idf": idf,
                    "avgdl": sum(item["length"] for item in entries) / count}
    return _LOCAL_INDEX


def _index_entry(doc: RetrievedDoc, title: str, ingredients: str, body: str) -> dict:
    tf = Counter()
    for token in _tokens(title):
        tf[token] += 3
    for token in _tokens(ingredients):
        tf[token] += 2
    for token in _tokens(body):
        tf[token] += 1
    return {"doc": doc, "title": title, "tf": tf, "length": max(1, sum(tf.values()))}


def _structured_filter_score(doc: RetrievedDoc, filters: SearchFilters) -> float:
    """Rank explicit metadata matches when taste words are absent from prose."""
    if doc.collection != "cocktails" or filters == SearchFilters():
        return 0.0
    ingredients = _doc_ingredients(doc)
    flavor = doc.meta.get("flavor") or {}
    score = 0.25
    score += 1.25 * len(set(filters.required_all_ingredients) & ingredients)
    score += 1.0 * len(set(filters.required_any_ingredients) & ingredients)
    if filters.min_sweet is not None or filters.max_sweet is not None:
        low = filters.min_sweet if filters.min_sweet is not None else 0.0
        high = filters.max_sweet if filters.max_sweet is not None else 10.0
        score += max(0.0, 2.0 - abs(float(flavor.get("sweet") or 0) - (low + high) / 2) * .35)
    if filters.min_sour is not None or filters.max_sour is not None:
        low = filters.min_sour if filters.min_sour is not None else 0.0
        high = filters.max_sour if filters.max_sour is not None else 10.0
        score += max(0.0, 2.0 - abs(float(flavor.get("sour") or 0) - (low + high) / 2) * .4)
    if filters.min_strong is not None:
        score += min(2.0, max(0.0, float(flavor.get("strong") or 0) - filters.min_strong + .5))
    if filters.max_abv is not None:
        score += max(0.0, (filters.max_abv - float(doc.meta.get("abv") or 0)) / 18)
    return score


def _score_tokens(query_tokens: set[str], title: str, ingredients: str, body: str) -> float:
    """加权命中打分：标题×3 / 材料×2 / 正文×1。"""
    t_title, t_ing, t_body = _tokens(title), _tokens(ingredients), _tokens(body)
    score = 0.0
    for tk in query_tokens:
        if tk in t_title:
            score += 3.0
        if tk in t_ing:
            score += 2.0
        if tk in t_body:
            score += 1.0
    return score
