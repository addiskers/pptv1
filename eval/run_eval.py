"""Tier-0 deterministic eval: render pinned specs, score, compare to last accepted.

Usage:
    python eval/run_eval.py            # score all pinned specs
    python eval/run_eval.py --accept   # bless current scores as the new baseline

Scores per deck (all deterministic, no LLM):
    warnings, truncations, overflow count, body-zone fill ratios (min / mean),
    slide count. Regressions vs eval/accepted.json fail the run (exit 1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckengine.render.deck_builder import build_deck  # noqa: E402
from deckengine.schema.slide_types import DeckSpec  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
SPEC_DIRS = [EVAL_DIR.parents[0] / "examples" / "specs", EVAL_DIR / "specs_cache",
             EVAL_DIR / "goldens"]
OUT_DIR = EVAL_DIR / "out"
ACCEPTED = EVAL_DIR / "accepted.json"

MIN_FILL_FLOOR = 0.55  # any body zone below this is a dead-space defect


def score_spec(path: Path) -> dict:
    spec = DeckSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
    out = OUT_DIR / f"{path.stem}.pptx"
    report = build_deck(spec, out)
    overflow = sum(1 for w in report.warnings if "overflow" in w)
    return {
        "slides": len(spec.slides),
        "warnings": len(report.warnings),
        "truncations": len(report.truncations),
        "overflows": overflow,
        "min_fill": round(min(report.fills), 3) if report.fills else None,
        "mean_fill": (round(sum(report.fills) / len(report.fills), 3)
                      if report.fills else None),
        "zones_below_floor": sum(1 for f in report.fills if f < MIN_FILL_FLOOR),
    }


def main() -> int:
    accept = "--accept" in sys.argv
    OUT_DIR.mkdir(exist_ok=True)
    specs = sorted(p for d in SPEC_DIRS if d.is_dir()
                   for p in d.glob("*.json"))
    if not specs:
        print("no pinned specs found"); return 1

    scores = {p.stem: score_spec(p) for p in specs}
    print(f"{'deck':<28}{'slides':>7}{'warn':>6}{'trunc':>6}{'ovfl':>6}"
          f"{'minfill':>9}{'below':>7}")
    for name, s in scores.items():
        print(f"{name:<28}{s['slides']:>7}{s['warnings']:>6}"
              f"{s['truncations']:>6}{s['overflows']:>6}"
              f"{str(s['min_fill']):>9}{s['zones_below_floor']:>7}")

    if accept:
        ACCEPTED.write_text(json.dumps(scores, indent=2), encoding="utf-8")
        print("\naccepted as new baseline")
        return 0

    if not ACCEPTED.is_file():
        print("\nno accepted baseline yet — run with --accept to bless")
        return 0

    baseline = json.loads(ACCEPTED.read_text(encoding="utf-8"))
    failures = []
    for name, s in scores.items():
        b = baseline.get(name)
        if not b:
            # ABSOLUTE floor for decks with no blessed baseline: new pinned
            # specs must ship with zero dead-space zones. (Legacy entries
            # keep the ratchet below — their content is pinned and cannot
            # be retro-filled by engine changes.)
            if s["zones_below_floor"] > 0:
                failures.append(
                    f"{name}: NEW deck has {s['zones_below_floor']} zone(s) "
                    f"below the {MIN_FILL_FLOOR} fill floor "
                    f"(min_fill {s['min_fill']}) — fix before accepting")
            continue
        for metric, worse_is_higher in (("warnings", True), ("truncations", True),
                                        ("overflows", True),
                                        ("zones_below_floor", True)):
            if s[metric] > b[metric]:
                failures.append(f"{name}: {metric} {b[metric]} -> {s[metric]}")
        if (s["min_fill"] is not None and b.get("min_fill") is not None
                and s["min_fill"] < b["min_fill"] - 0.05):
            failures.append(f"{name}: min_fill {b['min_fill']} -> {s['min_fill']}")
    if failures:
        print("\nREGRESSIONS:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nno regressions vs accepted baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
