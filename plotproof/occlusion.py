"""Captured filled geometry in PDF points and conservative D2 contributions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .evidence import alpha, integer_id
from .geometry import Rect, finite_number, intersections, union_area
from .units import Unit


@dataclass(frozen=True)
class FilledRecord:
    source_object_id: int
    box_pdf: Rect
    artist_class: str
    path_kind: str
    path_is_concave: bool | None
    fancybox: bool | None
    facecolor_alpha: float
    artist_alpha: float
    paint_order: int | None
    filled_area: float | None
    owner_unit_id: int | None
    image_opacity: float | None

    def __post_init__(self) -> None:
        integer_id(self.source_object_id, 'source_object_id')
        for name in ('paint_order', 'owner_unit_id'):
            if getattr(self, name) is not None:
                integer_id(getattr(self, name), name)
        if not isinstance(self.box_pdf, Rect):
            raise TypeError('box_pdf must be a Rect')
        if self.path_kind not in ('axis_aligned_rectangle', 'legend_frame', 'other_filled_path', 'image'):
            raise ValueError('unknown path_kind')
        for name in ('path_is_concave', 'fancybox'):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise TypeError(f'{name} must be boolean or None')
        for name in ('facecolor_alpha', 'artist_alpha'):
            object.__setattr__(self, name, alpha(getattr(self, name)))
        if self.image_opacity is not None:
            object.__setattr__(self, 'image_opacity', alpha(self.image_opacity))
        if self.filled_area is not None:
            object.__setattr__(self, 'filled_area', finite_number(self.filled_area, 'filled_area'))
            if self.filled_area < 0:
                raise ValueError('filled_area cannot be negative')

    @property
    def effective_alpha(self) -> float | None:
        opacity = self.image_opacity if self.path_kind == 'image' else self.facecolor_alpha
        return opacity * self.artist_alpha if opacity is not None else None

    @property
    def supported_geometry(self) -> bool:
        if self.path_kind == 'axis_aligned_rectangle':
            return True
        if self.path_kind == 'legend_frame':
            return self.fancybox is False
        if self.path_kind == 'image':
            return self.image_opacity is not None
        return (self.path_is_concave is False and self.filled_area is not None
                and self.filled_area >= 0.95 * self.box_pdf.area)


def contributions(unit: Unit, boxes: Sequence[Rect], fills: Sequence[FilledRecord],
                  page: Rect) -> tuple[dict, ...]:
    area = union_area(boxes)
    if area == 0:
        return ()
    output = []
    for artist in sorted(fills, key=lambda a: a.source_object_id):
        effective = artist.effective_alpha
        if artist.owner_unit_id == unit.record.source_object_id:
            continue
        if effective is not None and effective < 0.50:
            continue
        if effective is None and artist.artist_alpha < 0.50:
            continue  # even opacity=1 cannot reach the evidence band
        order = unit.record.paint_order
        known_after = order is not None and artist.paint_order is not None and artist.paint_order > order
        if order is not None and artist.paint_order is not None and artist.paint_order < order:
            continue
        cut = intersections(boxes, (artist.box_pdf,))
        if not cut:
            continue
        coverage = union_area(cut) / area
        output.append({
            'source_object_id': artist.source_object_id,
            'rectangle': artist.box_pdf.as_tuple(), 'intersection_boxes': tuple(b.as_tuple() for b in cut),
            'coverage': coverage, 'effective_alpha': effective,
            'facecolor_alpha': artist.facecolor_alpha, 'artist_alpha': artist.artist_alpha,
            'image_opacity': artist.image_opacity, 'path_kind': artist.path_kind,
            'path_is_concave': artist.path_is_concave, 'fancybox': artist.fancybox,
            'filled_area': artist.filled_area, 'inside_page': page.contains(artist.box_pdf),
            'owner_unit_id': artist.owner_unit_id, 'paint_order': artist.paint_order,
            'text_paint_order': order, 'known_after': known_after,
            'high_eligible': (effective is not None and effective >= 0.95 and known_after
                              and artist.supported_geometry and page.contains(artist.box_pdf)
                              and coverage >= 0.90),
        })
    return tuple(output)
