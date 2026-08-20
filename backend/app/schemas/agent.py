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
    token_prefix: str

    model_config = {"from_attributes": True}


class AgentCreateResult(BaseModel):
    """Returned only from enrollment/reissue — the plaintext token is shown
    exactly once here and never again."""
    agent: AgentOut
    token: str
