# Fourfold

A real-time, four-player anonymous guessing game. The backend owns room membership, phase transitions, hidden answers, and scoring. The browser stores a random session credential in `localStorage`; it is only sent in the `Authorization` header and is never put in a URL.

## Requirements

- Python 3.11+
- Node.js 20+
- PostgreSQL for deployment, or SQLite for local development

## Run locally

1. Backend:

   ```sh
   cd backend
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   cp ../.env.example .env
   alembic upgrade head
   uvicorn app.main:asgi_app --reload
   ```

   `DATABASE_URL=sqlite:///./game.db` is the convenient local default. For PostgreSQL, use `docker compose up -d postgres` from the repository root and set `DATABASE_URL=postgresql+psycopg://game:game@localhost:5432/guessing_game`.

2. Frontend, in another terminal:

   ```sh
   cd frontend
   npm install
   npm run dev
   ```

   Open http://localhost:5173. Vite proxies `/api` and `/socket.io` to the backend.

## Tests

```sh
cd backend
python3 -m pip install -r requirements.txt
pytest
```

```sh
cd frontend
npm install
npm test
npm run build
```

## Game rules and security

- A room reserves four numbered seats. A fifth new player and joining after the lobby closes are rejected.
- Each player privately drafts three descriptions. All 12 must be present before writing closes.
- Guessing is sealed. Each non-author submits one immutable guess per description. Author and subject scoring are independent (8 and 5 points).
- The server reveals and scores only after the three eligible guesses exist. Only the host can advance.
- A bearer session secret is generated with the OS CSPRNG; only its HMAC-SHA-256 digest is stored. Treat browser storage as a credential and do not share it.
- The current phase, active description, answers, and score totals are never accepted from clients.
- SQLite serializes local writes; PostgreSQL transactions and uniqueness constraints protect durable state. The service runs as a single Socket.IO process. Horizontal scaling requires a shared Socket.IO message manager and a coordinated database deployment.
- Disconnects do not count as incorrect guesses. A game waits for all required submissions; the host can cancel the game. A disconnected host role is reassigned to the lowest numbered connected player.
- A tied host can accept joint winners or start an optional tiebreaker. Each tied player privately writes one clue; the other tied players guess its author. Every tied player gets the same number of guesses, each correct guess earns one separate tiebreaker point, and main-game scores are never changed. A remaining tie is a joint win.
- After the game officially finishes, each player can download authoritative JSON results and a spreadsheet-ready CSV from the results screen. The host can separately select **Close Match Room**; after confirmation, this permanently deletes the room and all related game data. Save any needed results before closing.
- Result downloads are served by `GET /api/results/json` and `GET /api/results/csv`; host room closure uses `POST /api/close`. Connected clients receive `game:closing` and `game:closed` without game data in those events.

## Configuration and deployment

Copy `.env.example` to `backend/.env` and set a unique `APP_SECRET`, production PostgreSQL `DATABASE_URL`, comma-separated exact `FRONTEND_ORIGINS`, and the lobby seat reservation timeout. Never commit `.env`. Use TLS at the reverse proxy, restrict CORS to trusted origins, and keep the API and UI on trusted HTTPS origins.

Database migrations:

```

The migration adds the official finish timestamp used by result exports. Run `alembic upgrade head` when upgrading an existing database.sh
cd backend
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

The initial schema is created by Alembic. For local development only, `Base.metadata.create_all` is also used at app startup so a first run is frictionless. Troubleshooting: verify PostgreSQL is accepting connections, the `DATABASE_URL` driver matches the installed driver, `FRONTEND_ORIGINS` includes the exact UI origin, and the backend is reachable at the Vite proxy target.

## Scope note

The implementation includes room creation/joining, lobby readiness, private drafts, locked submissions, sealed guesses, reveal/scoring, host continuation, final standings, joint-win acceptance, a separate scored tiebreaker, cancellation, reconnection, REST endpoints, and individualized Socket.IO state broadcasts. The backend suite includes a live four-client Socket.IO/API test that completes all 12 descriptions, 36 main-game guesses, and the optional tiebreaker.
