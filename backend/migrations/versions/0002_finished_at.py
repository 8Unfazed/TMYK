"""Record when a game officially finishes."""
from alembic import op
import sqlalchemy as sa

revision = "0002_finished_at"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("finished_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("games", "finished_at")
