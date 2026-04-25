"""Add avatar_preset column to players table

Stores the name of a chosen built-in SVG avatar (e.g. 'meeple', 'dice').
NULL means no preset has been selected.  Custom uploads (avatar_ext) take
precedence over this field when both are somehow set.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns('players')}
    if 'avatar_preset' not in cols:
        op.execute("ALTER TABLE players ADD COLUMN avatar_preset VARCHAR(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE players DROP COLUMN avatar_preset")
