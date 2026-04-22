"""Tests for the POST /api/games/suggest (game night) endpoint."""
import pytest
from datetime import date, timedelta


def _make_game(client, name, status="owned", **kwargs):
    r = client.post("/api/games/", json={"name": name, "status": status, **kwargs})
    assert r.status_code == 201
    return r.json()["id"]


def _add_session(client, game_id, played_at=None):
    if played_at is None:
        played_at = (date.today() - timedelta(days=90)).isoformat()
    r = client.post(f"/api/games/{game_id}/sessions", json={"played_at": played_at})
    assert r.status_code == 201


def _suggest(client, **kwargs):
    return client.post("/api/games/suggest", json=kwargs)


# ---------------------------------------------------------------------------
# Basic filtering
# ---------------------------------------------------------------------------

def test_suggest_empty_collection(client):
    r = _suggest(client)
    assert r.status_code == 200
    assert r.json() == []


def test_suggest_returns_owned_games_only(client):
    _make_game(client, "Owned Game", status="owned")
    _make_game(client, "Wishlist Game", status="wishlist")
    _make_game(client, "Sold Game", status="sold")
    r = _suggest(client)
    assert r.status_code == 200
    names = [g["name"] for g in r.json()]
    assert "Owned Game" in names
    assert "Wishlist Game" not in names
    assert "Sold Game" not in names


def test_suggest_excludes_expansions(client):
    parent_id = _make_game(client, "Base Game")
    r = client.post("/api/games/", json={"name": "Expansion", "status": "owned", "parent_game_id": parent_id})
    assert r.status_code == 201
    r = _suggest(client)
    names = [g["name"] for g in r.json()]
    assert "Base Game" in names
    assert "Expansion" not in names


def test_suggest_player_count_filter(client):
    _make_game(client, "2-4 Player Game", min_players=2, max_players=4)
    _make_game(client, "6+ Player Game", min_players=6, max_players=8)
    r = _suggest(client, player_count=3)
    names = [g["name"] for g in r.json()]
    assert "2-4 Player Game" in names
    assert "6+ Player Game" not in names


def test_suggest_max_minutes_filter(client):
    _make_game(client, "Quick Game", min_playtime=15, max_playtime=30)
    _make_game(client, "Long Game", min_playtime=120, max_playtime=240)
    r = _suggest(client, max_minutes=60)
    names = [g["name"] for g in r.json()]
    assert "Quick Game" in names
    assert "Long Game" not in names


def test_suggest_returns_at_most_5(client):
    for i in range(8):
        _make_game(client, f"Game {i}")
    r = _suggest(client)
    assert r.status_code == 200
    assert len(r.json()) <= 5


# ---------------------------------------------------------------------------
# Scoring / reasons
# ---------------------------------------------------------------------------

def test_suggest_never_played_scores_higher(client):
    # Never Played: +3 (never played bonus), no rating
    never_id = _make_game(client, "Never Played")
    # Already Played: +0 (has been played), no rating bonus
    played_id = _make_game(client, "Already Played")
    _add_session(client, played_id, played_at=(date.today() - timedelta(days=200)).isoformat())

    r = _suggest(client)
    results = r.json()
    names = [g["name"] for g in results]
    assert "Never Played" in names
    never_idx = names.index("Never Played")
    played_idx = names.index("Already Played")
    # Never-played game should rank higher than already-played game with no rating
    assert never_idx < played_idx


def test_suggest_never_played_reason(client):
    _make_game(client, "Fresh Game")
    r = _suggest(client)
    game = next(g for g in r.json() if g["name"] == "Fresh Game")
    assert "Never Played" in game["reasons"]


def test_suggest_high_rating_reason(client):
    _make_game(client, "Top Rated", user_rating=9.0)
    r = _suggest(client)
    game = next(g for g in r.json() if g["name"] == "Top Rated")
    assert "High Rating" in game["reasons"]


def test_suggest_no_filters_returns_all_owned(client):
    for i in range(3):
        _make_game(client, f"Game {i}")
    r = _suggest(client)
    assert r.status_code == 200
    assert len(r.json()) == 3
