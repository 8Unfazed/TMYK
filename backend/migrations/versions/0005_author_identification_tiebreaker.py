"""Expand the tiebreaker to one author-identification round per subject."""
from alembic import op
import sqlalchemy as sa

revision = "0005_author_identification_tiebreaker"
down_revision = "0004_game_modes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("tie_participant_ids", sa.Text(), nullable=True))
    with op.batch_alter_table("tiebreaker_prompts") as batch_op:
        batch_op.add_column(
            sa.Column("subject_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_tiebreaker_prompts_subject_id_players",
            "players",
            ["subject_id"],
            ["id"],
        )
        batch_op.drop_constraint("uq_tiebreaker_author", type_="unique")
        batch_op.create_unique_constraint(
            "uq_tiebreaker_author_subject",
            ["game_id", "author_id", "subject_id"],
        )
    with op.batch_alter_table("tiebreaker_guesses") as batch_op:
        batch_op.alter_column(
            "author_guess_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "timed_out",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("tiebreaker_guesses") as batch_op:
        batch_op.drop_column("timed_out")
        batch_op.alter_column(
            "author_guess_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
    with op.batch_alter_table("tiebreaker_prompts") as batch_op:
        batch_op.drop_constraint("uq_tiebreaker_author_subject", type_="unique")
        batch_op.create_unique_constraint(
            "uq_tiebreaker_author",
            ["game_id", "author_id"],
        )
        batch_op.drop_constraint(
            "fk_tiebreaker_prompts_subject_id_players",
            type_="foreignkey",
        )
        batch_op.drop_column("subject_id")
    op.drop_column("games", "tie_participant_ids")
