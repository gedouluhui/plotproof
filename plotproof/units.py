"""Recompute the frozen ordered source-unit predicate without trusting wrapper totals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evidence import TextRecord
from .geometry import Rect, Transform


class AccountingError(ValueError):
    def __init__(self, detail: str):
        super().__init__('unit_accounting_mismatch: ' + detail)


@dataclass(frozen=True)
class Unit:
    record: TextRecord
    box_pdf: Rect
    unsupported_reason: str | None


@dataclass(frozen=True)
class UnitSet:
    units: tuple[Unit, ...]
    source_units_total: int


def exclusion_reason(record: TextRecord, transform: Transform, page: Rect) -> str | None:
    if not record.text.strip():
        return 'empty_text'
    if record.text_alpha <= 0 or record.artist_alpha <= 0:
        return 'alpha_nonpositive'
    if not record.visible:
        return 'invisible'
    if record.bbox_display.area == 0:
        return 'empty_extent'
    if transform.to_pdf(record.bbox_display).intersection(page) is None:
        return 'outside_page'
    if record.clip_box_display is not None and record.bbox_display.intersection(record.clip_box_display) is None:
        return 'fully_clipped'
    if record.tick_location is not None:
        low, high = sorted(record.view_limits)
        if not low <= record.tick_location <= high:
            return 'tick_outside_view'
    return None


def enumerate_units(records: Iterable[TextRecord], transform: Transform,
                    page: Rect, declared_total: int) -> UnitSet:
    if type(declared_total) is not int or declared_total < 0:
        raise AccountingError('source_units_total must be a nonnegative integer')
    units = []
    seen = set()
    for record in records:
        if record.source_object_id in seen:
            raise AccountingError('duplicate source_object_id')
        seen.add(record.source_object_id)
        reason = exclusion_reason(record, transform, page)
        if record.is_unit is not (reason is None) or record.exclusion_reason != reason:
            raise AccountingError(f'predicate disagreement for {record.source_object_id}')
        if reason is not None:
            continue
        unsupported = ('unsupported_rotated' if record.rotation != 0 else
                       'unsupported_mathtext' if '$' in record.text else None)
        units.append(Unit(record, transform.to_pdf(record.bbox_display), unsupported))
    if len(units) != declared_total:
        raise AccountingError('recomputed total differs from source_units_total')
    return UnitSet(tuple(sorted(units, key=lambda u: u.record.source_object_id)), declared_total)
