# -*- coding: utf-8 -*-
"""M7 玩法彩蛋：确定性测试（无 LLM / 无 Milvus）。

覆盖：
- gamification  技能树 + 徽章（XP/升级/达成/补发）
- zero_alcohol  零酒模式（基酒替换/结果无酒精）
- daily         每日一酒（同日同杯确定性）/ 趣味挑战
- banquet       晚宴规划（备料换算/酒精预算）
- context       情境感知（时间/天气/心情 → 风味方向）
"""
from __future__ import annotations

import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """隔离数据库：M7 徽章打点写临时库。"""
    monkeypatch.setattr("app.core.config.settings.DATABASE_PATH", str(tmp_path / "m7.db"))
    from app.db.database import init_db
    from app.db.database import db
    init_db()
    with db() as conn:
        conn.execute("INSERT INTO users(id,username) VALUES(1,'unit-user-1')")
        conn.execute("INSERT INTO users(id,username) VALUES(7,'unit-user-7')")
    return tmp_path


# ---------- gamification ----------

class TestGamification:
    def test_xp_rules(self):
        from app.services.gamification import _XP
        assert _XP["chat"] == 2
        assert _XP["favorite"] == 3

    def test_total_xp(self):
        from app.services.gamification import total_xp
        assert total_xp({"chat": 5, "favorite": 2}) == 5 * 2 + 2 * 3

    def test_level_progression(self):
        from app.services.gamification import level_for_xp
        assert level_for_xp(0)["level"] == 1
        assert level_for_xp(50)["level"] == 3          # 60 才是第 4 级
        assert level_for_xp(200)["level"] == 5

    def test_level_bounds(self):
        from app.services.gamification import level_for_xp
        lv = level_for_xp(30)
        assert lv["level"] == 3
        assert lv["next_level"] is not None

    def test_earned_badges_by_threshold(self):
        from app.services.gamification import earned_badges
        bs = earned_badges({"chat": 3, "favorite": 1})
        ids = {b["id"] for b in bs}
        assert "first_hello" in ids          # chat>=1
        assert "chat_10" not in ids          # 3<10

    def test_record_action_earns_badge(self, tmp_db):
        from app.services.gamification import record_action
        r = record_action(user_id=1, action="chat")
        assert r["ok"] is True
        assert any(b["id"] == "first_hello" for b in r["earned"])

    def test_record_unknown_action_ignored(self, tmp_db):
        from app.services.gamification import record_action
        r = record_action(user_id=1, action="nope")
        assert r["ok"] is False
        assert r["earned"] == []

    def test_badge_not_duplicated(self, tmp_db):
        from app.services.gamification import record_action
        record_action(user_id=1, action="chat")
        r2 = record_action(user_id=1, action="chat")
        assert all(b["id"] != "first_hello" for b in r2["earned"])  # 不重复发

    def test_bump_resolves_username(self, tmp_db):
        """业务接口 bump(username, action) 自动建用户并结算徽章。"""
        from app.services.gamification import bump, get_progress, resolve_user
        r = bump("bob", "chat")
        assert r["ok"] is True
        assert any(b["id"] == "first_hello" for b in r["earned"])
        p = get_progress(resolve_user("bob"))
        assert p["earned_count"] == 1
        assert p["stats"]["chat"] == 1

    def test_progress_full_view(self, tmp_db):
        from app.services.gamification import get_progress, record_action
        record_action(user_id=7, action="chat")
        record_action(user_id=7, action="favorite")
        p = get_progress(7)
        assert p["xp"] > 0
        assert p["level"]["level"] >= 1
        assert p["earned_count"] == 1          # chat=1→first_hello；favorite=1 未达 5
        assert any(b["id"] == "first_hello" and b["earned"] for b in p["badges"])


# ---------- zero_alcohol ----------

class TestZeroAlcohol:
    def test_mocktailize_removes_alcohol(self):
        from app.services.zero_alcohol import get_cocktail, mocktailize
        recipe = get_cocktail("Mojito")
        assert recipe is not None
        m = mocktailize(recipe)
        assert m["alcohol_free"] is True
        assert m["abv_estimate"] == 0
        assert m["base_swap"] is not None

    def test_mocktail_replaces_spirit(self):
        from app.services.zero_alcohol import get_cocktail, mocktailize
        recipe = get_cocktail("Mojito")
        m = mocktailize(recipe)
        names = [i["name"].lower() for i in m["ingredients"]]
        assert not any("rum" in n for n in names)      # 朗姆被替换
        assert m["replaced"]                              # 记录替换过程

    def test_mocktail_keeps_original(self):
        from app.services.zero_alcohol import get_cocktail, mocktailize
        recipe = get_cocktail("Mojito")
        m = mocktailize(recipe)
        assert m["name"] == "Mojito"                       # 原数据未被改
        assert recipe["alcoholic"] is True

    def test_list_mocktailable_nonempty(self):
        from app.services.zero_alcohol import list_mocktailable
        items = list_mocktailable()
        assert len(items) > 0

    def test_get_cocktail_case_insensitive(self):
        from app.services.zero_alcohol import get_cocktail
        assert get_cocktail("mojito")["name"] == "Mojito"
        assert get_cocktail("不存在的酒") is None


# ---------- daily ----------

class TestDaily:
    def test_same_day_same_cocktail(self):
        from app.services.daily import daily_cocktail
        a = daily_cocktail("2026-08-05")
        b = daily_cocktail("2026-08-05")
        assert a["recipe"]["name"] == b["recipe"]["name"]

    def test_different_day_different_seed(self):
        from app.services.daily import daily_cocktail
        # 种子不同即可（允许小概率同名）
        a = daily_cocktail("2026-08-05")
        b = daily_cocktail("2026-08-06")
        assert a["date"] != b["date"]

    def test_challenge_has_two_ingredients(self):
        from app.services.daily import daily_challenge
        c = daily_challenge()
        assert c["ingredient_a"] != c["ingredient_b"]
        assert "挑战" in c["title"]

    def test_challenge_deterministic(self):
        from app.services.daily import daily_challenge
        assert daily_challenge("2026-01-01")["title"] == daily_challenge("2026-01-01")["title"]


# ---------- banquet ----------

class TestBanquet:
    def test_scale_by_headcount(self):
        from app.services.banquet import plan_banquet
        p = plan_banquet(["Mojito"], headcount=4)
        mojito = p["cocktails"][0]
        assert "error" not in mojito              # 配方存在
        # 每杯每份 ×4 人
        per_person = mojito["ingredients"][0]["per_person"]
        for_n = mojito["ingredients"][0]["for_n"]
        assert abs(for_n - per_person * 4) < 1e-6

    def test_spirit_budget_nonnegative(self):
        from app.services.banquet import plan_banquet
        p = plan_banquet(["Mojito"], headcount=2)
        assert p["cocktails"][0]["total_spirit_ml"] >= 0

    def test_unknown_recipe_reports_error(self):
        from app.services.banquet import plan_banquet
        p = plan_banquet(["不存在"], headcount=2)
        assert "error" in p["cocktails"][0]

    def test_mocktail_mode_has_no_spirit(self):
        from app.services.banquet import plan_banquet
        p = plan_banquet(["Mojito"], headcount=2, mocktail=True)
        assert p["cocktails"][0]["alcohol_free"] is True
        assert p["cocktails"][0]["total_spirit_ml"] == 0

    def test_headcount_floor(self):
        from app.services.banquet import plan_banquet
        p = plan_banquet(["Mojito"], headcount=0)
        assert p["headcount"] == 1


# ---------- context ----------

class TestContext:
    def test_hot_happy_evening(self):
        from app.services.context import situational_profile
        p = situational_profile(time_of_day="evening", weather="hot", mood="happy")
        assert p["keywords"]
        assert p["reasons"]

    def test_unknown_inputs_fallback(self):
        from app.services.context import situational_profile
        p = situational_profile(time_of_day="???", weather="", mood="")
        assert p["keywords"] == ["经典", "均衡"]

    def test_empty_returns_fallback(self):
        from app.services.context import situational_profile
        assert situational_profile()["keywords"] == ["经典", "均衡"]

    def test_mood_sad_is_warm(self):
        from app.services.context import situational_profile
        p = situational_profile(mood="sad")
        assert "温暖" in p["keywords"]
