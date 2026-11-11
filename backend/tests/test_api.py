# -*- coding: utf-8 -*-
"""确定性测试：M4 产品化层（DB 仓储 / API 路由 / SSE 流式编排）。

方法：
- DB 用 tmp_path 临时库（monkeypatch DATABASE_PATH），不污染真实数据
- SSE 流式用 FakeGraph（monkeypatch get_graph），不依赖 LLM/Milvus，
  验证"按节点推进 → 事件顺序 → done 落库"的编排逻辑
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

import pytest
from fastapi.testclient import TestClient

from app.agents.orchestrator_agent import Intent
from app.core.config import settings
from app.db import repositories as repo
from app.db.database import init_db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每个测试用独立临时库。"""
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    return tmp_path


def _authenticated(client: TestClient, email: str = "alice@example.com") -> dict[str, str]:
    """Create a verified account and return an Authorization header."""
    from app.core import auth
    _, verification_token = auth.register_user(email, "SecurePass123", "Alice")
    auth.verify_email(verification_token)
    response = client.post("/api/auth/login", json={"email": email, "password": "SecurePass123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------- 仓储层 ----------

class TestRepositories:
    def test_get_or_create_user(self, tmp_db):
        u = repo.get_or_create_user("alice")
        assert u["username"] == "alice"
        assert repo.get_or_create_user("alice")["id"] == u["id"]  # 幂等

    def test_inventory_crud(self, tmp_db):
        repo.add_inventory_item("alice", "威士忌")
        repo.add_inventory_item("alice", "柠檬")
        repo.add_inventory_item("alice", "威士忌")      # 重名幂等
        assert repo.list_inventory("alice") == ["威士忌", "柠檬"]
        assert repo.remove_inventory_item("alice", "柠檬") is True
        assert repo.remove_inventory_item("alice", "不存在的") is False
        repo.set_inventory("alice", ["金酒", "汤力水"])  # 整体替换
        assert repo.list_inventory("alice") == ["金酒", "汤力水"]

    def test_inventory_isolation_between_users(self, tmp_db):
        repo.add_inventory_item("alice", "威士忌")
        repo.add_inventory_item("bob", "金酒")
        assert repo.list_inventory("alice") == ["威士忌"]
        assert repo.list_inventory("bob") == ["金酒"]

    def test_profile_merge_and_persist(self, tmp_db):
        repo.merge_profile("alice", {"sweetness": 8, "disliked_ingredients": ["vodka"]})
        repo.merge_profile("alice", {"sweetness": 6, "preferred_spirits": ["gin"]})
        p = repo.get_profile("alice")
        assert p["sweetness"] == 6          # 新值覆盖
        assert p["disliked_ingredients"] == ["vodka"]  # 保留旧字段
        assert p["preferred_spirits"] == ["gin"]

    def test_chat_history_roundtrip(self, tmp_db):
        repo.append_chat("alice", "user", "你好")
        repo.append_chat("alice", "assistant", "你好！想调什么酒？")
        hist = repo.list_chat_history("alice")
        assert [h["role"] for h in hist] == ["user", "assistant"]
        assert hist[1]["content"] == "你好！想调什么酒？"


# ---------- 假图（SSE 编排测试用）----------

class FakeGraph:
    """按预设步骤产出的假状态图。"""
    def __init__(self, updates):
        self._updates = updates

    def stream(self, initial, stream_mode="updates"):
        for u in self._updates:
            yield u


def _simple_flow_updates():
    """简单问题流程：总控直答 → done。"""
    return [
        {"orchestrator": {
            "plan": SimpleNamespace(intent=Intent.CHITCHAT, simple=True),
            "direct_answer": "你好！我是调酒助手",
            "events": ["总控判断: chitchat"],
        }},
        {"direct_answer": {"final_answer": "你好！我是调酒助手"}},
    ]


def _multi_agent_flow_updates():
    """复杂问题流程：总控 → 专业 Agent → 审校 pass → done（含回炉）。"""
    return [
        {"orchestrator": {
            "plan": SimpleNamespace(intent=Intent.RECOMMEND, simple=False),
            "events": ["总控判断: recommend"],
        }},
        {"specialists": {
            "events": ["→ 检索 Agent 开始", "检索到 5 条", "→ 库存推荐 Agent 开始"],
        }},
        {"reviewer": {"review_verdict": "revise"}},
        {"revise": {"revise_count": 1, "events": ["[回炉第 1 次] 审校发现问题: 引用不实"]}},
        {"specialists": {"events": ["→ 检索 Agent 开始", "检索到 6 条"]}},
        {"reviewer": {"review_verdict": "pass",
                      "final_answer": "推荐：金汤力（库存可调）",
                      "references": ["金汤力配方", "gin.md"]}},
    ]


# ---------- SSE 流式编排 ----------

class TestStreaming:
    def test_simple_question_stream(self, monkeypatch, tmp_db):
        monkeypatch.setattr("app.graph.graph.get_graph",
                            lambda: FakeGraph(_simple_flow_updates()))
        from app.services.streaming import stream_agent_response
        events = list(stream_agent_response("你好", user_id="alice"))
        text = "\n".join(events)
        assert "思考中" in text
        assert "直接回答" in text          # 准入线：简单问题不走多 Agent
        assert '"type": "done"' in text
        assert "你好！我是调酒助手" in text

    def test_multi_agent_stream_order(self, monkeypatch, tmp_db):
        """事件顺序 = 图节点推进顺序：总控 → 专业 → 审校 → 回炉 → pass。"""
        monkeypatch.setattr("app.graph.graph.get_graph",
                            lambda: FakeGraph(_multi_agent_flow_updates()))
        from app.services.streaming import stream_agent_response
        events = list(stream_agent_response("按库存推荐一杯", user_id="alice"))
        # 只取类型，验证执行链顺序
        import json
        types = [json.loads(e[6:])["type"] for e in events if e.startswith("data: ")]
        assert types[0] == "status"                       # 思考中
        assert "总控判断: recommend" in events[1] if len(events) > 1 else True
        assert '"type": "done"' in events[-1]
        done = json.loads(events[-1][6:])
        assert done["answer"] == "推荐：金汤力（库存可调）"
        assert [item["title"] for item in done["references"]] == ["金汤力配方", "gin.md"]
        assert done["agent_trace"]
        assert any(item["agent"] == "specialists" for item in done["agent_trace"])
        assert any(item["agent"] == "reviewer" for item in done["agent_trace"])
        assert any("回炉第 1 次" in e for e in events)    # 反思自纠可见

    def test_graph_failure_emits_error_not_crash(self, monkeypatch, tmp_db):
        """图执行抛异常 → 优雅 error 事件而非中断。"""
        def boom(*a, **k):
            raise RuntimeError("no api key")
        monkeypatch.setattr("app.graph.graph.get_graph", boom)
        from app.services.streaming import stream_agent_response
        events = list(stream_agent_response("你好", user_id="alice"))
        text = "\n".join(events)
        assert '"type": "error"' in text
        assert "no api key" not in text
        assert "未经验证的内容" in text


# ---------- API 层 ----------

class TestAPI:
    def test_rag_observability_uses_metadata_without_exposing_content(self, tmp_db):
        import json
        from app.api.routes.admin import _rag_observability
        from app.db.database import db

        metadata = {
            "trace_id": "trace-rag-1",
            "capability_mode": "local_retrieval",
            "retrieval": {
                "mode": "local_bm25", "confidence": 0.84,
                "field_coverage": 0.75, "candidate_count": 4,
                "missing_fields": ["steps"],
            },
        }
        with db() as conn:
            conn.execute("INSERT INTO users(username) VALUES(?)", ("rag-admin-test",))
            user_id = conn.execute(
                "SELECT id FROM users WHERE username=?", ("rag-admin-test",),
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO conversations(id,user_id,title) VALUES(?,?,?)",
                ("rag-observe", user_id, "private prompt"),
            )
            conn.execute(
                "INSERT INTO messages(conversation_id,role,content,metadata_json) VALUES(?,?,?,?)",
                ("rag-observe", "assistant", "sensitive answer",
                 json.dumps(metadata, ensure_ascii=False)),
            )

        result = _rag_observability()

        assert result["retrieval_modes"] == {"local_bm25": 1}
        assert result["avg_confidence"] == 0.84
        assert result["recent"][0]["candidate_count"] == 4
        assert "content" not in result["recent"][0]
        assert "sensitive answer" not in json.dumps(result)

    def test_health_degraded_gracefully(self, tmp_db, monkeypatch):
        """Milvus 没起 + 无 API key → 200 degraded（可展示而非报错）。

        显式清空 key：开发机 .env 配了真实 key，不清的话这里测不到"无 key 降级"。
        """
        from app.core.config import settings
        monkeypatch.setattr(settings, "QWEN_API_KEY", "")
        monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("pymilvus.connections.connect",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        from app.api.main import app
        with TestClient(app) as client:
            r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["milvus"] == "down"
        assert body["db"] == "up"
        assert body["graph"] == "up"
        assert body["llm_configured"] is False

    def test_health_reports_deepseek_as_configured_primary(self, tmp_db, monkeypatch):
        """Health output must follow the same provider order used by every Agent."""
        from app.core.config import settings
        from app.core import llm as llm_module

        monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "ds-real-key")
        monkeypatch.setattr(settings, "QWEN_API_KEY", "qw-real-key")
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "")
        monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "")
        monkeypatch.setattr(settings, "LLM_PROVIDER_PRIORITY", "deepseek,qwen,local")
        llm_module._runtime_health.clear()
        monkeypatch.setattr("pymilvus.connections.connect",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

        from app.api.main import app
        with TestClient(app) as client:
            body = client.get("/api/health").json()

        assert body["llm_provider"] == "deepseek"
        assert [item["name"] for item in body["llm_providers"][:2]] == [
            "deepseek", "qwen",
        ]

    def test_inventory_api(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client)
            r = client.put("/api/me/inventory", json={"items": ["威士忌"]}, headers=headers)
            assert r.status_code == 200 and r.json()["items"] == ["威士忌"]
            r = client.get("/api/me/inventory", headers=headers)
            assert r.json()["items"] == ["威士忌"]
            r = client.put("/api/me/inventory", json={"items": []}, headers=headers)
            assert r.json()["items"] == []

    def test_profile_api(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client)
            r = client.patch("/api/me", json={"profile": {"sweetness": 7}}, headers=headers)
            assert r.json()["profile"]["sweetness"] == 7

    def test_chat_stream_endpoint(self, tmp_db, monkeypatch):
        """端到端：POST /api/chat/stream → SSE 流 + 自动落库（会话记忆）。"""
        monkeypatch.setattr("app.graph.graph.get_graph",
                            lambda: FakeGraph(_simple_flow_updates()))
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client)
            conversation = client.post("/api/conversations", json={"title": "新对话"},
                                       headers=headers).json()
            r = client.post(f"/api/conversations/{conversation['id']}/messages/stream",
                            json={"message": "你好"}, headers=headers)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert '"type": "done"' in r.text
        with TestClient(app) as client:
            history = client.get(f"/api/conversations/{conversation['id']}/messages", headers=headers).json()
        assert [item["role"] for item in history["items"]] == ["user", "assistant"]

    def test_favorites_api(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client)
            r = client.post("/api/me/favorites", headers=headers,
                            json={"recipe": {"name": "玛格丽特", "spirit_base": "龙舌兰"}})
            assert r.status_code == 201
            r = client.get("/api/me/favorites", headers=headers)
            assert r.json()["items"][0]["name"] == "玛格丽特"
            r = client.delete("/api/me/favorites/玛格丽特", headers=headers)
            assert r.status_code == 204

    def test_themes_api(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            r = client.get("/api/themes")
            assert r.status_code == 200
            keys = {t["key"] for t in r.json()["themes"]}
            assert {"new_year", "summer_night", "date_night"} <= keys
            r = client.get("/api/themes/summer_night")
            assert r.status_code == 200
            assert len(r.json()["recommendations"]) >= 4
            assert client.get("/api/themes/nope").status_code == 404


# ---------- M7 玩法彩蛋 API ----------

class TestFunAPI:
    def test_daily_and_challenge(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client, "daily@example.com")
            r = client.get("/api/fun/daily", headers=headers)
            assert r.status_code == 200 and r.json()["recipe"]["name"]
            r = client.get("/api/fun/challenge")
            assert r.status_code == 200 and "挑战" in r.json()["title"]

    def test_mocktail_and_banquet(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client, "carol@example.com")
            r = client.post("/api/fun/mocktail?name=Mojito", headers=headers)
            assert r.status_code == 200
            assert r.json()["alcohol_free"] is True
            r = client.post("/api/fun/mocktail?name=不存在", headers=headers)
            assert r.status_code == 404
            r = client.post("/api/fun/banquet", headers=headers,
                            json={"names": ["Mojito"], "headcount": 4})
            assert r.status_code == 200
            assert r.json()["headcount"] == 4

    def test_context_api(self, tmp_db):
        from app.api.main import app
        with TestClient(app) as client:
            r = client.get("/api/fun/context", params={"weather": "hot", "mood": "happy"})
            assert r.status_code == 200 and r.json()["keywords"]
            r = client.get("/api/fun/context")
            assert r.status_code == 200 and r.json()["keywords"] == ["经典", "均衡"]

    def test_gamification_api(self, tmp_db):
        """成长只由真实业务动作累计，不暴露任意加分接口。"""
        from app.api.main import app
        with TestClient(app) as client:
            headers = _authenticated(client, "dave@example.com")
            assert client.post("/api/fun/action?action=chat&username=dave").status_code == 404
            p = client.get("/api/fun/progress", headers=headers).json()
            assert p["xp"] == 0 and p["earned_count"] == 0
