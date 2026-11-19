"""D1–D4 pure evidence rules. Inputs must already have capture provenance verified."""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import Mapping, Sequence

from .alignment import AlignmentResult
from .evidence import GlyphEvidence
from .geometry import Rect, boundary_evidence, bounding_rect, intersections, union_area
from .occlusion import FilledRecord, contributions
from .units import Unit

CLASSES = {'D1': 'clipped_text', 'D2': 'occluded_text',
           'D3': 'overlapping_text', 'D4': 'missing_glyph'}
PRIORITY = {'D1': 0, 'D4': 1, 'D2': 2, 'D3': 3}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    source_object_id: int
    related_source_object_id: int | None
    confidence: str
    box_pdf_points: tuple[float, float, float, float]
    source_text: str
    evidence: dict

    @property
    def defect_class(self) -> str:
        return CLASSES[self.rule_id]

    @property
    def state(self) -> str:
        return 'FAIL' if self.confidence == 'high' else 'UNKNOWN'


def _finding(rule: str, unit: Unit, confidence: str, box: Rect, evidence: dict,
             related: int | None = None) -> Finding:
    return Finding(rule, unit.record.source_object_id, related, confidence,
                   box.as_tuple(), unit.record.text, evidence)


def _d1(unit: Unit, boxes: Sequence[Rect], page: Rect) -> Finding | None:
    selected = {'high': [], 'medium': []}
    for box in boxes:
        band = boundary_evidence(box, page)
        if band:
            selected[band].append(box)
    confidence = 'high' if selected['high'] else 'medium'
    boxes = selected[confidence]
    bound = bounding_rect(boxes)
    if bound is None:
        return None
    evidence = {'page_rectangle': page.as_tuple(), 'boundary_boxes': tuple({
        'box': box.as_tuple(), 'area': box.area,
        'inside_area': inside.area if (inside := box.intersection(page)) else 0.0,
        'center': box.center} for box in boxes)}
    return _finding('D1', unit, confidence, bound, evidence)


def _d2(unit: Unit, boxes: Sequence[Rect], fills: Sequence[FilledRecord], page: Rect) -> Finding | None:
    artists = contributions(unit, boxes, fills, page)
    if not artists:
        return None
    cuts = tuple(Rect(*b) for artist in artists for b in artist['intersection_boxes'])
    area = union_area(boxes)
    joint = union_area(cuts) / area
    if joint < 0.50:
        return None
    high = any(artist['high_eligible'] for artist in artists)
    # Unknown-opacity intersections are possible, not confirmed coverage.
    confirmed = tuple(Rect(*b) for artist in artists if artist['effective_alpha'] is not None
                      for b in artist['intersection_boxes'])
    return _finding('D2', unit, 'high' if high else 'medium', bounding_rect(cuts), {
        'character_boxes': tuple(b.as_tuple() for b in boxes), 'occluders': artists,
        'joint_coverage': joint, 'confirmed_joint_coverage': union_area(confirmed) / area,
        'coverage_has_unknown_opacity': any(a['effective_alpha'] is None for a in artists),
        'page_rectangle': page.as_tuple(),
    })


def _d3(left: Unit, right: Unit, alignment: AlignmentResult,
        fills: Sequence[FilledRecord]) -> Finding | None:
    left_span = alignment.assignments.get(left.record.source_object_id)
    right_span = alignment.assignments.get(right.record.source_object_id)
    aligned = left_span is not None and right_span is not None
    a = left_span.boxes if aligned else (left.box_pdf,)
    b = right_span.boxes if aligned else (right.box_pdf,)
    smaller = min(union_area(a), union_area(b))
    if smaller == 0:
        return None
    cuts = intersections(a, b)
    ratio = union_area(cuts) / smaller
    if ratio < 0.15:
        return None
    witness = None
    if aligned:
        for first in a:
            for second in b:
                overlap = first.intersection(second)
                if overlap is not None and overlap.x1 - overlap.x0 >= 0.5 and overlap.y1 - overlap.y0 >= 0.5:
                    witness = (first.as_tuple(), second.as_tuple())
                    break
            if witness:
                break
    own_backgrounds = []
    for patch in sorted(fills, key=lambda fill: fill.source_object_id):
        if patch.owner_unit_id not in (left.record.source_object_id, right.record.source_object_id):
            continue
        effective = patch.facecolor_alpha * patch.artist_alpha
        intersects = bool(intersections(cuts, (patch.box_pdf,)))
        own_backgrounds.append({'owner_unit_id': patch.owner_unit_id,
            'source_object_id': patch.source_object_id, 'rectangle': patch.box_pdf.as_tuple(),
            'effective_alpha': effective, 'facecolor_alpha': patch.facecolor_alpha,
            'artist_alpha': patch.artist_alpha, 'intersects_overlap': intersects})
    demoted = any(p['effective_alpha'] >= 0.95 and p['intersects_overlap'] for p in own_backgrounds)
    high = aligned and ratio >= 0.50 and witness is not None and not demoted
    bound = bounding_rect(cuts)
    return _finding('D3', left, 'high' if high else 'medium', bound, {
        'operand_set': 'char_unions' if aligned else 'source_bboxes',
        'left_boxes': tuple(box.as_tuple() for box in a),
        'right_boxes': tuple(box.as_tuple() for box in b),
        'intersection_boxes': tuple(box.as_tuple() for box in cuts),
        'intersection_box': bound.as_tuple(), 'smaller_area': smaller, 'ratio': ratio,
        'character_pair': witness, 'own_backgrounds': tuple(own_backgrounds),
        'related_source_text': right.record.text,
    }, related=right.record.source_object_id)


def _d4(unit: Unit, aligned: bool, glyphs: Sequence[GlyphEvidence]) -> list[Finding]:
    output = []
    for glyph in sorted(glyphs, key=lambda g: g.codepoint):
        if chr(glyph.codepoint) not in unit.record.text:
            continue
        # §4 D4's explicit legal-fallback example qualifies the general
        # stack-disagreement medium case: confirmed supply + no warning is legal.
        supplied_without_warning = (
            all(font.file_id is not None for font in glyph.fonts)
            and any(font.glyph_id is not None and font.glyph_id > 0 for font in glyph.fonts)
            and not glyph.codepoint_warnings)
        if supplied_without_warning:
            continue
        has_missing = any(font.missing for font in glyph.fonts)
        if not has_missing and not glyph.codepoint_warnings:
            continue
        # Without alignment only the explicitly proven-missing exception may emit.
        if not aligned and not glyph.proven_missing:
            continue
        confidence = 'high' if aligned and glyph.proven_missing else 'medium'
        output.append(_finding('D4', unit, confidence, unit.box_pdf, {
            'codepoint': glyph.codepoint,
            'fonts': tuple({'family': font.family, 'file_id': font.file_id,
                            'glyph_id': font.glyph_id, 'missing': font.missing} for font in glyph.fonts),
            'resolved_families': tuple(font.family for font in glyph.fonts),
            'warnings': tuple({'category': w.category, 'message': w.message} for w in glyph.codepoint_warnings),
            'naming_warning': bool(glyph.naming_warnings),
            'source_bbox_pdf_points': unit.box_pdf.as_tuple(), 'unique_alignment': aligned,
        }))
    return output


def apply_precedence(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    ordered = sorted(findings, key=lambda f: (PRIORITY[f.rule_id], f.source_object_id,
        -1 if f.related_source_object_id is None else f.related_source_object_id, f.confidence,
        f.box_pdf_points))
    kept: list[Finding] = []
    for finding in ordered:
        members = {finding.source_object_id, finding.related_source_object_id} - {None}
        suppressor = next((index for index, higher in enumerate(kept)
            if higher.confidence == finding.confidence and PRIORITY[higher.rule_id] < PRIORITY[finding.rule_id]
            and members.intersection({higher.source_object_id, higher.related_source_object_id} - {None})), None)
        if suppressor is None:
            kept.append(finding)
        else:
            prior = kept[suppressor]
            note = {'rule_id': finding.rule_id, 'source_object_id': finding.source_object_id,
                    'related_source_object_id': finding.related_source_object_id, 'confidence': finding.confidence}
            kept[suppressor] = replace(prior, evidence={**prior.evidence,
                'suppressed': (*prior.evidence.get('suppressed', ()), note)})
    return tuple(kept)


def detect_rules(alignment: AlignmentResult, page: Rect,
                 fills: Sequence[FilledRecord], glyphs: Mapping[int, Sequence[GlyphEvidence]]) -> tuple[Finding, ...]:
    supported = sorted((u for u in alignment.units.units if not u.unsupported_reason),
                       key=lambda u: u.record.source_object_id)
    findings = []
    for unit in supported:
        uid = unit.record.source_object_id
        span = alignment.assignments.get(uid)
        if span is not None:
            for candidate in (_d1(unit, span.boxes, page), _d2(unit, span.boxes, fills, page)):
                if candidate:
                    findings.append(candidate)
        findings.extend(_d4(unit, span is not None, glyphs.get(uid, ())))
    for left, right in combinations(supported, 2):
        if candidate := _d3(left, right, alignment, fills):
            findings.append(candidate)
    return apply_precedence(findings)
