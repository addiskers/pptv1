"""EMU-based unit system. All engine-internal dimensions are integer EMU."""
from __future__ import annotations

EMU_PER_INCH = 914400
EMU_PER_PT = 12700
EMU_PER_CM = 360000

SLIDE_W_16_9 = 12192000  # 13.333 in
SLIDE_H_16_9 = 6858000   # 7.5 in


def pt(v: float) -> int:
    return round(v * EMU_PER_PT)


def inch(v: float) -> int:
    return round(v * EMU_PER_INCH)


def cm(v: float) -> int:
    return round(v * EMU_PER_CM)


def px(v: float, dpi: int = 96) -> int:
    return round(v * EMU_PER_INCH / dpi)


def to_pt(emu: int) -> float:
    return emu / EMU_PER_PT


def to_inch(emu: int) -> float:
    return emu / EMU_PER_INCH
