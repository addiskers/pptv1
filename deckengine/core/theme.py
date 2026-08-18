"""Theme system. Components reference semantic ROLES, never hex codes.

One theme JSON = entire deck rebrand. Zero hex codes or font names anywhere else.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .units import inch

THEMES_DIR = Path(__file__).resolve().parents[2] / "themes"


@dataclass
class Theme:
    name: str
    # semantic colors (hex strings "RRGGBB")
    color_bg: str
    color_surface: str
    color_surface_alt: str
    color_ink: str
    color_ink_muted: str
    color_primary: str
    color_primary_dark: str
    color_accent: str
    color_positive: str
    color_negative: str
    color_grid: str
    color_inverse_ink: str
    color_highlight: str = "F2D024"  # pill behind emphasised numbers (yellow)
    # semantic mid-tier between negative and positive (moderate/watch/mixed);
    # class default so the 11 theme JSONs need no edits
    color_warning: str = "B45309"
    badge_palette: dict[str, str] = field(default_factory=dict)
    heatmap_scale: list[str] = field(default_factory=list)  # low -> high

    font_display: str = "Georgia"
    font_body: str = "Segoe UI"

    size_title: float = 20.0
    size_h2: float = 14.0
    size_stat: float = 13.5
    size_body: float = 10.0
    size_small: float = 9.0
    size_micro: float = 7.5
    size_kicker: float = 8.5  # small-caps eyebrow line above the title

    unit: int = inch(0.1)  # base spacing unit; all gaps are multiples

    def has_color(self, role: str) -> bool:
        """True when `role` resolves without the fallback — probes (like
        legend_row's code-vs-cycle choice) use this, never try/except."""
        attr = f"color_{role}" if not role.startswith("color_") else role
        return hasattr(self, attr) or role in self.badge_palette

    def color(self, role: str) -> str:
        """Resolve a semantic role name to a hex string. An unknown role
        falls back to ink with a warning — the LLM sometimes invents a
        role name, and a whole deck must never die over a string (seen
        live: KeyError 'safe' killed a variant mid-render)."""
        attr = f"color_{role}" if not role.startswith("color_") else role
        if hasattr(self, attr):
            return getattr(self, attr)
        if role in self.badge_palette:
            return self.badge_palette[role]
        import logging
        logging.getLogger("deckengine").warning(
            "unknown color role %r — falling back to ink", role)
        return self.color_ink

    def soft(self, role: str, frac: float = 0.15) -> str:
        """A tint of `role` blended toward the background — the harmonized
        'soft accent' every theme gets for free (emphasis row fills etc.);
        no theme JSON edits needed."""
        fg = self.color(role)
        bg = self.color("bg")
        mix = [round(int(bg[i:i + 2], 16) * (1 - frac)
                     + int(fg[i:i + 2], 16) * frac) for i in (0, 2, 4)]
        return "".join(f"{c:02X}" for c in mix)

    def heatmap_color(self, value: float, lo: float = 0.0, hi: float = 1.0) -> str:
        """Map a value in [lo, hi] onto the heatmap scale."""
        if not self.heatmap_scale:
            raise ValueError(f"theme {self.name} has no heatmap_scale")
        if hi <= lo:
            idx = 0
        else:
            frac = min(1.0, max(0.0, (value - lo) / (hi - lo)))
            idx = min(len(self.heatmap_scale) - 1,
                      int(frac * len(self.heatmap_scale)))
        return self.heatmap_scale[idx]

    def spacing(self, multiple: float = 1.0) -> int:
        return round(self.unit * multiple)


def load_theme(name: str, themes_dir: Path | None = None) -> Theme:
    path = (themes_dir or THEMES_DIR) / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Theme(name=name, **data)
