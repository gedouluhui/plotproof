"""B0 D1 boundary probe: the page-boundary predicate on real PDFium char boxes.

Regression probe for the round-8 finding that PDFium returns zero-area
character boxes for spaces and for the CR/LF of a line break, and that the
round-7 wording of section 7 flagged those boxes as clipped on a fully inside
two-line title. It is not the PlotProof detector.

Three fixtures are measured because PDFium behaves differently by text path:
an axes title and a figure-level text report zero-area boxes only for CR/LF
while their spaces keep hairline (positive-area) boxes, and the tick-label
fixture also reports zero-area boxes for the spaces that separate x tick
labels. The frozen predicate must be clean on all three.

Run:
    python spikes/b0_d1_boundary_probe.py

Writes artifacts/b0/d1-boundary-probe.json only when every check passes. A
failed run writes artifacts/b0/d1-boundary-probe-FAILED.json and keeps the
passing record intact. All PDFium calls are serialized in this process.
"""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version as dist_version
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "b0"

TWO_LINE = (
    "Quarterly revenue by region, preliminary figures (2026, USD)\n"
    "Source: internal ledger; values rounded to the nearest thousand"
)
FIGURE_SPEC = {
    "figsize_in": [10.0, 6.0],
    "dpi": 100,
    "fonttype": 42,
    "font_family": "DejaVu Sans",
    "font_size_pt": 10,
    "fixtures": {
        "axes_title": {"kind": "axes_title", "text": TWO_LINE},
        "tick_labels": {"kind": "tick_labels", "text": TWO_LINE},
        "figure_text": {"kind": "figure_text", "text": TWO_LINE},
    },
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


def build_pdf(path: Path, fixture: dict[str, object]) -> None:
    spec = FIGURE_SPEC
    plt.rcParams["pdf.fonttype"] = spec["fonttype"]
    plt.rcParams["font.family"] = [spec["font_family"]]
    fig, ax = plt.subplots(figsize=tuple(spec["figsize_in"]), dpi=spec["dpi"])
    if fixture["kind"] == "tick_labels":
        ax.set_title(fixture["text"], fontsize=spec["font_size_pt"])
    elif fixture["kind"] == "axes_title":
        ax.set_axis_off()
        ax.set_title(fixture["text"], fontsize=spec["font_size_pt"])
    else:
        ax.set_axis_off()
        fig.text(0.5, 0.5, fixture["text"], ha="center", va="center", fontsize=spec["font_size_pt"])
    fig.savefig(
        path,
        format="pdf",
        metadata={"Creator": "plotproof-b0-d1-probe", "CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def read_boxes(path: Path) -> dict[str, object]:
    """Return the page rectangle, the text, and every character box."""
    doc = pdfium.PdfDocument(str(path))
    try:
        page_count = len(doc)
        page = doc[0]
        try:
            crop = list(page.get_cropbox())  # left, bottom, right, top
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
        "page_rect": [crop[0], crop[1], crop[2], crop[3]],
        "text": text,
        "char_count": char_count,
        "char_boxes": boxes,
    }


# --- the one positive-area predicate (prereg v1.5, sections 4 and 7) --------


def area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def inside_area(box: list[float], page: list[float]) -> float:
    x0 = max(box[0], page[0])
    y0 = max(box[1], page[1])
    x1 = min(box[2], page[2])
    y1 = min(box[3], page[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def center(box: list[float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def center_outside(box: list[float], page: list[float]) -> bool:
    cx, cy = center(box)
    return cx < page[0] or cx > page[2] or cy < page[1] or cy > page[3]


def classify(box: list[float], page: list[float]) -> str:
    """Return 'none', 'medium' or 'high' under the frozen positive-area rule."""
    a = area(box)
    if a <= EPS:
        return "none"
    a_in = inside_area(box, page)
    a_out = a - a_in
    if a_out >= 0.5 * a - EPS or center_outside(box, page):
        return "high"
    if a_out > 0.0:
        return "medium"
    return "none"


def literal_s7_flags(box: list[float], page: list[float]) -> bool:
    """Round-7 section 7 wording: 'at least 50% of the box area outside'."""
    a = area(box)
    a_in = inside_area(box, page)
    return (a - a_in) >= 0.5 * a


def literal_s4_flags(box: list[float], page: list[float]) -> bool:
    """Round-7 section 4 wording: 'less than 50% of its area inside'."""
    a = area(box)
    a_in = inside_area(box, page)
    return a_in < 0.5 * a


def synthetic_cases() -> list[dict[str, object]]:
    page = [0.0, 0.0, 100.0, 100.0]
    return [
        {"name": "fully_inside", "page": page, "box": [10.0, 10.0, 20.0, 20.0], "expected": "none"},
        {"name": "half_outside_inclusive", "page": page, "box": [-5.0, 10.0, 5.0, 20.0], "expected": "high"},
        {
            "name": "just_under_half_outside",
            "page": page,
            "box": [-4.9995, 10.0, 5.0005, 20.0],
            "expected": "medium",
        },
        {"name": "fully_outside", "page": page, "box": [120.0, 120.0, 140.0, 140.0], "expected": "high"},
        {"name": "straddles_corner", "page": page, "box": [90.0, 90.0, 110.0, 110.0], "expected": "high"},
        {"name": "zero_area_inside", "page": page, "box": [15.0, 10.0, 15.0, 20.0], "expected": "none"},
        {"name": "zero_area_center_outside", "page": page, "box": [-5.0, 10.0, -5.0, 20.0], "expected": "none"},
        {"name": "zero_area_at_page_edge", "page": page, "box": [0.0, 10.0, 0.0, 20.0], "expected": "none"},
        {"name": "tiny_sliver_outside", "page": page, "box": [-0.001, 10.0, 10.0, 20.0], "expected": "medium"},
    ]


def center_clause_is_implied() -> dict[str, object]:
    """For positive-area boxes, center-outside implies >50% area outside.

    Search a small deterministic grid; report the number of positive-area
    boxes with an outside center and the smallest outside fraction among them.
    """
    page = [0.0, 0.0, 100.0, 100.0]
    checked = 0
    outside_centers = 0
    min_fraction = None
    for x0 in (-60, -20, -5, 0, 20, 60, 95):
        for x1 in (x0 + 1, 0, 5, 20, 60, 105, 140):
            for y0 in (-60, -20, 0, 40, 95):
                for y1 in (y0 + 1, 20, 60, 105, 140):
                    box = [float(x0), float(y0), float(x1), float(y1)]
                    a = area(box)
                    if a <= 0:
                        continue
                    checked += 1
                    if not center_outside(box, page):
                        continue
                    outside_centers += 1
                    fraction = (a - inside_area(box, page)) / a
                    min_fraction = (
                        fraction if min_fraction is None else min(min_fraction, fraction)
                    )
    return {
        "positive_boxes_checked": checked,
        "outside_centers": outside_centers,
        "min_outside_fraction": min_fraction,
        "implied": min_fraction is not None and min_fraction > 0.5,
    }


def measure_fixture(path: Path, data: dict[str, object]) -> dict[str, object]:
    page = data["page_rect"]
    text = data["text"]
    boxes = data["char_boxes"]
    zero_area = []
    for index, box in enumerate(boxes):
        if area(box) <= EPS:
            char = text[index] if index < len(text) else "?"
            zero_area.append(
                {
                    "index": index,
                    "char": char,
                    "codepoint": f"U+{ord(char):04X}" if char != "?" else None,
                    "box": [round(value, 4) for value in box],
                }
            )
    verdicts = [classify(box, page) for box in boxes]
    literal_s7 = sum(1 for box in boxes if literal_s7_flags(box, page))
    literal_s4 = sum(1 for box in boxes if literal_s4_flags(box, page))
    positive = [box for box in boxes if area(box) > EPS]
    return {
        "pdf_sha256": sha256_file(path),
        "page_rect_pt": page,
        "char_count": len(boxes),
        "text": text,
        "zero_area": {
            "count": len(zero_area),
            "characters": {
                "space": sum(1 for entry in zero_area if entry["char"] == " "),
                "cr": sum(1 for entry in zero_area if entry["char"] == "\r"),
                "lf": sum(1 for entry in zero_area if entry["char"] == "\n"),
            },
            "boxes": zero_area,
        },
        "corrected_predicate": {
            "high": verdicts.count("high"),
            "medium": verdicts.count("medium"),
        },
        "literal_round7": {
            "s7_at_least_half_area_outside_flagged": literal_s7,
            "s4_less_than_half_area_inside_flagged": literal_s4,
        },
        "positive_boxes": {
            "count": len(positive),
            "inside_all": all(
                box[0] >= page[0] - EPS
                and box[1] >= page[1] - EPS
                and box[2] <= page[2] + EPS
                and box[3] <= page[3] + EPS
                for box in positive
            ),
            "min_x0": min(box[0] for box in positive),
            "max_x1": max(box[2] for box in positive),
            "min_y0": min(box[1] for box in positive),
            "max_y1": max(box[3] for box in positive),
        },
    }


def main() -> int:
    checks = Checks()
    measured: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="plotproof-d1-") as tmp:
        tmpdir = Path(tmp)
        for name, fixture in FIGURE_SPEC["fixtures"].items():
            first = tmpdir / f"{name}.pdf"
            second = tmpdir / f"{name}-repeat.pdf"
            build_pdf(first, fixture)
            build_pdf(second, fixture)
            data = read_boxes(first)
            data_repeat = read_boxes(second)
            record = measure_fixture(first, data)
            measured[name] = record

            checks.add(
                f"{name}.single_page",
                data["page_count"] == 1,
                {"page_count": data["page_count"], "page_rect_pt": data["page_rect"]},
            )
            checks.add(
                f"{name}.page_size_is_10x6_at_100dpi",
                abs((data["page_rect"][2] - data["page_rect"][0]) - 720.0) < 0.01
                and abs((data["page_rect"][3] - data["page_rect"][1]) - 432.0) < 0.01,
                data["page_rect"],
            )
            checks.add(
                f"{name}.text_index_matches_char_boxes",
                len(data["text"]) == data["char_count"],
                {"len_text": len(data["text"]), "char_count": data["char_count"]},
            )
            checks.add(
                f"{name}.two_lines_present",
                "\r\n" in data["text"] or "\n" in data["text"],
                {"text": data["text"]},
            )
            zero = record["zero_area"]
            checks.add(
                f"{name}.zero_area_boxes_exist",
                zero["count"] > 0,
                {"zero_area_count": zero["count"], "char_count": record["char_count"]},
            )
            char_set = {entry["char"] for entry in zero["boxes"]}
            checks.add(
                f"{name}.zero_area_boxes_are_whitespace",
                char_set.issubset({" ", "\r", "\n"}),
                {
                    "characters": [
                        {"char": ch, "codepoint": f"U+{ord(ch):04X}"} for ch in sorted(char_set)
                    ]
                },
            )
            checks.add(
                f"{name}.all_positive_area_boxes_inside_page",
                record["positive_boxes"]["inside_all"],
                {
                    "positive_count": record["positive_boxes"]["count"],
                    "min_x0": record["positive_boxes"]["min_x0"],
                    "max_x1": record["positive_boxes"]["max_x1"],
                    "min_y0": record["positive_boxes"]["min_y0"],
                    "max_y1": record["positive_boxes"]["max_y1"],
                },
            )
            checks.add(
                f"{name}.corrected_predicate_clean",
                record["corrected_predicate"]["high"] == 0
                and record["corrected_predicate"]["medium"] == 0,
                record["corrected_predicate"],
            )
            checks.add(
                f"{name}.literal_round7_s7_flags_zero_area_boxes",
                record["literal_round7"]["s7_at_least_half_area_outside_flagged"] == zero["count"],
                {
                    "literal_s7_flagged": record["literal_round7"]["s7_at_least_half_area_outside_flagged"],
                    "zero_area_boxes": zero["count"],
                },
            )
            checks.add(
                f"{name}.literal_round7_s4_does_not_flag_zero_area_boxes",
                record["literal_round7"]["s4_less_than_half_area_inside_flagged"] == 0,
                {"literal_s4_flagged": record["literal_round7"]["s4_less_than_half_area_inside_flagged"]},
            )
            checks.add(
                f"{name}.byte_identical_repeat",
                record["pdf_sha256"] == sha256_file(second)
                and data["text"] == data_repeat["text"]
                and data["char_boxes"] == data_repeat["char_boxes"],
                {"sha256": record["pdf_sha256"], "sha256_repeat": sha256_file(second)},
            )

        title = measured["axes_title"]
        ticks = measured["tick_labels"]
        figure = measured["figure_text"]
        checks.add(
            "axes_title_only_cr_lf_are_zero_area",
            title["zero_area"]["characters"]["space"] == 0
            and title["zero_area"]["characters"]["cr"] == 1
            and title["zero_area"]["characters"]["lf"] == 1,
            title["zero_area"]["characters"],
        )
        checks.add(
            "tick_label_spaces_are_zero_area",
            ticks["zero_area"]["characters"]["space"] > 0,
            ticks["zero_area"]["characters"],
        )
        checks.add(
            "figure_text_spaces_have_positive_area",
            figure["zero_area"]["characters"]["space"] == 0
            and figure["positive_boxes"]["count"] == figure["char_count"] - 2,
            {
                "zero_area": figure["zero_area"]["characters"],
                "positive_boxes": figure["positive_boxes"]["count"],
                "char_count": figure["char_count"],
            },
        )
        checks.add(
            "round7_sections_disagreed_on_every_fixture",
            all(
                record["literal_round7"]["s7_at_least_half_area_outside_flagged"]
                != record["literal_round7"]["s4_less_than_half_area_inside_flagged"]
                for record in measured.values()
            ),
            {
                name: record["literal_round7"]
                for name, record in measured.items()
            },
        )

        cases = []
        cases_ok = True
        for case in synthetic_cases():
            got = classify(case["box"], case["page"])
            ok = got == case["expected"]
            cases_ok = cases_ok and ok
            cases.append({**case, "got": got, "ok": ok})
        checks.add("synthetic_endpoints", cases_ok, cases)

        implied = center_clause_is_implied()
        checks.add("center_clause_implied_for_positive_area", implied["implied"], implied)

    script_hash = sha256_file(Path(__file__).resolve())
    spec_hash = sha256_bytes(
        json.dumps(FIGURE_SPEC, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    record = {
        "schema_version": 1,
        "probe": "b0_d1_boundary_predicate",
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
            "pdfium_build": str(pdfium.PDFIUM_INFO),
        },
        "fixtures": measured,
        "corrected_predicate_rule": (
            "positive-area boxes only; A_out >= 0.5*A or center strictly outside "
            "=> high; 0 < A_out < 0.5*A => medium; A = 0 => ignored"
        ),
        "synthetic_cases": cases,
        "center_clause_check": implied,
        "checks": checks.items,
        "result": "PASS" if not checks.failed else "FAIL",
    }

    target = OUT / (
        "d1-boundary-probe.json" if not checks.failed else "d1-boundary-probe-FAILED.json"
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
