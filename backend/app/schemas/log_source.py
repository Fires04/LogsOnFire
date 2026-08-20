from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

LogSourceMode = Literal["exact_path", "glob", "regex", "journal"]


class LogSourceCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    mode: LogSourceMode
    # For "journal" mode this holds a systemd unit name (e.g. "nginx.service"),
    # or "*" for the whole journal — not a filesystem path.
    path_or_pattern: str = Field(min_length=1, max_length=1000)
    regex_base_dir: str | None = None

    @model_validator(mode="after")
    def _validate_regex_base_dir(self) -> "LogSourceCreate":
        if self.mode == "regex" and not self.regex_base_dir:
            raise ValueError("regex_base_dir is required when mode is 'regex'")
        return self


class LogSourceUpdate(BaseModel):
    label: str | None = None
    mode: LogSourceMode | None = None
    path_or_pattern: str | None = None
    regex_base_dir: str | None = None


class LogSourceOut(BaseModel):
    id: str
    agent_id: str
    label: str
    mode: LogSourceMode
    path_or_pattern: str
    regex_base_dir: str | None

    model_config = {"from_attributes": True}


class ResolvedFileOut(BaseModel):
    path: str
    size: int | None = None
    mtime: float | None = None


class ResolveResponse(BaseModel):
    files: list[ResolvedFileOut]
    truncated: bool = False
    error: str | None = None
    # Non-fatal heads-up (e.g. journal mode + non-root user with limited
    # journal access) — the resolve still succeeded, but the result may be
    # incomplete for a reason the user can actually fix.
    warning: str | None = None
