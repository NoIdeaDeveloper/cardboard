"""Tests for game CRUD, list/search/sort, tag roundtrip, and expansion logic."""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_game(client, name="Catan", **kwargs):
    return client.post("/api/games/", json={"name": name, **kwargs})


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_game_minimal(client):
    r = _create_game(client)
    assert r.status_code == 201
    data = r.json()
    assert data["id"] > 0
    assert data["name"] == "Catan"
    assert data["status"] == "owned"


def test_create_game_full(client):
    r = _create_game(
        client,
        name="Wingspan",
        status="wishlist",
        year_published=2019,
        min_players=1,
        max_players=5,
        user_rating=9.0,
        bgg_id=266192,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["year_published"] == 2019
    assert data["bgg_id"] == 266192
    assert data["user_rating"] == 9.0


def test_create_game_duplicate_name_case_insensitive(client):
    _create_game(client, name="Ticket to Ride")
    r = _create_game(client, name="ticket to ride")
    assert r.status_code == 409


def test_create_game_duplicate_bgg_id(client):
    _create_game(client, name="Game A", bgg_id=12345)
    r = _create_game(client, name="Game B", bgg_id=12345)
    assert r.status_code == 409


def test_create_game_invalid_status(client):
    r = _create_game(client, name="Bad Status", status="unknown")
    assert r.status_code == 422


def test_create_game_invalid_rating(client):
    r = _create_game(client, name="Bad Rating", user_rating=11)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def test_get_game(client):
    created = _create_game(client, name="Azul").json()
    r = client.get(f"/api/games/{created['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Azul"


def test_get_game_not_found(client):
    r = client.get("/api/games/99999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_game(client):
    game_id = _create_game(client, name="Pandemic").json()["id"]
    r = client.patch(f"/api/games/{game_id}", json={"user_rating": 8.5, "status": "sold"})
    assert r.status_code == 200
    data = r.json()
    assert data["user_rating"] == 8.5
    assert data["status"] == "sold"
    assert data["name"] == "Pandemic"  # unmodified field preserved


def test_update_game_invalid_rating(client):
    game_id = _create_game(client, name="Scrabble").json()["id"]
    r = client.patch(f"/api/games/{game_id}", json={"user_rating": 11})
    assert r.status_code == 422


def test_update_game_invalid_status(client):
    game_id = _create_game(client, name="Chess").json()["id"]
    r = client.patch(f"/api/games/{game_id}", json={"status": "rented"})
    assert r.status_code == 422


def test_update_game_not_found(client):
    r = client.patch("/api/games/99999", json={"user_rating": 5})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_game(client):
    game_id = _create_game(client, name="Go").json()["id"]
    r = client.delete(f"/api/games/{game_id}")
    assert r.status_code == 204
    assert client.get(f"/api/games/{game_id}").status_code == 404


def test_delete_game_detaches_expansions(client):
    parent_id = _create_game(client, name="Dominion").json()["id"]
    exp_id = _create_game(client, name="Dominion: Intrigue", parent_game_id=parent_id).json()["id"]
    client.delete(f"/api/games/{parent_id}")
    exp = client.get(f"/api/games/{exp_id}").json()
    assert exp["parent_game_id"] is None


# ---------------------------------------------------------------------------
# Expansion validation
# ---------------------------------------------------------------------------

def test_expansion_self_reference(client):
    game_id = _create_game(client, name="Gloomhaven").json()["id"]
    r = client.patch(f"/api/games/{game_id}", json={"parent_game_id": game_id})
    assert r.status_code == 400


def test_expansion_cannot_be_parent_of_another(client):
    """An expansion cannot be set as parent of another game (no nesting)."""
    parent_id = _create_game(client, name="Base Game").json()["id"]
    exp_id = _create_game(client, name="Expansion 1", parent_game_id=parent_id).json()["id"]
    child_id = _create_game(client, name="Expansion 2").json()["id"]
    r = client.patch(f"/api/games/{child_id}", json={"parent_game_id": exp_id})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# List / search / sort / filter
# ---------------------------------------------------------------------------

def test_list_games_returns_all(client):
    _create_game(client, name="Alpha")
    _create_game(client, name="Beta")
    r = client.get("/api/games/")
    assert r.status_code == 200
    names = [g["name"] for g in r.json()]
    assert "Alpha" in names and "Beta" in names


def test_list_games_search(client):
    _create_game(client, name="Chess Odyssey")
    _create_game(client, name="Monopoly")
    r = client.get("/api/games/?search=chess")
    assert r.status_code == 200
    names = [g["name"] for g in r.json()]
    assert "Chess Odyssey" in names
    assert "Monopoly" not in names


def test_list_games_search_matches_designer(client):
    _create_game(client, name="Wingspan", designers='["Elizabeth Hargrave"]')
    _create_game(client, name="Monopoly")
    r = client.get("/api/games/?search=hargrave")
    assert r.status_code == 200
    names = [g["name"] for g in r.json()]
    assert "Wingspan" in names
    assert "Monopoly" not in names


def test_list_games_search_matches_mechanic(client):
    _create_game(client, name="Dominion", mechanics='["Deck Building"]')
    _create_game(client, name="Monopoly", mechanics='["Roll and Move"]')
    r = client.get("/api/games/?search=deck%20building")
    assert r.status_code == 200
    names = [g["name"] for g in r.json()]
    assert "Dominion" in names
    assert "Monopoly" not in names


def test_list_games_search_matches_category(client):
    _create_game(client, name="Twilight Imperium", categories='["Space Exploration"]')
    _create_game(client, name="Monopoly", categories='["Economic"]')
    r = client.get("/api/games/?search=space")
    names = [g["name"] for g in r.json()]
    assert "Twilight Imperium" in names
    assert "Monopoly" not in names


def test_list_games_search_drops_short_stopwords(client):
    """Tokens shorter than 2 chars (e.g. 'a', 'I') don't break the search."""
    _create_game(client, name="Settlers of Catan")
    _create_game(client, name="Monopoly")
    r = client.get("/api/games/?search=a%20catan")
    names = [g["name"] for g in r.json()]
    assert "Settlers of Catan" in names
    assert "Monopoly" not in names


def test_list_games_contains_multiple_statuses(client):
    _create_game(client, name="Owned Game", status="owned")
    _create_game(client, name="Wishlist Game", status="wishlist")
    r = client.get("/api/games/")
    assert r.status_code == 200
    statuses = {g["status"] for g in r.json()}
    assert "owned" in statuses
    assert "wishlist" in statuses


def test_list_games_exclude_expansions(client):
    parent_id = _create_game(client, name="Root").json()["id"]
    _create_game(client, name="Root: Underworld", parent_game_id=parent_id)
    r = client.get("/api/games/?include_expansions=false")
    names = [g["name"] for g in r.json()]
    assert "Root: Underworld" not in names
    assert "Root" in names


# ---------------------------------------------------------------------------
# Tag roundtrip
# ---------------------------------------------------------------------------

def test_tag_roundtrip(client):
    """Tags set via categories JSON are retrievable via junction tables."""
    r = _create_game(client, name="7 Wonders", categories='["Strategy", "Card Game"]')
    assert r.status_code == 201
    game_id = r.json()["id"]
    got = client.get(f"/api/games/{game_id}").json()
    # categories field should be a JSON string of the list
    import json
    cats = json.loads(got["categories"])
    assert "Strategy" in cats
    assert "Card Game" in cats
