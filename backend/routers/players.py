import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from utils import get_player_or_404

logger = logging.getLogger("cardboard.players")
router = APIRouter(prefix="/api/players", tags=["players"])


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
    results = []
    for player, cnt, wins in rows:
        r = schemas.PlayerResponse.model_validate(player)
        r.session_count = cnt
        r.win_count = wins
        results.append(r)
    return results


@router.post("/", response_model=schemas.PlayerResponse, status_code=201)
def create_player(player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Player).filter(models.Player.name == player.name).first()
    if existing:
        r = schemas.PlayerResponse.model_validate(existing)
        r.session_count = 0
        return JSONResponse(
            content=r.model_dump(mode="json"),
            status_code=200,
        )
    db_player = models.Player(name=player.name)
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    logger.info("Player created: %r", db_player.name)
    r = schemas.PlayerResponse.model_validate(db_player)
    r.session_count = 0
    return r


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
    r = schemas.PlayerResponse.model_validate(player)
    r.session_count = cnt or 0
    r.win_count = wins or 0
    return r


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
        db.query(models.Player.id, models.Player.name, func.count().label("co_count"))
        .join(models.SessionPlayer, models.SessionPlayer.player_id == models.Player.id)
        .filter(
            models.SessionPlayer.session_id.in_(
                db.query(models.SessionPlayer.session_id)
                .filter(models.SessionPlayer.player_id == player_id)
            ),
            models.Player.id != player_id,
        )
        .group_by(models.Player.id, models.Player.name)
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
    db.delete(player)
    db.commit()
    logger.info("Player deleted: id=%d", player_id)
