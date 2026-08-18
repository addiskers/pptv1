"""Dynamic intake questions — a tiny structured pre-pass that asks the
handful of clarifying questions THIS brief actually needs before any
slide (or even the outline) is written. Never a fixed form: a market-entry
brief and a quarterly review get different questions. Best-effort and
always skippable — a failure here must never block generation.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

_MAX_QUESTIONS = 5


class IntakeQuestion(BaseModel):
    id: str = Field(max_length=40, description=(
        "short slug, e.g. 'audience', 'decision', 'tone', 'scope'"))
    question: str = Field(max_length=140)
    kind: Literal["choice", "short_text"] = "short_text"
    options: list[str] | None = Field(
        default=None, max_length=5, description=(
            "2-5 short options when kind='choice'; null for short_text"))
    placeholder: str | None = Field(
        default=None, max_length=80, description=(
            "an example answer shown as placeholder text; null for choice"))


class IntakeQuestions(BaseModel):
    questions: list[IntakeQuestion] = Field(
        default_factory=list, max_length=_MAX_QUESTIONS, description=(
            "0-5 questions; fewer (or none) when the brief already answers "
            "them itself — never pad with generic filler"))


def intake_prompt(prompt: str, has_csv: bool) -> str:
    return (
        "You are a consulting analyst about to build a deck. Before "
        "writing anything, decide what you'd actually ask the "
        "stakeholder who requested it — but ONLY if the brief below "
        "doesn't already answer it.\n\n"
        f"THE BRIEF:\n{prompt}\n\n"
        + ("A dataset (CSV) is attached — do not ask about data "
           "availability.\n\n" if has_csv else "")
        + "Ask up to 5 questions that would MEASURABLY change what gets "
        "written — never generic filler. Good candidates: who the "
        "reader is and what they already know, the decision or action "
        "this deck must drive, tone (a single firm recommendation vs "
        "balanced options), scope boundaries (geography, segment, "
        "timeframe), and any known constraint or claim to avoid. Skip "
        "any question the brief already answers. If the brief is "
        "already complete, return zero questions — that is a valid "
        "answer.\n\n"
        "For each question: kind='choice' with 2-5 short options when "
        "the answer is naturally a pick from a small set (e.g. tone, "
        "audience seniority); kind='short_text' with a realistic "
        "one-line placeholder example otherwise. Keep every question "
        "under 140 characters and answerable in ten seconds.")
