import os
import time
from collections import defaultdict, deque
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import json
import socketio
from sqlalchemy.orm import Session
from .db import SessionLocal, engine, get_db
from .models import Base, Player
from . import schemas, service

Base.metadata.create_all(bind=engine)
api = FastAPI(title="Fourfold API", version="1.0.0")
origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
api.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=origins, logger=False, engineio_logger=False)
asgi_app = socketio.ASGIApp(sio, other_asgi_app=api)
sid_players: dict[str, str] = {}
rate_buckets: dict[str, deque] = defaultdict(deque)

def _limit(request: Request, key: str, maximum: int, period: int = 60):
    bucket = rate_buckets[f"{request.client.host if request.client else 'unknown'}:{key}"]
    now = time.monotonic()
    while bucket and bucket[0] < now - period:
        bucket.popleft()
    if len(bucket) >= maximum:
        raise HTTPException(status_code=429, detail="Too many attempts; please wait and try again")
    bucket.append(now)

def _auth_token(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A player session is required")
    token = authorization[7:]
    if len(token) < 32:
        raise HTTPException(status_code=401, detail="Invalid player session")
    return token

def current_player(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    return service.get_player(db, _auth_token(authorization))

async def broadcast_game(game_id: str):
    db = SessionLocal()
    try:
        payloads = [(player.id, service.snapshot(db, player)) for player in service._members(db, game_id)]
    finally:
        db.close()
    for player_id, payload in payloads:
        if payload["phase"] == "CLOSING":
            continue
        matching_sids = [sid for sid, current_player_id in sid_players.items() if current_player_id == player_id]
        for sid in matching_sids:
            await sio.emit("room:state", payload, to=sid)

@api.get("/api/health")
def health():
    return {"status": "ok"}

@api.post("/api/rooms")
async def create_room(body: schemas.CreateRoom, request: Request, db: Session = Depends(get_db)):
    _limit(request, "create", 5)
    result = service.create_room(db, body.name)
    player = service.get_player(db, result["token"])
    result["state"] = service.snapshot(db, player)
    return result

@api.post("/api/rooms/join")
async def join_room(body: schemas.JoinRoom, request: Request, db: Session = Depends(get_db)):
    _limit(request, "join", 12)
    result = service.join_room(db, body.code, body.name)
    player = service.get_player(db, result["token"])
    result["state"] = service.snapshot(db, player)
    await broadcast_game(result["game_id"])
    return result

@api.get("/api/state")
def get_state(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    return service.snapshot(db, player)

@api.get("/api/results/json")
def download_results_json(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    results = service.results_data(db, player)
    code = results["room_code"]
    return Response(
        content=json.dumps(results, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="guessing-game-results-{code}.json"'},
    )

@api.get("/api/results/csv")
def download_results_csv(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    results = service.results_data(db, player)
    code = results["room_code"]
    return Response(
        content="\ufeff" + service.results_csv(results),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="guessing-game-results-{code}.csv"'},
    )

@api.post("/api/close")
async def close_match(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    closure = service.begin_close_game(db, player)
    if closure["already_closed"]:
        return {"closed": True}
    game_id = closure["game_id"]
    member_ids = {member.id for member in service._members(db, game_id)}
    affected_sids = [sid for sid, player_id in sid_players.items() if player_id in member_ids]
    room = f"game:{game_id}"
    await sio.emit("game:closing", {}, room=room)
    service.delete_closed_game(db, game_id)
    await sio.emit("game:closed", {}, room=room)
    for sid in affected_sids:
        sid_players.pop(sid, None)
        await sio.disconnect(sid)
    return {"closed": True}

@api.post("/api/ready")
async def ready(body: schemas.ReadyRequest, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.set_ready(db, player, body.ready)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/start")
async def start(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.start_game(db, player)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/descriptions/draft")
async def draft(body: schemas.DraftRequest, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.save_draft(db, player, body.subject_id, body.text)
    return service.snapshot(db, player)

@api.post("/api/descriptions/submit")
async def submit_descriptions(body: schemas.SubmitDescriptions, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.submit_descriptions(db, player, body.descriptions)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/guesses")
async def guess(body: schemas.GuessRequest, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.submit_guess(db, player, body.description_id, body.author_guess_id, body.subject_guess_id)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/continue")
async def continue_game(body: schemas.ContinueRequest, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.continue_game(db, player, body.expected_version)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/cancel")
async def cancel(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.cancel_game(db, player)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/accept-tie")
async def accept_tie(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.accept_tie(db, player)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/tiebreaker/start")
async def start_tiebreaker(player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.start_tiebreaker(db, player)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/tiebreaker/clue")
async def submit_tiebreaker_clue(body: schemas.TiebreakerClue, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.submit_tiebreaker_clue(db, player, body.text)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/tiebreaker/guess")
async def submit_tiebreaker_guess(body: schemas.TiebreakerGuessRequest, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.submit_tiebreaker_guess(db, player, body.prompt_id, body.author_guess_id)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.post("/api/tiebreaker/continue")
async def continue_tiebreaker(body: schemas.ContinueRequest, player: Player = Depends(current_player), db: Session = Depends(get_db)):
    service.continue_tiebreaker(db, player, body.expected_version)
    await broadcast_game(player.game_id)
    return service.snapshot(db, player)

@api.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if not token or len(token) < 32:
        return False
    db = SessionLocal()
    try:
        player = service.get_player(db, token)
        service.mark_connected(db, player, True)
        sid_players[sid] = player.id
        await sio.enter_room(sid, f"game:{player.game_id}")
        await sio.emit("room:state", service.snapshot(db, player), to=sid)
        await broadcast_game(player.game_id)
        return True
    except HTTPException:
        return False
    finally:
        db.close()

@sio.on("session:sync")
async def socket_sync(sid, data=None):
    player_id = sid_players.get(sid)
    if not player_id:
        return {"error": "unauthorized"}
    db = SessionLocal()
    try:
        player = db.get(Player, player_id)
        if not player:
            return {"error": "unauthorized"}
        if player.game.phase == "CLOSING":
            return {"error": "room_closing"}
        return service.snapshot(db, player)
    finally:
        db.close()

@sio.event
async def disconnect(sid, reason=None):
    player_id = sid_players.pop(sid, None)
    if not player_id:
        return
    db = SessionLocal()
    try:
        player = db.get(Player, player_id)
        if player:
            game_id = player.game_id
            try:
                service.mark_connected(db, player, False)
                await broadcast_game(game_id)
            except HTTPException:
                pass
    finally:
        db.close()
