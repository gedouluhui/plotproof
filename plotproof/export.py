"""Assemble a check for one saved Matplotlib figure.

This is the B1 assembly layer: CA1 capture supplies the real PDF bytes, the
draw-time paint order and the renderer-applied alpha; the bounded reader
supplies character boxes; the frozen core supplies alignment and the D1-D3
rules.

What it does not do, and says so in the report:

* no font cmap evidence is collected, so D4 ``missing_glyph`` is reported as
  not assessed - never as passed;
* any capture issue that leaves material unmapped (images, collections,
  rasterized text, wrapped text, ...) makes the result ERROR rather than
  turning partial coverage into a pass;
* a PASS is about the supported defect classes only, not a claim that the
  figure is correct.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
import tempfile

from .capture import CaptureError, _artists, capture_pdf
from .core import CoreResult, check_core
from .evidence import TextRecord
from .geometry import Rect, Transform
from .occlusion import FilledRecord
from .pdf_input import PdfReadError, read_pdf
from .units import AccountingError, exclusion_reason


CHECKS_EVALUATED = ('D1_clipped_text', 'D2_occluded_text', 'D3_overlapping_text')
CHECKS_NOT_EVALUATED = ('D4_missing_glyph',)
# Material this layer cannot map. D2 needs the complete painted inventory, so
# these limit the assessed classes; they do not by themselves invalidate D1 or
# D3, which use character boxes rather than occluder geometry.
PAINT_LIMITS = frozenset({
    'image_capture_pending', 'collection_capture_pending', 'gouraud_capture_pending',
    'tex_capture_pending', 'rasterized_capture_pending', 'path_effect_capture_pending',
    'unassociated_material_event', 'mathtext_capture_pending',
    'multi_path_fill_unsupported', 'fill_without_geometry'})
RULE_CLASSES = {'D1': 'D1_clipped_text', 'D2': 'D2_occluded_text', 'D3': 'D3_overlapping_text'}
_MAX_ROUND_TRIP = 200_000


class CheckError(ValueError):
    """The figure or its saved PDF is outside what this assembly can state."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__('check failed: ' + reason)


@dataclass(frozen=True)
class CheckReport:
    state: str
    findings: tuple[dict, ...]
    coverage: dict | None
    unknown_objects: tuple[dict, ...]
    errors: tuple[dict, ...]
    assessed: tuple[str, ...]
    not_assessed: tuple[str, ...]
    capture_issues: tuple[str, ...]
    page_size_pt: tuple[float, float]
    input_sha256: str
    pdfium_version: str
    source_units_total: int
    text_records: int
    filled_records: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Collection:
    records: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _source_artists(fig):
    """Text/Patch artists in the same deterministic order capture registers."""
    from matplotlib.patches import Patch
    from matplotlib.text import Text
    for artist in _artists(fig):
        if isinstance(artist, (Text, Patch)):
            yield artist


def _clip_box(artist) -> Rect | None:
    if not artist.get_clip_on():
        return None
    box = artist.get_clip_box()
    if box is None:
        return None
    x0, y0, x1, y1 = (float(value) for value in box.extents)
    return Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _tick_terms(fig, artist) -> tuple[float, tuple[float, float]] | None:
    # Text.axes is not populated for tick labels after a save, so resolve the
    # owning tick by identity over every Axes in the figure.
    for axes in fig.axes:
        for axis in (axes.xaxis, axes.yaxis):
            for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                if artist is tick.label1 or artist is tick.label2:
                    low, high = (float(value) for value in axis.get_view_interval())
                    return float(tick.get_loc()), (min(low, high), max(low, high))
    return None


def _is_aligned_rectangle(vertices, box: Rect) -> bool:
    if len(vertices) not in (4, 5):
        return False
    points = {tuple(round(float(value), 6) for value in point) for point in vertices}
    if len(points) != 4:
        return False
    xs = sorted({point[0] for point in points})
    ys = sorted({point[1] for point in points})
    if len(xs) != 2 or len(ys) != 2:
        return False
    return all(abs(actual - expected) < 1e-3 for actual, expected in
               ((xs[0], box.x0), (xs[1], box.x1), (ys[0], box.y0), (ys[1], box.y1)))


def _collect(fig, captured, transform: Transform, page: Rect) -> _Collection:
    result = _Collection()
    sources = list(captured.sources)
    if captured.source_artists:
        # Authoritative: the very objects that were registered, in ID order.
        artists = list(captured.source_artists)
    else:
        artists = list(_source_artists(fig))
    if len(artists) != len(sources):
        result.errors.append({'stage': 'inventory', 'message': 'source_count_mismatch'})
        return result

    text_events = {}
    fill_events = {}
    for event in captured.events:
        if event.source_object_id is None:
            continue
        if event.kind == 'text':
            text_events.setdefault(event.source_object_id, event)
        elif event.kind == 'filled_path':
            fill_events.setdefault(event.source_object_id, []).append(event)

    renderer = fig.canvas.get_renderer()
    for artist, source in zip(artists, sources):
        if type(artist).__name__ != source.artist_class:
            result.errors.append({'stage': 'inventory', 'message': 'source_inventory_mismatch'})
            return result
        if source.text is None:
            events = fill_events.get(source.source_object_id, ())
            if not events:
                continue
            if len(events) > 1:
                # A patch that emits several painted pieces cannot be reduced
                # to one conservative rectangle here.
                result.errors.append({'stage': 'capture', 'message': 'multi_path_fill_unsupported'})
                continue
            event = events[0]
            if event.bbox_pdf is None:
                result.errors.append({'stage': 'capture', 'message': 'fill_without_geometry'})
                continue
            box = event.bbox_pdf
            rectangular = _is_aligned_rectangle(event.path_vertices_pdf, box)
            result.fills.append(FilledRecord(
                source_object_id=source.source_object_id, box_pdf=box,
                artist_class=source.artist_class,
                path_kind='axis_aligned_rectangle' if rectangular else 'other_filled_path',
                path_is_concave=False if rectangular else None,
                fancybox=None,
                facecolor_alpha=event.alpha.effective, artist_alpha=1.0,
                paint_order=event.sequence,
                filled_area=box.area if rectangular else None,
                owner_unit_id=source.owner_unit_id, image_opacity=None))
            continue

        event = text_events.get(source.source_object_id)
        extent = None
        if event is not None and event.bbox_pdf is not None:
            # Text events are recorded in PDF points; the record holds the
            # display-space box the predicate is defined on.
            extent = captured.to_source_display(event.bbox_pdf)
        else:
            try:
                extent = Rect(*(float(value) for value in
                                artist.get_window_extent(renderer=renderer).extents))
            except (TypeError, ValueError, RuntimeError):
                extent = None
        if extent is None:
            result.errors.append({'stage': 'capture', 'message': 'text_without_extent'})
            continue
        terms = _tick_terms(fig, artist)
        effective_alpha = (event.alpha.effective if event is not None
                           else float(source.raw_color_alpha or 1.0))
        record = TextRecord(
            source_object_id=source.source_object_id, text=artist.get_text(),
            bbox_display=extent,
            font_size_pt=float(event.font_size_pt if event is not None and event.font_size_pt
                               else artist.get_fontsize()),
            text_alpha=effective_alpha, artist_alpha=1.0,
            visible=bool(source.visible),
            rotation=float(event.angle if event is not None and event.angle is not None
                           else artist.get_rotation()),
            clip_box_display=_clip_box(artist),
            tick_location=None if terms is None else terms[0],
            view_limits=None if terms is None else terms[1],
            is_unit=True, exclusion_reason=None,
            paint_order=None if event is None else event.sequence,
            background_patch_id=source.background_patch_id)
        reason = exclusion_reason(record, transform, page)
        result.records.append(replace(record, is_unit=reason is None,
                                      exclusion_reason=reason))
    return result


def _state(core: CoreResult, findings: tuple[dict, ...]) -> str:
    """Recompute the state over the classes this run actually assessed."""
    if core.errors:
        return 'ERROR'
    if any(item['confidence'] == 'high' for item in findings):
        return 'FAIL'
    coverage = core.coverage or {}
    if (findings or core.unknown_objects
            or coverage.get('ratio') is None or coverage.get('ratio', 0) < 0.90
            or coverage.get('unsupported_units', 0) > 0):
        return 'UNKNOWN'
    return 'PASS'


def check_figure(fig, *, bbox_inches=None, pad_inches=None, transparent=False,
                 keep_pdf: str | Path | None = None) -> CheckReport:
    """Capture, read and check one live Matplotlib Figure."""
    try:
        return _check_figure(fig, bbox_inches=bbox_inches, pad_inches=pad_inches,
                             transparent=transparent, keep_pdf=keep_pdf)
    except CheckError:
        raise
    except (CaptureError, PdfReadError, AccountingError) as error:
        reason = getattr(error, 'reason', None) or str(error)
        raise CheckError(str(reason)) from None


def _check_figure(fig, *, bbox_inches=None, pad_inches=None, transparent=False,
                  keep_pdf: str | Path | None = None) -> CheckReport:
    captured = capture_pdf(fig, bbox_inches=bbox_inches, pad_inches=pad_inches,
                           transparent=transparent)
    if captured.origin_display is None:
        raise CheckError('no_saved_page_origin')
    temporary = None
    if keep_pdf is None:
        handle = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        handle.write(captured.pdf_bytes)
        handle.close()
        path = Path(handle.name)
        temporary = path
    else:
        path = Path(keep_pdf)
        path.write_bytes(captured.pdf_bytes)
    try:
        snapshot = read_pdf(str(path), captured.input_sha256)
        page = Rect(0.0, 0.0, float(snapshot.page_size_pt[0]),
                    float(snapshot.page_size_pt[1]))
        transform = Transform(captured.original_dpi, *captured.origin_display)
        collection = _collect(fig, captured, transform, page)
        paint_issue = any(issue in PAINT_LIMITS for issue in captured.capture_issues)
        errors = [{'stage': 'capture', 'message': issue}
                  for issue in captured.capture_issues if issue not in PAINT_LIMITS]
        errors.extend(collection.errors)
        total = sum(1 for record in collection.records if record.is_unit)
        core: CoreResult = check_core(
            records=tuple(collection.records), chars=snapshot.characters,
            fills=tuple(collection.fills), glyphs={}, transform=transform, page=page,
            source_units_total=total, errors=tuple(errors))
        assessed = tuple(name for name in CHECKS_EVALUATED
                         if not (paint_issue and name == 'D2_occluded_text'))
        findings = tuple(item for item in core.to_dict()['findings']
                         if RULE_CLASSES[item['rule_id']] in assessed)
        return CheckReport(
            state=_state(core, findings),
            findings=findings,
            coverage=core.coverage, unknown_objects=core.unknown_objects,
            errors=core.errors, assessed=assessed,
            not_assessed=tuple(name for name in CHECKS_EVALUATED if name not in assessed)
            + CHECKS_NOT_EVALUATED,
            capture_issues=captured.capture_issues,
            page_size_pt=(page.x1, page.y1), input_sha256=captured.input_sha256,
            pdfium_version=snapshot.pdfium_version,
            source_units_total=total, text_records=len(collection.records),
            filled_records=len(collection.fills))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def render_html(report: CheckReport) -> str:
    """Offline, script-free report for a browser or a CI artifact."""
    from html import escape
    rows = []
    for finding in report.findings:
        rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            escape(finding['rule_id']), escape(finding['defect_class']),
            escape(str(finding['source_object_id'])), escape(finding['confidence']),
            escape(', '.join('%.1f' % value for value in finding['box_pdf_points']))))
    if not rows:
        rows.append('<tr><td colspan="5">No finding in the assessed classes.</td></tr>')
    unknown = ''.join('<li>%s: %s</li>' % (escape(str(item.get('source_object_id'))),
                                           escape(str(item.get('reason'))))
                      for item in report.unknown_objects)
    errors = ''.join('<li>%s: %s</li>' % (escape(str(item.get('stage'))),
                                          escape(str(item.get('message'))))
                     for item in report.errors)
    coverage = report.coverage or {}
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>PlotProof report</title>
<style>
body{font:15px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem;color:#1b1b1b}
h1{font-size:1.4rem;margin:0 0 .25rem}
.state{display:inline-block;padding:.15rem .5rem;border-radius:.25rem;background:#eee;font-weight:600}
table{border-collapse:collapse;width:100%%;margin:1rem 0}
th,td{border-bottom:1px solid #ddd;padding:.35rem .5rem;text-align:left;font-size:.92rem}
code{background:#f4f4f4;padding:.05rem .25rem;border-radius:.2rem}
.muted{color:#555}
</style></head><body>
<h1>PlotProof report</h1>
<p><span class="state">%(state)s</span> <span class="muted">assessed: %(assessed)s — not assessed: %(missing)s</span></p>
<p class="muted">page %(page_w).1f × %(page_h).1f pt · units %(units)d · aligned coverage %(ratio)s ·
input <code>%(digest)s</code> · PDFium %(pdfium)s</p>
<h2>Findings</h2>
<table><thead><tr><th>Rule</th><th>Class</th><th>Source</th><th>Confidence</th><th>Box (pt)</th></tr></thead>
<tbody>%(rows)s</tbody></table>
<h2>Unaligned / unsupported</h2><ul>%(unknown)s</ul>
<h2>Capture and accounting limits</h2><ul>%(errors)s</ul>
<p class="muted">PASS means no supported defect was found with sufficient coverage in the assessed classes.
It does not mean the figure is correct, and it is not a benchmark result.</p>
</body></html>
""" % {'state': escape(report.state), 'assessed': escape(', '.join(report.assessed)),
       'missing': escape(', '.join(report.not_assessed)),
       'page_w': report.page_size_pt[0], 'page_h': report.page_size_pt[1],
       'units': report.source_units_total,
       'ratio': 'n/a' if coverage.get('ratio') is None else '%.3f' % coverage['ratio'],
       'digest': escape(report.input_sha256), 'pdfium': escape(report.pdfium_version),
       'rows': ''.join(rows), 'unknown': unknown or '<li>none</li>',
       'errors': errors or '<li>none</li>'}
