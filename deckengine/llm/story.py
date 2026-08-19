"""Story engine (lite): pyramid-principle outlines + the so-what validator.

Per the design review: structure over evaluation. The outline is a CLAIM CHAIN
(governing thought + one claim per slide) that a human can approve in 30
seconds — the title chain read in sequence IS the horizontal-logic check.
Slide titles derive from approved claims; a single holistic review pass
tightens the chain; a deterministic validator kills label-titles for free.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from ..schema.rich import plain

# -- outline schema ---------------------------------------------------------


class OutlineSlide(BaseModel):
    slide_type: str
    claim: str = Field(
        max_length=220,
        description="The one-sentence assertion this slide proves. Becomes the "
                    "slide title. Never a label like 'Market Overview'.")
    section: str | None = Field(
        default=None, max_length=40,
        description="2-4 word section tag (e.g. 'THE OPPORTUNITY'), constant "
                    "across consecutive slides of one act, changing at "
                    "dividers. Rendered as the small-caps kicker above each "
                    "title. Null on title/divider slides.")
    visual_concept: str | None = Field(
        default=None, max_length=120,
        description="One sentence naming the slide's visual composition — "
                    "the form AND the arrangement (e.g. 'dark hero panel "
                    "left with oversized stat, proof chart right, three "
                    "chips below'). Vary it slide to slide; null on "
                    "title/divider slides.")
    decision_type: str | None = Field(
        default=None, max_length=30,
        description="The DECISION this slide's SECTION drives, one id from "
                    "the decision vocabulary in the prompt — constant "
                    "across a section's slides like the section tag; "
                    "'none' when the section merely informs; null on "
                    "title/divider slides.")
    framework: str | None = Field(
        default=None, max_length=40,
        description="Leave null — assigned by the engine after the "
                    "outline, never by the model.")

    @field_validator("decision_type", mode="before")
    @classmethod
    def _norm_decision(cls, v):
        """Advisory: normalize; unknown ids coerce to None, never fail
        (stage 1 has no repair loop — the trim-never-fail doctrine)."""
        if isinstance(v, str):
            from .frameworks import DECISION_TYPE_IDS
            v = v.strip().lower().replace(" ", "_").replace("-", "_")[:30]
            return v if v in DECISION_TYPE_IDS else None
        return v

    @field_validator("framework", mode="before")
    @classmethod
    def _norm_framework(cls, v):
        """Engine-assigned ids survive the approve-gate round trip;
        anything else (model hallucination) coerces to None."""
        if isinstance(v, str):
            from .frameworks import FRAMEWORKS
            v = v.strip().lower().replace(" ", "_").replace("-", "_")[:40]
            return v if v in FRAMEWORKS else None
        return v

    @field_validator("section", "visual_concept", "claim", mode="before")
    @classmethod
    def _trim_advisory(cls, v, info):
        """Prompt-side fields TRIM instead of failing: an overlong sentence
        must never kill the whole outline (there is no repair loop around
        stage 1's validation — seen live twice: visual_concept, then a
        forced-flow claim chain with long claims killed 2 batch variants)."""
        cap = {"section": 40, "visual_concept": 120, "claim": 220}[
            info.field_name]
        if isinstance(v, str) and len(v) > cap:
            cut = v[:cap]
            sp = cut.rfind(" ")
            return (cut[:sp] if sp > cap // 2 else cut).strip()
        return v


class Outline(BaseModel):
    governing_thought: str = Field(
        max_length=300,
        description="The deck's single-sentence answer — what the audience "
                    "should believe after the last slide.")
    narrative_arc: str | None = Field(
        default=None, max_length=40,
        description="The deck FLOW this outline follows, chosen by the "
                    "audience's meta-question (one id from the flow menu, "
                    "e.g. 'options_decision', 'scqa', 'diagnostic').")
    slides: list[OutlineSlide] = Field(min_length=2, max_length=30)

    @field_validator("narrative_arc", mode="before")
    @classmethod
    def _norm_arc(cls, v):
        """Advisory: normalize and trim; never fail the outline over it."""
        if isinstance(v, str):
            return v.strip().lower().replace(" ", "_").replace("-", "_")[:40]
        return v

    @field_validator("governing_thought", mode="before")
    @classmethod
    def _trim_governing(cls, v):
        """Trim, never fail: an eloquent-but-overlong governing thought
        killed 2 of 5 batch variants live (stage 1 has no repair loop)."""
        if isinstance(v, str) and len(v) > 300:
            cut = v[:300]
            sp = cut.rfind(" ")
            return (cut[:sp] if sp > 150 else cut).strip()
        return v


REVIEW_PROMPT = """You are a partner reviewing a deck outline before any slide is written.
The governing thought and the claim chain are below. Read ONLY the claims in sequence — they must form a complete, non-repeating argument that proves the governing thought (pyramid principle: horizontal logic).

Fix what fails:
- claims that are labels, not assertions
- claims that repeat or heavily overlap an earlier claim (merge or replace)
- gaps where a listener would ask "wait, why?" between adjacent claims
- a governing thought the chain does not actually prove

Keep slide count within +/-1 of the input. Keep slide_type values unchanged unless a claim clearly belongs to a different type. Return the REVISED outline."""

# -- so-what validator (deterministic, free) --------------------------------

_VERB_HINTS = {
    "is", "are", "was", "were", "has", "have", "will", "can", "must", "should",
    "grew", "grows", "growing", "leads", "lead", "led", "drives", "drive",
    "drove", "shows", "show", "showed", "offers", "offer", "offered", "makes",
    "make", "made", "remains", "remain", "delivers", "deliver", "delivered",
    "reduces", "reduce", "reduced", "increases", "increase", "increased",
    "outperforms", "outperform", "requires", "require", "required", "signals",
    "signal", "suggests", "suggest", "creates", "create", "created", "lifts",
    "lifted", "cut", "cuts", "beats", "beat", "dominates", "dominate", "wins",
    "win", "won", "spans", "span", "concentrates", "concentrate", "favors",
    "favor", "supports", "support", "unlocks", "unlock", "positions",
    "position", "accelerates", "accelerate", "exceeds", "exceed", "trails",
    "trail", "lags", "lag", "resulted", "benefitted", "benefited", "reached",
    "rolls", "takes", "take", "took", "sits", "sit", "clusters", "cluster",
}

# archetypes whose titles are legitimately labels
TITLE_EXEMPT = {"title", "section_divider"}

# >_MAX_RUN consecutive slides of one archetype reads machine-stamped — the
# title-subtitle-3-bullets rhythm reviewers call out instantly
_MAX_RUN = 2


def title_is_takeaway(title: str) -> bool:
    """True if the title reads as a claim (verb, number, or full sentence) —
    not a label like 'Market Overview' or 'Results'."""
    text = plain(title).strip()
    if re.search(r"\d", text):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if len(words) >= 10:
        return True
    lower = {w.lower() for w in words}
    return bool(lower & _VERB_HINTS)


def check_outline(outline: Outline) -> list[str]:
    """Deterministic outline problems (free, run before any LLM review)."""
    problems = []
    seen: list[str] = []
    for i, s in enumerate(outline.slides):
        if s.slide_type in TITLE_EXEMPT:
            continue
        if not title_is_takeaway(s.claim):
            problems.append(
                f"slide {i + 1} ({s.slide_type}): claim is a label, not an "
                f"assertion: {s.claim!r}")
        for j, prev in enumerate(seen):
            overlap = _word_overlap(s.claim, prev)
            if overlap > 0.75:
                problems.append(
                    f"slide {i + 1} heavily overlaps slide {j + 1} "
                    f"({overlap:.0%} shared words)")
        seen.append(s.claim)
    problems.extend(_archetype_monotony(outline))
    return problems


def _archetype_monotony(outline: Outline) -> list[str]:
    """Anti-generic rule: flag runs of >_MAX_RUN consecutive same-archetype
    slides so the review pass varies the structure."""
    problems = []
    run_start = 0
    types = [s.slide_type for s in outline.slides]
    for i in range(1, len(types) + 1):
        if i == len(types) or types[i] != types[run_start]:
            run_len = i - run_start
            if run_len > _MAX_RUN and types[run_start] not in TITLE_EXEMPT:
                problems.append(
                    f"slides {run_start + 1}-{i} are {run_len} consecutive "
                    f"'{types[run_start]}' slides — vary the archetype "
                    "(chart_slide, n_column_comparison, framework_slide, "
                    "kpi_dashboard...) or merge slides")
            run_start = i
    return problems


def _word_overlap(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-z]+", a.lower())) - {"the", "a", "an", "of", "in",
                                                  "and", "to", "with", "for"}
    wb = set(re.findall(r"[a-z]+", b.lower())) - {"the", "a", "an", "of", "in",
                                                  "and", "to", "with", "for"}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))
