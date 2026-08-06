"""Writing-craft lint calibration + repair-loop wiring."""
from deckengine.llm.writing import check_slide_writing
from deckengine.schema.slide_types import BulletContentSpec


def hedgy_slide() -> BulletContentSpec:
    return BulletContentSpec(
        title="The commuter segment could potentially lead volume growth",
        bullets=[
            {"text": "Sales *might* improve and margins *may* expand "
                     "and share *could* grow and pricing *seems* firm"},
            {"text": "Additionally, the market appears strong!"},
        ])


def clean_slide() -> BulletContentSpec:
    return BulletContentSpec(
        title="The commuter segment leads volume growth at 35% CAGR",
        bullets=[
            {"text": "Sales grew **3x** in two years; margins expanded 4pp"},
            {"text": "Unit economics turned positive across all six metros"},
        ])


def test_hedged_title_flagged():
    problems = check_slide_writing(hedgy_slide())
    assert any("title hedges" in p for p in problems)


def test_body_hedge_pileup_flagged():
    assert any("hedge words" in p
               for p in check_slide_writing(hedgy_slide()))


def test_italics_everywhere_flagged():
    assert any("italic spans" in p
               for p in check_slide_writing(hedgy_slide()))


def test_connective_opener_and_exclamation_flagged():
    problems = check_slide_writing(hedgy_slide())
    assert any("Additionally" in p for p in problems)
    assert any("exclamation" in p for p in problems)


def test_clean_slide_passes():
    assert check_slide_writing(clean_slide()) == []


def test_bold_never_counted_as_italics():
    s = BulletContentSpec(
        title="Margins expanded 4pp on **$2.1B** of revenue",
        bullets=[{"text": "**bold** **bold** **bold** **bold** **bold**"}])
    assert check_slide_writing(s) == []


def test_generate_slide_repairs_writing(monkeypatch):
    """A hedgy first attempt must trigger one repair call with the writing
    problems in the prompt; the clean retry is returned."""
    from deckengine.llm import spec_generator as sg
    responses = [hedgy_slide().model_dump(), clean_slide().model_dump()]
    prompts = []

    def fake_call(name, schema, prompt, max_tokens=16000):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(sg, "_structured_call", fake_call)
    slide = sg.generate_slide("bullet_content", "claim", "prompt", None)
    assert len(prompts) == 2
    assert "Writing problems" in prompts[1]
    assert "hedge" in prompts[1]
    assert slide.title.startswith("The commuter segment leads")
