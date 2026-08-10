from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardPanelCreate(BaseModel):
    log_source_id: str
    resolved_path: str | None = None
    position_x: int = 0
    position_y: int = 0
    width: int = 6
    height: int = 4
    display_order: int = 0


class DashboardPanelOut(BaseModel):
    id: str
    log_source_id: str
    resolved_path: str | None
    position_x: int
    position_y: int
    width: int
    height: int
    display_order: int

    model_config = {"from_attributes": True}


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    panels: list[DashboardPanelCreate] = []


class DashboardUpdate(BaseModel):
    name: str | None = None
    panels: list[DashboardPanelCreate] | None = None


class DashboardOut(BaseModel):
    id: str
    name: str
    owner_id: str | None
    panels: list[DashboardPanelOut]

    model_config = {"from_attributes": True}
