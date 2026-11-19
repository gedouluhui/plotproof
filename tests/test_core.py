from dataclasses import replace
import json

import pytest

from _core_fixtures import module, text_record, pdf_chars, glyph_evidence, Rect, Transform
from test_rules import occluder


def check(records, chars=(), fills=(), glyphs=None, **changes):
    options = {'records': records, 'chars': chars, 'fills': fills, 'glyphs': glyphs or {},
               'transform': Transform(72, 0, 0), 'page': Rect(0, 0, 1000, 1000),
               'source_units_total': sum(r.is_unit for r in records), 'errors': ()}
    options.update(changes)
    return module('core').check_core(**options)


def test_core_pass_means_no_findings_and_complete_coverage():
    result = check((text_record(),), pdf_chars())
    assert result.overall_state == 'PASS'
    assert result.coverage['ratio'] == 1
    assert result.findings == () and result.unknown_objects == () and result.errors == ()
    assert json.loads(json.dumps(result.to_dict(), allow_nan=False))['overall_state'] == 'PASS'


def test_core_missing_glyph_without_remaining_text_is_unknown_not_high_or_pass():
    record = text_record(text='𠀀', box=Rect(10, 10, 20, 20))
    for chars in ((), pdf_chars('𠀀')):
        result = check((record,), chars, glyphs={1: (glyph_evidence(),)})
        assert result.overall_state == 'UNKNOWN'
        assert [(f.rule_id, f.confidence) for f in result.findings] == [('D4', 'medium')]
        assert result.coverage['ratio'] == 0
        assert result.unknown_objects == ({'source_object_id': 1, 'reason': 'no_text_match'},)


def test_empty_and_unsupported_units_never_pass():
    empty = check(())
    assert empty.overall_state == 'UNKNOWN' and empty.coverage['ratio'] is None
    assert empty.zero_unit_samples == 1
    for changes in ({'rotation': 90}, {'text': '$x$'}):
        result = check((text_record(**changes),), pdf_chars())
        assert result.overall_state == 'UNKNOWN'
        assert result.coverage['unsupported_units'] == 1


def test_coverage_threshold_and_unknown_objects_are_not_hidden():
    records = tuple(text_record(i, str(i), Rect(10 + i * 30, 10, 20 + i * 30, 20)) for i in range(10))
    chars = tuple(module('evidence').PdfChar(str(i), r.bbox_display) for i, r in enumerate(records))
    at_gate = check(records, chars[:-1])
    assert at_gate.overall_state == 'PASS'
    assert at_gate.coverage['ratio'] == 0.9 and len(at_gate.unknown_objects) == 1
    assert check(records, chars[:-2]).overall_state == 'UNKNOWN'
    unsupported = check((*records[:-1], replace(records[-1], rotation=90)), chars)
    assert unsupported.coverage['ratio'] == 0.9
    assert unsupported.overall_state == 'UNKNOWN'


def test_high_finding_outvotes_unknown_but_never_error():
    records = (text_record(1, 'a', Rect(10, 10, 20, 20)), text_record(2, 'unknown', Rect(50, 10, 60, 20)))
    result = check(records, pdf_chars('a'), (occluder(),))
    assert result.overall_state == 'FAIL'
    assert result.unknown_objects == ({'source_object_id': 2, 'reason': 'no_text_match'},)
    bad = check(records, pdf_chars('a'), (occluder(),), errors=({'stage': 'font', 'message': 'font_unavailable'},))
    assert bad.overall_state == 'ERROR'
    assert bad.errors[0]['message'] == 'font_unavailable'


@pytest.mark.parametrize('change', ['total', 'predicate', 'duplicate_text', 'fill_id', 'background', 'glyph_id'])
def test_invalid_accounting_returns_error_not_exception_or_pass(change):
    records = (text_record(),)
    options = {}
    if change == 'total':
        options['source_units_total'] = 2
    elif change == 'predicate':
        records = (text_record(is_unit=False, exclusion_reason='invisible'),)
    elif change == 'duplicate_text':
        records = (text_record(), text_record())
    elif change == 'fill_id':
        options['fills'] = (occluder(1),)
    elif change == 'background':
        records = (text_record(background_patch_id=99),)
    elif change == 'glyph_id':
        options['glyphs'] = {99: (glyph_evidence(),)}
    result = check(records, pdf_chars(), **options)
    assert result.overall_state == 'ERROR'
    assert result.errors and 'unit_accounting_mismatch' in result.errors[0]['message']
    assert result.coverage is None  # do not invent reconciled counts after a mismatch


def test_medium_finding_survives_90_percent_coverage():
    e = module('evidence')
    records = [text_record(0, '𠀀', Rect(10, 10, 20, 20))]
    records += [text_record(i, str(i), Rect(10 + i * 30, 10, 20 + i * 30, 20)) for i in range(1, 10)]
    chars = tuple(e.PdfChar(r.text, r.bbox_display) for r in records[1:])
    result = check(tuple(records), chars, glyphs={0: (glyph_evidence(),)})
    assert result.coverage['ratio'] == 0.9
    assert result.overall_state == 'UNKNOWN'
    assert result.findings[0].rule_id == 'D4'


def test_importing_core_does_not_load_rendering_stack():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c',
        "import sys; import plotproof.core; assert not any(m in sys.modules for m in "
        "('matplotlib','numpy','pypdfium2','fontTools','PIL'))"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
