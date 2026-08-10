from __future__ import annotations

from pydantic import BaseModel


class DirEntryOut(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    mtime: float | None = None
    permissions: str | None = None
    readable: bool | None = None


class BrowseResponse(BaseModel):
    path: str
    parent: str | None
    entries: list[DirEntryOut]
    truncated: bool = False
    error: str | None = None
