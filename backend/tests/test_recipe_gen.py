# -*- coding: utf-8 -*-
"""确定性测试：AI 配方创作（M5 生成-校验-重试闭环）。

成功路径需要真实 LLM → 留 e2e；这里测：
- 人格注册完整 / 未知人格回退 classic
- LLM 失败 → 优雅返回 error（不抛）
- API 端点可达
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.services.recipe_card import Ingredient, RecipeCard
from app.services.recipe_gen import (
    CreativeBrief, CreativeReview, PERSONAS, _CREATE_PROMPT,
    _brief_alignment_issues, generate_recipe,
)


class TestPersonas:
    def test_personas_registered(self):
        assert {"classic", "molecular", "japanese", "playful"} <= set(PERSONAS)

    def test_unknown_persona_falls_back(self, monkeypatch):
        """未知人格 → classic；模型离线时使用明确标注的本地规则创作。"""
        def boom(*a, **k):
            raise RuntimeError("no api key")
        monkeypatch.setattr("app.services.recipe_gen.get_creative_llm", boom)
        r = generate_recipe("清爽夏夜", persona="不存在的")
        assert r["ok"] is True
        assert r["persona"] == "classic"
        assert r["capability_mode"] == "local_rules"
        assert r["review"]["review_mode"] == "rules"

    def test_no_key_builds_validated_local_draft(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no api key")
        monkeypatch.setattr("app.services.recipe_gen.get_creative_llm", boom)
        r = generate_recipe("夏夜慢饮，低甜，柑橘和草本香，不要太酸", base_spirits=["gin"])
        assert r["ok"] is True
        assert r["recipe"]["spirit_base"] == "金酒"
        assert len(r["recipe"]["steps"]) >= 4
        assert r["validation"]["ok"] is True
        assert r["capability_mode"] == "local_rules"
        assert r["recipe"]["name_cn"] == "夏夜草本微光"
        assert r["recipe"]["name"].startswith("Summer Night Juniper")
        assert "本地规则" in " ".join(event["title"] for event in r["collaboration"])
        assert [event["stage"] for event in r["collaboration"]][:4] == [
            "brief", "brief", "evidence", "create",
        ]
        assert r["brief"]["flavor_targets"]["sour"] == 2

    def test_confirmed_inventory_is_preserved_as_hard_creation_contract(self, monkeypatch):
        from app.services.recipe_catalog import canonical

        monkeypatch.setattr("app.services.recipe_gen.get_creative_llm",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        result = generate_recipe(
            "中低甜；中低酸；保留清晰酒感；可使用金酒",
            base_spirits=["gin"],
            creative_brief={
                "sweetness": "中低甜，能尝到甜味但不腻",
                "acidity": "中低酸，有明亮感但不尖锐",
                "alcohol": "保留清晰酒感",
                "base_spirits": ["gin"],
                "available_ingredients": ["gin", "tonic water", "lemon juice"],
                "inventory_complete": True,
            },
        )

        assert result["ok"] is True
        assert result["capability_mode"] == "local_rules"
        allowed = {"gin", "tonic water", "lemon juice"}
        used = {canonical(item["name"]) for item in result["recipe"]["ingredients"]}
        assert used <= allowed
        assert result["brief"]["inventory_complete"] is True
        assert set(result["brief"]["available_ingredients"]) == allowed

    def test_selected_persona_is_part_of_creator_instruction(self):
        messages = _CREATE_PROMPT.format_messages(
            persona_prompt=PERSONAS["japanese"]["prompt"], preferences="低甜",
            base_spirits="gin", references="reference", feedback="first",
            creative_brief='{"flavor_targets":{"sweet":3}}',
            format_instructions="json",
        )
        assert PERSONAS["japanese"]["prompt"] in messages[0].content

    def test_brief_flavor_targets_are_hard_constraints(self):
        brief = CreativeBrief(summary="低甜不酸", flavor_targets={"sweet": 3, "sour": 2})
        issues = _brief_alignment_issues({"flavor": {"sweet": 8, "sour": 6}}, brief)
        assert {issue.code for issue in issues} == {"brief_sweet", "brief_sour"}

    def test_rejected_final_review_is_not_returned_as_success(self, monkeypatch):
        card = RecipeCard(
            name="Review Required", name_cn="待复核配方", spirit_base="金酒",
            ingredients=[Ingredient(name="金酒", amount="45ml"), Ingredient(name="汤力水", amount="90ml")],
            steps=["量取材料。", "杯中加入冰块。", "倒入金酒。", "补入汤力水并轻搅。"],
            glass="高球杯", alcohol_units=1.5, flavor={"sweet": 3},
        )

        class FakeCreatorChain:
            def __or__(self, _other):
                return self

            def invoke(self, _payload):
                return card

        monkeypatch.setattr("app.services.recipe_gen._CREATE_PROMPT", FakeCreatorChain())
        monkeypatch.setattr("app.services.recipe_gen.get_creative_llm", lambda: object())
        monkeypatch.setattr("app.services.recipe_gen._review", lambda *_args: CreativeReview(
            approved=False,
            intent_match="没有满足低甜要求。",
            feasibility="可以制作，但偏离用户目标。",
            issues=["甜味材料比例仍然过高"],
            revision_instruction="降低甜味材料用量。",
        ))

        result = generate_recipe("低甜", persona="japanese")

        assert result["ok"] is False
        assert result["recipe"] is None
        assert result["attempts"] == 3
        assert "甜味材料比例仍然过高" in result["error"]


class TestAPI:
    def test_personas_endpoint(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.db.database import init_db
        monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "t.db"))
        init_db()
        from fastapi.testclient import TestClient
        from app.api.main import app
        with TestClient(app) as client:
            r = client.get("/api/recipes/personas")
            assert r.status_code == 200
            assert len(r.json()["personas"]) == 4

    def test_generate_endpoint_no_key(self, tmp_path, monkeypatch):
        """无 key → 端点返回经过规则校验的明确降级结果。"""
        from app.core.config import settings
        from app.db.database import init_db
        monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "t.db"))
        init_db()
        monkeypatch.setattr("app.services.recipe_gen.get_creative_llm",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no key")))
        from fastapi.testclient import TestClient
        from app.api.main import app
        with TestClient(app) as client:
            from app.core import auth
            _, token = auth.register_user("creator@example.com", "SecurePass123", "Creator")
            auth.verify_email(token)
            login = client.post("/api/auth/login", json={
                "email": "creator@example.com", "password": "SecurePass123",
            })
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            r = client.post("/api/recipes/generate",
                            json={"preferences": "清爽柑橘调", "persona": "molecular"},
                            headers=headers)
            saved = client.get("/api/recipes/creations", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["capability_mode"] == "local_rules"
        assert body["validation"]["ok"] is True
        assert saved.json()["items"][0]["capability_mode"] == "local_rules"

    def test_generate_stream_reports_real_stages(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.db.database import init_db
        monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "stream.db"))
        init_db()
        monkeypatch.setattr("app.services.recipe_gen.get_creative_llm",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        from fastapi.testclient import TestClient
        from app.api.main import app
        with TestClient(app) as client:
            from app.core import auth
            _, token = auth.register_user("stream-creator@example.com", "SecurePass123", "Creator")
            auth.verify_email(token)
            login = client.post("/api/auth/login", json={"email": "stream-creator@example.com", "password": "SecurePass123"})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.post("/api/recipes/generate/stream",
                                   json={"preferences": "低甜草本", "persona": "classic"},
                                   headers=headers)
        assert response.status_code == 200
        assert '"type": "status"' in response.text
        assert '"stage": "brief"' in response.text
        assert '"type": "done"' in response.text
