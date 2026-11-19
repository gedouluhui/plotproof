"""Synthetic, hand-positioned facts; never benchmark or holdout fixtures."""
from importlib import import_module, util
from dataclasses import replace

from plotproof.geometry import Rect, Transform


def module(name):
    assert util.find_spec('plotproof.' + name) is not None, name + ' implementation missing'
    return import_module('plotproof.' + name)


def text_record(object_id=1, text='abc', box=None, **changes):
    e = module('evidence')
    record = e.TextRecord(
        source_object_id=object_id, text=text,
        bbox_display=box or Rect(10, 10, 40, 20), font_size_pt=10,
        text_alpha=1, artist_alpha=1, visible=True, rotation=0,
        clip_box_display=None, tick_location=None, view_limits=None,
        is_unit=True, exclusion_reason=None, paint_order=1,
        background_patch_id=None,
    )
    return replace(record, **changes)


def pdf_chars(text='abc', x=10, y=10, width=10, height=10):
    e = module('evidence')
    return tuple(e.PdfChar(c, Rect(x + i * width, y, x + (i + 1) * width, y + height))
                 for i, c in enumerate(text))


def glyph_evidence(codepoint=0x20000, glyph_ids=(None,), families=('Test Sans',),
                   warnings=None):
    e = module('evidence')
    if warnings is None:
        warnings = (e.SaveWarning('UserWarning',
                    f'Glyph {codepoint} (test character) missing from font(s) Test Sans.'),)
    return e.GlyphEvidence(codepoint, tuple(
        e.FontGlyph(family, family + '.ttf', glyph_id)
        for family, glyph_id in zip(families, glyph_ids)
    ), tuple(warnings))
