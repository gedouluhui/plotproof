"""PlotProof — source-assisted export evidence for Matplotlib figures.

The public surface is one call: ``check_figure(fig)``. It is imported lazily so
that ``import plotproof`` stays free of Matplotlib, NumPy, PDFium and Pillow.
"""
from __future__ import annotations

__version__ = "0.1.0a1"

__all__ = ["CheckError", "CheckReport", "check_figure", "render_html"]

_LAZY = frozenset(__all__)


def __getattr__(name: str):
    if name in _LAZY:
        from . import export
        return getattr(export, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY)
