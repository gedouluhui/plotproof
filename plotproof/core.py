"""Pure checking entry point, NOT a file-level report or verified input loader.

Callers must validate the capture/PDF/font hashes and collect renderer facts.
The internal result lacks those provenance fields and is not a §11 report.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .alignment import align_units
from .evidence import GlyphEvidence, PdfChar, TextRecord
from .geometry import Rect, Transform
from .occlusion import FilledRecord
from .rules import Finding, detect_rules
from .units import AccountingError, enumerate_units


@dataclass(frozen=True)
class CoreResult:
    overall_state: str
    coverage: dict | None
    findings: tuple[Finding, ...]
    unknown_objects: tuple[dict, ...]
    errors: tuple[dict, ...]
    zero_unit_samples: int

    def to_dict(self) -> dict:
        result = asdict(self)
        result['findings'] = [dict(asdict(f), defect_class=f.defect_class, state=f.state) for f in self.findings]
        return result


def _check_references(records: Sequence[TextRecord], fills: Sequence[FilledRecord],
                      glyphs: Mapping[int, Sequence[GlyphEvidence]]) -> None:
    text_ids = {r.source_object_id for r in records}
    fill_by_id = {f.source_object_id: f for f in fills}
    if len(fill_by_id) != len(fills) or text_ids.intersection(fill_by_id):
        raise AccountingError('filled/text IDs are not one unique shared namespace')
    if set(glyphs) - text_ids:
        raise AccountingError('font evidence references an unknown text ID')
    for uid, evidence in glyphs.items():
        if type(uid) is not int or len({g.codepoint for g in evidence}) != len(evidence):
            raise AccountingError('font evidence IDs or code points are duplicated/invalid')
    for fill in fills:
        if fill.owner_unit_id is not None and fill.owner_unit_id not in text_ids:
            raise AccountingError('filled artist has an unknown owner')
    by_id = {r.source_object_id: r for r in records}
    for record in records:
        if record.background_patch_id is not None:
            patch = fill_by_id.get(record.background_patch_id)
            if patch is None or patch.owner_unit_id != record.source_object_id:
                raise AccountingError('background patch reference is inconsistent')
    for fill in fills:
        if fill.owner_unit_id is not None and by_id[fill.owner_unit_id].background_patch_id != fill.source_object_id:
            raise AccountingError('background patch ownership must be reciprocal')


def check_core(*, records: Sequence[TextRecord], chars: Sequence[PdfChar],
               fills: Sequence[FilledRecord], glyphs: Mapping[int, Sequence[GlyphEvidence]],
               transform: Transform, page: Rect, source_units_total: int,
               errors: Sequence[dict] = ()) -> CoreResult:
    """Evaluate validated in-memory facts; ERROR dominates all other states."""
    errors = tuple(dict(error) for error in errors)
    try:
        _check_references(records, fills, glyphs)
        units = enumerate_units(records, transform, page, source_units_total)
        alignment = align_units(units, chars, glyphs)
        coverage = alignment.coverage
        findings = detect_rules(alignment, page, fills, glyphs)
    except AccountingError as error:
        return CoreResult('ERROR', None, (), (), (*errors, {'stage': 'accounting', 'message': str(error)}), 0)
    unknown = tuple({'source_object_id': uid, 'reason': reason} for uid, reason in alignment.unknown.items())
    if errors:
        state = 'ERROR'
    elif any(f.confidence == 'high' for f in findings):
        state = 'FAIL'
    elif (findings or coverage['ratio'] is None or coverage['ratio'] < 0.90
          or coverage['unsupported_units'] > 0):
        state = 'UNKNOWN'
    else:
        state = 'PASS'
    return CoreResult(state, coverage, findings, unknown, errors, int(source_units_total == 0))
