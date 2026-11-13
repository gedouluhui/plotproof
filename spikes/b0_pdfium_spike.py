"""B0 feasibility spike: Matplotlib figure -> PDF -> PDFium text/geometry/bitmap.

This is NOT the PlotProof detector. It only proves that the planned render and
extraction primitives work with the packages actually installed on this machine,
and records what fails or needs an UNKNOWN state.

Run:
    python spikes/fetch_b0_font.py     # once, downloads the pinned OFL font
    python spikes/b0_pdfium_spike.py

Writes evidence to artifacts/b0/ only when every check passes. A failed run
writes artifacts/b0/api-spike-FAILED.json and leaves the passing record intact.
All PDFium calls in this process are serialized by construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import warnings
from datetime import datetime, timezone
from importlib.metadata import distribution, version as dist_version
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
    "url": (
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/"
        "Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"
    ),
}
BUNDLED_CJK = ROOT / PINNED_FONT["file"]
EXPECTED_TITLE = "收入（万元）— 2026"
EXPECTED_XLABEL = "季度"
EXPECTED_YLABEL = "金额（万元）"
EXPECTED_LEGEND = "基准线"
PROBE_CHAR = "龘"
PROBE_CODEPOINT = 0x9F98
FIGURE_SPEC = {
    "figsize_in": [4.0, 3.0],
    "dpi": 100,
    "subplots_adjust": {"left": 0.18, "right": 0.96, "top": 0.88, "bottom": 0.22},
    "data_x": [0.0, 1.0, 2.0],
    "data_y": [0.0, 1.0, 4.0],
    "line_color": "#245c73",
    "title": EXPECTED_TITLE,
    "xlabel": EXPECTED_XLABEL,
    "ylabel": EXPECTED_YLABEL,
    "legend": {"label": EXPECTED_LEGEND, "loc": "upper left"},
    "annotation": {
        "text": "峰值 +12.5%",
        "xy": [2.0, 4.0],
        "xytext": [1.2, 3.1],
        "arrowstyle": "->",
        "arrow_color": "#444444",
        "bbox": {
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "edgecolor": "#999999",
        },
    },
}


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
    """Return a project-relative path when possible, else the basename.

    Evidence files are public: they must not embed the developer's home path.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.name


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def check_pinned_font() -> dict[str, object]:
    if not BUNDLED_CJK.is_file():
        print(
            "The pinned OFL font is missing.\n"
            f"Run: python spikes/fetch_b0_font.py\nExpected: {PINNED_FONT['file']}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    size = BUNDLED_CJK.stat().st_size
    digest = sha256_file(BUNDLED_CJK)
    if size != PINNED_FONT["bytes"] or digest != PINNED_FONT["sha256"]:
        print(
            "The pinned font does not match the preregistered hash; refusing to run.\n"
            f"expected {PINNED_FONT['bytes']} bytes {PINNED_FONT['sha256']}\n"
            f"actual   {size} bytes {digest}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    font_manager.fontManager.addfont(str(BUNDLED_CJK))
    resolved = Path(
        font_manager.findfont(
            FontProperties(family=PINNED_FONT["family"]), fallback_to_default=False
        )
    ).resolve()
    if resolved != BUNDLED_CJK.resolve():
        print(
            "Matplotlib resolves a different font file for "
            f"{PINNED_FONT['family']!r}: {resolved}\n"
            "Remove the conflicting font from the Matplotlib cache or set MPLCONFIGDIR.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return {
        "family": PINNED_FONT["family"],
        "file": PINNED_FONT["file"],
        "bytes": size,
        "sha256": digest,
        "license": "OFL-1.1",
        "artifact_redistributable": True,
        "url": PINNED_FONT["url"],
    }


def build_figure(font_family: str, fonttype: int):
    matplotlib.rcParams["pdf.fonttype"] = fonttype
    matplotlib.rcParams["font.family"] = [font_family]
    fig, ax = plt.subplots(
        figsize=tuple(FIGURE_SPEC["figsize_in"]), dpi=FIGURE_SPEC["dpi"]
    )
    ax.plot(
        FIGURE_SPEC["data_x"],
        FIGURE_SPEC["data_y"],
        label=EXPECTED_LEGEND,
        color=FIGURE_SPEC["line_color"],
    )
    ax.set_title(EXPECTED_TITLE)
    ax.set_xlabel(EXPECTED_XLABEL)
    ax.set_ylabel(EXPECTED_YLABEL)
    ann = FIGURE_SPEC["annotation"]
    ax.annotate(
        ann["text"],
        xy=tuple(ann["xy"]),
        xytext=tuple(ann["xytext"]),
        arrowprops={"arrowstyle": ann["arrowstyle"], "color": ann["arrow_color"]},
        bbox=dict(ann["bbox"]),
    )
    ax.legend(loc=FIGURE_SPEC["legend"]["loc"])
    fig.subplots_adjust(**FIGURE_SPEC["subplots_adjust"])
    return fig


def save_pdf(fig, path: Path) -> None:
    fig.savefig(
        path,
        format="pdf",
        metadata={"Creator": "plotproof-b0-spike", "CreationDate": None, "ModDate": None},
    )


def inspect_pdf(path: Path, *, scale: float = 2.0, render: bool = False):
    """Read a single-page PDF. Every PDFium call here is sequential."""
    doc = pdfium.PdfDocument(str(path))
    pil = None
    try:
        page_count = len(doc)
        page = doc[0]
        try:
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
                char_count = textpage.count_chars()
                boxes = [list(textpage.get_charbox(i)) for i in range(char_count)]
            finally:
                textpage.close()
            bitmap_size = None
            if render:
                bitmap = page.render(scale=scale)
                try:
                    pil = bitmap.to_pil()
                    bitmap_size = list(pil.size)
                finally:
                    bitmap.close()
            info = {
                "page_count": page_count,
                "page_size_pt": list(page.get_size()),
                "cropbox": list(page.get_cropbox()),
                "mediabox": list(page.get_mediabox()),
                "rotation": page.get_rotation(),
                "text": text,
                "char_count": char_count,
                "char_boxes": boxes,
                "bitmap_size_px": bitmap_size,
                "text_object_count": len(
                    list(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT]))
                ),
            }
        finally:
            page.close()
    finally:
        doc.close()
    return info, pil


def cmap_has_char(font_path: str, codepoint: int) -> bool:
    font = TTFont(font_path, fontNumber=0, lazy=True)
    try:
        for table in font["cmap"].tables:
            if table.isUnicode() and codepoint in table.cmap:
                return True
        return False
    finally:
        font.close()


def probe_missing_glyph(tmp: Path, families: list[str], tag: str) -> dict[str, object]:
    """Render text containing the probe character with a given font stack."""
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["font.family"] = families
    fig, ax = plt.subplots(figsize=(2, 1.2), dpi=100)
    ax.set_title(f"缺字 {PROBE_CHAR} 测试")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path = tmp / f"missing-{tag}.pdf"
        fig.savefig(
            path,
            format="pdf",
            metadata={"Creator": "plotproof-b0-spike", "CreationDate": None, "ModDate": None},
        )
    plt.close(fig)
    info, _ = inspect_pdf(path)
    return {
        "families": families,
        "warnings": [str(w.message) for w in caught],
        "text": info["text"],
        "sha256": sha256_file(path),
    }


def wheel_tag(dist_name: str) -> str | None:
    text = distribution(dist_name).read_text("WHEEL") or ""
    for line in text.splitlines():
        if line.startswith("Tag: "):
            return line[len("Tag: ") :].strip()
    return None


def main() -> int:
    font_record = check_pinned_font()
    checks = Checks()
    spec_hash = sha256_bytes(
        json.dumps(
            {"figure": FIGURE_SPEC, "font_sha256": font_record["sha256"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    script_hash = sha256_file(Path(__file__).resolve())
    record: dict[str, object] = {
        "spike_version": 2,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "backend": matplotlib.get_backend(),
        "pdf_fonttype": 42,
        "script_sha256": script_hash,
        "figure_spec_sha256": spec_hash,
        "figure_spec": FIGURE_SPEC,
        "packages": {},
        "pdfium": {},
        "font": font_record,
        "fonttype_42": {},
        "fonttype_3": {},
        "checks": checks.items,
        "artifacts": [],
    }

    for name in ("matplotlib", "pypdfium2", "fonttools", "numpy", "pillow"):
        try:
            record["packages"][name] = dist_version(name)
        except Exception as exc:  # pragma: no cover - environment dependent
            record["packages"][name] = f"MISSING: {type(exc).__name__}"
    record["pdfium"] = {
        "build": str(pdfium.PDFIUM_INFO),
        "wheel_tag": wheel_tag("pypdfium2"),
    }

    checks.add(
        "pinned_font_sha256_matches",
        font_record["sha256"] == PINNED_FONT["sha256"]
        and font_record["bytes"] == PINNED_FONT["bytes"],
        {"file": font_record["file"], "sha256": font_record["sha256"]},
    )

    tmp = Path(tempfile.mkdtemp(prefix="plotproof-b0-"))
    pil42 = None
    try:
        pdf42 = tmp / "spike-42.pdf"
        pdf42_again = tmp / "spike-42-again.pdf"
        pdf3 = tmp / "spike-3.pdf"

        for target, fonttype in ((pdf42, 42), (pdf42_again, 42), (pdf3, 3)):
            fig = build_figure(PINNED_FONT["family"], fonttype)
            save_pdf(fig, target)
            plt.close(fig)

        hash42 = sha256_file(pdf42)
        hash42_again = sha256_file(pdf42_again)
        record["fonttype_42"]["fonttype"] = 42
        record["fonttype_42"]["bytes"] = pdf42.stat().st_size
        record["fonttype_42"]["sha256"] = hash42
        record["fonttype_42"]["same_input_same_bytes"] = hash42 == hash42_again
        checks.add(
            "pdf_deterministic_bytes",
            hash42 == hash42_again,
            {"sha256": hash42, "again": hash42_again},
        )

        info42, pil42 = inspect_pdf(pdf42, render=True)
        record["fonttype_42"]["inspection"] = info42
        checks.add("single_page", info42["page_count"] == 1, info42["page_count"])
        checks.add(
            "page_size_matches_figure",
            info42["page_size_pt"] == [288.0, 216.0],
            info42["page_size_pt"],
        )
        checks.add(
            "ascii_and_cjk_text_extractable",
            EXPECTED_TITLE in info42["text"] and EXPECTED_XLABEL in info42["text"],
            {
                "title_found": EXPECTED_TITLE in info42["text"],
                "xlabel_found": EXPECTED_XLABEL in info42["text"],
                "legend_found": EXPECTED_LEGEND in info42["text"],
            },
        )
        boxes = info42["char_boxes"]
        usable = [b for b in boxes if b[2] - b[0] > 0.5 and b[3] - b[1] > 0.5]
        checks.add(
            "char_boxes_non_degenerate",
            len(usable) >= 45,
            {"usable": len(usable), "total": info42["char_count"]},
        )
        title_at = info42["text"].find(EXPECTED_TITLE)
        title_boxes = (
            boxes[title_at : title_at + len(EXPECTED_TITLE)] if title_at >= 0 else []
        )
        # 收入（万元）— 2026 : indices 0,1,3,4 are the ideographs; the full-width
        # parentheses have narrow ink and are excluded from the em-box check.
        cjk_boxes = [title_boxes[i] for i in (0, 1, 3, 4)] if len(title_boxes) == 12 else []
        checks.add(
            "title_cjk_boxes_non_degenerate",
            len(cjk_boxes) == 4
            and all(b[2] - b[0] >= 8.0 and b[3] - b[1] >= 8.0 for b in cjk_boxes),
            {"title_index": title_at, "cjk_boxes": cjk_boxes},
        )
        checks.add(
            "bitmap_rendered",
            info42["bitmap_size_px"] == [576, 432],
            info42["bitmap_size_px"],
        )

        info3, _ = inspect_pdf(pdf3)
        record["fonttype_3"]["fonttype"] = 3
        record["fonttype_3"]["bytes"] = pdf3.stat().st_size
        record["fonttype_3"]["sha256"] = sha256_file(pdf3)
        record["fonttype_3"]["inspection"] = info3
        checks.add(
            "fonttype3_still_readable_for_ascii",
            "2026" in info3["text"] and info3["page_count"] == 1,
            {"has_2026": "2026" in info3["text"], "chars": info3["char_count"]},
        )
        checks.add(
            "fonttype3_loses_cjk_extraction",
            EXPECTED_TITLE not in info3["text"] and EXPECTED_XLABEL not in info3["text"],
            {
                "title_found": EXPECTED_TITLE in info3["text"],
                "xlabel_found": EXPECTED_XLABEL in info3["text"],
                "chars": info3["char_count"],
            },
        )

        dejavu_path = font_manager.findfont("DejaVu Sans")
        dejavu = {
            "file": project_path(Path(dejavu_path)),
            "bytes": Path(dejavu_path).stat().st_size,
            "sha256": sha256_file(Path(dejavu_path)),
        }
        record["dejavu"] = dejavu
        cmap_absent = not cmap_has_char(dejavu_path, PROBE_CODEPOINT)
        probe_single = probe_missing_glyph(tmp, ["DejaVu Sans"], "single")
        probe_fallback = probe_missing_glyph(
            tmp, ["DejaVu Sans", PINNED_FONT["family"]], "fallback"
        )
        record["missing_glyph_probe"] = {
            "codepoint": f"U+{PROBE_CODEPOINT:04X}",
            "dejavu_cmap_has_char": not cmap_absent,
            "single_font": probe_single,
            "fallback_font_stack": probe_fallback,
            "limitation": (
                "PDF text extraction can still contain the probe character even when "
                "the glyph is missing from the font; extraction presence is not "
                "rendering evidence."
            ),
        }
        checks.add(
            "missing_glyph_cmap_absent",
            cmap_absent,
            {"font": dejavu["file"], "codepoint": f"U+{PROBE_CODEPOINT:04X}"},
        )
        single_warnings = " ".join(probe_single["warnings"]).lower()
        checks.add(
            "missing_glyph_warning_emitted",
            "missing from font" in single_warnings and "9f98" in single_warnings,
            {"warnings": probe_single["warnings"]},
        )
        checks.add(
            "missing_glyph_text_still_extractable",
            PROBE_CHAR in probe_single["text"],
            {
                "text": probe_single["text"],
                "note": "confirms extraction is not rendering evidence",
            },
        )
        checks.add(
            "fallback_suppresses_warning",
            not probe_fallback["warnings"] and PROBE_CHAR in probe_fallback["text"],
            {"warnings": probe_fallback["warnings"]},
        )

        if not checks.failed:
            OUT.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pdf42, OUT / "api-spike-fonttype42.pdf")
            shutil.copyfile(pdf3, OUT / "api-spike-fonttype3.pdf")
            if pil42 is not None:
                pil42.save(OUT / "api-spike-render.png")
            record["artifacts"] = [
                "artifacts/b0/api-spike-fonttype42.pdf",
                "artifacts/b0/api-spike-fonttype3.pdf",
                "artifacts/b0/api-spike-render.png",
                "artifacts/b0/api-spike.json",
            ]
    finally:
        if pil42 is not None:
            pil42.close()
        shutil.rmtree(tmp, ignore_errors=True)

    record["overall"] = "FAIL" if checks.failed else "PASS"
    target = OUT / ("api-spike-FAILED.json" if checks.failed else "api-spike.json")
    atomic_write(target, json.dumps(record, ensure_ascii=False, indent=2) + "\n")

    for item in checks.items:
        print(f"{item['status']:4s} {item['id']}: {item['detail']}")
    print(f"OVERALL {record['overall']} -> {target}")
    return 1 if checks.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
