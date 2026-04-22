"""Drop legacy tag TEXT columns from games table

The categories, mechanics, designers, publishers, and labels TEXT columns on
the games table were kept as a dual-write fallback while junction tables were
being introduced. This migration backfills any data that exists only in the
TEXT columns into the junction tables, then drops the TEXT columns.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
import json

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

_TAG_FIELDS = [
    ("categories", "categories",  "game_categories",  "category_id"),
    ("mechanics",  "mechanics",   "game_mechanics",   "mechanic_id"),
    ("designers",  "designers",   "game_designers",   "designer_id"),
    ("publishers", "publishers",  "game_publishers",  "publisher_id"),
    ("labels",     "labels",      "game_labels",      "label_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    game_cols = {c['name'] for c in inspector.get_columns('games')}

    # --- Backfill junction tables from TEXT columns ---
    # For each game that has data in the TEXT column but nothing in the junction
    # table, parse the JSON and insert the missing rows.
    for col, tag_table, pivot_table, fk_col in _TAG_FIELDS:
        if col not in game_cols:
            continue  # Already dropped, nothing to do

        rows = bind.execute(sa.text(f"SELECT id, {col} FROM games WHERE {col} IS NOT NULL")).fetchall()
        for game_id, json_str in rows:
            try:
                names = json.loads(json_str or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(names, list):
                continue
            names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
            if not names:
                continue

            # Check if junction table already has entries for this game
            existing_count = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {pivot_table} WHERE game_id = :gid"),
                {"gid": game_id},
            ).scalar()
            if existing_count:
                continue  # Junction table already populated — skip

            for name in names:
                # Upsert tag row
                bind.execute(
                    sa.text(f"INSERT OR IGNORE INTO {tag_table} (name) VALUES (:name)"),
                    {"name": name},
                )
                tag_id = bind.execute(
                    sa.text(f"SELECT id FROM {tag_table} WHERE name = :name"),
                    {"name": name},
                ).scalar()
                if tag_id is None:
                    continue
                bind.execute(
                    sa.text(
                        f"INSERT OR IGNORE INTO {pivot_table} (game_id, {fk_col}) "
                        f"VALUES (:gid, :tid)"
                    ),
                    {"gid": game_id, "tid": tag_id},
                )

    # --- Drop the TEXT columns (SQLite requires recreating the table) ---
    # SQLite does not support DROP COLUMN on older versions, but Python 3.12
    # ships with SQLite 3.35+ which does support it.
    for col, *_ in _TAG_FIELDS:
        if col in game_cols:
            op.execute(f"ALTER TABLE games DROP COLUMN {col}")


def downgrade() -> None:
    # Re-add the TEXT columns (empty — data is in junction tables)
    op.execute("ALTER TABLE games ADD COLUMN categories TEXT")
    op.execute("ALTER TABLE games ADD COLUMN mechanics TEXT")
    op.execute("ALTER TABLE games ADD COLUMN designers TEXT")
    op.execute("ALTER TABLE games ADD COLUMN publishers TEXT")
    op.execute("ALTER TABLE games ADD COLUMN labels TEXT")
