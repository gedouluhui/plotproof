"""Break real code only in fresh scratch copies; a crash is not a caught mutation."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__', 'geometry', 'evidence', 'units', 'alignment', 'occlusion', 'rules', 'core')
TESTS = ('_core_fixtures', 'test_geometry', 'test_units', 'test_alignment', 'test_rules', 'test_core')
# Each target is a behavioral assertion, not a source-string existence test.
MUTATIONS = [
    ('zero_area', 'geometry', (
        ("    if box.area == 0:\n        return None\n", ''),
        ('(outside > 0 and outside >= 0.5 * box.area)', '(outside >= 0.5 * box.area)'),
     ), 'test_geometry.py::test_boundary_positive_area_and_unrounded_thresholds'),
    ('sum_not_union', 'geometry', (('return fsum(strips)', 'return fsum(b.area for b in boxes)'),),
     'test_geometry.py::test_union_is_not_sum_or_bounding_box_and_ignores_degenerates'),
    ('no_wrapper_reconciliation', 'units', (
        ('if record.is_unit is not (reason is None) or record.exclusion_reason != reason:', 'if False:'),),
     'test_units.py::test_wrong_exclusion_reason_fails_even_when_total_still_matches'),
    ('warning_without_cmap', 'evidence', (
        ('self.fonts and all(font.missing for font in self.fonts) and self.naming_warnings', 'self.naming_warnings'),),
     'test_units.py::test_glyph_deletion_requires_all_fonts_and_exact_naming_warning'),
    ('empty_remainder', 'alignment', (
        ("return []  # §7.1 explicit empty-remainder exception, even if PDF emits tofu text", 'pass'),),
     'test_alignment.py::test_missing_glyph_second_search_recovers_remaining_text_only_when_proven'),
    ('reversed_greedy_tie', 'alignment', (
        ('(-pair[1].iou, pair[0], pair[1].start)', '(-pair[1].iou, -pair[0], pair[1].start)'),),
     'test_alignment.py::test_greedy_assignment_is_input_order_independent_and_no_reassignment'),
    ('no_ambiguity', 'alignment', (('if indistinguishable or tied:', 'if False:'),),
     'test_alignment.py::test_identical_geometry_spans_are_ambiguous_even_if_other_unit_claims_one'),
    ('pooled_high', 'rules', (("high = any(artist['high_eligible'] for artist in artists)", 'high = joint >= 0.90'),),
     'test_rules.py::test_d2_union_not_sum_and_single_occluder_high_guard'),
    ('ignore_artist_alpha', 'occlusion', (('opacity * self.artist_alpha if opacity is not None',
                                         'opacity if opacity is not None'),),
     'test_rules.py::test_d2_alpha_product_own_background_and_paint_order'),
    ('no_background_demotion', 'rules', (('and not demoted', 'and True'),),
     'test_rules.py::test_d3_own_opaque_background_demotes_not_suppresses'),
    ('source_box_for_ink', 'rules', (
        ('a = left_span.boxes if aligned else (left.box_pdf,)', 'a = (left.box_pdf,)'),
        ('b = right_span.boxes if aligned else (right.box_pdf,)', 'b = (right.box_pdf,)'),),
     'test_rules.py::test_d3_uses_unions_not_outer_bboxes'),
    ('cross_confidence_suppression', 'rules', (
        ('higher.confidence == finding.confidence and PRIORITY', 'PRIORITY'),),
     'test_rules.py::test_precedence_is_confidence_scoped_and_records_suppression'),
    ('closed_coverage_gate', 'core', (("coverage['ratio'] < 0.90", "coverage['ratio'] <= 0.90"),),
     'test_core.py::test_coverage_threshold_and_unknown_objects_are_not_hidden'),
    ('discard_errors', 'core', (('    if errors:\n', '    if False:\n'),),
     'test_core.py::test_high_finding_outvotes_unknown_but_never_error'),
    ('missing_char_silent_drop', 'rules', (('if not aligned and not glyph.proven_missing:', 'if not aligned:'),),
     'test_core.py::test_medium_finding_survives_90_percent_coverage'),
    ('legal_fallback_flagged', 'rules', (('if supplied_without_warning:', 'if False:'),),
     'test_rules.py::test_d4_missing_warning_stack_disagreement_and_wrong_family_are_medium'),
]


def assertion_kill(xml: str, target: str) -> bool:
    """Only a targeted assertion failure counts; syntax/import/fixture errors do not."""
    root = ET.fromstring(xml)
    cases = list(root.iter('testcase'))
    if not cases or list(root.iter('error')):
        return False
    failures = [(case, f) for case in cases for f in case.findall('failure')]
    return bool(failures) and all(
        case.get('name', '').startswith(target)
        and f.get('message', (f.text or '').strip()).startswith(
            ('AssertionError', 'assert ', 'Failed: DID NOT RAISE'))
        for case, f in failures)


def test_mutation_classifier_rejects_crashes_empty_runs_and_wrong_test():
    good = '<testsuite><testcase name="expected"><failure>AssertionError: wrong</failure></testcase></testsuite>'
    assert assertion_kill(good, 'expected')
    assert not assertion_kill(good.replace('expected', 'unrelated'), 'expected')
    assert not assertion_kill(good.replace('AssertionError: wrong', 'ZeroDivisionError'), 'expected')
    assert not assertion_kill(good.replace('failure', 'error'), 'expected')
    assert not assertion_kill('<testsuite/>', 'expected')


def test_mutation_classifier_accepts_pytest_rewritten_assert_not_traceback_word():
    rewritten = '<testsuite><testcase name="expected"><failure message="assert 7 == 2">E   assert 7 == 2</failure></testcase></testsuite>'
    assert assertion_kill(rewritten, 'expected')
    crash = '<testsuite><testcase name="expected"><failure message="ZeroDivisionError: division by zero">AssertionError mentioned in source; ZeroDivisionError</failure></testcase></testsuite>'
    assert not assertion_kill(crash, 'expected')


def populate(destination: Path) -> None:
    for directory, names in (('plotproof', MODULES), ('tests', TESTS)):
        (destination / directory).mkdir(parents=True)
        for name in names:
            shutil.copy2(ROOT / directory / (name + '.py'), destination / directory / (name + '.py'))


def run_tests(path: Path, target: str) -> tuple[subprocess.CompletedProcess, str]:
    report = path / 'junit.xml'
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(path))
    proc = subprocess.run([sys.executable, '-m', 'pytest', 'tests/' + target, '-q',
                           '--tb=short', '--junitxml=' + str(report)], cwd=path,
                          env=env, capture_output=True, text=True, timeout=60)
    assert report.is_file(), proc.stdout + proc.stderr
    return proc, report.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def control(tmp_path_factory):
    directory = tmp_path_factory.mktemp('core-control')
    populate(directory)
    proc, xml = run_tests(directory, '.')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root = ET.fromstring(xml)
    assert list(root.iter('testcase')) and not list(root.iter('failure')) and not list(root.iter('error'))
    return directory


@pytest.mark.parametrize('name,module,changes,target', MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_core_mutation_is_caught(control, tmp_path, name, module, changes, target):
    # control has completed; no same-file mutating runs or shared mutable snapshot.
    populate(tmp_path)
    original_path = ROOT / 'plotproof' / (module + '.py')
    original = original_path.read_bytes()
    code = original.decode('utf-8')
    for before, after in changes:
        assert code.count(before) == 1, f'{name}: mutation anchor must be unique'
        code = code.replace(before, after, 1)
    mutated = code.encode('utf-8')
    assert mutated != original, f'{name}: NOP is not a test result'
    (tmp_path / 'plotproof' / (module + '.py')).write_bytes(mutated)
    proc, xml = run_tests(tmp_path, target)
    assert original_path.read_bytes() == original, 'production source was altered'
    assert proc.returncode == 1 and assertion_kill(xml, target.split('::')[1]), (
        f'{name}: mutant survived or measurement failed\n' + proc.stdout + proc.stderr)
