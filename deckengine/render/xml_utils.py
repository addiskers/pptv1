"""Raw OOXML helpers for effects python-pptx doesn't expose cleanly.

Everything here is deliberately isolated and commented — the rest of the engine
uses python-pptx's API. Only reach for these when there is no API path.
"""
from __future__ import annotations

from pptx.oxml.ns import qn


def add_soft_shadow(shape, *, blur_emu: int = 40000, dist_emu: int = 24000,
                    direction: int = 5400000, alpha_pct: int = 62,
                    color: str = "1A1A1A") -> None:
    """Attach a subtle outer drop-shadow to an autoshape.

    Gives white content-cards the 'floating on canvas' depth of hand-built
    consulting decks. python-pptx has no shadow-build API (only shadow.inherit),
    so we insert <a:effectLst><a:outerShdw> into spPr directly.

    direction: 5400000 = 90° (down-right). alpha_pct: shadow opacity.
    """
    spPr = shape._element.spPr
    for old in spPr.findall(qn("a:effectLst")):
        spPr.remove(old)
    eff = spPr.makeelement(qn("a:effectLst"), {})
    shdw = eff.makeelement(qn("a:outerShdw"), {
        "blurRad": str(blur_emu), "dist": str(dist_emu),
        "dir": str(direction), "rotWithShape": "0"})
    clr = shdw.makeelement(qn("a:srgbClr"), {"val": color})
    alpha = clr.makeelement(qn("a:alpha"), {"val": str(alpha_pct * 1000)})
    clr.append(alpha)
    shdw.append(clr)
    eff.append(shdw)
    # effectLst must follow the fill/line group in spPr; append is schema-valid
    # because those precede it, and ln (if present) is already before this point
    spPr.append(eff)
