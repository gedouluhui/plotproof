"""Reproduce two Matplotlib capture-contract counterexamples with real PDFs.

This standalone probe imports no PlotProof product code or benchmark data.
run_probe() returns observations without writing artifacts. The CLI validates
controls and fixture premises before writing only the designated B1 JSON.
PDFs remain in memory; PDFium work is serial and every native/image handle is
closed explicitly. No PNG, post-save tightbbox measurement, or detector score.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import platform
import re
from threading import Lock

import matplotlib as mpl
from matplotlib import ft2font
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import numpy as np
import PIL
import pypdfium2 as pdfium


_PROBE_LOCK = Lock()
_PAGE_TOLERANCE_PT = 1e-4  # PDFium reports float-sized page dimensions.
_METADATA = {"CreationDate": None, "ModDate": None}


def _inspect_pdf(data: bytes, *, render_center: bool = False) -> dict:
    """Copy observations before releasing PDFium/Pillow resources, in order."""
    document = pdfium.PdfDocument(data)
    try:
        assert len(document) == 1, "Fixture must produce exactly one PDF page"
        page = document[0]
        try:
            result = {
                "page_count": len(document),
                "bytes_length": len(data),
                "page_size_pt": list(map(float, page.get_size())),
                "media_box_pt": list(map(float, page.get_mediabox())),
                "crop_box_pt": list(map(float, page.get_cropbox())),
                "rotation_degrees": page.get_rotation(),
            }
            if render_center:
                bitmap = page.render(scale=1)
                try:
                    image = bitmap.to_pil()
                    try:
                        rgb = image.convert("RGB")
                        try:
                            xy = (rgb.width // 2, rgb.height // 2)
                            result.update({
                                "bitmap_size_px": list(rgb.size),
                                "sample_xy_px": list(xy),
                                "center_rgb": list(rgb.getpixel(xy)),
                                "background_sample_xy_px": [0, 0],
                                "background_rgb": list(rgb.getpixel((0, 0))),
                            })
                        finally:
                            rgb.close()
                    finally:
                        image.close()
                finally:
                    bitmap.close()
                # Uncompressed ExtGState entries corroborate the raster only.
                # This search is not a general PDF parser or object association.
                result["auxiliary_fill_alpha_values"] = sorted({
                    float(value) for value in re.findall(rb"/ca\s+([0-9]*\.?[0-9]+)\b", data)
                })
            return result
        finally:
            page.close()
    finally:
        document.close()


def _alpha_case(case_id: str, intrinsic_alpha: float, artist_alpha: float | None) -> dict:
    fig = Figure(figsize=(2, 2), dpi=100, facecolor="white")
    canvas = FigureCanvasAgg(fig)
    rgba = (0, 0, 0, intrinsic_alpha)
    patch = Rectangle(
        (0.2, 0.2), 0.6, 0.6, transform=fig.transFigure,
        facecolor=rgba, alpha=artist_alpha, edgecolor="none",
    )
    fig.add_artist(patch)
    facecolor = list(map(float, patch.get_facecolor()))
    getter_alpha = patch.get_alpha()
    product = facecolor[3] * (1.0 if getter_alpha is None else getter_alpha)
    # Black over opaque white: round(255 * (1 - alpha)). These hypotheses
    # are independent of the actual PDFium pixels collected below.
    product_rgb = [round(255 * (1 - product))] * 3
    draw_alpha = intrinsic_alpha if artist_alpha is None else artist_alpha
    draw_rgb = [round(255 * (1 - draw_alpha))] * 3
    with BytesIO() as output:
        fig.savefig(output, format="pdf", bbox_inches=None, transparent=False, metadata=_METADATA)
        pdf = _inspect_pdf(output.getvalue(), render_center=True)
    product_matches = pdf["center_rgb"] == product_rgb
    draw_matches = pdf["center_rgb"] == draw_rgb
    classification = "inconclusive"
    if draw_matches:
        classification = "control_agrees" if product_matches else "counterexample"
    return {
        "case_id": case_id,
        "figure_size_inches": list(map(float, fig.get_size_inches())),
        "figure_dpi": float(fig.dpi),
        "canvas": type(canvas).__name__,
        "figure_facecolor_rgba": list(map(float, fig.get_facecolor())),
        "rectangle_bounds_figure": [patch.get_x(), patch.get_y(), patch.get_width(), patch.get_height()],
        "edgecolor_rgba": list(map(float, patch.get_edgecolor())),
        "input_facecolor_rgba": list(rgba),
        "input_artist_alpha": artist_alpha,
        "get_facecolor_rgba": facecolor,
        "get_alpha": getter_alpha,
        "frozen_getter_product_alpha": product,
        "frozen_prediction_rgb": product_rgb,
        "draw_contract_alpha": draw_alpha,
        "draw_contract_prediction_rgb": draw_rgb,
        "pdf": pdf,
        "interpretation": {
            "classification": classification,
            "frozen_product_matches_render": product_matches,
            "draw_contract_matches_render": draw_matches,
            "render_implied_black_alpha": [1 - channel / 255 for channel in pdf["center_rgb"]],
        },
    }


def _save_pdf_with_tightbbox_capture(fig: Figure) -> tuple[bytes, list[dict], bool]:
    """Wrap this figure only; return the exact save-time bounds, never post-save."""
    missing = object()
    previous_instance_value = fig.__dict__.get("get_tightbbox", missing)
    original = fig.get_tightbbox
    calls = []

    def capture(renderer=None, *args, **kwargs):
        bbox = original(renderer, *args, **kwargs)
        calls.append({
            "renderer": type(renderer).__name__,
            "bounds_inches": list(map(float, bbox.bounds)),
            "figure_dpi": float(fig.dpi),
            "is_saving": bool(fig.canvas.is_saving()),
        })
        return bbox  # Do not modify the object consumed by savefig.

    fig.get_tightbbox = capture
    try:
        with BytesIO() as output:
            fig.savefig(
                output, format="pdf", bbox_inches="tight", pad_inches=0.1,
                transparent=False, metadata=_METADATA,
            )
            data = output.getvalue()
    finally:
        if previous_instance_value is missing:
            del fig.get_tightbbox
        else:
            fig.get_tightbbox = previous_instance_value
    restored = fig.__dict__.get("get_tightbbox", missing) is previous_instance_value
    return data, calls, restored


def _bbox_case(*, constrained: bool) -> dict:
    fig = Figure(figsize=(4, 3), dpi=100, layout="constrained" if constrained else None)
    canvas = FigureCanvasAgg(fig)
    ax = fig.subplots()
    line, = ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_ylabel("Value", rotation=0, ha="right")
    ax.set_xlabel("Time")
    canvas.draw()
    renderer = canvas.get_renderer()
    pre = list(map(float, fig.get_tightbbox(renderer).bounds))
    engine = fig.get_layout_engine()
    data, calls, restored = _save_pdf_with_tightbbox_capture(fig)
    assert len(calls) == 1, "Need one unambiguous save-time tightbbox result"
    saved = calls[0]["bounds_inches"]
    pdf = _inspect_pdf(data)
    pre_prediction = [(dimension + 2 * 0.1) * 72 for dimension in pre[2:]]
    save_prediction = [(dimension + 2 * 0.1) * 72 for dimension in saved[2:]]
    pre_error = [a - b for a, b in zip(pdf["page_size_pt"], pre_prediction)]
    save_error = [a - b for a, b in zip(pdf["page_size_pt"], save_prediction)]
    pre_matches = all(abs(error) <= _PAGE_TOLERANCE_PT for error in pre_error)
    save_matches = all(abs(error) <= _PAGE_TOLERANCE_PT for error in save_error)
    classification = "inconclusive"
    if save_matches:
        classification = "control_agrees" if pre_matches else "counterexample"
    return {
        "case_id": "constrained_layout" if constrained else "ordinary",
        "figure_size_inches": list(map(float, fig.get_size_inches())),
        "figure_dpi": float(fig.dpi),
        "canvas": type(canvas).__name__,
        "layout_engine": type(engine).__name__ if engine is not None else None,
        "plot_x": line.get_xdata().tolist(),
        "plot_y": line.get_ydata().tolist(),
        "ylabel": ax.get_ylabel(),
        "ylabel_rotation": ax.yaxis.label.get_rotation(),
        "ylabel_ha": ax.yaxis.label.get_ha(),
        "xlabel": ax.get_xlabel(),
        "pre_draw_renderer": type(renderer).__name__,
        "pre_draw_tightbbox_inches": pre,
        "save_tightbbox_calls": calls,
        "get_tightbbox_restored": restored,
        "pre_draw_predicted_page_size_pt": pre_prediction,
        "save_predicted_page_size_pt": save_prediction,
        "pdf": pdf,
        "interpretation": {
            "classification": classification,
            "save_minus_pre_bounds_inches": [a - b for a, b in zip(saved, pre)],
            "bounds_agree_within_1e_9_inches": all(abs(a - b) <= 1e-9 for a, b in zip(saved, pre)),
            "pre_prediction_error_pt": pre_error,
            "save_prediction_error_pt": save_error,
            "pre_prediction_matches_pdf": pre_matches,
            "save_prediction_matches_pdf": save_matches,
        },
    }


def run_probe() -> dict:
    """Return fresh serial observations; restore rcParams and write no files.

    The lock serializes calls through this module, not unrelated third-party
    PDFium or Matplotlib calls. Run the owner command without parallel workers.
    """
    defaults = dict(mpl.rcParamsDefault)
    defaults.pop("backend", None)  # Do not select/change the caller's backend.
    defaults.update({"pdf.fonttype": 42, "font.family": ["DejaVu Sans"]})
    with _PROBE_LOCK, mpl.rc_context(defaults):
        premises = {
            "pdf_fonttype": mpl.rcParams["pdf.fonttype"],
            "pdf_use14corefonts": mpl.rcParams["pdf.use14corefonts"],
            "font_family": list(mpl.rcParams["font.family"]),
            "font_size_pt": float(mpl.rcParams["font.size"]),
            "text_usetex": mpl.rcParams["text.usetex"],
            "bbox_padding_inches": 0.1,
            "pdf_points_per_inch": 72,
            "page_comparison_tolerance_pt": _PAGE_TOLERANCE_PT,
            "pdfium_render_scale": 1,
            "pdfium_execution": "same_process_serial",
            "pdf_storage": "memory",
        }
        alpha_cases = [
            _alpha_case("artist_alpha_0_6", 0.6, 0.6),
            _alpha_case("artist_alpha_none", 0.6, None),
            _alpha_case("opaque", 1.0, 1.0),
        ]
        bbox_cases = [_bbox_case(constrained=False), _bbox_case(constrained=True)]
    return {
        "schema_version": 1,
        "classification": "capture_contract_counterexamples",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        "versions": {
            "python": platform.python_version(),
            "matplotlib": mpl.__version__,
            "pypdfium2": str(pdfium.PYPDFIUM_INFO),
            "pdfium": str(pdfium.PDFIUM_INFO),
            "numpy": np.__version__,
            "pillow": PIL.__version__,
            "freetype": ft2font.__freetype_version__,
        },
        "premises": premises,
        "alpha_cases": alpha_cases,
        "bbox_cases": bbox_cases,
        "observed_counterexamples": [
            case["case_id"] for case in alpha_cases + bbox_cases
            if case["interpretation"]["classification"] == "counterexample"
        ],
        "limitations": [
            "Capture-contract characterization only; no product detector evaluation or accuracy claim.",
            "Synthetic fixtures only; no benchmark, holdout, or frozen B0 files are read or changed.",
            "Alpha evidence is the center of one black rectangle over opaque white at PDFium scale 1.",
            "PDF /ca byte search is auxiliary, not a general parser or proof of artist association.",
            "Tightbbox evidence is pre-draw Agg versus the actual save-time renderer, never post-save.",
            "Constrained layout is an observed comparison, not a presumed agreeing control.",
            "Font metrics, Matplotlib, FreeType and PDFium versions may change these observations.",
            "Page agreement uses 0.0001 pt tolerance for PDFium page-size float precision.",
            "The probe lock cannot serialize unrelated callers of Matplotlib or PDFium.",
        ],
    }


def _assert_premises_and_controls(report: dict) -> None:
    """Gate artifact writes on raw evidence, not the report's verdict flags."""
    premises = report["premises"]
    assert premises["pdf_fonttype"] == 42
    assert premises["pdf_use14corefonts"] is False
    assert premises["font_family"] == ["DejaVu Sans"]
    assert premises["font_size_pt"] == 10
    assert premises["text_usetex"] is False
    assert premises["bbox_padding_inches"] == 0.1
    assert premises["pdf_points_per_inch"] == 72
    assert premises["pdfium_render_scale"] == 1
    assert premises["pdfium_execution"] == "same_process_serial"
    assert premises["pdf_storage"] == "memory"
    alphas = {case["case_id"]: case for case in report["alpha_cases"]}
    assert len(report["alpha_cases"]) == 3
    assert set(alphas) == {"artist_alpha_0_6", "artist_alpha_none", "opaque"}
    for name, intrinsic, artist, product, predicted in (
        ("artist_alpha_0_6", 0.6, 0.6, 0.36, [163, 163, 163]),
        ("artist_alpha_none", 0.6, None, 0.6, [102, 102, 102]),
        ("opaque", 1.0, 1.0, 1.0, [0, 0, 0]),
    ):
        case = alphas[name]
        assert case["figure_size_inches"] == [2, 2] and case["figure_dpi"] == 100
        assert case["canvas"] == "FigureCanvasAgg"
        assert case["figure_facecolor_rgba"] == [1, 1, 1, 1]
        assert case["rectangle_bounds_figure"] == [0.2, 0.2, 0.6, 0.6]
        assert case["edgecolor_rgba"][3] == 0
        assert case["input_facecolor_rgba"] == case["get_facecolor_rgba"] == [0, 0, 0, intrinsic]
        assert case["input_artist_alpha"] == case["get_alpha"] == artist
        assert abs(case["frozen_getter_product_alpha"] - product) < 1e-12
        assert case["frozen_prediction_rgb"] == predicted
        pdf = case["pdf"]
        assert pdf["page_count"] == 1 and pdf["rotation_degrees"] == 0
        assert pdf["page_size_pt"] == [144, 144]
        assert pdf["bitmap_size_px"] == [144, 144] and pdf["sample_xy_px"] == [72, 72]
        assert pdf["background_rgb"] == [255, 255, 255]
    # These controls have independent literal expected pixels. Do not assert
    # that constrained layout agrees, or require counterexamples to persist.
    assert alphas["artist_alpha_none"]["pdf"]["center_rgb"] == [102, 102, 102]
    assert alphas["opaque"]["pdf"]["center_rgb"] == [0, 0, 0]
    boxes = {case["case_id"]: case for case in report["bbox_cases"]}
    assert len(report["bbox_cases"]) == 2
    assert set(boxes) == {"ordinary", "constrained_layout"}
    for name, engine in (("ordinary", None), ("constrained_layout", "ConstrainedLayoutEngine")):
        case = boxes[name]
        assert case["figure_size_inches"] == [4, 3] and case["figure_dpi"] == 100
        assert case["canvas"] == "FigureCanvasAgg" and case["pre_draw_renderer"] == "RendererAgg"
        assert case["layout_engine"] == engine
        assert case["plot_x"] == [0, 1, 2] and case["plot_y"] == [0, 1, 4]
        assert case["ylabel"] == "Value" and case["xlabel"] == "Time"
        assert case["ylabel_rotation"] == 0 and case["ylabel_ha"] == "right"
        assert case["get_tightbbox_restored"] is True
        assert len(case["save_tightbbox_calls"]) == 1
        saved = case["save_tightbbox_calls"][0]
        assert saved["renderer"] == "MixedModeRenderer" and saved["is_saving"] is True
        assert saved["figure_dpi"] == 72
        pdf = case["pdf"]
        assert pdf["page_count"] == 1 and pdf["rotation_degrees"] == 0
        assert len(pdf["page_size_pt"]) == 2 and len(saved["bounds_inches"]) == 4
        for actual, extent in zip(pdf["page_size_pt"], saved["bounds_inches"][2:]):
            assert abs(actual - (extent + 0.2) * 72) <= 1e-4


def main() -> None:
    if not __debug__:
        raise RuntimeError("Run without -O: artifact generation requires enabled assertions")
    report = run_probe()
    _assert_premises_and_controls(report)
    destination = Path(__file__).resolve().parents[1] / "artifacts" / "b1" / "capture-semantics-probe.json"
    assert destination.parent.is_dir(), "The designated artifact directory must already exist"
    payload = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    destination.write_text(payload, encoding="utf-8", newline="\n")
    print("capture_contract_counterexamples: " + ", ".join(report["observed_counterexamples"]))


if __name__ == "__main__":
    main()
