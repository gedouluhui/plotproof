"""CA1 immutable event records; deliberately not a full source manifest."""
from __future__ import annotations

from dataclasses import dataclass

from .evidence import SaveWarning
from .geometry import Rect


@dataclass(frozen=True)
class AppliedAlpha:
    gc_alpha: float
    gc_forced: bool
    color_alpha: float
    effective: float


@dataclass(frozen=True)
class SourceArtist:
    source_object_id: int
    artist_class: str
    text: str | None
    visible: bool
    raw_artist_alpha: float | None
    raw_color_alpha: float | None
    background_patch_id: int | None
    owner_unit_id: int | None


@dataclass(frozen=True)
class DrawEvent:
    sequence: int
    kind: str
    source_object_id: int | None
    artist_class: str | None
    bbox_pdf: Rect | None
    alpha: AppliedAlpha
    raw_artist_alpha: float | None
    raw_color_alpha: float | None
    text: str | None = None
    font_size_pt: float | None = None
    angle: float | None = None
    path_vertices_pdf: tuple[tuple[float, float], ...] = ()
    path_codes: tuple[int, ...] | None = None


@dataclass(frozen=True)
class CapturedPdf:
    pdf_bytes: bytes
    input_sha256: str
    original_dpi: float
    bbox_inches: str | None
    pad_inches: float
    transparent: bool
    pre_tight_bbox_inches: tuple[float, float, float, float] | None
    save_tight_bbox_inches: tuple[float, float, float, float] | None
    origin_display: tuple[float, float] | None
    sources: tuple[SourceArtist, ...]
    events: tuple[DrawEvent, ...]
    warnings: tuple[SaveWarning, ...]
    capture_issues: tuple[str, ...]
    capture_revision: str = 'CA1'
    complete_source_manifest: bool = False
    # Live Text/Patch objects in the same order as ``sources``. Assembly code
    # needs the object that produced each source ID; this adds no captured
    # fact and is not serialized.
    source_artists: tuple = ()

    def to_source_display(self, box: Rect) -> Rect:
        if self.origin_display is None:
            raise ValueError('Capture has no established saved-page origin')
        x, y = self.origin_display
        scale = self.original_dpi / 72
        return Rect(box.x0*scale+x, box.y0*scale+y,
                    box.x1*scale+x, box.y1*scale+y)
