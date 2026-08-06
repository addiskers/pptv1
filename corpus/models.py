"""Corpus inventory data models.

Boundary schemas for the deck-corpus ingest pipeline: ShapeStats is the
structural fingerprint of one slide (derived via python-pptx), SlideRecord
is one line of work/index.jsonl (one slide/page normalized to PNG), and
DeckManifestEntry is one line of work/manifest.jsonl used for resume.
Pydantic v2; validators cap free-text and edge-list fields so index
lines stay small.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ShapeStats(BaseModel):
    n_shapes: int
    n_textboxes: int
    n_pictures: int
    n_tables: int
    n_charts: int
    n_groups: int
    chart_xml_types: list[str]
    has_smartart: bool
    title_text: str = ""
    fonts: list[str] = Field(default_factory=list)
    all_text: str = ""
    # Distinct shape left/right (x) and top/bottom (y) edges in points,
    # snapped to a 0.05in grid; sorted, capped at 60 per axis.
    x_edges: list[int] = Field(default_factory=list)
    y_edges: list[int] = Field(default_factory=list)
    n_distinct_fills: int = 0
    # Naive sum(shape areas)/slide area clamped to 0..1; None for PDFs.
    covered_frac: float | None = None
    # Rendered PNG width/height; 4:3 vs 16:9 era signal. None for PDFs.
    aspect: float | None = None

    @field_validator("all_text", "title_text")
    @classmethod
    def _cap_all_text(cls, v: str) -> str:
        return v[:2000]

    @field_validator("fonts")
    @classmethod
    def _cap_fonts(cls, v: list[str]) -> list[str]:
        return v[:10]

    @field_validator("x_edges", "y_edges")
    @classmethod
    def _cap_edges(cls, v: list[int]) -> list[int]:
        return v[:60]


class SlideRecord(BaseModel):
    deck_id: str
    slide_id: str
    slide_index: int
    png_path: str
    source_type: Literal["pptx", "ppt", "pdf"]
    source_path: str
    extracted_text: str
    shape_stats: ShapeStats | None
    phash: str
    dup_of: str | None = None
    ingested_at: str


class DeckManifestEntry(BaseModel):
    deck_id: str
    source_path: str
    mtime: float
    size: int
    n_slides: int
    ok: bool
