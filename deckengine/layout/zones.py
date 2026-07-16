"""Named zone allocation over the slide BBox."""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.units import SLIDE_H_16_9, SLIDE_W_16_9, inch

SLIDE = BBox(0, 0, SLIDE_W_16_9, SLIDE_H_16_9)


def standard_zones(*, title_h: float = 1.0, footer_h: float = 0.45,
                   margin: float = 0.45) -> dict[str, BBox]:
    """title / body / footer with side margins (inches)."""
    content = SLIDE.inset(left=inch(margin), right=inch(margin),
                          top=inch(0.30), bottom=inch(0.12))
    title, rest = content.take_top(inch(title_h))
    footer, body = rest.take_bottom(inch(footer_h))
    return {"title": title, "body": body, "footer": footer}


def with_sidebar(body: BBox, *, side_frac: float = 0.22,
                 gap: float = 0.25, side: str = "right") -> dict[str, BBox]:
    g = inch(gap)
    if side == "right":
        main, sidebar = body.split_h(1 - side_frac, side_frac, gap=g)
    else:
        sidebar, main = body.split_h(side_frac, 1 - side_frac, gap=g)
    return {"main": main, "sidebar": sidebar}
