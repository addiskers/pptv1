# DeckEngine — Claude Code Rules

- Python 3.11+, type hints everywhere, Pydantic v2 models for ALL data crossing boundaries.
- ALL positions/sizes in EMU internally. Use core/units.py helpers; never raw ints like 914400 inline.
- NEVER hardcode colors, fonts, or sizes in components — everything comes from Theme.
- Every text placement MUST go through core.pptx_text.set_rich_text / make_text_frame.
  Direct slide.shapes.add_textbox + text_frame writes are banned outside core/pptx_text.py.
  (python-pptx defaults are wrap=none + spAutoFit + hidden 0.1in/0.05in insets — they break layout.)
- Text measurement uses core.fit_text (uharfbuzz shaping). Wrap against SAFETY * writable width (0.96).
- Rich text is ALWAYS a list of Span(text, bold, italic, color_role, size_pt) — never a bare string
  at the measurement layer.
- Components: measure() must be side-effect free; render() must not draw outside its bbox; both
  return consumed height in EMU. Shared test asserts measure == render consumed height (±1pt).
- data_table and mini_table render as SHAPE GRIDS, never native OOXML tables (cells cannot hold
  shapes; row heights are minimums that PowerPoint re-grows).
- One component per file. New component = model in schema/components.py + renderer + unit test.
- Raw XML manipulation ONLY in render/xml_utils.py with a comment explaining why python-pptx can't.
- Run `python -m pytest tests/ -x` from the deckengine repo root before claiming any task done.
- Never let an LLM do arithmetic: numbers flow through fact tables (llm/facts.py), not literals.
- No print() in library code — use logging. Warnings accumulate into BuildReport.
