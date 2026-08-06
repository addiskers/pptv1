"""Aggregate mined slide classifications into committed style priors.

CLI:  python corpus/patterns.py [--work DIR]
                                [--out deckengine/llm/style_priors.json]
                                [--own-glob GLOB]
                                [--min-quality-anchor great]
                                [--min-support 25]

Joins work/classified.jsonl (SlideClassification) with
work/scores.jsonl (DetScore) and work/index.jsonl (provenance:
deck_id + source_path), keeps only the high-quality set (anchor at or
above --min-quality-anchor AND confidence >= 0.7 AND det score >= 60),
weights it (own decks x2, max 40 slides per deck, no firm_style over
50% of total weight) and writes the versioned priors JSON consumed by
deckengine/llm/style_priors.py.

Only features/craft/chart types in the RENDERABLE whitelist appear in
the frequency buckets and the judge checklist; everything else the top
firms do that we cannot draw yet lands in capability_gaps. Frequencies
are weight shares; bucket support `n` is the raw slide count and any
keyed bucket with n < --min-support is dropped entirely.

Design: classification rows are read as plain dicts (tolerant of the
classifier schema growing) through accessors that understand the REAL
SlideClassification dump shape — nested `chart` (boolean feature flags,
int annotations) and `layout` objects plus `craft_elements` — with flat
chart_type/features/craft keys as a legacy fallback; all aggregation is
pure, only run_patterns touches the filesystem. The firm cap is applied globally (one rescale
of the over-represented firm's weights), a documented approximation of
the per-bucket cap.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# RENDERABLE WHITELIST — everything the engine can actually draw today.
# deckengine/llm/style_priors.py duplicates these sets (import-light on
# the engine side); keep the two in sync when a component ships.
RENDERABLE_CHARTS = {"bar", "stacked_bar", "line", "donut_pie", "waterfall"}
RENDERABLE_FEATURES = {"value_labels", "sorted_desc",
                       "series_highlight", "annotations",
                       "endpoint_labels", "forecast_dashed",
                       "avg_or_target_line", "cagr_arrow"}
RENDERABLE_CRAFT = {"so_what_band", "brace", "arrow_callout", "icon_rail",
                    "kpi_cards", "framework_2x2", "funnel", "harvey_balls",
                    "heatmap_cells", "big_number", "chevron",
                    "timeline_bar", "numbered_steps", "watermark_image",
                    "legend_chips"}

# corpus/classify.py anchors are great/mediocre/bad; poor/weak/good are
# tolerated aliases so a hand-edited corpus can still be mined.
ANCHOR_RANK = {"bad": 0, "poor": 0, "weak": 0, "mediocre": 1, "good": 2,
               "great": 3}
MIN_CONFIDENCE = 0.7
MIN_DET_SCORE = 60
DECK_CAP = 40           # slides any single deck may contribute
FIRM_SHARE_CAP = 0.5    # no firm_style over 50% of total weight
OWN_WEIGHT = 2.0
TOP_FEATURES_K = 8
CHECKLIST_MAX = 6
CHECKLIST_MIN_FREQ = 0.2

_CHECKLIST_HINTS = {
    "value_labels": "label every bar/point with its value",
    "sorted_desc": "sort ranking charts descending so order proves rank",
    "series_highlight": "highlight one series and mute the rest",
    "annotations": "annotate the chart with the takeaway",
    "so_what_band": "close with a so-what band stating the implication",
    "brace": "tie grouped items together with a brace",
    "arrow_callout": "call out the key delta with an arrow",
    "icon_rail": "run parallel points down an icon rail",
    "kpi_cards": "set headline numbers in KPI cards",
    "framework_2x2": "frame positioning claims as a 2x2",
    "funnel": "render conversion stories as a funnel",
    "harvey_balls": "score qualitative criteria with harvey balls",
    "heatmap_cells": "shade dense comparisons as heatmap cells",
    "big_number": "let one hero number dominate the slide",
    "chevron": "render process claims as chevron steps",
    "timeline_bar": "put dated plans on a timeline bar",
    "numbered_steps": "number sequential steps",
    "watermark_image": "anchor the theme with a watermark image",
    "legend_chips": "render legends as inline color chips",
}


# --- output schema (exact committed shape) ------------------------------------

class ChartVariant(BaseModel):
    n: int
    features: dict[str, float]


class ContextBucket(BaseModel):
    n: int
    chart_type_freq: dict[str, float]
    top_features: dict[str, float]
    craft_freq: dict[str, float]


class LayoutPattern(BaseModel):
    structure_freq: dict[str, float]
    has_bottom_band: float
    has_source_footer: float


class GlobalStats(BaseModel):
    density_mean: float
    title_is_action_rate: float
    craft_freq: dict[str, float]


class Provenance(BaseModel):
    n_decks: int
    firm_style_mix: dict[str, float]


class StylePriors(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    version: int = 1
    generated_at: str
    n_slides_total: int
    n_slides_high_quality: int
    chart_variants: dict[str, ChartVariant]
    by_claim_context: dict[str, ContextBucket]
    layout_patterns: dict[str, LayoutPattern]
    global_: GlobalStats = Field(alias="global")
    judge_craft_checklist: list[str]
    capability_gaps: dict[str, float]
    provenance: Provenance


# --- jsonl IO -----------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # Torn trailing line from a crashed upstream append: skip,
            # same tolerance as corpus/ingest.py.
            continue
    return rows


def _latest_by_slide(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        sid = row.get("slide_id")
        if sid:
            out[sid] = row  # append-only file: last line wins
    return out


# --- SlideClassification accessors ---------------------------------------------
# classified.jsonl rows are SlideClassification.model_dump() from
# corpus/classify.py: chart features live as BOOLEANS on a nested
# `chart` object (annotations is an int count), layout flags on a
# nested `layout` object, and craft tags under `craft_elements`.
# Flat keys (chart_type/features/craft/structure/...) are accepted as a
# fallback so hand-built or legacy rows still aggregate.

_CHART_FLAG_FEATURES = (
    "value_labels", "endpoint_labels", "avg_or_target_line",
    "delta_brackets", "cagr_arrow", "forecast_dashed", "indexed_base100",
    "area_fill", "series_highlight", "sorted_desc")


def _nested(row: dict, key: str) -> dict:
    sub = row.get(key)
    return sub if isinstance(sub, dict) else {}


def _chart_type(row: dict) -> str | None:
    return row.get("chart_type") or _nested(row, "chart").get("chart_type")


def _features(row: dict) -> list[str]:
    flat = row.get("features")
    if isinstance(flat, list):
        return flat
    chart = _nested(row, "chart")
    out = [f for f in _CHART_FLAG_FEATURES if chart.get(f)]
    if chart.get("annotations"):  # int count in the shipped schema
        out.append("annotations")
    return out


def _craft(row: dict) -> list[str]:
    flat = row.get("craft")
    if isinstance(flat, list):
        return flat
    tags = row.get("craft_elements")
    return tags if isinstance(tags, list) else []


def _structure(row: dict) -> str | None:
    return row.get("structure") or _nested(row, "layout").get("structure")


def _layout_flag(row: dict, key: str) -> bool:
    if key in row:
        return bool(row.get(key))
    return bool(_nested(row, "layout").get(key))


# --- weighted high-quality set --------------------------------------------------

@dataclass
class _Slide:
    slide_id: str
    row: dict
    score: float
    deck_id: str
    source_path: str
    firm: str
    weight: float = 1.0


def _matches_own(source_path: str, glob: str | None) -> bool:
    if not glob:
        return False
    sp = (source_path or "").replace("\\", "/")
    return (fnmatch.fnmatch(sp, glob)
            or fnmatch.fnmatch(sp.rsplit("/", 1)[-1], glob))


def select_high_quality(classified: dict[str, dict],
                        scores: dict[str, float],
                        index: dict[str, dict],
                        own_glob: str | None,
                        min_quality_anchor: str) -> list[_Slide]:
    min_rank = ANCHOR_RANK.get(min_quality_anchor, ANCHOR_RANK["great"])
    picked: list[_Slide] = []
    for sid in sorted(classified):
        row = classified[sid]
        rank = ANCHOR_RANK.get(str(row.get("anchor") or "").lower(), -1)
        conf = float(row.get("confidence") or 0.0)
        score = scores.get(sid, 0.0)
        if rank < min_rank or conf < MIN_CONFIDENCE:
            continue
        if score < MIN_DET_SCORE:
            continue
        idx = index.get(sid, {})
        deck_id = idx.get("deck_id") or sid.split(":", 1)[0]
        source_path = idx.get("source_path") or ""
        picked.append(_Slide(
            slide_id=sid, row=row, score=score, deck_id=deck_id,
            source_path=source_path,
            firm=str(row.get("firm_style") or "unknown"),
            weight=OWN_WEIGHT if _matches_own(source_path, own_glob)
            else 1.0))
    # cap any single deck's contribution at DECK_CAP best-scored slides
    by_deck: dict[str, list[_Slide]] = {}
    for s in picked:
        by_deck.setdefault(s.deck_id, []).append(s)
    capped: list[_Slide] = []
    for deck in sorted(by_deck):
        mem = sorted(by_deck[deck], key=lambda s: (-s.score, s.slide_id))
        capped.extend(mem[:DECK_CAP])
    capped.sort(key=lambda s: s.slide_id)
    _rebalance_firms(capped)
    return capped


def _rebalance_firms(slides: list[_Slide]) -> None:
    """Scale down any firm_style holding > 50% of total weight so it
    lands exactly at 50% (global approximation of the per-bucket cap;
    a single dominant firm cannot dictate every frequency)."""
    for _ in range(8):  # >1 pass only when several firms overflow
        totals: dict[str, float] = {}
        for s in slides:
            totals[s.firm] = totals.get(s.firm, 0.0) + s.weight
        total = sum(totals.values())
        if total <= 0 or len(totals) < 2:
            return
        firm, w = max(totals.items(), key=lambda kv: (kv[1], kv[0]))
        if w / total <= FIRM_SHARE_CAP + 1e-9:
            return
        factor = (total - w) / w
        for s in slides:
            if s.firm == firm:
                s.weight *= factor


# --- aggregation --------------------------------------------------------------

def _round_freqs(d: dict[str, float]) -> dict[str, float]:
    items = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
    return {k: round(v, 4) for k, v in items}


def _wfreq(slides: list[_Slide], has) -> float:
    total = sum(s.weight for s in slides)
    if not total:
        return 0.0
    return sum(s.weight for s in slides if has(s)) / total


def _flag_freqs(slides: list[_Slide], get,
                whitelist: set[str] | None) -> dict[str, float]:
    """Weight share per flag from get(row) -> list[str], optionally
    whitelisted."""
    total = sum(s.weight for s in slides)
    if not total:
        return {}
    acc: dict[str, float] = {}
    for s in slides:
        for flag in get(s.row):
            if whitelist is not None and flag not in whitelist:
                continue
            acc[flag] = acc.get(flag, 0.0) + s.weight
    return _round_freqs({k: v / total for k, v in acc.items()})


def _chart_variants(hq: list[_Slide],
                    min_support: int) -> dict[str, ChartVariant]:
    out: dict[str, ChartVariant] = {}
    for ctype in sorted(RENDERABLE_CHARTS):
        rows = [s for s in hq if _chart_type(s.row) == ctype]
        if len(rows) < min_support:
            continue
        out[ctype] = ChartVariant(
            n=len(rows),
            features=_flag_freqs(rows, _features, RENDERABLE_FEATURES))
    return out


def _by_claim_context(hq: list[_Slide],
                      min_support: int) -> dict[str, ContextBucket]:
    contexts: dict[str, list[_Slide]] = {}
    for s in hq:
        ctx = str(s.row.get("claim_context") or "")
        if ctx:
            contexts.setdefault(ctx, []).append(s)
    out: dict[str, ContextBucket] = {}
    for ctx in sorted(contexts):
        rows = contexts[ctx]
        if len(rows) < min_support:
            continue
        chart_freq = {
            t: _wfreq(rows, lambda s, t=t: _chart_type(s.row) == t)
            for t in sorted(RENDERABLE_CHARTS)}
        chart_freq = _round_freqs(
            {k: v for k, v in chart_freq.items() if v > 0})
        feats = _flag_freqs(rows, _features, RENDERABLE_FEATURES)
        feats = dict(list(feats.items())[:TOP_FEATURES_K])
        out[ctx] = ContextBucket(
            n=len(rows), chart_type_freq=chart_freq, top_features=feats,
            craft_freq=_flag_freqs(rows, _craft, RENDERABLE_CRAFT))
    return out


def _layout_patterns(hq: list[_Slide],
                     min_support: int) -> dict[str, LayoutPattern]:
    roles: dict[str, list[_Slide]] = {}
    for s in hq:
        role = str(s.row.get("slide_role") or "")
        if role:
            roles.setdefault(role, []).append(s)
    out: dict[str, LayoutPattern] = {}
    for role in sorted(roles):
        rows = roles[role]
        if len(rows) < min_support:
            continue
        total = sum(s.weight for s in rows)
        struct: dict[str, float] = {}
        for s in rows:
            name = str(_structure(s.row) or "")
            if name:
                struct[name] = struct.get(name, 0.0) + s.weight
        out[role] = LayoutPattern(
            structure_freq=_round_freqs(
                {k: v / total for k, v in struct.items()}),
            has_bottom_band=round(_wfreq(
                rows, lambda s: _layout_flag(s.row, "has_bottom_band")), 4),
            has_source_footer=round(_wfreq(
                rows,
                lambda s: _layout_flag(s.row, "has_source_footer")), 4))
    return out


def _global_stats(hq: list[_Slide]) -> GlobalStats:
    dens = [(s.weight, float(s.row.get("density")))
            for s in hq if s.row.get("density") is not None]
    wsum = sum(w for w, _ in dens)
    return GlobalStats(
        density_mean=round(
            sum(w * d for w, d in dens) / wsum, 4) if wsum else 0.0,
        title_is_action_rate=round(_wfreq(
            hq, lambda s: bool(s.row.get("title_is_action"))), 4),
        craft_freq=_flag_freqs(hq, _craft, RENDERABLE_CRAFT))


def _capability_gaps(hq: list[_Slide]) -> dict[str, float]:
    total = sum(s.weight for s in hq)
    if not total:
        return {}
    acc: dict[str, float] = {}
    for s in hq:
        gaps: set[str] = set()
        ctype = _chart_type(s.row)
        if ctype and ctype not in RENDERABLE_CHARTS:
            gaps.add(str(ctype))
        gaps |= {f for f in _features(s.row)
                 if f not in RENDERABLE_FEATURES}
        gaps |= {c for c in _craft(s.row)
                 if c not in RENDERABLE_CRAFT}
        for g in gaps:
            acc[g] = acc.get(g, 0.0) + s.weight
    return _round_freqs({k: v / total for k, v in acc.items()})


def _checklist(hq: list[_Slide], global_stats: GlobalStats) -> list[str]:
    """<=6 lines, highest-frequency whitelisted signals first (v1:
    frequency stands in for discriminativeness). Each entry leads with
    the raw token so downstream checks can verify whitelisting."""
    cand: dict[str, float] = dict(global_stats.craft_freq)
    chart_rows = [s for s in hq
                  if _chart_type(s.row) in RENDERABLE_CHARTS]
    for k, v in _flag_freqs(chart_rows, _features,
                            RENDERABLE_FEATURES).items():
        cand[k] = max(cand.get(k, 0.0), v)
    out: list[str] = []
    for name, freq in sorted(cand.items(), key=lambda kv: (-kv[1], kv[0])):
        if freq < CHECKLIST_MIN_FREQ or len(out) >= CHECKLIST_MAX:
            break
        hint = _CHECKLIST_HINTS.get(name, "match the top-firm pattern")
        out.append(f"{name}: {hint} ({freq:.0%} of top slides)")
    return out


def build_priors(classified: dict[str, dict], scores: dict[str, float],
                 index: dict[str, dict], own_glob: str | None,
                 min_quality_anchor: str, min_support: int) -> StylePriors:
    hq = select_high_quality(classified, scores, index, own_glob,
                             min_quality_anchor)
    total_w = sum(s.weight for s in hq)
    mix = {}
    if total_w:
        firms: dict[str, float] = {}
        for s in hq:
            firms[s.firm] = firms.get(s.firm, 0.0) + s.weight
        mix = _round_freqs({k: v / total_w for k, v in firms.items()})
    gstats = _global_stats(hq)
    return StylePriors(
        generated_at=datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        n_slides_total=len(classified),
        n_slides_high_quality=len(hq),
        chart_variants=_chart_variants(hq, min_support),
        by_claim_context=_by_claim_context(hq, min_support),
        layout_patterns=_layout_patterns(hq, min_support),
        global_=gstats,
        judge_craft_checklist=_checklist(hq, gstats),
        capability_gaps=_capability_gaps(hq),
        provenance=Provenance(
            n_decks=len({s.deck_id for s in hq}), firm_style_mix=mix))


# --- run ----------------------------------------------------------------------

def run_patterns(work: str | Path, out: str | Path,
                 own_glob: str | None = None,
                 min_quality_anchor: str = "great",
                 min_support: int = 25) -> dict:
    work = Path(work)
    classified = _latest_by_slide(_read_jsonl(work / "classified.jsonl"))
    scores = {sid: float(row.get("score") or 0) for sid, row in
              _latest_by_slide(_read_jsonl(work / "scores.jsonl")).items()}
    index = _latest_by_slide(_read_jsonl(work / "index.jsonl"))
    priors = build_priors(classified, scores, index, own_glob,
                          min_quality_anchor, min_support)
    data = priors.model_dump(by_alias=True)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(
        description="Aggregate slide classifications into style priors.")
    ap.add_argument("--work",
                    default=str(Path(__file__).resolve().parent / "work"),
                    help="derived-data dir (default: corpus/work)")
    ap.add_argument("--out",
                    default=str(root / "deckengine/llm/style_priors.json"),
                    help="committed priors file")
    ap.add_argument("--own-glob", default=None,
                    help="source_path glob whose slides weigh 2.0")
    ap.add_argument("--min-quality-anchor", default="great",
                    choices=sorted(ANCHOR_RANK),
                    help="loosen to 'mediocre' on small corpora")
    ap.add_argument("--min-support", type=int, default=25,
                    help="drop keyed buckets with fewer slides")
    args = ap.parse_args(argv)
    data = run_patterns(args.work, args.out, args.own_glob,
                        args.min_quality_anchor, args.min_support)
    print(json.dumps({"n_slides_total": data["n_slides_total"],
                      "n_slides_high_quality":
                          data["n_slides_high_quality"],
                      "out": str(args.out)}))


if __name__ == "__main__":
    main()
