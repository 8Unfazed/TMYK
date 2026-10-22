"""Initial four-player game schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("games",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False, unique=True, index=True),
        sa.Column("phase", sa.String(16), nullable=False, server_default="LOBBY"),
        sa.Column("host_id", sa.String(36), nullable=True),
        sa.Column("active_description_id", sa.String(36), nullable=True),
        sa.Column("tie_accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tie_stage", sa.String(16), nullable=True),
        sa.Column("active_tiebreaker_id", sa.String(36), nullable=True),
        sa.Column("tie_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("players",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(24), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("writing_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disconnected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("game_id", "number", name="uq_player_seat"))
    op.create_table("descriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("subject_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("text", sa.String(250), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("game_id", "author_id", "subject_id", name="uq_description_author_subject"))
    op.create_table("guesses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("description_id", sa.String(36), sa.ForeignKey("descriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guesser_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("author_guess_id", sa.String(36), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("subject_guess_id", sa.String(36), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("author_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("description_id", "guesser_id", name="uq_guess_once"))
    op.create_index("ix_guess_description", "guesses", ["description_id"])
    op.create_table("tiebreaker_prompts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("text", sa.String(250), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("game_id", "author_id", name="uq_tiebreaker_author"))
    op.create_table("tiebreaker_guesses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prompt_id", sa.String(36), sa.ForeignKey("tiebreaker_prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guesser_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("author_guess_id", sa.String(36), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("prompt_id", "guesser_id", name="uq_tiebreaker_guess_once"))
    op.create_index("ix_tiebreaker_guesses_prompt_id", "tiebreaker_guesses", ["prompt_id"])

def downgrade():
    op.drop_index("ix_tiebreaker_guesses_prompt_id", table_name="tiebreaker_guesses")
    op.drop_table("tiebreaker_guesses")
    op.drop_table("tiebreaker_prompts")
    op.drop_index("ix_guess_description", table_name="guesses")
    op.drop_table("guesses")
    op.drop_table("descriptions")
    op.drop_table("players")
    op.drop_table("games")
