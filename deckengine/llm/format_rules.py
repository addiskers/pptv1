"""Format-selection brain: the chart is chosen by the CLAIM, not the data
(Zelazny). Pure rules — no I/O, no LLM calls.

Two signal sources feed an ordered rule table:
- the claim text: word-bounded regex lexicons (trend, ranking, ...)
- the fact-table shape: periods, shares, entities, negatives, targets

RULES is ordered SPECIFIC FIRST — the first rule whose detect() fires is
the format verdict. decision_table_text() renders the table for prompts;
check_outline_formats() turns type/claim mismatches into suggestions
(never blockers); check_slide_format() flags objective data-shape
violations phrased as repair instructions.

recommend_style() is the VARIANT TIER below the format verdict:
advisory ChartStyleSpec knobs (endpoint labels + CAGR chip, forecast
dashing, benchmark line, series highlight, 100% stacking, horizontal
bars) from the same signals. Boolean/literal knobs carry concrete
values; knobs whose value needs data the rules cannot see (the first
future category, the claim's subject series) carry guidance STRINGS.

v1 approximations (lexicons, not parses):
- 'growth mindset' fires the trend SIGNAL; the trend RULE stays quiet
  because the fact shape (n_periods >= 2) must corroborate the claim.
- criteria_count counts known criterion nouns after a scoring cue, min 1.
- hero_number = hero verb followed by a number, or a claim whose single
  number carries a currency symbol or magnitude suffix.
- bridge fires on any 'from X to Y ... driven/explained/built' phrasing,
  which can shadow trend claims that also name their drivers.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from ..schema.rich import plain
from ..schema.slide_types import ChartSlideSpec, CustomLayoutSpec
from .facts import FactTable
from .story import TITLE_EXEMPT

# -- claim lexicons (case-insensitive, word-bounded) -------------------------

_TREND = re.compile(
    r"\b(?:grew|grow(?:s|ing|th)|rose|fell|dropped|declin\w*"
    r"|doubl(?:ed|ing)|tripl(?:ed|ing)"
    r"|trajectory|cagr|forecasts?|peaked|year[-\s]on[-\s]year"
    r"|(?:since|from)\s+(?:19|20)\d{2}|by\s+20\d{2}"
    r"|over\s+the\s+(?:last|next))\b", re.I)
_RANKING = re.compile(
    r"\b(?:leads?|leaders?|largest|top|ranks?|number\s+one|dominates?"
    r"|outperforms?|ahead\s+of|biggest|lags?)\b|#\d", re.I)
_COMPOSITION = re.compile(
    r"\b(?:share|mix|split|composition|accounts?\s+for|breakdown)\b"
    r"|\bof\s+(?:the|total)\s+market\b", re.I)
_DISTRIBUTION = re.compile(
    r"\b(?:ranges?\s+from|concentrated|most\s+fall|spread\s+across"
    r"|clustered\s+around)\b", re.I)
_CORRELATION = re.compile(
    r"\b(?:correlates?|driven\s+by|increases\s+with|scales\s+with"
    r"|tracks)\b", re.I)
_TWO_AXIS = re.compile(
    # 'positioning' only: bare 'position' is a standing claim ("a 12% share
    # position", "#3 position") and would hijack the first rule in RULES.
    r"\b(?:2x2|matrix|quadrants?|positioning|prioriti[sz]\w*"
    r"|attractiveness)\b"
    r"|\b(?:impact|effort|risk|value|feasibility)"
    r"\s+(?:vs\.?|versus|against)\b", re.I)
_FUNNEL = re.compile(
    r"\b(?:funnels?|pipelines?|conversion|drop-?offs?)\b"
    r"|\bleads?\s+to\s+(?:bookings|sales|signed)\b", re.I)
_PROCESS = re.compile(
    r"\b(?:how\s+we|steps?|phases?|approach|methodology|playbook)\b", re.I)
_ROADMAP = re.compile(
    r"\b(?:roadmaps?|timelines?|milestones?|rollout|sequenc\w*)\b"
    r"|\bby\s+q[1-4]\b", re.I)
_BRIDGE = re.compile(
    r"\b(?:bridge|walks?\s+from|waterfall)\b"
    r"|\bfrom\b.{1,60}?\bto\b.{1,80}?\b(?:driven|explained|built)\b",
    re.I | re.S)
_HERO_VERB = re.compile(
    r"\b(?:reach(?:es|ed)?|hits?|worth|totals?)\s+"
    r"(?:(?:a|an|some|record)\s+)*[$€£]?\d", re.I)
_MAGNITUDE = re.compile(
    r"[$€£]\s?\d"
    r"|\d[\d,.]*(?:\s*(?:billion|million|trillion)|[bmtk]n?)\b", re.I)
_NUM_TOKEN = re.compile(r"\d[\d,]*\.?\d*")

_OPT_NUM = re.compile(
    r"\b(two|three|four|2|3|4)\s+(?:options?|routes?|models?|scenarios?"
    r"|paths?|entry\s+modes?)\b", re.I)
_OPT_LETTER = re.compile(r"\b[Oo]ptions?\s+[A-D]\b")
_LETTER = re.compile(r"\b([A-D])\b")     # deliberately case-sensitive
_WORD_NUM = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
_CRITERIA_CUE = re.compile(
    r"\b(?:criteri(?:a|on)|scored?|scoring|weighted|assess\w*"
    r"|trade-?offs?|benchmark\w*)\b", re.I)
_CRITERION_NOUNS = (
    "cost", "price", "risk", "speed", "time", "quality", "feasibility",
    "impact", "effort", "value", "scalability", "reach", "control",
    "flexibility", "margin", "fit")

# -- fact-shape lexicons ------------------------------------------------------

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ROW_ID = re.compile(r"^row(\d+)_")
_NEG_DISPLAY = re.compile(r"^-\d|\(\s*\$?\d[\d,.]*\s*\)")


@dataclass(frozen=True)
class Signals:
    """What the claim asserts + what shape the data has."""
    trend: bool = False
    ranking: bool = False
    composition: bool = False
    distribution: bool = False
    correlation: bool = False
    two_axis: bool = False
    funnel: bool = False
    process: bool = False
    roadmap: bool = False
    hero_number: bool = False
    bridge: bool = False
    crosses_zero: bool = False
    has_targets: bool = False
    option_count: int = 0
    criteria_count: int = 0
    n_periods: int = 0
    share_facts: int = 0
    entity_count: int = 0


def _option_count(text: str) -> int:
    m = _OPT_NUM.search(text)
    if m:
        return _WORD_NUM[m.group(1).lower()]
    if _OPT_LETTER.search(text):
        return max(2, len(set(_LETTER.findall(text))))
    return 0


def _criteria_count(text: str) -> int:
    """0 without a scoring cue; else distinct known criterion nouns, min 1
    (v1: a fixed noun list, not a parse)."""
    if not _CRITERIA_CUE.search(text):
        return 0
    nouns = {n for n in _CRITERION_NOUNS
             if re.search(rf"\b{n}\b", text, re.I)}
    return max(1, len(nouns))


def _hero_number(text: str) -> bool:
    if _HERO_VERB.search(text):
        return True
    nums = _NUM_TOKEN.findall(text)
    return len(nums) == 1 and bool(_MAGNITUDE.search(text))


def signals_from(claim: str, facts: FactTable | None = None) -> Signals:
    """Signals for one claim; fact-derived fields are 0/False without facts.

    Fact-shape v1 approximations: n_periods counts distinct 19xx/20xx
    tokens across descriptions+displays; entity_count counts distinct
    rowN_ ids; crosses_zero looks for leading-minus or parenthesised
    row displays; has_targets greps descriptions for 'target'."""
    text = claim or ""
    n_periods = share_facts = entity_count = 0
    crosses_zero = has_targets = False
    if facts is not None:
        years: set[str] = set()
        rows: set[int] = set()
        for f in facts.facts.values():
            years.update(_YEAR.findall(f.description))
            years.update(_YEAR.findall(f.display))
            m = _ROW_ID.match(f.id)
            if m:
                rows.add(int(m.group(1)))
                if _NEG_DISPLAY.search(f.display):
                    crosses_zero = True
            if f.id.endswith("_share") or (
                    "%" in f.display and "share" in f.description.lower()):
                share_facts += 1
            if "target" in f.description.lower():
                has_targets = True
        n_periods = len(years)
        entity_count = len(rows)
    return Signals(
        trend=bool(_TREND.search(text)),
        ranking=bool(_RANKING.search(text)),
        composition=bool(_COMPOSITION.search(text)),
        distribution=bool(_DISTRIBUTION.search(text)),
        correlation=bool(_CORRELATION.search(text)),
        two_axis=bool(_TWO_AXIS.search(text)),
        funnel=bool(_FUNNEL.search(text)),
        process=bool(_PROCESS.search(text)),
        roadmap=bool(_ROADMAP.search(text)),
        hero_number=_hero_number(text),
        bridge=bool(_BRIDGE.search(text)),
        crosses_zero=crosses_zero,
        has_targets=has_targets,
        option_count=_option_count(text),
        criteria_count=_criteria_count(text),
        n_periods=n_periods,
        share_facts=share_facts,
        entity_count=entity_count)


@dataclass(frozen=True)
class FormatRule:
    id: str
    when: str        # what the claim asserts (human-readable)
    then: str        # the format verdict
    rationale: str
    detect: Callable[[Signals], bool]
    target_slide_types: tuple[str, ...]  # slide types that SATISFY the rule


def _no_claim_signal(s: Signals) -> bool:
    return not (s.trend or s.ranking or s.composition or s.distribution
                or s.correlation or s.two_axis or s.funnel or s.process
                or s.roadmap or s.hero_number or s.bridge)


RULES: tuple[FormatRule, ...] = (
    FormatRule(
        id="two_axis_matrix",
        when="two-axis positioning (2x2/quadrant)",
        then="custom_layout + matrix_2x2, never a chart",
        rationale="position argues",
        detect=lambda s: s.two_axis,
        target_slide_types=("custom_layout",)),
    FormatRule(
        id="bridge_waterfall",
        when="walk from X to Y",
        then="waterfall (coming; today a stacked walk)",
        rationale="show each driver",
        detect=lambda s: s.bridge,
        target_slide_types=("chart_slide", "custom_layout")),
    FormatRule(
        id="funnel_stages",
        when="conversion stages",
        then="custom_layout + funnel",
        rationale="the drop-off is the story",
        detect=lambda s: s.funnel,
        target_slide_types=("custom_layout",)),
    FormatRule(
        id="options_scorecard",
        when="2-4 options weighed",
        then="n_column_comparison; harvey_balls if >3 criteria",
        rationale="verdicts need columns",
        detect=lambda s: s.option_count >= 2,
        target_slide_types=("n_column_comparison", "custom_layout")),
    FormatRule(
        id="composition_share",
        when="share/mix of a whole",
        then="stacked_bar over years, donut <=6, else % bar",
        rationale="parts sum to the whole",
        detect=lambda s: s.composition,
        target_slide_types=("chart_slide", "custom_layout")),
    FormatRule(
        id="trend_line",
        when="change across periods",
        then="chart_slide + line, sort='none' (column if 2)",
        rationale="the slope carries it",
        detect=lambda s: s.trend and s.n_periods >= 2,
        target_slide_types=("chart_slide",)),
    FormatRule(
        id="ranking_bar",
        when="ranks >=3 entities",
        then="bar, sort='desc', highlight the leader",
        rationale="order proves rank",
        detect=lambda s: s.ranking and s.entity_count >= 3,
        target_slide_types=("chart_slide",)),
    FormatRule(
        id="distribution_histogram",
        when="spread of values",
        then="column histogram",
        rationale="shape beats the average",
        detect=lambda s: s.distribution,
        target_slide_types=("chart_slide",)),
    FormatRule(
        id="correlation_scatter",
        when="X moves with Y",
        then="paired bars (scatter not yet renderable)",
        rationale="pair the movements",
        detect=lambda s: s.correlation,
        target_slide_types=("chart_slide", "custom_layout")),
    FormatRule(
        id="hero_number",
        when="one dominant number",
        then="custom_layout hero stat",
        rationale="let it fill the slide",
        detect=lambda s: s.hero_number,
        target_slide_types=("custom_layout",)),
    FormatRule(
        id="roadmap_timeline",
        when="dated milestones",
        then="timeline_slide",
        rationale="time is the axis",
        detect=lambda s: s.roadmap,
        target_slide_types=("timeline_slide",)),
    FormatRule(
        id="process_chevron",
        when="a method or steps",
        then="framework_slide chevrons",
        rationale="sequence, not prose",
        detect=lambda s: s.process,
        target_slide_types=("framework_slide",)),
    FormatRule(
        id="dense_reference",
        when=">=8 entities, no single claim",
        then="data_deep_dive table",
        rationale="reference, not argument",
        detect=lambda s: s.entity_count >= 8 and _no_claim_signal(s),
        target_slide_types=("data_deep_dive",)),
)


def first_rule(signals: Signals) -> FormatRule | None:
    """The format verdict: first rule in RULES whose detect() fires."""
    return next((r for r in RULES if r.detect(signals)), None)


_VARIANT_HINTS = (
    "CHART STYLE (native_chart.style — top-firm defaults from the corpus):",
    "- always label values (91-100% of elite charts do) and annotate the "
    "takeaway on the chart",
    "- growth line: style.endpoint_labels + style.cagr_chip (engine computes "
    "the CAGR)",
    "- forecast/'by 20XX': style.forecast_from='<first future period>' dashes "
    "the tail",
    "- 'vs benchmark/target/average': style.benchmark={value,label} draws a "
    "dashed reference line",
    "- multi-series where one is the subject: style.highlight_series='<name>' "
    "mutes the rest to gray",
    "- 'bridge/walk from X to Y': chart_type='waterfall' (signed steps, "
    "opening + closing totals)",
)


def decision_table_text() -> str:
    """Compact rule table + variant hints for prompts (capped <= 1800)."""
    lines = ["FORMAT SELECTION - match the layout shape to the argument "
             "shape:"]
    lines += [f"- {r.when} -> {r.then}; {r.rationale}" for r in RULES]
    lines += ["", *_VARIANT_HINTS]
    return "\n".join(lines)


# -- lint: outline-level suggestions ------------------------------------------


def check_outline_formats(outline,
                          facts: FactTable | None = None) -> list[str]:
    """Suggestions only, max one per slide: the first rule a claim fires
    should be satisfiable by the chosen slide_type. TITLE_EXEMPT slides
    are skipped."""
    out: list[str] = []
    for i, s in enumerate(outline.slides):
        if s.slide_type in TITLE_EXEMPT:
            continue
        rule = first_rule(signals_from(s.claim, facts))
        if rule is None or s.slide_type in rule.target_slide_types:
            continue
        out.append(
            f"slide {i + 1} ({s.slide_type}): the claim asserts "
            f"{rule.when} — suggest {rule.then}")
    return out


# -- lint: objective data-shape violations on a built slide -------------------


def _walk_charts(node) -> Iterator[dict]:
    """Yield embedded native_chart dicts from a model_dump tree."""
    if isinstance(node, dict):
        if node.get("kind") == "native_chart":
            yield node
        else:
            for v in node.values():
                yield from _walk_charts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_charts(v)


def _chart_problems(chart: dict, title: str) -> list[str]:
    out: list[str] = []
    ctype = chart.get("chart_type")
    cats = chart.get("categories") or []
    series = chart.get("series") or []
    if ctype == "line" and len(cats) < 3:
        out.append(f"line chart with {len(cats)} categories: use a "
                   "column chart or add periods")
    if ctype == "donut" and len(cats) > 6:
        out.append(f"donut with {len(cats)} categories: merge the tail "
                   "into an 'Other' slice (max 6)")
    if (ctype == "donut" and series
            and str(chart.get("value_suffix", "")).strip() == "%"):
        total = sum(series[0].get("values") or [])
        if not 95 <= total <= 105:
            out.append(f"donut shares sum to {total:g}%: recompute so "
                       "parts sum to ~100 (95-105)")
    if ctype == "stacked_bar" and len(series) == 1:
        out.append("stacked_bar with one series: use a plain bar chart")
    if (_RANKING.search(plain(title)) and chart.get("sort") == "none"
            and len(cats) > 4):
        out.append("title makes a ranking claim but the chart is "
                   "unsorted with >4 categories: set sort='desc' so "
                   "order proves the rank")
    hl = chart.get("highlight")
    if hl and hl not in cats:
        out.append(f"highlight {hl!r} is not a category: use an exact "
                   "category name or null")
    if len(series) > 3:
        out.append(f"{len(series)} series on one chart: split into "
                   "small multiples or drop to <=3")
    # waterfall must balance: sum of steps == closing total
    if ctype == "waterfall" and series:
        vals = series[0].get("values") or []
        if len(vals) >= 2:
            steps = sum(vals[:-1])
            if abs(vals[-1] - steps) > 0.02 * max(1.0, abs(vals[-1])):
                out.append(
                    f"waterfall does not balance: steps sum to {steps:g} but "
                    f"the closing total is {vals[-1]:g} — make them equal")
    # variant knobs that name data must reference something real
    style = chart.get("style") or {}
    ff = style.get("forecast_from")
    if ff and ff not in cats:
        out.append(f"style.forecast_from {ff!r} is not a category: use an "
                   "exact category name")
    hs = style.get("highlight_series")
    if hs and hs not in [s.get("name") for s in series]:
        out.append(f"style.highlight_series {hs!r} is not a series name")
    return out


def check_slide_format(slide, facts: FactTable | None = None) -> list[str]:
    """Objective data-shape violations, phrased as repair instructions.
    Archetypes without charts return []. `facts` is reserved for future
    cross-checks; v1 checks are purely shape-based."""
    if isinstance(slide, ChartSlideSpec):
        charts = [slide.chart.model_dump()]
    elif isinstance(slide, CustomLayoutSpec):
        charts = list(_walk_charts(slide.model_dump()))
    else:
        return []
    problems: list[str] = []
    for c in charts:
        problems.extend(_chart_problems(c, slide.title))
    return problems
