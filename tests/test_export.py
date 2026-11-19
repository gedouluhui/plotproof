"""Assembly-level checks: a real save, the real reader and the frozen core."""
import json
from pathlib import Path

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import pytest

from plotproof.cli import main
from plotproof.export import CheckError, check_figure, render_html


@pytest.fixture(autouse=True)
def style():
    with mpl.rc_context({'pdf.fonttype': 42, 'font.family': ['DejaVu Sans'],
                         'text.usetex': False, 'pdf.use14corefonts': False,
                         'savefig.bbox': None, 'savefig.transparent': False}):
        yield


def figure():
    fig = Figure(figsize=(4, 3), dpi=100, layout='constrained')
    FigureCanvasAgg(fig)
    return fig


def bars(fig):
    ax = fig.subplots()
    ax.bar(['alpha', 'beta', 'gamma'], [3, 5, 2])
    ax.set_xlabel('Category')
    ax.set_ylabel('Count', rotation=0)
    ax.set_title('Sample')
    return ax


def test_clean_figure_passes_in_assessed_classes():
    fig = figure()
    bars(fig)
    report = check_figure(fig)
    assert report.state == 'PASS', report.to_dict()
    assert report.coverage['ratio'] == 1.0
    assert report.findings == ()
    assert 'D1_clipped_text' in report.assessed
    assert 'D4_missing_glyph' in report.not_assessed
    assert report.source_units_total == report.coverage['total_units']


def test_partially_off_page_text_reports_high_d1_with_its_source_id():
    fig = figure()
    bars(fig)
    clipped = fig.text(0.96, 0.55, 'This annotation runs past the edge',
                       ha='left', va='center')
    report = check_figure(fig)
    assert report.state == 'FAIL', report.to_dict()
    found = [item for item in report.findings if item['rule_id'] == 'D1']
    assert len(found) == 1, report.findings
    finding = found[0]
    assert finding['confidence'] == 'high'
    assert finding['source_text'] == 'This annotation runs past the edge'
    # The reported box is the real painted box and it extends past the page.
    assert finding['box_pdf_points'][2] > report.page_size_pt[0]
    assert clipped.get_text() == finding['source_text']


def test_image_limits_occlusion_but_does_not_crash_or_pass_off_as_checked():
    from matplotlib.patches import Rectangle
    fig = figure()
    ax = bars(fig)
    ax.add_patch(Rectangle((0.1, 0.1), 0.5, 0.5, transform=ax.transAxes,
                           facecolor='C1', edgecolor='none'))
    report = check_figure(fig)
    assert 'D2_occluded_text' in report.not_assessed
    assert report.state in ('PASS', 'UNKNOWN', 'FAIL')
    assert report.assessed == ('D1_clipped_text', 'D3_overlapping_text')


def test_report_is_json_serialisable_and_html_has_no_script():
    fig = figure()
    bars(fig)
    report = check_figure(fig)
    payload = json.dumps(report.to_dict(), sort_keys=True)
    assert '"state": "PASS"' in payload
    html = render_html(report)
    assert '<script' not in html.lower()
    assert report.input_sha256 in html


def test_unsupported_runtime_is_reported_not_guessed():
    from matplotlib.figure import Figure
    bare = Figure(figsize=(2, 2))
    with pytest.raises(CheckError):
        check_figure(bare)


def test_demo_cli_writes_both_reports(tmp_path):
    target = tmp_path / 'reports'
    assert main(['demo', '--output', str(target)]) == 0
    clean = json.loads((target / 'clean.json').read_text(encoding='utf-8'))
    clipped = json.loads((target / 'clipped.json').read_text(encoding='utf-8'))
    assert clean['state'] == 'PASS'
    assert clipped['state'] == 'FAIL'
    assert (target / 'clipped.html').is_file()
