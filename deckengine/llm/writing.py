"""Deterministic writing-craft lint (Q4) — the machine-prose detector.

Free checks that run before any LLM repair, mirroring check_outline's role:
the four written tells reviewers call out are hedged claims, the
italics-everywhere habit, connective-chain openers, and exclamation marks.
Problems feed the existing stage-2 repair loop as plain sentences.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from ..schema.rich import plain

# hedges kill assertion-evidence writing; a claim is stated or cut
_HEDGES = ("may", "might", "could", "potentially", "possibly", "perhaps",
           "arguably", "somewhat", "seems", "appears")
_HEDGE_RE = re.compile(r"\b(" + "|".join(_HEDGES) + r")\b", re.IGNORECASE)
_CONNECTIVE_RE = re.compile(
    r"^\s*(Additionally|Furthermore|Moreover|It is important to note)\b")
# single-star italic runs only — **bold** must not match
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)")

_MAX_BODY_HEDGES = 2
_MAX_ITALIC_SPANS = 3
# under this many words, a dense body archetype reads as an empty slide
# (the winning deck averaged ~164 words/slide; sparse = machine tell)
_SPARSE_FLOOR = 60
_DENSE_BODY = frozenset({"bullet_content", "exec_summary",
                         "n_column_comparison", "framework_slide"})

# non-prose fields: enums, roles, asset names, icon vocab, codes
_SKIP_KEYS = frozenset({
    "slide_type", "kind", "icon", "fill_role", "color_role", "size_role",
    "font_role", "align", "anchor", "header_fill_role", "cell_kind", "style",
    "chart_type", "sort", "fit", "src", "bg_image", "code", "date",
    "wordmark", "org", "value_suffix", "display", "target_display",
    "center_text", "number",
})


def _prose_strings(node, key: str | None = None) -> list[str]:
    if isinstance(node, dict):
        return [s for k, v in node.items() if k not in _SKIP_KEYS
                for s in _prose_strings(v, k)]
    if isinstance(node, list):
        return [s for v in node for s in _prose_strings(v, key)]
    if isinstance(node, str):
        return [node]
    return []


def check_slide_writing(slide: BaseModel) -> list[str]:
    """Machine-prose problems for one slide spec (deterministic, free)."""
    problems: list[str] = []
    title = plain(getattr(slide, "title", "") or "")
    if title:
        hedge = _HEDGE_RE.search(title)
        if hedge:
            problems.append(
                f"title hedges with {hedge.group(0)!r} — assert the claim "
                f"or cut it: {title!r}")

    texts = _prose_strings(slide.model_dump())
    joined = "\n".join(texts)

    body_hedges = _HEDGE_RE.findall(joined)
    if len(body_hedges) > _MAX_BODY_HEDGES:
        problems.append(
            f"{len(body_hedges)} hedge words on one slide "
            f"({', '.join(sorted(set(h.lower() for h in body_hedges)))}) — "
            "state each point as evidence or remove it")

    italics = _ITALIC_RE.findall(joined)
    if len(italics) > _MAX_ITALIC_SPANS:
        problems.append(
            f"{len(italics)} italic spans — the italics-everywhere tell; "
            "keep *italics* for defined terms only (max "
            f"{_MAX_ITALIC_SPANS})")

    for t in texts:
        m = _CONNECTIVE_RE.match(plain(t))
        if m:
            problems.append(
                f"line opens with {m.group(1)!r} — connective-chain filler; "
                "lead with the point itself")
            break  # one report covers the habit

    if "!" in joined:
        problems.append("exclamation mark — consulting prose never exclaims")

    if getattr(slide, "slide_type", "") in _DENSE_BODY:
        words = len(plain(joined).split())
        if words < _SPARSE_FLOOR:
            problems.append(
                f"only {words} words on a dense body slide — a sparse slide "
                "reads as an empty argument; add evidence FROM THE FACTS "
                "block (or marked real figures), never filler")
    return problems
