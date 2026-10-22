import csv
import io
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import service
from app.models import Base, Description, Game, Guess, Player, TiebreakerGuess, TiebreakerPrompt


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_room(db, suffix=""):
    created = service.create_room(db, f"Host{suffix}")
    players = [service.get_player(db, created["token"])]
    tokens = [created["token"]]
    for number in range(2, 5):
        joined = service.join_room(db, created["code"], f"Player {number}{suffix}")
        players.append(service.get_player(db, joined["token"]))
        tokens.append(joined["token"])
    return created, players, tokens


def finish_match(db, players):
    game = db.get(Game, players[0].game_id)
    for player in players:
        service.set_ready(db, player, True)
    service.start_game(db, players[0])
    for author in players:
        entries = {target.id: f"Description about player {target.number}." for target in players if target.id != author.id}
        service.submit_descriptions(db, author, entries)
    descriptions = list(db.scalars(select(Description).where(Description.game_id == game.id).order_by(Description.sequence)))
    for index, description in enumerate(descriptions):
        for guesser in players:
            if guesser.id != description.author_id:
                service.submit_guess(db, guesser, description.id, description.author_id, description.subject_id)
        if index < len(descriptions) - 1:
            service.continue_game(db, players[0], game.version)
    service.continue_game(db, players[0], game.version)
    return descriptions


def test_finished_game_exports_server_results_and_all_csv_guesses(db):
    created, players, _ = make_room(db)
    descriptions = finish_match(db, players)
    descriptions[0].text = 'A "quoted", multiline\ntruth'
    db.commit()

    results = service.results_data(db, players[1])
    assert results["room_code"] == created["code"]
    assert results["completed_at"].endswith("Z")
    assert len(results["descriptions"]) == 12
    assert results["descriptions"][0]["description"] == descriptions[0].text
    assert results["descriptions"][0]["author"]["player_number"] == next(p.number for p in players if p.id == descriptions[0].author_id)
    assert len(results["descriptions"][0]["guesses"]) == 3
    assert all(row["final_score"]["total_points"] == 117 for row in results["players"])
    assert len(results["tiebreaker_results"]) == 0

    exported_csv = list(csv.DictReader(io.StringIO(service.results_csv(results))))
    assert len(exported_csv) == 36
    first_row = next(row for row in exported_csv if row["Description Number"] == str(descriptions[0].sequence + 1))
    assert first_row["Description"] == descriptions[0].text
    assert int(exported_csv[0]["Total Points"]) == 13


def test_export_includes_tiebreaker_results(db):
    _, players, _ = make_room(db)
    finish_match(db, players)
    game = db.get(Game, players[0].game_id)
    prompt = TiebreakerPrompt(id="tie-prompt", game_id=game.id, author_id=players[0].id, text="Clue, with a comma", sequence=0, resolved=True)
    db.add(prompt)
    db.flush()
    db.add(TiebreakerGuess(id="tie-guess", prompt_id=prompt.id, guesser_id=players[1].id, author_guess_id=players[0].id, points=1))
    db.commit()

    results = service.results_data(db, players[0])
    assert results["tiebreaker_results"][0]["clue"] == "Clue, with a comma"
    assert results["tiebreaker_results"][0]["guesses"][0]["points"] == 1


def test_download_endpoints_return_json_and_csv_only_while_finished(db):
    from app import main

    created, players, tokens = make_room(db)
    finish_match(db, players)

    def override_db():
        yield db

    main.api.dependency_overrides[main.get_db] = override_db
    try:
        client = TestClient(main.api)
        headers = {"Authorization": f"Bearer {created['token']}"}
        json_response = client.get("/api/results/json", headers=headers)
        assert json_response.status_code == 200
        assert json_response.headers["content-disposition"].endswith(f"guessing-game-results-{created['code']}.json\"")
        assert len(json.loads(json_response.content)["descriptions"]) == 12
        csv_response = client.get("/api/results/csv", headers=headers)
        assert csv_response.status_code == 200
        assert len(list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))) == 36
        non_host_headers = {"Authorization": f"Bearer {tokens[1]}"}
        assert client.post("/api/close", headers=non_host_headers).status_code == 403
        assert client.post("/api/close", headers=headers).json() == {"closed": True}
        assert client.get("/api/results/json", headers=headers).status_code == 401

        unfinished, _, _ = make_room(db, "-unfinished")
        unfinished_headers = {"Authorization": f"Bearer {unfinished['token']}"}
        assert client.post("/api/close", headers=unfinished_headers).status_code == 409
    finally:
        main.api.dependency_overrides.pop(main.get_db, None)


def test_unfinished_or_non_host_cannot_close(db):
    _, players, _ = make_room(db)
    with pytest.raises(HTTPException) as unfinished:
        service.close_and_delete_game(db, players[0])
    assert unfinished.value.status_code == 409

    db.get(Game, players[0].game_id).phase = "FINISHED"
    db.commit()
    with pytest.raises(HTTPException) as unauthorized:
        service.close_and_delete_game(db, players[1])
    assert unauthorized.value.status_code == 403


def test_closure_removes_all_game_rows_invalidates_tokens_and_is_idempotent(db):
    created, players, _ = make_room(db)
    other, other_players, _ = make_room(db, "-other")
    game_id = players[0].game_id
    db.add(Description(id="description-1", game_id=game_id, author_id=players[0].id, subject_id=players[1].id, text="A clue", sequence=0, resolved=True))
    db.add(TiebreakerPrompt(id="prompt-1", game_id=game_id, author_id=players[0].id, text="Tie clue", sequence=0))
    db.flush()
    db.add_all([
        Guess(id="guess-1", description_id="description-1", guesser_id=players[1].id, author_guess_id=players[0].id, subject_guess_id=players[1].id),
        TiebreakerGuess(id="tie-guess-1", prompt_id="prompt-1", guesser_id=players[1].id, author_guess_id=players[0].id),
    ])
    db.get(Game, game_id).phase = "FINISHED"
    db.commit()

    assert service.close_and_delete_game(db, players[0])["already_closed"] is False
    assert db.get(Game, game_id) is None
    assert db.scalar(select(func.count()).select_from(Player).where(Player.game_id == game_id)) == 0
    assert db.scalar(select(func.count()).select_from(Description).where(Description.game_id == game_id)) == 0
    assert db.scalar(select(func.count()).select_from(Guess).where(Guess.id == "guess-1")) == 0
    assert db.scalar(select(func.count()).select_from(TiebreakerPrompt).where(TiebreakerPrompt.game_id == game_id)) == 0
    assert db.scalar(select(func.count()).select_from(TiebreakerGuess).where(TiebreakerGuess.id == "tie-guess-1")) == 0
    with pytest.raises(HTTPException) as invalid:
        service.get_player(db, created["token"])
    assert invalid.value.status_code == 401

    assert service.close_and_delete_game(db, players[0])["already_closed"] is True
    assert db.get(Game, other_players[0].game_id) is not None
    assert service.get_player(db, other["token"]).game_id == other_players[0].game_id


def test_failed_cleanup_rolls_back_and_can_be_retried(db, monkeypatch):
    _, players, _ = make_room(db)
    game_id = players[0].game_id
    db.get(Game, game_id).phase = "FINISHED"
    db.commit()
    service.begin_close_game(db, players[0])
    original_execute = db.execute

    def fail_delete(*args, **kwargs):
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(db, "execute", fail_delete)
    with pytest.raises(HTTPException) as failure:
        service.delete_closed_game(db, game_id)
    assert failure.value.status_code == 500
    monkeypatch.setattr(db, "execute", original_execute)
    assert db.get(Game, game_id).phase == "CLOSING"
    assert db.scalar(select(func.count()).select_from(Player).where(Player.game_id == game_id)) == 4

    service.close_and_delete_game(db, players[0])
    assert db.get(Game, game_id) is None


def test_results_are_unavailable_after_cleanup(db):
    _, players, _ = make_room(db)
    db.get(Game, players[0].game_id).phase = "FINISHED"
    db.commit()
    game_id = players[0].game_id
    service.close_and_delete_game(db, players[0])
    with pytest.raises(HTTPException) as deleted:
        service.results_data(db, players[0])
    assert deleted.value.status_code == 404
    assert db.get(Game, game_id) is None
