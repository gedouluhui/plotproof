"""Unrounded binary64 rectangle geometry in bottom-left PDF coordinates."""
from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
from typing import Iterable, Literal


def finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f'{name} must be numeric, not {type(value).__name__}')
    result = float(value)
    if not isfinite(result):
        raise ValueError(f'{name} must be finite')
    return result


@dataclass(frozen=True, order=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for name in ('x0', 'y0', 'x1', 'y1'):
            object.__setattr__(self, name, finite_number(getattr(self, name), name))
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError('rectangle edges must be ordered')
        if not isfinite(self.area):
            raise ValueError('rectangle area must be finite')

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 / 2 + self.x1 / 2, self.y0 / 2 + self.y1 / 2)

    def intersection(self, other: Rect) -> Rect | None:
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        return Rect(x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None

    def contains(self, other: Rect) -> bool:
        return (self.x0 <= other.x0 <= other.x1 <= self.x1
                and self.y0 <= other.y0 <= other.y1 <= self.y1)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1


def bounding_rect(boxes: Iterable[Rect]) -> Rect | None:
    boxes = tuple(b for b in boxes if b.area > 0)
    if not boxes:
        return None
    return Rect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                max(b.x1 for b in boxes), max(b.y1 for b in boxes))


def intersections(left: Iterable[Rect], right: Iterable[Rect]) -> tuple[Rect, ...]:
    right = tuple(right)
    return tuple(overlap for a in left for b in right
                 if (overlap := a.intersection(b)) is not None)


def union_area(boxes: Iterable[Rect]) -> float:
    """Exact axis-aligned sweep, not a raster estimate or sum of box areas."""
    boxes = tuple(sorted(set(b for b in boxes if b.area > 0)))
    xs = sorted({x for b in boxes for x in (b.x0, b.x1)})
    strips = []
    for x0, x1 in zip(xs, xs[1:]):
        intervals = sorted((b.y0, b.y1) for b in boxes if b.x0 < x1 and b.x1 > x0)
        if not intervals:
            continue
        start, end = intervals[0]
        lengths = []
        for low, high in intervals[1:]:
            if low > end:
                lengths.append(end - start)
                start, end = low, high
            else:
                end = max(end, high)
        lengths.append(end - start)
        strips.append((x1 - x0) * fsum(lengths))
    return fsum(strips)


def iou(left: Rect, right: Rect) -> float:
    overlap = left.intersection(right)
    if overlap is None or left.area == 0 or right.area == 0:
        return 0.0
    scale = max(left.area, right.area)
    fraction = overlap.area / scale
    return fraction / (left.area / scale + right.area / scale - fraction)


def boundary_evidence(box: Rect, page: Rect) -> Literal['high', 'medium'] | None:
    """The single D1 boundary predicate (§4); zero area is never evidence."""
    if box.area == 0:
        return None
    inside = box.intersection(page)
    outside = box.area - (inside.area if inside else 0.0)
    cx, cy = box.center
    center_outside = cx < page.x0 or cx > page.x1 or cy < page.y0 or cy > page.y1
    if (outside > 0 and outside >= 0.5 * box.area) or center_outside:
        return 'high'
    if outside > 0:
        return 'medium'
    return None


@dataclass(frozen=True)
class Transform:
    dpi: float
    x0_px: float
    y0_px: float

    def __post_init__(self) -> None:
        for name in ('dpi', 'x0_px', 'y0_px'):
            object.__setattr__(self, name, finite_number(getattr(self, name), name))
        if self.dpi <= 0:
            raise ValueError('dpi must be positive')

    def to_pdf(self, box: Rect) -> Rect:
        return Rect((box.x0 - self.x0_px) * 72 / self.dpi,
                    (box.y0 - self.y0_px) * 72 / self.dpi,
                    (box.x1 - self.x0_px) * 72 / self.dpi,
                    (box.y1 - self.y0_px) * 72 / self.dpi)

    def page_in_display(self, width_pt: float, height_pt: float) -> Rect:
        return Rect(self.x0_px, self.y0_px,
                    self.x0_px + width_pt * self.dpi / 72,
                    self.y0_px + height_pt * self.dpi / 72)
