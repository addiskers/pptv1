"""Cycle-ring renderer — PIL-drawn flywheel segments (the icons.py move).

A ring of N arc-arrow segments with clockwise arrowheads, one segment
optionally accented. Drawn at 4x and downsampled, cached per
(n, colors, highlight, px) under assets/cache_rings/ (gitignored,
regenerated on demand). Labels are NOT drawn here — the component places
measured pptx text boxes at segment centroids, per the layout contract.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

CACHE_DIR = Path(__file__).resolve().parents[2] / "assets" / "cache_rings"

_GAP_DEG = 14          # gap between segments (arrowhead lives in it)
_THICK_FRAC = 0.16     # ring thickness as a fraction of the diameter


def _rgba(hex_color: str) -> tuple[int, int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def get_cycle_ring(n: int, base_hex: str, accent_hex: str,
                   highlight: int | None, px: int = 640) -> Path:
    """PNG of an n-segment clockwise ring; segment `highlight` accented."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / (f"ring{n}_{base_hex.lower()}_{accent_hex.lower()}"
                       f"_h{'x' if highlight is None else highlight}"
                       f"_{px}.png")
    if out.is_file():
        return out
    s = px * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    thick = round(s * _THICK_FRAC)
    margin = round(thick * 0.7)
    cx = cy = s / 2
    r_mid = (s - 2 * margin - thick) / 2
    r_out = r_mid + thick / 2
    r_in = r_mid - thick / 2
    seg = 360.0 / n
    lead = _GAP_DEG * 0.75    # how far the tip reaches into the gap

    def pt(radius: float, deg: float) -> tuple[float, float]:
        a = math.radians(deg)
        return cx + radius * math.cos(a), cy + radius * math.sin(a)

    for i in range(n):
        color = _rgba(accent_hex if i == highlight else base_hex)
        # clockwise from 12 o'clock; flat radial start, pointed end —
        # one annular wedge polygon with an integrated arrowhead
        a0 = -90 + i * seg + _GAP_DEG / 2
        a1 = -90 + (i + 1) * seg - _GAP_DEG / 2
        steps = max(6, int((a1 - a0) / 3))
        outer = [pt(r_out, a0 + (a1 - a0) * k / steps)
                 for k in range(steps + 1)]
        inner = [pt(r_in, a1 - (a1 - a0) * k / steps)
                 for k in range(steps + 1)]
        tip = pt(r_mid, a1 + lead)
        d.polygon(outer + [tip] + inner, fill=color)
    img = img.resize((px, px), Image.LANCZOS)
    img.save(out)
    return out
