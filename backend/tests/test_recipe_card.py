# -*- coding: utf-8 -*-
"""确定性测试：结构化配方卡 + 收藏。

覆盖：
- 启发式判定：闲聊/短文本不抽卡，像配方的才抽
- LLM 抽取失败 → None（优雅降级）
- 收藏 CRUD + 同名幂等
- SSE done 事件携带 recipe（假图驱动）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

import pytest

from app.db import repositories as repo
from app.services.recipe_card import _looks_like_recipe, extract_recipe_card
from app.services.streaming import stream_agent_response


class TestRecipeHeuristics:
    """启发式预判（不调 LLM）。"""

    def test_looks_like_recipe_yes(self):
        text = "玛格丽特：材料 龙舌兰50ml、君度20ml、青柠汁；步骤 1.加冰摇匀 2.滤入盐边杯"
        assert _looks_like_recipe(text) is True

    def test_looks_like_recipe_no_chitchat(self):
        assert _looks_like_recipe("你好，欢迎光临！") is False

    def test_looks_like_recipe_no_short(self):
        assert _looks_like_recipe("材料与步骤简述") is False  # 太短


class TestExtractFallback:
    def test_llm_failure_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no api key")
        monkeypatch.setattr("app.services.recipe_card.get_llm", boom)
        text = "金汤力：材料 金酒、汤力水；步骤 加冰倒入、搅匀"
        assert extract_recipe_card(text) is None

    def test_non_recipe_returns_none(self, monkeypatch):
        """启发式不过 → 连 get_llm 都不该被调用。"""
        called = []
        def fake_llm(*a, **k):
            called.append(1)
            raise AssertionError("不应调用 LLM")
        monkeypatch.setattr("app.services.recipe_card.get_llm", fake_llm)
        assert extract_recipe_card("你好") is None
        assert called == []


class TestFavorites:
    def test_add_list_remove(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.db.database import init_db
        monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "t.db"))
        init_db()

        card = {"name": "玛格丽特", "spirit_base": "龙舌兰",
                "ingredients": [{"name": "龙舌兰", "amount": "50ml"}]}
        repo.add_favorite("alice", card)
        repo.add_favorite("alice", card)               # 同名幂等
        favs = repo.list_favorites("alice")
        assert len(favs) == 1 and favs[0]["name"] == "玛格丽特"
        assert repo.remove_favorite("alice", "玛格丽特") is True
        assert repo.remove_favorite("alice", "玛格丽特") is False
        assert repo.list_favorites("alice") == []

    def test_favorites_isolation(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.db.database import init_db
        monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "t.db"))
        init_db()
        repo.add_favorite("alice", {"name": "玛格丽特"})
        assert repo.list_favorites("bob") == []


class TestStreamRecipe:
    def test_done_event_carries_recipe(self, monkeypatch, tmp_path):
        """假图产出配方答案 → done 事件带 recipe 字段（LLM 抽卡失败则 null）。"""
        from types import SimpleNamespace
        from app.agents.orchestrator_agent import Intent
        from app.core.config import settings
        from app.db.database import init_db
        monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "t.db"))
        init_db()

        updates = [
            {"orchestrator": {"plan": SimpleNamespace(intent=Intent.RECOMMEND, simple=False)}},
            {"specialists": {"events": ["→ 库存推荐 Agent 开始"]}},
            {"reviewer": {"review_verdict": "pass",
                          "final_answer": "推荐：金汤力\n材料：金酒50ml、汤力水\n步骤：加冰倒入搅匀"}},
        ]
        class FakeGraph:
            def stream(self, initial, stream_mode="updates"):
                yield from updates
        monkeypatch.setattr("app.graph.graph.get_graph", lambda: FakeGraph())

        # 无 API key → 抽卡失败 → recipe=None，但 done 仍正常
        def boom(*a, **k):
            raise RuntimeError("no key")
        monkeypatch.setattr("app.services.recipe_card.get_llm", boom)

        import json
        events = list(stream_agent_response("按库存推荐", user_id="alice"))
        done = [json.loads(e[6:]) for e in events if '"type": "done"' in e]
        assert done and done[0]["answer"].startswith("推荐：金汤力")
        assert done[0].get("recipe") is None        # 降级：纯文本也可用
