"""Format brain wired into generation: teach (prompt), police (review),
repair (stage-2 loop). All LLM calls mocked."""
from deckengine.llm import spec_generator as sg
from deckengine.schema.slide_types import BulletContentSpec, ChartSlideSpec


def _chart(chart_type, categories, values, sort="desc", suffix=""):
    return {"kind": "native_chart", "chart_type": chart_type,
            "categories": categories,
            "series": [{"name": "s", "values": values}],
            "sort": sort, "highlight": None, "annotation": None,
            "value_suffix": suffix}


def _ranking_facts():
    from deckengine.llm.facts import FactTable
    t = FactTable()
    for i, (name, v) in enumerate([("Acme", "40"), ("Beta", "25"),
                                   ("Gamma", "20"), ("Delta", "15")]):
        t.add(f"row{i}_volume", v, f"volume of {name}", "test.csv")
    return t


def test_outline_prompt_teaches_and_review_polices(monkeypatch):
    prompts = []
    bad = {"governing_thought": "Enter the market now.",
           "slides": [
               {"slide_type": "title", "claim": "Market entry"},
               # ranking claim mis-typed as bullets -> outline format lint
               {"slide_type": "bullet_content",
                "claim": "Acme leads the market and outperforms every rival "
                         "on volume"},
           ]}
    good = {"governing_thought": "Enter the market now.",
            "slides": [
                {"slide_type": "title", "claim": "Market entry"},
                {"slide_type": "chart_slide",
                 "claim": "Acme leads the market and outperforms every rival "
                          "on volume"},
            ]}
    responses = [bad, good]

    def fake(name, schema, prompt, max_tokens=16000):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(sg, "_structured_call", fake)
    outline = sg.generate_outline("test", _ranking_facts())
    assert "FORMAT SELECTION" in prompts[0]          # teach
    low = prompts[1].lower()
    assert "rank" in low or "sorted" in low          # police via review pass
    assert outline.slides[1].slide_type == "chart_slide"  # revision kept


def test_stage2_repairs_objective_chart_violation(monkeypatch):
    prompts = []
    bad = ChartSlideSpec(
        title="Revenue grew 3x from 2019 to 2025 across the portfolio",
        chart=_chart("line", ["2019", "2025"], [10, 30], sort="none"),
    ).model_dump()
    good = ChartSlideSpec(
        title="Revenue grew 3x from 2019 to 2025 across the portfolio",
        chart=_chart("line", ["2019", "2021", "2023", "2025"],
                     [10, 14, 22, 30], sort="none"),
    ).model_dump()
    responses = [bad, good]

    def fake(name, schema, prompt, max_tokens=16000):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(sg, "_structured_call", fake)
    slide = sg.generate_slide("chart_slide", "claim", "prompt", None)
    assert len(prompts) == 2
    assert "Chart format problems" in prompts[1]
    assert "FORMAT SELECTION" in prompts[0]          # taught for chart slides
    assert len(slide.chart.categories) == 4


def test_non_chart_archetype_untouched(monkeypatch):
    clean = BulletContentSpec(
        title="Five moves de-risk the launch over 18 months",
        bullets=[{"text": "Secure supply first; the rest follows"}],
    ).model_dump()
    prompts = []

    def fake(name, schema, prompt, max_tokens=16000):
        prompts.append(prompt)
        return clean

    monkeypatch.setattr(sg, "_structured_call", fake)
    sg.generate_slide("bullet_content", "claim", "prompt", None)
    assert len(prompts) == 1
    assert "FORMAT SELECTION" not in prompts[0]      # table only where live
