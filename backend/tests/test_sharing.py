"""Tests for share token creation and public collection access."""
import pytest
from datetime import datetime, timedelta, timezone


def _make_game(client, name="Shared Game"):
    r = client.post("/api/games/", json={"name": name, "status": "owned"})
    assert r.status_code == 201
    return r.json()["id"]


def test_create_token_no_expiry(client):
    r = client.post("/api/share/tokens")
    assert r.status_code == 201
    data = r.json()
    assert "token" in data
    assert len(data["token"]) > 0
    assert data["expires_at"] is None


def test_create_token_with_expiry(client):
    r = client.post("/api/share/tokens?expires_in=10")
    assert r.status_code == 201
    data = r.json()
    assert data["expires_at"] is not None


def test_create_token_invalid_expiry(client):
    # 7 is not in ALLOWED_EXPIRY_MINUTES = (10, 30, 60)
    r = client.post("/api/share/tokens?expires_in=7")
    assert r.status_code == 400


def test_list_tokens(client):
    client.post("/api/share/tokens")
    r = client.get("/api/share/tokens")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_shared_games_valid_token(client):
    _make_game(client)
    token = client.post("/api/share/tokens").json()["token"]

    r = client.get(f"/api/share/{token}/games")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_shared_games_invalid_token(client):
    r = client.get("/api/share/notarealtoken/games")
    assert r.status_code == 404


def test_delete_token(client):
    token = client.post("/api/share/tokens").json()["token"]
    r = client.delete(f"/api/share/tokens/{token}")
    assert r.status_code == 204
    r2 = client.get(f"/api/share/{token}/games")
    assert r2.status_code == 404
