# Logs On Fire

A small self-hosted web app for watching logs live from a browser, without
SSH-ing into servers and retyping paths. A lightweight **agent** runs on
each monitored host, reads logs locally, and pushes them to the central
server over a connection *it* opens — the server never needs SSH access or
credentials for your hosts, and your hosts never need an open inbound port.
Attach log sources to each agent (exact path, glob pattern, or regex over a
directory, or the systemd journal), tail them live in the browser with a
real `grep` filter bar, and build dashboards that show several logs from
different hosts at once.

## Features

- **Agents**: a small process (`agent/`) installed on each monitored host.
  It dials out to the server over WebSocket and authenticates with a
  bearer token generated when you enroll it — no inbound access to the
  host is ever needed, and it only ever reads that host's own filesystem/
  journal (no remote credentials to manage).
- **Log sources** per agent: an exact path, a glob pattern
  (`/var/www/*/logs/*.log`), a regex filter over a directory tree, or the
  systemd journal (`journalctl`, whole journal or one unit).
- **File browser** for picking a log source's path directly instead of
  typing it — shows each entry's permissions and a best-effort "can you
  actually read this" indicator, resolved by the agent on its own host.
- **Live tail** over WebSocket, with backfill on open. A log source is only
  actively tailed by its agent while at least one browser tab is watching
  it — closing every viewer stops it, so an idle dashboard costs nothing on
  the monitored host.
- **Live grep bar**: type real `grep` flags (`-i`, `-v`, `-A/-B/-C N`, `-w`,
  `-x`, `-E`, `-F`, `-m`, `-e`) and the view filters live, using the actual
  `grep` binary — not a reimplementation — so it also doubles as practice for
  real grep syntax.
- **Dashboards**: multiple log panels from different agents, all live,
  multiplexed over a single WebSocket connection per open tab.
- **Open any log/dashboard in a new tab** (`/view/log/:id`,
  `/view/dashboard/:id`) — a direct replacement for the old
  duplicate-SSH-session/tmux workflow.
- Cookie-based dashboard-user auth, CSRF protection, HMAC-hashed
  (never reversibly stored) agent bearer tokens, per-agent connection
  status with last-seen/heartbeat latency, login rate limiting, and an
  audit log of logins/agent changes/tail starts.

## Quick start (Docker)

```bash
cp .env.example .env
# fill in AGENT_TOKEN_PEPPER and JWT_SECRET, e.g.:
#   sed -i "s#^AGENT_TOKEN_PEPPER=.*#AGENT_TOKEN_PEPPER=$(openssl rand -base64 32)#" .env
#   sed -i "s#^JWT_SECRET=.*#JWT_SECRET=$(openssl rand -base64 48)#" .env

docker compose up -d --build
docker compose logs logsonfire   # first-boot admin password is printed here, once,
                                # if you didn't set ADMIN_PASSWORD in .env
```

Open `http://localhost:8000`, log in, go to **Agents → + New agent**, copy
the generated token, then install the agent on the host you want to
monitor:

```bash
curl -fsSL http://<this-server>:8000/agent/install.sh | sudo bash -s -- \
  --server ws://<this-server>:8000 --token <the-token-you-just-copied>
```

Once the agent shows **online** on the Agents page, add a log source to it
and click "View live".

For production, put Logs On Fire behind a TLS-terminating reverse proxy
(nginx/Traefik/Caddy) and set `TRUSTED_PROXY=true` in `.env` so it trusts
that proxy's `X-Forwarded-Proto`/`X-Forwarded-For` headers; use `wss://`
for the agent's `--server` in that case. Without a proxy in front,
`ENV=production` cookies require HTTPS — for local/direct HTTP access use
`ENV=development` instead.

## ⚠️ AGENT_TOKEN_PEPPER — read this before enrolling real hosts

Every agent's bearer token is hashed (HMAC-SHA256, one-way) with
`AGENT_TOKEN_PEPPER` before being stored — it is **never** stored or
logged in plaintext anywhere, and is only ever shown once, at enrollment
or token reissue.

- If `AGENT_TOKEN_PEPPER` is lost or rotated: every agent's stored token
  hash stops matching, so every agent fails to authenticate. This is
  **not** catastrophic — reissue each agent's token from the Agents page
  and update its config; no log data or log-source configuration is lost
  (unlike the old SSH-credential model this replaced, where losing the
  encryption key made stored credentials permanently unrecoverable).
- If you forget to set it at all, Logs On Fire will still start (for local
  experimentation) but generates a random pepper for that process only and
  logs a loud warning — every agent token hashed with it stops matching
  after a restart.
- Back up `AGENT_TOKEN_PEPPER` somewhere durable if you don't want to
  re-enroll every agent after a redeploy that doesn't preserve it.

## Configuration

All configuration is environment variables (see `.env.example` for Docker,
`backend/.env.example` for running the backend directly).

| Variable | Default | Notes |
|---|---|---|
| `ENV` | `development` | `production` enables `Secure` cookies (requires HTTPS or a TLS-terminating proxy) |
| `DB_PATH` | `./data/logsonfire.db` | SQLite file path |
| `AGENT_TOKEN_PEPPER` | *(none)* | base64, 32 bytes — `openssl rand -base64 32`. See warning above. |
| `JWT_SECRET` | *(none)* | signs dashboard-user session tokens — `openssl rand -base64 48` |
| `ADMIN_EMAIL` | `admin@example.com` | seeded on first boot only |
| `ADMIN_PASSWORD` | *(random, printed once)* | seeded on first boot only |
| `TRUSTED_PROXY` | `false` | set `true` only behind a TLS-terminating reverse proxy |
| `LOG_BUFFER_MAX_LINES` | `20000` | backfill/grep-corpus size per tailed file (10k–25k recommended) |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | dashboard-user session access token lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | dashboard-user session refresh token lifetime |
| `AGENT_HEARTBEAT_INTERVAL_SECONDS` | `30` | how often the server pings each connected agent |
| `AGENT_HEARTBEAT_TIMEOUT_SECONDS` | `90` | no pong within this window and the agent is marked offline |
| `AGENT_REQUEST_TIMEOUT_SECONDS` | `10` | resolve/browse/start_tail reply timeout before returning a clean "agent did not respond" error |

## Architecture (short version)

- **Server** (`backend/`): FastAPI + SQLAlchemy (async) + SQLite. Never
  touches a monitored host's filesystem directly — everything goes through
  the agent that host is running, over a persistent WebSocket
  (`/ws/agent`) the agent itself opens. `app/agents/registry.py` holds one
  live connection per agent plus request/reply matching for resolve/browse/
  start_tail; `app/tailing/manager.py` de-duplicates so two browser viewers
  of the same file share one `start_tail` (and one ring buffer) instead of
  each triggering their own. A log source is only actively streamed by its
  agent while at least one browser subscriber exists — the persistent
  agent↔server connection itself is a lightweight idle control channel the
  rest of the time.
- **Agent** (`agent/` + `agentcore/`): a small, separately-packaged Python
  process installed on each monitored host. `agentcore/` holds the actual
  local-file/journal reading logic (`LogProvider` interface,
  `LocalFileProvider`) with zero dependency on the server's web/DB stack,
  so installing the agent doesn't pull in FastAPI/SQLAlchemy. Adding a new
  log source type is meant to be a new module here + a small dispatch
  addition, not changes scattered through the server.
- **Frontend**: React + Vite SPA, built and served as static files by the
  same FastAPI process — one container, no separate frontend server.
- **Live tail (browser-facing)**: one WebSocket per open browser tab
  (`/ws/logs`), multiplexed with `subscribe`/`unsubscribe`/`set_filter`/
  `clear_filter` messages so a whole dashboard shares a single connection.
  This protocol is unchanged by the agent-push rewrite — only how the
  server *gets* the lines changed.
- No log content is stored persistently — Logs On Fire is a live monitoring
  view, not a log archive. Log files on disk (on each monitored host)
  remain the only source of truth.

See `backend/app/`, `agentcore/logsonfire_agentcore/`, and
`agent/logsonfire_agent/` for the fuller module layout; most files carry a
short docstring explaining their role and, where relevant, the security
reasoning behind how they're implemented (e.g. `app/security/agent_tokens.py`
on why tokens are HMAC-hashed rather than encrypted, and
`app/tailing/grep.py` on how the grep bar is sandboxed).

### A note on `--loop asyncio`

`app/entrypoint.py` explicitly runs uvicorn with `loop="asyncio"` instead of
its default `uvloop`. This isn't a style preference: under uvloop, this
app's SQLAlchemy async engine (which bridges aiosqlite's worker thread back
into async code via `greenlet`) hangs completely on startup in this setup.
This was found through direct testing, not a hypothetical — don't remove
`loop="asyncio"` without re-verifying against a real run first.

### A note on journal-mode buffering

`journalctl --follow` fully block-buffers its own stdout whenever it isn't
attached to a terminal — which it never is when the agent runs it as a
subprocess. Without countering that, freshly-logged lines can sit unflushed
for a long time, or effectively forever on a quiet unit — "live tail"
silently isn't live. `agentcore/logsonfire_agentcore/local.py` wraps the
follow command in `stdbuf -oL` to force line buffering (falling back to the
plain command if the monitored host doesn't have `stdbuf`). Verified
directly: `journalctl -f` piped to a file produced nothing until the
process was killed; `stdbuf -oL journalctl -f` flushed each line within a
second. See
`agentcore/tests/test_journal.py::test_tail_whole_journal_delivers_a_new_line_promptly`
for the regression test.

## Local development (without Docker)

Backend (server):
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # or: uv venv .venv
pip install -e ".[dev]"
cp .env.example .env   # fill in AGENT_TOKEN_PEPPER/JWT_SECRET, or leave blank for ephemeral dev keys
uvicorn app.main:app --reload --loop asyncio --port 8123
```

Frontend (in a second terminal — proxies `/api` and `/ws` to the backend
above, see `frontend/vite.config.ts`):
```bash
cd frontend
npm install
npm run dev
```

Agent (run on whatever host you want to test tailing against — can be the
same machine during development):
```bash
cd agentcore && pip install -e .   # or: uv venv .venv && uv pip install -e .
cd ../agent && pip install -e .
LOGSONFIRE_SERVER_URL=ws://localhost:8123 LOGSONFIRE_AGENT_TOKEN=<token-from-the-Agents-page> \
  logsonfire-agent
```

Run the test suites:
```bash
cd backend && source .venv/bin/activate && python -m pytest
cd agentcore && source .venv/bin/activate && python -m pytest
```

## Verifying it end-to-end (what "done" looks like)

1. `docker compose up -d --build`, then `docker compose logs logsonfire` shows
   migrations running and (on first boot) the generated admin password.
2. Log in, create an agent, install it on a host (or locally for testing),
   confirm it shows **online** with a recent "last seen" on the Agents page.
3. Add a log source (try a glob like `/var/log/*.log`), click "Show matches"
   to preview matches before opening it live.
4. Open a log in a new tab, confirm live lines appear as the file grows, and
   the grep bar (`-i error -C 3`) filters live.
5. Close every viewer of that log, confirm (e.g. via the agent's own logs)
   that it stops actively tailing — reopening it resumes from a fresh
   backfill read, not a gap-filled stream.
6. Build a dashboard from panels on different agents; confirm devtools'
   Network tab shows exactly one WebSocket connection for that page.
7. Stop the agent process; confirm the open log panel's status moves to
   "closed" rather than hanging, and the Agents page shows it offline.
8. Restart the server container; agents/log sources/dashboards should all
   survive (same volume) — agents reconnect automatically using their
   already-configured token, no re-enrollment needed.

## Known limitations / possible follow-ups

- Single admin user today; the schema (`users`/`roles`/`permissions`/
  `resource_grants`) is ready for multi-user + per-agent/per-log ACLs, but
  the UI to manage that doesn't exist yet.
- The dashboard layout editor and the Agents/Hosts UI are mid-migration to
  a drag-and-drop grid (`react-grid-layout`) and a Mantine-based redesign —
  check the current state of `frontend/src` before assuming either is
  finished.
- WebSocket reconnect (both browser↔server and agent↔server) uses
  exponential backoff and resubscribes/resumes automatically, but there's
  no UI indicator distinguishing "briefly reconnecting" from "agent has
  been unreachable for 10 minutes" beyond the status dot's tooltip and the
  Agents page's last-seen timestamp.
