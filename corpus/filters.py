"""Stage-1 deterministic junk filters over the corpus index.

CLI:  python corpus/filters.py [--work DIR]

Reads work/index.jsonl (SlideRecord lines; the last line per slide_id
wins because re-ingest appends) and rewrites work/filtered.jsonl with
one FilterVerdict per slide. Kill reasons are stable tags: dup,
boilerplate, placeholder, too_sparse, wall_of_text, era. Boilerplate
kinds (agenda / thank-you / divider / title-page) keep their FIRST two
otherwise-clean exemplars per kind so downstream style priors still
see each kind; the rest die. Exemplars skip the sparsity checks — a
divider is sparse by construction. PDF pages carry no shape stats, so
only dup / placeholder / too_sparse / wall_of_text can fire for them:
never boilerplate-by-shape-count and never era.

Design: filter_slide is a pure function of (record, running
boilerplate counter) so tests build SlideRecords directly; JSONL
reading reuses the torn-line-tolerant reader in corpus.ingest.
filtered.jsonl is a derived artifact rewritten whole each run —
appending would duplicate verdicts and skew exemplar quotas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

if __package__ in (None, ""):  # allow `python corpus/filters.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus.ingest import _read_jsonl
from corpus.models import ShapeStats, SlideRecord

BOILERPLATE_EXEMPLARS = 2
SPARSE_WORDS = 15
WALL_WORDS = 250
DIVIDER_WORDS = 8
DIVIDER_SHAPES = 3
ERA_ASPECT = 4.0 / 3.0
ERA_ASPECT_TOL = 0.02
ERA_FONTS = {"comic sans ms", "papyrus"}
PLACEHOLDER_MARKERS = ("click to add", "lorem ipsum",
                       "insert text here")
# Normalized (lowercase, punctuation stripped) title / first-line
# phrases that mark agenda, divider, thank-you and similar slides.
BOILERPLATE_PHRASES = {
    "agenda", "contents", "table of contents", "todays agenda",
    "todays discussion", "discussion topics", "thank you", "thanks",
    "thank you questions", "questions", "any questions", "q a",
    "appendix", "disclaimer", "backup", "end of presentation",
}


class FilterVerdict(BaseModel):
    slide_id: str
    keep: bool
    reasons: list[str] = Field(default_factory=list)


# --- pure helpers -----------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    out = "".join(c if c.isalnum() or c.isspace() else " "
                  for c in s.lower())
    return " ".join(out.split())


def _slide_text(rec: SlideRecord) -> str:
    if rec.extracted_text:
        return rec.extracted_text
    if rec.shape_stats is not None:
        return rec.shape_stats.all_text
    return ""


def _boilerplate_kind(stats: ShapeStats, words: int) -> str | None:
    """Boilerplate kind tag, or None if the slide looks like content."""
    first_line = ""
    for line in stats.all_text.splitlines():
        if line.strip():
            first_line = line
            break
    for cand in (stats.title_text, first_line):
        norm = _norm(cand)
        if norm and norm in BOILERPLATE_PHRASES:
            return norm
    # 0 < n_shapes: a completely blank slide is junk, not a divider —
    # it must not consume the divider exemplar quota (it falls through
    # to too_sparse instead).
    if words < DIVIDER_WORDS and 0 < stats.n_shapes <= DIVIDER_SHAPES:
        return "divider"
    return None


def filter_slide(rec: SlideRecord,
                 seen_boilerplate: dict) -> FilterVerdict:
    """Verdict for one slide; mutates seen_boilerplate (kind -> count
    of exemplars kept so far) so callers stream records in order."""
    reasons: list[str] = []
    stats = rec.shape_stats
    text = _slide_text(rec)
    words = len(text.split())

    if rec.dup_of:
        reasons.append("dup")
    lower = text.lower()
    if any(m in lower for m in PLACEHOLDER_MARKERS):
        reasons.append("placeholder")
    if stats is not None:
        aspect_43 = (stats.aspect is not None
                     and abs(stats.aspect - ERA_ASPECT) < ERA_ASPECT_TOL)
        if aspect_43 or any(f.lower() in ERA_FONTS for f in stats.fonts):
            reasons.append("era")

    # Only otherwise-clean slides may consume an exemplar slot, so a
    # dup agenda never crowds out the canonical one. Any recognized
    # boilerplate kind skips the sparsity checks: "boilerplate" is
    # the meaningful verdict, sparse/wall tags would be noise.
    is_boilerplate = False
    if stats is not None and not reasons:
        kind = _boilerplate_kind(stats, words)
        if kind is not None:
            is_boilerplate = True
            seen = seen_boilerplate.get(kind, 0)
            if seen < BOILERPLATE_EXEMPLARS:
                seen_boilerplate[kind] = seen + 1
            else:
                reasons.append("boilerplate")

    if not is_boilerplate:
        n_visuals = n_chart_tables = 0
        if stats is not None:
            n_visuals = (stats.n_pictures + stats.n_charts
                         + stats.n_tables)
            n_chart_tables = stats.n_charts + stats.n_tables
        if words < SPARSE_WORDS and n_visuals == 0:
            reasons.append("too_sparse")
        if words > WALL_WORDS and n_chart_tables == 0:
            reasons.append("wall_of_text")

    return FilterVerdict(slide_id=rec.slide_id, keep=not reasons,
                         reasons=reasons)


# --- work-dir IO ------------------------------------------------------------

def load_index(work: Path) -> list[SlideRecord]:
    """Index records in first-seen order; last line per slide_id wins
    (re-ingest of a touched deck appends fresh lines)."""
    by_id: dict[str, SlideRecord] = {}
    for row in _read_jsonl(work / "index.jsonl"):
        rec = SlideRecord.model_validate(row)
        by_id[rec.slide_id] = rec
    return list(by_id.values())


def write_jsonl(path: Path, rows: list[dict]) -> None:
    """Rewrite a derived artifact whole (unlike the append-only index)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_filters(work: str | Path) -> dict:
    work = Path(work)
    seen_boilerplate: dict[str, int] = {}
    verdicts = [filter_slide(rec, seen_boilerplate)
                for rec in load_index(work)]
    write_jsonl(work / "filtered.jsonl",
                [v.model_dump() for v in verdicts])
    kept = sum(1 for v in verdicts if v.keep)
    return {"total": len(verdicts), "kept": kept,
            "killed": len(verdicts) - kept}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Stage-1 junk filters: index.jsonl -> filtered.jsonl")
    ap.add_argument("--work",
                    default=str(Path(__file__).resolve().parent / "work"),
                    help="derived-data dir (default: corpus/work)")
    args = ap.parse_args(argv)
    print(json.dumps(run_filters(args.work)))


if __name__ == "__main__":
    main()
