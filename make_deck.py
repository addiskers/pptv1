"""THE front door: describe the deck you want, get a .pptx.

Usage:
    python make_deck.py "10-slide impact report on our India agri programs"
    python make_deck.py "Q2 sales review" --csv sales.csv
    python make_deck.py --spec examples/specs/agdev_demo.json     (no LLM, no key)
    python make_deck.py "..." --out my_deck.pptx --theme consulting_navy

The plain-English path needs an Anthropic API key:
    PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."
    (get one at https://console.anthropic.com/settings/keys)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deckengine.envfile import load_env  # noqa: E402
load_env()

from deckengine.render.deck_builder import build_deck  # noqa: E402
from deckengine.schema.slide_types import DeckSpec  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a consulting-grade .pptx")
    ap.add_argument("prompt", nargs="?", help="What you want, in plain English")
    ap.add_argument("--csv", help="CSV file with the numbers the deck should use")
    ap.add_argument("--spec", help="Render a hand-written JSON spec (skips the LLM)")
    ap.add_argument("--out", default="deck.pptx", help="Output .pptx path")
    ap.add_argument("--theme", default="consulting_navy")
    ap.add_argument("--preview", action="store_true",
                    help="Also export PNGs via PowerPoint (Windows + Office)")
    args = ap.parse_args()

    if args.spec:
        spec = DeckSpec.model_validate(
            json.loads(Path(args.spec).read_text(encoding="utf-8")))
    elif args.prompt:
        if not (os.environ.get("OPENAI_API_KEY")
                or os.environ.get("ANTHROPIC_API_KEY")):
            sys.exit(
                "The plain-English path needs an LLM API key.\n"
                '  PowerShell:  $env:OPENAI_API_KEY = "sk-..."      (OpenAI)\n'
                '           or  $env:ANTHROPIC_API_KEY = "sk-ant-..." (Anthropic)\n'
                "Or render a hand-written spec instead:\n"
                "  python make_deck.py --spec examples/specs/agdev_demo.json")
        from deckengine.llm.spec_generator import generate_deck_spec
        csv_text = Path(args.csv).read_text(encoding="utf-8") if args.csv else None
        print("Asking the model to plan and write the slide specs...")
        spec = generate_deck_spec(args.prompt, csv_text=csv_text, theme=args.theme)
        spec_out = Path(args.out).with_suffix(".spec.json")
        spec_out.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        print(f"spec saved to {spec_out} (edit it and re-run with --spec to tweak)")
    else:
        ap.error("give a prompt, or --spec path/to/spec.json")

    report = build_deck(spec, args.out)
    print(f"\nwrote {args.out}  ({len(spec.slides)} slides, "
          f"{len(report.warnings)} warnings)")
    for w in report.warnings:
        print("  warning:", w)

    if args.preview:
        from deckengine.render.preview import export_pngs_powerpoint
        outdir = Path(args.out).with_suffix("") .parent / "previews"
        pngs = export_pngs_powerpoint(args.out, outdir)
        print(f"previews: {len(pngs)} PNGs in {outdir}")


if __name__ == "__main__":
    main()
