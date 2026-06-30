from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChordRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_level: str
    ann_level: str
    selected_ann_cat: Any = Field(default_factory=dict)
    selected_taxon: Any = Field(default_factory=dict)


class OverviewVector(BaseModel):
    index: list[str]
    counts: list[float]


class OverviewResponse(BaseModel):
    counts_data: OverviewVector
    ann_data: OverviewVector


class OverviewRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
