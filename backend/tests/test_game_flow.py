import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.models import Base, Description, Game, Guess, Player, TiebreakerPrompt
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
    service.start_tiebreaker(db, players[0])
    for player in players:
        service.submit_tiebreaker_clue(db, player, f"A fresh clue from player {player.number}.")
    assert game.phase == "TIEBREAKER"
    assert game.tie_stage == "GUESSING"
    prompts = list(db.scalars(select(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game.id).order_by(TiebreakerPrompt.sequence)))
    assert len(prompts) == 4
    for prompt_index, prompt in enumerate(prompts):
        for guesser in players:
            if guesser.id != prompt.author_id:
                service.submit_tiebreaker_guess(db, guesser, prompt.id, prompt.author_id)
        assert game.tie_stage == "REVEAL"
        reveal = service.snapshot(db, players[0])
        assert len(reveal["active_tiebreaker"]["guesses"]) == 3
        service.continue_tiebreaker(db, players[0], game.version)
        if prompt_index < 3:
            assert game.tie_stage == "GUESSING"
    final_tie = service.snapshot(db, players[0])
    assert game.phase == "FINISHED"
    assert game.tie_completed is True
    assert len(final_tie["winners"]) == 4
    assert all(player["total"] == 0 for player in final_tie["leaderboard"])
    assert all(player["tiebreaker_points"] == 3 for player in final_tie["leaderboard"])

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
