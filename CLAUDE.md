# CLAUDE.md

Guidance for Claude Code (or any AI assistant) working in this repository.
This file is for *maintainers/assistants*; `README.md` is for end users —
keep facts in the file that matches their audience, don't duplicate.

## What this is

Logs On Fire: a self-hosted log-tailing dashboard. A lightweight **agent**
process (`agent/`) runs on each monitored host, reads logs *locally*
(exact path / glob / regex / systemd journal — no remote credentials, no
inbound SSH) and pushes them to a central **server** (`backend/` +
`frontend/`) over a persistent WebSocket it opens itself. The server
provides live tail over WebSocket with a real-`grep`-based filter bar,
short in-memory history, and multi-log dashboards — see `README.md` for
the user-facing feature list and deployment instructions.

**Architecture note (2026-08-19 rewrite)**: this used to be a pull model —
the server SSH'd out to each host and ran `tail -F`/`journalctl -f`
remotely. That was replaced outright (hard cutover, no dual-mode period)
with the push model described above, because SSH credentials needing
just-enough remote read permissions, and the server needing inbound network
reachability to every host, were both recurring real operational problems.
Existing hosts/log sources from the old model do not carry over — every
host must be re-enrolled as an agent (`POST /api/agents`, one token per
host) and have its log sources reconfigured.

## Layout

```
backend/app/
  agents/       Agent Manager: registry.py (one live WS per connected agent
                + request/reply matching), heartbeat.py (ping/pong,
                connection-timeout detection), service.py (enroll,
                reissue-token, connect/disconnect lifecycle)
  tailing/      TailSession (ring buffer, now fed by pushed lines rather
                than a server-owned tail process), manager.py (dedup by
                agent_id+path, refcounted by browser subscriber count),
                broker.py (pub/sub fan-out), grep.py (sandboxed real-grep
                filter)
  security/     agent_tokens.py (HMAC-SHA256 hashed bearer tokens),
                passwords.py (argon2id for dashboard users), jwt.py,
                deps.py (cookie/CSRF wiring for the dashboard-user session)
  api/routes/   REST + two WebSocket endpoints: ws_logs.py (browser-facing,
                unchanged by the rewrite) and ws_agent.py (agent-facing,
                new)
agentcore/logsonfire_agentcore/
                Local log-reading logic (LogProvider ABC, LocalFileProvider,
                journal.py, glob/regex resolvers) — zero FastAPI/SQLAlchemy
                dependency, since this runs inside the agent process on a
                monitored host, not the server. This is where
                `providers/local.py` used to live when the server read
                files itself.
agent/logsonfire_agent/
                The standalone agent: wsclient.py (persistent reconnecting
                connection to /ws/agent, mirrors frontend/src/lib/
                wsClient.ts's backoff pattern), dispatch.py (resolve/browse/
                start_tail/stop_tail handlers, calls into agentcore),
                config.py (just server_url + token — log source
                configuration stays centralized on the server). Packaged
                separately (own pyproject.toml) so installing it on a
                monitored host doesn't pull in the backend's web/DB stack.
frontend/src/
  routes/       page-level components (one per route in App.tsx)
  components/   shared UI (LogPanel, FileExplorer, LogSourceViewer, ...)
  lib/          wsClient.ts (multiplexed reconnecting WS client, browser-
                facing — unaffected by the push-model rewrite), api.ts,
                logHighlight.tsx
```

**The core design rule worth preserving** now lives one layer down from
where it used to: `agentcore/logsonfire_agentcore/base.py`'s `LogProvider`
ABC is deliberately small (`resolve_sources`, `read_tail`, `tail`,
`list_directory`, `default_browse_path`) so a new log source type is a new
module in `agentcore/` + a small dispatch addition in `agent/dispatch.py`,
not changes scattered through the server's `api/`/`tailing/`. The server
itself never touches a monitored host's filesystem directly anymore — it
only ever asks the connected agent over `/ws/agent` and waits for a reply.

## Non-obvious gotchas (found by direct testing — don't "fix" these back)

- **`--loop asyncio` is required.** `app/entrypoint.py` explicitly avoids
  uvicorn's default `uvloop`: under uvloop, the SQLAlchemy async engine
  (bridging aiosqlite's worker thread back via `greenlet`) hangs completely
  on startup. Verified directly, not a hypothetical.

- **journalctl needs `stdbuf -oL`.** `journalctl --follow` fully
  block-buffers its own stdout whenever it isn't a tty (always true for a
  subprocess pipe) — without forcing line buffering, freshly-logged lines
  sit unflushed indefinitely instead of arriving live. This now only
  applies inside `agentcore/logsonfire_agentcore/local.py`'s local
  `journalctl -f` invocation (the agent's own host), not a remote one —
  there's no more SSH-side copy of this gotcha to keep in sync.
  Regression test: `agentcore/tests/test_journal.py::test_tail_whole_journal_delivers_a_new_line_promptly`
  — it injects a marker via `logger` and requires prompt delivery; don't
  rely on ambient journal traffic to "prove" this works, that's how the bug
  passed unnoticed the first time.

- **The browse handler must compute `parent` even when listing fails.**
  This used to be a real bug in the server's own `/browse` endpoint; now
  it's the *agent's* `dispatch.py::_handle_browse` that must compute
  `parent` unconditionally from the requested path, independent of whether
  `list_directory()` succeeded — a permission-denied directory coming back
  with `parent: null` disables the file picker's "Up" button exactly when
  it's needed to back out. Regression test:
  `backend/tests/test_browse.py::test_browse_endpoint_reports_parent_even_when_listing_fails`
  (via a fake agent — see below).

- **journalctl's own access is silently restricted for non-privileged
  users.** A non-root agent process not in `systemd-journal`/`adm` only
  sees a fraction of the journal (mostly its own session activity) — no
  error, just quietly less data. `agentcore/logsonfire_agentcore/journal.py`'s
  `journal_access_warning()` + the `warning` field on `ResolveResponse`
  surface this proactively; don't remove it thinking it's dead code just
  because journalctl itself doesn't complain. The install script
  (`agent/install.sh`) adds the agent's system user to `systemd-journal`/
  `adm` for exactly this reason.

- **The WebSocket subscribe handler needs a branch per "deterministic"
  mode.** `exact_path` and `journal` log sources always resolve to
  themselves (no client-side pattern-match round trip needed); `glob`/
  `regex` do not. `ws_logs.py`'s `handle_subscribe` has to special-case both
  — a past regression here was journal-mode subscribes rejected with
  "resolved_path is required for glob/regex log sources" because only
  `exact_path` had the special case. Unaffected by the push-model rewrite —
  this is entirely about the browser-facing protocol.

- **Grep really is real `grep`.** `tailing/grep.py` whitelists flags, parses
  via `shlex.split`, and always runs the actual `grep` binary via
  `create_subprocess_exec` (argv list, no shell) — never reimplement this in
  Python; the point is real grep semantics.

- **`AgentConnectionRegistry.request()` always has a timeout.** Every
  resolve/browse/start_tail call the server makes to an agent
  (`app/agents/registry.py`) must resolve to either a reply or a clean
  `AgentOfflineError`/`AgentTimeoutError` within
  `settings.agent_request_timeout_seconds` — never let a route handler
  `await` an agent reply with no timeout; an agent that silently stops
  responding (not fully disconnected, just stuck) must not hang the
  request forever.

- **Agent disconnect must sweep every session it owned.**
  `agents/service.py::mark_disconnected` walks
  `get_tail_manager().sessions_for_agent(agent_id)` and publishes
  `TailClosed("agent_disconnected")` on each — otherwise a browser tab
  watching a log on a host that just went offline would sit there showing
  a stale "live" status forever instead of a clear closed/disconnected
  state.

- **Version is derived from git, not hand-bumped — and the agent's version
  is tracked separately from the server's.** `Dockerfile`'s `gitinfo` stage
  computes `<major from the nearest "vN" tag>.<commits since that
  tag>+g<hash>` (e.g. tag `v1` + 7 commits = `1.7+ge1be41b`) — but it
  computes this **twice**, once counting every commit (`/version.txt`, the
  server's own version — `backend`'s `pyproject.toml`) and once counting
  only commits that touch `agent/`/`agentcore/` (`/agent_version.txt` —
  those two packages' `pyproject.toml`, plus dropped at
  `app/static/agent/VERSION` for the server to read back). Both files
  overwrite whatever's checked into those `pyproject.toml`s at build time,
  which is why their own `version` lines don't matter and don't need
  editing. **Don't merge these two counters back into one** — agent code
  changes far less often than the backend/frontend do, so a same-repo
  commit that only touches backend/frontend must not bump the agent's
  version and make every already-current agent look out of date
  (`app/core/version.py::get_expected_agent_version()` is what
  `api/routes/agents.py`'s mismatch check compares an agent's self-reported
  version against — never the server's own `get_server_version()`). The
  second number in each scheme auto-increments on every relevant commit; a
  major jump (`1.x` → `2.0`, shared by both counters since they read the
  same tag) is a **deliberate, manual** `git tag vN && git push origin vN`
  — nothing else triggers it. Tags are a single number (`v1`, `v2`, …), not
  `vX.Y` — the version format is two segments (`major.count`), not three.
  This exists because a hand-maintained semver number *not* changing between
  builds was a real bug once already: `pip install --upgrade` on a host
  that already had the exact same version string installed was a silent
  no-op even though the server's `/agent/*.whl` content had changed (a
  docker-mode log source resolved with "unknown log source mode: 'docker'"
  against a freshly-rebuilt server until the agent was reinstalled with
  `--force-reinstall`). With git-derived versions this can't happen again —
  every commit produces a genuinely different version, so a plain
  `pip install --upgrade` (what `agent/upgrade.sh` runs) is always correct.
  If a repo checkout somehow has zero tags, the scheme falls back to
  `0.<total commit count>` — don't let that happen; tag early.

- **Upgrading an already-installed agent: `agent/upgrade.sh`, not
  `install.sh` again.** It reads `server_url` out of the existing
  `/etc/logsonfire-agent/config.toml`, so it needs no token/name
  re-entry (unlike install.sh, which provisions identity) — just
  `curl -fsSL <server>/agent/upgrade.sh | sudo bash`.

- **The "docker" log source mode needs the agent's OS user in the `docker`
  group — opt-in, not automatic.** Unlike journal access,
  `usermod -aG docker` is roughly root-equivalent (anyone in that group can
  trivially root the host via a bind-mounted container), so
  `agent/install.sh` asks explicitly (or reads
  `LOGSONFIRE_INSTALL_ENABLE_DOCKER=yes|no` for non-interactive installs) —
  never add it unconditionally the way journal/adm group membership is.

- **Remote "update now" (the Agents page's trigger-update button) doesn't
  retroactively apply to already-installed agents.** It works by having
  the agent (running as the unprivileged `logsonfire-agent` user, which
  can neither `pip install` into system site-packages nor restart its own
  systemd unit) invoke a fixed, root-owned wrapper script
  (`/usr/local/bin/logsonfire-agent-self-update`) via a narrowly-scoped
  `sudoers.d` NOPASSWD rule naming that exact path — both written by
  `install.sh`. A host enrolled before this feature existed has neither
  file; `agent/dispatch.py::_handle_self_update` checks for the wrapper
  script first and replies with a clear "re-run install.sh" error rather
  than a confusing sudo permission failure, but the fix genuinely is a
  one-time `install.sh` re-run (safe — it's idempotent, see the
  `enable`+`restart` gotcha above), not something the update mechanism can
  bootstrap itself out of. This is real remote-code-execution surface by
  design (that's the whole point — install.sh itself requires the same
  root trust over SSH), scoped as tightly as the feature allows: one fixed
  command, no arguments, not a blanket sudo grant.

## Testing

Three independent test suites, one per package (they don't share a venv —
`agentcore`/`agent` deliberately have no dependency on `backend`):

```bash
cd backend && source .venv/bin/activate && python -m pytest
cd agentcore && source .venv/bin/activate && python -m pytest
```

`backend/tests/fake_agent.py` provides an in-process fake agent
(`attach_fake_agent(agent_id, handler)`) used by most REST/tailing-layer
tests to exercise the resolve/browse/start_tail request-reply flow without
a real network WebSocket — safe to call directly from an async test since
it runs on the same event loop as the app under test (httpx's
`ASGITransport`). `backend/tests/test_ws_agent.py` and
`test_ws_logs.py` instead drive a real WebSocket via Starlette's
*synchronous* `TestClient` (httpx's async client has no WS support) — that
runs the app in a background thread with its own event loop, so anything
that touches `asyncio.Queue`/`Future` objects owned by that loop (like
`TailSession.receive_line`) must be scheduled *from a callback already
running on that loop* (e.g. `asyncio.get_running_loop().call_later(...)`
inside a fake-agent message handler), never called directly from the
test's own thread — that's an unsafe cross-thread asyncio access, not just
a style preference; it caused real intermittent failures during
development (see `test_ws_logs.py`'s `handler()` closures for the pattern).

Several tests (`agentcore/tests/test_journal.py`, parts of
`agentcore/tests/test_local_provider.py`) exercise the real
`journalctl`/filesystem-permission behavior of the host running the tests
rather than mocking it — they skip cleanly (`shutil.which(...)`) if the
binary isn't available, and a couple skip under a root shell where
permission bits can't produce a "denied" case. That's intentional: this
project has been repeatedly bitten by bugs that only reproduce against real
`grep`/`journalctl` behavior, not a mock of it.

## Deploying / redeploying

`docker compose up -d --build`. Two things that will silently look like data
loss if changed carelessly on a host with real data already stored:

- **`DB_PATH`** — changing it (or the compose volume name) points the app at
  an empty DB inside the same volume; the old file isn't deleted, just no
  longer used. Migrate explicitly (copy the old file to the new path/volume)
  before/after changing it, don't just redeploy and assume continuity.
- **`AGENT_TOKEN_PEPPER`** — losing or rotating it invalidates every
  agent's stored token hash (they'll fail to authenticate). Unlike the old
  `MASTER_KEY`, this is **not** catastrophic: reissue each agent's token
  (`POST /api/agents/{id}/reissue-token`) and update its config — no log
  data or log-source configuration is lost, since tokens are hashed
  one-way and never used to decrypt anything.

Every monitored host additionally needs the agent installed
(`agent/install.sh`, or `pip install` the `logsonfire-agent` +
`logsonfire-agentcore` wheels + the provided systemd unit) and enrolled via
the dashboard's Agents page before it can be configured with log sources.

## Security model (short version — see README for the user-facing warning)

Login passwords: argon2id, one-way (`security/passwords.py`). Agent bearer
tokens: HMAC-SHA256 hashed at rest with `AGENT_TOKEN_PEPPER`
(`security/agent_tokens.py`) — **not** reversibly encrypted, since a token
is a bearer secret the server never needs to present to a third party
(unlike the old SSH credentials, which had to be decrypted and handed to
`asyncssh.connect()`). A token is shown in plaintext exactly once, at
enrollment or reissue, and never stored or logged in plaintext anywhere.
`AgentOut`/API responses only ever expose `token_prefix` (not secret, just
enough to tell tokens apart in the UI) — the API must never grow a code
path that serializes a token hash or a way to recover the plaintext back to
a client. There is no SSH layer, no remote credentials, and no host-key
trust-on-first-use anymore — the agent only ever reads its own host's
filesystem/journal locally, and only initiates the one outbound connection
to the server.
