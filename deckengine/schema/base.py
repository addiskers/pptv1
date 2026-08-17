"""Shared slide-spec mixins (kept import-cycle-free: both slide_types and
canvas need these)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SpeakerNotes(BaseModel):
    """Mixin: directive speaker notes on every archetype — what to SAY, what
    to point at, what not to read aloud. Written into the pptx notes page
    (notes pages are laid out by PowerPoint and exempt from the engine's
    measured-layout contract)."""
    notes: str | None = Field(default=None, max_length=350)

    @field_validator("notes", mode="before")
    @classmethod
    def _trim_notes(cls, v):
        """Overlong notes TRIM instead of failing validation: notes never
        touch the measured layout, so a chatty speaker note must not be
        able to kill an otherwise perfect slide in the repair loop."""
        if isinstance(v, str) and len(v) > 350:
            cut = v[:350]
            dot = cut.rfind(". ")
            return (cut[:dot + 1] if dot > 200 else cut).strip()
        return v
