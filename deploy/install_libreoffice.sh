#!/usr/bin/env bash
# Install headless LibreOffice on Amazon Linux 2023 (no dnf package exists).
# Downloads the pinned TDF stable RPM tarball, installs runtime deps,
# symlinks soffice onto PATH, and smoke-tests through DeckEngine's own
# preview seam. Re-runnable; safe to re-invoke after a partial failure.
#
#   bash deploy/install_libreoffice.sh
#
# After success, put in .env:
#   DECKENGINE_PREVIEW=soffice
#   DECKENGINE_SOFFICE=/usr/local/bin/soffice
set -uo pipefail
cd "$(dirname "$0")/.."

STABLE_INDEX="https://download.documentfoundation.org/libreoffice/stable/"
LO_VERSION="${LO_VERSION:-auto}"
if [ "$LO_VERSION" = "auto" ]; then
  # TDF prunes old point releases from /stable/ — discover what exists and
  # prefer the OLDEST listed branch ("still": most conservative), newest
  # patch within it. Pin via LO_VERSION=x.y.z to override.
  vers=$(curl -fsSL "$STABLE_INDEX" | grep -oE 'href="[0-9]+\.[0-9]+\.[0-9]+/"' \
         | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | sort -uV)
  [ -n "$vers" ] || { echo "FATAL: could not list $STABLE_INDEX"; exit 1; }
  still_branch=$(echo "$vers" | head -1 | cut -d. -f1-2)
  LO_VERSION=$(echo "$vers" | grep "^${still_branch}\." | tail -1)
  echo "  discovered LibreOffice versions: $(echo $vers | tr '\n' ' ')"
  echo "  picked (still branch): $LO_VERSION"
fi
LO_DIR="LibreOffice_${LO_VERSION}_Linux_x86-64_rpm"
LO_TAR="${LO_DIR}.tar.gz"
# primary + mirror fallback (TDF moves old point releases to downloadarchive)
LO_URLS=(
  "https://download.documentfoundation.org/libreoffice/stable/${LO_VERSION}/rpm/x86_64/${LO_TAR}"
  "https://downloadarchive.documentfoundation.org/libreoffice/old/${LO_VERSION}/rpm/x86_64/${LO_TAR}"
)

echo "== [1/5] Preflight =="
if command -v soffice >/dev/null 2>&1; then
  echo "  soffice already on PATH: $(command -v soffice) — skipping install"
else
  avail_kb=$(df --output=avail /opt | tail -1 | tr -d ' ')
  if [ "${avail_kb:-0}" -lt 2500000 ]; then
    echo "FATAL: need ~2.5GB free under /opt (have ${avail_kb}KB)"; exit 1
  fi

  echo "== [2/5] Runtime dependencies (dnf) =="
  # LibreOffice RPMs assume a desktop-ish userland; headless still needs these
  sudo dnf install -y -q cairo cups-libs libSM libICE libXinerama \
    libXrender libXext libXrandr libX11 dbus-libs freetype fontconfig \
    nss nspr || { echo "FATAL: dependency install failed"; exit 1; }

  echo "== [3/5] Download + install LibreOffice ${LO_VERSION} =="
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  ok=""
  for url in "${LO_URLS[@]}"; do
    echo "  trying $url"
    if curl -fSL --retry 3 -o "$tmp/$LO_TAR" "$url"; then ok=1; break; fi
  done
  [ -n "$ok" ] || { echo "FATAL: download failed from all mirrors"; exit 1; }
  tar -xzf "$tmp/$LO_TAR" -C "$tmp"
  # the tarball's inner dir uses the FULL 4-part build version (e.g.
  # 25.8.7.2) — locate RPMS by search, never by constructed name.
  # skip desktop-integration RPMs (menus/mime, pull desktop deps we don't have)
  rpms=$(find "$tmp" -path '*/RPMS/*.rpm' ! -name '*desktop-integration*')
  [ -n "$rpms" ] || { echo "FATAL: no RPMs found in extracted tarball"; exit 1; }
  # shellcheck disable=SC2086
  sudo dnf install -y -q $rpms || { echo "FATAL: rpm install failed"; exit 1; }
fi

echo "== [4/5] PATH symlink =="
if ! command -v soffice >/dev/null 2>&1; then
  prog=$(ls -d /opt/libreoffice*/program/soffice 2>/dev/null | head -1)
  [ -n "$prog" ] || { echo "FATAL: soffice binary not found under /opt"; exit 1; }
  sudo ln -sf "$prog" /usr/local/bin/soffice
fi
soffice --version || { echo "FATAL: soffice does not run (check ldd $(command -v soffice))"; exit 1; }

echo "== [5/5] Smoke test through DeckEngine's preview seam =="
DECKENGINE_PREVIEW=soffice DECKENGINE_SOFFICE="$(command -v soffice)" \
.venv/bin/python - <<'PY'
import json, sys, tempfile, time
from pathlib import Path
from deckengine.render.deck_builder import build_deck
from deckengine.render.preview_provider import get_preview_exporter
from deckengine.schema.slide_types import DeckSpec

spec = DeckSpec.model_validate(json.loads(
    Path("examples/specs/agdev_demo.json").read_text(encoding="utf-8")))
out = Path(tempfile.mkdtemp()) / "lo_smoke.pptx"
build_deck(spec, out)
exp = get_preview_exporter()
assert exp is not None, "preview seam returned None with soffice set"
t0 = time.time()
pngs = exp(out, out.parent / "png", width=1280, height=720)
print(f"  preview OK: {len(pngs)} PNGs in {time.time()-t0:.1f}s (cold)")
assert len(pngs) == len(spec.slides)
PY
echo
echo "LibreOffice ready. Add to .env:"
echo "  DECKENGINE_PREVIEW=soffice"
echo "  DECKENGINE_SOFFICE=$(command -v soffice)"
echo "Then: sudo systemctl restart deckengine   (only when no jobs are running)"
