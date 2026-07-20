"""Table pagination: split data_deep_dive slides whose table exceeds the page.

Splits ONLY at row-group boundaries (a group larger than a page splits inside,
repeating the group label). Continuation slides repeat the header + legend and
suffix the title with "(cont'd)"; the insights sidebar rides on the first slide
only.
"""
from __future__ import annotations

from ..components.base import RenderContext, get_component
from ..core.units import inch
from ..schema.components import DataGroupSpec, DataTableSpec
from ..schema.slide_types import DataDeepDiveSpec
from .zones import standard_zones, with_sidebar

_SAFETY = 0.94  # never plan the last row flush against the zone edge


def _capacity_rows(spec: DataDeepDiveSpec, ctx: RenderContext) -> int:
    """How many data rows fit on one slide of this spec's geometry."""
    z = standard_zones(title_h=0.85 if not spec.subtitle else 1.1)
    body = z["body"]
    main = with_sidebar(body, side_frac=0.26)["main"] if spec.insights else body
    dt = get_component("data_table")
    header_h = dt._header_h(dt._header_fits(spec.table,
                                            dt._col_widths(spec.table, main.w),
                                            ctx), ctx)
    row_h = dt._row_h(ctx)
    avail = main.h
    if spec.legend:
        avail -= get_component("legend_row").measure(spec.legend, main.w, ctx)
        avail -= ctx.theme.spacing(0.6)
    if spec.footnote:
        avail -= inch(0.3) + ctx.theme.spacing(0.6)
    avail -= ctx.theme.spacing(0.8)  # gap before table
    return max(3, int((avail * _SAFETY - header_h) // row_h))


def paginate_deep_dive(spec: DataDeepDiveSpec,
                       ctx: RenderContext) -> list[DataDeepDiveSpec]:
    total_rows = sum(len(g.rows) for g in spec.table.groups)
    cap = _capacity_rows(spec, ctx)
    if total_rows <= cap:
        return [spec]

    # partition groups into pages at group boundaries
    pages: list[list[DataGroupSpec]] = [[]]
    used = 0
    for group in spec.table.groups:
        rows = group.rows
        while rows:
            room = cap - used
            if room <= 0:
                pages.append([])
                used = 0
                room = cap
            take = rows[:room]
            # a group split across pages repeats its label on each page
            pages[-1].append(DataGroupSpec(label=group.label, rows=list(take)))
            used += len(take)
            rows = rows[len(take):]

    out: list[DataDeepDiveSpec] = []
    for i, groups in enumerate(pages):
        table = spec.table.model_copy(update={"groups": groups})
        out.append(spec.model_copy(update={
            "table": table,
            "title": spec.title if i == 0 else f"{spec.title} *(cont'd)*",
            "insights": spec.insights if i == 0 else [],
            "insights_heading": spec.insights_heading if i == 0 else None,
        }))
    ctx.report.splits.append(
        f"data_deep_dive split into {len(pages)} slides ({total_rows} rows, "
        f"capacity {cap}/slide)")
    return out
