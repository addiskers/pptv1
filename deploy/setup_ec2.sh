#!/usr/bin/env bash
# One-shot setup for DeckEngine on Amazon Linux 2023 (EC2).
# Installs: Python 3.11, fonts (metric-compatible with the theme fonts),
# headless LibreOffice (for slide previews), and the Python package.
#
#   git clone https://github.com/addiskers/pptv1.git deckengine
#   cd deckengine
#   bash deploy/setup_ec2.sh
#
# Then set your keys and run deploy/run.sh (see below).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== system packages (dnf) =="
sudo dnf install -y \
  python3.11 python3.11-pip python3.11-devel gcc \
  libreoffice-core libreoffice-impress libreoffice-writer \
  liberation-fonts liberation-sans-fonts liberation-serif-fonts \
  dejavu-sans-fonts dejavu-serif-fonts \
  google-noto-sans-fonts google-noto-serif-fonts \
  fontconfig cairo || true
# Best-effort closer clones (Calibri/Cambria metrics). Not fatal if absent —
# the font registry falls back to Liberation/DejaVu, which are guaranteed.
sudo dnf install -y google-crosextra-carlito-fonts google-crosextra-caladea-fonts 2>/dev/null || true

echo "== metric-compatible clone fonts (best effort) =="
# Gelasio = Georgia metrics, Selawik = Segoe UI metrics. If these fail to
# download, generation still works via the Liberation fallback chain.
FDIR="$HOME/.local/share/fonts"; mkdir -p "$FDIR"
dl() { curl -fsSL --retry 2 "$1" -o "$FDIR/$2" 2>/dev/null && echo "  + $2" || echo "  - $2 (skipped; fallback will be used)"; }
GEL="https://raw.githubusercontent.com/google/fonts/main/ofl/gelasio"
dl "$GEL/Gelasio-Regular.ttf"     Gelasio-Regular.ttf
dl "$GEL/Gelasio-Bold.ttf"        Gelasio-Bold.ttf
dl "$GEL/Gelasio-Italic.ttf"      Gelasio-Italic.ttf
dl "$GEL/Gelasio-BoldItalic.ttf"  Gelasio-BoldItalic.ttf
SEL="https://github.com/microsoft/Selawik/raw/master/fonts/ttf"
dl "$SEL/selawk.ttf"   selawk.ttf
dl "$SEL/selawkb.ttf"  selawkb.ttf
fc-cache -f "$FDIR" >/dev/null 2>&1 || true

echo "== python env =="
python3.11 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -e ".[server]"

echo "== self-check (fonts + render + soffice preview) =="
DECKENGINE_PREVIEW=soffice python - <<'PY'
from pathlib import Path
from deckengine.core.theme import load_theme
from deckengine.core.fonts import default_registry
from deckengine.render.deck_builder import build_deck
from deckengine.render.preview_provider import get_preview_exporter
from deckengine.schema.slide_types import DeckSpec

for t in ("consulting_navy", "consulting_paper"):
    default_registry().validate_theme(load_theme(t))
    print(f"  fonts OK for theme: {t}")

demo = __import__("json").loads(Path("examples/specs/agdev_demo.json").read_text())
spec = DeckSpec.model_validate(demo)
rep = build_deck(spec, Path("/tmp/deckengine_selfcheck.pptx"))
print(f"  render OK: {len(spec.slides)} slides, {len(rep.warnings)} warnings")
exp = get_preview_exporter()
if exp:
    pngs = exp("/tmp/deckengine_selfcheck.pptx", "/tmp/deckengine_selfcheck_png")
    print(f"  soffice preview OK: {len(pngs)} PNGs")
else:
    print("  no preview exporter (set DECKENGINE_PREVIEW=soffice; install libreoffice)")
print("SELF-CHECK PASSED")
PY

echo
echo "Done. Next:"
echo "  export OPENAI_API_KEY=sk-...          # or ANTHROPIC_API_KEY"
echo "  export DECKENGINE_API_KEY=<a-secret>  # REQUIRED before exposing publicly"
echo "  bash deploy/run.sh"
