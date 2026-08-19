"""Monochrome icon set: real Lucide glyphs, PIL drawers as fallback.

Preferred source is assets/icons/lucide/*.png — professional stroke icons
(Lucide, ISC license) pre-rasterized to 512px black-on-transparent alpha
masks and tinted to any theme role at request time. Icons missing a mask
fall back to the original hand-drawn PIL glyphs, so the set degrades
gracefully offline. Everything is cached per (name, color, size).
get_icon_tile wraps any glyph in a rounded-square color tile.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

CACHE_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons" / "cache"
LUCIDE_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons" / "lucide"

ICON_NAMES = ("person", "people", "money", "growth", "chart", "leaf",
              "building", "target", "globe", "bulb", "shield", "clock",
              "gear", "handshake", "truck", "factory", "document",
              "calendar", "warning", "check", "refresh", "scale", "award",
              "flag", "pin", "cart", "drop", "rocket", "network", "lock")


def _lucide_mask(name: str) -> Path | None:
    p = LUCIDE_DIR / f"{name}.png"
    return p if p.is_file() else None


def _tinted_glyph(mask_path: Path, color: tuple, px: int) -> Image.Image:
    """Tint a pre-rasterized black-on-transparent mask via its alpha."""
    with Image.open(mask_path) as m:
        alpha = m.convert("RGBA").getchannel("A").resize(
            (px, px), Image.LANCZOS)
    glyph = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    glyph.paste(Image.new("RGBA", (px, px), color), mask=alpha)
    return glyph


def get_icon(name: str, hex_color: str, px: int = 128) -> Path:
    if name not in ICON_NAMES:
        raise KeyError(f"unknown icon {name!r}; choose from {ICON_NAMES}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mask = _lucide_mask(name)
    tag = "_lc" if mask else ""
    out = CACHE_DIR / f"{name}_{hex_color.lower()}_{px}{tag}.png"
    if out.is_file():
        return out
    color = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    if mask:
        _tinted_glyph(mask, color, px).save(out)
        return out
    s = px * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(3, round(s * 0.075))  # stroke width
    _DRAWERS[name](d, s, color, w)
    img = img.resize((px, px), Image.LANCZOS)
    img.save(out)
    return out


def get_icon_tile(name: str, fg_hex: str, bg_hex: str, px: int = 128,
                  radius_frac: float = 0.22) -> Path:
    if name not in ICON_NAMES:
        raise KeyError(f"unknown icon {name!r}; choose from {ICON_NAMES}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mask = _lucide_mask(name)
    tag = "_lc" if mask else ""
    out = (CACHE_DIR
           / (f"tile_{name}_{fg_hex.lower()}_{bg_hex.lower()}_{px}"
              f"_r{radius_frac:g}{tag}.png"))
    if out.is_file():
        return out
    s = px * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = tuple(int(bg_hex[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    d.rounded_rectangle([0, 0, s - 1, s - 1],
                        radius=round(s * radius_frac), fill=bg)
    inset = round(s * 0.24)
    gs = s - 2 * inset
    fg = tuple(int(fg_hex[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    if mask:
        glyph = _tinted_glyph(mask, fg, gs)
    else:
        glyph = Image.new("RGBA", (gs, gs), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glyph)
        w = max(3, round(gs * 0.075))
        _DRAWERS[name](gd, gs, fg, w)
    img.alpha_composite(glyph, (inset, inset))
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


def _poly(d, s, pts, color):
    d.polygon([(s * x, s * y) for x, y in pts], fill=color)


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


def _gear(d, s, c, w):
    _ell(d, s, 0.5, 0.5, 0.26, c, w)
    _ell(d, s, 0.5, 0.5, 0.1, c, w)
    for k in range(8):
        a = math.radians(k * 45)
        _line(d, s, [(0.5 + 0.26 * math.cos(a), 0.5 + 0.26 * math.sin(a)),
                     (0.5 + 0.38 * math.cos(a), 0.5 + 0.38 * math.sin(a))],
              c, w)


def _handshake(d, s, c, w):
    _line(d, s, [(0.06, 0.38), (0.26, 0.46), (0.4, 0.53)], c, w)
    _line(d, s, [(0.94, 0.38), (0.74, 0.46), (0.6, 0.53)], c, w)
    _poly(d, s, [(0.5, 0.44), (0.63, 0.53), (0.5, 0.62), (0.37, 0.53)], c)


def _truck(d, s, c, w):
    d.rectangle([s * 0.08, s * 0.3, s * 0.58, s * 0.68], outline=c, width=w)
    _line(d, s, [(0.58, 0.4), (0.76, 0.4), (0.88, 0.54), (0.88, 0.68),
                 (0.58, 0.68)], c, w)
    _ell(d, s, 0.26, 0.76, 0.07, c, w)
    _ell(d, s, 0.72, 0.76, 0.07, c, w)


def _factory(d, s, c, w):
    _line(d, s, [(0.1, 0.84), (0.1, 0.48), (0.32, 0.62), (0.32, 0.48),
                 (0.54, 0.62), (0.54, 0.48), (0.76, 0.62), (0.76, 0.84),
                 (0.1, 0.84)], c, w)
    d.rectangle([s * 0.6, s * 0.22, s * 0.72, s * 0.54], outline=c, width=w)
    for xx in (0.18, 0.36):
        d.rectangle([s * xx, s * 0.68, s * (xx + 0.1), s * 0.76], fill=c)


def _document(d, s, c, w):
    _line(d, s, [(0.3, 0.14), (0.3, 0.86), (0.7, 0.86), (0.7, 0.3),
                 (0.54, 0.14), (0.3, 0.14)], c, w)
    _line(d, s, [(0.54, 0.14), (0.54, 0.3), (0.7, 0.3)], c,
          max(2, w // 2))
    for yy in (0.46, 0.58, 0.7):
        _line(d, s, [(0.38, yy), (0.62, yy)], c, max(2, w // 2))


def _calendar(d, s, c, w):
    d.rectangle([s * 0.16, s * 0.22, s * 0.84, s * 0.84], outline=c,
                width=w)
    _line(d, s, [(0.16, 0.4), (0.84, 0.4)], c, w)
    _line(d, s, [(0.34, 0.12), (0.34, 0.28)], c, w)
    _line(d, s, [(0.66, 0.12), (0.66, 0.28)], c, w)
    for yy in (0.5, 0.64):
        for xx in (0.32, 0.56):
            d.rectangle([s * xx, s * yy, s * (xx + 0.1), s * (yy + 0.08)],
                        fill=c)


def _warning(d, s, c, w):
    _line(d, s, [(0.5, 0.14), (0.88, 0.8), (0.12, 0.8), (0.5, 0.14)], c, w)
    _line(d, s, [(0.5, 0.38), (0.5, 0.58)], c, w)
    _ell(d, s, 0.5, 0.68, 0.035, c, w, fill=True)


def _check(d, s, c, w):
    _ell(d, s, 0.5, 0.5, 0.36, c, w)
    _line(d, s, [(0.32, 0.52), (0.45, 0.65), (0.7, 0.37)], c, w)


def _refresh(d, s, c, w):
    box = [s * 0.16, s * 0.16, s * 0.84, s * 0.84]
    d.arc(box, 200, 340, fill=c, width=w)
    d.arc(box, 20, 160, fill=c, width=w)
    _poly(d, s, [(0.86, 0.48), (0.88, 0.36), (0.76, 0.4)], c)
    _poly(d, s, [(0.14, 0.52), (0.12, 0.64), (0.24, 0.6)], c)


def _scale(d, s, c, w):
    _line(d, s, [(0.5, 0.16), (0.5, 0.78)], c, w)
    _line(d, s, [(0.34, 0.84), (0.66, 0.84)], c, w)
    _line(d, s, [(0.2, 0.28), (0.8, 0.28)], c, w)
    for cx in (0.2, 0.8):
        _line(d, s, [(cx - 0.13, 0.42), (cx, 0.28), (cx + 0.13, 0.42)], c,
              max(2, w // 2))
        d.arc([s * (cx - 0.13), s * 0.29, s * (cx + 0.13), s * 0.55],
              0, 180, fill=c, width=w)


def _award(d, s, c, w):
    _ell(d, s, 0.5, 0.38, 0.2, c, w)
    _ell(d, s, 0.5, 0.38, 0.07, c, w, fill=True)
    _line(d, s, [(0.42, 0.55), (0.34, 0.86), (0.5, 0.76), (0.66, 0.86),
                 (0.58, 0.55)], c, w)


def _flag(d, s, c, w):
    _line(d, s, [(0.26, 0.12), (0.26, 0.88)], c, w)
    _line(d, s, [(0.26, 0.18), (0.78, 0.18), (0.66, 0.33), (0.78, 0.48),
                 (0.26, 0.48)], c, w)


def _pin(d, s, c, w):
    d.arc([s * 0.26, s * 0.14, s * 0.74, s * 0.62], 135, 45, fill=c,
          width=w)
    _line(d, s, [(0.33, 0.55), (0.5, 0.88)], c, w)
    _line(d, s, [(0.67, 0.55), (0.5, 0.88)], c, w)
    _ell(d, s, 0.5, 0.38, 0.05, c, w, fill=True)


def _cart(d, s, c, w):
    _line(d, s, [(0.1, 0.2), (0.24, 0.2), (0.36, 0.62), (0.76, 0.62),
                 (0.84, 0.32), (0.28, 0.32)], c, w)
    _ell(d, s, 0.42, 0.76, 0.055, c, w, fill=True)
    _ell(d, s, 0.7, 0.76, 0.055, c, w, fill=True)


def _drop(d, s, c, w):
    d.arc([s * 0.24, s * 0.32, s * 0.76, s * 0.84], 330, 210, fill=c,
          width=w)
    _line(d, s, [(0.275, 0.45), (0.5, 0.12)], c, w)
    _line(d, s, [(0.725, 0.45), (0.5, 0.12)], c, w)


def _rocket(d, s, c, w):
    _line(d, s, [(0.5, 0.08), (0.66, 0.32), (0.66, 0.62), (0.34, 0.62),
                 (0.34, 0.32), (0.5, 0.08)], c, w)
    _ell(d, s, 0.5, 0.38, 0.07, c, w)
    _line(d, s, [(0.34, 0.5), (0.2, 0.74), (0.34, 0.68)], c, w)
    _line(d, s, [(0.66, 0.5), (0.8, 0.74), (0.66, 0.68)], c, w)
    _line(d, s, [(0.5, 0.7), (0.5, 0.88)], c, w)


def _network(d, s, c, w):
    for nx, ny in ((0.5, 0.16), (0.16, 0.74), (0.84, 0.74)):
        _line(d, s, [(0.5, 0.52), (nx, ny)], c, max(2, w // 2))
        _ell(d, s, nx, ny, 0.09, c, w, fill=True)
    _ell(d, s, 0.5, 0.52, 0.11, c, w, fill=True)


def _lock(d, s, c, w):
    d.rectangle([s * 0.24, s * 0.44, s * 0.76, s * 0.86], outline=c,
                width=w)
    d.arc([s * 0.32, s * 0.16, s * 0.68, s * 0.72], 180, 360, fill=c,
          width=w)
    _ell(d, s, 0.5, 0.6, 0.045, c, w, fill=True)
    _line(d, s, [(0.5, 0.62), (0.5, 0.72)], c, max(2, w // 2))


_DRAWERS = {"person": _person, "people": _people, "money": _money,
            "growth": _growth, "chart": _chart, "leaf": _leaf,
            "building": _building, "target": _target, "globe": _globe,
            "bulb": _bulb, "shield": _shield, "clock": _clock,
            "gear": _gear, "handshake": _handshake, "truck": _truck,
            "factory": _factory, "document": _document,
            "calendar": _calendar, "warning": _warning, "check": _check,
            "refresh": _refresh, "scale": _scale, "award": _award,
            "flag": _flag, "pin": _pin, "cart": _cart, "drop": _drop,
            "rocket": _rocket, "network": _network, "lock": _lock}
