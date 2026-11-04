import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from datetime import timedelta, timezone
from app.models import Base, Description, Game, Guess, Player, TiebreakerGuess, TiebreakerPrompt, now
from app import service

@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()

def make_room(db):
    created = service.create_room(db, "Player 1")
    players = [service.get_player(db, created["token"])]
    for number in range(2, 5):
        joined = service.join_room(db, created["code"], f"Player {number}")
        players.append(service.get_player(db, joined["token"]))
    return created, players


def make_full_experience_room(db, player_count=8):
    created = service.create_room(db, "Player 1", service.FULL_EXPERIENCE_MODE)
    players = [service.get_player(db, created["token"])]
    for number in range(2, player_count + 1):
        joined = service.join_room(db, created["code"], f"Player {number}")
        players.append(service.get_player(db, joined["token"]))
    return created, players


def prepare_full_experience_guessing(db, player_count=8):
    created, players = make_full_experience_room(db, player_count)
    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    for author in players:
        entries = {
            target.id: f"Description about player {target.number}."
            for target in players
            if target.id != author.id
        }
        service.submit_descriptions(db, author, entries)
    game = db.get(Game, players[0].game_id)
    descriptions = list(
        db.scalars(
            select(Description)
            .where(Description.game_id == game.id)
            .order_by(Description.sequence)
        )
    )
    return created, players, game, descriptions

def prepare_writing(db):
    created, players = make_room(db)
    with pytest.raises(HTTPException) as exc:
        service.join_room(db, created["code"], "Fifth")
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        service.start_game(db, players[0])
    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    return created, players

def test_full_four_player_game_seals_answers_and_scores_once(db):
    created, players = prepare_writing(db)
    ids = [player.id for player in players]
    for author in players:
        others = [target.id for target in players if target.id != author.id]
        with pytest.raises(HTTPException) as exc:
            service.submit_descriptions(db, author, {**{target: f"About {target}" for target in others}, author.id: "self"})
        assert exc.value.status_code == 400
        service.submit_descriptions(db, author, {target: f"A distinct true thing about {target}." for target in others})

    game = db.get(Game, created["game_id"])
    descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id).order_by(Description.sequence)))
    assert len(descriptions) == 12
    assert len({description.sequence for description in descriptions}) == 12
    assert game.phase == "GUESSING"

    expected = {player.id: [0, 0] for player in players}
    categories = ("both", "author", "subject", "neither")
    for index, description in enumerate(descriptions):
        guesses_before = list(db.scalars(select(Guess).where(Guess.description_id == description.id)))
        assert not guesses_before
        author_player = next(p for p in players if p.id == description.author_id)
        assert service.snapshot(db, author_player)["active_description"]["text"] is None
        assert service.snapshot(db, author_player)["active_description"]["author_id"] is None
        assert service.snapshot(db, author_player)["active_description"]["is_author"] is True
        for player in players:
            if player.id == description.author_id:
                continue
            state = service.snapshot(db, player)
            assert state["active_description"]["text"] == description.text
            assert state["active_description"]["author_id"] is None
            assert state["active_description"]["guesses"] == []
            category = categories[(index + player.number) % len(categories)]
            wrong_player = next(item.id for item in players if item.id not in (description.author_id, description.subject_id))
            author_guess = description.author_id if category in ("both", "author") else wrong_player
            subject_guess = description.subject_id if category in ("both", "subject") else wrong_player
            service.submit_guess(db, player, description.id, author_guess, subject_guess)
            if category in ("both", "author"):
                expected[player.id][0] += 8
            if category in ("both", "subject"):
                expected[player.id][1] += 5
        assert game.phase == "REVEAL"
        reveal = service.snapshot(db, players[0])
        assert len(reveal["active_description"]["guesses"]) == 3
        with pytest.raises(HTTPException):
            service.submit_guess(db, next(p for p in players if p.id != description.author_id), description.id, description.author_id, description.subject_id)
        if index < 11:
            service.continue_game(db, players[0], game.version)
            assert game.phase == "GUESSING"

    service.continue_game(db, players[0], game.version)
    assert game.phase == "FINISHED"
    board = service.snapshot(db, players[0])["leaderboard"]
    assert sum(len(list(db.scalars(select(Guess).where(Guess.description_id == d.id)))) for d in descriptions) == 36
    for row in board:
        assert row["author_points"] == expected[row["id"]][0]
        assert row["subject_points"] == expected[row["id"]][1]
        assert row["total"] == sum(expected[row["id"]])
    with pytest.raises(HTTPException):
        service.submit_guess(db, players[0], descriptions[-1].id, None, descriptions[-1].subject_id)

    for guess in db.scalars(select(Guess).join(Description).where(Description.game_id == game.id)):
        guess.author_points = 0
        guess.subject_points = 0
    db.commit()
    assert service.snapshot(db, players[0])["tie_available"] is True
    main_scores = {row["id"]: row["total"] for row in service.snapshot(db, players[0])["leaderboard"]}
    service.start_tiebreaker(db, players[0])
    for player in players:
        service.submit_tiebreaker_descriptions(db, player, {
            subject.id: f"Player {subject.number} is known for a memorable habit."
            for subject in players
            if subject.id != player.id
        })
    assert game.phase == "TIEBREAKER"
    assert game.tie_stage == "GUESSING"
    prompts = list(db.scalars(select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id).order_by(TiebreakerPrompt.sequence)))
    assert len(prompts) == 4 * (len(players) - 1)
    for prompt_index, prompt in enumerate(prompts):
        for guesser in players:
            if guesser.id != prompt.author_id:
                service.submit_tiebreaker_guess(db, guesser, prompt.id, prompt.author_id)
        assert game.tie_stage == "REVEAL"
        reveal = service.snapshot(db, players[0])
        assert reveal["active_tiebreaker"]["subject_id"] == prompt.subject_id
        assert reveal["active_tiebreaker"]["author_id"] == prompt.author_id
        assert len(reveal["active_tiebreaker"]["guesses"]) == len(players) - 1
        service.continue_tiebreaker(db, players[0], game.version)
        if prompt_index < len(prompts) - 1:
            assert game.tie_stage == "GUESSING"
    final_tie = service.snapshot(db, players[0])
    assert game.phase == "FINISHED"
    assert game.tie_completed is True
    assert len(final_tie["winners"]) == 4
    assert all(player["total"] == 0 for player in final_tie["leaderboard"])
    assert all(player["tiebreaker_points"] == (len(players) - 1) ** 2 for player in final_tie["leaderboard"])
    assert {row["id"]: row["total"] for row in final_tie["leaderboard"]} == main_scores

def test_drafts_and_unresolved_answers_are_private(db):
    created, players = prepare_writing(db)
    service.save_draft(db, players[0], players[1].id, "A secret draft")
    assert service.snapshot(db, players[0])["drafts"] == [{"subject_id": players[1].id, "text": "A secret draft"}]
    assert service.snapshot(db, players[1])["drafts"] == []
    assert service.snapshot(db, players[1])["descriptions"] == []

def test_only_host_can_cancel_and_host_is_reassigned_on_disconnect(db):
    _, players = make_room(db)
    game_id = players[0].game_id
    service.mark_connected(db, players[1], True)
    service.mark_connected(db, players[2], True)
    with pytest.raises(HTTPException) as exc:
        service.cancel_game(db, players[1])
    assert exc.value.status_code == 403
    service.mark_connected(db, players[0], False)
    assert db.get(Game, game_id).host_id == players[1].id

def test_draft_validation_and_guess_validation(db):
    _, players = prepare_writing(db)
    with pytest.raises(HTTPException):
        service.save_draft(db, players[0], players[0].id, "self")
    with pytest.raises(HTTPException):
        service.save_draft(db, players[0], players[1].id, "  ")

def test_host_configures_supported_round_durations_and_defaults_to_one_minute(db):
    _, players = make_room(db)
    game = db.get(Game, players[0].game_id)
    assert game.round_duration_seconds == 60
    for duration in (30, 60, 90, 120):
        service.set_round_duration(db, players[0], duration)
        assert game.round_duration_seconds == duration
    with pytest.raises(HTTPException) as unauthorized:
        service.set_round_duration(db, players[1], 30)
    assert unauthorized.value.status_code == 403
    with pytest.raises(HTTPException) as invalid:
        service.set_round_duration(db, players[0], 45)
    assert invalid.value.status_code == 422

    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    with pytest.raises(HTTPException) as started:
        service.set_round_duration(db, players[0], 30)
    assert started.value.status_code == 409

def prepare_guessing(db, duration=60):
    created, players = make_room(db)
    service.set_round_duration(db, players[0], duration)
    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    for author in players:
        entries = {target.id: f"Description about player {target.number}." for target in players if target.id != author.id}
        service.submit_descriptions(db, author, entries)
    game = db.get(Game, players[0].game_id)
    descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id).order_by(Description.sequence)))
    return created, players, game, descriptions

def test_round_deadline_is_shared_and_expiration_preserves_submitted_guess(db):
    _, players, game, descriptions = prepare_guessing(db, duration=30)
    description = descriptions[0]
    started_at = game.round_started_at
    deadline = game.round_deadline
    assert deadline == started_at + timedelta(seconds=30)
    states = [service.snapshot(db, player) for player in players]
    assert {state["round_deadline"] for state in states} == {deadline.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")}

    guesser = next(
        player for player in players
        if player.id not in (description.author_id, description.subject_id)
    )
    service.submit_guess(db, guesser, description.id, description.author_id, description.subject_id)
    game.round_deadline = now() - timedelta(seconds=1)
    db.commit()
    assert service.expire_due_rounds(db) == [game.id]

    guesses = list(db.scalars(select(Guess).where(Guess.description_id == description.id)))
    assert len(guesses) == 3
    submitted = next(guess for guess in guesses if guess.guesser_id == guesser.id)
    assert not submitted.timed_out
    assert (submitted.author_points, submitted.subject_points) == (8, 5)
    timed_out = [guess for guess in guesses if guess.timed_out]
    assert len(timed_out) == 2
    assert all((guess.author_points, guess.subject_points) == (0, 0) for guess in timed_out)
    assert game.phase == "REVEAL"
    assert game.round_deadline is None
    for timeout in timed_out:
        state = service.snapshot(db, next(player for player in players if player.id == timeout.guesser_id))
        assert state["my_guess"]["timed_out"] is True
        scores_by_player = {row["id"]: row["total"] for row in state["leaderboard"]}
        assert scores_by_player[timeout.guesser_id] == 0

def test_late_guess_triggers_timeout_and_is_rejected(db):
    _, players, game, descriptions = prepare_guessing(db)
    description = descriptions[0]
    game.round_deadline = now() - timedelta(seconds=1)
    db.commit()
    guesser = next(player for player in players if player.id != description.author_id)

    with pytest.raises(HTTPException) as expired:
        service.submit_guess(db, guesser, description.id, description.author_id, description.subject_id)
    assert expired.value.status_code == 409
    assert game.phase == "REVEAL"
    assert db.scalar(select(Guess.id).where(Guess.description_id == description.id, Guess.guesser_id == guesser.id)) is not None
    with pytest.raises(HTTPException) as duplicate:
        service.submit_guess(db, guesser, description.id, description.author_id, description.subject_id)
    assert duplicate.value.status_code == 409

def test_next_description_gets_a_fresh_full_timer(db):
    _, players, game, descriptions = prepare_guessing(db, duration=30)
    first = descriptions[0]
    first_started = game.round_started_at
    first_deadline = game.round_deadline
    for player in players:
        if player.id != first.author_id:
            service.submit_guess(db, player, first.id, first.author_id, first.subject_id)
    assert game.phase == "REVEAL"
    assert game.round_deadline is None

    service.continue_game(db, players[0], game.version)
    assert game.phase == "GUESSING"
    assert game.active_description_id != first.id
    assert game.round_started_at >= first_started
    assert game.round_deadline == game.round_started_at + timedelta(seconds=30)
    assert game.round_deadline > first_deadline

def test_host_can_accept_joint_winners_only_when_top_score_is_tied(db):
    _, players = make_room(db)
    game = db.get(Game, players[0].game_id)
    game.phase = "FINISHED"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.accept_tie(db, players[1])
    assert exc.value.status_code == 403
    service.accept_tie(db, players[0])
    result = service.snapshot(db, players[0])
    assert result["tie_accepted"] is True
    assert len(result["winners"]) == 4
    assert result["tie_available"] is False
    with pytest.raises(HTTPException):
        service.start_tiebreaker(db, players[0])


def test_full_experience_capacity_and_server_fixed_timer(db):
    created, players = make_full_experience_room(db)
    game = db.get(Game, created["game_id"])
    assert game.game_mode == service.FULL_EXPERIENCE_MODE
    assert [player.number for player in players] == list(range(1, 9))
    assert game.round_duration_seconds == 30
    with pytest.raises(HTTPException) as full:
        service.join_room(db, created["code"], "Player 9")
    assert full.value.status_code == 409
    with pytest.raises(HTTPException) as not_ready:
        service.start_game(db, players[0])
    assert not_ready.value.status_code == 409
    with pytest.raises(HTTPException) as invalid_mode:
        service.create_room(db, "Invalid", "UNSUPPORTED")
    assert invalid_mode.value.status_code == 422
    with pytest.raises(HTTPException) as fixed:
        service.set_round_duration(db, players[0], 120)
    assert fixed.value.status_code == 409
    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    assert game.phase == "WRITING"


@pytest.mark.parametrize("player_count", [5, 6, 7, 8])
def test_full_experience_can_start_at_every_supported_player_count(db, player_count):
    _, players = make_full_experience_room(db, player_count)
    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    assert db.get(Game, players[0].game_id).phase == "WRITING"


def test_full_experience_cannot_start_with_fewer_than_five_players(db):
    _, players = make_full_experience_room(db, 4)
    for player in players:
        service.set_ready(db, player, True)
    with pytest.raises(HTTPException) as too_few:
        service.start_game(db, players[0])
    assert too_few.value.status_code == 409


@pytest.mark.parametrize("player_count", [5, 6, 7, 8])
def test_full_experience_generates_dynamic_descriptions_and_eligible_guesses(db, player_count):
    _, players, game, descriptions = prepare_full_experience_guessing(db, player_count)
    round_count = player_count * (player_count - 1)
    assert len(descriptions) == round_count
    assert {description.sequence for description in descriptions} == set(range(round_count))
    assert {
        (description.author_id, description.subject_id)
        for description in descriptions
    } == {
        (author.id, subject.id)
        for author in players
        for subject in players
        if author.id != subject.id
    }
    assert game.round_deadline == game.round_started_at + timedelta(seconds=30)
    assert service.snapshot(db, players[0])["round_duration_seconds"] == 30
    assert service.snapshot(db, players[0])["player_count"] == player_count
    assert service.snapshot(db, players[0])["round_count"] == round_count
    assert service.snapshot(db, players[0])["progress"]["guess_required"] == player_count - 1

    description = descriptions[0]
    guessers = [player for player in players if player.id != description.author_id]
    with pytest.raises(HTTPException) as self_guess:
        service.submit_guess(db, guessers[0], description.id, guessers[0].id, None)
    assert self_guess.value.status_code == 400
    with pytest.raises(HTTPException) as unknown_player:
        service.submit_guess(db, guessers[0], description.id, "not-a-room-player", None)
    assert unknown_player.value.status_code == 400
    with pytest.raises(HTTPException) as unknown_subject:
        service.submit_guess(db, guessers[0], description.id, None, "not-a-room-player")
    assert unknown_subject.value.status_code == 400
    outsider = Player(id="outsider", game_id=game.id, number=player_count + 1, name="Outsider", token_hash="outsider-token")
    with pytest.raises(HTTPException) as non_member:
        service.submit_guess(db, outsider, description.id, None, players[0].id)
    assert non_member.value.status_code == 403
    with pytest.raises(HTTPException) as author_guess:
        service.submit_guess(db, next(player for player in players if player.id == description.author_id), description.id, None, description.subject_id)
    assert author_guess.value.status_code == 403

    author_guesser = next(player for player in guessers if player.id != description.subject_id)
    writer_subject_guesser = next(player for player in guessers if player.id != author_guesser.id)
    correct_subject_guesser = next(
        player for player in guessers
        if player.id not in (author_guesser.id, writer_subject_guesser.id)
    )
    service.submit_guess(db, author_guesser, description.id, description.author_id, author_guesser.id)
    with pytest.raises(HTTPException) as locked_guess:
        service.submit_guess(db, author_guesser, description.id, None, players[0].id)
    assert locked_guess.value.status_code == 409
    service.submit_guess(db, writer_subject_guesser, description.id, description.author_id, description.author_id)
    service.submit_guess(db, correct_subject_guesser, description.id, None, description.subject_id)
    for guesser in guessers:
        if guesser.id in (author_guesser.id, writer_subject_guesser.id, correct_subject_guesser.id):
            continue
        wrong_author = next(player.id for player in players if player.id not in (guesser.id, description.author_id))
        service.submit_guess(db, guesser, description.id, wrong_author, guesser.id)
    assert game.phase == "REVEAL"
    guesses = list(db.scalars(select(Guess).where(Guess.description_id == description.id)))
    assert len(guesses) == player_count - 1
    by_guesser = {guess.guesser_id: guess for guess in guesses}
    assert (by_guesser[author_guesser.id].author_points, by_guesser[author_guesser.id].subject_points) == (8, 0)
    assert (by_guesser[writer_subject_guesser.id].author_points, by_guesser[writer_subject_guesser.id].subject_points) == (8, 0)
    assert (by_guesser[correct_subject_guesser.id].author_points, by_guesser[correct_subject_guesser.id].subject_points) == (0, 5)
    with pytest.raises(HTTPException) as duplicate:
        service.submit_guess(db, guessers[0], description.id, description.author_id, None)
    assert duplicate.value.status_code == 409


@pytest.mark.parametrize("player_count", [5, 6, 7, 8])
def test_full_experience_timeout_preserves_submitted_guess_and_reconnect_timer(db, player_count):
    _, players, game, descriptions = prepare_full_experience_guessing(db, player_count)
    description = descriptions[0]
    deadline = game.round_deadline
    guesser = next(
        player for player in players
        if player.id not in (description.author_id, description.subject_id)
    )
    service.submit_guess(db, guesser, description.id, description.author_id, description.subject_id)
    service.mark_connected(db, guesser, False)
    service.mark_connected(db, guesser, True)
    assert game.round_deadline == deadline
    game.round_deadline = now() - timedelta(seconds=1)
    db.commit()
    assert service.expire_due_rounds(db) == [game.id]
    guesses = list(db.scalars(select(Guess).where(Guess.description_id == description.id)))
    assert len(guesses) == player_count - 1
    submitted = next(guess for guess in guesses if guess.guesser_id == guesser.id)
    assert not submitted.timed_out
    assert (submitted.author_points, submitted.subject_points) == (8, 5)
    timed_out = [guess for guess in guesses if guess.timed_out]
    assert len(timed_out) == player_count - 2
    assert all((guess.author_points, guess.subject_points) == (0, 0) for guess in timed_out)
    with pytest.raises(HTTPException) as late:
        service.submit_guess(
            db,
            next(
                player for player in players
                if player.id not in (description.author_id, description.subject_id, guesser.id)
            ),
            description.id,
            description.author_id,
            None,
        )
    assert late.value.status_code == 409


@pytest.mark.parametrize("player_count", [5, 6, 7, 8])
def test_full_experience_advances_all_dynamic_rounds_without_repetition(db, player_count):
    _, players, game, descriptions = prepare_full_experience_guessing(db, player_count)
    seen = []
    for index, description in enumerate(descriptions):
        assert game.phase == "GUESSING"
        assert game.active_description_id == description.id
        assert game.round_deadline == game.round_started_at + timedelta(seconds=30)
        round_started_at = game.round_started_at
        seen.append(description.id)
        for guesser in players:
            if guesser.id != description.author_id:
                subject_guess = next(
                    player.id for player in players
                    if player.id not in (guesser.id, description.author_id)
                )
                service.submit_guess(db, guesser, description.id, description.author_id, subject_guess)
        assert game.phase == "REVEAL"
        if index < len(descriptions) - 1:
            with pytest.raises(HTTPException) as non_host:
                service.continue_game(db, players[1], game.version)
            assert non_host.value.status_code == 403
            service.continue_game(db, players[0], game.version)
            assert game.round_started_at >= round_started_at
    expected_rounds = player_count * (player_count - 1)
    assert len(seen) == len(set(seen)) == expected_rounds
    service.continue_game(db, players[0], game.version)
    assert game.phase == "FINISHED"


@pytest.mark.parametrize("tie_size", [2, 3, 4, 5, 6, 7, 8])
def test_full_experience_tiebreaker_supports_different_tie_sizes(db, tie_size):
    _, players, game, prompts = prepare_tiebreaker_room(db, tie_size)
    tied_ids = {player.id for player in players[:tie_size]}
    assert set(service.snapshot(db, players[0])["tie_participants"]) == tied_ids
    expected_count = tie_size * (len(players) - 1)
    assert len(prompts) == expected_count
    assert {(prompt.author_id, prompt.subject_id) for prompt in prompts} == {
        (author.id, subject.id)
        for author in players[:tie_size]
        for subject in players
        if subject.id != author.id
    }
    assert game.round_deadline == game.round_started_at + timedelta(seconds=30)
    for index, prompt in enumerate(prompts):
        for guesser in players:
            if guesser.id != prompt.author_id:
                service.submit_tiebreaker_guess(db, guesser, prompt.id, prompt.author_id)
        assert game.tie_stage == "REVEAL"
        service.continue_tiebreaker(db, players[0], game.version)
        if index < len(prompts) - 1:
            assert game.tie_stage == "GUESSING"
    result = service.snapshot(db, players[0])
    assert game.phase == "FINISHED"
    assert result["tie_completed"] is True
    assert set(result["winners"]) == tied_ids
    assert {row["id"] for row in result["tiebreaker_leaderboard"]} == tied_ids
    assert all(
        row["tiebreaker_points"] == (tie_size - 1) * (len(players) - 1)
        for row in result["tiebreaker_leaderboard"]
    )
    assert all(row["tiebreaker_points"] == expected_count for row in result["leaderboard"] if row["id"] not in tied_ids)


def make_finished_tie_room(db, tie_size=3, player_count=8):
    _, players = make_full_experience_room(db, player_count)
    game = db.get(Game, players[0].game_id)
    game.phase = "FINISHED"
    description = Description(
        id=service.new_id(),
        game_id=game.id,
        author_id=players[0].id,
        subject_id=players[1].id,
        text="A tie-score fixture.",
        sequence=0,
    )
    db.add(description)
    for player in players[:tie_size]:
        db.add(Guess(
            id=service.new_id(),
            description_id=description.id,
            guesser_id=player.id,
            author_guess_id=players[0].id,
            subject_guess_id=players[1].id,
            author_points=1,
        ))
    db.commit()
    return players, game


def prepare_tiebreaker_room(db, tie_size=3, player_count=8):
    players, game = make_finished_tie_room(db, tie_size, player_count)
    service.start_tiebreaker(db, players[0])
    for author in players[:tie_size]:
        service.submit_tiebreaker_descriptions(db, author, {
            subject.id: f"Description about player {subject.number} from player {author.number}."
            for subject in players
            if subject.id != author.id
        })
    prompts = list(db.scalars(
        select(TiebreakerPrompt)
        .where(TiebreakerPrompt.game_id == game.id)
        .order_by(TiebreakerPrompt.sequence)
    ))
    return players[0].game_id, players, game, prompts


def test_only_locked_tied_players_can_submit_complete_description_sets(db):
    players, game = make_finished_tie_room(db, tie_size=3)
    tied_ids = {player.id for player in players[:3]}
    service.start_tiebreaker(db, players[0])
    assert set(service.snapshot(db, players[-1])["tie_participants"]) == tied_ids
    with pytest.raises(HTTPException) as repeat_start:
        service.start_tiebreaker(db, players[0])
    assert repeat_start.value.status_code == 409

    non_tied_entries = {player.id: f"About {player.name}." for player in players[:-1]}
    with pytest.raises(HTTPException) as non_tied_writer:
        service.submit_tiebreaker_descriptions(db, players[-1], non_tied_entries)
    assert non_tied_writer.value.status_code == 403

    incomplete = {player.id: f"About {player.name}." for player in players[1:-1]}
    with pytest.raises(HTTPException) as missing_subject:
        service.submit_tiebreaker_descriptions(db, players[0], incomplete)
    assert missing_subject.value.status_code == 400
    with_self = {player.id: f"About {player.name}." for player in players if player.id != players[0].id}
    with_self[players[0].id] = "About myself."
    with pytest.raises(HTTPException) as self_description:
        service.submit_tiebreaker_descriptions(db, players[0], with_self)
    assert self_description.value.status_code == 400

    entries = {player.id: f"About {player.name}." for player in players if player.id != players[0].id}
    service.submit_tiebreaker_descriptions(db, players[0], entries)
    with pytest.raises(HTTPException) as duplicate_submission:
        service.submit_tiebreaker_descriptions(db, players[0], entries)
    assert duplicate_submission.value.status_code == 409
    for author in players[1:3]:
        service.submit_tiebreaker_descriptions(db, author, {
            subject.id: f"About {subject.name}."
            for subject in players
            if subject.id != author.id
        })
    prompts = list(db.scalars(select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id)))
    assert len(prompts) == 3 * (len(players) - 1)
    assert len({(prompt.author_id, prompt.subject_id) for prompt in prompts}) == len(prompts)


def test_tiebreaker_can_select_only_one_winner_from_the_original_tie(db):
    _, players, game, prompts = prepare_tiebreaker_room(db, tie_size=3)
    winner_id = players[0].id
    tied_ids = {player.id for player in players[:3]}
    for prompt in prompts:
        for guesser in players:
            if guesser.id == prompt.author_id:
                continue
            if guesser.id == winner_id:
                choice = prompt.author_id
            else:
                wrong = next(
                    (candidate.id for candidate in players[:3]
                     if candidate.id not in (guesser.id, prompt.author_id)),
                    prompt.author_id,
                )
                choice = wrong
            service.submit_tiebreaker_guess(db, guesser, prompt.id, choice)
        service.continue_tiebreaker(db, players[0], game.version)

    final = service.snapshot(db, players[0])
    assert final["winners"] == [winner_id]
    assert {row["id"] for row in final["tiebreaker_leaderboard"]} == tied_ids
    assert final["tiebreaker_leaderboard"][0]["id"] == winner_id


def test_tiebreaker_guesses_are_anonymous_subject_visible_and_author_only(db):
    _, players, game, prompts = prepare_tiebreaker_room(db, tie_size=3)
    prompt = prompts[0]
    author = next(player for player in players if player.id == prompt.author_id)
    non_tied_guesser = players[-1]
    tied_guesser = next(player for player in players[:3] if player.id not in (prompt.author_id, prompt.subject_id))

    author_state = service.snapshot(db, author)["active_tiebreaker"]
    guesser_state = service.snapshot(db, non_tied_guesser)["active_tiebreaker"]
    assert author_state["text"] == prompt.text
    assert author_state["subject_id"] == prompt.subject_id
    assert author_state["author_id"] is None
    assert author_state["is_author"] is True
    assert guesser_state["subject_id"] == prompt.subject_id
    assert guesser_state["author_id"] is None
    assert guesser_state["text"] == prompt.text
    assert set(service.snapshot(db, non_tied_guesser)["tie_participants"]) == {p.id for p in players[:3]}

    with pytest.raises(HTTPException) as author_sits_out:
        service.submit_tiebreaker_guess(db, author, prompt.id, players[1].id)
    assert author_sits_out.value.status_code == 403
    with pytest.raises(HTTPException) as cannot_guess_self:
        service.submit_tiebreaker_guess(db, tied_guesser, prompt.id, tied_guesser.id)
    assert cannot_guess_self.value.status_code == 400
    with pytest.raises(HTTPException) as non_tied_cannot_be_author:
        service.submit_tiebreaker_guess(db, non_tied_guesser, prompt.id, non_tied_guesser.id)
    assert non_tied_cannot_be_author.value.status_code == 400

    before_scores = {row["id"]: row["total"] for row in service.snapshot(db, players[0])["leaderboard"]}
    guessers = [player for player in players if player.id != prompt.author_id]
    for guesser in guessers:
        choice = prompt.author_id
        if guesser.id == non_tied_guesser.id:
            choice = next(player.id for player in players[:3] if player.id not in (prompt.author_id, guesser.id))
        service.submit_tiebreaker_guess(db, guesser, prompt.id, choice)
    reveal = service.snapshot(db, players[0])
    assert reveal["tie_stage"] == "REVEAL"
    assert len(reveal["active_tiebreaker"]["guesses"]) == len(players) - 1
    results = {guess["guesser_id"]: guess for guess in reveal["active_tiebreaker"]["guesses"]}
    assert results[non_tied_guesser.id]["points"] == 0
    assert all(
        result["points"] == 1
        for guesser_id, result in results.items()
        if guesser_id != non_tied_guesser.id
    )
    assert {row["id"]: row["total"] for row in reveal["leaderboard"]} == before_scores
    with pytest.raises(HTTPException) as duplicate:
        service.submit_tiebreaker_guess(db, guessers[0], prompt.id, prompt.author_id)
    assert duplicate.value.status_code == 409
    assert len(list(db.scalars(select(TiebreakerGuess).where(TiebreakerGuess.prompt_id == prompt.id)))) == len(players) - 1


def test_tiebreaker_timer_preserves_guesses_and_reconnect_does_not_reset_deadline(db):
    _, players, game, prompts = prepare_tiebreaker_room(db, tie_size=3)
    prompt = prompts[0]
    guesser = players[-1]
    service.submit_tiebreaker_guess(db, guesser, prompt.id, prompt.author_id)
    deadline = game.round_deadline
    service.mark_connected(db, guesser, False)
    service.mark_connected(db, guesser, True)
    assert game.round_deadline == deadline

    expired_at = now() + timedelta(seconds=31)
    assert service.expire_due_rounds(db, expired_at) == [game.id]
    guesses = list(db.scalars(select(TiebreakerGuess).where(TiebreakerGuess.prompt_id == prompt.id)))
    assert len(guesses) == len(players) - 1
    submitted = next(guess for guess in guesses if guess.guesser_id == guesser.id)
    assert not submitted.timed_out
    assert submitted.points == 1
    timed_out = [guess for guess in guesses if guess.timed_out]
    assert len(timed_out) == len(players) - 2
    assert all(guess.points == 0 and guess.author_guess_id is None for guess in timed_out)
    assert game.tie_stage == "REVEAL"
    assert game.round_deadline is None
    assert service.snapshot(db, players[1])["active_tiebreaker"]["guesses"]
    with pytest.raises(HTTPException):
        service.submit_tiebreaker_guess(db, players[1], prompt.id, prompt.author_id)


def test_classic_tiebreaker_preserves_configured_round_timer(db):
    _, players = make_room(db)
    game = db.get(Game, players[0].game_id)
    game.phase = "FINISHED"
    game.round_duration_seconds = 90
    description = Description(
        id=service.new_id(),
        game_id=game.id,
        author_id=players[0].id,
        subject_id=players[1].id,
        text="Tie fixture",
    )
    db.add(description)
    for player in players[:2]:
        db.add(Guess(
            id=service.new_id(),
            description_id=description.id,
            guesser_id=player.id,
            author_guess_id=players[0].id,
            subject_guess_id=players[1].id,
            author_points=1,
        ))
    db.commit()
    service.start_tiebreaker(db, players[0])
    for author in players[:2]:
        service.submit_tiebreaker_descriptions(db, author, {
            subject.id: f"About {subject.name}."
            for subject in players
            if subject.id != author.id
        })
    assert (game.round_deadline - game.round_started_at).total_seconds() == 90
