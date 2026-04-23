"""Add avatar_ext column to players table

Stores the file extension (e.g. '.jpg') of a player's custom profile photo.
NULL means no photo has been uploaded.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('players')}
    if 'avatar_ext' not in cols:
        op.execute("ALTER TABLE players ADD COLUMN avatar_ext VARCHAR(10)")


def downgrade() -> None:
    op.execute("ALTER TABLE players DROP COLUMN avatar_ext")
