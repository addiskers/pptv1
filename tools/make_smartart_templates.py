"""One-time template authoring: real SmartArt objects via PowerPoint COM.

Run on a Windows machine with PowerPoint installed:
    python tools/make_smartart_templates.py

Produces assets/smartart/{org_chart,issue_tree,cycle,radial}.pptx — each a
single slide holding ONE SmartArt object of the target layout. The clone
engine (render/smartart_clone.py) only reuses the LAYOUT / QUICKSTYLE /
COLORS parts from these files; the data model is synthesized fresh per
deck, so node counts/texts here don't matter — the layout identity does.
"""
from __future__ import annotations

import sys
from pathlib import Path

import win32com.client

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "assets" / "smartart"

# our name -> substring of PowerPoint's English layout name (first match)
LAYOUTS = {
    "org_chart": "Organization Chart",     # hierarchy family
    "issue_tree": "Horizontal Hierarchy",  # left->right tree
    "cycle": "Basic Cycle",
    "radial": "Basic Radial",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = win32com.client.gencache.EnsureDispatch("PowerPoint.Application")
    # SmartArtLayouts throws "Object does not exist" until the app surface
    # is initialized — Visible=True AND an open presentation are required
    app.Visible = True
    made = []
    boot = app.Presentations.Add(WithWindow=True)
    try:
        layouts = app.SmartArtLayouts
        by_name = {}
        for i in range(1, layouts.Count + 1):
            lo = layouts.Item(i)
            by_name[lo.Name] = lo
        print(f"{len(by_name)} SmartArt layouts visible")
        for ours, want in LAYOUTS.items():
            match = next((lo for name, lo in by_name.items()
                          if want.lower() in name.lower()), None)
            if match is None:
                print(f"!! no layout matching {want!r}; available sample: "
                      f"{list(by_name)[:10]}")
                continue
            pres = app.Presentations.Add(WithWindow=True)
            try:
                slide = pres.Slides.Add(1, 12)  # ppLayoutBlank
                slide.Shapes.AddSmartArt(match, 100, 100, 800, 500)
                dest = OUT / f"{ours}.pptx"
                pres.SaveAs(str(dest), 24)  # ppSaveAsOpenXMLPresentation
                made.append(dest.name)
                print(f"made {dest.name} <- {match.Name!r}")
            finally:
                pres.Close()
    finally:
        boot.Close()
        app.Quit()
    print(f"{len(made)}/{len(LAYOUTS)} templates written to {OUT}")
    return 0 if len(made) == len(LAYOUTS) else 1


if __name__ == "__main__":
    sys.exit(main())
