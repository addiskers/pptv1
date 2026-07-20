"""Programmatic monochrome icon set.

Icons are drawn with PIL at request time and cached per (name, color, size) —
no licensed assets, no emoji tell, recolorable to any theme role. Drawn at 4x
and downsampled for clean anti-aliasing.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CACHE_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons" / "cache"

ICON_NAMES = ("person", "people", "money", "growth", "chart", "leaf",
              "building", "target", "globe", "bulb", "shield", "clock")


def get_icon(name: str, hex_color: str, px: int = 128) -> Path:
    if name not in ICON_NAMES:
        raise KeyError(f"unknown icon {name!r}; choose from {ICON_NAMES}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"{name}_{hex_color.lower()}_{px}.png"
    if out.is_file():
        return out
    s = px * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    w = max(3, round(s * 0.075))  # stroke width
    _DRAWERS[name](d, s, color, w)
    img = img.resize((px, px), Image.LANCZOS)
    img.save(out)
    return out


def _ell(d, s, cx, cy, r, color, w, fill=False):
    box = [s * (cx - r), s * (cy - r), s * (cx + r), s * (cy + r)]
    if fill:
        d.ellipse(box, fill=color)
    else:
        d.ellipse(box, outline=color, width=w)


def _line(d, s, pts, color, w):
    d.line([(s * x, s * y) for x, y in pts], fill=color, width=w,
           joint="curve")


def _person(d, s, c, w):
    _ell(d, s, 0.5, 0.32, 0.15, c, w)
    d.arc([s * 0.2, s * 0.52, s * 0.8, s * 1.12], 180, 360, fill=c, width=w)


def _people(d, s, c, w):
    _ell(d, s, 0.36, 0.32, 0.13, c, w)
    d.arc([s * 0.1, s * 0.5, s * 0.62, s * 1.02], 180, 360, fill=c, width=w)
    _ell(d, s, 0.68, 0.36, 0.11, c, w)
    d.arc([s * 0.46, s * 0.54, s * 0.9, s * 0.98], 180, 360, fill=c, width=w)


def _money(d, s, c, w):
    _ell(d, s, 0.5, 0.5, 0.36, c, w)
    _line(d, s, [(0.58, 0.36), (0.46, 0.36), (0.42, 0.44), (0.5, 0.5),
                 (0.58, 0.56), (0.54, 0.64), (0.42, 0.64)], c, w)
    _line(d, s, [(0.5, 0.28), (0.5, 0.72)], c, max(2, w // 2))


def _growth(d, s, c, w):
    _line(d, s, [(0.14, 0.78), (0.4, 0.52), (0.55, 0.64), (0.84, 0.3)], c, w)
    _line(d, s, [(0.66, 0.28), (0.86, 0.28), (0.86, 0.48)], c, w)


def _chart(d, s, c, w):
    for x, h in ((0.24, 0.3), (0.47, 0.5), (0.7, 0.68)):
        d.rectangle([s * x, s * (0.85 - h), s * (x + 0.14), s * 0.85],
                    outline=c, width=w)


def _leaf(d, s, c, w):
    d.arc([s * 0.2, s * 0.15, s * 1.0, s * 0.95], 90, 200, fill=c, width=w)
    d.arc([s * 0.05, s * 0.2, s * 0.75, s * 0.9], 270, 30, fill=c, width=w)
    _line(d, s, [(0.32, 0.85), (0.62, 0.42)], c, w)


def _building(d, s, c, w):
    d.rectangle([s * 0.24, s * 0.18, s * 0.76, s * 0.85], outline=c, width=w)
    for yy in (0.32, 0.48, 0.64):
        for xx in (0.35, 0.55):
            d.rectangle([s * xx, s * yy, s * (xx + 0.1), s * (yy + 0.08)],
                        fill=c)


def _target(d, s, c, w):
    _ell(d, s, 0.5, 0.5, 0.36, c, w)
    _ell(d, s, 0.5, 0.5, 0.21, c, w)
    _ell(d, s, 0.5, 0.5, 0.07, c, w, fill=True)


def _globe(d, s, c, w):
    _ell(d, s, 0.5, 0.5, 0.36, c, w)
    d.ellipse([s * 0.34, s * 0.14, s * 0.66, s * 0.86], outline=c, width=w)
    _line(d, s, [(0.14, 0.5), (0.86, 0.5)], c, w)


def _bulb(d, s, c, w):
    _ell(d, s, 0.5, 0.42, 0.24, c, w)
    d.rectangle([s * 0.42, s * 0.68, s * 0.58, s * 0.8], outline=c, width=w)
    _line(d, s, [(0.44, 0.87), (0.56, 0.87)], c, w)


def _shield(d, s, c, w):
    _line(d, s, [(0.5, 0.14), (0.8, 0.26), (0.8, 0.52)], c, w)
    d.arc([s * 0.2, s * 0.3, s * 0.8, s * 0.9], 0, 180, fill=c, width=w)
    _line(d, s, [(0.5, 0.14), (0.2, 0.26), (0.2, 0.52)], c, w)
    _line(d, s, [(0.38, 0.5), (0.48, 0.62), (0.66, 0.38)], c, w)


def _clock(d, s, c, w):
    _ell(d, s, 0.5, 0.5, 0.36, c, w)
    _line(d, s, [(0.5, 0.3), (0.5, 0.52), (0.66, 0.6)], c, w)


_DRAWERS = {"person": _person, "people": _people, "money": _money,
            "growth": _growth, "chart": _chart, "leaf": _leaf,
            "building": _building, "target": _target, "globe": _globe,
            "bulb": _bulb, "shield": _shield, "clock": _clock}
