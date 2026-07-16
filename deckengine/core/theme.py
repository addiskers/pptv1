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

    unit: int = inch(0.1)  # base spacing unit; all gaps are multiples

    def color(self, role: str) -> str:
        """Resolve a semantic role name to a hex string."""
        attr = f"color_{role}" if not role.startswith("color_") else role
        if hasattr(self, attr):
            return getattr(self, attr)
        if role in self.badge_palette:
            return self.badge_palette[role]
        raise KeyError(f"unknown color role: {role!r}")

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
