"""Stage-2a deterministic slide quality score (v1 heuristics).

CLI:  python corpus/score.py [--work DIR]

Reads work/index.jsonl plus work/filtered.jsonl and rewrites
work/scores.jsonl with one DetScore line per keep=true slide. The
0-100 score is a documented, deterministic sum of five parts:

- fill (0-25): covered_frac in [0.35, 0.80] is full marks, linear
  falloff to 0 at empty (0.0) and saturated (1.0) canvases.
- alignment (0-25): 4-10 distinct x-edges is full marks (a real
  grid); falloff to 0 at >= 28 (careless scatter) and below 3.
- font_discipline (0-20): <= 2 font families full, -6 per extra.
- fill_discipline (0-15): <= 6 distinct solid fills full, -1.5 per
  extra.
- balance (0-15): a visual (chart/table/picture) plus 15-180 words
  is full; visual-only or word-range-only is partial.

PDF pages carry no shape geometry, so fill and alignment fall back
to a neutral midpoint (12) instead of punishing them. These are v1
heuristics: cheap, explainable rankers feeding the LLM/vision
stages — not ground-truth quality labels.

Design: score_slide and the per-part functions are pure so tests
craft SlideRecords directly; index/filtered IO reuses the tolerant
reader via corpus.filters; scores.jsonl is a derived artifact
rewritten whole each run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

if __package__ in (None, ""):  # allow `python corpus/score.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus.filters import (FilterVerdict, load_index, write_jsonl,
                            _read_jsonl)
from corpus.models import SlideRecord

FILL_LO, FILL_HI = 0.35, 0.80
ALIGN_LO, ALIGN_HI = 4, 10
ALIGN_DEAD = 28
FONT_FREE = 2
FONT_PENALTY = 6.0
FILLS_FREE = 6
FILLS_PENALTY = 1.5
BALANCE_LO, BALANCE_HI = 15, 180
NEUTRAL_GEOMETRY = 12.0


class DetScore(BaseModel):
    slide_id: str
    score: int = Field(ge=0, le=100)
    parts: dict[str, float]


# --- pure part functions ----------------------------------------------------

def part_fill(covered: float | None) -> float:
    if covered is None:  # PDFs: no geometry -> neutral
        return NEUTRAL_GEOMETRY
    if covered < FILL_LO:
        return 25.0 * covered / FILL_LO
    if covered > FILL_HI:
        return 25.0 * max(0.0, (1.0 - covered) / (1.0 - FILL_HI))
    return 25.0


def part_alignment(x_edges: list[int] | None) -> float:
    if not x_edges:  # PDFs / no geometry -> neutral
        return NEUTRAL_GEOMETRY
    n = len(x_edges)
    if n < 3:
        return 0.0
    if n < ALIGN_LO:  # n == 3: gray zone, half marks
        return 12.5
    if n <= ALIGN_HI:
        return 25.0
    return 25.0 * max(0.0, (ALIGN_DEAD - n) / (ALIGN_DEAD - ALIGN_HI))


def part_font_discipline(n_fonts: int) -> float:
    return max(0.0, 20.0 - FONT_PENALTY * max(0, n_fonts - FONT_FREE))


def part_fill_discipline(n_fills: int) -> float:
    return max(0.0, 15.0 - FILLS_PENALTY * max(0, n_fills - FILLS_FREE))


def part_balance(has_visual: bool, words: int) -> float:
    in_range = BALANCE_LO <= words <= BALANCE_HI
    if has_visual and in_range:
        return 15.0
    if has_visual or in_range:
        return 8.0
    return 3.0


def score_slide(rec: SlideRecord) -> DetScore:
    stats = rec.shape_stats
    text = rec.extracted_text
    if not text and stats is not None:
        text = stats.all_text
    words = len(text.split())
    has_visual = bool(stats is not None
                      and (stats.n_charts or stats.n_tables
                           or stats.n_pictures))
    parts = {
        "fill": part_fill(stats.covered_frac if stats else None),
        "alignment": part_alignment(stats.x_edges if stats else None),
        "font_discipline": part_font_discipline(
            len(stats.fonts) if stats else 0),
        "fill_discipline": part_fill_discipline(
            stats.n_distinct_fills if stats else 0),
        "balance": part_balance(has_visual, words),
    }
    parts = {k: round(v, 2) for k, v in parts.items()}
    score = max(0, min(100, int(round(sum(parts.values())))))
    return DetScore(slide_id=rec.slide_id, score=score, parts=parts)


# --- work-dir IO ------------------------------------------------------------

def run_scoring(work: str | Path) -> dict:
    work = Path(work)
    keep: dict[str, bool] = {}  # last verdict per slide_id wins
    for row in _read_jsonl(work / "filtered.jsonl"):
        v = FilterVerdict.model_validate(row)
        keep[v.slide_id] = v.keep
    scores = [score_slide(rec) for rec in load_index(work)
              if keep.get(rec.slide_id)]
    write_jsonl(work / "scores.jsonl",
                [s.model_dump() for s in scores])
    return {"scored": len(scores)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Deterministic 0-100 slide scores -> scores.jsonl")
    ap.add_argument("--work",
                    default=str(Path(__file__).resolve().parent / "work"),
                    help="derived-data dir (default: corpus/work)")
    args = ap.parse_args(argv)
    print(json.dumps(run_scoring(args.work)))


if __name__ == "__main__":
    main()
