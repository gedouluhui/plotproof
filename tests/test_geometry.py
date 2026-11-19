"""Independent numeric oracles: no expected value uses production geometry."""
from importlib import import_module, util
import math
import random

import pytest


def geometry():
    assert util.find_spec('plotproof.geometry') is not None, 'geometry implementation missing'
    return import_module('plotproof.geometry')


@pytest.mark.parametrize('coords', [(0, 0, -1, 1), (0, 2, 1, 1),
                                    (0, 0, math.nan, 1), (0, 0, math.inf, 1),
                                    (False, 0, 1, 1), ('0', 0, 1, 1)])
def test_reject_invalid_geometry_instead_of_clean_result(coords):
    g = geometry()
    with pytest.raises((ValueError, TypeError)):
        g.Rect(*coords)


def test_rect_intersection_touching_and_hairline():
    g = geometry()
    a = g.Rect(0, 0, 2, 2)
    assert a.intersection(g.Rect(1, 1, 3, 3)) == g.Rect(1, 1, 2, 2)
    assert a.intersection(g.Rect(2, 0, 4, 2)) is None
    assert a.intersection(g.Rect(3, 0, 4, 2)) is None
    assert g.Rect(0, 0, 3.18, 0.009995).area == pytest.approx(0.0317841)
    assert g.Rect(0, 0, 0, 20).area == 0
    assert a.center == (1, 1)
    assert a.contains(g.Rect(0, 0, 2, 1))
    assert not a.contains(g.Rect(-0.0001, 0, 2, 1))


def test_union_is_not_sum_or_bounding_box_and_ignores_degenerates():
    g = geometry()
    rects = [g.Rect(0, 0, 2, 2), g.Rect(1, 1, 3, 3), g.Rect(-100, 0, -100, 100)]
    assert g.union_area(rects) == 7
    assert g.union_area(rects + rects) == 7
    assert g.union_area([]) == 0
    assert g.bounding_rect(rects) == g.Rect(0, 0, 3, 3)
    assert g.bounding_rect([g.Rect(0, 0, 0, 3)]) is None
    assert g.iou(g.Rect(0, 0, 2, 2), g.Rect(1, 1, 3, 3)) == pytest.approx(1 / 7)
    assert g.iou(g.Rect(0, 0, 0, 1), g.Rect(0, 0, 0, 1)) == 0


def test_intersection_of_unions_does_not_fill_empty_ink_gaps():
    g = geometry()
    a = [g.Rect(0, 0, 1, 2), g.Rect(3, 0, 4, 2)]
    b = [g.Rect(1, 0, 3, 2)]
    assert g.union_area(g.intersections(a, b)) == 0
    b.append(g.Rect(0.5, 0, 3.5, 1))
    assert g.union_area(g.intersections(a, b)) == 1


def test_union_against_independent_unit_cell_oracle():
    g = geometry()
    rng = random.Random(1841)
    for _ in range(200):
        coords = []
        for _ in range(rng.randrange(12)):
            x = sorted(rng.choices(range(-4, 5), k=2))
            y = sorted(rng.choices(range(-4, 5), k=2))
            coords.append((x[0], y[0], x[1], y[1]))
        cells = {(x, y) for x0, y0, x1, y1 in coords
                 for x in range(x0, x1) for y in range(y0, y1)}
        assert g.union_area([g.Rect(*c) for c in coords]) == len(cells)


@pytest.mark.parametrize('box,want', [
    ((0, 0, 1, 1), None), ((-1, 0, 1, 2), 'high'),
    ((-0.99, 0, 1.01, 2), 'medium'), ((-2, 0, -1, 1), 'high'),
    ((-100, 0, -100, 1), None), ((0, -100, 1, -100), None),
    ((9, 0, 11, 2), 'high'), ((9, 0, 10, 2), None),
    ((0, 9, 1, 11), 'high'), ((0, -1, 1, 1), 'high'),
    ((-0.001, 0, 1, 0.00001), 'medium'),
])
def test_boundary_positive_area_and_unrounded_thresholds(box, want):
    g = geometry()
    assert g.boundary_evidence(g.Rect(*box), g.Rect(0, 0, 10, 10)) == want


def test_extreme_finite_boxes_do_not_overflow_iou_or_invent_clipping():
    g = geometry()
    huge = g.Rect(0, 0, 1e154, 1e154)
    tiny = g.Rect(0, 0, 1e-200, 1e-200)
    assert g.iou(huge, huge) == 1.0
    assert g.iou(tiny, tiny) == 0.0  # zero representable area is not usable evidence
    assert g.boundary_evidence(g.Rect(0, 0, 5e-324, 1), g.Rect(0, 0, 10, 10)) is None


def test_transform_plain_tight_and_page_pullback():
    g = geometry()
    plain = g.Transform(100, 0, 0)
    assert plain.to_pdf(g.Rect(100, 50, 200, 100)) == g.Rect(72, 36, 144, 72)
    tight = g.Transform(100, -10, 20)
    assert tight.to_pdf(g.Rect(0, 20, 100, 120)) == g.Rect(7.2, 0, 79.2, 72)
    assert tight.page_in_display(720, 432) == g.Rect(-10, 20, 990, 620)
    for dpi in (0, -1, math.nan, math.inf, True):
        with pytest.raises((TypeError, ValueError)):
            g.Transform(dpi, 0, 0)
