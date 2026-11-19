"""Real-PDF tests using a TEST-ONLY, single-page Figure.text collector.

This is not a public API, verified input loader, manifest writer, or completed
wrapper. Only the explicit unrotated Figure.text artists and axis-aligned
rectangles below are collected. No axes, tight export, or benchmark data is used.
PDFium facts are copied into Python records, serially, before handles are closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import median
import warnings

from fontTools.ttLib import TTFont
import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.patches import Rectangle
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import pytest

from plotproof.alignment import AlignmentResult, align_units
from plotproof.core import CoreResult, check_core
from plotproof.evidence import FontGlyph, GlyphEvidence, PdfChar, SaveWarning, TextRecord
from plotproof.geometry import Rect, Transform, intersections, union_area
from plotproof.occlusion import FilledRecord
from plotproof.units import enumerate_units


TRANSFORM = Transform(100, 0, 0)


@dataclass(frozen=True)
class _Capture:
    path: Path
    page: Rect
    chars: tuple[PdfChar, ...]
    pdf_text: str
    records: tuple[TextRecord, ...]
    fills: tuple[FilledRecord, ...]
    glyphs: dict[int, tuple[GlyphEvidence, ...]]
    save_warnings: tuple[SaveWarning, ...]
    draw_calls: tuple[tuple[int, str], ...]
    alignment: AlignmentResult
    result: CoreResult


def _read_single_page(path):
    """No zip(text, boxes): PDFium text and character indices can differ."""
    document = pdfium.PdfDocument(str(path))
    try:
        assert len(document) == 1
        page = document[0]
        try:
            width, height = page.get_size()
            bounds = Rect(0, 0, width, height)
            assert page.get_rotation() == 0
            assert Rect(*page.get_mediabox()) == bounds
            assert Rect(*page.get_cropbox()) == bounds
            textpage = page.get_textpage()
            try:
                chars = tuple(
                    PdfChar(chr(pdfium_raw.FPDFText_GetUnicode(textpage, i)),
                            Rect(*textpage.get_charbox(i)))
                    for i in range(textpage.count_chars())
                )
                text = textpage.get_text_range()
            finally:
                textpage.close()
        finally:
            page.close()
    finally:
        document.close()
    return bounds, chars, text


@pytest.fixture
def collect_pdf(tmp_path, monkeypatch):
    """Generate independent PDFs; reject inputs beyond this small test collector."""
    properties = FontProperties(family=['DejaVu Sans'], size=20)
    resolved = Path(findfont(properties, fallback_to_default=False,
                             rebuild_if_missing=False))
    # Bind the rendering font to the very file whose cmap was inspected. Evidence
    # carries a content ID, never the machine's absolute font path.
    properties.set_file(str(resolved))
    file_id = 'sha256:' + sha256(resolved.read_bytes()).hexdigest()
    font = TTFont(resolved, lazy=True)
    try:
        family = font['name'].getDebugName(1)
        cmap = font.getBestCmap()
        assert family == 'DejaVu Sans' and cmap is not None
        glyph_ids = {cp: font.getGlyphID(name) for cp, name in cmap.items()}
        assert 0x20000 not in cmap  # Observed from the local font, not input evidence.
    finally:
        font.close()

    def collect(specs, *, cover=None):
        assert cover in (None, 'before', 'after')
        fig = Figure(figsize=(4, 2), dpi=100)
        canvas = FigureCanvasAgg(fig)
        texts = [fig.text(x, y, text, fontproperties=properties, zorder=3)
                 for x, y, text in specs]
        assert texts and not fig.axes
        # These are Agg/display extents at 100 dpi, not PDF text boxes. Layout
        # warnings are deliberately not supplied as save-time glyph evidence.
        with warnings.catch_warnings(record=True):
            warnings.simplefilter('always')
            canvas.draw()
            renderer = canvas.get_renderer()
            text_boxes = [Rect(*map(float, t.get_window_extent(renderer).extents))
                          for t in texts]
        patches = [(0, fig.patch)]
        if cover is not None:
            assert len(texts) == 1
            box = text_boxes[0]
            patch = Rectangle(
                ((box.x0 - 3) / fig.bbox.width, (box.y0 - 3) / fig.bbox.height),
                (box.x1 - box.x0 + 6) / fig.bbox.width,
                (box.y1 - box.y0 + 6) / fig.bbox.height,
                transform=fig.transFigure, facecolor='white', edgecolor='none',
                zorder=4 if cover == 'after' else 2,
            )
            fig.add_artist(patch)
            patches.append((len(texts) + 1, patch))
        patch_boxes = {
            uid: TRANSFORM.to_pdf(Rect(*map(float, p.get_window_extent(renderer).extents)))
            for uid, p in patches
        }

        calls = []
        tracked = [*patches, *enumerate(texts, start=1)]

        def trace(uid, original):
            def draw(renderer):
                calls.append((uid, type(renderer).__name__))
                return original(renderer)
            return draw

        path = tmp_path / 'single-page.pdf'
        with monkeypatch.context() as tracing:
            for uid, artist in tracked:
                tracing.setattr(artist, 'draw', trace(uid, artist.draw))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                fig.savefig(path, format='pdf', dpi=100, metadata={
                    'Creator': 'plotproof-test-only-collector',
                    'CreationDate': None, 'ModDate': None,
                })
        saved = tuple(SaveWarning(w.category.__name__, str(w.message)) for w in caught)
        assert len(calls) == len(tracked)
        assert {uid for uid, _ in calls} == {uid for uid, _ in tracked}
        assert all(name == 'MixedModeRenderer' for _, name in calls)
        # Rank actual save-time calls. zorder values are never the evidence.
        paint_order = {uid: rank for rank, (uid, _) in enumerate(calls)}
        assert calls[0][0] == 0  # The figure's real background draw is included.
        page, chars, pdf_text = _read_single_page(path)
        assert page == Rect(0, 0, 288, 144)
        assert fig.dpi == 100

        records = []
        for uid, (artist, box) in enumerate(zip(texts, text_boxes), start=1):
            color_alpha = to_rgba(artist.get_color())[3]
            artist_alpha = artist.get_alpha()
            artist_alpha = 1.0 if artist_alpha is None else artist_alpha
            clip_box = artist.get_clip_box() if artist.get_clip_on() else None
            clip_box = (Rect(*map(float, clip_box.extents))
                        if clip_box is not None else None)
            # All these deliberately small fixtures are units, including the
            # partially off-page case. Reject rather than guess other predicates.
            assert artist.get_text().strip() and '$' not in artist.get_text()
            assert artist.get_visible() and color_alpha > 0 and artist_alpha > 0
            assert artist.get_rotation() == 0 and artist.get_bbox_patch() is None
            assert artist.get_clip_path() is None and clip_box is None
            assert box.area > 0 and TRANSFORM.to_pdf(box).intersection(page) is not None
            records.append(TextRecord(
                source_object_id=uid, text=artist.get_text(), bbox_display=box,
                font_size_pt=float(artist.get_fontsize()), text_alpha=color_alpha,
                artist_alpha=artist_alpha, visible=artist.get_visible(),
                rotation=float(artist.get_rotation()), clip_box_display=clip_box,
                tick_location=None, view_limits=None, is_unit=True,
                exclusion_reason=None, paint_order=paint_order[uid],
                background_patch_id=None,
            ))
        fills = []
        for uid, patch in patches:
            assert isinstance(patch, Rectangle) and patch.angle == 0
            assert patch.get_visible() and patch.get_fill()
            box = patch_boxes[uid]
            fills.append(FilledRecord(
                source_object_id=uid, box_pdf=box,
                artist_class=type(patch).__name__, path_kind='axis_aligned_rectangle',
                path_is_concave=False, fancybox=None,
                facecolor_alpha=patch.get_facecolor()[3],
                artist_alpha=1.0 if patch.get_alpha() is None else patch.get_alpha(),
                paint_order=paint_order[uid], filled_area=box.area,
                owner_unit_id=None, image_opacity=None,
            ))
        records, fills = tuple(records), tuple(fills)
        glyphs = {
            record.source_object_id: tuple(
                GlyphEvidence(cp, (FontGlyph(family, file_id, glyph_ids.get(cp)),), saved)
                for cp in sorted({ord(c) for c in record.text if not c.isspace()})
            )
            for record in records
        }
        result = check_core(records=records, chars=chars, fills=fills, glyphs=glyphs,
                            transform=TRANSFORM, page=page, source_units_total=len(records))
        alignment = align_units(enumerate_units(records, TRANSFORM, page, len(records)),
                                chars, glyphs)
        return _Capture(path, page, chars, pdf_text, records, fills, glyphs, saved,
                        tuple(calls), alignment, result)

    with mpl.rc_context({
        'pdf.fonttype': 42, 'pdf.use14corefonts': False,
        'font.family': ['DejaVu Sans'], 'text.usetex': False,
        'savefig.bbox': None, 'savefig.transparent': False,
    }):
        yield collect


def _assert_aligned(capture, total):
    result = capture.result
    assert capture.path.is_file()
    assert result.errors == () and result.unknown_objects == (), result
    assert result.coverage['source_units_total'] == total
    assert result.coverage['aligned_units'] == total
    assert result.coverage['unaligned_units'] == result.coverage['unsupported_units'] == 0
    assert result.coverage['ratio'] == 1.0
    assert len(capture.alignment.assignments) == total
    for record in capture.records:
        span = capture.alignment.assignments[record.source_object_id]
        assert span.iou >= 0.50, span
        heights = [b.y1 - b.y0 for b in span.boxes if b.y1 > b.y0]
        assert 0.20 <= median(heights) / record.font_size_pt <= 1.50


def _assert_pass(capture):
    assert capture.result.overall_state == 'PASS', capture.result
    assert capture.result.findings == ()
    assert capture.save_warnings == ()


def test_plain_pdf_is_clean_and_font_supplies_glyphs(collect_pdf):
    # Also the D4 negative control: identical position/font to ANCHOR + U+20000.
    capture = collect_pdf([(0.15, 0.55, 'ANCHOR')])
    _assert_aligned(capture, 1)
    _assert_pass(capture)
    assert capture.pdf_text == ''.join(c.text for c in capture.chars) == 'ANCHOR'
    assert all(capture.page.contains(c.box) for c in capture.chars)
    assert len(capture.glyphs[1]) == len(set('ANCHOR'))
    assert all(g.fonts[0].glyph_id > 0 and not g.proven_missing
               for g in capture.glyphs[1])


def test_multiline_pdfium_crlf_aligns_as_one_source_unit(collect_pdf):
    # LF is Matplotlib's line break; PDFium emits CRLF. Literal source CRLF would
    # also render a missing Glyph 13, so it is not this clean multiline control.
    capture = collect_pdf([(0.15, 0.65, 'First line\nSecond line')])
    _assert_aligned(capture, 1)
    _assert_pass(capture)
    assert capture.pdf_text == ''.join(c.text for c in capture.chars) == 'First line\r\nSecond line'
    breaks = [c for c in capture.chars if c.text in '\r\n']
    assert len(breaks) == 2 and all(c.box.area == 0 for c in breaks)
    span = capture.alignment.assignments[1]
    assert (span.start, span.end) == (0, len(capture.chars))
    assert span.canonical_text == 'First line Second line'
    index = capture.pdf_text.index('\r')
    mapping = capture.alignment.pdf_canonical.original_to_canonical
    assert mapping[index] == mapping[index + 1]
    assert span.source_map[capture.records[0].text.index('\n')] == mapping[index]


def test_partial_page_clip_uses_real_outside_character_boxes(collect_pdf):
    # Same text/font/y as the plain control; only the x position changes.
    capture = collect_pdf([(0.87, 0.55, 'ANCHOR')])
    _assert_aligned(capture, 1)
    assert capture.save_warnings == ()
    source = TRANSFORM.to_pdf(capture.records[0].bbox_display)
    assert source.intersection(capture.page) is not None
    assert not capture.page.contains(source)
    assert capture.pdf_text == 'ANCHOR'  # Extraction is not proof of visibility.
    assert any(c.box.x0 < capture.page.x1 < c.box.x1 for c in capture.chars)
    assert any(c.box.x0 > capture.page.x1 and c.box.area > 0 for c in capture.chars)
    assert capture.result.overall_state == 'FAIL'
    assert [(f.rule_id, f.confidence) for f in capture.result.findings] == [('D1', 'high')]
    finding = capture.result.findings[0]
    assert finding.evidence['page_rectangle'] == capture.page.as_tuple()
    assert any((b['area'] - b['inside_area']) / b['area'] >= 0.50
               for b in finding.evidence['boundary_boxes'])


@pytest.mark.parametrize('cover', ['after', 'before'])
def test_opaque_rectangle_depends_on_captured_draw_order(collect_pdf, cover):
    capture = collect_pdf([(0.15, 0.55, 'COVERED')], cover=cover)
    _assert_aligned(capture, 1)
    assert capture.save_warnings == () and capture.pdf_text == 'COVERED'
    text = capture.records[0]
    rectangle = next(f for f in capture.fills if f.source_object_id == 2)
    assert rectangle.effective_alpha == 1.0 and capture.page.contains(rectangle.box_pdf)
    boxes = capture.alignment.assignments[1].boxes
    coverage = union_area(intersections(boxes, (rectangle.box_pdf,))) / union_area(boxes)
    assert coverage == pytest.approx(1.0)
    order = tuple(uid for uid, _ in capture.draw_calls)
    assert text.paint_order == order.index(1) and rectangle.paint_order == order.index(2)
    if cover == 'after':
        assert order == (0, 1, 2) and rectangle.paint_order > text.paint_order
        assert capture.result.overall_state == 'FAIL'
        assert [(f.rule_id, f.confidence) for f in capture.result.findings] == [('D2', 'high')]
        evidence = capture.result.findings[0].evidence
        assert evidence['joint_coverage'] == pytest.approx(coverage)
        assert len(evidence['occluders']) == 1
        occluder = evidence['occluders'][0]
        assert occluder['source_object_id'] == rectangle.source_object_id
        assert occluder['known_after'] and occluder['high_eligible']
        assert occluder['coverage'] >= 0.90 and occluder['effective_alpha'] >= 0.95
    else:
        assert order == (0, 2, 1) and rectangle.paint_order < text.paint_order
        _assert_pass(capture)


@pytest.mark.parametrize('overlap', [True, False], ids=['overlapping', 'separated'])
def test_distinct_text_uses_real_character_union_overlap(collect_pdf, overlap):
    positions = (0.55, 0.55) if overlap else (0.75, 0.25)
    capture = collect_pdf([(0.15, positions[0], 'MMMM'), (0.15, positions[1], 'NNNN')])
    _assert_aligned(capture, 2)
    assert capture.save_warnings == ()
    left, right = (capture.alignment.assignments[i] for i in (1, 2))
    assert left.canonical_text == 'MMMM' and right.canonical_text == 'NNNN'
    assert (left.start, left.end) != (right.start, right.end)
    cuts = intersections(left.boxes, right.boxes)
    ratio = union_area(cuts) / min(union_area(left.boxes), union_area(right.boxes))
    if overlap:
        assert ratio >= 0.50, ratio
        assert any(b.x1 - b.x0 >= 0.5 and b.y1 - b.y0 >= 0.5 for b in cuts)
        assert capture.result.overall_state == 'FAIL'
        assert [(f.rule_id, f.confidence) for f in capture.result.findings] == [('D3', 'high')]
        finding = capture.result.findings[0]
        assert (finding.source_object_id, finding.related_source_object_id) == (1, 2)
        assert finding.evidence['operand_set'] == 'char_unions'
        assert finding.evidence['ratio'] == pytest.approx(ratio)
        assert finding.evidence['character_pair'] is not None
    else:
        assert ratio == 0
        _assert_pass(capture)


def test_missing_non_bmp_glyph_has_cmap_and_save_warning_evidence(collect_pdf):
    capture = collect_pdf([(0.15, 0.55, 'ANCHOR\U00020000')])
    _assert_aligned(capture, 1)
    glyph = next(g for g in capture.glyphs[1] if g.codepoint == 0x20000)
    assert glyph.fonts[0].glyph_id is None and glyph.fonts[0].missing
    assert glyph.fonts[0].file_id.startswith('sha256:')
    assert glyph.proven_missing and glyph.naming_warnings
    assert glyph.codepoint_warnings == capture.save_warnings
    assert all(w.category == 'UserWarning' for w in capture.save_warnings)
    assert capture.pdf_text == ''.join(c.text for c in capture.chars) == 'ANCHOR'
    span = capture.alignment.assignments[1]
    assert span.canonical_text == 'ANCHOR'
    assert span.removed_codepoints == (0x20000,) and span.source_map[-1] is None
    assert capture.result.overall_state == 'FAIL'
    assert [(f.rule_id, f.confidence) for f in capture.result.findings] == [('D4', 'high')]
    evidence = capture.result.findings[0].evidence
    assert evidence['codepoint'] == 0x20000
    assert evidence['unique_alignment'] and evidence['naming_warning']
    assert evidence['fonts'][0]['glyph_id'] is None and evidence['fonts'][0]['missing']
