from __future__ import annotations

from pydantic import BaseModel, Field


class SavedFilterCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    expression: str = Field(min_length=1, max_length=500)


class SavedFilterOut(BaseModel):
    id: str
    label: str
    expression: str

    model_config = {"from_attributes": True}
