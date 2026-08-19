"""Consulting frameworks: decision-based, evidence-gated selection.

Doctrine (from a live failure analysis): NEVER ask a model to name a
framework — a flat menu of famous names mode-collapses onto the most
written-about entry (BCG) because nothing in the menu discriminates.
Selection is two-stage:

- STAGE 1 (model): the outline tags each SECTION with a DECISION TYPE
  from the neutral vocabulary in decision_menu() — no framework names
  anywhere in the prompt, so there is nothing to gravitate toward.
- STAGE 2 (code): DECISION_TYPES maps the decision to 1-2 candidates and
  the EVIDENCE GATE drops any candidate whose required data the brief /
  facts cannot honestly support. An empty shortlist means NO framework —
  a BCG matrix built on guessed share numbers is worse than none. Only a
  surviving 2-way tie (positioning) spends one fast-model call, shown
  BOTH choose_when and avoid_when with A/B order shuffled per section.
  The bcg-vs-nine_box portfolio tie resolves in code, never by model.

At most ONE framework per section and TWO per deck. The section's anchor
slide must LAND the framework's verdict: check_framework_verdicts rides
the outline review pass; check_framework_slide rides the slide repair
pass ("a framework without a verdict is wallpaper").
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Sequence

from pydantic import BaseModel, Field

from ..schema.rich import plain

if TYPE_CHECKING:  # avoid runtime import; facts is only type-referenced
    from .facts import FactTable


@dataclass(frozen=True)
class Framework:
    id: str
    label: str               # human name, for UI lines and critic messages
    question: str            # the decision it answers — the selection key
    choose_when: str         # signals in the brief/claims that call for it
    render_as: str           # engine form that draws it (exact kind names)
    axes: str | None = None  # for matrix forms: "x-axis / y-axis"
    cells: tuple[str, ...] = ()    # canonical quadrants/segments/forces
    requires: tuple[str, ...] = ()  # evidence signal ids; () = qualitative
    avoid_when: str = ""     # anti-signals, shown only in tie prompts
    verdict_signal: str = ""  # regex the anchor slide's CLAIM must hit


FRAMEWORKS: dict[str, Framework] = {f.id: f for f in [
    Framework(
        "bcg_matrix", "BCG growth-share matrix",
        "which businesses/products deserve investment, which fund the "
        "rest, and which we exit?",
        "a PORTFOLIO of units/products/markets competing for the same "
        "capital; words like prioritize, allocate, divest, cash cow",
        render_as="matrix_2x2",
        axes="relative market share / market growth rate",
        cells=("Stars", "Cash Cows", "Question Marks", "Dogs"),
        requires=("per_unit_share", "per_unit_growth"),
        avoid_when="share or growth per unit is guessed rather than "
                   "measured, or the portfolio has more than ~6 units "
                   "scored on richer criteria",
        verdict_signal=r"invest|divest|exit|harvest|fund|double.?down|"
                       r"reallocat|prioriti[sz]e|cash"),
    Framework(
        "ansoff_matrix", "Ansoff growth matrix",
        "which growth path do we take — and how much risk does it carry?",
        "growth options on the table: sell more of the same, enter new "
        "markets, launch new products, or diversify outright",
        render_as="matrix_2x2",
        axes="products (existing→new) / markets (existing→new)",
        cells=("Market Penetration", "Market Development",
               "Product Development", "Diversification"),
        avoid_when="the growth path is already chosen and the deck only "
                   "plans its execution",
        verdict_signal=r"penetrat|market development|product development|"
                       r"diversif|path|expand|grow (via|through|by)"),
    Framework(
        "porters_five_forces", "Porter's Five Forces",
        "is this industry structurally attractive enough to enter or stay?",
        "entry/attractiveness questions; margins under pressure; talk of "
        "suppliers, buyers, substitutes, new entrants, rivalry",
        render_as="hub_spoke",
        cells=("Competitive Rivalry", "Supplier Power", "Buyer Power",
               "Threat of Substitutes", "Threat of New Entrants"),
        avoid_when="the question is which segment or lane to take within "
                   "an industry already committed to",
        verdict_signal=r"attractive|unattractive|enter|entry|stay|exit|"
                       r"worth|structur"),
    Framework(
        "swot", "SWOT / TOWS",
        "where do we stand — and which strength meets which opportunity?",
        "a positioning stock-take before choices; pair with TOWS actions "
        "or it reads as a filler slide",
        render_as="matrix_2x2",
        axes="internal↔external / helpful↔harmful",
        cells=("Strengths", "Weaknesses", "Opportunities", "Threats"),
        avoid_when="the deck already argues a specific choice — a stock-"
                   "take slide would dilute it",
        verdict_signal=r"strength|opportunit|leverage|address|act on|"
                       r"defend|priorit"),
    Framework(
        "mckinsey_7s", "McKinsey 7S",
        "is the organization ALIGNED enough to execute the strategy?",
        "post-merger, transformation or execution-risk decks; strategy is "
        "set but delivery is the question",
        render_as="hub_spoke",
        cells=("Strategy", "Structure", "Systems", "Shared Values",
               "Style", "Staff", "Skills"),
        avoid_when="the strategy itself is still the open question",
        verdict_signal=r"align|misalign|ready|readiness|execut|gap|"
                       r"capab"),
    Framework(
        "value_chain", "Porter's value chain",
        "where in the chain is value created or cost buried?",
        "cost-out, margin, make-vs-buy or vertical-integration decisions",
        render_as="chevron_pathway",
        cells=("Inbound", "Operations", "Outbound", "Marketing & Sales",
               "Service"),
        avoid_when="cost detail per activity is unknown — the chain "
                   "becomes decoration",
        verdict_signal=r"cost|margin|outsourc|make.or.buy|integrat|"
                       r"concentrat|buried|capture"),
    Framework(
        "pestle", "PESTLE analysis",
        "which outside forces can make or break this move?",
        "market-entry or regulatory-heavy contexts; the macro backdrop "
        "changes the answer, not just the framing",
        render_as="icon_tile_row",
        cells=("Political", "Economic", "Social", "Technological",
               "Legal", "Environmental"),
        avoid_when="macro forces are background color rather than "
                   "decision-relevant — then name the 1-2 that matter "
                   "instead of the full grid",
        verdict_signal=r"regulat|policy|macro|force|risk|tailwind|"
                       r"headwind|make.or.break"),
    Framework(
        "ge_mckinsey_nine_box", "GE-McKinsey nine-box",
        "which market/unit combinations do we grow, hold, or harvest?",
        "a BCG-matrix question but with richer, multi-criteria axes and "
        "more than four units; 9 cells instead of 4",
        render_as="canvas 3x3 panel grid",
        axes="competitive strength / market attractiveness",
        cells=("Grow", "Selectivity", "Harvest"),
        requires=("many_units", "multi_criteria"),
        avoid_when="only share and growth are measured, or the portfolio "
                   "is small enough for four quadrants",
        verdict_signal=r"grow|hold|harvest|invest|divest|selectiv"),
    Framework(
        "three_cs", "3Cs (Company-Customers-Competitors)",
        "where do customer needs, our strengths, and competitor gaps "
        "intersect?",
        "positioning and value-proposition decks; the sweet-spot argument",
        render_as="venn",
        cells=("Company", "Customers", "Competitors"),
        avoid_when="the section is really a choose-your-lane call between "
                   "cost and differentiation, or warns about being stuck "
                   "in the middle",
        verdict_signal=r"sweet.?spot|position|intersect|differentiat|win|"
                       r"target|own"),
    Framework(
        "issue_tree", "issue tree (MECE decomposition)",
        "what are ALL the ways to solve this — and which branch wins?",
        "problem-structuring decks; MECE decomposition of a how/why "
        "question before the recommendation",
        render_as="tree",
        cells=("Root question", "MECE branches", "Leaf hypotheses"),
        avoid_when="the answer is already known — a tree after the fact "
                   "reads as theater",
        verdict_signal=r"driver|root|branch|because|priorit|explains|"
                       r"wins"),
    Framework(
        "porters_generic_strategies", "Porter's generic strategies",
        "do we win on cost, on differentiation, or in a niche?",
        "competitive-positioning choices; 'stuck in the middle' warnings",
        render_as="matrix_2x2",
        axes="competitive scope / source of advantage",
        cells=("Cost Leadership", "Differentiation", "Cost Focus",
               "Differentiation Focus"),
        avoid_when="the argument is a customer-competitor-company sweet "
                   "spot rather than a commitment to one lane",
        verdict_signal=r"cost leadership|differentiat|focus|niche|stuck|"
                       r"lane|commit"),
    Framework(
        "blue_ocean_errc", "Blue Ocean ERRC grid",
        "how do we escape head-to-head competition entirely?",
        "category-creation or repositioning decks; the grid IS the "
        "strategy statement",
        render_as="comparison_columns",
        cells=("Eliminate", "Reduce", "Raise", "Create"),
        avoid_when="the deck competes within the existing category on "
                   "existing factors",
        verdict_signal=r"eliminat|reduce|raise|create|uncontested|new "
                       r"(market|category|space)"),
]}


# -- stage 1 vocabulary: decisions, never framework names --------------------

@dataclass(frozen=True)
class DecisionType:
    id: str
    question: str                 # the audience's decision, for the menu
    candidates: tuple[str, ...]   # 0-2 framework ids


DECISION_TYPES: dict[str, DecisionType] = {d.id: d for d in [
    DecisionType("portfolio_allocation",
                 "which units/products get capital, which fund the rest, "
                 "which we exit",
                 ("bcg_matrix", "ge_mckinsey_nine_box")),
    DecisionType("market_attractiveness",
                 "is this industry/market structurally worth entering or "
                 "staying in",
                 ("porters_five_forces",)),
    DecisionType("growth_path",
                 "which growth direction to take (same market, new market, "
                 "new product, diversify)",
                 ("ansoff_matrix",)),
    DecisionType("positioning",
                 "where and how we win against competitors for these "
                 "customers",
                 ("three_cs", "porters_generic_strategies")),
    DecisionType("org_execution",
                 "whether the organization is aligned enough to deliver "
                 "the strategy",
                 ("mckinsey_7s",)),
    DecisionType("cost_structure",
                 "where in the operating chain cost or value concentrates",
                 ("value_chain",)),
    DecisionType("macro_risk",
                 "which outside (regulatory/economic/social) forces change "
                 "the answer",
                 ("pestle",)),
    DecisionType("problem_structuring",
                 "decomposing a how/why question into testable drivers",
                 ("issue_tree",)),
    DecisionType("category_creation",
                 "escaping head-to-head competition by redefining the "
                 "offer",
                 ("blue_ocean_errc",)),
    DecisionType("stocktake",
                 "an honest where-do-we-stand before choices are argued",
                 ("swot",)),
    DecisionType("none",
                 "the section informs; it forces no decision",
                 ()),
]}

DECISION_TYPE_IDS: frozenset[str] = frozenset(DECISION_TYPES)


def decision_menu() -> str:
    """One line per decision type for the outline prompt — deliberately
    free of framework names (naming them re-creates the collapse)."""
    return "\n".join(f"- {d.id}: when the section decides {d.question}"
                     for d in DECISION_TYPES.values() if d.id != "none")


# -- stage 2: signals, gate, shortlist (pure code) ---------------------------

_SHARE_RX = re.compile(r"(market|relative|unit)[\s_-]*share", re.I)
_GROWTH_RX = re.compile(r"growth|cagr|yoy|year[\s_-]*over[\s_-]*year", re.I)
_CRITERIA_RX = re.compile(r"criteri|weight|scor(?:e|ing|ecard)|"
                          r"attractiveness", re.I)
_SIZE_COLS_RX = re.compile(r"revenue|sales|size|volume|units", re.I)


def detect_signals(brief: str, facts: "FactTable | None") -> set[str]:
    """Evidence signals the gate checks `Framework.requires` against.
    With a dataset, structure beats keywords; WITHOUT one, `many_units`
    is never granted (a nine-box can't be earned on vibes) and share/
    growth must be claimed in the brief itself."""
    signals: set[str] = set()
    text = brief or ""
    if facts is not None:
        slugs = facts.column_slugs()
        spaced = {s: s.replace("_", " ") for s in slugs}
        if any(_SHARE_RX.search(v) for v in spaced.values()) or any(
                re.match(r"row\d+_.*(revenue|sales|size|volume|units).*"
                         r"_share$", fid)
                for fid in facts.facts):
            signals.add("per_unit_share")
        if any(_GROWTH_RX.search(v) for v in spaced.values()):
            signals.add("per_unit_growth")
        if facts.unit_count() > 4:
            signals.add("many_units")
        if len(slugs) >= 4 or _CRITERIA_RX.search(text):
            signals.add("multi_criteria")
    else:
        if _SHARE_RX.search(text):
            signals.add("per_unit_share")
        if _GROWTH_RX.search(text):
            signals.add("per_unit_growth")
        if _CRITERIA_RX.search(text):
            signals.add("multi_criteria")
    return signals


def evidence_gate(candidates: Sequence[Framework],
                  signals: set[str]) -> list[Framework]:
    """Drop every candidate whose required evidence is missing — the
    honest no-data path is NO framework, never an invented one."""
    return [f for f in candidates if set(f.requires) <= signals]


def shortlist_for(decision_type: str, signals: set[str]) -> list[Framework]:
    """decision -> candidates -> gate -> at most 2; the portfolio pair
    tie-breaks in CODE (both surviving means the richer nine-box data
    exists — familiarity must never win that call)."""
    dt = DECISION_TYPES.get(decision_type)
    if dt is None:
        return []
    survivors = evidence_gate([FRAMEWORKS[c] for c in dt.candidates], signals)
    if len(survivors) == 2 and \
            {f.id for f in survivors} == {"bcg_matrix",
                                          "ge_mckinsey_nine_box"}:
        pick = ("ge_mckinsey_nine_box"
                if {"many_units", "multi_criteria"} <= signals
                else "bcg_matrix")
        return [FRAMEWORKS[pick]]
    return survivors


# -- the one model call: resolving a surviving 2-way tie ---------------------

class TieChoice(BaseModel):
    section: str = Field(max_length=40)
    framework_id: str = Field(max_length=40)


class TieChoices(BaseModel):
    choices: list[TieChoice]


Tie = tuple[str, list[str], Framework, Framework]  # (section, claims, a, b)


def _tie_order(tag: str, claims: list[str],
               a: Framework, b: Framework) -> tuple[Framework, Framework]:
    """Deterministic A/B shuffle per section — kills position bias while
    staying reproducible (no randomness allowed in the pipeline)."""
    h = hashlib.sha1((tag + "".join(claims)).encode("utf-8")).digest()[0]
    return (a, b) if h % 2 == 0 else (b, a)


def ties_prompt(ties: Sequence[Tie], brief: str) -> str:
    lines = [
        "You are choosing the analytical lens for deck sections where two "
        "lenses both fit on paper. Read each section's claims and pick the "
        "lens the ARGUMENT actually makes — the avoid line disqualifies, "
        "the choose line qualifies. Answer with one framework_id per "
        "section.",
        f"\nDeck brief:\n{brief[:600]}",
    ]
    for tag, claims, a, b in ties:
        first, second = _tie_order(tag, claims, a, b)
        lines.append(f"\nSECTION {tag!r} — its claims:")
        lines += [f"  - {c}" for c in claims[:4]]
        for f in (first, second):
            lines.append(f"  OPTION {f.id}: answers \"{f.question}\"")
            lines.append(f"    choose if: {f.choose_when}")
            lines.append(f"    AVOID if: {f.avoid_when}")
    return "\n".join(lines)


# -- assignment (mutates outline; the only writer of slide.framework) --------

def assign_frameworks(outline, brief: str, facts: "FactTable | None",
                      choose: Callable[[list[Tie]], dict[str, str]]
                      | None = None) -> dict[str, str]:
    """Two-stage selection over an Outline (duck-typed: anything with
    .slides carrying claim/section/decision_type/framework). Clears any
    model-written framework values first — the field exists in the schema
    so the model can hallucinate it; code never trusts it (the
    narrative_arc doctrine). Returns {section: framework_id}."""
    for s in outline.slides:
        s.framework = None
    sections: dict[str, list] = {}
    order: list[str] = []
    for s in outline.slides:
        tag = (s.section or "").strip()
        if not tag:
            continue
        if tag not in sections:
            sections[tag] = []
            order.append(tag)
        sections[tag].append(s)
    signals = detect_signals(brief, facts)
    assigned: dict[str, Framework] = {}
    ties: list[Tie] = []
    for tag in order:
        slides = sections[tag]
        dt = next((s.decision_type for s in slides
                   if getattr(s, "decision_type", None)), None)
        if not dt or dt == "none":
            continue
        short = shortlist_for(dt, signals)
        if len(short) == 1:
            assigned[tag] = short[0]
        elif len(short) == 2:
            ties.append((tag, [s.claim for s in slides],
                         short[0], short[1]))
    if ties and choose is not None:
        try:
            picks = choose(ties)
        except Exception:  # noqa: BLE001 — a failed tie call means NO
            picks = {}     # framework, never a default (defaults collapse)
        for tag, _claims, a, b in ties:
            fid = picks.get(tag)
            if fid in (a.id, b.id):
                assigned[tag] = FRAMEWORKS[fid]
    if len(assigned) > 2:
        # deck cap: evidence-backed frameworks outrank qualitative ones,
        # then earliest section wins ("a deck of six frameworks is a
        # textbook, not an argument")
        keep = sorted(assigned, key=lambda t: (
            -len(set(assigned[t].requires) & signals), order.index(t)))[:2]
        assigned = {t: assigned[t] for t in keep}
    for tag, fw in assigned.items():
        slides = sections[tag]
        anchor = next((s for s in slides
                       if fw.verdict_signal
                       and re.search(fw.verdict_signal, s.claim, re.I)),
                      slides[0])
        anchor.framework = fw.id
    return {t: fw.id for t, fw in assigned.items()}


# -- what the chosen framework tells the slide designer ----------------------

def framework_directive(fw: Framework) -> str:
    lines = [f"FRAMEWORK — this slide argues through the {fw.label}; the "
             f"{fw.render_as} IS the layout, drawn as the dominant element:"]
    if fw.axes:
        lines.append(f"- axes: {fw.axes}")
    if fw.cells:
        lines.append(f"- parts, ALL labeled: {', '.join(fw.cells)} — each "
                     "filled with THIS deck's entities and evidence, never "
                     "textbook definitions")
    lines.append(f"- the title LANDS the verdict ({fw.question}) naming "
                 "winners/losers with visual emphasis — a framework "
                 "without a verdict is wallpaper")
    return "\n".join(lines)


# -- deterministic critics (free; mirror narrative.check_outline_flow) -------

def check_framework_verdicts(outline) -> list[str]:
    """Outline-level: every framework-anchored claim must land its
    verdict. Rides the existing review pass — zero extra calls."""
    problems = []
    for i, s in enumerate(outline.slides):
        fw = FRAMEWORKS.get(getattr(s, "framework", None) or "")
        if fw is None or not fw.verdict_signal:
            continue
        if not re.search(fw.verdict_signal, s.claim, re.I):
            problems.append(
                f"slide {i + 1} argues through the {fw.label} but its "
                f"claim never lands the verdict (\"{fw.question}\") — "
                f"reshape the claim to state the decision outcome plainly")
    return problems


def check_framework_slide(slide, fw: Framework) -> list[str]:
    """Slide-level contract, capped at TWO rules so it cannot crowd the
    shared repair budget: the form's parts are present, and the title
    lands the verdict."""
    problems = []
    text = slide.model_dump_json().lower()
    if fw.cells:
        hits = sum(1 for c in fw.cells if c.lower() in text)
        if hits * 2 < len(fw.cells):
            problems.append(
                f"the slide argues through the {fw.label} but only {hits} "
                f"of its {len(fw.cells)} canonical parts appear "
                f"({', '.join(fw.cells)}) — render the {fw.render_as} "
                f"with every part labeled")
    title = plain(str(getattr(slide, "title", "") or ""))
    if fw.verdict_signal and not re.search(fw.verdict_signal, title, re.I):
        problems.append(
            f"a {fw.label} without a verdict is wallpaper — the title "
            f"must land the decision (\"{fw.question}\")")
    return problems
