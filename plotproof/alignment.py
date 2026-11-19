"""Frozen §7.1 canonicalization, candidate search and deterministic assignment."""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from statistics import median
from types import MappingProxyType
from typing import Mapping, Sequence
import unicodedata

from .evidence import GlyphEvidence, PdfChar
from .geometry import Rect, iou
from .units import AccountingError, Unit, UnitSet

REASONS = ('no_text_match', 'height_mismatch', 'low_overlap', 'ambiguous', 'conflict',
           'unsupported_rotated', 'unsupported_mathtext')


@dataclass(frozen=True)
class Canonical:
    text: str
    original_to_canonical: tuple[int | None, ...]


def canonicalize(text: str, *, source: bool) -> Canonical:
    start, end = 0, len(text)
    if source:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
    chars: list[str] = []
    mapping: list[int | None] = [None] * len(text)
    for index in range(start, end):
        c = ' ' if text[index].isspace() else text[index]
        if c == ' ' and chars and chars[-1] == ' ':
            mapping[index] = len(chars) - 1
            continue
        normalized = unicodedata.normalize('NFKC', c)
        chars.append(normalized if len(normalized) == 1 else c)
        mapping[index] = len(chars) - 1
    return Canonical(''.join(chars), tuple(mapping))


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    boxes: tuple[Rect, ...]
    box: Rect
    iou: float
    canonical_text: str
    source_map: tuple[int | None, ...]
    removed_codepoints: tuple[int, ...]


@dataclass(frozen=True)
class AlignmentResult:
    units: UnitSet
    assignments: Mapping[int, Span]
    unknown: Mapping[int, str]
    pdf_canonical: Canonical

    def __post_init__(self) -> None:
        object.__setattr__(self, 'assignments', MappingProxyType(dict(self.assignments)))
        object.__setattr__(self, 'unknown', MappingProxyType(dict(self.unknown)))
        ids = {unit.record.source_object_id for unit in self.units.units}
        if (set(self.assignments) & set(self.unknown)
                or set(self.assignments) | set(self.unknown) != ids
                or len(ids) != self.units.source_units_total
                or any(reason not in REASONS for reason in self.unknown.values())):
            raise AccountingError('alignment result does not partition source units')

    @property
    def coverage(self) -> dict:
        counts = {reason: sum(r == reason for r in self.unknown.values()) for reason in REASONS}
        total = self.units.source_units_total
        aligned = len(self.assignments)
        return {'source_units_total': total, 'total_units': total, 'aligned_units': aligned,
                'unaligned_units': sum(counts[r] for r in REASONS[:5]),
                'unsupported_units': sum(counts[r] for r in REASONS[5:]),
                'unaligned_by_reason': counts, 'ratio': aligned / total if total else None}


def _source_searches(unit: Unit, glyphs: Sequence[GlyphEvidence]) -> list[tuple[Canonical, tuple[int, ...]]]:
    text = unit.record.text
    searches = [(canonicalize(text, source=True), ())]
    removed = tuple(sorted({g.codepoint for g in glyphs if g.proven_missing and chr(g.codepoint) in text}))
    if removed:
        kept_indices = [i for i, c in enumerate(text) if ord(c) not in removed]
        reduced = canonicalize(''.join(text[i] for i in kept_indices), source=True)
        if not reduced.text:
            return []  # §7.1 explicit empty-remainder exception, even if PDF emits tofu text
        mapping: list[int | None] = [None] * len(text)
        for i, original in enumerate(kept_indices):
            mapping[original] = reduced.original_to_canonical[i]
        searches.append((Canonical(reduced.text, tuple(mapping)), removed))
    return searches


def _candidates(unit: Unit, chars: Sequence[PdfChar], pdf: Canonical,
                indices: Sequence[Sequence[int]], glyphs: Sequence[GlyphEvidence]
                ) -> tuple[list[Span], list[Span], str]:
    all_spans: dict[tuple[int, int], Span] = {}
    valid: dict[tuple[int, int], Span] = {}
    had_height = False
    for source, removed in _source_searches(unit, glyphs):
        if not source.text:
            continue
        offset = 0
        while (position := pdf.text.find(source.text, offset)) != -1:
            offset = position + 1
            start = indices[position][0]
            end = indices[position + len(source.text) - 1][-1] + 1
            boxes = tuple(c.box for c in chars[start:end])
            # Span bounding box includes the original stream's degenerate boxes.
            # D1 and union-area consumers independently discard zero-area evidence.
            box = Rect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                       max(b.x1 for b in boxes), max(b.y1 for b in boxes))
            overlap = iou(box, unit.box_pdf)
            span = Span(start, end, boxes, box, overlap, source.text,
                        source.original_to_canonical, removed)
            all_spans.setdefault((start, end), span)
            heights = [b.y1 - b.y0 for b in boxes if b.y1 > b.y0]
            height_ok = bool(heights) and 0.20 <= median(heights) / unit.record.font_size_pt <= 1.50
            had_height |= height_ok
            if height_ok and overlap >= 0.50:
                valid.setdefault((start, end), span)
    reason = 'no_text_match' if not all_spans else 'low_overlap' if had_height else 'height_mismatch'
    return list(valid.values()), list(all_spans.values()), reason


def align_units(units: UnitSet, chars: Sequence[PdfChar],
                glyphs: Mapping[int, Sequence[GlyphEvidence]] | None = None) -> AlignmentResult:
    glyphs = glyphs or {}
    pdf = canonicalize(''.join(c.text for c in chars), source=False)
    indices: list[list[int]] = [[] for _ in pdf.text]
    for original, canonical in enumerate(pdf.original_to_canonical):
        indices[canonical].append(original)
    unknown: dict[int, str] = {}
    valid_by_unit: dict[int, list[Span]] = {}
    all_by_unit: dict[int, list[Span]] = {}
    pairs = []
    for unit in units.units:
        uid = unit.record.source_object_id
        if unit.unsupported_reason:
            unknown[uid] = unit.unsupported_reason
            continue
        valid, all_spans, reason = _candidates(unit, chars, pdf, indices, glyphs.get(uid, ()))
        valid_by_unit[uid] = sorted(valid, key=lambda s: (-s.iou, s.start))
        all_by_unit[uid] = all_spans
        if not valid:
            unknown[uid] = reason
        else:
            pairs.extend((uid, span) for span in valid)
    pairs.sort(key=lambda pair: (-pair[1].iou, pair[0], pair[1].start))
    assignments: dict[int, Span] = {}
    taken = set()
    for uid, span in pairs:
        key = span.start, span.end
        if uid not in assignments and key not in taken:
            assignments[uid] = span
            taken.add(key)
    for uid, valid in valid_by_unit.items():
        if valid and uid not in assignments:
            unknown[uid] = 'conflict'
    for uid, assigned in tuple(assignments.items()):
        indistinguishable = any(
            (other.start, other.end) != (assigned.start, assigned.end)
            and other.canonical_text == assigned.canonical_text
            and all(abs(a - b) <= 1.0 for a, b in zip(other.box.as_tuple(), assigned.box.as_tuple()))
            for other in all_by_unit[uid])
        best = valid_by_unit[uid][:2]
        tied = (len(best) == 2 and hypot(best[0].box.center[0] - best[1].box.center[0],
                                       best[0].box.center[1] - best[1].box.center[1]) <= 2.0
                and abs(best[0].iou - best[1].iou) < 0.02)
        if indistinguishable or tied:
            del assignments[uid]
            unknown[uid] = 'ambiguous'
    return AlignmentResult(units, assignments, dict(sorted(unknown.items())), pdf)
