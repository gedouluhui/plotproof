# B1 deterministic core implementation plan and ledger

> Execute sequentially with test-driven development and owner verification. The user delegated implementation decisions and all reviews to the owner. No approval round is outstanding.

**Goal:** Turn the frozen rules into testable, dependency-light code, then connect the code to an actual save/capture/PDF extraction pipeline.

**Architecture:** Pure float64 geometry and immutable evidence objects feed unit accounting, canonicalization/alignment, and D1–D4 rule functions. The I/O boundary will separately collect font and renderer evidence; the core never fabricates it or opens a file. A pure core result is not yet a complete §11 export report.

**Tech stack:** Python 3.12 standard library for the core; pytest for tests. The later I/O layer uses the existing Matplotlib/PDFium/fontTools/Pillow dependencies.

**Spec:** `docs/B0_PREREGISTRATION.md` v1.13 at `b0-freeze-r17`, particularly §§2–4, 7.1 and 11. B0 closed by Round 17 at `8112fee`.

## Global constraints

- Do not generate or open `benchmark/holdout/`; no tuning on holdout.
- Do not modify B0-pinned files during this core slice. The package root remains an unreleased stub; new internal modules do not change that claim into a public API.
- All comparisons use finite Python floats (binary64), PDF points, bottom-left origin, unrounded values. Degenerate boxes are allowed but have zero area.
- High findings alone produce FAIL; preserve `ERROR > FAIL > UNKNOWN > PASS` and confidence-scoped `D1 > D4 > D2 > D3`.
- All seven alignment failure reasons are accounted for. Missing-glyph deletion requires evidence from every resolved font plus this save's naming warning.
- No network, credentials, private competition data, git configuration changes, or root-repository operations.
- This core slice adds files only. No commit or remote publication is assumed from a continuation request.

## Execution decisions

Use the existing, dedicated PlotProof checkout on a new feature branch rather than duplicate its environment. B0-pinned files and old artifacts stay byte-identical. Implement inline because geometry, evidence shapes, alignment and rules have tightly dependent interfaces. An independent read-only reviewer may inspect the final additions; owner tests remain mandatory.

Core inputs are typed records, not permissive JSON dictionaries. Missing/untrusted JSON fields will be rejected by the later bundle loader, not filled with favorable defaults by the core. Font evidence contains glyph IDs (`None` means absent; 0 means missing), a resolved family, and a file identifier. The later collector must derive these from real cmap files and warning records. A missing font is an error, not a skipped unit.

## Task 1 — Geometry (`plotproof/geometry.py`, `tests/test_geometry.py`)

- [x] RED: parameterized literal cases for zero area, hairline boxes, exact boundary equality, negative/tight origins and invalid coordinates; integer-grid oracle for rectangle union.
- [x] Implement `Rect`, `Transform`, `union_area`, `intersections`, `bounding_rect`, `iou`, `boundary_evidence`.
- [x] GREEN: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/Scripts/python.exe -m pytest tests/test_geometry.py -q`.

Example acceptance: `union_area([Rect(0,0,2,2), Rect(1,1,3,3)]) == 7`; `boundary_evidence(Rect(-1,0,1,2), Rect(0,0,10,10)) == 'high'`; zero-width boxes outside the page produce no evidence.

## Task 2 — Unit accounting and alignment (`plotproof/evidence.py`, `plotproof/units.py`, `plotproof/alignment.py`, corresponding tests)

- [x] RED: first-failed predicate, invisible/out-of-view ticks, saved-page rather than figure-page, strict count reconciliation, unsupported reasons.
- [x] RED: whitespace/CRLF canonical maps, per-character NFKC without ligature expansion, candidate height/IoU boundaries, deterministic assignment, both ambiguity rules, no reassignment after ambiguity, missing-glyph second search.
- [x] Implement immutable records and `enumerate_units`, `canonicalize`, `align_units`.
- [x] GREEN: run these tests together with geometry tests.

Interfaces: `TextRecord` contains captured predicate terms and recorded `is_unit`/exclusion; `PdfChar` contains one Unicode character and a point rectangle; `AlignmentResult` exposes source-ID-to-span assignments, unknown reasons, and recomputable coverage. Canonical maps preserve original character indices including all members of a collapsed whitespace run.

## Task 3 — Rules and core result (`plotproof/rules.py`, `plotproof/core.py`, corresponding tests)

- [x] RED: D1 positive-area guard and reporting bbox; D2 union versus single-artist coverage, alpha endpoints/paint order/geometry/own-background guards; D3 char-unions versus source-bboxes, 0.15/0.50/0.5-pt endpoints, own opaque background demotion; D4 complete font/warning evidence and unaligned medium path.
- [x] RED: same-confidence precedence, unordered pair identities, ERROR/FAIL/UNKNOWN/PASS aggregation, coverage 0.90 boundary, empty and unsupported units.
- [x] Implement `detect_rules` and `check_core` returning structured evidence and counts, not a falsely complete file-level report.
- [x] GREEN: run all tests. Evidence must include operands sufficient to independently recompute finding boxes and coverages.

## Task 4 — Verification and handover

- [x] Read-only review of every new module against the spec, with findings adjudicated explicitly.
- [x] Mutation falsification in isolated temporary copies only; assert each source substitution is nonempty and an intended assertion fails (not an import/encoding/collection error).
- [x] Run full pytest, compile checks, frozen-manifest verification, whitespace checks and a public-data-only review.
- [x] Update this ledger and both handovers with actual test outputs, limits and next action. Do not claim benchmark performance or B1 completion.

## Subsequent I/O slice (not implemented by the pure core)

`plotproof/export.py` will capture deterministic traversal/paint order and saved geometry; a serialized, resource-limited PDFium worker will extract character boxes and page metadata; font evidence will be collected from actual resolved files and warnings. A dev-only generator will implement the twelve dev templates and six dev counterexamples, certify injection operands and clean checks, and produce JSON reports. These require their own red tests and real saved PDFs. No holdout sample is an integration fixture. Baselines, evaluation freeze and holdout remain later milestones.

## Initial verification (2026-11-18)

Owner command: `.venv/Scripts/python.exe -m pytest -q` — 88 passed; one pre-existing auto-loaded AnyIO plugin deprecation warning from the system Anaconda installation. `sha256sum -c docs/B0_FREEZE.sha256` — every pinned entry OK. The isolated test invocations below disable unrelated globally auto-loaded pytest plugins, without changing the environment or repository configuration.

## Progress

Core modules and synthetic tests are now implemented on `b1-deterministic-core`, with no changes to B0-pinned files. The first red runs were 22 geometry, 20 unit/evidence, 17 alignment, 29 rule and 13 core failures, followed by passing implementations. These are observed test runs, not benchmark metrics.

Independent read-only reviewers found two groups of issues which the owner reproduced before fixing: extreme finite-area IoU overflow/underflow and a subnormal boundary false positive; and the §7.1 empty missing-glyph remainder exception incorrectly retaining an ordinary match when PDF extraction still contains the missing character. The latter now remains unaligned and D4 medium. A later rule review found the normal fallback-font case, which was reproduced and fixed as below. No finding was dismissed merely because the suite was green.

Ruling: §4 D4's explicit legal example (all fonts resolved, a fallback supplies a nonzero glyph ID, and no missing-glyph warning for that code point) overrides the broad stack-disagreement medium wording. A naming warning or uncertain supply still cannot be promoted to high. This resolves an ambiguity without changing the frozen file; the legal no-warning `(None,7)` and `(0,7)` stacks are exercised directly.

Ruling: an image with unknown opacity cannot prove D2 high. Its intersection contributes only possible coverage; `effective_alpha` stays null and `confirmed_joint_coverage` is recorded separately. Alpha below 0.50 is excluded even when an opacity upper bound of 1 cannot rescue it. Equal paint-order values are ambiguous, never known-after. The rule reviewer independently probed these two cases.

Mutation verification runs in fresh temporary copies and never writes a product file. The first pass exposed a masked test: removing the predicate-reconciliation check still failed the final total check, so the original tests could not isolate that guard. A wrong exclusion reason with an unchanged total now tests that branch independently. The first pass also showed that pytest's rewritten assertion XML can omit the literal `AssertionError`; the classifier now reads the failure message and has paired positive/negative controls, including a crash whose traceback merely mentions that word. These were measurement issues, not reasons to relax a product threshold.

## Final owner verification for this slice (2026-11-18)

- Full command `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/Scripts/python.exe -m pytest -q --tb=short`: **217 passed**, no warnings with unrelated plugin autoload disabled. Receipt: `artifacts/b1/core-verification.json`; includes the tested Python files' SHA-256 values and actual installed dependency versions.
- The suite includes the original B0 tests, synthetic geometry/alignment/rule/state cases, **16 isolated on-disk core mutations plus two mutation-classifier controls**, and **8 real-PDF tests**. Counts describe tests, not an estimate of detector accuracy.
- The real-PDF test-only collector uses actual Agg source extents, save-time draw calls, PDFium code points/char boxes, resolved DejaVu Sans cmap IDs, and same-save warnings. Four defective examples return FAIL; four legal controls return PASS. These are manually designed small Figure.text fixtures, not the preregistered dev or holdout sample inventory.
- Owner rendered and visually inspected all eight pages: `artifacts/b1/core-real-pdf-contact-sheet.png`. Clipping truncates the right-edge text; the after-painted opaque rectangle erases its text; distinct strings visibly overlap; U+20000 appears as tofu. The controls remain visibly legible. Image rendering was an inspection operation, not a detector input or an accuracy metric.
- `sha256sum -c docs/B0_FREEZE.sha256`: **24/24** unchanged. No holdout generation, inspection or evaluation occurred in this slice.
- All independent reviewers' required findings were reproduced by the owner and fixed with regression tests; final fixes were owner-verified, not claimed to have received a new independent APPROVE verdict. No per-call model selector was exposed; no claim of cross-model independence is made.

Core work is complete for this slice. **B1 as a whole is not complete:** the production save wrapper, resource-limited PDFium I/O worker, complete manifest/cmap collectors, dev generator, baseline comparison and file-level reports remain next. The package root deliberately still exposes no public API. No precision/recall, speedup, adoption or launch claim exists.

Related P1 progress, owned in the separate repository: optional light reports and single-step expansion now pass the owner's 144-test run and 8/8 total gate. Default full JSON is byte-identical to the running `f1fa847` implementation for all five fault modes. A strict TypeScript optional-union overload issue found by independent review was reproduced and fixed without a runtime change. The recorded 64-step seed-7 report sizes are full 213403 bytes and light(k=5) 79043 bytes; this is output reduction only. Both repositories' new work remains uncommitted/unpublished.
