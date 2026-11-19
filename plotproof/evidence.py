"""Internal immutable evidence records; collectors, not these types, attest provenance."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import re

from .geometry import Rect, finite_number


def integer_id(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')


def alpha(value: float) -> float:
    result = finite_number(value, 'alpha')
    if not 0 <= result <= 1:
        raise ValueError('alpha must be in [0, 1]')
    return result


@dataclass(frozen=True)
class TextRecord:
    source_object_id: int
    text: str
    bbox_display: Rect
    font_size_pt: float
    text_alpha: float
    artist_alpha: float
    visible: bool
    rotation: float
    clip_box_display: Rect | None
    tick_location: float | None
    view_limits: tuple[float, float] | None
    is_unit: bool
    exclusion_reason: str | None
    paint_order: int | None
    background_patch_id: int | None

    def __post_init__(self) -> None:
        integer_id(self.source_object_id, 'source_object_id')
        if not isinstance(self.text, str):
            raise TypeError('text must be a string')
        if type(self.visible) is not bool or type(self.is_unit) is not bool:
            raise TypeError('visible and is_unit must be booleans')
        if not isinstance(self.bbox_display, Rect):
            raise TypeError('bbox_display must be a Rect')
        if self.clip_box_display is not None and not isinstance(self.clip_box_display, Rect):
            raise TypeError('clip_box_display must be a Rect or None')
        object.__setattr__(self, 'font_size_pt', finite_number(self.font_size_pt, 'font_size_pt'))
        if self.font_size_pt <= 0:
            raise ValueError('font_size_pt must be positive')
        object.__setattr__(self, 'rotation', finite_number(self.rotation, 'rotation'))
        for name in ('text_alpha', 'artist_alpha'):
            object.__setattr__(self, name, alpha(getattr(self, name)))
        for name in ('paint_order', 'background_patch_id'):
            if getattr(self, name) is not None:
                integer_id(getattr(self, name), name)
        if (self.tick_location is None) != (self.view_limits is None):
            raise ValueError('tick location and view limits must both be present or absent')
        if self.tick_location is not None:
            object.__setattr__(self, 'tick_location', finite_number(self.tick_location, 'tick_location'))
            if len(self.view_limits) != 2:
                raise ValueError('view_limits must have two endpoints')
            object.__setattr__(self, 'view_limits', tuple(finite_number(x, 'view_limit') for x in self.view_limits))


@dataclass(frozen=True)
class PdfChar:
    text: str
    box: Rect

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or len(self.text) != 1:
            raise ValueError('PdfChar requires one Unicode character')
        if not isinstance(self.box, Rect):
            raise TypeError('PdfChar box must be a Rect')


@dataclass(frozen=True)
class SaveWarning:
    category: str
    message: str


@dataclass(frozen=True)
class FontGlyph:
    family: str
    file_id: str | None
    glyph_id: int | None

    def __post_init__(self) -> None:
        if self.glyph_id is not None:
            integer_id(self.glyph_id, 'glyph_id')

    @property
    def missing(self) -> bool:
        return self.file_id is not None and (self.glyph_id is None or self.glyph_id == 0)


_WARNING = re.compile(r'^Glyph (\d+)\s+\([^\n]*\) missing from font\(s\) (.+)\.$')


@dataclass(frozen=True)
class GlyphEvidence:
    codepoint: int
    fonts: tuple[FontGlyph, ...]
    warnings: tuple[SaveWarning, ...]

    def __post_init__(self) -> None:
        integer_id(self.codepoint, 'codepoint')
        if self.codepoint > 0x10FFFF or 0xD800 <= self.codepoint <= 0xDFFF:
            raise ValueError('invalid Unicode code point')
        object.__setattr__(self, 'fonts', tuple(self.fonts))
        object.__setattr__(self, 'warnings', tuple(self.warnings))

    @property
    def codepoint_warnings(self) -> tuple[SaveWarning, ...]:
        return tuple(w for w in self.warnings if (m := _WARNING.fullmatch(w.message))
                     and int(m.group(1)) == self.codepoint)

    @property
    def naming_warnings(self) -> tuple[SaveWarning, ...]:
        result = []
        families = {font.family for font in self.fonts}
        for warning in self.codepoint_warnings:
            text = _WARNING.fullmatch(warning.message).group(2)
            if text.startswith('['):
                try:
                    names = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    continue
                if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                    continue
            else:
                names = [name.strip().strip("'\"") for name in text.split(',')]
            if families.intersection(names):
                result.append(warning)
        return tuple(result)

    @property
    def proven_missing(self) -> bool:
        return bool(self.fonts and all(font.missing for font in self.fonts) and self.naming_warnings)
