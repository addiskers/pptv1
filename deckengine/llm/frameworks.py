"""Classic consulting STRATEGY FRAMEWORKS as a selectable registry — DUMMY,
not yet wired into generation.

The story brain (narrative.py) picks the deck's FLOW by the audience's
meta-question; this module is the sibling registry one level down: the
named analytical framework a slide (or section) argues through — BCG
growth-share matrix, Ansoff, Porter's Five Forces, and the rest of the
canon every partner knows by sight.

Selection doctrine (same spirit as the flow menu): a framework is chosen
by the DECISION the audience faces, never by topic, and never decoration —
if the deck doesn't need the framework's verdict, it doesn't get the
framework. At most ONE framework per section; a deck of six frameworks is
a textbook, not an argument.

Wiring plan (when promoted from dummy): framework_menu() joins the outline
prompt next to flow_menu(); the chosen framework's `render_as` routes to
the engine form (matrix_2x2, data_table, driver tree canvas...) and its
`cells`/`axes` seed the slide brief.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Framework:
    id: str
    question: str           # the decision it answers — the selection key
    choose_when: str        # signals in the brief/claims that call for it
    render_as: str          # engine form that draws it
    axes: str | None = None  # for matrix forms: "x-axis / y-axis"
    cells: tuple[str, ...] = ()   # canonical quadrants/segments/forces


FRAMEWORKS: dict[str, Framework] = {f.id: f for f in [
    Framework(
        "bcg_matrix",
        "which businesses/products deserve investment, which fund the "
        "rest, and which we exit?",
        "a PORTFOLIO of units/products/markets competing for the same "
        "capital; words like prioritize, allocate, divest, cash cow",
        render_as="matrix_2x2",
        axes="relative market share / market growth rate",
        cells=("Stars", "Cash Cows", "Question Marks", "Dogs")),
    Framework(
        "ansoff_matrix",
        "which growth path do we take — and how much risk does it carry?",
        "growth options on the table: sell more of the same, enter new "
        "markets, launch new products, or diversify outright",
        render_as="matrix_2x2",
        axes="products (existing→new) / markets (existing→new)",
        cells=("Market Penetration", "Market Development",
               "Product Development", "Diversification")),
    Framework(
        "porters_five_forces",
        "is this industry structurally attractive enough to enter or stay?",
        "entry/attractiveness questions; margins under pressure; talk of "
        "suppliers, buyers, substitutes, new entrants, rivalry",
        render_as="hub_spoke or five-panel canvas",
        cells=("Competitive Rivalry", "Supplier Power", "Buyer Power",
               "Threat of Substitutes", "Threat of New Entrants")),
    Framework(
        "swot",
        "where do we stand — and which strength meets which opportunity?",
        "a positioning stock-take before choices; pair with TOWS actions "
        "or it reads as a filler slide",
        render_as="matrix_2x2",
        axes="internal↔external / helpful↔harmful",
        cells=("Strengths", "Weaknesses", "Opportunities", "Threats")),
    Framework(
        "mckinsey_7s",
        "is the organization ALIGNED enough to execute the strategy?",
        "post-merger, transformation or execution-risk decks; strategy is "
        "set but delivery is the question",
        render_as="hub_spoke",
        cells=("Strategy", "Structure", "Systems", "Shared Values",
               "Style", "Staff", "Skills")),
    Framework(
        "value_chain",
        "where in the chain is value created or cost buried?",
        "cost-out, margin, make-vs-buy or vertical-integration decisions",
        render_as="chevron_pathway",
        cells=("Inbound", "Operations", "Outbound", "Marketing & Sales",
               "Service")),
    Framework(
        "pestle",
        "which outside forces can make or break this move?",
        "market-entry or regulatory-heavy contexts; the macro backdrop "
        "changes the answer, not just the framing",
        render_as="icon_tile_row or six-panel canvas",
        cells=("Political", "Economic", "Social", "Technological",
               "Legal", "Environmental")),
    Framework(
        "ge_mckinsey_nine_box",
        "which market/unit combinations do we grow, hold, or harvest?",
        "a BCG-matrix question but with richer, multi-criteria axes; "
        "9 cells instead of 4",
        render_as="matrix canvas (3x3)",
        axes="competitive strength / market attractiveness",
        cells=("Grow", "Selectivity", "Harvest")),
    Framework(
        "three_cs",
        "where do customer needs, our strengths, and competitor gaps "
        "intersect?",
        "positioning and value-proposition decks; the sweet-spot argument",
        render_as="venn or three-panel comparison_columns",
        cells=("Company", "Customers", "Competitors")),
    Framework(
        "issue_tree",
        "what are ALL the ways to solve this — and which branch wins?",
        "problem-structuring decks; MECE decomposition of a how/why "
        "question before the recommendation",
        render_as="driver-tree canvas (brace_group nest)",
        cells=("Root question", "MECE branches", "Leaf hypotheses")),
    Framework(
        "porters_generic_strategies",
        "do we win on cost, on differentiation, or in a niche?",
        "competitive-positioning choices; 'stuck in the middle' warnings",
        render_as="matrix_2x2",
        axes="competitive scope / source of advantage",
        cells=("Cost Leadership", "Differentiation", "Cost Focus",
               "Differentiation Focus")),
    Framework(
        "blue_ocean_errc",
        "how do we escape head-to-head competition entirely?",
        "category-creation or repositioning decks; the grid IS the "
        "strategy statement",
        render_as="comparison_columns (4 cols)",
        cells=("Eliminate", "Reduce", "Raise", "Create")),
]}


def framework_menu() -> str:
    """One line per framework for a selection prompt — chosen by the
    DECISION, mirror of narrative.flow_menu()."""
    return "\n".join(
        f"- {f.id}: when the audience asks \"{f.question}\""
        for f in FRAMEWORKS.values())


# prompt when this registry is wired in.
SELECTION_PROMPT = (
    "FRAMEWORK (optional): if — and only if — one section of this deck "
    "argues a decision that a classic framework ANSWERS, name it in that "
    "section's visual_concept and shape the section's claims to deliver "
    "the framework's VERDICT (a BCG matrix without an invest/divest call "
    "is wallpaper). Choose by the audience's decision, never the topic; "
    "at most ONE framework per section, and none is the right answer for "
    "most sections:\n" + framework_menu())
