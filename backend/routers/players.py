import logging
import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from utils import get_player_or_404, safe_delete_file, safe_write_file, validate_file_extension

logger = logging.getLogger("cardboard.players")
router = APIRouter(prefix="/api/players", tags=["players"])

AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _avatars_dir() -> str:
    return os.path.join(os.getenv("DATA_DIR", "/app/data"), "avatars")


def _avatar_path(player: models.Player) -> str:
    return os.path.join(_avatars_dir(), f"{player.id}{player.avatar_ext}")


def _avatar_url(player: models.Player) -> str | None:
    return f"/api/players/{player.id}/avatar" if player.avatar_ext else None


def _build_response(player: models.Player, session_count: int = 0, win_count: int = 0) -> schemas.PlayerResponse:
    r = schemas.PlayerResponse.model_validate(player)
    r.session_count = session_count
    r.win_count = win_count
    r.avatar_url = _avatar_url(player)
    return r


@router.get("/", response_model=List[schemas.PlayerResponse])
def get_players(db: Session = Depends(get_db)):
    session_counts = (
        db.query(models.SessionPlayer.player_id, func.count().label("cnt"))
        .group_by(models.SessionPlayer.player_id)
        .subquery()
    )
    win_counts = (
        db.query(models.Player.id.label("player_id"), func.count().label("wins"))
        .join(models.PlaySession, models.PlaySession.winner == models.Player.name)
        .filter(models.PlaySession.winner.isnot(None))
        .group_by(models.Player.id)
        .subquery()
    )
    rows = (
        db.query(
            models.Player,
            func.coalesce(session_counts.c.cnt, 0).label("session_count"),
            func.coalesce(win_counts.c.wins, 0).label("win_count"),
        )
        .outerjoin(session_counts, models.Player.id == session_counts.c.player_id)
        .outerjoin(win_counts, models.Player.id == win_counts.c.player_id)
        .order_by(models.Player.name)
        .all()
    )
    return [_build_response(player, cnt, wins) for player, cnt, wins in rows]


@router.post("/", response_model=schemas.PlayerResponse, status_code=201)
def create_player(player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Player).filter(models.Player.name == player.name).first()
    if existing:
        return JSONResponse(
            content=_build_response(existing).model_dump(mode="json"),
            status_code=200,
        )
    db_player = models.Player(name=player.name)
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    logger.info("Player created: %r", db_player.name)
    return _build_response(db_player)


@router.patch("/{player_id}", response_model=schemas.PlayerResponse)
def rename_player(player_id: int, data: schemas.PlayerUpdate, db: Session = Depends(get_db)):
    player = get_player_or_404(player_id, db)
    new_name = data.name
    if not new_name:
        raise HTTPException(status_code=422, detail="Name cannot be empty")
    conflict = (
        db.query(models.Player)
        .filter(models.Player.name == new_name, models.Player.id != player_id)
        .first()
    )
    if conflict:
        raise HTTPException(status_code=409, detail="A player with that name already exists")
    player.name = new_name
    db.commit()
    db.refresh(player)
    logger.info("Player renamed: id=%d new_name=%r", player_id, new_name)
    cnt = (
        db.query(func.count())
        .select_from(models.SessionPlayer)
        .filter(models.SessionPlayer.player_id == player_id)
        .scalar()
    )
    wins = (
        db.query(func.count())
        .select_from(models.PlaySession)
        .filter(models.PlaySession.winner == player.name, models.PlaySession.winner.isnot(None))
        .scalar()
    )
    return _build_response(player, cnt or 0, wins or 0)


# ── Avatar endpoints ──────────────────────────────────────────────────────────

@router.get("/{player_id}/avatar")
def get_player_avatar(player_id: int, db: Session = Depends(get_db)):
    player = get_player_or_404(player_id, db)
    if not player.avatar_ext:
        raise HTTPException(status_code=404, detail="No avatar uploaded")
    path = _avatar_path(player)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Avatar file not found")
    return FileResponse(path)


@router.post("/{player_id}/avatar", response_model=schemas.PlayerResponse)
async def upload_player_avatar(
    player_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    player = get_player_or_404(player_id, db)
    ext = validate_file_extension(
        file.filename or "",
        _ALLOWED_AVATAR_EXTS,
        "Only JPG, PNG, WebP, or GIF images are allowed",
    )
    content = await file.read(AVATAR_MAX_BYTES + 1)
    if len(content) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Avatar too large (max 5 MB)")

    os.makedirs(_avatars_dir(), exist_ok=True)

    # Remove old avatar file if it exists and is a different extension
    if player.avatar_ext and player.avatar_ext != ext:
        safe_delete_file(_avatar_path(player))

    player.avatar_ext = ext
    db.commit()

    dest = _avatar_path(player)
    safe_write_file(dest, content, f"Avatar write failed for player {player_id}", "Failed to save avatar")

    logger.info("Avatar uploaded for player id=%d ext=%s", player_id, ext)
    cnt = (
        db.query(func.count())
        .select_from(models.SessionPlayer)
        .filter(models.SessionPlayer.player_id == player_id)
        .scalar()
    )
    wins = (
        db.query(func.count())
        .select_from(models.PlaySession)
        .filter(models.PlaySession.winner == player.name, models.PlaySession.winner.isnot(None))
        .scalar()
    )
    return _build_response(player, cnt or 0, wins or 0)


@router.delete("/{player_id}/avatar", status_code=204)
def delete_player_avatar(player_id: int, db: Session = Depends(get_db)):
    player = get_player_or_404(player_id, db)
    if not player.avatar_ext:
        raise HTTPException(status_code=404, detail="No avatar to delete")
    path = _avatar_path(player)
    player.avatar_ext = None
    db.commit()
    safe_delete_file(path)
    logger.info("Avatar deleted for player id=%d", player_id)


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/{player_id}/stats", response_model=schemas.PlayerStatsResponse)
def get_player_stats(player_id: int, db: Session = Depends(get_db)):
    player = get_player_or_404(player_id, db)

    session_count = (
        db.query(func.count())
        .select_from(models.SessionPlayer)
        .filter(models.SessionPlayer.player_id == player_id)
        .scalar() or 0
    )
    win_count = (
        db.query(func.count())
        .select_from(models.PlaySession)
        .join(models.SessionPlayer, models.SessionPlayer.session_id == models.PlaySession.id)
        .filter(
            models.SessionPlayer.player_id == player_id,
            models.PlaySession.winner == player.name,
            models.PlaySession.winner.isnot(None),
        )
        .scalar() or 0
    )
    last_played_row = (
        db.query(func.max(models.PlaySession.played_at))
        .join(models.SessionPlayer, models.SessionPlayer.session_id == models.PlaySession.id)
        .filter(models.SessionPlayer.player_id == player_id)
        .scalar()
    )

    # Top 3 games by play count for this player
    top_games_rows = (
        db.query(models.Game.id, models.Game.name, func.count().label("play_count"))
        .join(models.PlaySession, models.PlaySession.game_id == models.Game.id)
        .join(models.SessionPlayer, models.SessionPlayer.session_id == models.PlaySession.id)
        .filter(models.SessionPlayer.player_id == player_id)
        .group_by(models.Game.id, models.Game.name)
        .order_by(func.count().desc())
        .limit(3)
        .all()
    )

    # Sessions by month
    sessions_by_month_rows = (
        db.query(
            func.strftime("%Y-%m", models.PlaySession.played_at).label("month"),
            func.count().label("count"),
        )
        .join(models.SessionPlayer, models.SessionPlayer.session_id == models.PlaySession.id)
        .filter(models.SessionPlayer.player_id == player_id)
        .group_by("month")
        .order_by("month")
        .all()
    )

    # All co-players (most sessions in common)
    co_player_rows = (
        db.query(models.Player.id, models.Player.name, models.Player.avatar_ext, func.count().label("co_count"))
        .join(models.SessionPlayer, models.SessionPlayer.player_id == models.Player.id)
        .filter(
            models.SessionPlayer.session_id.in_(
                db.query(models.SessionPlayer.session_id)
                .filter(models.SessionPlayer.player_id == player_id)
            ),
            models.Player.id != player_id,
        )
        .group_by(models.Player.id, models.Player.name, models.Player.avatar_ext)
        .order_by(func.count().desc())
        .all()
    )

    # Head-to-head W/L for each co-player
    rivalry_data = {}
    for c in co_player_rows:
        co_sessions = (
            db.query(models.SessionPlayer.session_id)
            .filter(models.SessionPlayer.player_id == c.id)
            .subquery()
        )
        wins = (
            db.query(func.count())
            .select_from(models.PlaySession)
            .join(models.SessionPlayer, models.SessionPlayer.session_id == models.PlaySession.id)
            .filter(
                models.SessionPlayer.player_id == player_id,
                models.PlaySession.winner == player.name,
                models.PlaySession.winner.isnot(None),
                models.PlaySession.id.in_(co_sessions),
            )
            .scalar() or 0
        )
        losses = (
            db.query(func.count())
            .select_from(models.PlaySession)
            .join(models.SessionPlayer, models.SessionPlayer.session_id == models.PlaySession.id)
            .filter(
                models.SessionPlayer.player_id == player_id,
                models.PlaySession.winner == c.name,
                models.PlaySession.winner.isnot(None),
                models.PlaySession.id.in_(co_sessions),
            )
            .scalar() or 0
        )
        rivalry_data[c.id] = (wins, losses)

    return schemas.PlayerStatsResponse(
        session_count=session_count,
        win_count=win_count,
        last_played=last_played_row,
        top_games=[
            schemas.PlayerTopGame(game_id=g.id, game_name=g.name, play_count=g.play_count)
            for g in top_games_rows
        ],
        most_played_with=[
            schemas.PlayerCoPlayer(
                player_id=c.id,
                player_name=c.name,
                count=c.co_count,
                wins_against=rivalry_data.get(c.id, (0, 0))[0],
                losses_to=rivalry_data.get(c.id, (0, 0))[1],
                avatar_url=f"/api/players/{c.id}/avatar" if c.avatar_ext else None,
            )
            for c in co_player_rows
        ],
        sessions_by_month=[
            schemas.PlayerSessionsByMonth(month=r.month, count=r.count)
            for r in sessions_by_month_rows
        ],
    )


@router.delete("/{player_id}", status_code=204)
def delete_player(player_id: int, db: Session = Depends(get_db)):
    player = get_player_or_404(player_id, db)
    # Clean up avatar file before deleting the player record
    if player.avatar_ext:
        safe_delete_file(_avatar_path(player))
    db.delete(player)
    db.commit()
    logger.info("Player deleted: id=%d", player_id)
