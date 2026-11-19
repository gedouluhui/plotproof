"""Characterize capture assumptions, not PlotProof detector accuracy.

Literal expectations below come from the independently reproduced fixtures;
no product capture code or frozen B0 data is imported. All PDFs stay in memory.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "spikes" / "b1_capture_semantics_probe.py"
ARTIFACT = ROOT / "artifacts" / "b1" / "capture-semantics-probe.json"


@lru_cache(maxsize=1)
def _probe():
    assert SCRIPT.is_file(), "The runnable capture-semantics probe is missing"
    spec = importlib.util.spec_from_file_location("capture_semantics_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _report():
    return _probe().run_probe()


def test_report_is_attributable_json_without_machine_paths():
    report = _report()
    encoded = json.dumps(report, allow_nan=False)
    assert report["classification"] == "capture_contract_counterexamples"
    assert report["script_sha256"] == sha256(SCRIPT.read_bytes()).hexdigest()
    assert datetime.fromisoformat(report["generated_at"]).utcoffset().total_seconds() == 0
    for name in ("python", "matplotlib", "pypdfium2", "pdfium", "numpy", "pillow", "freetype"):
        assert report["versions"][name]
    assert not re.search(r"[A-Za-z]:[/\\]|/Users/|/home/|/tmp/|\\\\", encoded)
    assert report["limitations"]
    assert "detector_accuracy" not in report
    assert "PASS" not in encoded


@pytest.mark.parametrize(
    "case_id, rgba, artist_alpha, product, product_rgb, actual_rgb, classification",
    [
        ("artist_alpha_0_6", [0, 0, 0, 0.6], 0.6, 0.36, [163] * 3, [102] * 3, "counterexample"),
        ("artist_alpha_none", [0, 0, 0, 0.6], None, 0.6, [102] * 3, [102] * 3, "control_agrees"),
        ("opaque", [0, 0, 0, 1.0], 1.0, 1.0, [0] * 3, [0] * 3, "control_agrees"),
    ],
)
def test_real_pdf_pixels_refute_double_alpha_not_the_controls(
    case_id, rgba, artist_alpha, product, product_rgb, actual_rgb, classification
):
    cases = {case["case_id"]: case for case in _report()["alpha_cases"]}
    assert set(cases) == {"artist_alpha_0_6", "artist_alpha_none", "opaque"}
    case = cases[case_id]
    assert case["input_facecolor_rgba"] == rgba
    assert case["input_artist_alpha"] == artist_alpha
    assert case["get_facecolor_rgba"] == rgba
    assert case["get_alpha"] == artist_alpha
    assert case["figure_size_inches"] == [2.0, 2.0]
    assert case["figure_dpi"] == 100
    assert case["canvas"] == "FigureCanvasAgg"
    assert case["rectangle_bounds_figure"] == [0.2, 0.2, 0.6, 0.6]
    assert case["frozen_getter_product_alpha"] == pytest.approx(product)
    assert case["frozen_prediction_rgb"] == product_rgb
    assert case["draw_contract_prediction_rgb"] == actual_rgb
    assert case["pdf"]["page_count"] == 1
    assert case["pdf"]["page_size_pt"] == [144.0, 144.0]
    assert case["pdf"]["bitmap_size_px"] == [144, 144]
    assert case["pdf"]["sample_xy_px"] == [72, 72]
    assert case["pdf"]["center_rgb"] == actual_rgb
    assert case["pdf"]["background_rgb"] == [255, 255, 255]
    assert case["interpretation"]["classification"] == classification
    assert case["interpretation"]["draw_contract_matches_render"] is True
    assert case["interpretation"]["frozen_product_matches_render"] is (case_id != "artist_alpha_0_6")
    # This is auxiliary corroboration, not the source of actual_rgb.
    assert (1.0 if case_id == "opaque" else 0.6) in case["pdf"]["auxiliary_fill_alpha_values"]


def test_ordinary_layout_records_pre_and_actual_save_bbox_against_literals():
    case = next(c for c in _report()["bbox_cases"] if c["case_id"] == "ordinary")
    assert case["pre_draw_renderer"] == "RendererAgg"
    assert case["pre_draw_tightbbox_inches"] == pytest.approx(
        [-0.1227777778, -0.1027777778, 3.7227777778, 2.7427777778], abs=1e-9
    )
    assert len(case["save_tightbbox_calls"]) == 1
    save = case["save_tightbbox_calls"][0]
    assert save["renderer"] == "MixedModeRenderer"
    assert save["bounds_inches"] == pytest.approx(
        [-0.123046875, -0.0914409722, 3.723046875, 2.7314409722], abs=1e-9
    )
    assert case["pre_draw_predicted_page_size_pt"] == pytest.approx([282.44, 211.88], abs=1e-8)
    assert case["save_predicted_page_size_pt"] == pytest.approx([282.459375, 211.06375], abs=1e-8)
    assert case["pdf"]["page_size_pt"] == pytest.approx([282.459375, 211.06375], abs=1e-4)
    assert case["interpretation"]["pre_prediction_matches_pdf"] is False
    assert case["interpretation"]["save_prediction_matches_pdf"] is True
    assert case["interpretation"]["classification"] == "counterexample"


@pytest.mark.parametrize("case_id, engine", [("ordinary", None), ("constrained_layout", "ConstrainedLayoutEngine")])
def test_bbox_predictions_use_recorded_save_call_not_a_post_save_measurement(case_id, engine):
    case = next(c for c in _report()["bbox_cases"] if c["case_id"] == case_id)
    assert case["figure_size_inches"] == [4.0, 3.0]
    assert case["figure_dpi"] == 100
    assert case["layout_engine"] == engine
    assert case["plot_x"] == [0, 1, 2]
    assert case["plot_y"] == [0, 1, 4]
    assert case["ylabel"] == "Value"
    assert case["ylabel_rotation"] == 0
    assert case["ylabel_ha"] == "right"
    assert case["xlabel"] == "Time"
    assert case["get_tightbbox_restored"] is True
    assert len(case["save_tightbbox_calls"]) == 1
    save = case["save_tightbbox_calls"][0]
    assert save["renderer"] == "MixedModeRenderer"
    assert save["figure_dpi"] == 72
    assert save["is_saving"] is True
    actual = case["pdf"]["page_size_pt"]
    pre = case["pre_draw_tightbbox_inches"]
    saved = save["bounds_inches"]
    # Independent unit conversion: two 0.1-inch margins, 72 PDF points/inch.
    expected_pre = [(pre[2] + 0.2) * 72, (pre[3] + 0.2) * 72]
    expected_save = [(saved[2] + 0.2) * 72, (saved[3] + 0.2) * 72]
    assert case["pre_draw_predicted_page_size_pt"] == pytest.approx(expected_pre)
    assert case["save_predicted_page_size_pt"] == pytest.approx(expected_save)
    assert actual == pytest.approx(expected_save, abs=1e-4)
    pre_matches = all(abs(a - p) <= 1e-4 for a, p in zip(actual, expected_pre))
    assert case["interpretation"]["pre_prediction_matches_pdf"] is pre_matches
    assert case["interpretation"]["save_prediction_matches_pdf"] is True
    assert case["interpretation"]["classification"] == ("control_agrees" if pre_matches else "counterexample")
    assert case["interpretation"]["pre_prediction_error_pt"] == pytest.approx(
        [a - p for a, p in zip(actual, expected_pre)]
    )
    assert case["interpretation"]["save_minus_pre_bounds_inches"] == pytest.approx(
        [a - b for a, b in zip(saved, pre)]
    )


def test_probe_uses_only_pre_draw_and_save_time_bbox_calls_and_restores_rc(monkeypatch):
    probe = _probe()
    calls = []
    original = Figure.get_tightbbox

    def record(self, renderer=None, *args, **kwargs):
        calls.append((type(renderer).__name__, self.canvas.is_saving()))
        return original(self, renderer, *args, **kwargs)

    monkeypatch.setattr(Figure, "get_tightbbox", record)
    with mpl.rc_context({"font.size": 37, "pdf.fonttype": 3, "savefig.bbox": "tight", "savefig.transparent": True}):
        report = probe.run_probe()
        assert mpl.rcParams["font.size"] == 37
        assert mpl.rcParams["pdf.fonttype"] == 3
        assert mpl.rcParams["savefig.bbox"] == "tight"
        assert mpl.rcParams["savefig.transparent"] is True
    assert calls == [("RendererAgg", False), ("MixedModeRenderer", True)] * 2
    assert report["premises"]["pdf_fonttype"] == 42
    assert report["premises"]["pdfium_render_scale"] == 1
    assert report["premises"]["pdfium_execution"] == "same_process_serial"
    assert report["premises"]["pdf_storage"] == "memory"
    # Ambient style must not change this fixture's measurements.
    assert report["alpha_cases"][0]["pdf"]["center_rgb"] == [102, 102, 102]
    assert report["bbox_cases"][0]["pre_draw_predicted_page_size_pt"] == pytest.approx([282.44, 211.88])


@pytest.mark.parametrize("instance_override", [False, True])
def test_tightbbox_instance_wrapper_is_restored_even_when_save_raises(monkeypatch, instance_override):
    probe = _probe()
    fig = Figure(figsize=(4, 3), dpi=100)
    FigureCanvasAgg(fig)
    if instance_override:
        fig.get_tightbbox = fig.get_tightbbox
    before = dict(fig.__dict__)

    def fail_save(*args, **kwargs):
        raise OSError("injected save failure")

    monkeypatch.setattr(fig, "savefig", fail_save)
    with pytest.raises(OSError, match="injected save failure"):
        probe._save_pdf_with_tightbbox_capture(fig)
    assert ("get_tightbbox" in fig.__dict__) is instance_override
    if instance_override:
        assert fig.__dict__["get_tightbbox"] is before["get_tightbbox"]


@pytest.mark.parametrize("broken", ["control_pixel", "fonttype", "getter", "save_size", "restoration"])
def test_main_refuses_to_write_when_controls_or_premises_are_broken(monkeypatch, broken):
    probe = _probe()
    report = deepcopy(_report())
    if broken == "control_pixel":
        report["alpha_cases"][1]["pdf"]["center_rgb"] = [163, 163, 163]
    elif broken == "fonttype":
        report["premises"]["pdf_fonttype"] = 3
    elif broken == "getter":
        report["alpha_cases"][0]["get_alpha"] = 0.5
    elif broken == "save_size":
        report["bbox_cases"][0]["pdf"]["page_size_pt"] = [1, 1]
    else:
        report["bbox_cases"][1]["get_tightbbox_restored"] = False
    monkeypatch.setattr(probe, "run_probe", lambda: report)

    def forbid_write(*args, **kwargs):
        pytest.fail("Artifact write occurred before validation")

    monkeypatch.setattr(Path, "write_text", forbid_write)
    with pytest.raises(AssertionError):
        probe.main()


def test_main_serializes_only_the_designated_artifact_after_validation(monkeypatch):
    probe = _probe()
    report = deepcopy(_report())
    writes = []
    monkeypatch.setattr(probe, "run_probe", lambda: report)

    def capture_write(path, text, *, encoding, newline=None):
        writes.append((path, json.loads(text), encoding, newline))
        return len(text)

    monkeypatch.setattr(Path, "write_text", capture_write)
    probe.main()
    assert writes == [(ARTIFACT, report, "utf-8", "\n")]


def test_main_writes_utf8_lf_bytes_not_platform_newlines(tmp_path, monkeypatch):
    probe = _probe()
    report = deepcopy(_report())
    destination = tmp_path / 'artifacts' / 'b1'
    destination.mkdir(parents=True)
    monkeypatch.setattr(probe, '__file__', str(tmp_path / 'spikes' / 'probe.py'))
    monkeypatch.setattr(probe, 'run_probe', lambda: deepcopy(report))
    probe.main()
    data = (destination / 'capture-semantics-probe.json').read_bytes()
    assert b'\r\n' not in data
    assert data.endswith(b'\n')
    assert json.loads(data)['classification'] == 'capture_contract_counterexamples'
