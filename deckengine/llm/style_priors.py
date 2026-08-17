"""Engine-side loader for mined style priors (corpus/patterns.py).

load_priors() reads deckengine/llm/style_priors.json (the committed
artifact) and prior_block() turns one claim into a <=500-char prompt
block citing top-firm frequency stats for the claim's context, plus
one craft suggestion. Missing/invalid file, the DECKENGINE_STYLE_PRIORS=0
kill-switch, non-chart archetypes and unroutable claims all degrade to
"" — priors are a hint, never a dependency.

Design: import-light by intent (json/pathlib/re/functools + os for the
env kill-switch only) so the prompt path adds no heavy deps. Claim ->
context routing reuses the format_rules lexicon IDEA as a small local
regex map (nothing imported from it). The renderable whitelists mirror
corpus/patterns.py RENDERABLE_* — duplicated, not imported, because
corpus/ does not ship with the engine; only whitelisted names are ever
cited, so capability_gaps features can never leak into a prompt.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

PRIORS_PATH = Path(__file__).parent / "style_priors.json"
MAX_CHARS = 500  # ~120 tokens; unit-tested hard cap

_PRIOR_ARCHETYPES = {"chart_slide", "custom_layout", "kpi_dashboard",
                     "canvas"}

# waterfall + the four style knobs are now renderable (A+); corpus tag ->
# engine field: avg_or_target_line -> style.benchmark, cagr_arrow ->
# style.cagr_chip, forecast_dashed -> style.forecast_from.
_WL_CHARTS = {"bar", "stacked_bar", "line", "donut_pie", "waterfall"}
_WL_FEATURES = {"value_labels", "sorted_desc", "series_highlight",
                "annotations", "endpoint_labels", "forecast_dashed",
                "avg_or_target_line", "cagr_arrow"}
_WL_CRAFT = {"so_what_band", "brace", "arrow_callout", "icon_rail",
             "kpi_cards", "framework_2x2", "funnel", "harvey_balls",
             "heatmap_cells", "big_number", "chevron", "timeline_bar",
             "numbered_steps", "watermark_image", "legend_chips"}

# Ordered specific-first; the first pattern that fires wins.
_CONTEXTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("process_roadmap", re.compile(
        r"\b(?:roadmaps?|timelines?|milestones?|phases?|rollout"
        r"|sequenc\w*|playbook|steps?|how\s+we)\b|\bby\s+q[1-4]\b", re.I)),
    ("benchmark", re.compile(
        r"\b(?:benchmark\w*|peers?|median|percentile|index(?:ed)?"
        r"|vs\.?\s+industry)\b", re.I)),
    ("share_mix", re.compile(
        r"\b(?:share|mix|split|composition|breakdown|accounts?\s+for)\b",
        re.I)),
    ("trend_forecast", re.compile(
        r"\b(?:forecasts?|project(?:ed|ions?)|outlook|trajectory|cagr"
        r"|by\s+20\d{2}|through\s+20\d{2})\b", re.I)),
    ("growth", re.compile(
        r"\b(?:grew|grow(?:s|ing|th)|rose|fell|declin\w*|doubl(?:ed|ing)"
        r"|tripl(?:ed|ing)|expand\w*|surg\w*)\b", re.I)),
    ("ranking_comparison", re.compile(
        r"\b(?:leads?|leaders?|largest|top|ranks?|outperforms?"
        r"|ahead\s+of|biggest|lags?|number\s+one|dominates?)\b|#\d",
        re.I)),
)


@lru_cache(maxsize=1)
def load_priors() -> dict:
    """Parsed priors, {} on any failure. Cached: the file is a build
    artifact that never changes mid-process (tests cache_clear())."""
    if os.environ.get("DECKENGINE_STYLE_PRIORS") == "0":
        return {}
    try:
        data = json.loads(PRIORS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def route_context(claim: str) -> str | None:
    text = claim or ""
    for name, pattern in _CONTEXTS:
        if pattern.search(text):
            return name
    return None


def _pct(v: float) -> str:
    return f"{v:.0%}"


def _top(freqs, whitelist: set[str], k: int) -> list[tuple[str, float]]:
    if not isinstance(freqs, dict):
        return []
    items = [(name, float(v)) for name, v in freqs.items()
             if name in whitelist and isinstance(v, (int, float)) and v > 0]
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    return items[:k]


def _designer_block(priors: dict) -> str:
    """Census-derived design-language lines for canvas slides (form
    frequencies from the 300-deck census; empty until a census ran)."""
    lines = (priors.get("designer") or {}).get("lines") or []
    lines = [str(x) for x in lines[:4]]
    if not lines:
        return ""
    body = ("DESIGN LANGUAGE (from a census of 350 top-firm slides):\n"
            + "\n".join(f"- {x}" for x in lines))
    return body[:MAX_CHARS + 200]


def prior_block(archetype: str, claim: str) -> str:
    # env checked here too so a warm load_priors cache cannot defeat
    # the kill-switch
    if os.environ.get("DECKENGINE_STYLE_PRIORS") == "0":
        return ""
    if archetype not in _PRIOR_ARCHETYPES:
        return ""
    priors = load_priors()
    if not priors:
        return ""
    designer = _designer_block(priors) if archetype == "canvas" else ""
    context = route_context(claim)
    if context is None:
        return designer
    bucket = (priors.get("by_claim_context") or {}).get(context)
    if not isinstance(bucket, dict):
        return ""
    stats: list[str] = []
    for name, f in _top(bucket.get("chart_type_freq"), _WL_CHARTS, 1):
        stats.append(f"{name} charts {_pct(f)} of the time")
    for name, f in _top(bucket.get("top_features"), _WL_FEATURES, 2):
        stats.append(f"{name} on {_pct(f)} of slides")
    craft = _top(bucket.get("craft_freq"), _WL_CRAFT, 1)
    if not craft:
        craft = _top((priors.get("global") or {}).get("craft_freq"),
                     _WL_CRAFT, 1)
    for name, f in craft[:1]:
        stats.append(f"consider a {name} ({_pct(f)} of top slides)")
    if len(stats) < 2:  # a lone stat is noise, not a prior
        return designer
    head = ("STYLE PRIORS (top-firm frequency data - follow unless the "
            f"claim argues otherwise): for {context} claims - ")
    body = head + "; ".join(stats) + "."
    while len(body) > MAX_CHARS and len(stats) > 2:
        stats.pop()
        body = head + "; ".join(stats) + "."
    body = body[:MAX_CHARS]
    return (designer + "\n\n" + body) if designer else body
