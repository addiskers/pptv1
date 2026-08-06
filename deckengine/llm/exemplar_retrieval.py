"""Tag-based best-match exemplar retrieval for stage-2 few-shots.

spec_generator._few_shot used to pick each archetype's exemplars by a fixed
rule: the hand-authored {archetype}.json + {archetype}_2.json, plus the
LATEST won/{archetype}_*.json by mtime. That ignored (a) the claim the slide
actually makes and (b) every induced big-firm exemplar corpus/induce.py
applies at {archetype}_3.json and beyond. This module replaces the
compounding-winner slot with a deterministic best-MATCH pick over the whole
exemplar pool, so the exemplar riding in the prompt is the one whose
claim_context / chart / craft (and, for induced ones, firm_style + quality)
fit this slide.

Each exemplar's tags are DERIVED from its DeckEngine spec — slide_type, any
embedded chart_type, and component `kind`s mapped to craft tags — so no side
file is required for the spec-visible signals. An optional overlay
(few_shots/exemplars_index.json, keyed by filename) carries the corpus-mined
firm_style / anchor / det_score that a spec alone cannot express; induction
writes it when it applies a big-firm exemplar.

route_context is reused from style_priors so the claim->context lexicon is
single-sourced. Kill-switch: DECKENGINE_EXEMPLAR_RETRIEVAL=0 -> empty result,
caller keeps its mtime fallback. Any missing/garbage file degrades to "no
match" — retrieval is a hint, never a dependency (mirrors style_priors.py).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .style_priors import route_context

log = logging.getLogger("deckengine")

OVERLAY_NAME = "exemplars_index.json"

# a spec component's `kind` -> the corpus craft tag it embodies (names match
# corpus/classify.py CRAFT_VOCAB so overlay + derived tags stay comparable)
_KIND_TO_CRAFT = {
    "chevron_pathway": "chevron",
    "numbered_block": "numbered_steps",
    "timeline_row": "timeline_bar",
    "kpi_card_strip": "kpi_cards",
    "arrow_callout": "arrow_callout",
    "brace_group": "brace",
    "funnel": "funnel",
    "harvey_balls": "harvey_balls",
    "matrix_2x2": "framework_2x2",
    "icon_stat_row": "icon_rail",
    "icon_tile_row": "icon_rail",
    "callout_band": "so_what_band",
    "legend_row": "legend_chips",
    "donut_stat": "big_number",
}

# corpus/classify.py anchors are great/mediocre/bad; poor/good tolerated as
# hand-edit aliases (same set as corpus/patterns.py ANCHOR_RANK).
_ANCHOR_RANK = {"bad": 0, "poor": 0, "mediocre": 1, "good": 2, "great": 3}

# categorical matches dominate the score; quality (anchor + det_score) only
# breaks ties between equally-matched exemplars.
W_CONTEXT = 3.0
W_CHART = 2.0
W_FIRM = 1.0


@dataclass(frozen=True)
class ExemplarTags:
    archetype: str
    claim_context: str | None = None
    chart_type: str | None = None
    craft: frozenset[str] = frozenset()
    firm_style: str | None = None
    anchor: str | None = None
    det_score: float = 0.0


@dataclass(frozen=True)
class Exemplar:
    path: Path
    tags: ExemplarTags
    mtime: float = 0.0


@dataclass(frozen=True)
class Query:
    archetype: str
    claim_context: str | None = None
    chart_hint: str | None = None
    firm_hint: str | None = None


# --- tag derivation (pure) ----------------------------------------------------

def _walk_kinds(node, out: list[str]) -> None:
    if isinstance(node, dict):
        k = node.get("kind")
        if isinstance(k, str):
            out.append(k)
        for v in node.values():
            _walk_kinds(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_kinds(v, out)


def _find_chart_type(node) -> str | None:
    if isinstance(node, dict):
        ct = node.get("chart_type")
        if isinstance(ct, str):
            return ct
        for v in node.values():
            r = _find_chart_type(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_chart_type(v)
            if r:
                return r
    return None


def derive_tags(spec: dict, overlay: dict | None = None) -> ExemplarTags:
    """Tags for one exemplar spec. Spec-visible signals (archetype,
    chart_type, craft, claim_context from the title) are always computed;
    an overlay dict enriches with corpus-mined firm_style / anchor /
    det_score that the spec cannot express. Pure — no IO."""
    kinds: list[str] = []
    _walk_kinds(spec, kinds)
    craft = frozenset(_KIND_TO_CRAFT[k] for k in kinds if k in _KIND_TO_CRAFT)
    title = str(spec.get("title") or "")
    o = overlay or {}
    return ExemplarTags(
        archetype=str(spec.get("slide_type") or ""),
        claim_context=o.get("claim_context") or route_context(title),
        chart_type=o.get("chart_type") or _find_chart_type(spec),
        craft=craft,
        firm_style=o.get("firm_style"),
        anchor=o.get("anchor"),
        det_score=float(o.get("det_score") or 0.0),
    )


# --- scoring + ranking (pure) -------------------------------------------------

def score(query: Query, tags: ExemplarTags) -> float:
    """Weighted tag-match score. Categorical matches dominate; anchor +
    det_score add a small quality tie-break so equally-matched exemplars
    rank best-craft-first. Pure."""
    s = 0.0
    if query.claim_context and tags.claim_context == query.claim_context:
        s += W_CONTEXT
    if query.chart_hint and tags.chart_type == query.chart_hint:
        s += W_CHART
    if query.firm_hint and tags.firm_style == query.firm_hint:
        s += W_FIRM
    if tags.anchor:
        s += _ANCHOR_RANK.get(str(tags.anchor).lower(), 0) * 0.1
    s += tags.det_score * 0.001
    return s


def rank(query: Query, exemplars: list[Exemplar]) -> list[Exemplar]:
    """Best-first, fully deterministic. Ties break by det_score, then mtime
    (latest wins — reproduces the historical rule as the final fallback),
    then filename."""
    return sorted(
        exemplars,
        key=lambda e: (score(query, e.tags), e.tags.det_score, e.mtime,
                       e.path.name),
        reverse=True,
    )


# --- IO-facing helpers --------------------------------------------------------

def enabled() -> bool:
    return os.environ.get("DECKENGINE_EXEMPLAR_RETRIEVAL") != "0"


def _load_overlay(few_shots_dir: Path) -> dict:
    p = Path(few_shots_dir) / OVERLAY_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_spec(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def build_exemplars(paths: list[Path], few_shots_dir: Path) -> list[Exemplar]:
    """Load + tag each exemplar file, joining the overlay by filename.
    Unreadable/garbage files are skipped, not fatal."""
    overlay = _load_overlay(few_shots_dir)
    out: list[Exemplar] = []
    for p in paths:
        spec = _read_spec(p)
        if spec is None:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append(Exemplar(p, derive_tags(spec, overlay.get(p.name)), mtime))
    return out


def select_exemplars(archetype: str, claim: str, pool: list[Path],
                     few_shots_dir: Path, k: int,
                     chart_hint: str | None = None,
                     firm_hint: str | None = None) -> list[Path]:
    """Up to k best-matching exemplar paths for this slide, best-first.
    Returns [] when disabled or the pool yields nothing, so the caller can
    fall back to its own rule."""
    if k <= 0 or not enabled():
        return []
    exemplars = build_exemplars(pool, few_shots_dir)
    if not exemplars:
        return []
    q = Query(archetype, route_context(claim or ""), chart_hint, firm_hint)
    return [e.path for e in rank(q, exemplars)[:k]]
