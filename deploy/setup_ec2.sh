#!/usr/bin/env bash
# One-shot setup for DeckEngine on Amazon Linux 2023 (EC2).
# Steps are independent and tolerant: a missing OPTIONAL package (e.g.
# LibreOffice, which AL2023 does not package) never blocks the essentials.
#
#   git clone https://github.com/addiskers/pptv1.git deckengine
#   cd deckengine && bash deploy/setup_ec2.sh
#
# Re-runnable. Prints the preview mode to put in .env at the end.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== [1/5] Python 3.11 (essential) =="
sudo dnf install -y python3.11 python3.11-pip python3.11-devel gcc \
  || { echo "FATAL: python3.11 install failed"; exit 1; }

echo "== [2/5] Fonts (metric clones ship IN the repo) =="
# The metric-compatible clones (Gelasio=Georgia, Selawik=Segoe UI,
# Carlito=Calibri, LiberationSans=Arial) are VENDORED in assets/fonts/ and
# resolve first — no system font may stand in for a theme family (the old
# Georgia->LiberationSerif mapping measured 8-12% narrow and wrecked every
# layout). System packages below are only glyph fallbacks: Noto Devanagari
# for Nirmala UI, DejaVu for Segoe UI Symbol markers.
for f in Gelasio-Regular.ttf Gelasio-Bold.ttf selawk.ttf selawkb.ttf \
         Carlito-Regular.ttf LiberationSans-Regular.ttf; do
  [ -f "assets/fonts/$f" ] || { echo "FATAL: assets/fonts/$f missing — pull the full repo"; exit 1; }
done
echo "  bundled metric clones present"
sudo dnf install -y fontconfig dejavu-sans-fonts || true
sudo dnf install -y google-noto-sans-fonts google-noto-sans-devanagari-fonts || true
fc-cache -f >/dev/null 2>&1 || true

echo "== [3/5] LibreOffice for slide previews (optional) =="
PREVIEW=none
if command -v soffice >/dev/null 2>&1; then
  PREVIEW=soffice
elif sudo dnf install -y libreoffice-impress >/dev/null 2>&1 && command -v soffice >/dev/null 2>&1; then
  PREVIEW=soffice
elif sudo dnf install -y libreoffice >/dev/null 2>&1 && command -v soffice >/dev/null 2>&1; then
  PREVIEW=soffice
else
  echo "  LibreOffice not available from dnf on this AMI."
  echo "  -> Deploying WITHOUT previews (generation + download work fully)."
  echo "  -> To add previews later:  bash deploy/install_libreoffice.sh"
fi
echo "  preview mode: $PREVIEW"

echo "== [4/5] Python package =="
python3.11 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel >/dev/null
pip install -e ".[server]"

echo "== [5/5] Self-check (fonts resolve + demo deck renders) =="
DECKENGINE_PREVIEW="$PREVIEW" python - <<'PY'
import json
from pathlib import Path
from deckengine.core.theme import load_theme
from deckengine.core.fonts import default_registry
from deckengine.render.deck_builder import build_deck
from deckengine.render.preview_provider import get_preview_exporter
from deckengine.schema.slide_types import DeckSpec

for t in ("consulting_navy", "consulting_paper", "skyquest_brand"):
    default_registry().validate_theme(load_theme(t))
    print(f"  fonts OK: {t}")

spec = DeckSpec.model_validate(
    json.loads(Path("examples/specs/agdev_demo.json").read_text()))
rep = build_deck(spec, Path("/tmp/deckengine_selfcheck.pptx"))
print(f"  render OK: {len(spec.slides)} slides, {len(rep.warnings)} warnings")

exp = get_preview_exporter()
if exp is None:
    print("  previews OFF (no LibreOffice) — deck still generates & downloads")
else:
    pngs = exp("/tmp/deckengine_selfcheck.pptx", "/tmp/deckengine_selfcheck_png")
    print(f"  preview OK: {len(pngs)} PNGs via {exp.__name__}")
print("SELF-CHECK PASSED")
PY

echo
echo "Setup complete. Next:"
echo "  cat > .env <<EOF"
echo "  OPENAI_API_KEY=sk-...            # or ANTHROPIC_API_KEY=..."
echo "  DECKENGINE_API_KEY=<long-random> # REQUIRED before public exposure"
echo "  DECKENGINE_PREVIEW=$PREVIEW"
echo "  DECKENGINE_EMBED_FONTS=1         # served decks carry their fonts"
echo "  EOF"
echo "  sudo cp deploy/deckengine.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload && sudo systemctl enable --now deckengine"
