"""One-time install links: `agent/install.sh` normally needs `--server`/
`--token` as CLI arguments, which land in the operator's shell history and
are briefly visible to other local users via `ps` while the command runs.
An install link sidesteps that — the browser hands the server the
already-copied plaintext token (the server itself never persists it, only
its hash) plus the server_url it should embed, gets back a short random
single-use code, and the resulting `curl .../agent/install/<code> | sudo
bash` needs no arguments at all: the download endpoint bakes --server/
--token into the script it returns, then the code is immediately
invalidated. Only that meaningless one-time code — not the real bearer
token — ever touches shell history.

Deliberately in-memory, not a DB table: this is a short-lived (default
15 min), single-use operational convenience, not a credential — a server
restart invalidating pending links just means "generate a new one",
same as it would for a password-reset link.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

LINK_TTL_SECONDS = 15 * 60


@dataclass
class InstallLink:
    agent_id: str
    token: str
    server_url: str
    expires_at: float


class InstallLinkStore:
    def __init__(self) -> None:
        self._links: dict[str, InstallLink] = {}

    def create(self, agent_id: str, token: str, server_url: str) -> str:
        self._sweep_expired()
        code = secrets.token_urlsafe(24)
        self._links[code] = InstallLink(agent_id, token, server_url, time.monotonic() + LINK_TTL_SECONDS)
        return code

    def consume(self, code: str) -> InstallLink | None:
        """Single-use: a valid link is removed the moment it's read,
        whether or not the caller goes on to actually use its contents."""
        link = self._links.pop(code, None)
        if link is None:
            return None
        if time.monotonic() > link.expires_at:
            return None
        return link

    def _sweep_expired(self) -> None:
        now = time.monotonic()
        expired = [code for code, link in self._links.items() if now > link.expires_at]
        for code in expired:
            self._links.pop(code, None)


_store: InstallLinkStore | None = None


def get_install_link_store() -> InstallLinkStore:
    global _store
    if _store is None:
        _store = InstallLinkStore()
    return _store


def reset_install_link_store_for_tests() -> None:
    global _store
    _store = None
