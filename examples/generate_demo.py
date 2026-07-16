"""Render the demo spec and (on Windows + Office) export PowerPoint previews.

Usage:  python examples/generate_demo.py [spec.json] [out.pptx]
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckengine.render.deck_builder import build_deck  # noqa: E402
from deckengine.schema.slide_types import DeckSpec  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

spec_path = Path(sys.argv[1] if len(sys.argv) > 1 else
                 Path(__file__).parent / "specs" / "agdev_demo.json")
out_path = Path(sys.argv[2] if len(sys.argv) > 2 else
                Path(__file__).parent / "out" / "agdev_demo.pptx")

spec = DeckSpec.model_validate(json.loads(spec_path.read_text(encoding="utf-8")))
report = build_deck(spec, out_path)

print(f"\nwrote {out_path}")
print(f"warnings: {len(report.warnings)}")
for w in report.warnings:
    print("  -", w)
for t in report.truncations:
    print("  truncated:", t)
