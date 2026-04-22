"""Add image_cache_status column to games table

Tracks whether a background image-cache task is pending, succeeded, or failed.
Values: NULL (no image URL), 'pending', 'cached', 'failed'.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('games')}
    if 'image_cache_status' not in cols:
        op.execute("ALTER TABLE games ADD COLUMN image_cache_status VARCHAR(10)")
    # Back-fill: games that already have a cached image get 'cached'; others stay NULL.
    op.execute(
        "UPDATE games SET image_cache_status = 'cached' WHERE image_cached = 1 AND image_url LIKE '/api/%'"
    )


def downgrade() -> None:
    # SQLite 3.35+ supports DROP COLUMN
    op.execute("ALTER TABLE games DROP COLUMN image_cache_status")
