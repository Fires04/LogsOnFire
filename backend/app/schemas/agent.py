from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class AgentUpdate(BaseModel):
    name: str | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    online: bool
    last_seen_at: datetime | None
    last_heartbeat_rtt_ms: int | None
    agent_version: str | None
    # True when agent_version is known and differs from the server's own
    # version — a real, previously-hit gotcha (see CLAUDE.md): an agent
    # doesn't pick up new code on its own, and `pip install --upgrade`
    # silently no-ops if the wheel's version string didn't change, so this
    # is worth surfacing rather than leaving it to be discovered as
    # "some feature mysteriously doesn't work on this one host". False
    # (not True) when agent_version is None — an agent that's never
    # connected is "unknown", not "outdated".
    server_version_mismatch: bool
    token_prefix: str

    model_config = {"from_attributes": True}


class AgentCreateResult(BaseModel):
    """Returned only from enrollment/reissue — the plaintext token is shown
    exactly once here and never again."""
    agent: AgentOut
    token: str


class InstallLinkCreate(BaseModel):
    """The browser already holds the plaintext token (from AgentCreateResult
    — the server never persists it) and knows its own server_url (derived
    from window.location) — both are handed back here purely to generate a
    one-time download link, never stored beyond the link's short TTL."""
    token: str = Field(min_length=1)
    server_url: str = Field(min_length=1)

    @property
    def is_valid_scheme(self) -> bool:
        return self.server_url.startswith("ws://") or self.server_url.startswith("wss://")


class InstallLinkOut(BaseModel):
    code: str
    expires_in_seconds: int
