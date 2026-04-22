"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'games' not in existing:
        op.create_table(
            'games',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='owned'),
            sa.Column('year_published', sa.Integer(), nullable=True),
            sa.Column('min_players', sa.Integer(), nullable=True),
            sa.Column('max_players', sa.Integer(), nullable=True),
            sa.Column('min_playtime', sa.Integer(), nullable=True),
            sa.Column('max_playtime', sa.Integer(), nullable=True),
            sa.Column('difficulty', sa.Float(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('image_url', sa.Text(), nullable=True),
            sa.Column('thumbnail_url', sa.Text(), nullable=True),
            sa.Column('image_cached', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('image_ext', sa.String(10), nullable=True),
            sa.Column('instructions_filename', sa.Text(), nullable=True),
            sa.Column('scan_filename', sa.Text(), nullable=True),
            sa.Column('scan_glb_filename', sa.String(255), nullable=True),
            sa.Column('scan_featured', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('categories', sa.Text(), nullable=True),
            sa.Column('mechanics', sa.Text(), nullable=True),
            sa.Column('designers', sa.Text(), nullable=True),
            sa.Column('publishers', sa.Text(), nullable=True),
            sa.Column('labels', sa.Text(), nullable=True),
            sa.Column('purchase_date', sa.Date(), nullable=True),
            sa.Column('purchase_price', sa.Float(), nullable=True),
            sa.Column('purchase_location', sa.String(255), nullable=True),
            sa.Column('user_rating', sa.Float(), nullable=True),
            sa.Column('user_notes', sa.Text(), nullable=True),
            sa.Column('location', sa.String(255), nullable=True),
            sa.Column('show_location', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('last_played', sa.Date(), nullable=True),
            sa.Column('date_added', sa.DateTime(), nullable=False),
            sa.Column('date_modified', sa.DateTime(), nullable=False),
            sa.Column('parent_game_id', sa.Integer(), sa.ForeignKey('games.id'), nullable=True),
            sa.Column('bgg_id', sa.Integer(), nullable=True),
            sa.Column('bgg_rating', sa.Float(), nullable=True),
            sa.Column('priority', sa.Integer(), nullable=True),
            sa.Column('target_price', sa.Float(), nullable=True),
            sa.Column('condition', sa.String(20), nullable=True),
            sa.Column('edition', sa.String(255), nullable=True),
            sa.Column('share_hidden', sa.Boolean(), nullable=False, server_default='0'),
        )

    if 'game_images' not in existing:
        op.create_table(
            'game_images',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('caption', sa.String(500), nullable=True),
            sa.Column('date_added', sa.DateTime(), nullable=False),
        )

    if 'play_sessions' not in existing:
        op.create_table(
            'play_sessions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), nullable=False),
            sa.Column('played_at', sa.Date(), nullable=False),
            sa.Column('player_count', sa.Integer(), nullable=True),
            sa.Column('duration_minutes', sa.Integer(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('winner', sa.String(255), nullable=True),
            sa.Column('solo', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('date_added', sa.DateTime(), nullable=False),
        )

    if 'players' not in existing:
        op.create_table(
            'players',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True),
            sa.Column('date_added', sa.DateTime(), nullable=False),
        )

    if 'session_players' not in existing:
        op.create_table(
            'session_players',
            sa.Column('session_id', sa.Integer(), sa.ForeignKey('play_sessions.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('score', sa.Integer(), nullable=True),
        )

    if 'share_tokens' not in existing:
        op.create_table(
            'share_tokens',
            sa.Column('token', sa.String(64), primary_key=True),
            sa.Column('label', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
        )

    if 'categories' not in existing:
        op.create_table(
            'categories',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True),
        )

    if 'game_categories' not in existing:
        op.create_table(
            'game_categories',
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('category_id', sa.Integer(), sa.ForeignKey('categories.id', ondelete='CASCADE'), primary_key=True),
        )

    if 'mechanics' not in existing:
        op.create_table(
            'mechanics',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True),
        )

    if 'game_mechanics' not in existing:
        op.create_table(
            'game_mechanics',
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('mechanic_id', sa.Integer(), sa.ForeignKey('mechanics.id', ondelete='CASCADE'), primary_key=True),
        )

    if 'designers' not in existing:
        op.create_table(
            'designers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True),
        )

    if 'game_designers' not in existing:
        op.create_table(
            'game_designers',
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('designer_id', sa.Integer(), sa.ForeignKey('designers.id', ondelete='CASCADE'), primary_key=True),
        )

    if 'publishers' not in existing:
        op.create_table(
            'publishers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True),
        )

    if 'game_publishers' not in existing:
        op.create_table(
            'game_publishers',
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('publisher_id', sa.Integer(), sa.ForeignKey('publishers.id', ondelete='CASCADE'), primary_key=True),
        )

    if 'labels' not in existing:
        op.create_table(
            'labels',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False, unique=True),
        )

    if 'game_labels' not in existing:
        op.create_table(
            'game_labels',
            sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('label_id', sa.Integer(), sa.ForeignKey('labels.id', ondelete='CASCADE'), primary_key=True),
        )

    # Single-column indexes
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_id ON games(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_name ON games(name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_status ON games(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_bgg_id ON games(bgg_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_parent_game_id ON games(parent_game_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_game_images_id ON game_images(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_game_images_game_id ON game_images(game_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_play_sessions_id ON play_sessions(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_play_sessions_game_id ON play_sessions(game_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_players_id ON players(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_categories_name ON categories(name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mechanics_name ON mechanics(name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_designers_name ON designers(name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_publishers_name ON publishers(name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_labels_name ON labels(name)")

    # Composite indexes for filter+sort patterns
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_status_name ON games(status, name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_status_last_played ON games(status, last_played)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_status_date_added ON games(status, date_added)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_play_sessions_game_played ON play_sessions(game_id, played_at)")

    # Partial unique index on bgg_id (NULL values excluded so multiple games can have bgg_id=NULL)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_games_bgg_id_unique "
        "ON games(bgg_id) WHERE bgg_id IS NOT NULL"
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table('game_labels')
    op.drop_table('labels')
    op.drop_table('game_publishers')
    op.drop_table('publishers')
    op.drop_table('game_designers')
    op.drop_table('designers')
    op.drop_table('game_mechanics')
    op.drop_table('mechanics')
    op.drop_table('game_categories')
    op.drop_table('categories')
    op.drop_table('share_tokens')
    op.drop_table('session_players')
    op.drop_table('play_sessions')
    op.drop_table('players')
    op.drop_table('game_images')
    op.drop_table('games')
