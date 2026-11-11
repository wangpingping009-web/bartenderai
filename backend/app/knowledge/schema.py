# -*- coding: utf-8 -*-
"""Milvus 知识库 Schema 定义。

设计决策（为什么是 2 个 collection 而不是 4 个）:
- 需求里划分了 4 类知识（配方/基酒/技法/替代规则），但向量库里
  用 2 个 collection + doc_type 字段即可表达：配方单独一个 collection
  （字段最重、是检索主入口），其余知识卡片统一进 knowledge collection，
  用 doc_type 区分类型。检索时只搜 2 个 collection，实现与维护都更简单。

混合检索的数据基础:
- doc_vector:    稠密向量（bge-m3, 1024 维），捕捉语义相似
- sparse_vector: BM25 稀疏向量，捕捉专有名词精确命中（"Mojito" "玛格丽特"）
检索时用 Milvus 的 WeightedRanker/RRF 融合两者，再交给 BGE-Rerank（M2 实现）

本文件只负责"建集合"，写数据在 scripts/ingest_knowledge.py。
"""
from __future__ import annotations

from pymilvus import DataType, MilvusClient

from app.core.config import settings

# 嵌入模型配置：优先用环境变量，默认 bge-m3（中文+英文跨语言效果好）
# 首次运行会联网下载模型权重（约 2.3GB），之后走本地缓存
EMBED_MODEL = settings.EMBED_MODEL_PATH  # e.g. BAAI/bge-m3


def get_client() -> MilvusClient:
    """获取 Milvus 客户端（连接串带超时，避免启动即报错阻塞）。"""
    return MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}",
                        timeout=10)


def _dense_dim() -> int:
    """读取嵌入模型真实维度（bge-m3=1024），避免手写魔数漂移。

    优先从本地 models/<slug>/config.json 读 hidden_size —— 不加载模型，
    秒回、且不依赖网络。config 不存在时再退化为构造 embedding function
    （走 resolve_model_dir，命中本地缓存）。
    """
    from pathlib import Path
    from app.core.model_env import resolve_model_dir

    slug = settings.EMBED_MODEL_PATH.split("/")[-1]
    cfg_path = Path(__file__).resolve().parents[2] / "models" / slug / "config.json"
    if cfg_path.exists():
        try:
            import json
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            dim = cfg.get("hidden_size")
            if dim:
                return int(dim)
        except Exception:
            pass
    from pymilvus.model.dense import SentenceTransformerEmbeddingFunction
    ef = SentenceTransformerEmbeddingFunction(model_name=resolve_model_dir(EMBED_MODEL))
    return ef.dim


# ---------- cocktails collection ----------

def create_cocktails_collection(client: MilvusClient) -> None:
    """配方库 collection：一款酒一条记录，检索文本放 ingredients_text。"""
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="pk", datatype=DataType.VARCHAR,
                     is_primary=True, max_length=64)
    schema.add_field(field_name="name", datatype=DataType.VARCHAR, max_length=256)
    schema.add_field(field_name="name_cn", datatype=DataType.VARCHAR, max_length=256)
    schema.add_field(field_name="category", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="alcoholic", datatype=DataType.BOOL)
    schema.add_field(field_name="glass", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="instructions", datatype=DataType.VARCHAR, max_length=65535)
    schema.add_field(field_name="instructions_zh", datatype=DataType.VARCHAR, max_length=65535)
    schema.add_field(field_name="ingredients", datatype=DataType.VARCHAR, max_length=65535)  # JSON
    schema.add_field(field_name="tags", datatype=DataType.VARCHAR, max_length=2048)  # JSON
    schema.add_field(field_name="ingredients_text", datatype=DataType.VARCHAR, max_length=65535)  # 检索文本
    schema.add_field(field_name="abv", datatype=DataType.FLOAT)
    schema.add_field(field_name="flavor_profile", datatype=DataType.VARCHAR, max_length=2048)  # JSON
    schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="version", datatype=DataType.INT64)
    schema.add_field(field_name="doc_vector", datatype=DataType.FLOAT_VECTOR, dim=_dense_dim())
    schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

    index = MilvusClient.prepare_index_params()
    index.add_index(field_name="doc_vector", index_type="AUTOINDEX", metric_type="COSINE")
    # 稀疏向量必须用 IP 度量 + SPARSE_INVERTED_INDEX（Milvus 约束）
    index.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")

    client.create_collection(
        collection_name="cocktails",
        schema=schema,
        index_params=index,
    )


# ---------- knowledge collection ----------

def create_knowledge_collection(client: MilvusClient) -> None:
    """知识卡片 collection：基酒/技法/替代规则三类，用 doc_type 区分。"""
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="pk", datatype=DataType.VARCHAR,
                     is_primary=True, max_length=64)
    schema.add_field(field_name="doc_type", datatype=DataType.VARCHAR, max_length=32)  # base_spirit/technique/substitution
    schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=256)
    schema.add_field(field_name="title_cn", datatype=DataType.VARCHAR, max_length=256)
    schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
    schema.add_field(field_name="content_cn", datatype=DataType.VARCHAR, max_length=65535)
    schema.add_field(field_name="tags", datatype=DataType.VARCHAR, max_length=2048)  # JSON
    schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="version", datatype=DataType.INT64)
    schema.add_field(field_name="doc_vector", datatype=DataType.FLOAT_VECTOR, dim=_dense_dim())
    schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

    index = MilvusClient.prepare_index_params()
    index.add_index(field_name="doc_vector", index_type="AUTOINDEX", metric_type="COSINE")
    index.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")

    client.create_collection(
        collection_name="knowledge",
        schema=schema,
        index_params=index,
    )


def ensure_collections() -> MilvusClient:
    """幂等建集合：已存在则跳过，返回 client。"""
    client = get_client()
    for name, fn in (("cocktails", create_cocktails_collection),
                     ("knowledge", create_knowledge_collection)):
        if client.has_collection(name):
            print(f"[schema] {name} 已存在，跳过")
        else:
            print(f"[schema] 创建 {name} ...")
            fn(client)
    return client


if __name__ == "__main__":
    ensure_collections()
