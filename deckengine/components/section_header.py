"""section_header — slide title block.

Title in the display face at 'title' size (ink), optional subtitle at 'small'
size (accent or muted ink), optional thin full-width rule spacing(0.5) below
the last line of text. Consulting convention: the rule separates the message
line from the exhibit body.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult
from ..core.fit_text import fit_text
from ..core.pptx_shapes import add_hline
from ..core.pptx_text import add_text_box, write_fit_result
from ..core.units import pt
from ..schema.components import SectionHeaderSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_TITLE_MIN = 14.0
_SUBTITLE_MIN = 7.5
_RULE_WEIGHT_PT = 0.75


@register("section_header")
class SectionHeader(Component):
    spec_model = SectionHeaderSpec

    # -- shared fit math (measure and render call the same functions) ------

    def _fit_title(self, data: SectionHeaderSpec, box: BBox,
                   ctx: RenderContext) -> FitResult:
        spans = parse_rich(data.title, base_color_role="ink")
        return fit_text(spans, box, ctx.font("display"),
                        max_size=ctx.size("title"), min_size=_TITLE_MIN,
                        measurer=ctx.measurer)

    def _subtitle_role(self, data: SectionHeaderSpec) -> str:
        return "accent" if data.accent_subtitle else "ink_muted"

    def _fit_subtitle(self, data: SectionHeaderSpec, box: BBox,
                      ctx: RenderContext) -> FitResult:
        spans = parse_rich(data.subtitle or "",
                           base_color_role=self._subtitle_role(data))
        return fit_text(spans, box, ctx.font("body"),
                        max_size=ctx.size("small"), min_size=_SUBTITLE_MIN,
                        measurer=ctx.measurer)

    # -- contract -----------------------------------------------------------

    def measure(self, data: SectionHeaderSpec, width: int,
                ctx: RenderContext) -> int:
        probe = BBox(0, 0, width, 10_000_000)
        h = self._fit_title(data, probe, ctx).height_emu
        if data.subtitle:
            h += ctx.theme.spacing(0.3)
            h += self._fit_subtitle(data, probe, ctx).height_emu
        if data.rule:
            h += ctx.theme.spacing(0.5) + pt(_RULE_WEIGHT_PT)
        return h

    def render(self, slide, data: SectionHeaderSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        y = bbox.y
        title_fit = self._fit_title(
            data, BBox(bbox.x, y, bbox.w, max(0, bbox.bottom - y)), ctx)
        if title_fit.truncated:
            ctx.report.truncated(f"section_header title: {data.title[:40]!r}")
        box = add_text_box(slide, BBox(bbox.x, y, bbox.w, title_fit.height_emu))
        write_fit_result(box.text_frame, title_fit, ctx.theme,
                         family=ctx.font("display"), default_color_role="ink")
        y += title_fit.height_emu

        if data.subtitle:
            y += ctx.theme.spacing(0.3)
            sub_fit = self._fit_subtitle(
                data, BBox(bbox.x, y, bbox.w, max(0, bbox.bottom - y)), ctx)
            if sub_fit.truncated:
                ctx.report.truncated(
                    f"section_header subtitle: {data.subtitle[:40]!r}")
            box = add_text_box(slide,
                               BBox(bbox.x, y, bbox.w, sub_fit.height_emu))
            write_fit_result(box.text_frame, sub_fit, ctx.theme,
                             family=ctx.font("body"),
                             default_color_role=self._subtitle_role(data))
            y += sub_fit.height_emu

        if data.rule:
            y += ctx.theme.spacing(0.5)
            add_hline(slide, bbox.x, y, bbox.w, ctx.theme,
                      role="grid", weight_pt=_RULE_WEIGHT_PT)
            y += pt(_RULE_WEIGHT_PT)
        return y - bbox.y
