"""Asset resolution + watermark processing (Q3).

Images NEVER block a render: a missing asset resolves to None and the caller
draws a placeholder / skips with a warning.
"""
from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
_FADE_CACHE = ASSETS_DIR / "cache_faded"


def resolve_asset(src: str) -> Path | None:
    """Absolute path, or a name under assets/ or assets/samples/."""
    p = Path(src)
    candidates = [p] if p.is_absolute() else [ASSETS_DIR / src,
                                              ASSETS_DIR / "samples" / src]
    for c in candidates:
        if c.is_file():
            return c
    return None


def faded_copy(path: Path, opacity: float) -> Path:
    """Cached RGBA copy with alpha scaled to `opacity` — the watermark look.
    PowerPoint picture transparency needs XML surgery; baking the alpha into
    the PNG is deterministic and edit-safe."""
    from PIL import Image
    _FADE_CACHE.mkdir(parents=True, exist_ok=True)
    key = int(round(opacity * 100))
    out = _FADE_CACHE / f"{path.stem}_a{key}.png"
    if out.is_file() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    img = Image.open(path).convert("RGBA")
    alpha = img.getchannel("A").point(lambda a: int(a * opacity))
    img.putalpha(alpha)
    img.save(out)
    return out


def image_size(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size
