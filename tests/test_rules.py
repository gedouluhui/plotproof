from dataclasses import replace

import pytest

from _core_fixtures import module, text_record, pdf_chars, glyph_evidence, Rect, Transform
from test_alignment import align


def occluder(object_id=8, box=None, **changes):
    e = module('occlusion')
    record = e.FilledRecord(object_id, box or Rect(10, 10, 20, 20),
        'Rectangle', 'axis_aligned_rectangle', False, None, 1.0, 1.0,
        2, 100.0, None, None)
    return replace(record, **changes)


def detect(records, chars, fills=(), glyphs=None, page=Rect(0, 0, 100, 100)):
    result = align(records, chars, glyphs)
    return module('rules').detect_rules(result, page, fills, glyphs or {})


def single(fills=(), glyphs=None):
    return detect((text_record(text='a', box=Rect(10, 10, 20, 20)),),
                  pdf_chars('a'), fills, glyphs)


def test_d1_high_box_uses_only_high_positive_area_evidence():
    e = module('evidence')
    chars = (e.PdfChar('a', Rect(-5, 10, 5, 20)),
             e.PdfChar(' ', Rect(-1e3, 10, -1e3, 10)),
             e.PdfChar('b', Rect(-1, 10, 9, 20)))
    # Construct typed aligned evidence directly: D1 should ignore any degenerate box,
    # even one that a real alignment might reject for its span bbox.
    a = module('alignment'); u = module('units')
    rec = text_record(text='a b', box=Rect(0, 10, 10, 20))
    units = u.enumerate_units((rec,), Transform(72, 0, 0), Rect(0, 0, 100, 100), 1)
    span = a.Span(0, 3, tuple(c.box for c in chars), Rect(-5, 10, 9, 20), 0.5,
                  'a b', (0, 1, 2), ())
    result = a.AlignmentResult(units, {1: span}, {}, a.canonicalize('a b', source=False))
    findings = module('rules').detect_rules(result, Rect(0, 0, 100, 100), (), {})
    assert len(findings) == 1
    f = findings[0]
    assert (f.rule_id, f.confidence, f.box_pdf_points) == ('D1', 'high', (-5, 10, 5, 20))
    assert f.evidence['boundary_boxes'] == ({'box': (-5, 10, 5, 20), 'area': 100,
             'inside_area': 50, 'center': (0, 15)},)


@pytest.mark.parametrize('width,alpha,want', [
    (9, 1, 'high'), (8.999, 1, 'medium'), (5, 1, 'medium'),
    (4.999, 1, None), (10, 0.95, 'high'), (10, 0.949, 'medium'),
    (10, 0.5, 'medium'), (10, 0.499, None),
])
def test_d2_coverage_and_alpha_endpoints(width, alpha, want):
    findings = single((occluder(box=Rect(10, 10, 10 + width, 20), facecolor_alpha=alpha),))
    assert [(f.rule_id, f.confidence) for f in findings] == ([] if want is None else [('D2', want)])


def test_d2_alpha_product_own_background_and_paint_order():
    assert single((occluder(facecolor_alpha=0.9, artist_alpha=0.5),)) == ()
    assert single((occluder(owner_unit_id=1),)) == ()
    assert single((occluder(paint_order=0),)) == ()
    assert single((occluder(paint_order=1),))[0].confidence == 'medium'
    assert single((occluder(paint_order=None),))[0].confidence == 'medium'


def test_d2_union_not_sum_and_single_occluder_high_guard():
    same = single((occluder(8, Rect(10, 10, 16, 20)), occluder(9, Rect(10, 10, 16, 20))))[0]
    assert same.confidence == 'medium'
    assert same.evidence['joint_coverage'] == 0.6
    split = single((occluder(8, Rect(10, 10, 15, 20)), occluder(9, Rect(15, 10, 20, 20))))[0]
    assert split.confidence == 'medium'
    assert split.evidence['joint_coverage'] == 1
    assert split.box_pdf_points == (10, 10, 20, 20)
    assert [a['coverage'] for a in split.evidence['occluders']] == [0.5, 0.5]
    assert split.evidence['occluders'][0]['intersection_boxes'] == ((10, 10, 15, 20),)


@pytest.mark.parametrize('changes', [
    {'path_kind': 'legend_frame', 'fancybox': True},
    {'path_kind': 'other_filled_path', 'path_is_concave': True},
    {'path_kind': 'other_filled_path', 'filled_area': 94.999},
    {'box_pdf': Rect(-1, 10, 20, 20)},
])
def test_d2_geometry_high_only_guards(changes):
    assert single((occluder(**changes),))[0].confidence == 'medium'


def test_d2_supported_geometry_and_images():
    for changes in ({'path_kind': 'legend_frame', 'fancybox': False},
                    {'path_kind': 'other_filled_path', 'filled_area': 95},
                    {'path_kind': 'image', 'image_opacity': 1, 'filled_area': None}):
        assert single((occluder(**changes),))[0].confidence == 'high'
    assert single((occluder(path_kind='image', image_opacity=0.49),)) == ()
    # Unknown opacity cannot be assumed opaque, nor silently certify this case clean.
    f = single((occluder(path_kind='image', image_opacity=None),))[0]
    assert f.confidence == 'medium'
    assert f.evidence['occluders'][0]['effective_alpha'] is None


def test_d2_no_alignment_no_occlusion():
    assert detect((text_record(text='xyz'),), pdf_chars('a'), (occluder(),)) == ()


def pair(offset=5, height=10, second_aligned=True, fills=(), rotate=0):
    boxes = [Rect(10, 10, 20, 10 + height), Rect(10 + offset, 10, 20 + offset, 10 + height)]
    records = (text_record(9, 'a', boxes[0], font_size_pt=height),
               text_record(2, 'b', boxes[1], font_size_pt=height, rotation=rotate))
    e = module('evidence')
    chars = (e.PdfChar('a', boxes[0]), e.PdfChar('b' if second_aligned else 'z', boxes[1]))
    return detect(records, chars, fills)


@pytest.mark.parametrize('offset,want', [(5, 'high'), (5.001, 'medium'),
                                        (8.5, 'medium'), (8.501, None), (10, None)])
def test_d3_ratio_endpoints_and_pair_identity(offset, want):
    findings = pair(offset)
    assert [(f.rule_id, f.confidence) for f in findings] == ([] if want is None else [('D3', want)])
    if findings:
        f = findings[0]
        assert (f.source_object_id, f.related_source_object_id) == (2, 9)
        assert f.evidence['operand_set'] == 'char_unions'
        assert f.box_pdf_points == (10 + offset, 10, 20, 20)


def test_d3_high_requires_half_point_in_both_axes():
    assert pair(height=0.5)[0].confidence == 'high'
    assert pair(height=0.4999)[0].confidence == 'medium'


def test_d3_own_opaque_background_demotes_not_suppresses():
    f = pair(fills=(occluder(box=Rect(15, 10, 20, 20), owner_unit_id=9, paint_order=0),))[0]
    assert (f.rule_id, f.confidence) == ('D3', 'medium')
    assert f.evidence['own_backgrounds'][0]['owner_unit_id'] == 9
    assert pair(fills=(occluder(box=Rect(0, 0, 1, 1), owner_unit_id=9, paint_order=0),))[0].confidence == 'high'
    assert pair(fills=(occluder(owner_unit_id=9, facecolor_alpha=0.94, paint_order=0),))[0].confidence == 'high'


def test_d3_unaligned_pair_source_bbox_path_and_unsupported_exclusion():
    f = pair(second_aligned=False)[0]
    assert (f.confidence, f.evidence['operand_set']) == ('medium', 'source_bboxes')
    assert pair(rotate=90) == ()


def test_d3_uses_unions_not_outer_bboxes():
    e = module('evidence')
    chars = (e.PdfChar('a', Rect(10, 10, 11, 20)), e.PdfChar('c', Rect(19, 10, 20, 20)),
             e.PdfChar('b', Rect(12, 10, 18, 20)))
    records = (text_record(1, 'ac', Rect(10, 10, 20, 20)), text_record(2, 'b', Rect(12, 10, 18, 20)))
    assert detect(records, chars) == ()


def test_d4_high_missing_glyph_even_when_extracted_and_medium_without_alignment():
    evidence = glyph_evidence()
    record = text_record(text='a𠀀b')
    f = detect((record,), pdf_chars('a𠀀b'), glyphs={1: (evidence,)})[0]
    assert (f.rule_id, f.confidence, f.box_pdf_points) == ('D4', 'high', (10, 10, 40, 20))
    assert f.evidence['codepoint'] == 0x20000
    f = detect((text_record(text='𠀀'),), (), glyphs={1: (evidence,)})[0]
    assert (f.rule_id, f.confidence) == ('D4', 'medium')
    assert detect((text_record(text='$𠀀$'),), (), glyphs={1: (evidence,)}) == ()


def test_d4_missing_warning_stack_disagreement_and_wrong_family_are_medium():
    evidence = glyph_evidence()
    wrong_family = replace(evidence, fonts=(module('evidence').FontGlyph('Other', 'other.ttf', None),))
    fallback = glyph_evidence(glyph_ids=(None, 7), families=('Test Sans', 'Fallback'))
    for item in (replace(evidence, warnings=()), wrong_family, fallback):
        f = detect((text_record(text='a𠀀b'),), pdf_chars('a𠀀b'), glyphs={1: (item,)})[0]
        assert (f.rule_id, f.confidence) == ('D4', 'medium')
    supplied = glyph_evidence(glyph_ids=(7,), warnings=())
    assert detect((text_record(text='a𠀀b'),), pdf_chars('a𠀀b'), glyphs={1: (supplied,)}) == ()
    assert single(glyphs={1: (evidence,)}) == ()  # character must belong to this unit
    for missing_id in (None, 0):
        legal_fallback = glyph_evidence(glyph_ids=(missing_id, 7),
                                       families=('Test Sans', 'Fallback'), warnings=())
        assert detect((text_record(text='a𠀀b'),), pdf_chars('a𠀀b'),
                      glyphs={1: (legal_fallback,)}) == ()


def test_precedence_is_confidence_scoped_and_records_suppression():
    # Semi-transparent D2 must not erase a high D3 on the same unit.
    findings = pair(fills=(occluder(box=Rect(10, 10, 25, 20), facecolor_alpha=0.5),))
    assert {(f.rule_id, f.confidence) for f in findings} == {('D2', 'medium'), ('D3', 'high')}
    # Same-confidence D2 suppresses the entire unordered D3 pair.
    findings = pair(fills=(occluder(box=Rect(10, 10, 25, 20)),))
    assert {f.rule_id for f in findings} == {'D2'}
    assert any(f.evidence.get('suppressed') for f in findings)
