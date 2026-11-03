import hashlib
import hmac
import json
import secrets
import uuid
import os
import csv
import io
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from dotenv import load_dotenv
from .models import Description, Game, Guess, Player, TiebreakerGuess, TiebreakerPrompt, now

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROUND_DURATION_OPTIONS = (30, 60, 90, 120)
CLASSIC_MODE = "CLASSIC"
FULL_EXPERIENCE_MODE = "FULL_EXPERIENCE_8"
FULL_EXPERIENCE_MIN_PLAYERS = 5
FULL_EXPERIENCE_MAX_PLAYERS = 8
FULL_EXPERIENCE_DURATION_SECONDS = 30


def _player_capacity(game: Game) -> int:
    return FULL_EXPERIENCE_MAX_PLAYERS if game.game_mode == FULL_EXPERIENCE_MODE else 4


def _minimum_players(game: Game) -> int:
    return FULL_EXPERIENCE_MIN_PLAYERS if game.game_mode == FULL_EXPERIENCE_MODE else 4


def _round_duration(game: Game) -> int:
    return FULL_EXPERIENCE_DURATION_SECONDS if game.game_mode == FULL_EXPERIENCE_MODE else game.round_duration_seconds

load_dotenv()
def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)

def new_id():
    return str(uuid.uuid4())

def token_hash(token: str):
    secret = os.getenv("APP_SECRET", "development-only-change-this-secret")
    if not os.getenv("DATABASE_URL", "sqlite:///./game.db").startswith("sqlite") and (
        len(secret) < 32 or secret == "development-only-change-this-secret"
    ):
        raise RuntimeError("APP_SECRET must be set to a unique value of at least 32 characters")
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()

def get_player(db: Session, token: str) -> Player:
    player = db.scalar(select(Player).where(Player.token_hash == token_hash(token)))
    if not player:
        fail(401, "Invalid or expired session")
    return player

def _game(db: Session, game_id: str, lock=False) -> Game:
    query = select(Game).where(Game.id == game_id)
    if lock:
        query = query.with_for_update()
    game = db.scalar(query)
    if not game:
        fail(404, "Game not found")
    return game

def _members(db: Session, game_id: str):
    return list(db.scalars(select(Player).where(Player.game_id == game_id).order_by(Player.number)))

def create_room(db: Session, name: str, game_mode: str = CLASSIC_MODE):
    if game_mode not in (CLASSIC_MODE, FULL_EXPERIENCE_MODE):
        fail(422, "Choose a supported game mode")
    code_length = min(max(int(os.getenv("ROOM_CODE_LENGTH", "6")), 6), 8)
    for _ in range(5):
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(code_length))
        if db.scalar(select(Game.id).where(Game.code == code)):
            continue
        game_id, player_id = new_id(), new_id()
        token = secrets.token_urlsafe(32)
        game = Game(
            id=game_id,
            code=code,
            phase="LOBBY",
            host_id=player_id,
            game_mode=game_mode,
            round_duration_seconds=(
                FULL_EXPERIENCE_DURATION_SECONDS if game_mode == FULL_EXPERIENCE_MODE else 60
            ),
        )
        player = Player(id=player_id, game_id=game_id, number=1, name=name.strip(), token_hash=token_hash(token))
        db.add_all([game, player])
        try:
            db.commit()
            return {"game_id": game_id, "code": code, "token": token, "player_id": player_id}
        except IntegrityError:
            db.rollback()
    fail(503, "Could not reserve a room code; try again")

def join_room(db: Session, code: str, name: str):
    game = db.scalar(select(Game).where(Game.code == code.upper()).with_for_update())
    if not game:
        fail(404, "Room code not found")
    if game.phase != "LOBBY":
        fail(409, "This game has already started")
    members = _members(db, game.id)
    timeout = int(os.getenv("SESSION_RESERVATION_MINUTES", "30"))
    cutoff = now() - timedelta(minutes=max(1, timeout))
    expired = [member for member in members if not member.connected and member.disconnected_at and member.disconnected_at < cutoff]
    for member in expired:
        db.delete(member)
    if expired:
        db.flush()
        members = _members(db, game.id)
        if game.host_id in {member.id for member in expired}:
            connected = [member for member in members if member.connected]
            game.host_id = min(connected or members, key=lambda member: member.number).id if members else None
    capacity = _player_capacity(game)
    if len(members) >= capacity:
        fail(409, f"This room already has {capacity} players")
    token = secrets.token_urlsafe(32)
    used_seats = {member.number for member in members}
    seat = next(number for number in range(1, capacity + 1) if number not in used_seats)
    player = Player(id=new_id(), game_id=game.id, number=seat, name=name.strip(), token_hash=token_hash(token))
    db.add(player)
    if game.host_id is None:
        game.host_id = player.id
    game.version += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "The last seat was just taken; try joining again")
    return {"game_id": game.id, "code": game.code, "token": token, "player_id": player.id}

def set_ready(db: Session, player: Player, ready: bool):
    game = _game(db, player.game_id, lock=True)
    if game.phase != "LOBBY":
        fail(409, "The lobby is closed")
    player.ready = ready
    game.version += 1
    db.commit()

def set_round_duration(db: Session, player: Player, duration_seconds: int):
    game = _game(db, player.game_id, lock=True)
    if player.id != game.host_id:
        fail(403, "Only the host can configure the round timer")
    if game.game_mode == FULL_EXPERIENCE_MODE:
        fail(409, "The 8-player mode always uses a fixed 30-second round timer")
    if game.phase != "LOBBY":
        fail(409, "The round timer can only be changed before the game starts")
    if duration_seconds not in ROUND_DURATION_OPTIONS:
        fail(422, "Choose a supported round duration")
    game.round_duration_seconds = duration_seconds
    game.version += 1
    db.commit()

def _start_round_timer(game: Game):
    started_at = now()
    game.round_started_at = started_at
    game.round_deadline = started_at + timedelta(seconds=_round_duration(game))

def _clear_round_timer(game: Game):
    game.round_started_at = None
    game.round_deadline = None

def _start_tiebreaker_timer(game: Game):
    started_at = now()
    game.round_started_at = started_at
    game.round_deadline = started_at + timedelta(seconds=_round_duration(game))

def _resolve_description(db: Session, game: Game, description: Description):
    guesses = list(db.scalars(select(Guess).where(Guess.description_id == description.id)))
    for guess in guesses:
        if not guess.timed_out:
            guess.author_points = 8 if guess.author_guess_id == description.author_id else 0
            guess.subject_points = 5 if guess.subject_guess_id == description.subject_id else 0
    description.resolved = True
    description.resolved_at = now()
    game.phase = "REVEAL"
    _clear_round_timer(game)

def _expire_round(db: Session, game: Game, expired_at: datetime):
    if game.phase == "TIEBREAKER":
        return _expire_tiebreaker_round(db, game, expired_at)
    if game.phase != "GUESSING" or not game.round_deadline or game.round_deadline > expired_at:
        return False
    description = db.get(Description, game.active_description_id) if game.active_description_id else None
    if not description:
        return False
    members = _members(db, game.id)
    existing = {
        guess.guesser_id
        for guess in db.scalars(select(Guess).where(Guess.description_id == description.id))
    }
    for member in members:
        if member.id != description.author_id and member.id not in existing:
            db.add(Guess(
                id=new_id(),
                description_id=description.id,
                guesser_id=member.id,
                author_guess_id=None,
                subject_guess_id=None,
                author_points=0,
                subject_points=0,
                timed_out=True,
                created_at=expired_at,
            ))
    db.flush()
    _resolve_description(db, game, description)
    game.version += 1
    db.commit()
    return True

def expire_due_rounds(db: Session, expired_at: datetime | None = None):
    current_time = expired_at or now()
    game_ids = list(db.scalars(select(Game.id).where(
        Game.phase.in_(("GUESSING", "TIEBREAKER")),
        Game.round_deadline.is_not(None),
        Game.round_deadline <= current_time,
    )))
    expired_games = []
    for game_id in game_ids:
        game = _game(db, game_id, lock=True)
        if _expire_round(db, game, current_time):
            expired_games.append(game_id)
    return expired_games

def start_game(db: Session, player: Player):
    game = _game(db, player.game_id, lock=True)
    members = _members(db, game.id)
    if player.id != game.host_id:
        fail(403, "Only the host can start the game")
    capacity = _player_capacity(game)
    minimum = _minimum_players(game)
    if game.phase != "LOBBY" or not minimum <= len(members) <= capacity or not all(item.ready for item in members):
        requirement = (
            f"At least {minimum} and at most {capacity} players must be ready"
            if game.game_mode == FULL_EXPERIENCE_MODE
            else f"All {capacity} players must be ready"
        )
        fail(409, f"{requirement} before the game starts")
    game.phase = "WRITING"
    game.version += 1
    db.commit()

def save_draft(db: Session, player: Player, subject_id: str, text: str):
    game = _game(db, player.game_id, lock=True)
    subject = db.get(Player, subject_id)
    text = text.strip()
    if game.phase != "WRITING" or player.writing_submitted:
        fail(409, "Writing is locked")
    if not subject or subject.game_id != game.id or subject.id == player.id:
        fail(400, "Choose another player in this room")
    if not text or len(text) > 250:
        fail(400, "Description must contain 1 to 250 characters")
    row = db.scalar(select(Description).where(Description.game_id == game.id, Description.author_id == player.id, Description.subject_id == subject.id))
    if row:
        row.text = text
    else:
        row = Description(id=new_id(), game_id=game.id, author_id=player.id, subject_id=subject.id, text=text)
        db.add(row)
    game.version += 1
    db.commit()

def submit_descriptions(db: Session, player: Player, entries: dict[str, str]):
    game = _game(db, player.game_id, lock=True)
    if game.phase != "WRITING" or player.writing_submitted:
        fail(409, "Writing is locked or already submitted")
    members = _members(db, game.id)
    expected = {member.id for member in members if member.id != player.id}
    capacity = _player_capacity(game)
    if len(members) < _minimum_players(game) or len(members) > capacity or set(entries) != expected:
        fail(400, f"Submit exactly one description for each of the other {capacity - 1} players")
    for subject_id, raw_text in entries.items():
        text = raw_text.strip()
        if not text or len(text) > 250:
            fail(400, "Each description must contain 1 to 250 characters")
        row = db.scalar(select(Description).where(Description.game_id == game.id, Description.author_id == player.id, Description.subject_id == subject_id))
        if row:
            row.text = text
        else:
            db.add(Description(id=new_id(), game_id=game.id, author_id=player.id, subject_id=subject_id, text=text))
    player.writing_submitted = True
    db.flush()
    if all(member.writing_submitted or member.id == player.id for member in members):
        descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id)))
        expected_count = len(members) * (len(members) - 1)
        if len(descriptions) != expected_count:
            fail(409, f"The complete set of {expected_count} descriptions is required")
        secrets.SystemRandom().shuffle(descriptions)
        for sequence, description in enumerate(descriptions):
            description.sequence = sequence
        game.phase = "GUESSING"
        game.active_description_id = descriptions[0].id
        _start_round_timer(game)
    game.version += 1
    db.commit()

def submit_guess(db: Session, player: Player, description_id: str, author_guess_id: str | None, subject_guess_id: str | None):
    game = _game(db, player.game_id, lock=True)
    description = db.get(Description, description_id)
    if game.phase != "GUESSING" or description is None or description.id != game.active_description_id or description.game_id != game.id:
        fail(409, "This is not the active guessing turn")
    if game.round_deadline and now() >= game.round_deadline:
        _expire_round(db, game, now())
        fail(409, "The time for this description has expired")
    if player.id == description.author_id:
        fail(403, "This description is not available to you")
    if author_guess_id is None and subject_guess_id is None:
        fail(400, "Choose at least one category")
    members = {member.id for member in _members(db, game.id)}
    if any(value is not None and value not in members for value in (author_guess_id, subject_guess_id)):
        fail(400, "Guesses must be players in this room")
    if game.game_mode == FULL_EXPERIENCE_MODE and player.id in (author_guess_id, subject_guess_id):
        fail(400, "You cannot guess yourself as the author or subject")
    if (
        game.game_mode == FULL_EXPERIENCE_MODE
        and author_guess_id is not None
        and author_guess_id == subject_guess_id
    ):
        fail(400, "The author and subject guesses must be different players")
    if db.scalar(select(Guess.id).where(Guess.description_id == description.id, Guess.guesser_id == player.id)):
        fail(409, "Your guess is already locked")
    db.add(Guess(id=new_id(), description_id=description.id, guesser_id=player.id, author_guess_id=author_guess_id, subject_guess_id=subject_guess_id))
    db.flush()
    guesses = list(db.scalars(select(Guess).where(Guess.description_id == description.id)))
    eligible = len(members) - 1
    if len(guesses) == eligible:
        _resolve_description(db, game, description)
    game.version += 1
    db.commit()

def continue_game(db: Session, player: Player, expected_version: int | None):
    game = _game(db, player.game_id, lock=True)
    if player.id != game.host_id:
        fail(403, "Only the host can continue")
    if game.phase != "REVEAL":
        fail(409, "There is no completed reveal to advance")
    if expected_version is not None and expected_version != game.version:
        fail(409, "Game state changed; refresh and try again")
    descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id).order_by(Description.sequence)))
    next_description = next((row for row in descriptions if not row.resolved), None)
    if next_description:
        game.active_description_id = next_description.id
        game.phase = "GUESSING"
        _start_round_timer(game)
    else:
        game.active_description_id = None
        game.phase = "FINISHED"
        game.finished_at = now()
        _clear_round_timer(game)
    game.version += 1
    db.commit()

def accept_tie(db: Session, player: Player):
    game = _game(db, player.game_id, lock=True)
    if player.id != game.host_id:
        fail(403, "Only the host can accept joint winners")
    if game.phase != "FINISHED" or game.tie_accepted or game.tie_completed:
        fail(409, "Results are not available")
    board = scores(db, game.id)
    if len(board) < 2 or board[0]["total"] != board[1]["total"]:
        fail(409, "There is no tie for first place")
    game.tie_accepted = True
    game.version += 1
    db.commit()

def scores(db: Session, game_id: str):
    members = _members(db, game_id)
    totals = {p.id: {"author": 0, "subject": 0} for p in members}
    guesses = db.scalars(select(Guess).join(Description).where(Description.game_id == game_id))
    for guess in guesses:
        totals[guess.guesser_id]["author"] += guess.author_points
        totals[guess.guesser_id]["subject"] += guess.subject_points
    board = [{"id": p.id, "number": p.number, "name": p.name, "author_points": totals[p.id]["author"], "subject_points": totals[p.id]["subject"], "total": totals[p.id]["author"] + totals[p.id]["subject"]} for p in members]
    return sorted(board, key=lambda p: (-p["total"], p["number"]))

def _top_player_ids(db: Session, game_id: str):
    board = scores(db, game_id)
    if not board:
        return []
    high = board[0]["total"]
    return [player["id"] for player in board if player["total"] == high]

def _locked_tie_ids(game: Game):
    return json.loads(game.tie_participant_ids) if game.tie_participant_ids else []

def start_tiebreaker(db: Session, player: Player):
    game = _game(db, player.game_id, lock=True)
    if player.id != game.host_id:
        fail(403, "Only the host can start a tiebreaker")
    if game.phase != "FINISHED" or game.tie_accepted or game.tie_completed or game.tie_stage:
        fail(409, "A tiebreaker cannot be started now")
    tied_ids = _top_player_ids(db, game.id)
    if len(tied_ids) < 2:
        fail(409, "A tiebreaker is only available for a tie at the top")
    game.tie_participant_ids = json.dumps(tied_ids)
    game.phase = "TIEBREAKER"
    game.tie_stage = "WRITING"
    _clear_round_timer(game)
    game.version += 1
    db.commit()

def submit_tiebreaker_descriptions(db: Session, player: Player, entries: dict[str, str]):
    game = _game(db, player.game_id, lock=True)
    if game.phase != "TIEBREAKER" or game.tie_stage != "WRITING":
        fail(409, "Tiebreaker description writing is closed")
    tied_ids = set(_locked_tie_ids(game))
    if player.id not in tied_ids:
        fail(403, "Only players tied for first can write tiebreaker descriptions")
    members = _members(db, game.id)
    room_ids = {member.id for member in members}
    expected_subjects = room_ids - {player.id}
    if set(entries) != expected_subjects:
        fail(400, f"Submit exactly one description for each of the other {len(members) - 1} players")
    cleaned = {subject_id: raw_text.strip() for subject_id, raw_text in entries.items()}
    if any(not text or len(text) > 250 for text in cleaned.values()):
        fail(400, "Each description must contain 1 to 250 characters")
    if db.scalar(select(TiebreakerPrompt.id).where(
        TiebreakerPrompt.game_id == game.id,
        TiebreakerPrompt.author_id == player.id,
    )):
        fail(409, "Your tiebreaker descriptions are already locked")
    for subject_id, text in cleaned.items():
        db.add(TiebreakerPrompt(
            id=new_id(),
            game_id=game.id,
            author_id=player.id,
            subject_id=subject_id,
            text=text,
        ))
    db.flush()
    prompts = list(db.scalars(
        select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id)
    ))
    expected_count = len(tied_ids) * (len(members) - 1)
    if len(prompts) == expected_count:
        expected_pairs = {
            (author_id, subject_id)
            for author_id in tied_ids
            for subject_id in room_ids
            if author_id != subject_id
        }
        actual_pairs = {(prompt.author_id, prompt.subject_id) for prompt in prompts}
        if actual_pairs != expected_pairs:
            fail(409, "The complete set of tiebreaker descriptions is required")
        secrets.SystemRandom().shuffle(prompts)
        for sequence, prompt in enumerate(prompts):
            prompt.sequence = sequence
        game.active_tiebreaker_id = prompts[0].id
        game.tie_stage = "GUESSING"
        _start_tiebreaker_timer(game)
    game.version += 1
    db.commit()

def _resolve_tiebreaker_prompt(db: Session, game: Game, prompt: TiebreakerPrompt):
    guesses = list(db.scalars(
        select(TiebreakerGuess).where(TiebreakerGuess.prompt_id == prompt.id)
    ))
    for guess in guesses:
        if not guess.timed_out:
            guess.points = int(guess.author_guess_id == prompt.author_id)
    prompt.resolved = True
    prompt.resolved_at = now()
    game.tie_stage = "REVEAL"
    _clear_round_timer(game)

def _expire_tiebreaker_round(db: Session, game: Game, expired_at: datetime):
    if (
        game.phase != "TIEBREAKER"
        or game.tie_stage != "GUESSING"
        or not game.round_deadline
        or game.round_deadline > expired_at
    ):
        return False
    prompt = db.get(TiebreakerPrompt, game.active_tiebreaker_id) if game.active_tiebreaker_id else None
    if not prompt:
        return False
    existing_ids = set(db.scalars(
        select(TiebreakerGuess.guesser_id).where(TiebreakerGuess.prompt_id == prompt.id)
    ))
    for member in _members(db, game.id):
        if member.id != prompt.author_id and member.id not in existing_ids:
            db.add(TiebreakerGuess(
                id=new_id(),
                prompt_id=prompt.id,
                guesser_id=member.id,
                author_guess_id=None,
                points=0,
                timed_out=True,
                created_at=expired_at,
            ))
    db.flush()
    _resolve_tiebreaker_prompt(db, game, prompt)
    game.version += 1
    db.commit()
    return True

def submit_tiebreaker_guess(db: Session, player: Player, prompt_id: str, author_guess_id: str):
    game = _game(db, player.game_id, lock=True)
    prompt = db.get(TiebreakerPrompt, prompt_id)
    if game.phase != "TIEBREAKER" or game.tie_stage != "GUESSING" or prompt is None or prompt.id != game.active_tiebreaker_id or prompt.game_id != game.id:
        fail(409, "This is not the active tiebreaker prompt")
    if game.round_deadline and now() >= game.round_deadline:
        _expire_tiebreaker_round(db, game, now())
        fail(409, "The time for this tiebreaker description has expired")
    if player.id == prompt.author_id:
        fail(403, "You do not guess your own tiebreaker clue")
    tied_ids = set(_locked_tie_ids(game))
    if author_guess_id not in tied_ids:
        fail(400, "Choose one of the tied players")
    if author_guess_id == player.id:
        fail(400, "You cannot guess yourself as the author")
    if db.scalar(select(TiebreakerGuess.id).where(TiebreakerGuess.prompt_id == prompt.id, TiebreakerGuess.guesser_id == player.id)):
        fail(409, "Your tiebreaker guess is already locked")
    db.add(TiebreakerGuess(id=new_id(), prompt_id=prompt.id, guesser_id=player.id, author_guess_id=author_guess_id))
    db.flush()
    guesses = list(db.scalars(select(TiebreakerGuess).where(TiebreakerGuess.prompt_id == prompt.id)))
    if len(guesses) == len(_members(db, game.id)) - 1:
        _resolve_tiebreaker_prompt(db, game, prompt)
    game.version += 1
    db.commit()

def continue_tiebreaker(db: Session, player: Player, expected_version: int | None):
    game = _game(db, player.game_id, lock=True)
    if player.id != game.host_id:
        fail(403, "Only the host can continue the tiebreaker")
    if game.phase != "TIEBREAKER" or game.tie_stage != "REVEAL":
        fail(409, "There is no completed tiebreaker reveal to advance")
    if expected_version is not None and expected_version != game.version:
        fail(409, "Game state changed; refresh and try again")
    prompts = list(db.scalars(select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id).order_by(TiebreakerPrompt.sequence)))
    next_prompt = next((prompt for prompt in prompts if not prompt.resolved), None)
    if next_prompt:
        game.active_tiebreaker_id = next_prompt.id
        game.tie_stage = "GUESSING"
        _start_tiebreaker_timer(game)
    else:
        game.phase = "FINISHED"
        game.finished_at = now()
        game.tie_stage = None
        game.active_tiebreaker_id = None
        game.tie_completed = True
        _clear_round_timer(game)
    game.version += 1
    db.commit()

def cancel_game(db: Session, player: Player):
    game = _game(db, player.game_id, lock=True)
    if player.id != game.host_id:
        fail(403, "Only the host can cancel")
    if game.phase in ("FINISHED", "CANCELLED", "CLOSING"):
        fail(409, "This game cannot be cancelled")
    game.phase = "CANCELLED"
    game.version += 1
    db.commit()

def mark_connected(db: Session, player: Player, connected: bool):
    game = _game(db, player.game_id, lock=True)
    if game.phase == "CLOSING":
        fail(409, "This match room is closing")
    player.connected = connected
    player.disconnected_at = None if connected else now()
    members = _members(db, game.id)
    if connected and (game.host_id is None or not next((p.connected for p in members if p.id == game.host_id), False)):
        candidates = [p for p in members if p.connected]
        if candidates:
            game.host_id = min(candidates, key=lambda p: p.number).id
    elif not connected and player.id == game.host_id:
        candidates = [p for p in members if p.id != player.id and p.connected]
        if candidates:
            game.host_id = min(candidates, key=lambda p: p.number).id
    game.version += 1
    db.commit()


def reset_stale_connections(db: Session):
    db.execute(update(Player).values(connected=False, disconnected_at=now()))
    db.commit()


def results_data(db: Session, player: Player):
    game = db.scalar(select(Game).where(Game.id == player.game_id).with_for_update())
    if not game:
        fail(404, "Game not found")
    if game.phase != "FINISHED":
        fail(409, "Results are only available after the game has finished")
    members = _members(db, game.id)
    player_by_id = {member.id: member for member in members}
    board = snapshot(db, player)["leaderboard"]
    descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id).order_by(Description.sequence)))
    results_descriptions = []
    for description in descriptions:
        author = player_by_id[description.author_id]
        subject = player_by_id[description.subject_id]
        guesses = list(db.scalars(select(Guess).where(Guess.description_id == description.id).order_by(Guess.created_at)))
        results_descriptions.append({
            "number": (description.sequence or 0) + 1,
            "description": description.text,
            "author": {"player_number": author.number, "display_name": author.name},
            "subject": {"player_number": subject.number, "display_name": subject.name},
            "guesses": [{
                "guesser": {"player_number": player_by_id[guess.guesser_id].number, "display_name": player_by_id[guess.guesser_id].name},
                "guessed_author": _player_result(player_by_id.get(guess.author_guess_id)),
                "guessed_subject": _player_result(player_by_id.get(guess.subject_guess_id)),
                "author_points": guess.author_points,
                "subject_points": guess.subject_points,
                "total_points": guess.author_points + guess.subject_points,
                "timed_out": guess.timed_out,
            } for guess in guesses],
        })
    prompts = list(db.scalars(select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id).order_by(TiebreakerPrompt.sequence)))
    tiebreakers = []
    for prompt in prompts:
        author = player_by_id[prompt.author_id]
        subject = player_by_id.get(prompt.subject_id)
        guesses = list(db.scalars(select(TiebreakerGuess).where(TiebreakerGuess.prompt_id == prompt.id).order_by(TiebreakerGuess.created_at)))
        tiebreakers.append({
            "number": (prompt.sequence or 0) + 1,
            "description": prompt.text,
            "author": {"player_number": author.number, "display_name": author.name},
            "subject": _player_result(subject),
            "guesses": [{
                "guesser": _player_result(player_by_id.get(guess.guesser_id)),
                "guessed_author": _player_result(player_by_id.get(guess.author_guess_id)),
                "points": guess.points,
                "timed_out": guess.timed_out,
            } for guess in guesses],
        })
    return {
        "match_reference": game.id,
        "room_code": game.code,
        "completed_at": (game.finished_at or game.updated_at).isoformat() + "Z",
        "players": [{
            "player_number": row["number"],
            "display_name": row["name"],
            "rank": index + 1,
            "final_score": {
                "author_points": row["author_points"],
                "subject_points": row["subject_points"],
                "tiebreaker_points": row["tiebreaker_points"],
                "total_points": row["total"],
            },
        } for index, row in enumerate(board)],
        "descriptions": results_descriptions,
        "tiebreaker_results": tiebreakers,
    }


def _player_result(player: Player | None):
    return None if player is None else {"player_number": player.number, "display_name": player.name}


def results_csv(data: dict):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "Description Number", "Description", "Author Number", "Author Name",
        "Subject Number", "Subject Name", "Guesser Number", "Guesser Name",
        "Guessed Author", "Guessed Subject", "Author Points", "Subject Points", "Total Points", "Timed Out",
    ])
    for description in data["descriptions"]:
        for guess in description["guesses"]:
            values = [
                description["number"], description["description"],
                description["author"]["player_number"], description["author"]["display_name"],
                description["subject"]["player_number"], description["subject"]["display_name"],
                guess["guesser"]["player_number"], guess["guesser"]["display_name"],
                guess["guessed_author"]["display_name"] if guess["guessed_author"] else "Skipped",
                guess["guessed_subject"]["display_name"] if guess["guessed_subject"] else "Skipped",
                guess["author_points"], guess["subject_points"], guess["total_points"], guess["timed_out"],
            ]
            writer.writerow([_spreadsheet_safe(value) for value in values])
    return output.getvalue()


def _spreadsheet_safe(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def begin_close_game(db: Session, player: Player):
    game = db.scalar(select(Game).where(Game.id == player.game_id).with_for_update())
    if game is None:
        return {"game_id": player.game_id, "code": None, "already_closed": True}
    if game.host_id != player.id:
        fail(403, "Only the current host can close this match room")
    if game.phase not in ("FINISHED", "CLOSING"):
        fail(409, "Only a finished game can be closed")
    if game.phase == "FINISHED":
        game.phase = "CLOSING"
        game.version += 1
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            fail(500, "Could not begin closing the match room")
    return {"game_id": game.id, "code": game.code, "already_closed": False}


def delete_closed_game(db: Session, game_id: str):
    try:
        game = db.scalar(select(Game).where(Game.id == game_id).with_for_update())
        if game is None:
            db.rollback()
            return
        if game.phase != "CLOSING":
            fail(409, "The match room is not closing")
        description_ids = select(Description.id).where(Description.game_id == game_id)
        prompt_ids = select(TiebreakerPrompt.id).where(TiebreakerPrompt.game_id == game_id)
        db.execute(delete(TiebreakerGuess).where(TiebreakerGuess.prompt_id.in_(prompt_ids)))
        db.execute(delete(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game_id))
        db.execute(delete(Guess).where(Guess.description_id.in_(description_ids)))
        db.execute(delete(Description).where(Description.game_id == game_id))
        db.execute(delete(Player).where(Player.game_id == game_id))
        db.execute(delete(Game).where(Game.id == game_id))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        fail(500, "Could not delete match data; the host can safely retry")


def close_and_delete_game(db: Session, player: Player):
    closure = begin_close_game(db, player)
    if not closure["already_closed"]:
        delete_closed_game(db, closure["game_id"])
    return closure

def snapshot(db: Session, player: Player):
    game = _game(db, player.game_id)
    members = _members(db, game.id)
    descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id).order_by(Description.sequence)))
    active = next((d for d in descriptions if d.id == game.active_description_id), None)
    guesses_by_description = defaultdict(list)
    for guess in db.scalars(select(Guess).join(Description).where(Description.game_id == game.id)):
        guesses_by_description[guess.description_id].append(guess)
    scores = {p.id: {"author": 0, "subject": 0} for p in members}
    for guesses in guesses_by_description.values():
        for guess in guesses:
            scores[guess.guesser_id]["author"] += guess.author_points
            scores[guess.guesser_id]["subject"] += guess.subject_points
    reveal_allowed = game.phase in ("REVEAL", "FINISHED")
    visible_descriptions = []
    for desc in descriptions:
        is_current_reveal = reveal_allowed and desc.id == game.active_description_id
        visible = game.phase == "FINISHED" or is_current_reveal
        guess_data = []
        if visible:
            for guess in guesses_by_description[desc.id]:
                guesser = next(p for p in members if p.id == guess.guesser_id)
                guess_data.append({"guesser_id": guess.guesser_id, "guesser_name": guesser.name, "guesser_number": guesser.number, "author_guess_id": guess.author_guess_id, "subject_guess_id": guess.subject_guess_id, "author_points": guess.author_points, "subject_points": guess.subject_points})
        text_visible = visible or (game.phase == "WRITING" and desc.author_id == player.id) or (desc.id == game.active_description_id and desc.author_id != player.id and game.phase == "GUESSING")
        if desc.id == game.active_description_id and game.phase == "GUESSING" and desc.author_id == player.id:
            text_visible = False
        visible_descriptions.append({
            "id": desc.id, "sequence": desc.sequence,
            "text": desc.text if text_visible else None,
            "author_id": desc.author_id if visible else None,
            "subject_id": desc.subject_id if visible else None,
            "is_author": bool(game.phase == "GUESSING" and desc.id == game.active_description_id and desc.author_id == player.id),
            "resolved": desc.resolved,
            "guesses": guess_data,
        })
    own_drafts = []
    if game.phase == "WRITING":
        own_drafts = [{"subject_id": d.subject_id, "text": d.text} for d in descriptions if d.author_id == player.id]
    my_active_guess = next((g for g in guesses_by_description.get(game.active_description_id, []) if g.guesser_id == player.id), None) if active else None
    progress = {
        "writing_submitted": sum(1 for p in members if p.writing_submitted),
        "guess_submitted": len(guesses_by_description.get(game.active_description_id, [])) if active else 0,
        "guess_required": len(members) - 1 if active else 0,
    }
    board = [{"id": p.id, "number": p.number, "name": p.name, "author_points": scores[p.id]["author"], "subject_points": scores[p.id]["subject"], "total": scores[p.id]["author"] + scores[p.id]["subject"]} for p in members]
    main_high = max((row["total"] for row in board), default=0)
    current_top_ids = [row["id"] for row in board if row["total"] == main_high]
    tied_ids = set(_locked_tie_ids(game) or current_top_ids)
    tie_points = {p.id: 0 for p in members}
    prompts = list(db.scalars(select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id).order_by(TiebreakerPrompt.sequence)))
    tie_guesses_by_prompt = defaultdict(list)
    for guess in db.scalars(select(TiebreakerGuess).join(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id)):
        tie_points[guess.guesser_id] += guess.points
        tie_guesses_by_prompt[guess.prompt_id].append(guess)
    for row in board:
        row["tiebreaker_points"] = tie_points[row["id"]]
    board.sort(key=lambda p: (-p["total"], -(p["tiebreaker_points"] if game.tie_completed and p["id"] in tied_ids else 0), p["number"]))
    main_winners = [row for row in board if row["total"] == main_high]
    if game.phase == "FINISHED" and game.tie_completed and tied_ids:
        tied_board = [row for row in board if row["id"] in tied_ids]
        best_tie = max(row["tiebreaker_points"] for row in tied_board)
        winners = [row["id"] for row in tied_board if row["tiebreaker_points"] == best_tie]
    else:
        winners = [row["id"] for row in main_winners] if game.phase == "FINISHED" else []
    active_tiebreaker = next((prompt for prompt in prompts if prompt.id == game.active_tiebreaker_id), None)
    tiebreaker_reveal = game.phase == "TIEBREAKER" and game.tie_stage == "REVEAL"
    tiebreaker_final = game.phase == "FINISHED"

    def present_prompt(prompt: TiebreakerPrompt):
        visible = tiebreaker_reveal or tiebreaker_final
        is_active_guess = game.phase == "TIEBREAKER" and game.tie_stage == "GUESSING" and prompt.id == game.active_tiebreaker_id
        text_visible = tiebreaker_final or tiebreaker_reveal or is_active_guess
        guess_data = []
        if visible:
            for guess in tie_guesses_by_prompt[prompt.id]:
                guesser = next(p for p in members if p.id == guess.guesser_id)
                guess_data.append({
                    "guesser_id": guess.guesser_id,
                    "guesser_name": guesser.name,
                    "author_guess_id": guess.author_guess_id,
                    "points": guess.points,
                    "timed_out": guess.timed_out,
                })
        return {
            "id": prompt.id, "sequence": prompt.sequence, "text": prompt.text if text_visible else None,
            "author_id": prompt.author_id if visible else None,
            "subject_id": prompt.subject_id if (is_active_guess or visible) else None,
            "is_author": bool(is_active_guess and prompt.author_id == player.id),
            "resolved": prompt.resolved, "guesses": guess_data,
        }
    active_tiebreaker_data = present_prompt(active_tiebreaker) if active_tiebreaker else None
    own_tiebreaker_count = sum(1 for prompt in prompts if prompt.author_id == player.id)
    own_tiebreaker_guess = next((g for g in tie_guesses_by_prompt.get(game.active_tiebreaker_id, []) if g.guesser_id == player.id), None) if active_tiebreaker else None
    tiebreaker_description_count = len(tied_ids) * max(0, len(members) - 1)
    if game.phase == "TIEBREAKER" and game.tie_stage == "WRITING":
        complete_writers = {
            author_id
            for author_id in tied_ids
            if sum(1 for prompt in prompts if prompt.author_id == author_id) == len(members) - 1
        }
        waiting_player_ids = [member.id for member in members if member.id in tied_ids - complete_writers]
    elif game.phase == "TIEBREAKER" and active_tiebreaker:
        submitted_guesser_ids = {
            guess.guesser_id
            for guess in tie_guesses_by_prompt[active_tiebreaker.id]
        }
        waiting_player_ids = [
            member.id for member in members
            if member.id != active_tiebreaker.author_id and member.id not in submitted_guesser_ids
        ]
    else:
        waiting_player_ids = []
    tiebreaker_progress = {
        "description_submitted": len(prompts),
        "description_required": tiebreaker_description_count,
        "guess_submitted": len(tie_guesses_by_prompt.get(game.active_tiebreaker_id, [])) if active_tiebreaker else 0,
        "guess_required": max(0, len(members) - 1) if active_tiebreaker else 0,
        "waiting_player_ids": waiting_player_ids,
    }
    tie_available = game.phase == "FINISHED" and len(current_top_ids) > 1 and not game.tie_accepted and not game.tie_completed
    tiebreaker_leaderboard = sorted(
        (row for row in board if row["id"] in tied_ids),
        key=lambda row: (-row["tiebreaker_points"], row["number"]),
    )
    return {
        "game_id": game.id, "code": game.code, "phase": game.phase, "version": game.version,
        "game_mode": game.game_mode,
        "player_capacity": _player_capacity(game),
        "minimum_players": _minimum_players(game),
        "player_count": len(members),
        "round_count": len(members) * (len(members) - 1),
        "round_duration_seconds": _round_duration(game),
        "round_started_at": game.round_started_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if game.round_started_at else None,
        "round_deadline": game.round_deadline.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if game.round_deadline else None,
        "server_now": now().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "host_id": game.host_id, "tie_accepted": game.tie_accepted, "tie_completed": game.tie_completed,
        "tie_available": tie_available, "tie_stage": game.tie_stage, "tie_participants": list(_locked_tie_ids(game) or current_top_ids) if len(tied_ids) > 1 else [],
        "tiebreaker_progress": tiebreaker_progress,
        "tiebreaker_submitted": own_tiebreaker_count == len(members) - 1 and game.phase == "TIEBREAKER",
        "active_tiebreaker": active_tiebreaker_data,
        "tiebreaker_prompts": [present_prompt(prompt) for prompt in prompts] if tiebreaker_final else [],
        "my_tiebreaker_guess": ({
            "author_guess_id": own_tiebreaker_guess.author_guess_id,
            "timed_out": own_tiebreaker_guess.timed_out,
        } if own_tiebreaker_guess else None),
        "me": {"id": player.id, "number": player.number, "name": player.name},
        "players": [{"id": p.id, "number": p.number, "name": p.name, "ready": p.ready, "connected": p.connected, "writing_submitted": p.writing_submitted} for p in members],
        "active_description_id": game.active_description_id, "active_description": next((d for d in visible_descriptions if d["id"] == game.active_description_id), None),
        "descriptions": visible_descriptions if game.phase == "FINISHED" else [d for d in visible_descriptions if d["sequence"] is not None and (d["id"] == game.active_description_id or (game.phase == "REVEAL" and d["resolved"]))],
        "drafts": own_drafts, "my_guess": ({"author_guess_id": my_active_guess.author_guess_id, "subject_guess_id": my_active_guess.subject_guess_id, "timed_out": my_active_guess.timed_out} if my_active_guess else None),
        "progress": progress, "leaderboard": board,
        "tiebreaker_leaderboard": tiebreaker_leaderboard,
        "winners": winners,
    }
