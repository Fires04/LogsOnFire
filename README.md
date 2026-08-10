# Logs On Fire

A small self-hosted web app for watching logs — local or over SSH — without
repeatedly SSH-ing into servers and retyping paths. Keep a list of hosts,
attach log sources to each (exact path, glob pattern, or regex over a
directory), tail them live in the browser with a real `grep` filter bar, and
build dashboards that show several logs from different hosts at once.

## Features

- **Hosts**: local (the Logs On Fire container's own filesystem) or remote via
  SSH (password or private key, stored encrypted).
- **Log sources** per host: an exact path, a glob pattern
  (`/var/www/*/logs/*.log`), a regex filter over a directory tree, or the
  systemd journal (`journalctl`, whole journal or one unit).
- **File browser** for picking a log source's path directly instead of
  typing it — shows each entry's permissions and a best-effort "can you
  actually read this" indicator, both locally and over SFTP.
- **Live tail** over WebSocket, with up to `LOG_BUFFER_MAX_LINES` (default
  20 000) lines of backfill on open.
- **Live grep bar**: type real `grep` flags (`-i`, `-v`, `-A/-B/-C N`, `-w`,
  `-x`, `-E`, `-F`, `-m`, `-e`) and the view filters live, using the actual
  `grep` binary — not a reimplementation — so it also doubles as practice for
  real grep syntax.
- **Dashboards**: multiple log panels from different hosts, all live,
  multiplexed over a single WebSocket connection per open tab.
- **Open any log/dashboard in a new tab** (`/view/log/:id`,
  `/view/dashboard/:id`) — a direct replacement for the old
  duplicate-SSH-session/tmux workflow.
- Cookie-based auth, CSRF protection, encrypted-at-rest SSH credentials,
  trust-on-first-use SSH host key pinning, per-host SSH connection reuse
  (N viewers of the same host/file never open more than one SSH connection
  or one remote `tail` process), login rate limiting, and an audit log of
  logins/host changes/tail starts.

## Quick start (Docker)

```bash
cp .env.example .env
# fill in MASTER_KEY and JWT_SECRET, e.g.:
#   sed -i "s#^MASTER_KEY=.*#MASTER_KEY=$(openssl rand -base64 32)#" .env
#   sed -i "s#^JWT_SECRET=.*#JWT_SECRET=$(openssl rand -base64 48)#" .env

docker compose up -d --build
docker compose logs logsonfire   # first-boot admin password is printed here, once,
                                # if you didn't set ADMIN_PASSWORD in .env
```

Open `http://localhost:8000`, log in, add a host, add a log source, click
"View live".

For production, put Logs On Fire behind a TLS-terminating reverse proxy
(nginx/Traefik/Caddy) and set `TRUSTED_PROXY=true` in `.env` so it trusts
that proxy's `X-Forwarded-Proto`/`X-Forwarded-For` headers. Without a proxy
in front, `ENV=production` cookies require HTTPS — for local/direct HTTP
access use `ENV=development` instead.

## ⚠️ MASTER_KEY — read this before storing real credentials

Every SSH password and private key is encrypted at rest with **AES-256-GCM**
using `MASTER_KEY`. This key is **only** ever supplied via the environment —
it is never written to the database.

- If `MASTER_KEY` is lost, changed, or not backed up: **every stored SSH
  credential becomes permanently unrecoverable.** There is no recovery path
  by design — that's what "the key encrypts the secrets" means. You would
  need to re-enter every host's password/key.
- If you forget to set it at all, Logs On Fire will still start (for local
  experimentation) but generates a random key for that process only and logs
  a loud warning — anything encrypted with it is unreadable after a restart.
- Back up `MASTER_KEY` somewhere durable and **separate** from the database
  volume (a password manager, a secrets vault — not a file living next to
  the SQLite database it protects).
- A wrong/rotated key doesn't crash the app: connecting to a host whose
  credential can't be decrypted returns a clear
  "MASTER_KEY does not match" error instead.

## Configuration

All configuration is environment variables (see `.env.example` for Docker,
`backend/.env.example` for running the backend directly).

| Variable | Default | Notes |
|---|---|---|
| `ENV` | `development` | `production` enables `Secure` cookies (requires HTTPS or a TLS-terminating proxy) |
| `DB_PATH` | `./data/logsonfire.db` | SQLite file path |
| `MASTER_KEY` | *(none)* | base64, 32 bytes — `openssl rand -base64 32`. See warning above. |
| `JWT_SECRET` | *(none)* | signs session tokens — `openssl rand -base64 48` |
| `ADMIN_EMAIL` | `admin@example.com` | seeded on first boot only |
| `ADMIN_PASSWORD` | *(random, printed once)* | seeded on first boot only |
| `TRUSTED_PROXY` | `false` | set `true` only behind a TLS-terminating reverse proxy |
| `LOG_BUFFER_MAX_LINES` | `20000` | backfill/grep-corpus size per tailed file (10k–25k recommended) |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | session access token lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | session refresh token lifetime |
| `SSH_CONNECT_TIMEOUT_SECONDS` | `10` | |
| `SSH_IDLE_EVICTION_SECONDS` | `300` | how long an unused pooled SSH connection stays open |

## Architecture (short version)

- **Backend**: FastAPI + SQLAlchemy (async) + SQLite, `asyncssh` for SSH.
  `app/providers/` is a small interface (`LogProvider`) implemented by
  `LocalFileProvider` and `SshFileProvider` — adding another source is meant
  to be a new module + a registry entry, no changes elsewhere. This paid off
  already: the `journal` mode (tailing `journalctl` instead of a file) was
  added later as `app/providers/journal.py` plus a couple of dispatch lines
  in the two existing providers — nothing in `api/` or `tailing/` changed.
  `app/ssh/pool.py` reuses one SSH connection per host across every
  concurrent tail; `app/tailing/manager.py` de-duplicates so two viewers of
  the same file share one remote `tail -F` (or `journalctl -f`) process.
- **Frontend**: React + Vite SPA, built and served as static files by the
  same FastAPI process — one container, no separate frontend server.
- **Live tail**: one WebSocket per open browser tab (`/ws/logs`),
  multiplexed with `subscribe`/`unsubscribe`/`set_filter`/`clear_filter`
  messages so a whole dashboard shares a single connection.
- No log content is stored persistently — Logs On Fire is a live monitoring
  view, not a log archive. Log files on disk remain the only source of
  truth.

See `backend/app/` for the fuller module layout; most files carry a short
docstring explaining their role and, where relevant, the security reasoning
behind how they're implemented (e.g. `app/providers/ssh.py` on why SSH
commands are shell-quoted rather than passed as an argv array, and
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
attached to a terminal — which it never is here (subprocess pipe locally, SSH
exec channel remotely). Without countering that, freshly-logged lines can sit
unflushed for a long time, or effectively forever on a quiet unit — "live
tail" silently isn't live. Both providers wrap the follow command in
`stdbuf -oL` to force line buffering (falling back to the plain command if
the target host doesn't have `stdbuf`). Verified directly: `journalctl -f`
piped to a file produced nothing until the process was killed; `stdbuf -oL
journalctl -f` flushed each line within a second. See
`backend/tests/test_journal.py::test_tail_whole_journal_delivers_a_new_line_promptly`
for the regression test.

## Local development (without Docker)

Backend:
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # or: uv venv .venv
pip install -e ".[dev]"
cp .env.example .env   # fill in MASTER_KEY/JWT_SECRET, or leave blank for ephemeral dev keys
uvicorn app.main:app --reload --loop asyncio --port 8123
```

Frontend (in a second terminal — proxies `/api` and `/ws` to the backend
above, see `frontend/vite.config.ts`):
```bash
cd frontend
npm install
npm run dev
```

Run the backend test suite:
```bash
cd backend && source .venv/bin/activate && python -m pytest
```

## Verifying it end-to-end (what "done" looks like)

1. `docker compose up -d --build`, then `docker compose logs logsonfire` shows
   migrations running and (on first boot) the generated admin password.
2. Log in, add a `local` host and an `ssh` host (password or key auth).
3. Add a log source (try a glob like `/var/log/*.log`), click "Show matches"
   to preview matches before opening it live.
4. Open a log in a new tab, confirm live lines appear as the file grows, and
   the grep bar (`-i error -C 3`) filters live.
5. Open the same log in two tabs — only one SSH connection/remote `tail`
   process should exist on the target host regardless.
6. Build a dashboard from panels on different hosts; confirm devtools'
   Network tab shows exactly one WebSocket connection for that page.
7. Restart the container; hosts/log sources/dashboards and the ability to
   decrypt stored credentials should all survive (same `MASTER_KEY`, same
   volume).

## Known limitations / possible follow-ups

- Single admin user today; the schema (`users`/`roles`/`permissions`/
  `resource_grants`) is ready for multi-user + per-host/per-log ACLs, but
  the UI to manage that doesn't exist yet.
- No MASTER_KEY rotation tool yet (would decrypt-all/re-encrypt-all under a
  new key) — rotating today means re-entering every host's credentials.
- The dashboard layout editor is a simple ordered list with a width choice,
  not a drag-and-drop grid.
- WebSocket reconnect uses exponential backoff and resubscribes
  automatically, but there's no UI indicator distinguishing "briefly
  reconnecting" from "host has been unreachable for 10 minutes" beyond the
  status dot's tooltip.
