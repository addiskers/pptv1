"""Font registry: (family, bold, italic) -> TTF file path.

The review's hard rule: every (family, weight) a theme uses MUST resolve to a
real font file, or we fail at startup — measuring with a substituted face
while PowerPoint renders the real one guarantees wrap mismatches.

Cross-platform: on Windows the real Segoe UI / Georgia files resolve from the
system Fonts dir. On Linux (EC2 deploy) those don't exist, so each family also
lists METRIC-COMPATIBLE clone filenames — Gelasio (=Georgia), Selawik/Carlito
(=Segoe UI/Calibri), Liberation/DejaVu — installed by deploy/setup_ec2.sh.
The clone keeps the same glyph advances, so wrapping still matches; the theme
JSON keeps the original family name so the output .pptx renders the real font
on any client that has it. Bundled fonts under assets/fonts/ resolve first.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BUNDLED_DIR = _REPO / "assets" / "fonts"

_WIN_FONT_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
]
_NIX_FONT_DIRS = [
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local" / "share" / "fonts",
    Path.home() / ".fonts",
]


def _search_dirs() -> list[Path]:
    """Bundled fonts first, then platform system dirs, then DECKENGINE_FONT_DIR
    (os.pathsep-separated) overrides for a custom deploy layout."""
    dirs = [_BUNDLED_DIR]
    dirs += _WIN_FONT_DIRS if sys.platform.startswith("win") else _NIX_FONT_DIRS
    extra = os.environ.get("DECKENGINE_FONT_DIR", "")
    dirs += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return [d for d in dirs if d.is_dir()]


# Known filename stems per (family, bold, italic). The FIRST existing file
# wins, so the real font is used on Windows and the metric clone elsewhere.
#
# HARD RULE: every stem listed for a family MUST be metric-compatible with
# it (verified deltas: Gelasio=Georgia 0.000%, Selawik=Segoe worst 0.28%,
# Carlito=Calibri 0.000%, LiberationSans=Arial 0.000%). The EC2 deck
# disaster came from Liberation Serif (Times-metric) standing in for
# Georgia: text measured 8-12% narrow, PowerPoint re-wrapped everything.
# A missing clone must FAIL LOUDLY, never silently mis-measure.
_KNOWN: dict[tuple[str, bool, bool], list[str]] = {
    ("Segoe UI", False, False): [
        "segoeui.ttf", "selawk.ttf", "Selawik-Regular.ttf"],
    ("Segoe UI", True, False): [
        "segoeuib.ttf", "selawkb.ttf", "Selawik-Bold.ttf"],
    # Selawik ships no italic: the upright file stands in (advance widths
    # of the SAME face — acceptable drift; house style caps italics anyway)
    ("Segoe UI", False, True): [
        "segoeuii.ttf", "seguisli.ttf", "selawk.ttf"],
    ("Segoe UI", True, True): [
        "segoeuiz.ttf", "selawkb.ttf"],
    ("Georgia", False, False): ["georgia.ttf", "Gelasio-Regular.ttf"],
    ("Georgia", True, False): ["georgiab.ttf", "Gelasio-Bold.ttf"],
    ("Georgia", False, True): ["georgiai.ttf", "Gelasio-Italic.ttf"],
    ("Georgia", True, True): ["georgiaz.ttf", "Gelasio-BoldItalic.ttf"],
    ("Arial", False, False): [
        "arial.ttf", "LiberationSans-Regular.ttf", "Arimo-Regular.ttf"],
    ("Arial", True, False): [
        "arialbd.ttf", "LiberationSans-Bold.ttf", "Arimo-Bold.ttf"],
    ("Arial", False, True): [
        "ariali.ttf", "LiberationSans-Italic.ttf", "Arimo-Italic.ttf"],
    ("Arial", True, True): [
        "arialbi.ttf", "LiberationSans-BoldItalic.ttf",
        "Arimo-BoldItalic.ttf"],
    ("Calibri", False, False): ["calibri.ttf", "Carlito-Regular.ttf"],
    ("Calibri", True, False): ["calibrib.ttf", "Carlito-Bold.ttf"],
    ("Calibri", False, True): ["calibrii.ttf", "Carlito-Italic.ttf"],
    ("Calibri", True, True): ["calibriz.ttf", "Carlito-BoldItalic.ttf"],
    # No OFL metric clone of Nirmala exists; Noto Devanagari is a GLYPH
    # fallback, not metric-compatible — themes using Nirmala are
    # Windows-only until licensed (documented limitation).
    ("Nirmala UI", False, False): [
        "Nirmala.ttf", "NirmalaS.ttf", "NotoSansDevanagari-Regular.ttf",
        "NotoSans-Regular.ttf"],
    ("Nirmala UI", True, False): [
        "NirmalaB.ttf", "NotoSansDevanagari-Bold.ttf", "NotoSans-Bold.ttf"],
    # markers (●◐○) render in Segoe UI Symbol; single glyphs at micro size,
    # measured with the same file that renders per-machine
    ("Segoe UI Symbol", False, False): ["seguisym.ttf", "DejaVuSans.ttf"],
}


class FontRegistry:
    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._dirs = _search_dirs() + [d for d in (extra_dirs or [])
                                       if d.is_dir()]
        self._index: dict[str, Path] | None = None
        self._cache: dict[tuple[str, bool, bool], Path] = {}
        self._overrides: dict[tuple[str, bool, bool], Path] = {}

    def _file_index(self) -> dict[str, Path]:
        """Lazy {lowercased filename -> path} across every search dir,
        recursively (Linux nests fonts in per-family subdirs). First dir wins,
        so bundled/system order is honored."""
        if self._index is None:
            idx: dict[str, Path] = {}
            for d in self._dirs:
                for p in d.rglob("*"):
                    if p.suffix.lower() in (".ttf", ".otf") and p.is_file():
                        idx.setdefault(p.name.lower(), p)
            self._index = idx
        return self._index

    def register(self, family: str, path: Path, *, bold: bool = False,
                 italic: bool = False) -> None:
        self._overrides[(family, bold, italic)] = path

    def resolve(self, family: str, *, bold: bool = False,
                italic: bool = False) -> Path:
        key = (family, bold, italic)
        if key in self._overrides:
            return self._overrides[key]
        if key in self._cache:
            return self._cache[key]
        index = self._file_index()
        for stem in _KNOWN.get(key, []):
            p = index.get(stem.lower())
            if p is not None:
                self._cache[key] = p
                return p
        raise FileNotFoundError(
            f"No font file for family={family!r} bold={bold} italic={italic}. "
            f"On Linux run deploy/setup_ec2.sh to install metric-compatible "
            f"fonts, drop a TTF in assets/fonts/, or FontRegistry.register() "
            f"one — measuring with a substituted face breaks the layout "
            f"contract."
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
