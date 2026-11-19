# B1.5 assembly: from a live figure to a class-scoped report

Status: preview assembly, 2026-11-19. Governed by `CA1` for capture and by the frozen
B0 preregistration (§2 input contract, §4 evidence levels, §7.1 alignment) for the
rules. This document records what the assembly does, which decisions it forced, and
what it deliberately refuses to claim.

## Why an assembly layer exists

The core (`plotproof/core.py`) takes typed facts and returns a `CoreResult`. It never
opens a file and never touches Matplotlib. The capture layer (`CA1`) produces a real
save plus draw-order events. The reader (`pdf_input.py`) produces page geometry and one
`PdfChar` per extracted character. Nothing joined them, so no figure could be checked
end to end.

`plotproof/export.py` is that join. It is deliberately thin: it converts facts and makes
fail-closed decisions; it does not add a rule.

## Decisions that had to be made

1. **Source IDs must come from capture, not from a second traversal.** A save can
   register artists that a later walk does not see in the same order (tick labels get
   their text during draw; layout creates artists). `CapturedPdf.source_artists` exposes
   the registered objects in ID order, so assembly pairs each source with the exact
   object that produced it. Pairing by position in a fresh traversal produced visibly
   wrong boxes during development and is kept only as an explicit fallback that records
   `source_inventory_mismatch`.

2. **Text event boxes are PDF points.** `DrawEvent.bbox_pdf` is named for what it holds.
   The record needs a display-space box, so assembly uses
   `CapturedPdf.to_source_display`. Treating the event box as display pixels scaled every
   unit by 72/dpi a second time and produced `low_overlap` for every unit.

3. **Tick labels are resolved by identity over the figure's axes.** `Text.axes` is not
   populated for tick labels after a save. Without the tick term, out-of-view tick labels
   stay in the unit set with stale extents and depress coverage (measured: 3 of 18 units
   on a clean sample, ratio 0.78 instead of 1.00).

4. **Alpha is the renderer's, not the product of the getters.** The CA1 counterexample
   shows a forced-alpha fill rendering at 0.6 while the getters multiply to 0.36. Filled
   records therefore carry `facecolor_alpha = event.alpha.effective` with
   `artist_alpha = 1.0`, exactly the normalized-factor form CA1 sanctions.

5. **A patch that emits several painted pieces is not collapsed.** It is recorded as a
   capture limit (`multi_path_fill_unsupported`) instead of being reduced to its bounding
   rectangle, which could invent an occluder.

6. **Paint limits are scoped, not global.** An image or collection means the painted
   inventory is incomplete, so D2 cannot be assessed. It does not invalidate D1 or D3,
   which use character boxes and the page rectangle, not occluder geometry. The report
   lists `assessed` and `not_assessed` explicitly, and the state is recomputed over the
   assessed classes only. Hard limits (invalid geometry, ambiguous crop origin,
   non-rectangular clip, wrapped text) are still `ERROR`.

## What the assembly does not do

- No font cmap collection, so D4 is never assessed. A report that says `PASS` therefore
  never means "no missing glyph".
- No image/collection geometry, so D2 is skipped whenever one is painted.
- No claim of a §11 report: the fields are a subset, and no benchmark sample is touched.

## Verification

`tests/test_export.py` (6 tests) exercises the real save, the real reader and the real
core:

- a clean bar chart reaches `PASS` with coverage 1.0 and no findings;
- an annotation that starts inside the page and runs past the right edge produces exactly
  one high-confidence D1 finding whose reported box extends past the page width;
- a figure with an added rectangle reports `D2_occluded_text` as not assessed;
- the report serialises to JSON and the HTML contains no script;
- a figure without an Agg canvas raises `CheckError` instead of guessing;
- the demo CLI writes both reports and returns 0.

The full suite is 358 tests. None of this is a holdout result, and the holdout remains
unopened.
