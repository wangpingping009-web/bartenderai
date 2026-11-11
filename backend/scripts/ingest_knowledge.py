# -*- coding: utf-8 -*-
"""把结构化数据向量化并写入 Milvus。

数据源:
- data/processed/cocktails.json      (清洗后的配方, build_dataset.py 产物)
- data/knowledge/*.json              (人工精选知识卡片: 基酒/技法/替代规则)

流程:
1. 构建每个文档的"检索文本"(被嵌入/BM25 的原文)
2. 稠密向量: bge-m3 encode_documents
3. 稀疏向量: BM25 在整个语料上 fit(统计 idf) -> encode, 并保存 fit 参数
   (BM25 的词汇统计依赖语料, 检索阶段必须 load 同一份参数, 否则检索失效)
4. 批量写入 Milvus (cocktails / knowledge 两个 collection)

运行: python backend/scripts/ingest_knowledge.py [--reset]
注意: 首次运行会下载 bge-m3 权重(约 2.3GB), 之后走本地缓存。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.model_env import apply_hf_endpoint, ensure_local_model, resolve_model_dir
apply_hf_endpoint()   # 下载 bge-m3 前先走国内镜像（关键！）

from app.knowledge.schema import ensure_collections, get_client
from pymilvus.model.dense import SentenceTransformerEmbeddingFunction
from pymilvus.model.sparse import BM25EmbeddingFunction

from app.core.config import settings
from app.services.recipe_catalog import all_recipes

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PROCESSED = DATA_DIR / "processed" / "cocktails.json"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
BM25_PARAMS_PATH = DATA_DIR / "processed" / "bm25_params.json"  # fit 参数落盘

BATCH = 64  # Milvus 插入批量大小


# ---------- 检索文本构建 ----------

def _cocktail_doc(c: dict) -> tuple[str, dict]:
    """配方 -> (检索文本, 插入 payload)。检索文本聚合所有可命中信息。"""
    text = ", ".join(p for p in [
        c["name"], c.get("name_cn", ""), " ".join(c.get("aliases") or []),
        " ".join(f"{i.get('name','')} {i.get('name_zh','')} {i.get('amount','')}" for i in c["ingredients"]),
        c.get("instructions_en", ""), c.get("instructions", ""), c.get("category", ""), c.get("glass", ""),
        json.dumps(c.get("flavor") or {}, ensure_ascii=False),
    ] if p)
    payload = {
        "pk": c["id"],
        "name": c["name"],
        "name_cn": c.get("name_cn", ""),
        "category": c["category"],
        "alcoholic": c["alcoholic"],
        "glass": c["glass"],
        "instructions": c.get("instructions_en", ""),
        "instructions_zh": c.get("instructions", ""),
        "ingredients": json.dumps(c["ingredients"], ensure_ascii=False),
        "tags": json.dumps(c["tags"], ensure_ascii=False),
        "ingredients_text": text,
        "abv": float(c.get("abv") or 0),
        "flavor_profile": json.dumps(c.get("flavor") or {}, ensure_ascii=False),
        "source": c["source"],
        "version": c["version"],
    }
    return text, payload


def _knowledge_doc(k: dict) -> tuple[str, dict]:
    """知识卡片 -> (检索文本, payload)。content 双语都要进检索文本。"""
    text = ", ".join(p for p in [
        k["title"], k["title_cn"],
        k["content"], k["content_cn"],
        ",".join(k["tags"]),
    ] if p)
    payload = {
        "pk": k["id"],
        "doc_type": k["doc_type"],
        "title": k["title"],
        "title_cn": k["title_cn"],
        "content": k["content"],
        "content_cn": k["content_cn"],
        "tags": json.dumps(k["tags"], ensure_ascii=False),
        "source": k.get("source", "curated"),
        "version": k.get("version", 1),
    }
    return text, payload


# ---------- 向量化 ----------

def _to_sparse_dicts(sparse_matrix, n: int) -> list[dict]:
    """把 scipy 稀疏矩阵转成 Milvus 需要的 {token_id: weight} 字典列表。"""
    rows = []
    for i in range(n):
        row = sparse_matrix[i]
        # scipy 稀疏数组可能是 coo_array（新版本默认）；统一转 csr 拿 .indices/.data
        row = row.tocsr()
        rows.append({int(j): float(v) for j, v in zip(row.indices, row.data)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true",
                        help="先删除已存在的 collection 再重建")
    args = parser.parse_args()

    # 1. 读取数据
    cocktails = all_recipes()
    knowledge: list[dict] = []
    for kf in sorted(KNOWLEDGE_DIR.glob("*.json")):
        with open(kf, encoding="utf-8") as f:
            data = json.load(f)
        # themes.json 是 dict（前端主题玩法用，不进向量知识库）；只收 list 结构的知识卡
        if isinstance(data, list):
            knowledge.extend(data)
        else:
            print(f"[skip] {kf.name}: 非列表结构（{type(data).__name__}），跳过")
    print(f"配方 {len(cocktails)} 款, 知识卡片 {len(knowledge)} 张")

    # 2. 建 collection
    client = ensure_collections()
    if args.reset:
        for name in ("cocktails", "knowledge"):
            if client.has_collection(name):
                client.drop_collection(name)
                print(f"[reset] 删除 {name}")
        ensure_collections()

    # 3. 构建检索文本与 payload
    c_texts, c_payloads = zip(*[_cocktail_doc(c) for c in cocktails]) if cocktails else ((), ())
    k_texts, k_payloads = zip(*[_knowledge_doc(k) for k in knowledge]) if knowledge else ((), ())
    all_texts = list(c_texts) + list(k_texts)
    print(f"共 {len(all_texts)} 个文档进入向量化")

    # 4. 稠密向量（本地缓存命中则离线加载，否则走镜像/ModelScope）
    embed_path = ensure_local_model(settings.EMBED_MODEL_PATH)
    print(f"[dense] 加载嵌入模型 {embed_path} ...")
    dense = SentenceTransformerEmbeddingFunction(model_name=embed_path)
    all_dense = dense.encode_documents(all_texts)

    # 5. 稀疏向量（BM25 fit + encode + 落盘）
    print("[sparse] BM25 fit + encode ...")
    bm25 = BM25EmbeddingFunction()
    bm25.fit(all_texts)
    all_sparse = _to_sparse_dicts(bm25.encode_documents(all_texts), len(all_texts))
    bm25.save(str(BM25_PARAMS_PATH))  # 检索阶段 load 同一份参数
    print(f"[sparse] 参数已保存 -> {BM25_PARAMS_PATH}")

    # 6. 组装 + 批量写入
    def _rows(payloads, dense_vecs, sparse_vecs):
        return [
            {**p, "doc_vector": dv, "sparse_vector": sv}
            for p, dv, sv in zip(payloads, dense_vecs, sparse_vecs)
        ]

    def _insert(name, rows):
        for i in range(0, len(rows), BATCH):
            client.insert(collection_name=name, data=rows[i:i + BATCH])
        print(f"[insert] {name}: {len(rows)} 条")

    _insert("cocktails", _rows(c_payloads, all_dense[:len(c_payloads)], all_sparse[:len(c_payloads)]))
    _insert("knowledge", _rows(k_payloads, all_dense[len(c_payloads):], all_sparse[len(c_payloads):]))

    print(f"\n完成: cocktails={len(c_payloads)}, knowledge={len(k_payloads)}")


if __name__ == "__main__":
    main()
