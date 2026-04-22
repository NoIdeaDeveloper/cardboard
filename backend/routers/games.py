import certifi
import csv
import glob
import io
import json
import logging
import os
import re
import sqlite3
import ssl
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date as _date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import and_, asc, case, desc, exists, func, or_
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
import models
import schemas
from routers.game_images import delete_all_gallery_images
from utils import validate_url_safety, safe_image_ext, get_game_or_404, validate_file_extension, collection_etag, parse_json_list, safe_write_file, safe_delete_file
from constants import (
    MAX_IMAGE_SIZE, ALLOWED_IMAGE_EXTENSIONS,
    MAX_INSTRUCTIONS_SIZE, ALLOWED_INSTRUCTIONS_EXTENSIONS,
    BGG_IMPORT_MAX_BYTES, BGG_PLAYS_MAX_BYTES, NOTES_MAX_LENGTH,
    CSV_IMPORT_MAX_BYTES, NO_LOCATION_SENTINEL,
)

logger = logging.getLogger("cardboard.games")
router = APIRouter(prefix="/api/games", tags=["games"])


# ---------------------------------------------------------------------------
# BGG rate limiter — token bucket, 10 requests / minute per IP
# ---------------------------------------------------------------------------
import threading as _threading
import collections as _collections

_BGG_RATE_LIMIT = 10          # requests
_BGG_RATE_WINDOW = 60.0       # seconds
_bgg_buckets: dict[str, list[float]] = _collections.defaultdict(list)
_bgg_lock = _threading.Lock()
_bgg_ssl_ctx = ssl.create_default_context(cafile=certifi.where())


def _check_bgg_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - _BGG_RATE_WINDOW
    with _bgg_lock:
        timestamps = _bgg_buckets[ip]
        # Evict old timestamps
        _bgg_buckets[ip] = [t for t in timestamps if t > cutoff]
        if len(_bgg_buckets[ip]) >= _BGG_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many BGG requests — please wait a moment")
        _bgg_buckets[ip].append(now)


def _heat_level(last_played) -> int:
    if not last_played:
        return 0
    days = (_date.today() - last_played).days
    return 3 if days <= 14 else 2 if days <= 60 else 1 if days <= 180 else 0

IMAGES_DIR = os.getenv("IMAGES_DIR", "/app/data/images")
INSTRUCTIONS_DIR = os.getenv("INSTRUCTIONS_DIR", "/app/data/instructions")

# ---------------------------------------------------------------------------
# Image caching
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    """Strip path components and replace unsafe characters."""
    name = os.path.basename(name)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200]  # cap length


_safe_ext = safe_image_ext  # backward-compatible alias


def _cache_game_image(game_id: int, image_url: str) -> None:
    """Download image_url and store locally; update game record. Runs as a background task."""
    if not image_url or image_url.startswith("/api/"):
        return  # already local or empty

    is_valid, err_msg = validate_url_safety(image_url)
    if not is_valid:
        logger.warning("Image cache refused for game %d: %s", game_id, err_msg)
        return

    # Abort early if the URL has already been changed (e.g. user uploaded a file
    # or changed the URL before this background task ran).
    with SessionLocal() as db:
        game = db.query(models.Game).filter(models.Game.id == game_id).first()
        if not game or game.image_url != image_url:
            logger.info("Image cache skipped for game %d: URL has changed", game_id)
            return
        # Mark as pending while the download is in progress
        game.image_cache_status = "pending"
        db.commit()

    os.makedirs(IMAGES_DIR, exist_ok=True)

    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": "Cardboard/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            ext = _safe_ext(image_url, content_type)
            dest = os.path.join(IMAGES_DIR, f"{game_id}{ext}")
            downloaded = 0
            # Write to a temp file first so the destination is never partial.
            with tempfile.NamedTemporaryFile(dir=IMAGES_DIR, delete=False) as tmp:
                tmp_path = tmp.name
                try:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_IMAGE_SIZE:
                            raise ValueError("Remote image exceeds size limit")
                        tmp.write(chunk)
                except Exception:
                    os.unlink(tmp_path)
                    raise
            os.replace(tmp_path, dest)
    except Exception:
        logger.exception("Image cache failed for game %d", game_id)
        _delete_cached_image(game_id)
        with SessionLocal() as db:
            game = db.query(models.Game).filter(models.Game.id == game_id).first()
            if game and game.image_url == image_url:
                game.image_cache_status = "failed"
                db.commit()
        return

    # Verify the URL is still current before updating the DB — the user may have
    # changed or uploaded a new image while we were downloading.
    with SessionLocal() as db:
        game = db.query(models.Game).filter(models.Game.id == game_id).first()
        if game and game.image_url == image_url:
            game.image_url = f"/api/games/{game_id}/image"
            game.image_cached = True
            game.image_ext = ext
            game.image_cache_status = "cached"
            db.commit()
            logger.info("Image cached for game %d", game_id)
        else:
            _delete_cached_image(game_id)
            logger.info("Image cache discarded for game %d: URL changed during download", game_id)


def _instructions_path(game_id: int, filename: str) -> str:
    return os.path.join(INSTRUCTIONS_DIR, f"{game_id}_{os.path.basename(filename)}")


def _verify_within(path: str, directory: str) -> str:
    """Resolve *path* and verify it lives inside *directory*; raise 404 otherwise."""
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(directory) + os.sep):
        raise HTTPException(status_code=404, detail="File not found")
    return real


def _safe_header_filename(name: str) -> str:
    """Strip characters that could enable HTTP header injection from a filename."""
    return name.replace('"', '').replace('\r', '').replace('\n', '')


def _delete_cached_image(game_id: int) -> None:
    for path in glob.glob(os.path.join(IMAGES_DIR, f"{game_id}.*")):
        safe_delete_file(path)


# ---------------------------------------------------------------------------
# Tag junction-table helpers
# ---------------------------------------------------------------------------

# (game_field, tag_model, pivot_model, fk_attr)
_TAG_FIELDS = [
    ("categories", models.Category, models.GameCategory, "category_id"),
    ("mechanics",  models.Mechanic,  models.GameMechanic,  "mechanic_id"),
    ("designers",  models.Designer,  models.GameDesigner,  "designer_id"),
    ("publishers", models.Publisher, models.GamePublisher, "publisher_id"),
    ("labels",     models.Label,     models.GameLabel,     "label_id"),
]


_TAG_FIELD_NAMES = frozenset(f for f, *_ in _TAG_FIELDS)


def _save_tags(game_id: int, data_dict: dict, db: Session) -> None:
    """Sync junction tables for any tag fields present in *data_dict*."""
    try:
        for field, TagModel, PivotModel, fk_attr in _TAG_FIELDS:
            if field not in data_dict:
                continue
            json_str = data_dict[field]
            try:
                raw = json.loads(json_str) if json_str else []
                if not isinstance(raw, list):
                    continue
                # Deduplicate and clean in one pass
                seen: dict[str, None] = {}
                for n in raw:
                    clean = (str(n) if n else "").strip()
                    if clean:
                        seen[clean] = None
                names = list(seen)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON for tag field %s on game %d: %.80s", field, game_id, str(json_str))
                continue

            # Clear existing pivot rows for this game + tag type
            db.query(PivotModel).filter(PivotModel.game_id == game_id).delete()

            if not names:
                continue

            # Batch-fetch all existing tags in one query
            existing = {
                tag.name: tag
                for tag in db.query(TagModel).filter(TagModel.name.in_(names)).all()
            }

            # Bulk-create any tags that don't exist yet, then flush once for IDs
            new_tags = [TagModel(name=name) for name in names if name not in existing]
            if new_tags:
                db.add_all(new_tags)
                db.flush()
                for tag in new_tags:
                    existing[tag.name] = tag

            # Bulk-insert all pivot rows
            db.add_all([PivotModel(game_id=game_id, **{fk_attr: existing[name].id}) for name in names])

        db.flush()
    except Exception as e:
        logger.error("Failed to save tags for game %d: %s", game_id, str(e))
        raise HTTPException(status_code=500, detail="Failed to save tags")


def _load_tags(games, db: Session) -> None:
    """Populate tag attributes on game objects from junction tables (batch).

    Modifies games in-place. Sets each tag field to a JSON-encoded sorted list
    of names; games with no tags get an empty JSON array.
    """
    if not games:
        return
    game_ids = [g.id for g in games]

    for field, TagModel, PivotModel, fk_attr in _TAG_FIELDS:
        # Single batch query per tag type
        rows = (
            db.query(PivotModel.game_id, TagModel.name)
            .join(TagModel, getattr(PivotModel, fk_attr) == TagModel.id)
            .filter(PivotModel.game_id.in_(game_ids))
            .all()
        )
        by_game: dict[int, list[str]] = {}
        for gid, name in rows:
            by_game.setdefault(gid, []).append(name)

        for g in games:
            setattr(g, field, json.dumps(sorted(by_game.get(g.id, []))))


# ---------------------------------------------------------------------------
# Collection CRUD
# ---------------------------------------------------------------------------

def _attach_parent_name(game: models.Game, db: Session) -> schemas.GameResponse:
    """Build a GameResponse with parent_game_name, heat_level, and expansion_count populated."""
    data = schemas.GameResponse.model_validate(game)
    if game.parent_game_id:
        parent = db.query(models.Game).filter(models.Game.id == game.parent_game_id).first()
        data.parent_game_name = parent.name if parent else None
    data.heat_level = _heat_level(game.last_played)
    data.expansion_count = (
        db.query(func.count(models.Game.id))
        .filter(models.Game.parent_game_id == game.id)
        .scalar() or 0
    )
    return data


def build_game_responses(games: list, db: Session) -> list:
    """Batch-populate tags, parent names, expansion counts, and heat levels for a list of Game objects.

    Used by both get_games() and sharing._build_game_list() to avoid duplicating this logic.
    """
    _load_tags(games, db)

    parent_ids = {g.parent_game_id for g in games if g.parent_game_id}
    parent_names: dict[int, str] = {}
    if parent_ids:
        parents = db.query(models.Game.id, models.Game.name).filter(models.Game.id.in_(parent_ids)).all()
        parent_names = {p.id: p.name for p in parents}

    game_ids = [g.id for g in games]
    exp_rows = (
        db.query(models.Game.parent_game_id, func.count(models.Game.id))
        .filter(models.Game.parent_game_id.isnot(None))
        .filter(models.Game.parent_game_id.in_(game_ids))
        .group_by(models.Game.parent_game_id)
        .all()
    )
    expansion_counts = {pid: cnt for pid, cnt in exp_rows}

    results = []
    for g in games:
        row = schemas.GameResponse.model_validate(g)
        if g.parent_game_id:
            row.parent_game_name = parent_names.get(g.parent_game_id)
        row.heat_level = _heat_level(g.last_played)
        row.expansion_count = expansion_counts.get(g.id, 0)
        results.append(row)
    return results


@router.get("/")
def get_games(
    request: Request,
    search: Optional[str] = Query(None, max_length=200),
    sort_by: Optional[str] = Query(None, pattern="^(name|min_playtime|max_playtime|min_players|max_players|difficulty|user_rating|date_added|last_played|status|purchase_price|purchase_date)$"),
    sort_dir: Optional[str] = Query("asc", pattern="^(asc|desc)$"),
    include_expansions: bool = True,
    status: Optional[str] = Query(None, pattern="^(owned|wishlist|sold)$"),
    never_played: bool = False,
    min_players: Optional[int] = Query(None, ge=1),
    max_players: Optional[int] = Query(None, ge=1),
    min_playtime: Optional[int] = Query(None, ge=1),
    max_playtime: Optional[int] = Query(None, ge=1),
    mechanics: Optional[str] = Query(None, max_length=1000),
    categories: Optional[str] = Query(None, max_length=1000),
    location: Optional[str] = Query(None, max_length=255),
    limit: Optional[int] = Query(None, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    etag = collection_etag(db)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    query = db.query(models.Game)

    if not include_expansions:
        query = query.filter(models.Game.parent_game_id.is_(None))

    if search:
        query = query.filter(models.Game.name.ilike(f"%{search}%"))

    if status:
        query = query.filter(models.Game.status == status)

    if never_played:
        query = query.filter(
            models.Game.last_played.is_(None),
            models.Game.status == "owned",
        )

    if min_players is not None:
        query = query.filter(
            or_(models.Game.max_players.is_(None), models.Game.max_players >= min_players)
        )

    if max_players is not None:
        query = query.filter(
            or_(models.Game.min_players.is_(None), models.Game.min_players <= max_players)
        )

    if min_playtime is not None:
        query = query.filter(
            or_(models.Game.max_playtime.is_(None), models.Game.max_playtime >= min_playtime)
        )

    if max_playtime is not None:
        query = query.filter(
            or_(models.Game.min_playtime.is_(None), models.Game.min_playtime <= max_playtime)
        )

    if mechanics:
        mechanic_list = [m.strip() for m in mechanics.split(",") if m.strip()]
        if len(mechanic_list) > 50:
            raise HTTPException(status_code=422, detail="Too many mechanics specified (max 50)")
        if mechanic_list:
            query = query.filter(
                or_(*(
                    exists().where(
                        and_(
                            models.GameMechanic.game_id == models.Game.id,
                            models.GameMechanic.mechanic_id == models.Mechanic.id,
                            models.Mechanic.name == m,
                        )
                    )
                    for m in mechanic_list
                ))
            )

    if location is not None:
        if location == NO_LOCATION_SENTINEL:
            query = query.filter(or_(models.Game.location.is_(None), models.Game.location == ""))
        else:
            query = query.filter(models.Game.location == location)

    if categories:
        category_list = [c.strip() for c in categories.split(",") if c.strip()]
        if len(category_list) > 50:
            raise HTTPException(status_code=422, detail="Too many categories specified (max 50)")
        if category_list:
            query = query.filter(
                or_(*(
                    exists().where(
                        and_(
                            models.GameCategory.game_id == models.Game.id,
                            models.GameCategory.category_id == models.Category.id,
                            models.Category.name == c,
                        )
                    )
                    for c in category_list
                ))
            )

    SORT_COLUMNS = {
        "min_playtime": models.Game.min_playtime,
        "max_playtime": models.Game.max_playtime,
        "min_players": models.Game.min_players,
        "max_players": models.Game.max_players,
        "difficulty": models.Game.difficulty,
        "user_rating": models.Game.user_rating,
        "date_added": models.Game.date_added,
        "last_played": models.Game.last_played,
        "status": models.Game.status,
        "purchase_price": models.Game.purchase_price,
        "purchase_date": models.Game.purchase_date,
    }
    if not sort_by or sort_by == 'name':
        sort_column = case(
            (func.lower(models.Game.name).like('the %'), func.substr(models.Game.name, 5)),
            else_=models.Game.name,
        )
    else:
        sort_column = SORT_COLUMNS.get(sort_by, models.Game.name)
    if sort_dir == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(asc(sort_column))

    total_count = query.count()
    if limit is not None:
        query = query.offset(offset).limit(limit)
    games = query.all()
    results = build_game_responses(games, db)

    resp = JSONResponse(content=[r.model_dump(mode="json") for r in results])
    resp.headers["ETag"] = etag
    resp.headers["X-Total-Count"] = str(total_count)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


# ===== Backup =====

@router.get("/backup")
def download_backup(background_tasks: BackgroundTasks):
    """
    Create a ZIP backup of the database and media files (images, instructions, gallery).
    The ZIP is streamed directly — nothing is persisted to disk permanently.
    """
    data_dir = os.getenv("DATA_DIR", "/app/data")
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/cardboard.db")

    # Strip SQLite URL prefix to get the file path
    db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if not os.path.isabs(db_path):
        db_path = os.path.join("/app", db_path)

    if not os.path.isfile(db_path):
        raise HTTPException(status_code=500, detail="Database file not found")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_filename = f"cardboard-backup-{ts}.zip"

    # Write to a named temp file so FileResponse can seek/stat it
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()

    # Use SQLite backup API — safe with active connections
    db_tmp = tmp.name + ".db"
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(db_tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_tmp, "cardboard.db")
            for subdir in ["images", "instructions", "gallery"]:
                dir_path = os.path.join(data_dir, subdir)
                for f in glob.glob(os.path.join(dir_path, "**"), recursive=True):
                    if os.path.isfile(f):
                        zf.write(f, os.path.relpath(f, data_dir))
    finally:
        if os.path.exists(db_tmp):
            os.remove(db_tmp)

    size_mb = round(os.path.getsize(tmp.name) / 1_048_576, 1)
    logger.info("Backup created: %s (%.1f MB)", zip_filename, size_mb)

    try:
        response = FileResponse(
            tmp.name,
            media_type="application/zip",
            filename=zip_filename,
        )
    except Exception:
        safe_delete_file(tmp.name)
        raise
    background_tasks.add_task(os.remove, tmp.name)
    return response


@router.get("/backup/json")
def download_json_backup(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Export all games and sessions as JSON inside a ZIP (human-readable backup)."""
    data_dir = os.getenv("DATA_DIR", "/app/data")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_filename = f"cardboard-json-backup-{ts}.zip"

    games = db.query(models.Game).all()
    sessions = db.query(models.PlaySession).all()
    session_players = db.query(models.SessionPlayer, models.Player.name).join(
        models.Player, models.Player.id == models.SessionPlayer.player_id
    ).all()

    # Build player names by session
    players_by_session = {}
    for sp, name in session_players:
        players_by_session.setdefault(sp.session_id, []).append(name)

    games_data = [
        {k: v for k, v in g.__dict__.items() if not k.startswith('_')}
        for g in games
    ]
    sessions_data = [
        {
            **{k: v for k, v in s.__dict__.items() if not k.startswith('_')},
            "players": players_by_session.get(s.id, []),
        }
        for s in sessions
    ]

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("games.json", json.dumps(games_data, default=str, indent=2))
            zf.writestr("sessions.json", json.dumps(sessions_data, default=str, indent=2))
            for subdir in ["images", "gallery"]:
                dir_path = os.path.join(data_dir, subdir)
                for f_path in glob.glob(os.path.join(dir_path, "**"), recursive=True):
                    if os.path.isfile(f_path):
                        zf.write(f_path, os.path.join("media", os.path.relpath(f_path, data_dir)))
    except Exception as exc:
        safe_delete_file(tmp.name)
        logger.error("JSON backup failed: %s", exc)
        raise HTTPException(status_code=500, detail="Backup failed. Check server logs for details.")

    logger.info("JSON backup created: %s", zip_filename)

    try:
        response = FileResponse(
            tmp.name,
            media_type="application/zip",
            filename=zip_filename,
        )
    except Exception:
        safe_delete_file(tmp.name)
        raise
    background_tasks.add_task(os.remove, tmp.name)
    return response


RESTORE_MAX_BYTES = 500 * 1024 * 1024  # 500 MB


@router.post("/restore", status_code=200)
async def restore_backup(file: UploadFile = File(...)):
    """
    Restore from a ZIP backup created by GET /api/games/backup.
    The ZIP must contain a `cardboard.db` file.  Media files
    (images/, gallery/, instructions/) are also restored if present.
    The server restarts the database connection after the restore.
    """
    data_dir = os.getenv("DATA_DIR", "/app/data")
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/cardboard.db")
    db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if not os.path.isabs(db_path):
        db_path = os.path.join("/app", db_path)

    validate_file_extension(file.filename or "", {".zip"})

    content = await file.read(RESTORE_MAX_BYTES + 1)
    if len(content) > RESTORE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Backup file too large (max 500 MB)")

    tmp_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        tmp_zip.write(content)
        tmp_zip.close()

        with zipfile.ZipFile(tmp_zip.name, "r") as zf:
            names = zf.namelist()
            if "cardboard.db" not in names:
                raise HTTPException(status_code=422, detail="Invalid backup: cardboard.db not found in ZIP")

            # Restore database
            db_tmp = tmp_zip.name + ".restore.db"
            with zf.open("cardboard.db") as src, open(db_tmp, "wb") as dst:
                dst.write(src.read())

            # Validate it's a real SQLite database
            try:
                conn = sqlite3.connect(db_tmp)
                conn.execute("PRAGMA integrity_check")
                conn.close()
            except Exception:
                raise HTTPException(status_code=422, detail="Invalid backup: database file is corrupt")

            # Atomically replace the database
            os.replace(db_tmp, db_path)

            # Restore media directories (optional — skip missing)
            for arc_path in names:
                # Only restore known subdirs
                if not any(arc_path.startswith(d + "/") for d in ["images", "gallery", "instructions"]):
                    continue
                dest = os.path.join(data_dir, arc_path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(arc_path) as src, open(dest, "wb") as dst:
                    dst.write(src.read())

        logger.info("Restore completed from uploaded backup")
        return {"detail": "Restore successful. Reload the page to see your restored data."}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Restore failed: %s", exc)
        raise HTTPException(status_code=500, detail="Restore failed. The backup may be invalid.")
    finally:
        safe_delete_file(tmp_zip.name)
        if os.path.exists(tmp_zip.name + ".restore.db"):
            safe_delete_file(tmp_zip.name + ".restore.db")


@router.get("/bgg-search")
def bgg_search(request: Request, q: str = Query(..., min_length=1, max_length=200)):
    _check_bgg_rate_limit(request)
    """Search BGG for boardgames matching the query string."""
    url = f"https://boardgamegeek.com/xmlapi2/search?query={urllib.parse.quote(q)}&type=boardgame"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cardboard/1.0"})
        with urllib.request.urlopen(req, timeout=10, context=_bgg_ssl_ctx) as resp:
            content = resp.read(2 * 1024 * 1024)
        root = ET.fromstring(content)
        results = []
        for item in root.findall("item")[:8]:
            bgg_id = int(item.get("id", 0))
            name_el = item.find("name[@type='primary']") or item.find("name")
            name = name_el.get("value", "").strip() if name_el is not None else ""
            year_el = item.find("yearpublished")
            year = year_el.get("value") if year_el is not None else None
            if bgg_id and name:
                results.append({"bgg_id": bgg_id, "name": name, "year_published": int(year) if year else None})
        return results
    except Exception as exc:
        logger.warning("BGG search failed (%s): %s", type(exc).__name__, exc)
        raise HTTPException(status_code=502, detail="BGG search temporarily unavailable")


@router.get("/bgg-fetch/{bgg_id}")
def bgg_fetch(request: Request, bgg_id: int):
    _check_bgg_rate_limit(request)
    """Fetch full BGG metadata for a given BGG ID and return as game fields."""
    item = _fetch_bgg_thing(bgg_id)
    if item is None:
        raise HTTPException(status_code=502, detail="Failed to fetch from BGG")
    data = _parse_bgg_item(item)
    data["bgg_id"] = bgg_id
    return data


@router.get("/{game_id}", response_model=schemas.GameResponse)
def get_game(game_id: int, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    _load_tags([game], db)
    return _attach_parent_name(game, db)


@router.get("/{game_id}/similar", response_model=List[schemas.GameSuggestion])
def get_similar_games(game_id: int, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)

    # Load tags for the source game from junction tables
    game_categories = set(
        name for (name,) in
        db.query(models.Category.name)
        .join(models.GameCategory, models.GameCategory.category_id == models.Category.id)
        .filter(models.GameCategory.game_id == game_id)
        .all()
    )
    game_mechanics = set(
        name for (name,) in
        db.query(models.Mechanic.name)
        .join(models.GameMechanic, models.GameMechanic.mechanic_id == models.Mechanic.id)
        .filter(models.GameMechanic.game_id == game_id)
        .all()
    )

    candidates = (
        db.query(
            models.Game.id, models.Game.name,
            models.Game.min_players, models.Game.max_players,
            models.Game.difficulty, models.Game.image_url,
            models.Game.min_playtime, models.Game.max_playtime,
            models.Game.user_rating, models.Game.last_played,
        )
        .filter(models.Game.id != game_id, models.Game.status == 'owned')
        .all()
    )

    # Batch-load categories and mechanics for all candidates
    candidate_ids = [c.id for c in candidates]
    cat_rows = (
        db.query(models.GameCategory.game_id, models.Category.name)
        .join(models.Category, models.GameCategory.category_id == models.Category.id)
        .filter(models.GameCategory.game_id.in_(candidate_ids))
        .all()
    )
    mech_rows = (
        db.query(models.GameMechanic.game_id, models.Mechanic.name)
        .join(models.Mechanic, models.GameMechanic.mechanic_id == models.Mechanic.id)
        .filter(models.GameMechanic.game_id.in_(candidate_ids))
        .all()
    )
    cats_by_game: dict[int, set] = {}
    for gid, name in cat_rows:
        cats_by_game.setdefault(gid, set()).add(name)
    mechs_by_game: dict[int, set] = {}
    for gid, name in mech_rows:
        mechs_by_game.setdefault(gid, set()).add(name)

    scored = []
    for c in candidates:
        score = 0
        score += len(game_categories & cats_by_game.get(c.id, set()))
        score += len(game_mechanics & mechs_by_game.get(c.id, set())) * 2  # mechanics weighted 2×

        if game.min_players and game.max_players and c.min_players and c.max_players:
            if game.max_players >= c.min_players and c.max_players >= game.min_players:
                score += 1

        if game.difficulty and c.difficulty and abs(game.difficulty - c.difficulty) <= 0.5:
            score += 1

        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    return [
        schemas.GameSuggestion(
            id=c.id,
            name=c.name,
            image_url=c.image_url,
            min_players=c.min_players,
            max_players=c.max_players,
            min_playtime=c.min_playtime,
            max_playtime=c.max_playtime,
            difficulty=c.difficulty,
            user_rating=c.user_rating,
            last_played=c.last_played,
        )
        for _, c in scored[:4]
    ]


def _validate_parent_game_id(parent_id: Optional[int], self_id: Optional[int], db: Session) -> None:
    """Validate parent_game_id: must exist, not self, not itself an expansion."""
    if parent_id is None:
        return
    if self_id is not None and parent_id == self_id:
        raise HTTPException(status_code=400, detail="A game cannot be its own parent")
    parent = db.query(models.Game).filter(models.Game.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=400, detail="Parent game not found")
    if parent.parent_game_id is not None:
        raise HTTPException(status_code=400, detail="Cannot nest expansions — the target game is already an expansion")


@router.post("/", response_model=schemas.GameResponse, status_code=201)
def create_game(
    game: schemas.GameCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    _validate_parent_game_id(game.parent_game_id, None, db)
    data = game.model_dump()

    # Separate tag fields — they live only in junction tables, not on the model
    tag_data = {k: data.pop(k) for k in list(data) if k in _TAG_FIELD_NAMES}

    # Duplicate check: match by BGG ID (if provided) or case-insensitive name
    name = (data.get("name") or "").strip()
    dup_filters = []
    if data.get("bgg_id"):
        dup_filters.append(models.Game.bgg_id == data["bgg_id"])
    if name:
        dup_filters.append(models.Game.name.ilike(name))
    if dup_filters:
        existing = db.query(models.Game).filter(or_(*dup_filters)).first()
        if existing:
            if data.get("bgg_id") and existing.bgg_id == data["bgg_id"]:
                raise HTTPException(
                    status_code=409,
                    detail=f"A game with BGG ID {data['bgg_id']} already exists ('{existing.name}').",
                )
            raise HTTPException(
                status_code=409,
                detail=f"A game named '{existing.name}' already exists.",
            )

    db_game = models.Game(**data)
    db.add(db_game)
    db.flush()
    _save_tags(db_game.id, tag_data, db)
    db.commit()
    db.refresh(db_game)
    _load_tags([db_game], db)
    logger.info("Game added: id=%d name=%r", db_game.id, db_game.name)

    if db_game.image_url and not db_game.image_url.startswith("/api/"):
        db_game.image_cache_status = "pending"
        db.commit()
        background_tasks.add_task(_cache_game_image, db_game.id, db_game.image_url)
    else:
        db_game.image_cache_status = None

    return _attach_parent_name(db_game, db)


@router.patch("/{game_id}", response_model=schemas.GameResponse)
def update_game(
    game_id: int,
    game: schemas.GameUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    db_game = get_game_or_404(game_id, db)

    update_data = game.model_dump(exclude_unset=True)

    if "parent_game_id" in update_data:
        _validate_parent_game_id(update_data["parent_game_id"], game_id, db)

    # If image_url is being explicitly changed, clean up the old cached file first.
    new_image_url = None
    if "image_url" in update_data:
        new_image_url = update_data["image_url"] or None
        update_data["image_url"] = new_image_url  # normalise empty string → None
        if not new_image_url or not new_image_url.startswith("/api/"):
            _delete_cached_image(game_id)
            db_game.image_cached = False

    # Separate tag fields — they live only in junction tables, not on the model
    tag_data = {k: update_data.pop(k) for k in list(update_data) if k in _TAG_FIELD_NAMES}

    for field, value in update_data.items():
        setattr(db_game, field, value)

    _save_tags(game_id, tag_data, db)
    db.commit()
    db.refresh(db_game)
    _load_tags([db_game], db)
    logger.info("Game updated: id=%d name=%r", db_game.id, db_game.name)

    if new_image_url and not new_image_url.startswith("/api/"):
        db_game.image_cache_status = "pending"
        db.commit()
        background_tasks.add_task(_cache_game_image, game_id, new_image_url)
    elif "image_url" in update_data:
        # image_url was explicitly cleared or set to a local path
        db_game.image_cache_status = None
        db.commit()

    return _attach_parent_name(db_game, db)


@router.delete("/{game_id}", status_code=204)
def delete_game(game_id: int, db: Session = Depends(get_db)):
    db_game = get_game_or_404(game_id, db)

    logger.info("Game deleted: id=%d name=%r", db_game.id, db_game.name)

    # Clean up files
    _delete_cached_image(game_id)
    if db_game.instructions_filename:
        safe_delete_file(_instructions_path(game_id, db_game.instructions_filename))
    delete_all_gallery_images(game_id, db)

    # Detach any expansions that had this game as their parent
    db.query(models.Game).filter(models.Game.parent_game_id == game_id)\
        .update({"parent_game_id": None})

    # Delete associated play sessions
    db.query(models.PlaySession).filter(models.PlaySession.game_id == game_id).delete()

    db.delete(db_game)
    db.commit()


# ---------------------------------------------------------------------------
# Cached image endpoint
# ---------------------------------------------------------------------------

@router.get("/{game_id}/image")
def get_game_image(game_id: int, db: Session = Depends(get_db)):
    db_game = db.query(models.Game).filter(models.Game.id == game_id).first()
    if db_game and db_game.image_ext:
        base_dir = os.path.realpath(IMAGES_DIR)
        candidate = os.path.realpath(os.path.join(IMAGES_DIR, f"{game_id}{db_game.image_ext}"))
        if not candidate.startswith(base_dir + os.sep) or not os.path.isfile(candidate):
            raise HTTPException(status_code=404, detail="Image not cached")
        return FileResponse(candidate, headers={"Cache-Control": "public, max-age=604800"})
    # Fallback: glob for images cached before image_ext was introduced
    matches = glob.glob(os.path.join(IMAGES_DIR, f"{game_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Image not cached")
    base_dir = os.path.realpath(IMAGES_DIR)
    candidate = os.path.realpath(matches[0])
    if not candidate.startswith(base_dir + os.sep) or not os.path.isfile(candidate):
        raise HTTPException(status_code=404, detail="Image not cached")
    return FileResponse(candidate, headers={"Cache-Control": "public, max-age=604800"})


# ---------------------------------------------------------------------------
# Image upload endpoint
# ---------------------------------------------------------------------------

@router.post("/{game_id}/image", status_code=204)
async def upload_image(game_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    db_game = get_game_or_404(game_id, db)

    safe_name = _safe_filename(file.filename or "image.jpg")
    ext = validate_file_extension(safe_name, ALLOWED_IMAGE_EXTENSIONS, "Only image files (.jpg, .png, .gif, .webp) are allowed")

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    os.makedirs(IMAGES_DIR, exist_ok=True)
    _delete_cached_image(game_id)

    dest = os.path.join(IMAGES_DIR, f"{game_id}{ext}")
    safe_write_file(dest, content, f"Failed to write image for game {game_id}", "Failed to save image to disk")

    db_game.image_url = f"/api/games/{game_id}/image"
    db_game.image_cached = True
    db_game.image_ext = ext
    db.commit()
    logger.info("Image uploaded for game %d: %s", game_id, safe_name)


@router.delete("/{game_id}/image", status_code=204)
def delete_image(game_id: int, db: Session = Depends(get_db)):
    db_game = get_game_or_404(game_id, db)

    _delete_cached_image(game_id)
    db_game.image_url = None
    db_game.image_cached = False
    db_game.image_ext = None
    db.commit()
    logger.info("Image deleted for game %d", game_id)


# ---------------------------------------------------------------------------
# Instructions endpoints
# ---------------------------------------------------------------------------

@router.post("/{game_id}/instructions", status_code=204)
async def upload_instructions(game_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    db_game = get_game_or_404(game_id, db)

    safe_name = _safe_filename(file.filename or "instructions")
    validate_file_extension(safe_name, ALLOWED_INSTRUCTIONS_EXTENSIONS, "Only .pdf and .txt files are allowed")

    content = await file.read()
    if len(content) > MAX_INSTRUCTIONS_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")

    os.makedirs(INSTRUCTIONS_DIR, exist_ok=True)

    # Remove old file if present
    if db_game.instructions_filename:
        safe_delete_file(_instructions_path(game_id, db_game.instructions_filename))

    dest = _instructions_path(game_id, safe_name)
    safe_write_file(dest, content, f"Failed to write instructions for game {game_id}", "Failed to save instructions to disk")

    db_game.instructions_filename = safe_name
    db.commit()
    logger.info("Instructions uploaded for game %d: %s", game_id, safe_name)


@router.get("/{game_id}/instructions")
def get_instructions(game_id: int, db: Session = Depends(get_db)):
    db_game = get_game_or_404(game_id, db)
    if not db_game.instructions_filename:
        raise HTTPException(status_code=404, detail="No instructions uploaded")

    path = _instructions_path(game_id, db_game.instructions_filename)
    path = _verify_within(path, INSTRUCTIONS_DIR)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Instructions file not found")

    ext = os.path.splitext(db_game.instructions_filename)[1].lower()
    media_type = "application/pdf" if ext == ".pdf" else "text/plain"
    disposition = "inline" if ext == ".pdf" else "attachment"

    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{_safe_header_filename(db_game.instructions_filename)}"',
            "Cache-Control": "public, max-age=604800",
        },
    )


@router.delete("/{game_id}/instructions", status_code=204)
def delete_instructions(game_id: int, db: Session = Depends(get_db)):
    db_game = get_game_or_404(game_id, db)
    if not db_game.instructions_filename:
        raise HTTPException(status_code=404, detail="No instructions to delete")

    safe_delete_file(_instructions_path(game_id, db_game.instructions_filename))
    db_game.instructions_filename = None
    db.commit()
    logger.info("Instructions deleted for game %d", game_id)


# ===== BGG XML Import =====


@router.post("/import/bgg")
async def import_bgg(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import a BoardGameGeek XML collection export (collectionlist format)."""
    content = await file.read(BGG_IMPORT_MAX_BYTES + 1)
    if len(content) > BGG_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.warning("BGG XML import parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid XML file")

    # BGG exports use <items> as root with <item> children, or <boardgames> with <boardgame>
    items = root.findall("item") or root.findall("boardgame")
    if not items:
        raise HTTPException(status_code=400, detail="No game items found in XML — is this a BGG collection export?")

    results = {"imported": 0, "skipped": 0, "errors": []}

    for item in items:
        try:
            # Name: BGG exports have <name sortindex="1">Title</name>
            name_el = item.find("name[@sortindex='1']") or item.find("name")
            name = (name_el.text or "").strip() if name_el is not None else ""
            if not name:
                results["skipped"] += 1
                continue

            # Skip duplicates (case-insensitive by name)
            if db.query(models.Game).filter(
                models.Game.name.ilike(name)
            ).first():
                results["skipped"] += 1
                continue

            # BGG object ID — extract early to skip duplicates before expensive parsing
            bgg_id = None
            try:
                bgg_id_str = item.get("objectid") or ""
                bgg_id = int(bgg_id_str) if bgg_id_str else None
            except (ValueError, TypeError):
                pass

            if bgg_id and db.query(models.Game).filter(models.Game.bgg_id == bgg_id).first():
                results["skipped"] += 1
                continue

            # Status
            status_el = item.find("status")
            status = "owned"
            if status_el is not None:
                if status_el.get("wishlist") == "1":
                    status = "wishlist"
                elif status_el.get("prevowned") == "1":
                    status = "sold"

            # Year
            year_text = item.findtext("yearpublished", "").strip()
            try:
                year = int(year_text) or None
            except ValueError:
                year = None
            if year is not None and not (1800 <= year <= 2099):
                year = None

            # Players / playtime from <stats> attributes
            stats_el = item.find("stats")
            def _int_attr(el, attr):
                if el is None:
                    return None
                try:
                    v = int(el.get(attr, "0") or "0")
                    return v if v > 0 else None
                except ValueError:
                    return None

            min_players  = _int_attr(stats_el, "minplayers")
            max_players  = _int_attr(stats_el, "maxplayers")
            min_playtime = _int_attr(stats_el, "minplaytime")
            max_playtime = _int_attr(stats_el, "maxplaytime")

            # User rating
            user_rating = None
            bgg_rating = None
            rating_el = item.find(".//stats/rating") if stats_el is not None else None
            if rating_el is not None:
                val = rating_el.get("value", "N/A")
                if val not in ("N/A", "0", ""):
                    try:
                        user_rating = round(min(10.0, max(1.0, float(val))), 1)
                    except ValueError:
                        pass
                # BGG community average
                avg_el = rating_el.find("average")
                if avg_el is not None:
                    try:
                        avg_val = float(avg_el.get("value", "0") or "0")
                        bgg_rating = round(min(10.0, max(1.0, avg_val)), 2) if avg_val > 0 else None
                    except (ValueError, TypeError):
                        pass

            # Notes / comment
            notes = (item.findtext("comment") or "").strip() or None

            # Image URL
            image_url = (item.findtext("image") or "").strip()
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            image_url = image_url or None

            game = models.Game(
                name=name,
                status=status,
                year_published=year,
                min_players=min_players,
                max_players=max_players,
                min_playtime=min_playtime,
                max_playtime=max_playtime,
                user_rating=user_rating,
                bgg_id=bgg_id,
                bgg_rating=bgg_rating,
                user_notes=notes,
                image_url=image_url,
            )
            db.add(game)
            results["imported"] += 1

        except (AttributeError, ValueError, TypeError, KeyError, OSError) as exc:
            row_name = locals().get("name") or "unknown"
            results["errors"].append(f"Skipped '{row_name}': {type(exc).__name__}")
            logger.debug("BGG import row error for '%s': %s", row_name, exc)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("BGG import commit failed: %s", exc)
        results["errors"].append("Database commit failed — no games were saved")
    logger.info("BGG import: imported=%d skipped=%d errors=%d", results["imported"], results["skipped"], len(results["errors"]))
    return results


# ===== BGG Metadata Refresh =====

BGG_API_URL = "https://boardgamegeek.com/xmlapi2/thing?id={bgg_id}&stats=1"
BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search?query={query}&type=boardgame&exact=1"


def _fetch_bgg_thing(bgg_id: int) -> Optional[ET.Element]:
    """Fetch BGG XML for a thing ID. Returns the <item> element or None.

    BGG returns HTTP 202 when the request is queued for processing — retries
    up to 3 times with a 2-second delay before giving up.
    """
    url = BGG_API_URL.format(bgg_id=bgg_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cardboard/1.0"})
        content = None
        for attempt in range(3):
            with urllib.request.urlopen(req, timeout=15, context=_bgg_ssl_ctx) as resp:
                if resp.status == 202:
                    logger.info("BGG returned 202 for id=%d, retry %d/3", bgg_id, attempt + 1)
                    time.sleep(2)
                    continue
                content = resp.read(5 * 1024 * 1024)
                break
        if content is None:
            logger.warning("BGG fetch gave up after 3 x 202 for id=%d", bgg_id)
            return None
        root = ET.fromstring(content)
        return root.find("item")
    except Exception as exc:
        logger.warning("BGG fetch failed for id=%d: %s", bgg_id, exc)
        return None


def _parse_bgg_item(item: ET.Element) -> dict:
    """Extract game fields from a BGG <item> element."""
    def _int_val(tag, attr="value"):
        el = item.find(tag)
        if el is None:
            return None
        try:
            v = int(el.get(attr, "0") or el.text or "0")
            return v if v > 0 else None
        except (ValueError, TypeError):
            return None

    def _float_val(tag, attr="value"):
        el = item.find(tag)
        if el is None:
            return None
        try:
            return float(el.get(attr) or el.text or "0")
        except (ValueError, TypeError):
            return None

    # Primary name
    name_el = item.find("name[@type='primary']") or item.find("name")
    name = name_el.get("value", "").strip() if name_el is not None else ""

    # Description
    desc_el = item.find("description")
    description = (desc_el.text or "").strip()[:5000] if desc_el is not None else None

    # Year
    year = _int_val("yearpublished")

    # Players / playtime / difficulty
    min_players = _int_val("minplayers")
    max_players = _int_val("maxplayers")
    min_playtime = _int_val("minplaytime")
    max_playtime = _int_val("maxplaytime")

    difficulty = None
    weight_el = item.find(".//averageweight")
    if weight_el is not None:
        try:
            w = float(weight_el.get("value", "0"))
            difficulty = round(min(5.0, max(1.0, w)), 2) if w > 0 else None
        except (ValueError, TypeError):
            pass

    # BGG community rating
    bgg_rating = None
    avg_el = item.find(".//average")
    if avg_el is not None:
        try:
            r = float(avg_el.get("value", "0"))
            bgg_rating = round(min(10.0, max(1.0, r)), 2) if r > 0 else None
        except (ValueError, TypeError):
            pass

    # Tags
    def _links(link_type):
        return json.dumps([el.get("value", "") for el in item.findall(f"link[@type='{link_type}']") if el.get("value")])

    categories = _links("boardgamecategory")
    mechanics = _links("boardgamemechanic")
    designers = _links("boardgamedesigner")
    publishers = _links("boardgamepublisher")

    # Image
    img_el = item.find("image")
    image_url = (img_el.text or "").strip() if img_el is not None else None
    if image_url and image_url.startswith("//"):
        image_url = "https:" + image_url

    return {
        "name": name,
        "description": description,
        "year_published": year,
        "min_players": min_players,
        "max_players": max_players,
        "min_playtime": min_playtime,
        "max_playtime": max_playtime,
        "difficulty": difficulty,
        "bgg_rating": bgg_rating,
        "categories": categories,
        "mechanics": mechanics,
        "designers": designers,
        "publishers": publishers,
        "image_url": image_url,
    }


@router.post("/{game_id}/refresh-bgg", response_model=schemas.GameResponse)
def refresh_from_bgg(
    game_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Re-fetch metadata from BGG and update the game record."""
    db_game = get_game_or_404(game_id, db)
    if not db_game.bgg_id:
        raise HTTPException(status_code=400, detail="Game has no BGG ID — add it manually first")

    item = _fetch_bgg_thing(db_game.bgg_id)
    if item is None:
        raise HTTPException(status_code=502, detail="Could not fetch data from BoardGameGeek")

    data = _parse_bgg_item(item)
    tag_data = {k: data.pop(k) for k in ["categories", "mechanics", "designers", "publishers"]}

    for field, value in data.items():
        if value is not None:
            setattr(db_game, field, value)

    db.flush()
    _save_tags(game_id, tag_data, db)
    db.commit()
    db.refresh(db_game)
    _load_tags([db_game], db)

    new_image = db_game.image_url
    if new_image and not new_image.startswith("/api/"):
        background_tasks.add_task(_cache_game_image, game_id, new_image)

    logger.info("BGG refresh: game_id=%d bgg_id=%d", game_id, db_game.bgg_id)
    return _attach_parent_name(db_game, db)


# ===== Game Night Suggest =====

@router.post("/suggest", response_model=List[schemas.GameSuggestion])
def suggest_games(body: schemas.SuggestRequest, db: Session = Depends(get_db)):
    """Return up to 5 game suggestions ranked for a game night."""
    from datetime import date, timedelta

    query = db.query(models.Game).filter(
        models.Game.status == "owned",
        models.Game.parent_game_id.is_(None),
    )

    if body.player_count:
        query = query.filter(
            (models.Game.min_players.is_(None)) | (models.Game.min_players <= body.player_count),
            (models.Game.max_players.is_(None)) | (models.Game.max_players >= body.player_count),
        )

    if body.max_minutes:
        query = query.filter(
            (models.Game.min_playtime.is_(None)) | (models.Game.min_playtime <= body.max_minutes),
        )

    games = query.all()

    # Count sessions per game
    session_counts = {
        row.game_id: row.count
        for row in db.query(
            models.PlaySession.game_id,
            func.count(models.PlaySession.id).label("count")
        ).group_by(models.PlaySession.game_id).all()
    }

    today = date.today()
    recent_cutoff = today - timedelta(days=30)

    scored = []
    for g in games:
        score = 0.0
        reasons = []
        count = session_counts.get(g.id, 0)

        if count == 0:
            score += 3
            reasons.append("Never Played")

        if g.user_rating:
            score += g.user_rating / 2
            if g.user_rating >= 8:
                reasons.append("High Rating")

        if g.last_played and g.last_played >= recent_cutoff:
            score -= 1  # played recently, penalise slightly
        elif count > 0 and g.last_played:
            reasons.append("Long Overdue" if (today - g.last_played).days > 180 else "Not Recently Played")

        if body.max_minutes and g.min_playtime and g.min_playtime <= body.max_minutes // 2:
            reasons.append("Quick Game")

        if g.difficulty and g.difficulty <= 2.0:
            reasons.append("Easy to Learn")

        scored.append((score, g, reasons))

    scored.sort(key=lambda x: -x[0])

    results = []
    for score, g, reasons in scored[:5]:
        results.append(schemas.GameSuggestion(
            id=g.id,
            name=g.name,
            image_url=g.image_url,
            min_players=g.min_players,
            max_players=g.max_players,
            min_playtime=g.min_playtime,
            max_playtime=g.max_playtime,
            difficulty=g.difficulty,
            user_rating=g.user_rating,
            last_played=g.last_played,
            reasons=reasons[:3],
        ))
    return results


# ===== BGG Play History Import =====


@router.post("/import/bgg-plays")
async def import_bgg_plays(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import play history from a BGG plays XML export."""
    from routers.sessions import _sync_last_played

    content = await file.read(BGG_PLAYS_MAX_BYTES + 1)
    if len(content) > BGG_PLAYS_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.warning("BGG plays XML import parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid XML file")

    plays = root.findall("play")
    if not plays:
        raise HTTPException(status_code=400, detail="No play records found — is this a BGG plays export?")

    results = {"imported": 0, "skipped": 0, "errors": []}
    affected_game_ids = set()

    for play in plays:
        try:
            item_el = play.find("item")
            if item_el is None:
                results["skipped"] += 1
                continue

            game_name = (item_el.get("name") or "").strip()
            bgg_object_id = item_el.get("objectid")

            # Match game by bgg_id first, then by name
            game = None
            if bgg_object_id:
                try:
                    game = db.query(models.Game).filter(models.Game.bgg_id == int(bgg_object_id)).first()
                except (ValueError, TypeError):
                    pass
            if not game and game_name:
                game = db.query(models.Game).filter(models.Game.name.ilike(game_name)).first()

            if not game:
                results["skipped"] += 1
                continue

            affected_game_ids.add(game.id)

            date_str = play.get("date", "")
            try:
                from datetime import date as date_cls
                played_at = date_cls.fromisoformat(date_str)
            except (ValueError, TypeError):
                results["skipped"] += 1
                continue

            quantity = min(int(play.get("quantity", "1") or "1"), 50)
            player_count = None
            players_el = play.find("players")
            if players_el is not None:
                player_count = len(players_el.findall("player")) or None

            duration = None
            try:
                dur = int(play.get("length", "0") or "0")
                duration = dur if dur > 0 else None
            except (ValueError, TypeError):
                pass

            comment = (play.findtext("comments") or "").strip() or None

            for _ in range(quantity):
                db_session = models.PlaySession(
                    game_id=game.id,
                    played_at=played_at,
                    player_count=player_count,
                    duration_minutes=duration,
                    notes=comment,
                )
                db.add(db_session)
                results["imported"] += 1

        except Exception as exc:
            row_name = locals().get("game_name") or "unknown"
            results["errors"].append(f"Skipped '{row_name}': {type(exc).__name__}")
            logger.debug("BGG plays import row error for '%s': %s", row_name, exc)

    db.flush()
    for gid in affected_game_ids:
        _sync_last_played(gid, db, commit=False)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("BGG plays import commit failed: %s", exc)
        results["errors"].append("Database commit failed — no plays were saved")
        logger.info("BGG plays import: imported=%d skipped=%d errors=%d", results["imported"], results["skipped"], len(results["errors"]))
        return results

    logger.info("BGG plays import: imported=%d skipped=%d errors=%d", results["imported"], results["skipped"], len(results["errors"]))
    return results


# ===== CSV Import =====


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import games from a CSV file. Columns: name, status, user_rating, notes, labels, categories, mechanics."""
    content = await file.read(CSV_IMPORT_MAX_BYTES + 1)
    if len(content) > CSV_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")

    try:
        text_content = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_content))
    except Exception as exc:
        logger.warning("CSV import parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Could not parse CSV file")

    results = {"imported": 0, "skipped": 0, "errors": []}

    VALID_STATUSES = {"owned", "wishlist", "sold"}

    for row in reader:
        try:
            name = (row.get("name") or row.get("Name") or "").strip()
            if not name:
                results["skipped"] += 1
                continue

            if db.query(models.Game).filter(models.Game.name.ilike(name)).first():
                results["skipped"] += 1
                continue

            status_raw = (row.get("status") or row.get("Status") or "owned").strip().lower()
            status = status_raw if status_raw in VALID_STATUSES else "owned"

            user_rating = None
            rating_raw = (row.get("user_rating") or row.get("rating") or "").strip()
            if rating_raw:
                try:
                    user_rating = round(min(10.0, max(1.0, float(rating_raw))), 1)
                except ValueError:
                    pass

            notes_raw = (row.get("notes") or row.get("comment") or "").strip()
            notes = notes_raw[:NOTES_MAX_LENGTH] if notes_raw else None

            def _csv_to_json(val):
                val = (val or "").strip()
                if not val:
                    return None
                items = [x.strip() for x in val.split(";") if x.strip()]
                return json.dumps(items) if items else None

            categories = _csv_to_json(row.get("categories") or row.get("Categories"))
            mechanics = _csv_to_json(row.get("mechanics") or row.get("Mechanics"))
            labels = _csv_to_json(row.get("labels") or row.get("Labels"))

            game = models.Game(
                name=name,
                status=status,
                user_rating=user_rating,
                user_notes=notes,
            )
            db.add(game)
            db.flush()

            tag_data = {}
            if categories:
                tag_data["categories"] = categories
            if mechanics:
                tag_data["mechanics"] = mechanics
            if labels:
                tag_data["labels"] = labels
            if tag_data:
                _save_tags(game.id, tag_data, db)

            db.commit()
            results["imported"] += 1

        except HTTPException as http_exc:
            db.rollback()
            results["errors"].append(f"Row '{name}': {http_exc.detail}")
        except Exception as exc:
            db.rollback()
            logger.debug("CSV import row error for '%s': %s", name, exc)
            results["errors"].append(f"Row '{name}': {type(exc).__name__}")
    logger.info("CSV import: imported=%d skipped=%d errors=%d", results["imported"], results["skipped"], len(results["errors"]))
    return results
