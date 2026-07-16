"""Font registry: (family, bold, italic) -> TTF file path.

The review's hard rule: every (family, weight) a theme uses MUST resolve to a real
font file, or we fail at startup — measuring with a substituted face while
PowerPoint renders the real one guarantees wrap mismatches.
"""
from __future__ import annotations

import os
from pathlib import Path

_WIN_FONT_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
]

# Known filename stems for the families we ship themes for.
_KNOWN: dict[tuple[str, bool, bool], list[str]] = {
    ("Segoe UI", False, False): ["segoeui.ttf"],
    ("Segoe UI", True, False): ["segoeuib.ttf"],
    ("Segoe UI", False, True): ["segoeuii.ttf"],
    ("Segoe UI", True, True): ["segoeuiz.ttf"],
    ("Georgia", False, False): ["georgia.ttf"],
    ("Georgia", True, False): ["georgiab.ttf"],
    ("Georgia", False, True): ["georgiai.ttf"],
    ("Georgia", True, True): ["georgiaz.ttf"],
    ("Arial", False, False): ["arial.ttf"],
    ("Arial", True, False): ["arialbd.ttf"],
    ("Arial", False, True): ["ariali.ttf"],
    ("Arial", True, True): ["arialbi.ttf"],
    ("Calibri", False, False): ["calibri.ttf"],
    ("Calibri", True, False): ["calibrib.ttf"],
    ("Nirmala UI", False, False): ["Nirmala.ttf", "NirmalaS.ttf"],
    ("Nirmala UI", True, False): ["NirmalaB.ttf"],
}


class FontRegistry:
    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._dirs = [d for d in (_WIN_FONT_DIRS + (extra_dirs or [])) if d.is_dir()]
        self._cache: dict[tuple[str, bool, bool], Path] = {}
        self._overrides: dict[tuple[str, bool, bool], Path] = {}

    def register(self, family: str, path: Path, *, bold: bool = False,
                 italic: bool = False) -> None:
        self._overrides[(family, bold, italic)] = path

    def resolve(self, family: str, *, bold: bool = False, italic: bool = False) -> Path:
        key = (family, bold, italic)
        if key in self._overrides:
            return self._overrides[key]
        if key in self._cache:
            return self._cache[key]
        for stem in _KNOWN.get(key, []):
            for d in self._dirs:
                p = d / stem
                if p.is_file():
                    self._cache[key] = p
                    return p
        raise FileNotFoundError(
            f"No font file for family={family!r} bold={bold} italic={italic}. "
            f"Register one explicitly via FontRegistry.register() — measuring with a "
            f"substituted face breaks the layout contract."
        )

    def validate_theme(self, theme) -> None:
        """Fail loudly at startup if any theme font/weight lacks a real file."""
        for fam in (theme.font_display, theme.font_body):
            for bold in (False, True):
                self.resolve(fam, bold=bold)


_default: FontRegistry | None = None


def default_registry() -> FontRegistry:
    global _default
    if _default is None:
        _default = FontRegistry()
    return _default
