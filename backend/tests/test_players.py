"""Tests for the players CRUD endpoints."""
import pytest


def _make_game(client, name="Test Game"):
    r = client.post("/api/games/", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


def _make_player(client, name="Alice"):
    r = client.post("/api/players/", json={"name": name})
    assert r.status_code in (200, 201)
    return r.json()["id"]


def _add_session(client, game_id, player_names=None, played_at="2024-01-15"):
    payload = {"played_at": played_at}
    if player_names:
        payload["player_names"] = player_names
    r = client.post(f"/api/games/{game_id}/sessions", json=payload)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# GET /api/players/
# ---------------------------------------------------------------------------

def test_list_players_empty(client):
    r = client.get("/api/players/")
    assert r.status_code == 200
    assert r.json() == []


def test_list_players_sorted_alphabetically(client):
    client.post("/api/players/", json={"name": "Zara"})
    client.post("/api/players/", json={"name": "Alice"})
    client.post("/api/players/", json={"name": "Mike"})
    r = client.get("/api/players/")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert names == sorted(names)


def test_list_players_includes_session_count(client):
    gid = _make_game(client)
    _add_session(client, gid, player_names=["Alice", "Bob"])
    r = client.get("/api/players/")
    assert r.status_code == 200
    players = {p["name"]: p["session_count"] for p in r.json()}
    assert players["Alice"] == 1
    assert players["Bob"] == 1


# ---------------------------------------------------------------------------
# POST /api/players/
# ---------------------------------------------------------------------------

def test_create_player(client):
    r = client.post("/api/players/", json={"name": "Alice"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Alice"
    assert data["session_count"] == 0


def test_create_player_duplicate_returns_existing(client):
    r1 = client.post("/api/players/", json={"name": "Alice"})
    assert r1.status_code == 201
    r2 = client.post("/api/players/", json={"name": "Alice"})
    # Duplicate returns 200 (idempotent), not 409
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]


def test_create_player_strips_whitespace(client):
    r = client.post("/api/players/", json={"name": "  Bob  "})
    assert r.status_code == 201
    assert r.json()["name"] == "Bob"


# ---------------------------------------------------------------------------
# PATCH /api/players/{player_id}
# ---------------------------------------------------------------------------

def test_rename_player(client):
    pid = _make_player(client, "Alice")
    r = client.patch(f"/api/players/{pid}", json={"name": "Alicia"})
    assert r.status_code == 200
    assert r.json()["name"] == "Alicia"


def test_rename_player_empty_name(client):
    pid = _make_player(client, "Alice")
    r = client.patch(f"/api/players/{pid}", json={"name": "   "})
    assert r.status_code == 422


def test_rename_player_conflict(client):
    pid = _make_player(client, "Alice")
    _make_player(client, "Bob")
    r = client.patch(f"/api/players/{pid}", json={"name": "Bob"})
    assert r.status_code == 409


def test_rename_player_not_found(client):
    r = client.patch("/api/players/99999", json={"name": "Ghost"})
    assert r.status_code == 404


def test_rename_player_preserves_session_count(client):
    gid = _make_game(client)
    _add_session(client, gid, player_names=["Alice"])
    players = client.get("/api/players/").json()
    pid = next(p["id"] for p in players if p["name"] == "Alice")
    r = client.patch(f"/api/players/{pid}", json={"name": "Alicia"})
    assert r.status_code == 200
    assert r.json()["session_count"] == 1


# ---------------------------------------------------------------------------
# DELETE /api/players/{player_id}
# ---------------------------------------------------------------------------

def test_delete_player(client):
    pid = _make_player(client, "Alice")
    r = client.delete(f"/api/players/{pid}")
    assert r.status_code == 204
    names = [p["name"] for p in client.get("/api/players/").json()]
    assert "Alice" not in names


def test_delete_player_not_found(client):
    r = client.delete("/api/players/99999")
    assert r.status_code == 404
