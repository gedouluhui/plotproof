"""B0 missing-glyph alignment probe: the injected U+20000 unit on real PDFium boxes.

Regression probe for the round-12 finding that the round-7 prose value 0.7045
was measured on U+9FD8 (the character in the string `Trend 鿘 chart`), not on
the injected U+20000 character that the D4 rule actually uses. This probe
draws `Trend 𠀀 chart` in DejaVu Sans under the pinned 10 pt binding, proves the
character is absent from both benchmark fonts and from PDF text extraction,
and measures the §7.1 missing-glyph rule: delete the proven-missing character,
match `Trend chart`, require the height band, and score the span bbox against
the unit's full source bbox (which still contains the missing character's
layout region).

It is not the PlotProof detector. The U+9FD8 cmap checks are recorded as
provenance: U+9FD8 is absent from DejaVu Sans but present in Noto Sans CJK SC,
so its 0.7045 measurement cannot be transferred to U+20000.

Run:
    python spikes/fetch_b0_font.py     # once, downloads the pinned OFL font
    python spikes/b0_missing_glyph_alignment_probe.py

Writes artifacts/b0/missing-glyph-alignment-probe.json only when every check
passes. A failed run writes artifacts/b0/missing-glyph-alignment-probe-FAILED.json
and keeps the passing record intact. All PDFium calls are serialized in this
process.
"""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
import unicodedata
import warnings
from datetime import datetime, timezone
from importlib.metadata import version as dist_version
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "b0"

PINNED_FONT = {
    "family": "Noto Sans CJK SC",
    "file": ".fonts/NotoSansCJKsc-Regular.otf",
    "bytes": 16_437_364,
    "sha256": "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b",
}
NOTO_PATH = ROOT / PINNED_FONT["file"]

MISSING = "\U00020000"
OTHER = "\u9fd8"
FONT_FAMILY = "DejaVu Sans"
FONT_SIZE_PT = 10.0
DPI = 100
FIGSIZE_IN = [4.0, 3.0]
UNIT_TEXT = f"Trend {MISSING} chart"
DELETED_TEXT = "Trend chart"
FIGURE_SPEC = {
    "figsize_in": FIGSIZE_IN,
    "dpi": DPI,
    "fonttype": 42,
    "font_family": FONT_FAMILY,
    "font_size_pt": FONT_SIZE_PT,
    "text": UNIT_TEXT,
    "deleted_text": DELETED_TEXT,
    "missing_codepoint": "U+20000",
    "provenance_codepoint": "U+9FD8",
}

EPS = 1e-9


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def add(self, check_id: str, ok: bool, detail: object) -> None:
        self.items.append(
            {"id": check_id, "status": "PASS" if ok else "FAIL", "detail": detail}
        )

    @property
    def failed(self) -> bool:
        return any(item["status"] == "FAIL" for item in self.items)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.name


def portable_font_record(path: Path) -> dict[str, str]:
    """Describe a font path without leaking machine-specific absolute paths."""
    resolved = path.resolve()
    record = {"name": resolved.name}
    try:
        record["relative_to_matplotlib_data"] = (
            resolved.relative_to(Path(matplotlib.get_data_path()).resolve()).as_posix()
        )
    except ValueError:
        pass
    return record


def unicode_cmap(path: Path) -> dict[str, object]:
    """Return the union of the font's Unicode cmap subtables."""
    font = TTFont(str(path), fontNumber=0, lazy=True)
    try:
        codepoints: set[int] = set()
        tables: list[dict[str, object]] = []
        for table in font["cmap"].tables:
            platform_id = table.platformID
            encoding_id = table.platEncID
            is_unicode = platform_id == 0 or (platform_id == 3 and encoding_id in (1, 10))
            if not is_unicode:
                continue
            table_points = set(table.cmap.keys())
            codepoints |= table_points
            tables.append(
                {
                    "platform_id": platform_id,
                    "encoding_id": encoding_id,
                    "format": table.format,
                    "size": len(table_points),
                }
            )
        return {
            "codepoints": codepoints,
            "unicode_subtables": tables,
            "cmap_table_count": len(font["cmap"].tables),
        }
    finally:
        font.close()


def best_cmap_glyph(path: Path, codepoint: int) -> str | None:
    font = TTFont(str(path), fontNumber=0, lazy=True)
    try:
        return font.getBestCmap().get(codepoint)
    finally:
        font.close()


def canonical_with_index(text: str, strip: bool) -> tuple[str, list[int | None]]:
    """§7.1 canonical map over `text`, plus one index (or None) per input char."""
    if strip:
        text = text.strip()
    mapped = [" " if ch.isspace() else ch for ch in text]
    out: list[str] = []
    mapping: list[int | None] = []
    previous_space = False
    for ch in mapped:
        if ch == " " and previous_space:
            mapping.append(None)
            continue
        normalized = unicodedata.normalize("NFKC", ch)
        if len(normalized) != 1:
            normalized = ch
        mapping.append(len(out))
        out.append(normalized)
        previous_space = ch == " "
    return "".join(out), mapping


def bbox_of(boxes: list[list[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def intersection_area(a: list[float], b: list[float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def iou(a: list[float], b: list[float]) -> float:
    inter = intersection_area(a, b)
    union = area(a) + area(b) - inter
    return 0.0 if union <= 0 else inter / union


def build_pdf(path: Path, horizontal_alignment: str = "center") -> dict[str, object]:
    """Draw the unit and return the pre-save source bbox in PDF points.

    Vertical alignment does not change the IoU: the source bbox and the
    extracted span translate together. Horizontal alignment does change the
    extracted span's sub-point start position, so both modes are measured.
    """
    plt.rcParams["pdf.fonttype"] = FIGURE_SPEC["fonttype"]
    plt.rcParams["font.family"] = [FONT_FAMILY]
    dejavu_path = font_manager.findfont(FONT_FAMILY)
    dejavu_props = FontProperties(fname=dejavu_path)
    fig = plt.figure(figsize=tuple(FIGSIZE_IN), dpi=DPI)
    fig.text(
        0.5,
        0.5,
        UNIT_TEXT,
        ha=horizontal_alignment,
        va="center",
        fontsize=FONT_SIZE_PT,
        fontproperties=dejavu_props,
    )
    with warnings.catch_warnings(record=True) as caught_draw:
        warnings.simplefilter("always")
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        artist = fig.texts[0]
        window = artist.get_window_extent(renderer)
        source_bbox = [
            window.x0 * 72.0 / DPI,
            window.y0 * 72.0 / DPI,
            window.x1 * 72.0 / DPI,
            window.y1 * 72.0 / DPI,
        ]
    with warnings.catch_warnings(record=True) as caught_save:
        warnings.simplefilter("always")
        fig.savefig(
            path,
            format="pdf",
            metadata={"Creator": "plotproof-b0-missing-glyph-probe", "CreationDate": None, "ModDate": None},
        )
    plt.close(fig)
    return {
        "source_bbox_pt": source_bbox,
        "horizontal_alignment": horizontal_alignment,
        "dejavu_path": dejavu_path,
        "warnings_draw": [str(item.message) for item in caught_draw],
        "warnings_save": [str(item.message) for item in caught_save],
    }


def read_pdf(path: Path) -> dict[str, object]:
    doc = pdfium.PdfDocument(str(path))
    try:
        page_count = len(doc)
        page = doc[0]
        try:
            crop = list(page.get_cropbox())
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
                char_count = textpage.count_chars()
                boxes = [list(textpage.get_charbox(i)) for i in range(char_count)]
            finally:
                textpage.close()
        finally:
            page.close()
    finally:
        doc.close()
    return {
        "page_count": page_count,
        "page_rect": crop,
        "text": text,
        "char_count": char_count,
        "char_boxes": boxes,
    }


def measure(
    path: Path,
    data: dict[str, object],
    build: dict[str, object],
    deleted_text: str,
    full_text: str,
) -> dict[str, object]:
    raw_text = data["text"]
    boxes = data["char_boxes"]
    source_bbox = build["source_bbox_pt"]

    pdf_canon, pdf_map = canonical_with_index(raw_text, strip=False)

    def span_for(needle: str) -> dict[str, object] | None:
        position = pdf_canon.find(needle)
        while position >= 0:
            end = position + len(needle)
            indices = [
                index
                for index, mapped_index in enumerate(pdf_map)
                if mapped_index is not None and position <= mapped_index < end
            ]
            if indices:
                span_boxes = [boxes[index] for index in indices]
                span_bbox = bbox_of(span_boxes)
                heights = sorted(
                    boxes[index][3] - boxes[index][1]
                    for index in indices
                    if boxes[index][3] - boxes[index][1] > 0
                )
                median_height = (
                    0.0
                    if not heights
                    else (
                        heights[len(heights) // 2]
                        if len(heights) % 2 == 1
                        else (heights[len(heights) // 2 - 1] + heights[len(heights) // 2]) / 2.0
                    )
                )
                return {
                    "canonical_position": position,
                    "char_indices": [indices[0], indices[-1] + 1],
                    "char_count": len(indices),
                    "bbox_pt": span_bbox,
                    "positive_heights": len(heights),
                    "median_height_pt": median_height,
                    "median_height_over_font_size": median_height / FONT_SIZE_PT,
                    "iou_vs_source_bbox": iou(span_bbox, source_bbox),
                    "intersection_area_pt2": intersection_area(span_bbox, source_bbox),
                    "span_area_pt2": area(span_bbox),
                }
            position = pdf_canon.find(needle, position + 1)
        return None

    full_canon, _ = canonical_with_index(full_text, strip=True)
    deleted_canon, _ = canonical_with_index(deleted_text, strip=True)
    return {
        "pdf_sha256": sha256_file(path),
        "page_rect_pt": data["page_rect"],
        "char_count": data["char_count"],
        "text": raw_text,
        "canonical_pdf": pdf_canon,
        "source_bbox_pt": source_bbox,
        "source_bbox_area_pt2": area(source_bbox),
        "full_canonical_needle": full_canon,
        "deleted_canonical_needle": deleted_canon,
        "full_needle_occurrences": pdf_canon.count(full_canon),
        "deleted_needle_occurrences": pdf_canon.count(deleted_canon),
        "full_needle_span": span_for(full_canon),
        "deleted_needle_span": span_for(deleted_canon),
    }


def main() -> int:
    checks = Checks()

    noto_size = NOTO_PATH.stat().st_size if NOTO_PATH.is_file() else -1
    noto_sha = sha256_file(NOTO_PATH) if NOTO_PATH.is_file() else None
    checks.add(
        "font.pinned_noto_present",
        noto_size == PINNED_FONT["bytes"] and noto_sha == PINNED_FONT["sha256"],
        {
            "path": PINNED_FONT["file"],
            "bytes": noto_size,
            "sha256": noto_sha,
            "expected_bytes": PINNED_FONT["bytes"],
            "expected_sha256": PINNED_FONT["sha256"],
        },
    )

    dejavu_path = Path(font_manager.findfont(FONT_FAMILY))
    dejavu = unicode_cmap(dejavu_path)
    noto = unicode_cmap(NOTO_PATH)
    dejavu_points = dejavu["codepoints"]
    noto_points = noto["codepoints"]

    checks.add(
        "cmap.dejavu_resolved",
        dejavu_path.is_file() and "dejavu" in dejavu_path.name.lower(),
        portable_font_record(dejavu_path),
    )
    checks.add(
        "cmap.noto_has_unicode_subtables",
        len(noto["unicode_subtables"]) > 0,
        noto["unicode_subtables"],
    )
    checks.add(
        "cmap.missing_absent_from_dejavu",
        0x20000 not in dejavu_points,
        {"codepoint": "U+20000", "unicode_subtables": dejavu["unicode_subtables"]},
    )
    checks.add(
        "cmap.missing_absent_from_noto",
        0x20000 not in noto_points,
        {"codepoint": "U+20000", "unicode_subtables": noto["unicode_subtables"]},
    )
    checks.add(
        "provenance.u9fd8_absent_from_dejavu",
        0x9FD8 not in dejavu_points,
        {"codepoint": "U+9FD8"},
    )
    checks.add(
        "provenance.u9fd8_present_in_noto",
        0x9FD8 in noto_points,
        {
            "codepoint": "U+9FD8",
            "noto_glyph": best_cmap_glyph(NOTO_PATH, 0x9FD8),
        },
    )

    with tempfile.TemporaryDirectory(prefix="plotproof-missing-glyph-") as tmp:
        tmpdir = Path(tmp)
        first = tmpdir / "u20000.pdf"
        second = tmpdir / "u20000-repeat.pdf"
        baseline = tmpdir / "u20000-left-aligned.pdf"
        build_first = build_pdf(first)
        build_second = build_pdf(second)
        build_baseline = build_pdf(baseline, horizontal_alignment="left")
        data_first = read_pdf(first)
        data_second = read_pdf(second)
        data_baseline = read_pdf(baseline)
        measured = measure(first, data_first, build_first, DELETED_TEXT, UNIT_TEXT)
        measured_baseline = measure(baseline, data_baseline, build_baseline, DELETED_TEXT, UNIT_TEXT)
        measured["horizontal_alignment_sensitivity"] = {
            "center": {
                "iou_vs_source_bbox": (
                    None
                    if measured["deleted_needle_span"] is None
                    else measured["deleted_needle_span"]["iou_vs_source_bbox"]
                ),
                "source_bbox_pt": build_first["source_bbox_pt"],
                "span_bbox_pt": (
                    None
                    if measured["deleted_needle_span"] is None
                    else measured["deleted_needle_span"]["bbox_pt"]
                ),
            },
            "left": {
                "iou_vs_source_bbox": (
                    None
                    if measured_baseline["deleted_needle_span"] is None
                    else measured_baseline["deleted_needle_span"]["iou_vs_source_bbox"]
                ),
                "source_bbox_pt": build_baseline["source_bbox_pt"],
                "span_bbox_pt": (
                    None
                    if measured_baseline["deleted_needle_span"] is None
                    else measured_baseline["deleted_needle_span"]["bbox_pt"]
                ),
            },
        }
        checks.add(
            "save.repeat_is_byte_identical",
            measured["pdf_sha256"] == sha256_file(second)
            and data_first["text"] == data_second["text"]
            and data_first["char_boxes"] == data_second["char_boxes"]
            and build_first["source_bbox_pt"] == build_second["source_bbox_pt"],
            {
                "sha256": measured["pdf_sha256"],
                "sha256_repeat": sha256_file(second),
                "source_bbox_pt": build_first["source_bbox_pt"],
            },
        )
        all_warnings = build_first["warnings_draw"] + build_first["warnings_save"]
        checks.add(
            "save.warning_names_missing_codepoint",
            any("Glyph 131072" in message for message in all_warnings),
            {"warnings": all_warnings},
        )
        checks.add(
            "save.warning_names_resolved_font",
            any(
                "Glyph 131072" in message and FONT_FAMILY in message
                for message in all_warnings
            ),
            {"warnings": all_warnings},
        )
        checks.add(
            "pdf.single_page_and_pinned_size",
            data_first["page_count"] == 1
            and abs((data_first["page_rect"][2] - data_first["page_rect"][0]) - 288.0) < 0.01
            and abs((data_first["page_rect"][3] - data_first["page_rect"][1]) - 216.0) < 0.01,
            {"page_count": data_first["page_count"], "page_rect_pt": data_first["page_rect"]},
        )
        checks.add(
            "pdf.text_index_matches_char_boxes",
            len(data_first["text"]) == data_first["char_count"],
            {"len_text": len(data_first["text"]), "char_count": data_first["char_count"]},
        )
        checks.add(
            "pdf.missing_character_absent_from_extraction",
            MISSING not in data_first["text"],
            {"codepoint": "U+20000", "text": data_first["text"]},
        )
        checks.add(
            "canonical.full_needle_absent",
            measured["full_needle_occurrences"] == 0,
            {
                "needle": measured["full_canonical_needle"],
                "occurrences": measured["full_needle_occurrences"],
            },
        )
        checks.add(
            "canonical.deleted_needle_present",
            measured["deleted_needle_occurrences"] == 1,
            {
                "needle": measured["deleted_canonical_needle"],
                "occurrences": measured["deleted_needle_occurrences"],
            },
        )
        span = measured["deleted_needle_span"]
        checks.add(
            "alignment.deleted_needle_span_found",
            span is not None,
            {"span": span},
        )
        if span is not None:
            checks.add(
                "alignment.height_band",
                0.20 <= span["median_height_over_font_size"] <= 1.50,
                {
                    "median_height_pt": span["median_height_pt"],
                    "font_size_pt": FONT_SIZE_PT,
                    "ratio": span["median_height_over_font_size"],
                },
            )
            checks.add(
                "alignment.iou_at_least_0_50",
                span["iou_vs_source_bbox"] >= 0.50,
                {
                    "iou": span["iou_vs_source_bbox"],
                    "span_bbox_pt": span["bbox_pt"],
                    "source_bbox_pt": measured["source_bbox_pt"],
                    "intersection_area_pt2": span["intersection_area_pt2"],
                    "span_area_pt2": span["span_area_pt2"],
                    "source_area_pt2": measured["source_bbox_area_pt2"],
                },
            )
            checks.add(
                "alignment.measured_value_matches_prereg",
                abs(span["iou_vs_source_bbox"] - 0.7734) <= 0.0001,
                {
                    "measured": span["iou_vs_source_bbox"],
                    "prereg_value": 0.7734,
                    "horizontal_alignment": "center",
                    "tolerance": 0.0001,
                },
            )
        baseline_span = measured_baseline["deleted_needle_span"]
        checks.add(
            "alignment.left_aligned_span_found",
            baseline_span is not None,
            {"span": baseline_span},
        )
        if baseline_span is not None:
            checks.add(
                "alignment.left_aligned_iou_at_least_0_50",
                baseline_span["iou_vs_source_bbox"] >= 0.50,
                {
                    "iou": baseline_span["iou_vs_source_bbox"],
                    "span_bbox_pt": baseline_span["bbox_pt"],
                    "source_bbox_pt": measured_baseline["source_bbox_pt"],
                },
            )
            checks.add(
                "alignment.left_aligned_value_matches_prereg",
                abs(baseline_span["iou_vs_source_bbox"] - 0.7730) <= 0.0001,
                {
                    "measured": baseline_span["iou_vs_source_bbox"],
                    "prereg_value": 0.7730,
                    "horizontal_alignment": "left",
                    "tolerance": 0.0001,
                },
            )
            checks.add(
                "alignment.rounds_to_three_decimals",
                round(span["iou_vs_source_bbox"], 3) == 0.773
                and round(baseline_span["iou_vs_source_bbox"], 3) == 0.773,
                {
                    "center": span["iou_vs_source_bbox"],
                    "left": baseline_span["iou_vs_source_bbox"],
                    "rounded": "0.773",
                },
            )

    script_hash = sha256_file(Path(__file__).resolve())
    spec_hash = sha256_bytes(
        json.dumps(FIGURE_SPEC, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    record = {
        "schema_version": 1,
        "probe": "b0_missing_glyph_alignment",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": project_path(Path(__file__).resolve()),
        "script_sha256": script_hash,
        "figure_spec": FIGURE_SPEC,
        "figure_spec_sha256": spec_hash,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "matplotlib": dist_version("matplotlib"),
            "pypdfium2": dist_version("pypdfium2"),
            "fonttools": dist_version("fonttools"),
            "pdfium_build": str(pdfium.PDFIUM_INFO),
        },
        "fonts": {
            "dejavu": {
                **portable_font_record(dejavu_path),
                "unicode_subtables": dejavu["unicode_subtables"],
            },
            "noto": {
                "path": PINNED_FONT["file"],
                "bytes": noto_size,
                "sha256": noto_sha,
                "unicode_subtables": noto["unicode_subtables"],
            },
        },
        "measurement": measured,
        "rule_under_test": (
            "§7.1 missing-glyph alignment: delete every proven-missing character, "
            "recompute the canonical string, require the height band, and require "
            "IoU >= 0.50 against the unit's full source bbox"
        ),
        "provenance_note": (
            "The round-7 prose value 0.7045 was measured on the U+9FD8 string "
            "`Trend 鿘 chart`; U+9FD8 is absent from DejaVu Sans and present in "
            "Noto Sans CJK SC, a different font behavior from U+20000, so 0.7045 "
            "is not a U+20000 measurement."
        ),
        "checks": checks.items,
        "result": "PASS" if not checks.failed else "FAIL",
    }

    target = OUT / (
        "missing-glyph-alignment-probe.json"
        if not checks.failed
        else "missing-glyph-alignment-probe-FAILED.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {"result": record["result"], "evidence": project_path(target)},
            ensure_ascii=False,
        )
    )
    for item in checks.items:
        print(f"{item['status']} {item['id']}")
    return 0 if not checks.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
