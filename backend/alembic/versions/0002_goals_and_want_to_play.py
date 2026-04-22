"""Add goals and want_to_play_requests tables; add session_rating column

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Add session_rating to play_sessions if missing
    if 'play_sessions' in existing:
        cols = {c['name'] for c in inspector.get_columns('play_sessions')}
        if 'session_rating' not in cols:
            op.execute("ALTER TABLE play_sessions ADD COLUMN session_rating INTEGER")

    # Goals table
    if 'goals' not in existing:
        op.create_table(
            'goals',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('type', sa.String(50), nullable=False),
            sa.Column('target_value', sa.Integer(), nullable=False),
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='SET NULL'), nullable=True),
            sa.Column('year', sa.Integer(), nullable=True),
            sa.Column('is_complete', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )

    # Want-to-play requests table
    if 'want_to_play_requests' not in existing:
        op.create_table(
            'want_to_play_requests',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('token', sa.String(64), nullable=False, index=True),
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
            sa.Column('visitor_name', sa.String(100), nullable=True),
            sa.Column('message', sa.String(500), nullable=True),
            sa.Column('seen', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_want_to_play_requests_token ON want_to_play_requests(token)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_want_to_play_requests_game_id ON want_to_play_requests(game_id)")


def downgrade() -> None:
    op.drop_table('want_to_play_requests')
    op.drop_table('goals')
