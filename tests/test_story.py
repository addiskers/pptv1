"""Story-engine calibration: the validator must flag every bad fixture and
pass every good one."""
from deckengine.llm.story import (Outline, OutlineSlide, check_outline,
                                  title_is_takeaway)

BAD_TITLES = [
    "Market Overview", "Results", "Competitive Landscape", "Next Steps",
    "State-level outcomes", "Financial Summary", "Introduction",
    "Our Approach", "Segment Analysis",
]
GOOD_TITLES = [
    "The commuter segment offers the best beachhead for a new OEM",
    "Interventions lifted incomes 5% above state averages in all three states",
    "EV natives lead growth while legacy OEMs retain scale",
    "Digital reach grew 8x since 2022 while direct reach doubled",
    "Hybrid cereals lead the pipeline with $150M committed",
]


def test_all_bad_titles_flagged():
    misses = [t for t in BAD_TITLES if title_is_takeaway(t)]
    assert not misses, f"labels that slipped through: {misses}"


def test_all_good_titles_pass():
    misses = [t for t in GOOD_TITLES if not title_is_takeaway(t)]
    assert not misses, f"claims wrongly flagged: {misses}"


def test_check_outline_flags_labels_and_duplicates():
    outline = Outline(
        governing_thought="Enter the commuter EV segment now.",
        slides=[
            OutlineSlide(slide_type="title", claim="Market entry strategy"),
            OutlineSlide(slide_type="exec_summary",
                         claim="Market Overview"),  # label
            OutlineSlide(slide_type="chart_slide",
                         claim="The commuter segment grew 35% and leads on volume"),
            OutlineSlide(slide_type="bullet_content",
                         claim="The commuter segment leads on volume and grew 35%"),  # dup
        ])
    problems = check_outline(outline)
    assert any("label" in p for p in problems)
    assert any("overlaps" in p for p in problems)
    # title slide exempt: its label claim must NOT be flagged
    assert not any("slide 1" in p for p in problems)


def test_clean_outline_no_problems():
    outline = Outline(
        governing_thought="Enter the commuter EV segment within 12 months.",
        slides=[
            OutlineSlide(slide_type="title", claim="India EV market entry"),
            OutlineSlide(slide_type="chart_slide",
                         claim="The market doubled to 1.7M units in two years"),
            OutlineSlide(slide_type="n_column_comparison",
                         claim="Commuter offers the largest pool at accessible price points"),
            OutlineSlide(slide_type="bullet_content",
                         claim="Five moves over 18 months de-risk the launch"),
        ])
    assert check_outline(outline) == []


# --- anti-generic rule: consecutive same-archetype runs ------------------------


def test_three_consecutive_same_archetype_flagged():
    outline = Outline(
        governing_thought="Enter the commuter EV segment within 12 months.",
        slides=[
            OutlineSlide(slide_type="title", claim="India EV market entry"),
            OutlineSlide(slide_type="bullet_content",
                         claim="The market doubled to 1.7M units in two years"),
            OutlineSlide(slide_type="bullet_content",
                         claim="Commuter offers the largest pool at accessible prices"),
            OutlineSlide(slide_type="bullet_content",
                         claim="Five moves over 18 months de-risk the launch"),
        ])
    problems = check_outline(outline)
    assert any("consecutive" in p for p in problems), problems


def test_two_consecutive_same_archetype_ok():
    outline = Outline(
        governing_thought="Enter the commuter EV segment within 12 months.",
        slides=[
            OutlineSlide(slide_type="title", claim="India EV market entry"),
            OutlineSlide(slide_type="bullet_content",
                         claim="The market doubled to 1.7M units in two years"),
            OutlineSlide(slide_type="bullet_content",
                         claim="Commuter offers the largest pool at accessible prices"),
            OutlineSlide(slide_type="chart_slide",
                         claim="Five moves over 18 months de-risk the launch"),
        ])
    assert not any("consecutive" in p for p in check_outline(outline))


# --- stage-1 wiring: generate_outline emits the claim chain + review pass ------


def test_generate_outline_claim_chain_and_review(monkeypatch):
    from deckengine.llm import spec_generator as sg
    calls = []

    def fake_call(name, schema, prompt, max_tokens=16000, **kw):
        calls.append(prompt)
        return {"governing_thought": "India quick commerce rewards scale now.",
                "slides": [
                    {"slide_type": "title", "claim": "India quick commerce"},
                    {"slide_type": "chart_slide",
                     "claim": "GMV tripled to $7.1B in two years"},
                ]}

    monkeypatch.setattr(sg, "_structured_call", fake_call)
    outline = sg.generate_outline("test prompt", None)
    assert outline.governing_thought
    assert outline.slides[1].claim.startswith("GMV")
    assert len(calls) == 2                      # draft + holistic review pass
    assert "claim" in calls[0].lower()
    assert "partner reviewing" in calls[1].lower()


def test_generate_outline_keeps_original_when_review_worse(monkeypatch):
    from deckengine.llm import spec_generator as sg
    good = {"governing_thought": "India quick commerce rewards scale now.",
            "slides": [
                {"slide_type": "chart_slide",
                 "claim": "GMV tripled to $7.1B in two years"},
                {"slide_type": "kpi_dashboard",
                 "claim": "Unit economics turned positive across 3 players"},
            ]}
    bad = {"governing_thought": "India quick commerce rewards scale now.",
           "slides": [
               {"slide_type": "chart_slide", "claim": "Market Overview"},
               {"slide_type": "kpi_dashboard", "claim": "Financial Summary"},
           ]}
    responses = [good, bad]

    def fake_call(name, schema, prompt, max_tokens=16000, **kw):
        return responses.pop(0)

    from deckengine.llm import spec_generator as sg2
    monkeypatch.setattr(sg2, "_structured_call", fake_call)
    outline = sg2.generate_outline("test prompt", None)
    assert outline.slides[0].claim.startswith("GMV")  # review discarded
