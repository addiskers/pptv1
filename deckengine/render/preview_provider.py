"""Preview-exporter selection seam.

One place decides how slide PNGs get rendered, so the API and the vision judge
stay provider-agnostic:

  DECKENGINE_PREVIEW = com | soffice | none | auto   (default: auto)

- com     : real PowerPoint via COM (Windows dev box; the golden oracle)
- soffice : headless LibreOffice -> pdf -> pypdfium2 (Linux / EC2)
- none    : previews disabled (generation still works; judge falls back to
            the deterministic pick)
- auto    : COM if it looks available, else soffice if installed, else none

get_preview_exporter() returns a callable
(pptx, out_dir, width, height) -> list[Path], or None when previews are off.
"""
from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

Exporter = Callable[..., list[Path]]


def _com_available() -> bool:
    return sys.platform.startswith("win") and shutil.which("powershell") is not None


def _soffice_available() -> bool:
    binary = os.environ.get("DECKENGINE_SOFFICE", "soffice")
    return shutil.which(binary) is not None


def get_preview_exporter() -> Exporter | None:
    mode = os.environ.get("DECKENGINE_PREVIEW", "auto").lower()
    if mode == "none":
        return None
    if mode == "com":
        from .preview import export_pngs_powerpoint
        return export_pngs_powerpoint
    if mode == "soffice":
        from .preview_soffice import export_pngs_soffice
        return export_pngs_soffice
    # auto
    if _com_available():
        from .preview import export_pngs_powerpoint
        return export_pngs_powerpoint
    if _soffice_available():
        from .preview_soffice import export_pngs_soffice
        return export_pngs_soffice
    return None
