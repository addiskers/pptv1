"""Table pagination tests."""
from deckengine.components.base import BuildReport, RenderContext
from deckengine.core.fit_text import TextMeasurer
from deckengine.core.theme import load_theme
from deckengine.layout.pagination import paginate_deep_dive
from deckengine.schema.components import (DataColumnSpec, DataGroupSpec,
                                          DataTableSpec)
from deckengine.schema.slide_types import DataDeepDiveSpec
import deckengine.components  # noqa: F401


def make_ctx():
    return RenderContext(theme=load_theme("consulting_navy"),
                         measurer=TextMeasurer(), report=BuildReport())


def big_spec(n_rows_per_group=15, n_groups=3):
    return DataDeepDiveSpec(
        title="A very long benchmark of everything",
        table=DataTableSpec(
            columns=[DataColumnSpec(label="Group", frac=0.3),
                     DataColumnSpec(label="Item", frac=0.5),
                     DataColumnSpec(label="Score", frac=0.2,
                                    cell_kind="number")],
            groups=[DataGroupSpec(
                label=f"Group {g}",
                rows=[[f"item {g}.{r}", str(r)] for r in range(n_rows_per_group)])
                for g in range(n_groups)]))


def test_small_table_not_split():
    ctx = make_ctx()
    spec = big_spec(n_rows_per_group=3, n_groups=2)
    assert len(paginate_deep_dive(spec, ctx)) == 1


def test_45_row_table_splits_cleanly():
    ctx = make_ctx()
    spec = big_spec(n_rows_per_group=15, n_groups=3)  # 45 rows
    pages = paginate_deep_dive(spec, ctx)
    assert len(pages) >= 2
    # no rows lost, order preserved
    all_rows = [r for p in pages for g in p.table.groups for r in g.rows]
    orig_rows = [r for g in spec.table.groups for r in g.rows]
    assert all_rows == orig_rows
    # continuation styling
    assert "(cont'd)" in pages[1].title
    assert pages[1].insights == []
    assert ctx.report.splits
