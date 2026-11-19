from dataclasses import replace
import math

import pytest

from _core_fixtures import module, text_record, glyph_evidence, Rect, Transform


@pytest.mark.parametrize('changes,reason', [
    ({'text': ' \n ', 'visible': False}, 'empty_text'),
    ({'text_alpha': 0, 'visible': False}, 'alpha_nonpositive'),
    ({'artist_alpha': 0}, 'alpha_nonpositive'),
    ({'visible': False}, 'invisible'),
    ({'bbox_display': Rect(0, 0, 0, 1)}, 'empty_extent'),
    ({'bbox_display': Rect(100, 1, 101, 3)}, 'outside_page'),
    ({'clip_box_display': Rect(40, 0, 50, 30)}, 'fully_clipped'),
    ({'tick_location': 0.5, 'view_limits': (1, 3)}, 'tick_outside_view'),
])
def test_predicate_first_failure_is_recomputed(changes, reason):
    u = module('units')
    record = text_record(**changes, is_unit=False, exclusion_reason=reason)
    result = u.enumerate_units((record,), Transform(72, 0, 0), Rect(0, 0, 100, 100), 0)
    assert result.units == ()
    with pytest.raises(u.AccountingError, match='unit_accounting_mismatch'):
        u.enumerate_units((replace(record, is_unit=True, exclusion_reason=None),),
                          Transform(72, 0, 0), Rect(0, 0, 100, 100), 1)


def test_tick_endpoints_inverted_limits_and_tight_saved_page():
    u = module('units')
    records = (text_record(1, tick_location=1, view_limits=(3, 1)),
               text_record(2, tick_location=3, view_limits=(3, 1)),
               text_record(3, box=Rect(102, 20, 120, 30)))
    result = u.enumerate_units(records, Transform(100, -10, -10), Rect(0, 0, 100, 100), 3)
    assert [unit.record.source_object_id for unit in result.units] == [1, 2, 3]
    assert result.units[2].box_pdf == Rect(80.64, 21.6, 93.6, 28.8)


def test_accounting_refuses_duplicate_ids_wrong_total_and_fake_boolean():
    u = module('units')
    for records, total in [((text_record(),), 2), ((text_record(), text_record()), 2),
                           ((text_record(),), True)]:
        with pytest.raises(u.AccountingError, match='unit_accounting_mismatch'):
            u.enumerate_units(records, Transform(72, 0, 0), Rect(0, 0, 100, 100), total)
    with pytest.raises((TypeError, ValueError)):
        text_record(is_unit=1)


def test_wrong_exclusion_reason_fails_even_when_total_still_matches():
    u = module('units')
    stale = text_record(visible=False, is_unit=False, exclusion_reason='empty_text')
    with pytest.raises(u.AccountingError, match='predicate disagreement'):
        u.enumerate_units((stale,), Transform(72, 0, 0), Rect(0, 0, 100, 100), 0)


def test_scope_rotation_wins_over_mathtext():
    u = module('units')
    result = u.enumerate_units((text_record(1, '$x$', rotation=90), text_record(2, '$x$')),
                              Transform(72, 0, 0), Rect(0, 0, 100, 100), 2)
    assert [unit.unsupported_reason for unit in result.units] == [
        'unsupported_rotated', 'unsupported_mathtext']


@pytest.mark.parametrize('changes', [
    {'font_size_pt': 0}, {'text_alpha': math.nan}, {'artist_alpha': 1.01},
    {'rotation': math.inf}, {'source_object_id': True}, {'visible': 1},
    {'tick_location': 1}, {'view_limits': (1, 2)},
])
def test_bad_captured_terms_are_not_accepted(changes):
    with pytest.raises((TypeError, ValueError)):
        text_record(**changes)


def test_glyph_deletion_requires_all_fonts_and_exact_naming_warning():
    e = module('evidence')
    missing = glyph_evidence(glyph_ids=(None, 0), families=('Test Sans', 'Fallback'))
    assert missing.proven_missing
    assert not replace(missing, warnings=()).proven_missing
    assert not glyph_evidence(glyph_ids=(None, 5), families=('Test Sans', 'Fallback')).proven_missing
    assert not replace(missing, fonts=()).proven_missing
    assert not replace(missing, fonts=(e.FontGlyph('Test Sans', None, None),)).proven_missing
    for message in ['Glyph 1310720 (x) missing from font(s) Test Sans.',
                    'Glyph 131072 (x) missing from font(s) Test Sans Extra.',
                    'Glyph 131072 (x) missing from font(s) Other.',
                    'Glyph 131072 present in font(s) Test Sans.']:
        assert not replace(missing, warnings=(e.SaveWarning('UserWarning', message),)).proven_missing
    # Matplotlib also emits a bracketed list in supported versions.
    assert replace(missing, warnings=(e.SaveWarning('UserWarning',
        "Glyph 131072 (x) missing from font(s) ['Test Sans', 'Fallback']."),)).proven_missing
