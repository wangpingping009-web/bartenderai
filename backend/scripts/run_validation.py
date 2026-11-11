# -*- coding: utf-8 -*-
"""M1/M2 一键验证：入库 + 检索 + E2E 测试。

当 Milvus 就绪后运行本脚本，即可完成 M1 收尾 + M2 真实验证：
  1. ingest_knowledge.py    数据入库（含向量化，首次会下载 bge-m3）
  2. verify_search.py       混合检索验证（人工看召回质量）
  3. pytest -m e2e          真实检索链路测试（需 .env 配好 LLM key）

用法:
  python backend/scripts/run_validation.py [--reset] [--skip-e2e]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def run_step(title: str, cmd: list[str]) -> int:
    print(f"\n{'=' * 60}\n▶ {title}\n{'=' * 60}")
    return subprocess.run(cmd, cwd=BACKEND, env={"PYTHONPATH": "."}).returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="重建 collection 再入库")
    parser.add_argument("--skip-e2e", action="store_true", help="跳过 E2E 测试（无 LLM key 时）")
    args = parser.parse_args()

    # 1. 入库
    ingest_cmd = [sys.executable, "scripts/ingest_knowledge.py"]
    if args.reset:
        ingest_cmd.append("--reset")
    if run_step("数据入库（向量化 + 写 Milvus）", ingest_cmd) != 0:
        sys.exit("入库失败，终止验证")

    # 2. 检索验证
    if run_step("混合检索验证", [sys.executable, "scripts/verify_search.py",
                                 "青柠 朗姆 薄荷 能调什么"]) != 0:
        sys.exit("检索验证失败")

    # 3. E2E 测试
    if not args.skip_e2e:
        run_step("E2E 测试（真实 LLM + Milvus）", [sys.executable, "-m", "pytest", "-m", "e2e", "-v"])

    print("\n全部完成。若上面检索结果合理，M1 收尾 + M2 验证通过。")


if __name__ == "__main__":
    main()
