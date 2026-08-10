# CLAUDE.md

Guidance for Claude Code (or any AI assistant) working in this repository.
This file is for *maintainers/assistants*; `README.md` is for end users —
keep facts in the file that matches their audience, don't duplicate.

## What this is

Logs On Fire: a self-hosted single-container web app for live-tailing local
and remote (SSH) logs from a browser — hosts, per-host log sources
(exact path / glob / regex / systemd journal), live tail over WebSocket with
a real-`grep`-based filter bar, multi-log dashboards, encrypted-at-rest SSH
credentials. See `README.md` for the user-facing feature list and deployment
instructions — don't re-derive that here.

## Layout

```
backend/app/
  providers/    LogProvider ABC (base.py) + LocalFileProvider, SshFileProvider,
                journal.py (journalctl support, shared by both providers)
  ssh/          connection pooling (pool.py), TOFU host-key handling (connect.py)
  tailing/      TailSession (ring buffer), manager.py (dedup), broker.py
                (pub/sub fan-out), grep.py (sandboxed real-grep filter)
  security/     crypto.py (AES-256-GCM for host creds), passwords.py (argon2id),
                jwt.py, deps.py (cookie/CSRF wiring)
  api/routes/   REST + the one WebSocket endpoint (ws_logs.py)
frontend/src/
  routes/       page-level components (one per route in App.tsx)
  components/   shared UI (LogPanel, FileExplorer, LogSourceViewer, ...)
  lib/          wsClient.ts (multiplexed reconnecting WS client), api.ts, logHighlight.tsx
```

The one design rule worth preserving: `providers/base.py`'s `LogProvider`
interface is deliberately small (`resolve_sources`, `read_tail`, `tail`,
`list_directory`, `default_browse_path`) so a new log source type is a new
module + a registry entry, not changes scattered through `api/`/`tailing/`.
The `journal` mode was added this way after the fact with zero changes to
`api/` or `tailing/` — if you're tempted to special-case a new source type
in the WebSocket handler or the tailing layer, that's a sign to instead teach
the *provider* to dispatch on the resolved path (see how both providers
detect `journal://` paths via `journal_unit_from_path()`).

## Non-obvious gotchas (found by direct testing — don't "fix" these back)

- **`--loop asyncio` is required.** `app/entrypoint.py` explicitly avoids
  uvicorn's default `uvloop`: under uvloop, the SQLAlchemy async engine
  (bridging aiosqlite's worker thread back via `greenlet`) hangs completely
  on startup. Verified directly, not a hypothetical.

- **journalctl needs `stdbuf -oL`.** `journalctl --follow` fully
  block-buffers its own stdout whenever it isn't a tty (always true for a
  subprocess pipe or an SSH exec channel) — without forcing line buffering,
  freshly-logged lines sit unflushed indefinitely instead of arriving live.
  Both `providers/local.py` and `providers/ssh.py` wrap the follow command in
  `stdbuf -oL` (falling back to the plain command if the target lacks
  `stdbuf`). Regression test:
  `backend/tests/test_journal.py::test_tail_whole_journal_delivers_a_new_line_promptly`
  — it injects a marker via `logger` and requires prompt delivery; don't
  rely on ambient journal traffic to "prove" this works, that's how the bug
  passed unnoticed the first time.

- **SSH commands are one shell string, not argv.** The SSH "exec" channel
  only ever transports a single command string that the remote shell
  interprets (`$SHELL -c "..."`) — unlike a local `subprocess`, there's no
  argv-array form. `providers/ssh.py` always builds that string with
  `shlex.quote()` on every interpolated value. Never f-string a raw path or
  unit name into an SSH command.

- **The browse endpoint must compute `parent` even when listing fails.**
  `api/routes/hosts.py`'s `/browse` had a real bug where a permission-denied
  directory came back with `parent: null`, disabling the file picker's "Up"
  button exactly when it was needed to back out. `parent` is derived from
  the *requested path*, independent of whether `list_directory()` succeeded
  — keep that ordering if you touch this endpoint.

- **journalctl's own access is silently restricted for non-privileged
  users.** A non-root user not in `systemd-journal`/`adm` only sees a
  fraction of the journal (mostly its own session activity) — no error, just
  quietly less data. `providers/journal.py`'s `journal_access_warning()` +
  the `warning` field on `ResolveResponse` surface this proactively; don't
  remove it thinking it's dead code just because journalctl itself doesn't
  complain.

- **The WebSocket subscribe handler needs a branch per "deterministic"
  mode.** `exact_path` and `journal` log sources always resolve to
  themselves (no client-side pattern-match round trip needed); `glob`/
  `regex` do not. `ws_logs.py`'s `handle_subscribe` has to special-case both
  — a past regression here was journal-mode subscribes rejected with
  "resolved_path is required for glob/regex log sources" because only
  `exact_path` had the special case.

- **Grep really is real `grep`.** `tailing/grep.py` whitelists flags, parses
  via `shlex.split`, and always runs the actual `grep` binary via
  `create_subprocess_exec` (argv list, no shell) — never reimplement this in
  Python; the point is real grep semantics.

## Testing

```bash
cd backend && source .venv/bin/activate  # or: uv venv / pip install -e ".[dev]"
python -m pytest
```

Several tests (`test_journal.py`, parts of `test_browse.py`) exercise the
real `journalctl`/filesystem-permission behavior of the host running the
tests rather than mocking it — they skip cleanly (`shutil.which(...)`) if
the binary isn't available, and a couple skip under a root shell where
permission bits can't produce a "denied" case. That's intentional: this
project has been repeatedly bitten by bugs that only reproduce against real
`grep`/`journalctl`/SSH behavior, not a mock of it.

## Deploying / redeploying

`docker compose up -d --build`. Two things that will silently look like data
loss if changed carelessly on a host with real data already stored:

- **`DB_PATH`** — changing it (or the compose volume name) points the app at
  an empty DB inside the same volume; the old file isn't deleted, just no
  longer used. Migrate explicitly (copy the old file to the new path/volume)
  before/after changing it, don't just redeploy and assume continuity.
- **`MASTER_KEY`** — losing or rotating it makes every stored SSH
  credential permanently undecryptable (by design, see README). Never
  regenerate it as a "fix" for anything; if it's genuinely lost, every host
  needs its password/key re-entered.

## Security model (short version — see README for the user-facing warning)

Login passwords: argon2id, one-way. Host SSH passwords/private keys:
AES-256-GCM, `MASTER_KEY` only ever in env (never in DB), decrypt-on-demand
when a tail session actually connects. `HostOut`/API responses only ever
expose `has_password`/`has_private_key` booleans — the API must never grow a
code path that serializes the decrypted secret or the raw encrypted bytes
back to a client. SSH host keys are trust-on-first-use, pinned per host in
`known_host_key`.
