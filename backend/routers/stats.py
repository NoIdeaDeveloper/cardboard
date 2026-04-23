import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from constants import NO_LOCATION_SENTINEL
from database import get_db
import models
import schemas
from utils import collection_etag

logger = logging.getLogger("cardboard.stats")
router = APIRouter(prefix="/api", tags=["stats"])


def _status_counts(db: Session) -> dict:
    rows = db.query(models.Game.status, func.count(models.Game.id)).group_by(models.Game.status).all()
    result: dict = {"owned": 0, "wishlist": 0, "sold": 0}
    for status, count in rows:
        key = status or "owned"
        result[key] = result.get(key, 0) + count
    return result


def _iso_month_to_label(iso_month: str) -> str:
    """Convert a 'YYYY-MM' string to a display label like 'Jan 2025'."""
    return date(int(iso_month[:4]), int(iso_month[5:7]), 1).strftime("%b %Y")


@router.get("/stats", response_model=schemas.StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    # ── Game counts ──────────────────────────────────────────────────────────
    by_status = _status_counts(db)
    total_games = sum(by_status.values())

    # ── Session aggregates ───────────────────────────────────────────────────
    session_agg = db.query(
        func.count(models.PlaySession.id),
        func.coalesce(func.sum(models.PlaySession.duration_minutes), 0),
    ).first()
    total_sessions = int(session_agg[0] or 0)
    total_minutes = int(session_agg[1] or 0)
    total_hours = round(total_minutes / 60, 1)
    avg_session_minutes = round(total_minutes / total_sessions, 1) if total_sessions else 0.0

    # ── Most played (top 5 by session count) ────────────────────────────────
    most_played_rows = (
        db.query(
            models.Game.id,
            models.Game.name,
            func.count(models.PlaySession.id).label("count"),
            func.coalesce(func.sum(models.PlaySession.duration_minutes), 0).label("total_minutes"),
        )
        .join(models.Game, models.PlaySession.game_id == models.Game.id)
        .group_by(models.Game.id, models.Game.name)
        .order_by(func.count(models.PlaySession.id).desc())
        .limit(5)
        .all()
    )
    most_played = [
        schemas.MostPlayedEntry(id=gid, name=name, count=count, total_minutes=int(tot_min))
        for gid, name, count, tot_min in most_played_rows
    ]

    # ── Never played ─────────────────────────────────────────────────────────
    never_played_count = (
        db.query(func.count(models.Game.id))
        .outerjoin(models.PlaySession, models.PlaySession.game_id == models.Game.id)
        .filter(models.PlaySession.id.is_(None))
        .filter(models.Game.status == "owned")
        .scalar() or 0
    )

    # ── Average rating ───────────────────────────────────────────────────────
    avg_rating_raw = (
        db.query(func.avg(models.Game.user_rating))
        .filter(models.Game.user_rating.isnot(None))
        .scalar()
    )
    avg_rating = round(float(avg_rating_raw), 1) if avg_rating_raw is not None else None

    # ── Total spent ──────────────────────────────────────────────────────────
    total_spent_raw = (
        db.query(func.sum(models.Game.purchase_price))
        .filter(models.Game.purchase_price.isnot(None))
        .scalar()
    )
    total_spent = round(float(total_spent_raw), 2) if total_spent_raw is not None else None

    # ── Label counts (via junction tables) ──────────────────────────────────────
    label_rows = (
        db.query(models.Label.name, func.count(models.GameLabel.game_id))
        .join(models.GameLabel, models.Label.id == models.GameLabel.label_id)
        .group_by(models.Label.name)
        .all()
    )
    label_counts: dict = {name: count for name, count in label_rows}

    # ── Rating distribution ───────────────────────────────────────────────────
    r = models.Game.user_rating
    (b1, b2, b3, b4, b5) = db.query(
        func.count(case((r <= 2,  1))),
        func.count(case(((r >= 3) & (r <= 4),  1))),
        func.count(case(((r >= 5) & (r <= 6),  1))),
        func.count(case(((r >= 7) & (r <= 8),  1))),
        func.count(case((r >= 9,  1))),
    ).filter(r.isnot(None)).one()
    buckets = {"1–2": b1, "3–4": b2, "5–6": b3, "7–8": b4, "9–10": b5}

    # ── Build 12-month skeleton (reused for games and sessions) ──────────────
    today = date.today()
    month_keys: list = []
    window_start = None
    for i in range(11, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        d = date(year, month, 1)
        if window_start is None:
            window_start = d
        month_keys.append(d.strftime("%b %Y"))

    # ── Added by month (SQL GROUP BY — avoids full table scan in Python) ──────
    month_counts: dict = {k: 0 for k in month_keys}
    for iso_month, count in db.query(
        func.strftime("%Y-%m", models.Game.date_added).label("month"),
        func.count(models.Game.id).label("count"),
    ).filter(
        models.Game.date_added.isnot(None),
        models.Game.date_added >= window_start,
    ).group_by("month").all():
        key = _iso_month_to_label(iso_month)
        if key in month_counts:
            month_counts[key] += count

    added_by_month = [
        schemas.AddedByMonthEntry(month=m, count=c)
        for m, c in month_counts.items()
    ]

    # ── Sessions by month (SQL GROUP BY) ──────────────────────────────────────
    session_month_counts: dict = {k: 0 for k in month_keys}
    session_month_game_ids: dict = {k: set() for k in month_keys}
    for game_id, iso_month, count in db.query(
        models.PlaySession.game_id,
        func.strftime("%Y-%m", models.PlaySession.played_at).label("month"),
        func.count(models.PlaySession.id).label("count"),
    ).filter(
        models.PlaySession.played_at.isnot(None),
        models.PlaySession.played_at >= window_start,
    ).group_by(
        models.PlaySession.game_id, "month"
    ).all():
        key = _iso_month_to_label(iso_month)
        if key in session_month_counts:
            session_month_counts[key] += count
            session_month_game_ids[key].add(game_id)

    sessions_by_month = [
        schemas.SessionsByMonthEntry(month=m, count=c, game_ids=sorted(session_month_game_ids[m]))
        for m, c in session_month_counts.items()
    ]

    # ── Recent sessions (last 10) ─────────────────────────────────────────────
    recent_rows = (
        db.query(models.PlaySession, models.Game.name)
        .join(models.Game, models.PlaySession.game_id == models.Game.id)
        .order_by(models.PlaySession.played_at.desc(), models.PlaySession.date_added.desc())
        .limit(10)
        .all()
    )
    recent_sessions = [
        schemas.RecentSessionEntry(
            game_id=s.game_id,
            game_name=name,
            played_at=s.played_at,
            player_count=s.player_count,
            duration_minutes=s.duration_minutes,
        )
        for s, name in recent_rows
    ]

    # ── Session counts per game ─────────────────────────────────────────────
    session_counts_rows = (
        db.query(models.PlaySession.game_id, func.count(models.PlaySession.id))
        .group_by(models.PlaySession.game_id)
        .all()
    )
    session_counts = {str(gid): count for gid, count in session_counts_rows}

    # ── Collection value stats ────────────────────────────────────────────────
    owned_priced = (
        db.query(models.Game.id, models.Game.name, models.Game.purchase_price,
                 models.Game.last_played, models.Game.date_added)
        .filter(models.Game.status == "owned", models.Game.purchase_price.isnot(None),
                models.Game.purchase_price > 0)
        .all()
    )
    collection_value = schemas.CollectionValueStats()
    if owned_priced:
        all_prices = [r.purchase_price for r in owned_priced]
        collection_value.owned_total = round(sum(all_prices), 2)
        collection_value.avg_price   = round(sum(all_prices) / len(all_prices), 2)
        unplayed_prices = [r.purchase_price for r in owned_priced if not r.last_played]
        collection_value.unplayed_total = round(sum(unplayed_prices), 2) if unplayed_prices else 0.0

        sc_map: dict[int, int] = {gid: cnt for gid, cnt in session_counts_rows}

        # Best Value by Play: lowest $/session (owned games with ≥1 session)
        bvp = sorted(
            [r for r in owned_priced if sc_map.get(r.id, 0) > 0],
            key=lambda r: r.purchase_price / sc_map[r.id],
        )[:5]
        collection_value.best_value_by_play = [
            schemas.ValueGameEntry(
                id=r.id, name=r.name, purchase_price=r.purchase_price,
                sessions=sc_map[r.id],
                cpp=round(r.purchase_price / sc_map[r.id], 2),
            )
            for r in bvp
        ]

        # Best Value by Time: lowest $/hr (games with logged duration)
        minutes_map: dict[int, int] = {
            gid: int(tot)
            for gid, tot in db.query(
                models.PlaySession.game_id,
                func.coalesce(func.sum(models.PlaySession.duration_minutes), 0),
            )
            .filter(models.PlaySession.game_id.in_([r.id for r in owned_priced]))
            .group_by(models.PlaySession.game_id)
            .all()
            if tot and tot > 0
        }
        bvt = sorted(
            [r for r in owned_priced if minutes_map.get(r.id, 0) > 0],
            key=lambda r: r.purchase_price / (minutes_map[r.id] / 60),
        )[:5]
        collection_value.best_value_by_time = [
            schemas.ValueGameEntry(
                id=r.id, name=r.name, purchase_price=r.purchase_price,
                total_minutes=minutes_map[r.id],
                cph=round(r.purchase_price / (minutes_map[r.id] / 60), 2),
            )
            for r in bvt
        ]

        # Most Expensive Unplayed: top 5 priciest owned, never played
        meu = sorted(
            [r for r in owned_priced if not r.last_played],
            key=lambda r: -r.purchase_price,
        )[:5]
        collection_value.most_expensive_unplayed = [
            schemas.ValueGameEntry(
                id=r.id, name=r.name, purchase_price=r.purchase_price,
                date_added=r.date_added,
            )
            for r in meu
        ]

    # ── Expansion count ──────────────────────────────────────────────────────
    total_expansions = (
        db.query(func.count(models.Game.id))
        .filter(models.Game.parent_game_id.isnot(None))
        .scalar() or 0
    )

    # ── Top players (top 5 by session count) ────────────────────────────────
    top_player_rows = (
        db.query(
            models.Player.id,
            models.Player.name,
            models.Player.avatar_ext,
            func.count(models.SessionPlayer.session_id).label("session_count"),
        )
        .join(models.SessionPlayer, models.SessionPlayer.player_id == models.Player.id)
        .group_by(models.Player.id, models.Player.name, models.Player.avatar_ext)
        .order_by(func.count(models.SessionPlayer.session_id).desc())
        .limit(5)
        .all()
    )
    # Get win counts for these players
    top_player_ids = [r.id for r in top_player_rows]
    win_rows = (
        db.query(models.Player.id, func.count(models.PlaySession.id).label("wins"))
        .join(models.PlaySession, models.PlaySession.winner == models.Player.name)
        .filter(models.Player.id.in_(top_player_ids), models.PlaySession.winner.isnot(None))
        .group_by(models.Player.id)
        .all()
    ) if top_player_ids else []
    win_by_id = {r.id: r.wins for r in win_rows}
    top_players = [
        schemas.TopPlayerEntry(
            player_id=r.id,
            player_name=r.name,
            session_count=r.session_count,
            win_count=win_by_id.get(r.id, 0),
            win_rate=round(win_by_id.get(r.id, 0) / r.session_count * 100) if r.session_count else 0,
            avatar_url=f"/api/players/{r.id}/avatar" if r.avatar_ext else None,
        )
        for r in top_player_rows
    ]

    # ── Sessions by day of week ──────────────────────────────────────────────
    dow_rows = (
        db.query(
            func.strftime("%w", models.PlaySession.played_at).label("dow"),
            func.count(models.PlaySession.id).label("count"),
        )
        .group_by("dow")
        .all()
    )
    # Collect distinct game_ids per DOW for drill-down
    dow_game_rows = (
        db.query(
            func.strftime("%w", models.PlaySession.played_at).label("dow"),
            models.PlaySession.game_id,
        )
        .distinct()
        .all()
    )
    dow_game_ids: dict[int, list[int]] = {}
    for dow_str, game_id in dow_game_rows:
        d = int(dow_str)
        dow_game_ids.setdefault(d, []).append(game_id)
    sessions_by_dow = [
        schemas.SessionsByDowEntry(dow=int(dow), count=count, game_ids=dow_game_ids.get(int(dow), []))
        for dow, count in dow_rows
    ]

    # ── Sessions by day — last 52 weeks ──────────────────────────────────────
    cutoff = today - timedelta(weeks=52)
    day_rows = (
        db.query(
            func.strftime("%Y-%m-%d", models.PlaySession.played_at).label("day"),
            func.count(models.PlaySession.id).label("count"),
        )
        .filter(models.PlaySession.played_at >= cutoff)
        .group_by("day")
        .all()
    )
    # Collect distinct game_ids per day for drill-down
    day_game_rows = (
        db.query(
            func.strftime("%Y-%m-%d", models.PlaySession.played_at).label("day"),
            models.PlaySession.game_id,
        )
        .filter(models.PlaySession.played_at >= cutoff)
        .distinct()
        .all()
    )
    day_game_ids: dict[str, list[int]] = {}
    for day_str, game_id in day_game_rows:
        day_game_ids.setdefault(day_str, []).append(game_id)
    sessions_by_day = [
        schemas.SessionsByDayEntry(date=r.day, count=r.count, game_ids=day_game_ids.get(r.day, []))
        for r in day_rows
    ]

    logger.info("Stats computed: %d games, %d sessions, %d expansions", total_games, total_sessions, total_expansions)

    return schemas.StatsResponse(
        total_games=total_games,
        by_status=by_status,
        total_sessions=total_sessions,
        total_hours=total_hours,
        avg_session_minutes=avg_session_minutes,
        most_played=most_played,
        never_played_count=never_played_count,
        avg_rating=avg_rating,
        total_spent=total_spent,
        label_counts=dict(sorted(label_counts.items(), key=lambda x: -x[1])),
        ratings_distribution=buckets,
        added_by_month=added_by_month,
        sessions_by_month=sessions_by_month,
        recent_sessions=recent_sessions,
        session_counts=session_counts,
        total_expansions=total_expansions,
        top_players=top_players,
        sessions_by_dow=sessions_by_dow,
        sessions_by_day=sessions_by_day,
        collection_value=collection_value,
    )


@router.get("/collection/stats")
def get_collection_stats(request: Request, db: Session = Depends(get_db)):
    etag = collection_etag(db)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    # Status counts
    by_status = _status_counts(db)

    # Total hours from all sessions
    total_minutes_raw = (
        db.query(func.coalesce(func.sum(models.PlaySession.duration_minutes), 0))
        .scalar() or 0
    )
    total_hours = round(int(total_minutes_raw) / 60, 1)

    # Base game vs expansion counts
    expansion_count = (
        db.query(func.count(models.Game.id))
        .filter(models.Game.parent_game_id.isnot(None))
        .scalar() or 0
    )
    base_game_count = by_status["owned"] + by_status["wishlist"] + by_status["sold"] - expansion_count

    # Unplayed owned base games (no sessions ever logged)
    unplayed_count = (
        db.query(func.count(models.Game.id))
        .outerjoin(models.PlaySession, models.PlaySession.game_id == models.Game.id)
        .filter(models.PlaySession.id.is_(None))
        .filter(models.Game.status == "owned")
        .filter(models.Game.parent_game_id.is_(None))
        .scalar() or 0
    )

    # Rated owned games
    rated_count = (
        db.query(func.count(models.Game.id))
        .filter(models.Game.user_rating.isnot(None))
        .filter(models.Game.status == "owned")
        .scalar() or 0
    )

    # Storage locations for owned games, grouped server-side so the frontend
    # can render the full set of rooms regardless of which filter is currently
    # applied to the games list.
    location_rows = (
        db.query(models.Game.location, func.count(models.Game.id))
        .filter(models.Game.status == "owned")
        .group_by(models.Game.location)
        .all()
    )
    locations: dict[str, int] = {}
    for raw_loc, count in location_rows:
        label = (raw_loc or "").strip()
        key = label or NO_LOCATION_SENTINEL
        locations[key] = locations.get(key, 0) + int(count)

    data = schemas.CollectionStatsResponse(
        total_owned=by_status["owned"],
        total_wishlist=by_status["wishlist"],
        total_sold=by_status["sold"],
        base_game_count=base_game_count,
        expansion_count=expansion_count,
        total_hours=total_hours,
        unplayed_count=unplayed_count,
        rated_count=rated_count,
        locations=locations,
    )
    resp = JSONResponse(content=data.model_dump())
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp
