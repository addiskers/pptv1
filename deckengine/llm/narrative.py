"""The story brain — deck flows, their grammars, and the flow-level critic.

Every consulting deck follows one of ~19 narrative FLOWS, and each flow
rests on persuasion PRINCIPLES about how audiences are convinced. The flow
is chosen by the AUDIENCE'S META-QUESTION, not the topic: "should we
enter?" → options_decision; "how healthy is the target?" → diagnostic;
"why must we change?" → three_act. Same data, different question,
different deck.

This module encodes the doctrine as data:
- FLOWS: id → meta-question, required beats (signal-regex per beat),
  closing beat, and the principles the flow rests on.
- check_outline_flow(): deterministic review-pass critic — a declared flow
  whose required beats are missing from the claim chain is broken at the
  flow level even if every title is individually fine.
- SLIDE_PRINCIPLES: the slide-level doctrine distilled for the SYSTEM
  prompt (flow-level principles live on the flows themselves).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Beat:
    name: str
    signal: str  # regex over claims + section tags (case-insensitive)


@dataclass(frozen=True)
class Flow:
    id: str
    meta_question: str
    beats: tuple[Beat, ...]           # required, loosely ordered
    closing: str | None = None        # regex the LAST body claims must hit
    principles: tuple[str, ...] = ()


def _b(name: str, signal: str) -> Beat:
    return Beat(name, signal)


FLOWS: dict[str, Flow] = {f.id: f for f in [
    Flow("scqa", "what changed and what should we do about it?",
         (_b("situation", r"today|current|has (grown|been)|baseline|stable"),
          _b("complication", r"but|however|risk|threat|shift|disrupt|stress|"
                             r"declin|gap|slow"),
          _b("answer", r"should|must|recommend|the answer|now is|requires")),
         closing=r"next step|recommend|ask|decision|now",
         principles=("tension-and-resolution", "answer-first")),
    Flow("pyramid", "what's the answer, and can you defend it?",
         (_b("governing answer first",
             r"should|must|will|is the|recommend"),
          _b("supporting arguments", r"because|three|driver|reason|evidence"
                                     r"|support")),
         closing=r"next step|ask|so what|implication",
         principles=("answer-first", "progressive-disclosure")),
    Flow("problem_solution_impact", "what's broken and what's it worth to fix?",
         (_b("problem sized", r"problem|cost(s|ing)?|loss|leak|fail|pain|"
                              r"under-?perform"),
          _b("solution", r"solution|fix|approach|program|intervention|play"),
          _b("impact", r"impact|worth|unlock|save|gain|return|value")),
         closing=r"implement|roadmap|next|start",
         principles=("tension-and-resolution", "quantification")),
    Flow("gap_bridge", "how far are we from where we should be?",
         (_b("current state", r"today|current|baseline|as-?is"),
          _b("future state", r"target|vision|to-?be|by 20\d\d|ambition"),
          _b("path", r"path|bridge|close|roadmap|journey|phase")),
         closing=r"roadmap|phase|first|next",
         principles=("contrast", "narrative-coherence")),
    Flow("grouping", "what are the parallel parts of the answer?",
         (_b("governing thought", r"three|four|five|pillars|levers|"
                                  r"workstream|priorit"),
          _b("synthesis", r"together|combined|in sum|total|add up")),
         closing=r"together|sequence|next",
         principles=("mece-completeness", "rule-of-three")),
    Flow("deductive", "convince me step by step.",
         (_b("premises chained", r"therefore|because|which means|so |implies"),),
         closing=r"conclu|therefore|must|follows",
         principles=("logical-inevitability",)),
    Flow("inductive", "do independent signals agree?",
         (_b("parallel evidence", r"signal|evidence|independent|all point|"
                                  r"converge|three .*show"),),
         closing=r"together|converge|conclusion|points to",
         principles=("mece-completeness", "hypothesis-first")),
    Flow("chronological", "how did we get here and where next?",
         (_b("timeline", r"20\d\d|phase|since|history|journey|then|now|next"),),
         closing=r"next|ahead|20\d\d|will",
         principles=("narrative-coherence",)),
    Flow("options_decision", "which option should we choose?",
         (_b("options laid out", r"option|alternative|scenario|build|buy|"
                                 r"partner|path (a|b|1|2)"),
          _b("criteria evaluation", r"criteri|evaluat|score|weigh|compare|"
                                    r"trade-?off|matrix"),
          _b("recommendation", r"recommend|preferred|should (choose|enter|"
                               r"pursue)|best option|we advise")),
         closing=r"recommend|decision|approve|next step",
         principles=("decision-framing", "answer-first")),
    Flow("hypothesis", "was the hypothesis right?",
         (_b("hypothesis stated", r"hypothes|we believe|thesis|bet"),
          _b("tests/evidence", r"test|evidence|validat|data (shows|confirms)|"
                               r"found")),
         closing=r"confirm|validat|conclusion|therefore",
         principles=("hypothesis-first",)),
    Flow("diagnostic", "how healthy is it, really?",
         (_b("framework/dimensions", r"dimension|framework|across|assess|"
                                     r"criteria|lens"),
          _b("findings", r"finding|score|strength|weakness|gap|red flag"),
          _b("prioritized issues", r"priorit|critical|top|most important")),
         closing=r"recommend|address|fix|next",
         principles=("diagnose-before-prescribe", "mece-completeness")),
    Flow("three_act", "why must we change, and toward what?",
         (_b("what is", r"today|reality|current|stuck|pain"),
          _b("what could be", r"could|imagine|possib|potential|future|"
                              r"instead"),
          _b("call to action", r"act|now|start|choose|commit|call")),
         closing=r"act|start|commit|call to",
         principles=("contrast", "tension-and-resolution")),
    Flow("funnel_zoom", "where exactly is the opportunity?",
         (_b("broad context", r"market|globally|overall|landscape"),
          _b("narrowing", r"segment|within|specifically|zoom|corridor|niche"),
          _b("the play", r"opportunity|play|entry|target|focus")),
         closing=r"implication|play|next|so what",
         principles=("progressive-disclosure",)),
    Flow("progress_review", "are we on track?",
         (_b("plan vs actual", r"plan|target|actual|vs\.?|track|status"),
          _b("variances", r"variance|behind|ahead|miss|delay|overrun"),
          _b("corrective actions", r"corrective|recover|mitigat|fix|"
                                   r"accelerate")),
         closing=r"outlook|next (quarter|period)|ask",
         principles=("quantification", "answer-first")),
    Flow("playbook_replication", "can we repeat the win at scale?",
         (_b("proven result", r"worked|proved|delivered|success|results in"),
          _b("the mechanism", r"because|mechanism|why it worked|model|"
                              r"formula"),
          _b("scaling plan", r"scale|replicate|roll ?out|expand|next \d+")),
         closing=r"scale|rollout|expand|next",
         principles=("narrative-coherence", "quantification")),
    Flow("benchmark", "how do we compare, and what's the gap worth?",
         (_b("leaders/peers", r"peer|leader|best[- ]in[- ]class|benchmark|"
                              r"competitor"),
          _b("quantified gap", r"gap|trail|behind|vs\.?|delta|lag"),
          _b("adoption plan", r"adopt|close|learn|implement|apply")),
         closing=r"close|adopt|sequence|next",
         principles=("contrast", "quantification")),
    Flow("investment_committee", "should we write the check?",
         (_b("thesis", r"thesis|case|why now|belief"),
          _b("market", r"market|size|growth|tam|demand"),
          _b("economics", r"unit econom|margin|payback|return|irr|"
                          r"econom"),
          _b("risks & mitigants", r"risk|mitigant|downside|sensitivit"),
          _b("the ask", r"ask|approve|invest|commit|term|allocate")),
         closing=r"ask|approve|invest|terms|next",
         principles=("decision-framing", "quantification",
                     "mece-completeness")),
    Flow("turnaround", "how bad is it, and can it be saved?",
         (_b("honest baseline", r"declin|loss|underperform|fell|reality|"
                                r"erod|miss"),
          _b("root causes", r"root cause|driver|because|why|structural"),
          _b("decisive plan", r"plan|stabiliz|restructur|decisive|act"),
          _b("early proof", r"proof|early|quick win|first \d+|already")),
         closing=r"proof|milestone|commit|first",
         principles=("diagnose-before-prescribe", "tension-and-resolution")),
    Flow("first_100_days", "what happens the moment we start?",
         (_b("mandate", r"mandate|charter|goal|remit"),
          _b("immediate actions", r"immediate|day.?one|week|stabiliz|first"),
          _b("quick wins", r"quick win|visible|early|30|60|90"),
          _b("longer arc", r"foundation|longer|beyond|year|horizon")),
         closing=r"beyond|horizon|then|next phase",
         principles=("narrative-coherence", "progressive-disclosure")),
]}


# slide-level doctrine, distilled for the SYSTEM prompt (≤6 lines)
SLIDE_PRINCIPLES = """- ONE idea per slide: the action title IS the idea; the body exists only to prove that title (vertical logic). Two ideas = two slides.
- Every exhibit carries its SO-WHAT on the slide (annotation/takeaway); data without an implication is decoration.
- Group in THREES where content allows; push proof detail to an appendix (altitude discipline) and lead each section with the finding that matters most (80/20).
- QUANTIFY: "significant/substantial/many" are banned where a number exists.
- PRIMACY & RECENCY: the first body slide carries the answer; the LAST slide carries the ask/next steps — never end on a data slide."""


def flow_menu() -> str:
    """One line per flow for the outline prompt — chosen by meta-question."""
    return "\n".join(f"- {f.id}: when the audience asks \"{f.meta_question}\""
                     for f in FLOWS.values())


def check_outline_flow(outline) -> list[str]:
    """Flow-level critic: the declared narrative_arc's required beats must
    be present in the claim chain, and the deck must close on the flow's
    closing beat. Suggestion-grade; unknown/undeclared arcs are skipped
    (never a trap)."""
    arc = (getattr(outline, "narrative_arc", None) or "").strip().lower()
    flow = FLOWS.get(arc)
    if flow is None:
        return []
    corpus = " || ".join(
        f"{s.claim} {s.section or ''}" for s in outline.slides)
    missing = [b.name for b in flow.beats
               if not re.search(b.signal, corpus, re.IGNORECASE)]
    problems = []
    if missing:
        problems.append(
            f"the outline declares the '{flow.id}' flow (audience asks: "
            f"{flow.meta_question}) but is missing its required beats: "
            f"{', '.join(missing)} — add or reshape claims so the flow's "
            f"argument is complete, or declare a flow that matches the "
            f"story you are telling")
    if flow.closing:
        tail = outline.slides[-1].claim
        if not re.search(flow.closing, tail, re.IGNORECASE):
            problems.append(
                f"a '{flow.id}' deck must CLOSE on its ask/resolution "
                f"(primacy-recency principle): reshape the final claims to "
                f"land the {flow.beats[-1].name if flow.beats else 'close'}"
                f" — never end on a data slide")
    return problems
