"""Add host-configured description round timers."""
from alembic import op
import sqlalchemy as sa

revision = "0003_round_timers"
down_revision = "0002_finished_at"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("round_duration_seconds", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("games", sa.Column("round_started_at", sa.DateTime(), nullable=True))
    op.add_column("games", sa.Column("round_deadline", sa.DateTime(), nullable=True))
    op.add_column("guesses", sa.Column("timed_out", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("guesses", "timed_out")
    op.drop_column("games", "round_deadline")
    op.drop_column("games", "round_started_at")
    op.drop_column("games", "round_duration_seconds")
