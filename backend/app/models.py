from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Base(DeclarativeBase):
    pass

class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    phase: Mapped[str] = mapped_column(String(16), default="LOBBY", nullable=False)
    host_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    active_description_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tie_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tie_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    active_tiebreaker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tie_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    players: Mapped[list["Player"]] = relationship(back_populates="game", cascade="all, delete-orphan", order_by="Player.number")

class Player(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("game_id", "number", name="uq_player_seat"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    writing_submitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    game: Mapped[Game] = relationship(back_populates="players")

class Description(Base):
    __tablename__ = "descriptions"
    __table_args__ = (UniqueConstraint("game_id", "author_id", "subject_id", name="uq_description_author_subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    subject_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    text: Mapped[str] = mapped_column(String(250), nullable=False)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Guess(Base):
    __tablename__ = "guesses"
    __table_args__ = (UniqueConstraint("description_id", "guesser_id", name="uq_guess_once"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    description_id: Mapped[str] = mapped_column(ForeignKey("descriptions.id", ondelete="CASCADE"), index=True)
    guesser_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    author_guess_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    subject_guess_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    author_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subject_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

class TiebreakerPrompt(Base):
    __tablename__ = "tiebreaker_prompts"
    __table_args__ = (UniqueConstraint("game_id", "author_id", name="uq_tiebreaker_author"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    text: Mapped[str] = mapped_column(String(250), nullable=False)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class TiebreakerGuess(Base):
    __tablename__ = "tiebreaker_guesses"
    __table_args__ = (UniqueConstraint("prompt_id", "guesser_id", name="uq_tiebreaker_guess_once"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("tiebreaker_prompts.id", ondelete="CASCADE"), index=True)
    guesser_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    author_guess_id: Mapped[str] = mapped_column(ForeignKey("players.id"), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
