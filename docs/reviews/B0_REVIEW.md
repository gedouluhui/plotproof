# PlotProof B0 — Independent Review Record

**Date:** 2026-11-13
**Scope:** B0 design freeze and the feasibility spike. No detector code exists; nothing in this review evaluates detection accuracy.
**Reviewers:** two independent read-only subagents with no write access, dispatched with different scopes:

- **Protocol reviewer** — read `docs/B0_PREREGISTRATION.md`, `README.md`, `benchmark/manifest.json`, `benchmark/validate_manifest.py` and checked internal consistency, frozen-scope completeness, metric/gate coherence, and whether the benchmark can support the stated claims.
- **Engineering reviewer** — read `spikes/b0_pdfium_spike.py`, `spikes/fetch_b0_font.py`, `artifacts/b0/api-spike.json`, `tests/test_package.py`, `pyproject.toml`, `docs/DEPENDENCY_LICENSES.md`, `THIRD_PARTY_NOTICES.md` and checked reproducibility, evidence integrity, dependency/license claims, and package behaviour.

Both reviewers were told to report against the B0 rule that no detector work starts before the review is recorded, and to treat unsupported claims as blocking. Their reports were delivered in-session; this document is the project owner's disposition log, not a verbatim transcript.

## Round 1 verdicts

| Reviewer | Verdict | Blocking findings |
|---|---|---|
| Protocol | **REJECT** | 11 (A1–A11) |
| Engineering | **APPROVE WITH REQUIRED FIXES** | 9 required changes |

B0 was therefore **not** accepted in round 1. No B1 detector work was started.

## Protocol findings and dispositions

| ID | Finding | Disposition | Where it is now verified |
|---|---|---|---|
| A1 | The benchmark inventory was prose counts only; 228 samples could not be enumerated or checked, and "24 templates / 228 samples" was an unverified claim. | Added a per-sample `samples` array (ID, template, variant, seed, split, expected state, defect class, target role) and a validator that recomputes every count. | `benchmark/manifest.json`; `benchmark/validate_manifest.py` prints 13 count lines plus `MANIFEST PASS`. |
| A2 | Rotated text was implicitly supported by D2/D3 prose while §3.2 excluded it; reviewers could not tell whether a rotated overlap should be `FAIL` or `UNKNOWN`. | Rotated (rotation ≠ 0.0°) and mathtext units are explicitly unsupported; they remain in the coverage denominator and can only force `UNKNOWN`. D3 states rotated ink separation is not a `FAIL`. | §3.2, §7.1 "Unit", §4 D3 legal counterexamples, §14. |
| A3 | D1/D2/D4 referenced "the aligned character box" but no alignment algorithm was specified; the core comparison was unimplementable as written. | Added §7.1: canonical per-character map, candidate span rule, IoU ≥ 0.50 and char-height ratio [0.20, 1.50], deterministic greedy assignment, ambiguity thresholds, explicit unaligned reasons, and coverage definition. | §7.1. |
| A4 | Nothing prevented a silent or over-eager detector from passing: clean samples could be marked `FAIL` and precision could be computed on a favorable denominator. | Added a clean/counterexample gate (≥16/18 `PASS`, 0 `FAIL`), a precision denominator that includes findings on clean samples and counterexamples, and undefined precision = gate failure. | §8 metric table; §7 "Precision denominator". |
| A5 | Wilson intervals were presented without acknowledging that samples cluster inside 12 templates, which would overstate independence. | Wilson intervals are now descriptive only; a template-cluster bootstrap (12 families, 10,000 draws, seed 0) is the uncertainty statement, and gates are evaluated on point estimates. | §8 "Uncertainty". |
| A6 | D2 used source/PDF bounding-box intersection, which is not occlusion and would fire on legal overlapping bboxes. | D2 now requires aligned character boxes, an opaque filled artist (alpha ≥ 0.95), later paint order, and ≥90% character-box occlusion; 50–90% is medium `UNKNOWN`. | §4 D2. |
| A7 | A single injected mutation could create a collateral second high-confidence finding, inflating recall or corrupting labels. | Added class precedence `D1 > D4 > D2 > D3`, a collateral-review requirement before sealing, and a multi-defect subset with every reference recorded; single-instance counts exclude such samples. | §4 "Class precedence and collateral findings"; §5 design rule. |
| A8 | H09 (scientific notation) risked a mathtext offset text being counted as a supported target, contradicting the "mathtext absent" inventory claim. | All H09 samples pin `target_role = title`; the prereg states mathtext is absent from the inventory, and any `$`-bearing unit is unsupported and stays in the coverage denominator. | `benchmark/manifest.json` H09 records; §3.2, §5. |
| A9 | The D1 boundary (page edge vs axes patch) was ambiguous at sub-point distances, so a legal near-edge sample could be labeled `FAIL`. | D1 defines clipping against the page/axes boundary with the recorded tolerance and a legal near-edge counterexample; text fully inside the page is not clipped. | §4 D1; §4 D1 legal counterexamples; L01–L12. |
| A10 | The holdout had no sealing mechanism; nothing stopped tuning against it or silently regenerating it. | Added family split, separate-process generation at B2, `benchmark/holdout/` git-ignored, `seal.json` with per-sample and generator hashes, one unseal per prereg version, burn rule, and custodian limitation. | §6; `.gitignore`. |
| A11 | The project had no gate for incremental value: a detector could pass while adding nothing over a trivial geometry baseline. | Added the baseline-B delta gate, fixed threshold sweep grid, no-admissible-point = gate failure, and a §9 paragraph on which baseline counts. | §8 metric row + "Baseline sweep"; §9. |

## Engineering findings and dispositions

| Finding | Disposition | Where it is now verified |
|---|---|---|
| The spike depended on whatever system fonts Matplotlib resolved; a missing-glyph probe with DejaVu Sans is reproducible only by accident, and the evidence was not tied to a redistributable font. | Pinned Noto Sans CJK SC Regular (OFL-1.1) by URL, byte size, and sha256; the spike refuses to run if the file is missing/mismatched or if Matplotlib resolves a different file; added `spikes/fetch_b0_font.py` that refuses to overwrite a mismatched existing file. | `spikes/b0_pdfium_spike.py` `PINNED_FONT`/`check_pinned_font`; `spikes/fetch_b0_font.py`; `.gitignore` `.fonts/`. |
| A failing spike run could overwrite previously passing evidence, making the record untrustworthy. | Evidence is written only after 14/14 checks pass; failure writes `api-spike-FAILED.json` and leaves passing artifacts untouched. The failed-run file was removed after the passing run. | `spikes/b0_pdfium_spike.py`; `artifacts/b0/`. |
| Pillow was used by the spike (`PdfBitmap.to_pil()`) but described as not a runtime dependency; the license table was therefore incomplete. | Pillow added as a direct runtime dependency (`pillow>=10,<13`), with MIT-CMU license and purpose recorded in both the license table and the notices table. | `pyproject.toml`; `docs/DEPENDENCY_LICENSES.md`; `THIRD_PARTY_NOTICES.md`. |
| The evidence JSON had no provenance for the script, figure spec, renderer build, or wheel, so a later reader could not tell what produced it. | Added `script_sha256`, `figure_spec_sha256`, PDFium build, wheel tag, backend, `pdf.fonttype`, Matplotlib/NumPy/fontTools/Pillow versions, and the pinned font hash; no absolute user paths are written. | `artifacts/b0/api-spike.json`; `spikes/b0_pdfium_spike.py`. |
| The spike claimed all title CJK character boxes were non-degenerate; the 6th title character is a full-width `）` with a narrow box, so the claim was false. | The check now tests only the ideographs at indices 0, 1, 3, 4 with width and height ≥ 8.0 pt, and the README describes the result accurately. | `title_cjk_boxes_non_degenerate`; README §0 table. |
| README said 67 characters / 41 non-whitespace; the evidence contains 76 / 50. | Corrected to 76 characters (50 non-whitespace) in README and prereg §0. | README; §0. |
| The L04 counterexample (rotated annotation) was expected `PASS`, contradicting the rotated-text exclusion. | L04 is now expected `UNKNOWN`; L06 (semi-transparent occlusion) is also `UNKNOWN`; the six holdout counterexamples remain expected `PASS`. | `benchmark/manifest.json`; README notes; §14. |
| `pyproject.toml` allowed Python 3.11 while only 3.12.3 was verified and the code uses 3.12-era typing. | `requires-python = ">=3.12,<3.13"`; §0 says 3.12 only. | `pyproject.toml`; §0. |
| The third-party notices invented copyright-year ranges that were not read from the installed license files. | Removed the invented ranges; the table now names the license and the exact installed notice path, and states that copyright lines are reproduced from package files at distribution time. | `THIRD_PARTY_NOTICES.md`. |
| `plotproof` could silently import the heavy stack at package import time, hiding a packaging regression. | Added a subprocess isolation test that asserts no heavy module is imported, plus a control test that imports Pillow and asserts the probe reports it. | `tests/test_package.py` (3 passed in `.venv`). |

## Deferred or rejected suggestions

- **Adding more templates at B0.** Rejected. The inventory is frozen at 24 templates; changing it after an iteration starts requires a new prereg version (§15). More templates are a B2+ decision, not a review fix.
- **Claiming the holdout is independent.** Rejected. The split is by template family and shares line-chart and font material; the limitation is stated in §6 and §14.
- **Publishing the proprietary-font probe as a public benchmark case.** Rejected. Only the OFL font is public; proprietary fonts are excluded from artifacts.
- **Running the detector on real PDFs to "sanity check" the design.** Rejected at B0. The input contract is wrapper-created figures only; arbitrary PDFs are out of scope, and no detector exists.

## Residual risks accepted for B0

1. The alignment algorithm is specified but untested; §7.1 thresholds (IoU 0.50, height ratio [0.20, 1.50], ambiguity tolerances) are design choices that may need a prereg revision after B1 dev-set evidence.
2. The benchmark is synthetic and small; the gates are initial product thresholds, not estimates of real-world performance.
3. The 12-template cluster bootstrap will be wide; a passing point estimate with overlapping intervals must be reported as such, not as a significance claim.
4. The seal is procedural (hash + timestamp), not access-controlled; the project owner is the only custodian.
5. Only Windows 11 / Python 3.12.3 / Matplotlib 3.10.8 / PDFium 149.0.7825.0 is verified; other environments are untested.

## Round 2

A fresh read-only reviewer was dispatched after the round-1 fixes, with the same B0 gate rule and no access to the round-1 dispositions. Its report was delivered in-session; this table is the owner's disposition log.

**Verdict: REJECT** — 9 required findings (one blocker) and 7 minor. The blocker was that the frozen inventory contradicted the frozen scope: D12 declared `date_ticks_rotated_30` while §3.2 excluded rotated text, making D12 clean samples unable to reach the 0.90 coverage required for `PASS`. The reviewer independently re-ran the validator (`MANIFEST PASS`, all 13 counts match), pytest (`3 passed`), and the evidence hash checks, and confirmed the spike's 14/14 `PASS` and the absence of absolute paths.

| ID | Finding | Disposition | Where it is now verified |
|---|---|---|---|
| R2-1 | **BLOCKER** — D12 declares rotated date ticks while rotated text is out of scope; its clean samples cannot reach 0.90 coverage, so a dev-set label is unreachable. | D12's feature is now `date_ticks_horizontal` with an explicit note that rotation is excluded; the validator rejects any template feature containing `rotated`, so this contradiction cannot silently return. | `benchmark/manifest.json` D12; `benchmark/validate_manifest.py` template-feature check. |
| R2-2 | §5 claims each template declares a `target_role`, but template records had no such field; only per-sample strings were checked for non-emptiness. | All 24 template records now carry `target_role` (23 `title`, H11 `suptitle`), derived from and asserted consistent with their sample records; the validator rejects a missing or disagreeing template role. | `benchmark/manifest.json`; `benchmark/validate_manifest.py`. |
| R2-3 | §7.1's height-ratio condition has no corresponding unaligned reason, and ambiguity removal does not say whether spans are released, so two implementations can disagree on coverage. | Added `height_mismatch` to the reason taxonomy and stated that ambiguous units are removed together with their spans and are not reassigned; no second pass runs. | §7.1 "Reason precedence" and ambiguity paragraph. |
| R2-4 | §8 defines coverage over supported text objects while §7.1 includes unsupported and unaligned units in the denominator. | §8 now defines coverage as aligned units / all units, explicitly including unsupported and unaligned units. | §8 coverage row. |
| R2-5 | §10 says the project stops after two recorded iterations but also that the third failed attempt triggers the stop. | §10 now states that the second failed attempt triggers the stop. | §10. |
| R2-6 | §6 requires a committed `benchmark/holdout/seal.json`, but `.gitignore` excluded the whole directory with no negation, so Git could never re-include the seal. | The ignore rule is now `benchmark/holdout/*` plus `!benchmark/holdout/seal.json`; the directory itself is no longer excluded. | `.gitignore`; tested in a throwaway temp repo with the same ignore file and two files: `git add -n .` lists `benchmark/holdout/seal.json` and does not list `benchmark/holdout/H01.clean.s1.pdf`, while `git check-ignore` attributes the PDF to the `benchmark/holdout/*` rule. |
| R2-7 | The evidence JSON records `pdf_fonttype: 3` while the artifact is the fonttype-42 PDF; the spike read `rcParams` before `build_figure` set 42. | The spike now records the main PDF as fonttype 42 and records `fonttype` per section (`42` and `3`); evidence was regenerated from the corrected script. | `artifacts/b0/api-spike.json` (`pdf_fonttype=42`, `fonttype_42.fonttype=42`, `fonttype_3.fonttype=3`, 14/14 `PASS`); `spikes/b0_pdfium_spike.py`. |
| R2-8 | §0 still claimed all title CJK character boxes are non-degenerate although the check deliberately tests only the four ideographs. | §0 now says "the four CJK ideographs in the title have non-degenerate character boxes." | §0 environment table. |
| R2-9 | §3.2 excluded "rotated text of any nonzero rotation (0/30/45/90° labels)" — listing 0° although 0° is supported. | Removed `0/`; the exclusion now reads 30/45/90° and agrees with §3.1 and §7.1. | §3.2. |
| R2-10 | `pyproject.toml` still classified Python 3.11 while `requires-python` is `>=3.12`. | Removed the 3.11 classifier. | `pyproject.toml`. |
| R2-11 | The review record and §13 claim 14 count lines; the validator prints 13 counts plus `MANIFEST PASS`. | Both now say 13 count lines plus `MANIFEST PASS`. | This file, row A1; §13. |
| R2-12 | README says the font URL is in §0; §0 had no URL. | §0's font row now includes the pinned URL. | §0; README. |
| R2-13 | §7 matches against "the reference box", but a reference is a tuple with no box. | §7 now says the IoU is between the candidate and the reference instance's source-object box transformed under §2. | §7. |
| R2-14 | The bootstrap resamples only the 12 template families, excluding the 6 holdout counterexamples that enter precision and the clean gate. | The bootstrap now resamples the 12 template families plus, independently, the 6 holdout counterexamples, pooled. | §8 "Uncertainty". |
| R2-15 | §14 says "higher z-order" while D2 uses recorded paint order. | §14 now says "a later recorded paint order." | §14. |
| R2-16 | `docs/DEPENDENCY_LICENSES.md` had a heading merged into a table row (`…left implicit.### Transitive…`). | Split into a paragraph and a `### Transitive runtime dependencies observed` heading. | `docs/DEPENDENCY_LICENSES.md`. |

The reviewer also noted it could not verify whether H09's `scientific_offset` renders as mathtext, which would decide whether H09 clean can hit 0.90 coverage. That cannot be settled without generating samples, so §5 now requires H09 to use a plain offset text (`1e3`, `axes.formatter.use_mathtext=False`) and states that mathtext offsets are not allowed as the target; if an offset still renders as mathtext it is unsupported and stays in the coverage denominator.

Re-verification after the fixes (owner-run, this session):

- `spikes/b0_pdfium_spike.py`: 14/14 checks `PASS`, `OVERALL PASS`; regenerated JSON has `pdf_fonttype=42`, per-section fonttype fields `42`/`3`, script sha256 `aeba5aa83053…`, and the fonttype-42 PDF sha256 is unchanged at `0800e869…` (the script edit did not change the PDF bytes).
- `benchmark/validate_manifest.py`: 13 count lines plus `MANIFEST PASS` under the new `target_role` and rotated-feature checks.
- `.venv` pytest: 3 passed (one third-party deprecation warning only).

## Round 3

A fresh read-only reviewer was dispatched against the round-2 state, with the same B0 gate rule and no access to the round-2 dispositions. Its report was delivered in-session; this table is the owner's disposition log.

**Verdict: REJECT** — 3 required findings (one blocker) and 4 minor. The blocker was the same class as round 2's: D11 (log scale) declared `scientific_ticks`, but Matplotlib 3.10.8 renders log tick labels as `$\mathdefault{10^{n}}$`; D11 had no plain-formatter binding, and the validator only rejected `rotated`. The reviewer measured 9 mathtext units out of 19, so D11 clean could not exceed 0.526 coverage and its `PASS` label was unreachable. The reviewer independently confirmed that all 16 round-2 claims verify, re-ran the validator (`MANIFEST PASS`, 13 counts), pytest (`3 passed`), and the evidence hash checks, and found D12, `target_role`, and the H09 mitigation unambiguous. It also found that the review target changed during the review and that no revision hash was pinned.

| ID | Finding | Disposition | Where it is now verified |
|---|---|---|---|
| R3-1 | **BLOCKER** — D11 (log scale) has the same unreachable-clean-`PASS` defect that blocked D12: default log labels are mathtext, D11 had no plain-formatter binding, and the validator only rejected `rotated`. | D11 now declares `log_ticks_plain_text`, binds `tick_formatter` to `FuncFormatter('{:g}')`, and carries a scope note. The validator requires that feature and a `FuncFormatter` (non-mathtext) binding for every template with a `log_` feature, rejects the ambiguous `scientific_ticks` name, and §5 documents the binding. Fresh reproduction: default labels were 10/10 `$…$`; with the formatter, 0/10 contained `$` and 10/10 were non-empty plain labels. | `benchmark/manifest.json` D11; `benchmark/validate_manifest.py`; §5. |
| R3-2 | **REQUIRED** — §11 still reported `coverage {supported_objects, aligned_objects, ratio}`, so the ratio was not recomputable; §3.2, §4.1, and §8 still used "supported-object alignment coverage"; the 0/0 convention for a unit-less sample was undefined. | §11 now records `total_units`, `aligned_units`, `unaligned_units`, `unsupported_units`, `unaligned_by_reason`, and `ratio`, plus the run-level `zero_unit_samples`. `ratio = aligned/total`, null exactly when `total = 0`; such a sample is `UNKNOWN`, excluded from the §8 macro-average, counted separately, and still counted in the UNKNOWN rate. §7.1 defines the bucket sums; §8 states that undefined coverage fails the gate; the metric is renamed "text alignment coverage" throughout. | §3.2, §4.1, §7.1, §8, §11. |
| R3-3 | **REQUIRED** — the review target changed during the review (observed mtimes 12:45:23/12:45:32/12:45:49 against 12:40/12:42), and no Git revision existed, so no immutable revision could be named. | The normative files are now pinned by `docs/B0_FREEZE.sha256`, committed in a Git repository initialized **inside `plotproof` only**, and tagged `b0-freeze-r4`. Round 4 reviews that tag; no normative file is edited while it runs. The review record is excluded from the freeze because it is the live disposition log, not a normative artifact. | `docs/B0_FREEZE.sha256`; Git tag `b0-freeze-r4`. |
| R3-4 | **REQUIRED** — §6 required every holdout sample to be reviewed by a human before sealing, while §6.6 burned the holdout if the developer opened any holdout file and §6.8 made the owner the only custodian. The rules contradicted each other. | §6.2 now freezes the detector, every threshold, and the evaluation script before holdout generation, and records that revision in the seal. §6.5 defines the **label reviewer** role and one logged pre-seal session, records corrections as hashes without label text, and forbids running the detector in that session. §6.6 burns the holdout only for openings outside that session or any detector run before the B3 unseal. §6.8 limits the claim to the procedural record, not blindness or independent annotation. | §6 items 2–6 and 8; §5 "Generator labels are not ground truth." |
| R3-5 | **MINOR** — the bootstrap left three choices open: whether the clean sample travels with its family, whether to pool counts or average cluster ratios, and how duplicated families count. | §8 "Uncertainty" now draws whole families (clean + eight defect samples), draws counterexamples independently, counts duplicates with multiplicity, pools numerators/denominators for precision, recall, and the UNKNOWN/ERROR rates, recomputes coverage as the mean of per-sample ratios, pools the clean-gate counts, and reports undefined draws. | §8 "Uncertainty". |
| R3-6 | **MINOR** — §14's alignment-failure list omitted `height_mismatch` and the two `unsupported_*` reasons. | §14 now lists all seven reasons and distinguishes supported-but-unaligned units from out-of-scope units. | §14. |
| R3-7 | **MINOR** — the dependency audit commands omitted Pillow although it is a direct runtime dependency. | Both the `importlib.metadata` loop and `pip show` now include `pillow`. | `docs/DEPENDENCY_LICENSES.md` §5. |

Re-verification after the fixes (owner-run, this session, before freezing):

- `benchmark/validate_manifest.py`: 13 count lines plus `MANIFEST PASS` under the new D11/H09 bindings.
- D11 label reproduction on Matplotlib 3.10.8: default 10/10 labels were mathtext; `FuncFormatter('{:g}')` produced 10/10 plain, non-`$` labels.
- `.venv` pytest: 3 passed (one third-party deprecation warning only).
- `artifacts/b0/api-spike.json`: internal PDF sha256 values still match the committed PDFs; no absolute paths.

### Freeze record for `b0-freeze-r4`

- A Git repository was initialized **inside `plotproof` only**. The parent directory (`C:\Users\lyj20\Desktop\kaggle`) contains private competition material and was never initialized, staged, or pushed.
- Freeze commit: `f7892e1156716a81e9eb187255e0c3e3c2dd8c0f`, tagged `b0-freeze-r4` (lightweight tag). The commit tracks exactly 18 files: the 17 normative files listed in `docs/B0_FREEZE.sha256` plus the manifest itself. `docs/reviews/B0_REVIEW.md` is deliberately untracked at that commit.
- Before freezing, `artifacts/b0/api-spike.json` was normalized from CRLF to LF line endings so a fresh clone reproduces the recorded bytes; JSON semantics were verified unchanged (parsed objects compare equal), and the internal PDF sha256 values were re-checked against the committed PDFs.
- Working-tree check: `sha256sum -c docs/B0_FREEZE.sha256` → 17/17 `OK`, exit 0.
- Fresh-clone check: cloned the repository to a temporary directory, checked out `b0-freeze-r4`, ran the same command → 17/17 `OK`, exit 0. The freeze therefore describes the tagged revision, not just this working copy.

The round-4 review target is the `b0-freeze-r4` tag. No normative file may be edited while that review runs; this log is the only file expected to change.
