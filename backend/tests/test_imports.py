"""Tests for CSV and BGG XML import endpoints."""
import io
import json
import pytest


# ---------------------------------------------------------------------------
# CSV import helpers
# ---------------------------------------------------------------------------

def _csv_upload(client, csv_text: str):
    content = csv_text.encode("utf-8")
    return client.post(
        "/api/games/import/csv",
        files={"file": ("games.csv", io.BytesIO(content), "text/csv")},
    )


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def test_csv_import_basic(client):
    csv_text = "name,status\nCatan,owned\nPandemic,wishlist\n"
    r = _csv_upload(client, csv_text)
    assert r.status_code == 200
    data = r.json()
    assert data["imported"] == 2
    assert data["skipped"] == 0
    assert data["errors"] == []


def test_csv_import_skips_duplicates(client):
    # Create a game first
    client.post("/api/games/", json={"name": "Catan"})
    csv_text = "name\nCatan\nTicket to Ride\n"
    r = _csv_upload(client, csv_text)
    data = r.json()
    assert data["imported"] == 1
    assert data["skipped"] == 1


def test_csv_import_skips_empty_name(client):
    # Use a row with only whitespace as the name — should be skipped
    csv_text = "name\n   \nPandemic\n"
    r = _csv_upload(client, csv_text)
    data = r.json()
    assert data["imported"] == 1
    assert data["skipped"] == 1


def test_csv_import_invalid_rating_still_imports(client):
    csv_text = "name,user_rating\n7 Wonders,not_a_number\n"
    r = _csv_upload(client, csv_text)
    data = r.json()
    assert data["imported"] == 1
    # Verify rating is None
    games = client.get("/api/games/?search=7 Wonders").json()
    assert any(g["user_rating"] is None for g in games if "7 Wonders" in g["name"])


def test_csv_import_with_tags(client):
    csv_text = "name,categories,mechanics\nImperial,Strategy;Economic,Auction;Negotiation\n"
    r = _csv_upload(client, csv_text)
    assert r.json()["imported"] == 1
    games = client.get("/api/games/?search=Imperial").json()
    assert len(games) == 1
    cats = json.loads(games[0]["categories"])
    assert "Strategy" in cats
    assert "Economic" in cats


def test_csv_import_too_large(client):
    # Build a CSV > 5 MB
    big_csv = "name\n" + ("A" * 1000 + "\n") * 6000
    r = _csv_upload(client, big_csv)
    assert r.status_code == 413


def test_csv_import_malformed_encoding(client):
    # Send non-UTF-8 bytes as a CSV
    bad_bytes = b"\xff\xfe" + b"\x00" * 100  # not valid UTF-8
    r = client.post(
        "/api/games/import/csv",
        files={"file": ("bad.csv", io.BytesIO(bad_bytes), "text/csv")},
    )
    assert r.status_code == 400


def test_csv_notes_truncated_at_2000_chars(client):
    long_note = "X" * 3000
    csv_text = f"name,notes\nLong Notes Game,{long_note}\n"
    r = _csv_upload(client, csv_text)
    assert r.json()["imported"] == 1
    games = client.get("/api/games/?search=Long Notes Game").json()
    assert len(games[0]["user_notes"]) <= 2000


# ---------------------------------------------------------------------------
# BGG collection XML import
# ---------------------------------------------------------------------------

_BGG_COLLECTION_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<items totalitems="1" termsofuse="" pubdate="">
  <item objecttype="thing" objectid="174430" subtype="boardgame" collid="1">
    <name sortindex="1">Gloomhaven</name>
    <yearpublished>2017</yearpublished>
    <stats minplayers="1" maxplayers="4" minplaytime="60" maxplaytime="120" numowned="1">
      <rating value="N/A">
        <average value="8.5"/>
      </rating>
    </stats>
    <status own="1" prevowned="0" fortrade="0" want="0" wanttoplay="0" wanttobuy="0" wishlist="0" preordered="0" lastmodified="2024-01-01 00:00:00"/>
  </item>
</items>
"""

_BGG_INVALID_XML = "<not valid xml<<<<"

_BGG_EMPTY_XML = '<?xml version="1.0"?><items totalitems="0"></items>'


def _bgg_upload(client, xml_text: str):
    content = xml_text.encode("utf-8")
    return client.post(
        "/api/games/import/bgg",
        files={"file": ("collection.xml", io.BytesIO(content), "text/xml")},
    )


def test_bgg_import_valid_xml(client):
    r = _bgg_upload(client, _BGG_COLLECTION_XML)
    assert r.status_code == 200
    data = r.json()
    assert data["imported"] == 1
    assert data["errors"] == []
    games = client.get("/api/games/?search=Gloomhaven").json()
    assert len(games) == 1
    assert games[0]["bgg_id"] == 174430
    assert games[0]["year_published"] == 2017


def test_bgg_import_invalid_xml(client):
    r = _bgg_upload(client, _BGG_INVALID_XML)
    assert r.status_code == 400


def test_bgg_import_no_items(client):
    r = _bgg_upload(client, _BGG_EMPTY_XML)
    assert r.status_code == 400


def test_bgg_import_skips_duplicate_name(client):
    _bgg_upload(client, _BGG_COLLECTION_XML)
    r = _bgg_upload(client, _BGG_COLLECTION_XML)
    data = r.json()
    assert data["skipped"] == 1
    assert data["imported"] == 0


def test_bgg_import_skips_duplicate_bgg_id(client):
    """Second import with same objectid but different name is skipped."""
    second_xml = _BGG_COLLECTION_XML.replace(
        "<name sortindex=\"1\">Gloomhaven</name>",
        "<name sortindex=\"1\">Gloomhaven 2nd Edition</name>",
    )
    _bgg_upload(client, _BGG_COLLECTION_XML)
    r = _bgg_upload(client, second_xml)
    data = r.json()
    assert data["skipped"] == 1


def test_bgg_import_year_out_of_range_nullified(client):
    """Years outside 1800-2099 are stored as None."""
    bad_year_xml = _BGG_COLLECTION_XML.replace(
        "<yearpublished>2017</yearpublished>",
        "<yearpublished>0</yearpublished>",
    )
    r = _bgg_upload(client, bad_year_xml)
    assert r.json()["imported"] == 1
    games = client.get("/api/games/?search=Gloomhaven").json()
    assert games[0]["year_published"] is None


# ---------------------------------------------------------------------------
# BGG plays XML import
# ---------------------------------------------------------------------------

_BGG_PLAYS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<plays username="testuser" userid="1" total="1" page="1" termsofuse="">
  <play id="1" date="2024-03-10" quantity="1" length="90" incomplete="0" nowinstats="1" location="">
    <item name="Gloomhaven" objecttype="thing" objectid="174430"/>
    <players/>
  </play>
</plays>
"""


def test_bgg_plays_import(client):
    # First import the game so it can be matched
    _bgg_upload(client, _BGG_COLLECTION_XML)
    r = client.post(
        "/api/games/import/bgg-plays",
        files={"file": ("plays.xml", io.BytesIO(_BGG_PLAYS_XML.encode()), "text/xml")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["imported"] == 1
    # Verify last_played was updated
    games = client.get("/api/games/?search=Gloomhaven").json()
    assert games[0]["last_played"] == "2024-03-10"


def test_bgg_plays_import_skips_unknown_game(client):
    r = client.post(
        "/api/games/import/bgg-plays",
        files={"file": ("plays.xml", io.BytesIO(_BGG_PLAYS_XML.encode()), "text/xml")},
    )
    data = r.json()
    assert data["skipped"] == 1
    assert data["imported"] == 0
