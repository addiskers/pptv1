Vendored metric-compatible fonts (all SIL OFL — redistribution permitted).

These files exist so DeckEngine measures text with the SAME advance widths
PowerPoint will render, on machines without the Microsoft fonts (Linux/EC2).
Verified metric deltas vs the real faces (100pt ref string):
  Gelasio = Georgia          0.000%
  Selawik = Segoe UI         0.28% worst (bold)
  Carlito = Calibri          0.000%
  Liberation Sans = Arial    0.000%

Sources (fetched 2026-08-13):
  Gelasio  google/fonts ofl/gelasio (VF; statics instanced at wght 400/700
           via fontTools.varLib.instancer)
  Selawik  microsoft/Selawik release 1.01 (selawk.ttf, selawkb.ttf)
  Carlito  google/fonts ofl/carlito
  Liberation Sans  liberationfonts/liberation-fonts 2.1.5

NEVER add a non-metric-compatible face as a fallback for a theme font —
that is how the EC2 deck disaster happened (Liberation Serif standing in
for Georgia measured 8-12% narrow; PowerPoint re-wrapped everything).
core/fonts.py enforces this: unknown weights FAIL LOUDLY.
