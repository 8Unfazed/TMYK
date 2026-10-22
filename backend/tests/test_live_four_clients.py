import asyncio
import os
import socket

import httpx
import pytest
import socketio
import uvicorn

def test_four_live_clients_complete_twelve_description_game(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'live.db'}"
    os.environ["APP_SECRET"] = "test-secret-for-live-integration"
    from app.main import asgi_app

    async def run_game():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="critical", access_log=False))
        server_task = asyncio.create_task(server.serve())
        clients = []
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            assert server.started
            base = f"http://127.0.0.1:{port}"
            async with httpx.AsyncClient(base_url=base, timeout=10) as http:
                created = (await http.post("/api/rooms", json={"name": "Player 1"})).json()
                records = [{"token": created["token"], "state": created["state"]}]
                assert (await http.post("/api/close", headers={"Authorization": f"Bearer {created['token']}"})).status_code == 409
                for number in range(2, 5):
                    response = await http.post("/api/rooms/join", json={"name": f"Player {number}", "code": created["code"]})
                    assert response.status_code == 200, response.text
                    records.append({"token": response.json()["token"], "state": response.json()["state"]})
                assert (await http.post("/api/rooms/join", json={"name": "Fifth", "code": created["code"]})).status_code == 409

                socket_states = [[] for _ in records]
                closure_events = [[] for _ in records]
                for index, record in enumerate(records):
                    client = socketio.AsyncClient(reconnection=False)
                    async def receive_state(data, index=index):
                        socket_states[index].append(data)
                    client.on("room:state", receive_state)
                    client.on("game:closing", lambda data, index=index: closure_events[index].append("closing"))
                    client.on("game:closed", lambda data, index=index: closure_events[index].append("closed"))
                    await client.connect(base, auth={"token": record["token"]}, transports=["websocket"])
                    clients.append(client)
                def headers(index):
                    return {"Authorization": f"Bearer {records[index]['token']}"}

                reconnect_id = records[2]["state"]["me"]["id"]
                await clients[2].disconnect()
                await clients[2].connect(base, auth={"token": records[2]["token"]}, transports=["websocket"])
                restored = (await http.get("/api/state", headers=headers(2))).json()
                assert restored["me"]["id"] == reconnect_id

                for index in range(4):
                    response = await http.post("/api/ready", json={"ready": True}, headers=headers(index))
                    assert response.status_code == 200, response.text
                response = await http.post("/api/start", headers=headers(0))
                assert response.status_code == 200, response.text

                for author_index in range(4):
                    descriptions = {}
                    for target_index in range(4):
                        if target_index == author_index:
                            continue
                        description_text = f"Player {author_index + 1} remembers a detail about player {target_index + 1}."
                        subject_id = records[target_index]["state"]["me"]["id"]
                        descriptions[subject_id] = description_text
                    response = await http.post("/api/descriptions/submit", json={"descriptions": descriptions}, headers=headers(author_index))
                    assert response.status_code == 200, response.text
                for author_index, record in enumerate(records):
                    own_state = (await http.get("/api/state", headers=headers(author_index))).json()
                    assert own_state["phase"] == "GUESSING"
                    assert own_state["active_description"] is not None

                # The database-assigned sequence is intentionally opaque to clients; determine
                # answer keys from the independent descriptions submitted by the simulated clients.
                expected_answers = {}
                for author_index in range(4):
                    for target_index in range(4):
                        if author_index != target_index:
                            text = f"Player {author_index + 1} remembers a detail about player {target_index + 1}."
                            expected_answers[text] = (author_index, target_index)

                resolved = 0
                while True:
                    current = (await http.get("/api/state", headers=headers(0))).json()
                    if current["phase"] == "FINISHED":
                        break
                    assert current["phase"] == "GUESSING"
                    active_id = current["active_description"]["id"]
                    text = current["active_description"]["text"]
                    answer = expected_answers.get(text)
                    if answer is None:
                        # Player 1 is intentionally excluded on their own card; another client
                        # can read the same public-to-guessers text.
                        for index in range(1, 4):
                            candidate = (await http.get("/api/state", headers=headers(index))).json()["active_description"]
                            if candidate and candidate["text"]:
                                text = candidate["text"]
                                break
                        answer = expected_answers[text]
                    author_index, target_index = answer
                    author_id = records[author_index]["state"]["me"]["id"]
                    subject_id = records[target_index]["state"]["me"]["id"]
                    author_view = (await http.get("/api/state", headers=headers(author_index))).json()["active_description"]
                    assert author_view["is_author"] is True
                    assert author_view["text"] is None
                    assert author_view["author_id"] is None
                    for guesser_index in range(4):
                        if guesser_index == author_index:
                            continue
                        response = await http.get("/api/state", headers=headers(guesser_index))
                        guess_state = response.json()
                        assert guess_state["active_description"]["author_id"] is None
                        assert guess_state["active_description"]["text"] == text
                        assert guess_state["active_description"]["guesses"] == []
                        result = await http.post("/api/guesses", json={
                            "description_id": active_id,
                            "author_guess_id": author_id,
                            "subject_guess_id": subject_id,
                        }, headers=headers(guesser_index))
                        assert result.status_code == 200, result.text
                    reveal = (await http.get("/api/state", headers=headers(0))).json()
                    assert reveal["phase"] == "REVEAL"
                    assert len(reveal["active_description"]["guesses"]) == 3
                    assert reveal["active_description"]["author_id"] == author_id
                    assert reveal["active_description"]["subject_id"] == subject_id
                    resolved += 1
                    result = await http.post("/api/continue", json={"expected_version": reveal["version"]}, headers=headers(0))
                    assert result.status_code == 200, result.text

                final = (await http.get("/api/state", headers=headers(0))).json()
                assert resolved == 12
                assert final["phase"] == "FINISHED"
                assert len(final["descriptions"]) == 12
                assert sum(len(description["guesses"]) for description in final["descriptions"]) == 36
                assert all(description["resolved"] for description in final["descriptions"])
                assert len({player["total"] for player in final["leaderboard"]}) == 1
                main_scores = {player["id"]: player["total"] for player in final["leaderboard"]}
                started = await http.post("/api/tiebreaker/start", headers=headers(0))
                assert started.status_code == 200, started.text
                clue_authors = {}
                for index in range(4):
                    clue_text = f"A new clue in player {index + 1}'s own voice."
                    clue_authors[clue_text] = records[index]["state"]["me"]["id"]
                    response = await http.post("/api/tiebreaker/clue", json={"text": clue_text}, headers=headers(index))
                    assert response.status_code == 200, response.text
                tiebreaker_resolved = 0
                while True:
                    tie_state = (await http.get("/api/state", headers=headers(0))).json()
                    if tie_state["phase"] == "FINISHED":
                        break
                    assert tie_state["phase"] == "TIEBREAKER"
                    assert tie_state["tie_stage"] == "GUESSING"
                    active_tie = tie_state["active_tiebreaker"]
                    clue = active_tie["text"]
                    if not clue:
                        for index in range(1, 4):
                            candidate = (await http.get("/api/state", headers=headers(index))).json()["active_tiebreaker"]
                            if candidate and candidate["text"]:
                                clue = candidate["text"]
                                break
                    author_id = clue_authors[clue]
                    author_index = next(index for index, record in enumerate(records) if record["state"]["me"]["id"] == author_id)
                    author_view = (await http.get("/api/state", headers=headers(author_index))).json()["active_tiebreaker"]
                    assert author_view["is_author"] is True
                    assert author_view["text"] is None
                    for guesser_index, record in enumerate(records):
                        if record["state"]["me"]["id"] == author_id:
                            continue
                        response = await http.post("/api/tiebreaker/guess", json={
                            "prompt_id": active_tie["id"],
                            "author_guess_id": author_id,
                        }, headers=headers(guesser_index))
                        assert response.status_code == 200, response.text
                    reveal = (await http.get("/api/state", headers=headers(0))).json()
                    assert reveal["tie_stage"] == "REVEAL"
                    assert len(reveal["active_tiebreaker"]["guesses"]) == 3
                    tiebreaker_resolved += 1
                    response = await http.post("/api/tiebreaker/continue", json={"expected_version": reveal["version"]}, headers=headers(0))
                    assert response.status_code == 200, response.text
                final = (await http.get("/api/state", headers=headers(0))).json()
                assert tiebreaker_resolved == 4
                assert final["tie_completed"] is True
                assert len(final["tiebreaker_prompts"]) == 4
                assert sum(len(prompt["guesses"]) for prompt in final["tiebreaker_prompts"]) == 12
                assert {player["id"]: player["total"] for player in final["leaderboard"]} == main_scores
                assert all(player["tiebreaker_points"] == 3 for player in final["leaderboard"])
                assert len(final["winners"]) == 4
                results_response = await http.get("/api/results/json", headers=headers(1))
                assert results_response.status_code == 200
                assert len(results_response.json()["descriptions"]) == 12
                csv_response = await http.get("/api/results/csv", headers=headers(2))
                assert csv_response.status_code == 200
                assert len(csv_response.content.splitlines()) == 37
                assert (await http.post("/api/close", headers=headers(1))).status_code == 403
                close_response = await http.post("/api/close", headers=headers(0))
                assert close_response.status_code == 200, close_response.text
                assert close_response.json() == {"closed": True}
                await asyncio.sleep(0.05)
                assert all(socket_states), "each connected client should receive individualized live snapshots"
                assert all(events == ["closing", "closed"] for events in closure_events)
                assert (await http.get("/api/state", headers=headers(0))).status_code == 401
                assert (await http.get("/api/results/json", headers=headers(1))).status_code == 401
                assert (await http.post("/api/rooms/join", json={"name": "Stale", "code": created["code"]})).status_code == 404
                assert (await http.post("/api/guesses", json={
                    "description_id": final["descriptions"][0]["id"],
                    "author_guess_id": final["descriptions"][0]["author_id"],
                }, headers=headers(2))).status_code == 401
                with pytest.raises(socketio.exceptions.ConnectionError):
                    await clients[0].connect(base, auth={"token": records[0]["token"]}, transports=["websocket"])
        finally:
            for client in clients:
                if client.connected:
                    await client.disconnect()
            server.should_exit = True
            await server_task

    asyncio.run(run_game())
