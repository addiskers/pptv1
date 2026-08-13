"""Font-metric correctness — the EC2-disaster regression gate.

Whatever file resolve() returns for a theme family MUST measure within 1%
of the real Microsoft face (baselines recorded on the Windows dev box).
The evaluated Gujarat deck failed because Liberation Serif (Times-metric,
~8-12% narrow) stood in for Georgia on EC2; these tests make that class of
substitution impossible to reintroduce.
"""
from __future__ import annotations

import sys

import pytest
import uharfbuzz as hb

from deckengine.core.fonts import FontRegistry

REF = "Handgloves 0123456789 Sabarkantha, Patan, Mehsana Market Income Water"

# advance width of REF at 100pt, measured with the REAL Microsoft faces
# (recorded 2026-08-13 on the Windows dev box) — the ground truth every
# resolved file must stay within 1% of.
BASELINES = {
    ("Georgia", False): 3437.35,
    ("Georgia", True): 3980.71,
    ("Segoe UI", False): 3386.18,
    ("Segoe UI", True): 3620.41,
    ("Arial", False): 3470.65,
    ("Arial", True): 3620.07,
    ("Calibri", False): 3140.72,
    ("Calibri", True): 3204.20,
}

# what filenames are ALLOWED to satisfy each family (real face or verified
# metric clone — nothing else, ever)
ALLOWED = {
    "Georgia": ("georgia", "gelasio"),
    "Segoe UI": ("segoeui", "seguisli", "selawk", "selawik"),
    "Arial": ("arial", "liberationsans", "arimo"),
    "Calibri": ("calibri", "carlito"),
}


def _width_pt(path, size=100.0) -> float:
    blob = hb.Blob.from_file_path(str(path))
    face = hb.Face(blob)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(REF)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    units = sum(p.x_advance for p in buf.glyph_positions)
    return units / face.upem * size


@pytest.mark.parametrize("family,bold", list(BASELINES))
def test_resolved_face_is_metric_correct(family, bold):
    reg = FontRegistry()
    path = reg.resolve(family, bold=bold)
    width = _width_pt(path)
    baseline = BASELINES[(family, bold)]
    delta = abs(width - baseline) / baseline
    assert delta < 0.01, (
        f"{family} bold={bold} resolved to {path.name} which measures "
        f"{width:.1f} vs baseline {baseline:.1f} ({delta:.2%} off) — a "
        f"non-metric-compatible face has crept into _KNOWN")


@pytest.mark.parametrize("family", list(ALLOWED))
def test_resolution_allowlist(family):
    reg = FontRegistry()
    for bold in (False, True):
        name = reg.resolve(family, bold=bold).name.lower()
        assert any(name.startswith(stem) for stem in ALLOWED[family]), (
            f"{family} bold={bold} resolved to disallowed file {name!r}")


@pytest.mark.skipif(sys.platform.startswith("win"),
                    reason="Linux/EC2-only: must resolve to bundled clones")
def test_linux_resolves_to_bundled_clones():
    reg = FontRegistry()
    for family, stems in (("Georgia", ("gelasio",)),
                          ("Segoe UI", ("selawk", "selawik"))):
        for bold in (False, True):
            name = reg.resolve(family, bold=bold).name.lower()
            assert any(s in name for s in stems), (
                f"{family} bold={bold} resolved to {name!r} on Linux — "
                f"the bundled metric clone was not picked up")


def test_bundled_clone_files_exist_in_repo():
    """The vendored files themselves — pruning without them bricks Linux."""
    from deckengine.core.fonts import _BUNDLED_DIR
    for fname in ("Gelasio-Regular.ttf", "Gelasio-Bold.ttf",
                  "selawk.ttf", "selawkb.ttf",
                  "Carlito-Regular.ttf", "Carlito-Bold.ttf",
                  "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"):
        assert (_BUNDLED_DIR / fname).is_file(), f"missing vendored {fname}"
