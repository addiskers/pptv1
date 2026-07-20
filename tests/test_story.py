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
