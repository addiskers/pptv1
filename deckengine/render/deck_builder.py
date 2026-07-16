"""DeckSpec -> .pptx. The single entry point for rendering."""
from __future__ import annotations

import logging
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from ..components.base import BuildReport, RenderContext
from ..core.bbox import BBox
from ..core.fit_text import Span, TextMeasurer
from ..core.fonts import default_registry
from ..core.pptx_shapes import add_hline
from ..core.pptx_text import add_text_box, write_spans_paragraph
from ..core.theme import load_theme
from ..core.units import SLIDE_H_16_9, SLIDE_W_16_9, inch
from ..schema.slide_types import DeckSpec
# importing these modules registers all components / assemblers
from .. import components as _components  # noqa: F401
from ..slides import base as slide_base
from .. import slides as _slides  # noqa: F401

log = logging.getLogger("deckengine")


def build_deck(spec: DeckSpec, out_path: str | Path) -> BuildReport:
    theme = load_theme(spec.theme)
    default_registry().validate_theme(theme)  # fail loudly before drawing anything
    report = BuildReport()
    ctx = RenderContext(theme=theme, measurer=TextMeasurer(), report=report)

    prs = Presentation()
    prs.slide_width = Emu(SLIDE_W_16_9)
    prs.slide_height = Emu(SLIDE_H_16_9)
    blank = prs.slide_layouts[6]

    for i, slide_spec in enumerate(spec.slides, start=1):
        slide = prs.slides.add_slide(blank)
        try:
            slide_base.get_assembler(slide_spec.slide_type).assemble(
                slide, slide_spec, ctx)
        except Exception:
            log.exception("slide %d (%s) failed", i, slide_spec.slide_type)
            raise
        if slide_spec.slide_type not in ("title", "section_divider"):
            _footer(slide, spec, i, ctx)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    log.info("wrote %s (%d slides, %d warnings)", out_path, len(spec.slides),
             len(report.warnings))
    return report


def _footer(slide, spec: DeckSpec, page: int, ctx: RenderContext) -> None:
    y = SLIDE_H_16_9 - inch(0.42)
    x0, x1 = inch(0.45), SLIDE_W_16_9 - inch(0.45)
    add_hline(slide, x0, y, x1 - x0, ctx.theme, role="grid", weight_pt=1.0)
    size = ctx.theme.size_micro
    ty = y + inch(0.07)
    if spec.meta.date:
        b = add_text_box(slide, BBox(x0, ty, inch(2.0), inch(0.25)))
        write_spans_paragraph(b.text_frame, [Span(spec.meta.date)], size,
                              ctx.theme, family=ctx.font("body"),
                              default_color_role="ink_muted")
    if spec.meta.confidentiality:
        b = add_text_box(slide, BBox(SLIDE_W_16_9 // 2 - inch(2), ty, inch(4),
                                     inch(0.25)), align="center")
        write_spans_paragraph(b.text_frame, [Span(spec.meta.confidentiality)],
                              size, ctx.theme, family=ctx.font("body"),
                              align="center", default_color_role="ink_muted")
    right_bits = " ".join(b for b in (spec.meta.footer_org, str(page)) if b)
    if right_bits:
        b = add_text_box(slide, BBox(x1 - inch(3), ty, inch(3), inch(0.25)),
                         align="right")
        write_spans_paragraph(b.text_frame, [Span(right_bits)], size, ctx.theme,
                              family=ctx.font("body"), align="right",
                              default_color_role="ink_muted")
