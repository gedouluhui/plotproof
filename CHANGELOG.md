# Changelog


## Unreleased

- Align public governance, bilingual quickstarts, issue templates, and documentation validation.
## 0.1.0a2 — 2026-11-19

Fixes what a fresh install would have hit.

### Fixed

- `pypdfium2` is pinned to `5.8.0`, the interface the bounded reader and its protocol
  validation were written and verified against. A fresh install resolved 5.15.2, whose
  version objects and character-box behaviour differ, and every PDF read failed with
  `PDF worker returned invalid evidence`.
- `.gitattributes` forces LF for text files. A fresh Windows checkout converted the
  sources to CRLF, so two core mutation anchors could not be found and the mutation suite
  failed on CI while passing locally.

### Not changed

- Rules, thresholds, report schema, CLI and the assessed classes are unchanged from
  0.1.0a1. The 0.1.0a1 release is withdrawn because its wheel declared an open
  `pypdfium2` range and could install the incompatible version.


## 0.1.0a1 — 2026-11-19

First installable preview. Not a certified detector: no holdout run, no accuracy
figure, and `D4_missing_glyph` is never assessed.

### Added

- `plotproof.check_figure(fig)` — captures the figure's real save, reads the exported
  PDF in an owned process, and returns a class-scoped report.
- `plotproof` CLI with `demo` (clean and deliberately clipped samples) and `check`
  (a Python file exposing `figure()`), plus offline JSON and script-free HTML reports.
- Assembly layer (`plotproof/export.py`): source records from the CA1 capture inventory,
  filled records from real painted paths, and a page-origin-aware transform.
- Capture exposes the live source artists in ID order so assembly never has to guess
  which object produced a source ID.

### Changed

- The package is installable (`pyproject.toml`, console script) and pins
  Matplotlib 3.10.8, the runtime the capture layer is version-checked against.
- README rewritten around what is actually assessed, with the B0 design record kept as
  a pointer rather than the front page.

### Limits (unchanged by this release)

- D2 is assessed only when no image or collection was painted.
- Rotated text, mathtext, TeX, wrapped text, rasterized text and path effects force
  `UNKNOWN` or `ERROR`; they are never silently passed.
- The reader's POSIX path is not exercised by the release build.
