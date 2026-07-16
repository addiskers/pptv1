# DeckEngine

Consulting-grade PPTX generation: an LLM writes a validated JSON slide spec, a
deterministic layout engine measures real fonts and renders fully editable
PowerPoint at Gates-Foundation density.

## Quick start

```bash
pip install -e .[dev]
python -m pytest tests/ -q                 # 76 tests
python examples/generate_demo.py          # renders examples/out/agdev_demo.pptx
```

On Windows with Office installed, `deckengine.render.preview.export_pngs_powerpoint`
opens the deck in real PowerPoint (the "no repair prompt" acceptance gate) and
exports per-slide PNGs.

## Architecture

```
prompt/CSV -> llm/spec_generator (structured outputs + fact table)
           -> schema/* (Pydantic, the LLM contract)
           -> slides/* assemblers -> layout/* (zones, two-phase stacker)
           -> components/* (14 renderers; measure() == render() contract)
           -> core/* (EMU units, BBox algebra, uharfbuzz fit_text,
                      make_text_frame factory, themed shapes)
           -> .pptx
```

Key design decisions (from an adversarial design review):
- **Text is measured by shaping with uharfbuzz** against the same TTFs PowerPoint
  uses, wrapped at 96% width; line spacing is written as exact `<a:spcPts>` so the
  measured value is the rendered value.
- **Every text frame goes through `make_text_frame`** — wrap on, autofit off,
  margins pinned (python-pptx defaults break measured layout on first click).
- **Tables are shape grids**, never native OOXML tables (cells can't hold badge
  chips; row heights are minimums PowerPoint re-grows).
- **comparison_columns is a row-track grid** — the same cell row lands at the same
  y in every column.
- **Numbers are never computed by the LLM** — `llm/facts.py` computes them in
  Python and `verify_spec_numbers` gates the output.
- One theme JSON (`themes/*.json`) = full rebrand; zero hex/font literals outside.

## Layers

| dir | what |
|---|---|
| `deckengine/core` | units, bbox, theme, fonts, fit_text, pptx_text/shapes |
| `deckengine/schema` | Pydantic specs (components, slides, deck), rich-text parser |
| `deckengine/components` | 14 registered component renderers |
| `deckengine/layout` | zones + two-phase stacker (plan -> render) |
| `deckengine/slides` | 7 slide archetype assemblers |
| `deckengine/render` | deck_builder, PowerPoint-COM preview |
| `deckengine/llm` | fact tables, two-stage spec generator (OpenAI or Anthropic — set OPENAI_API_KEY or ANTHROPIC_API_KEY; model via DECKENGINE_MODEL, default gpt-5.4 / claude-sonnet-5) |
| `deckengine/api` | FastAPI: POST /render (spec) and /generate (prompt) |

## API

```bash
uvicorn deckengine.api.main:app
# POST /render   {"spec": {...DeckSpec...}}          -> job_id
# POST /generate {"prompt": "...", "csv_text": "..."} -> job_id (LLM path)
# GET  /jobs/{id} , GET /download/{id}
# set DECKENGINE_API_KEY to require X-API-Key
```

## Status / roadmap

v0.1 (this): 14 components, 7 archetypes, working end-to-end from hand-written or
LLM specs. Not yet: table split across slides (seams exist via
`data_table.row_offsets`), slide-master/theme-XML sync, LibreOffice server
preview path, edit-then-regenerate round trip, second theme.
