from dataclasses import replace
from itertools import permutations

import pytest

from _core_fixtures import module, text_record, pdf_chars, glyph_evidence, Rect, Transform


def align(records, chars, glyphs=None, dpi=72):
    units = module('units').enumerate_units(records, Transform(dpi, 0, 0),
                                           Rect(0, 0, 1000, 1000), len(records))
    return module('alignment').align_units(units, chars, glyphs or {})


def test_canonical_mapping_preserves_collapsed_whitespace_and_ligatures():
    a = module('alignment')
    source = a.canonicalize(' \tＡ\n\r  ﬁ e\u0301  ', source=True)
    assert source.text == 'A ﬁ e\u0301'
    assert source.original_to_canonical == (None, None, 0, 1, 1, 1, 1, 2, 3, 4, 5, None, None)
    pdf = a.canonicalize(' \r\nＡ\t ﬁ ', source=False)
    assert pdf.text == ' A ﬁ '
    assert pdf.original_to_canonical == (0, 0, 0, 1, 2, 2, 3, 4)
    assert a.canonicalize('ﬃ①ß', source=True).text == 'ﬃ1ß'


def test_exact_assignment_and_recomputable_coverage():
    result = align((text_record(),), pdf_chars())
    assert set(result.assignments) == {1}
    span = result.assignments[1]
    assert (span.start, span.end, span.iou) == (0, 3, 1)
    assert span.boxes == (Rect(10, 10, 20, 20), Rect(20, 10, 30, 20), Rect(30, 10, 40, 20))
    assert result.unknown == {}
    assert result.coverage == {'source_units_total': 1, 'total_units': 1, 'aligned_units': 1,
        'unaligned_units': 0, 'unsupported_units': 0, 'ratio': 1.0,
        'unaligned_by_reason': {'no_text_match': 0, 'height_mismatch': 0, 'low_overlap': 0,
          'ambiguous': 0, 'conflict': 0, 'unsupported_rotated': 0, 'unsupported_mathtext': 0}}


@pytest.mark.parametrize('chars,reason', [
    (('xyz', 10, 10, 10, 10), 'no_text_match'),
    (('abc', 10, 10, 10, 1.99), 'height_mismatch'),
    (('abc', 100, 10, 10, 10), 'low_overlap'),
    (('abc', 10, 10, 10, 0), 'height_mismatch'),
])
def test_reason_precedence(chars, reason):
    result = align((text_record(),), pdf_chars(*chars))
    assert result.unknown == {1: reason}
    assert result.assignments == {}


@pytest.mark.parametrize('height,want', [(2, True), (15, True), (15.001, False)])
def test_closed_height_band(height, want):
    result = align((text_record(box=Rect(10, 10, 40, 10 + height)),), pdf_chars(height=height))
    assert (1 in result.assignments) is want


def test_iou_half_is_included_but_below_half_is_not():
    assert 1 in align((text_record(box=Rect(10, 10, 70, 20)),), pdf_chars()).assignments
    assert align((text_record(box=Rect(10, 10, 70.001, 20)),), pdf_chars()).unknown == {1: 'low_overlap'}


def test_multiline_pdf_crlf_span_keeps_all_original_char_indices():
    e = module('evidence')
    chars = (e.PdfChar('a', Rect(10, 20, 20, 30)),
             e.PdfChar('\r', Rect(20, 20, 20, 20)), e.PdfChar('\n', Rect(20, 20, 20, 20)),
             e.PdfChar('b', Rect(10, 10, 20, 20)))
    result = align((text_record(text=' a\nb ', box=Rect(10, 10, 20, 30)),), chars)
    assert (result.assignments[1].start, result.assignments[1].end) == (0, 4)
    assert len(result.assignments[1].boxes) == 4


def test_greedy_assignment_is_input_order_independent_and_no_reassignment():
    chars = pdf_chars() + pdf_chars(' ', x=100) + pdf_chars(x=60)
    records = (text_record(7), text_record(2), text_record(3, box=Rect(60, 10, 90, 20)))
    for order in permutations(records):
        result = align(order, chars)
        assert {key: span.start for key, span in result.assignments.items()} == {2: 0, 3: 4}
        assert result.unknown == {7: 'conflict'}


def test_identical_geometry_spans_are_ambiguous_even_if_other_unit_claims_one():
    chars = pdf_chars() + pdf_chars(' ', x=100) + pdf_chars()
    result = align((text_record(1), text_record(2)), chars)
    assert result.assignments == {}
    assert result.unknown == {1: 'ambiguous', 2: 'ambiguous'}


def test_near_center_close_iou_ambiguity_and_no_second_pass():
    # Edges differ by >1 pt, so only the second ambiguity rule can fire.
    source = text_record(box=Rect(8, 10, 42, 20))
    chars = pdf_chars(x=8.1) + pdf_chars(' ', x=100) + pdf_chars(x=9.9)
    result = align((source, text_record(2, box=source.bbox_display)), chars)
    assert result.unknown == {1: 'ambiguous', 2: 'ambiguous'}
    assert not result.assignments


def test_missing_glyph_second_search_recovers_remaining_text_only_when_proven():
    record = text_record(text='a 𠀀 b', box=Rect(10, 10, 50, 20))
    evidence = glyph_evidence()
    result = align((record,), pdf_chars('a b'), {1: (evidence,)})
    assert (result.assignments[1].start, result.assignments[1].end) == (0, 3)
    assert result.assignments[1].removed_codepoints == (0x20000,)
    assert align((record,), pdf_chars('a b'), {1: (replace(evidence, warnings=()),)}).unknown == {1: 'no_text_match'}
    assert align((text_record(text='𠀀'),), (), {1: (evidence,)}).unknown == {1: 'no_text_match'}
    lone = text_record(text='𠀀', box=Rect(10, 10, 20, 20))
    assert align((lone,), pdf_chars('𠀀'), {1: (evidence,)}).unknown == {1: 'no_text_match'}


def test_reason_precedence_is_over_both_searches_and_exact_presence_not_veto():
    record = text_record(text='a𠀀b')
    evidence = glyph_evidence()
    result = align((record,), pdf_chars('a𠀀b'), {1: (evidence,)})
    assert 1 in result.assignments
    # Exact text exists but too short; reduced text passes height but is far away.
    chars = pdf_chars('a𠀀b', height=1) + pdf_chars(' ', x=100) + pdf_chars('ab', x=100)
    assert align((record,), chars, {1: (evidence,)}).unknown == {1: 'low_overlap'}


def test_unsupported_units_stay_in_denominator_and_empty_ratio_is_null():
    result = align((text_record(1), text_record(2, rotation=90), text_record(3, '$x$')),
                   pdf_chars())
    assert result.coverage['ratio'] == 1 / 3
    assert result.coverage['unsupported_units'] == 2
    assert result.unknown == {2: 'unsupported_rotated', 3: 'unsupported_mathtext'}
    empty = align((), ())
    assert empty.coverage['ratio'] is None
    assert empty.coverage['total_units'] == 0
