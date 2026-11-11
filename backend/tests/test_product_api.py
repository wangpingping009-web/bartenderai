# -*- coding: utf-8 -*-
"""Deterministic product API tests for authentication and tenant isolation."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.database import init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "product.db"))
    monkeypatch.setattr(settings, "QWEN_API_KEY", "")
    init_db()
    from app.api.main import app
    with TestClient(app) as test_client:
        yield test_client


def _account(client: TestClient, email: str) -> tuple[dict[str, str], str]:
    from app.core import auth
    _, token = auth.register_user(email, "SecurePass123", email.split("@")[0])
    auth.verify_email(token)
    response = client.post("/api/auth/login", json={"email": email, "password": "SecurePass123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, response.cookies.get("bartender_refresh")


def test_register_verify_and_login(client, monkeypatch):
    sent = {}
    monkeypatch.setattr("app.api.routes.auth.send_verification",
                        lambda email, token: sent.update(email=email, token=token))
    response = client.post("/api/auth/register", json={
        "email": "new@example.com", "password": "SecurePass123", "display_name": "New User",
    })
    assert response.status_code == 201
    assert sent["email"] == "new@example.com"
    assert client.post("/api/auth/login", json={
        "email": "new@example.com", "password": "SecurePass123",
    }).status_code == 403
    assert client.post("/api/auth/verify", json={"token": sent["token"]}).status_code == 200
    login = client.post("/api/auth/login", json={
        "email": "new@example.com", "password": "SecurePass123",
    })
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "new@example.com"
    assert login.cookies.get("bartender_refresh")


def test_register_returns_dev_verification_link_when_mail_is_down(client, monkeypatch):
    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.setattr("app.api.routes.auth.send_verification",
                        lambda *_: (_ for _ in ()).throw(OSError("mail down")))
    response = client.post("/api/auth/register", json={
        "email": "offline-mail@example.com", "password": "SecurePass123",
    })
    assert response.status_code == 201
    assert response.json()["verification_url"].startswith(settings.FRONTEND_URL + "/verify?token=")


def test_refresh_rotates_and_rejects_replay(client):
    _, old_refresh = _account(client, "rotate@example.com")
    first = client.post("/api/auth/refresh")
    assert first.status_code == 200
    new_refresh = first.cookies.get("bartender_refresh")
    assert new_refresh and new_refresh != old_refresh

    from app.api.main import app
    with TestClient(app) as replay:
        replay.cookies.set("bartender_refresh", old_refresh, path="/api/auth")
        assert replay.post("/api/auth/refresh").status_code == 401


def test_user_cannot_read_another_users_conversation(client):
    alice, _ = _account(client, "alice-isolation@example.com")
    bob, _ = _account(client, "bob-isolation@example.com")
    conversation = client.post("/api/conversations", json={"title": "Alice private"},
                               headers=alice).json()
    response = client.get(f"/api/conversations/{conversation['id']}/messages", headers=bob)
    assert response.status_code == 404


def test_creation_detail_is_openable_only_by_its_owner(client):
    alice, _ = _account(client, "alice-creation@example.com")
    bob, _ = _account(client, "bob-creation@example.com")
    from app.core.auth import get_user_by_email
    from app.db.database import db

    owner = get_user_by_email("alice-creation@example.com")
    recipe = {"name": "Summer Ink", "name_cn": "盛夏墨彩", "ingredients": [], "steps": []}
    with db() as conn:
        cursor = conn.execute("INSERT INTO creations(user_id,recipe_json) VALUES(?,?)",
                              (owner["id"], json.dumps(recipe, ensure_ascii=False)))
        creation_id = cursor.lastrowid

    response = client.get(f"/api/recipes/creations/{creation_id}", headers=alice)
    assert response.status_code == 200
    assert response.json()["recipe"]["name_cn"] == "盛夏墨彩"
    assert client.get(f"/api/recipes/creations/{creation_id}", headers=bob).status_code == 404
    assert client.delete(f"/api/recipes/creations/{creation_id}", headers=bob).status_code == 404
    assert client.delete(f"/api/recipes/creations/{creation_id}", headers=alice).status_code == 204


def test_feedback_updates_profile_deterministically(client):
    headers, _ = _account(client, "feedback@example.com")
    response = client.post("/api/feedback", headers=headers, json={
        "recipe_id": "11007", "recipe_name": "Margarita", "rating": 2,
        "tags": ["too_sweet", "not-a-real-tag"], "note": "糖浆偏多",
    })
    assert response.status_code == 201
    assert response.json()["profile_updated"] is True
    profile = client.get("/api/me", headers=headers).json()["profile"]
    assert profile["sweetness"] == 3


def test_admin_routes_require_admin_role(client):
    headers, _ = _account(client, "normal@example.com")
    assert client.get("/api/admin/overview", headers=headers).status_code == 403


@pytest.mark.parametrize("content_type", ["text/plain", "image/gif", "application/pdf"])
def test_vision_rejects_unsupported_types(client, content_type):
    headers, _ = _account(client, f"upload-{content_type.replace('/', '-')}@example.com")
    response = client.post("/api/vision/identify", headers=headers,
                           files={"file": ("sample.bin", b"not-an-image", content_type)})
    assert response.status_code == 415
    assert response.json()["request_id"]


def test_vision_checks_magic_before_capability(client):
    headers, _ = _account(client, "magic@example.com")
    invalid = client.post("/api/vision/identify", headers=headers,
                          files={"file": ("sample.png", b"plain text", "image/png")})
    assert invalid.status_code == 400
    valid_signature = client.post("/api/vision/identify", headers=headers,
                                  files={"file": ("sample.png", b"\x89PNG\r\n\x1a\n", "image/png")})
    assert valid_signature.status_code == 503
