# -*- coding: utf-8 -*-
"""从 TheCocktailDB 公开 API 抓取鸡尾酒配方原始数据。

为什么用这个数据源：
- 公开免费、无需 key、数据量约 600+ 款经典/流行鸡尾酒
- 字段覆盖：名称/材料/用量/步骤/杯具/分类/含酒精/标签，够我们结构化

拉取策略：
- 该 API 没有"全量导出"端点，但支持按名称首字母搜索 `search.php?f=<letter>`
- 所以按 a-z + 0-9 遍历 36 次即可拿到全量
- 每次请求结果去重（同一款酒可能被多个首字母命中）

注意：免费层约 100 次请求/天。本脚本一次约 36 次请求，不要频繁重跑。

运行: python backend/scripts/fetch_cocktails.py
产物: data/raw/cocktails_raw.json  (保留 API 原始字段，不在此处清洗)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

BASE_URL = "https://www.thecocktaildb.com/api/json/v1/1/search.php"
LETTERS = list("abcdefghijklmnopqrstuvwxyz0123456789")

RAW_PATH = Path(__file__).resolve().parents[1] / "data" / "raw"


def fetch_letter(letter: str) -> list[dict]:
    """抓取指定首字母的所有饮品。失败时重试 2 次后返回空。"""
    url = f"{BASE_URL}?f={letter}"
    for attempt in range(3):
        try:
            with urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("drinks") or []
        except Exception as e:  # 网络抖动常见，重试后仍失败再抛
            if attempt == 2:
                print(f"  [warn] {letter} 抓取失败: {e}")
            time.sleep(1.5)
    return []


def main() -> None:
    RAW_PATH.mkdir(parents=True, exist_ok=True)

    all_drinks: dict[str, dict] = {}  # 用 idDrink 去重
    for i, letter in enumerate(LETTERS):
        drinks = fetch_letter(letter)
        for d in drinks:
            all_drinks[d["idDrink"]] = d
        print(f"[{i + 1:2d}/{len(LETTERS)}] {letter}: +{len(drinks)}  (累计 {len(all_drinks)})")
        time.sleep(0.6)  # 温和节流，避免触发免费层限制

    out = RAW_PATH / "cocktails_raw.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(list(all_drinks.values()), f, ensure_ascii=False, indent=2)

    print(f"\n完成: 共 {len(all_drinks)} 款饮品 -> {out}")


if __name__ == "__main__":
    main()
