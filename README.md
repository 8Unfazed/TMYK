# TMYK

A real-time anonymous guessing game for exactly four players (Classic) or five to eight players (Full Experience). The backend owns room membership, phase transitions, hidden answers, and scoring. The browser stores a random session credential in `localStorage`; it is only sent in the `Authorization` header and is never put in a URL.

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

- A room reserves exactly four (Classic) or up to eight (Full Experience) numbered seats. Full Experience starts with at least five players. Additional players and joining after the lobby closes are rejected.
- Each player privately drafts a description about every other player. All 12 (Classic) or N × (N − 1) (Full Experience) must be present before writing closes.
- Guessing is sealed. Each non-author submits one immutable guess per description. Author and subject scoring are independent (8 and 5 points).
- The server reveals and scores only after all eligible guesses exist (three in Classic, N − 1 in Full Experience). Only the host can advance.
- Full Experience uses a fixed, server-enforced 30-second round timer; Classic retains the host-configurable timer.
- A bearer session secret is generated with the OS CSPRNG; only its HMAC-SHA-256 digest is stored. Treat browser storage as a credential and do not share it.
- The current phase, active description, answers, and score totals are never accepted from clients.
- SQLite serializes local writes; PostgreSQL transactions and uniqueness constraints protect durable state. The service runs as a single Socket.IO process. Horizontal scaling requires a shared Socket.IO message manager and a coordinated database deployment.
- Disconnects do not erase locked guesses or reset timers. Timed rounds preserve submitted answers and record unanswered players as zero-point timeouts; the host can cancel the game. A disconnected host role is reassigned to the lowest numbered connected player.
- A tied host can accept joint winners or start an optional author-identification tiebreaker. The tied players each write one anonymous description about every other player (T × (N − 1) total); all other players can guess its author, and the subject is shown. Only tied players are selectable authors, the writer sits out their own description, and each correct author guess earns one separate point. Tiebreaker points never change main-game scores, and only the original tied players can win; a remaining tie is shared.
- After the game officially finishes, each player can download authoritative JSON results and a spreadsheet-ready CSV from the results screen. The host can separately select **Close Match Room**; after confirmation, this permanently deletes the room and all related game data. Save any needed results before closing.
- Result downloads are served by `GET /api/results/json` and `GET /api/results/csv`; host room closure uses `POST /api/close`. Connected clients receive `game:closing` and `game:closed` without game data in those events.

## Configuration and deployment

Copy `.env.example` to `backend/.env` and set a unique `APP_SECRET`, production PostgreSQL `DATABASE_URL`, comma-separated exact `FRONTEND_ORIGINS`, and the lobby seat reservation timeout. Never commit `.env`. Use TLS at the reverse proxy, restrict CORS to trusted origins, and keep the API and UI on trusted HTTPS origins.

### Render and Vercel deployment

The project is a monorepo. Create a Render **Web Service** from the repository with:

- Root directory: `backend`
- Runtime: Python 3.12 (pinned by `backend/.python-version`)
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:asgi_app --host 0.0.0.0 --port $PORT`
- Health check path: `/api/health`
- Instance count: one for this Socket.IO in-memory deployment
- Pre-deploy/release command: `alembic upgrade head`

Attach a Render PostgreSQL database and set these service environment variables:

- `DATABASE_URL`: the Render database's **internal** connection URL. The app normalizes `postgres://`/`postgresql://` to the installed psycopg v3 driver.
- `APP_SECRET`: a unique secret of at least 32 characters. Generate it locally with `python -c "import secrets; print(secrets.token_hex(32))"` and enter it only in the Render dashboard.
- `FRONTEND_ORIGINS`: the exact Vercel HTTPS origin, for example `https://tmyk-example.vercel.app` (no trailing slash; comma-separate additional trusted origins).
- `SESSION_RESERVATION_MINUTES`: optional; defaults to `30`.
- `ROOM_CODE_LENGTH`: optional; defaults to `6`.

Run `alembic upgrade head` as a pre-deploy/release command before app startup. If that facility is unavailable on the selected plan, run it once from the service shell after setting its environment and before the first deploy. Do not run schema-reset or database-delete commands against the production database.

Create the Vercel project from the same repository with:

- Root directory: `frontend`
- Framework preset: Vite
- Build command: `npm run build`
- Output directory: `dist`
- Production environment variable: `VITE_API_URL=https://<your-render-service>.onrender.com` (backend origin only; do not append `/api`)
- Optional `VITE_SOCKET_URL`: backend origin; when omitted, Socket.IO uses `VITE_API_URL`.

The frontend's development proxy remains in `vite.config.ts`; deployed requests use the public Vite environment variable and HTTPS/WSS. The SPA rewrite in `frontend/vercel.json` supports direct browser navigation. Rebuild/redeploy Vercel after changing either public Vite variable.

Render supports inbound WebSockets, but deployments and network interruptions can disconnect clients; the current client reconnects. The present server keeps Socket.IO session mappings and rate-limit buckets in process memory, so do not scale it to multiple instances without adding a shared Socket.IO message manager and coordinated rate limiting. Render documents that free web services spin down after inactivity and free PostgreSQL expires after 30 days; those plans are suitable for testing, not durable public production use. Check current [Render pricing and free-instance limitations](https://render.com/docs/free) before selecting a plan.

For a free test deployment, the repository-root `render.yaml` defines a Render Blueprint for the backend and connects it to the existing `fourfold-db` PostgreSQL resource in the `Production` environment. It allows the deployed frontend at `https://tmyk.vercel.app`; update `FRONTEND_ORIGINS` in the Blueprint if that domain changes. Keep `backend/.python-version` committed so Render uses the tested Python version; generate and commit this file if it is absent from the deployed branch. Render generates `APP_SECRET`, applies Alembic migrations on startup, and checks `/api/health`. Set the Vercel project's `VITE_API_URL` to the backend's public origin after the backend deploys. The existing free database expires after 30 days, so export any needed results before then.

Database migrations:

```

The incremental migrations add finish timestamps, configurable round timers, game modes, and the author-identification tiebreaker data fields. Run `alembic upgrade head` when upgrading an existing database.sh
cd backend
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

The initial schema is created by Alembic. For local development only, `Base.metadata.create_all` is also used at app startup so a first run is frictionless. Troubleshooting: verify PostgreSQL is accepting connections, the `DATABASE_URL` driver matches the installed driver, `FRONTEND_ORIGINS` includes the exact UI origin, and the backend is reachable at the Vite proxy target.

## Scope note

The implementation includes both game modes, room creation/joining, lobby readiness, private drafts, locked submissions, sealed guesses, reveal/scoring, host continuation, final standings, joint-win acceptance, a separate scored tiebreaker, cancellation, reconnection, REST endpoints, and individualized Socket.IO state broadcasts. The backend suite includes a live four-client Socket.IO/API test for Classic plus service coverage across Full Experience player counts from five to eight.
