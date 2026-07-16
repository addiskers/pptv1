"""Immutable bounding-box algebra. Every layout decision is BBox math.

No component ever computes absolute slide coordinates itself: it receives a BBox
and may only subdivide it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BBox:
    x: int
    y: int
    w: int
    h: int  # all EMU

    def __post_init__(self) -> None:
        if self.w < 0 or self.h < 0:
            raise ValueError(f"negative BBox dimensions: {self}")

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def inset(self, all: int | None = None, *, top: int = 0, right: int = 0,
              bottom: int = 0, left: int = 0) -> "BBox":
        if all is not None:
            top = right = bottom = left = all
        return BBox(self.x + left, self.y + top,
                    max(0, self.w - left - right), max(0, self.h - top - bottom))

    def cols(self, n: int, gap: int = 0) -> list["BBox"]:
        """n equal-width columns with `gap` EMU between them."""
        return self.split_h(*([1.0] * n), gap=gap)

    def rows(self, n: int, gap: int = 0) -> list["BBox"]:
        return self.split_v(*([1.0] * n), gap=gap)

    def split_h(self, *fractions: float, gap: int = 0) -> list["BBox"]:
        """Split horizontally (side by side) by relative fractions."""
        total = sum(fractions)
        usable = self.w - gap * (len(fractions) - 1)
        out: list[BBox] = []
        cursor = self.x
        for i, f in enumerate(fractions):
            w = round(usable * f / total)
            if i == len(fractions) - 1:  # absorb rounding into last cell
                w = self.right - cursor
            out.append(BBox(cursor, self.y, w, self.h))
            cursor += w + gap
        return out

    def split_v(self, *fractions: float, gap: int = 0) -> list["BBox"]:
        """Split vertically (stacked) by relative fractions."""
        total = sum(fractions)
        usable = self.h - gap * (len(fractions) - 1)
        out: list[BBox] = []
        cursor = self.y
        for i, f in enumerate(fractions):
            h = round(usable * f / total)
            if i == len(fractions) - 1:
                h = self.bottom - cursor
            out.append(BBox(self.x, cursor, self.w, h))
            cursor += h + gap
        return out

    def take_top(self, h: int) -> tuple["BBox", "BBox"]:
        h = min(h, self.h)
        return (BBox(self.x, self.y, self.w, h),
                BBox(self.x, self.y + h, self.w, self.h - h))

    def take_bottom(self, h: int) -> tuple["BBox", "BBox"]:
        h = min(h, self.h)
        return (BBox(self.x, self.bottom - h, self.w, h),
                BBox(self.x, self.y, self.w, self.h - h))

    def take_left(self, w: int) -> tuple["BBox", "BBox"]:
        w = min(w, self.w)
        return (BBox(self.x, self.y, w, self.h),
                BBox(self.x + w, self.y, self.w - w, self.h))

    def take_right(self, w: int) -> tuple["BBox", "BBox"]:
        w = min(w, self.w)
        return (BBox(self.right - w, self.y, w, self.h),
                BBox(self.x, self.y, self.w - w, self.h))

    def with_height(self, h: int) -> "BBox":
        return BBox(self.x, self.y, self.w, h)

    def contains(self, other: "BBox", tolerance: int = 0) -> bool:
        return (other.x >= self.x - tolerance and other.y >= self.y - tolerance
                and other.right <= self.right + tolerance
                and other.bottom <= self.bottom + tolerance)
