"""Add selectable Classic and 8-player game modes."""
from alembic import op
import sqlalchemy as sa

revision = "0004_game_modes"
down_revision = "0003_round_timers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "games",
        sa.Column("game_mode", sa.String(length=32), nullable=False, server_default="CLASSIC"),
    )


def downgrade():
    op.drop_column("games", "game_mode")
