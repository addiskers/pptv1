"""Core primitive tests: units, bbox algebra, theme, fonts, fit_text."""
import pytest

from deckengine.core.bbox import BBox
from deckengine.core.fit_text import Span, TextMeasurer, fit_text
from deckengine.core.fonts import default_registry
from deckengine.core.theme import load_theme
from deckengine.core.units import EMU_PER_INCH, inch, pt


def test_units():
    assert inch(1) == EMU_PER_INCH
    assert pt(72) == EMU_PER_INCH


def test_bbox_split_h_absorbs_rounding():
    b = BBox(0, 0, 1000, 100)
    parts = b.split_h(1, 1, 1)
    assert sum(p.w for p in parts) == 1000
    assert parts[-1].right == 1000


def test_bbox_take_and_inset():
    b = BBox(0, 0, inch(10), inch(5))
    top, rest = b.take_top(inch(1))
    assert top.h == inch(1) and rest.y == inch(1) and rest.h == inch(4)
    inner = b.inset(inch(0.5))
    assert inner.x == inch(0.5) and inner.w == inch(9)


def test_bbox_cols_gap():
    b = BBox(0, 0, inch(12), inch(1))
    cols = b.cols(3, gap=inch(0.2))
    assert len(cols) == 3
    assert cols[1].x == cols[0].right + inch(0.2)
    assert cols[-1].right == b.right


def test_theme_roles_and_heatmap():
    t = load_theme("consulting_navy")
    assert t.color("primary") == "1F3864"
    assert t.color("LIV") == "7CB342"
    assert t.heatmap_color(0) == t.heatmap_scale[0]
    assert t.heatmap_color(100, 0, 100) == t.heatmap_scale[-1]
    # an invented role must never crash a render: fallback to ink + warn
    # (probes use has_color, which stays exact)
    assert t.color("nope") == t.color("ink")
    assert t.has_color("primary") and t.has_color("LIV")
    assert not t.has_color("nope")


def test_fonts_resolve_theme():
    reg = default_registry()
    t = load_theme("consulting_navy")
    reg.validate_theme(t)  # must not raise on this machine


class TestFitText:
    m = TextMeasurer()

    def test_known_width_sane(self):
        # 'iiii' must be much narrower than 'MMMM' (proportional metrics work)
        wi = self.m.width_pt("iiii", "Segoe UI", 10)
        wm = self.m.width_pt("MMMM", "Segoe UI", 10)
        assert wm > wi * 2

    def test_bold_wider(self):
        w = self.m.width_pt("Benchmark", "Segoe UI", 10)
        wb = self.m.width_pt("Benchmark", "Segoe UI", 10, bold=True)
        assert wb > w

    def test_wrap_never_exceeds_width(self):
        spans = [Span("The quick brown fox jumps over the lazy dog " * 4)]
        maxw = inch(2)
        lines = self.m.wrap(spans, "Segoe UI", 10, maxw)
        assert len(lines) > 1
        for ln in lines:
            assert ln.width_emu <= maxw

    def test_wrap_preserves_bold_spans(self):
        spans = [Span("normal text then "), Span("bold tail", bold=True)]
        lines = self.m.wrap(spans, "Segoe UI", 10, inch(5))
        flat = [s for ln in lines for s in ln.spans]
        assert any(s.bold for s in flat) and any(not s.bold for s in flat)

    def test_hard_newline(self):
        lines = self.m.wrap([Span("one\ntwo")], "Segoe UI", 10, inch(5))
        assert len(lines) == 2

    def test_giant_word_kept_whole_never_char_split(self):
        # a token wider than the line stays WHOLE on one over-wide line;
        # fit_text shrinks/ellipsizes — wrap never emits "Marke/t" fragments
        lines = self.m.wrap([Span("A" * 200)], "Segoe UI", 10, inch(1))
        assert len(lines) == 1
        assert lines[0].spans[0].text == "A" * 200

    def test_overlong_token_ellipsized_at_floor(self):
        word = "Supercalifragilisticexpialidocious"
        box = BBox(0, 0, inch(1), inch(1))
        fit = fit_text([Span(word)], box, "Segoe UI", max_size=12, min_size=8)
        assert fit.truncated
        txt = fit.lines[0].spans[0].text
        assert txt.endswith("…") and word.startswith(txt[:-1])
        assert all(ln.width_emu <= box.w for ln in fit.lines)

    def test_overlong_token_shrinks_to_fit_without_ellipsis(self):
        # wide box: shrinking alone rescues the long token — no truncation
        fit = fit_text([Span("Muskmelon-Watermelon")], BBox(0, 0, inch(2.1), inch(1)),
                       "Segoe UI", max_size=14, min_size=7)
        assert not fit.truncated
        assert fit.lines[0].spans[0].text == "Muskmelon-Watermelon"

    def test_empty(self):
        lines = self.m.wrap([Span("")], "Segoe UI", 10, inch(1))
        assert len(lines) == 1

    def test_devanagari_and_rupee_measure(self):
        w = self.m.width_pt("किसानों की आय ₹1,216", "Nirmala UI", 10)
        assert w > 0

    def test_fit_shrinks_then_truncates(self):
        spans = [Span("word " * 120)]
        small = BBox(0, 0, inch(2), inch(0.5))
        fit = fit_text(spans, small, "Segoe UI", max_size=12, min_size=8)
        assert fit.truncated
        assert fit.size_pt == 8
        assert fit.height_emu <= small.h
        assert fit.lines[-1].spans[-1].text.endswith("…")

    def test_fit_no_shrink_when_fits(self):
        fit = fit_text([Span("short")], BBox(0, 0, inch(5), inch(1)),
                       "Segoe UI", max_size=12, min_size=8)
        assert fit.size_pt == 12 and not fit.truncated


def test_rich_parse():
    from deckengine.schema.rich import parse_rich, plain
    spans = parse_rich("plain **bold** *ital* [[accent]]orange[[/]] end")
    assert [s.bold for s in spans] == [False, True, False, False, False, False, False]
    assert spans[5].color_role == "accent"
    assert any(s.italic for s in spans)
    assert plain("a **b** c") == "a b c"
