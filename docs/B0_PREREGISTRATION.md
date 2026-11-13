# PlotProof B0 Preregistration

**Version:** 1.0 (frozen candidate, 2026-11-13)
**Status:** B0 design is frozen before detector implementation. Round-1, round-2, and round-3 reviews and their dispositions are recorded in `docs/reviews/B0_REVIEW.md`; round 3 was REJECT. The round-3 fixes are pinned by `docs/B0_FREEZE.sha256` and the `b0-freeze-r4` tag; the round-4 scoped re-review of that tag is pending. Do not start B1 detector work until that re-review is recorded as passing.
**Product:** PlotProof — a source-assisted export checker for Matplotlib figures.

**中文摘要**

- 本文件在写任何检测器代码之前，冻结 P2 PlotProof 的输入边界、缺陷定义、228 个自制样本的模板清单、按模板族划分的保留集规则、匹配/去重规则、指标与放行门槛。
- B0 只完成可行性核验与设计冻结：Matplotlib→PDF→PDFium 的字符框/文本/位图链路已在本机跑通；样本尚未生成，检测器尚未实现，没有任何真实用户或效果数据。
- 已核验的关键事实：`pdf.fonttype=42` 可提取中英文文本与字符框；`fonttype=3` 下中文提取失败；缺字警告与字体 cmap 缺失可作证据，但“PDF 文本里仍有该字符”**不能**证明字形已渲染；回退字体可消除缺字警告。
- 初始放行门槛：保留集高置信 FAIL precision ≥ 0.95、端到端 recall ≥ 0.80、样本级 UNKNOWN ≤ 0.20、ERROR ≤ 0.05、支持对象对齐覆盖率 ≥ 0.90，且干净样本/合法反例不得被高置信判 FAIL。
- 这些是待验证的产品门槛，不是已经达到的成绩；样本为自制合成数据，不能外推为真实世界准确率。

---

## 0. Status and verified evidence

B0 is a design gate, not a product release. No detector code exists. The `plotproof` package is a version stub.

The following facts were verified on the development machine on 2026-11-13. The machine-readable record is `artifacts/b0/api-spike.json`; the reproducible script is `spikes/b0_pdfium_spike.py`.

| Item | Observed | Consequence for v1 |
|---|---|---|
| Python | 3.12.3 (Anaconda, Windows) | v1 targets 3.12 only (`>=3.12,<3.13`); only 3.12.3 is verified here |
| Matplotlib | 3.10.8, Agg, PDF backend | v1 verifies this version; other versions are untested |
| pypdfium2 / PDFium | 5.8.0 / 149.0.7825.0, wheel `py3-none-win_amd64` | renderer version is part of every result hash |
| fontTools / NumPy / Pillow | 4.61.1 / 2.4.6 / 12.2.0 | cmap checks and bitmap helpers are available |
| CJK font used for evidence | Noto Sans CJK SC Regular, OFL-1.1, sha256 `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`, URL `https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf` | redistributable benchmark font; binary is not committed |
| Matplotlib `pdf.fonttype=42` | CJK title, labels, legend extracted; 76 characters (50 non-whitespace); the four CJK ideographs in the title have non-degenerate character boxes | supported path for text alignment |
| Matplotlib `pdf.fonttype=3` | ASCII still extractable; CJK title/label absent (50 chars) | CJK under Type 3 must be UNKNOWN, never PASS/FAIL by text evidence |
| Single-page geometry | 288 × 216 pt; cropbox == mediabox; rotation 0; 576 × 432 px at scale 2 | coordinate transform is testable; rotated/multi-page is out of scope |
| Deterministic bytes | identical input produced identical PDF sha256 `0800e869b86f66c671e8ccf94c7a3ae15ac25a576291ab5ca0ecb62165fd820a` | sample hashes can pin inputs only when the font file and library versions match the recorded environment |
| Missing glyph (U+9F98 with DejaVu Sans) | cmap absent; Matplotlib warning emitted; **PDF text extraction still contains U+9F98**; fallback font stack suppresses the warning | D4 requires cmap absence + warning; extraction presence is not rendering evidence |

The spike passed all 14 checks. It is not a detector and it does not generate benchmark samples.

## 1. Product claim and non-claims

**Claim.** For a Matplotlib `Figure` exported through PlotProof's wrapper in the same process, PlotProof compares the captured source text objects and geometry with the final single-page PDF, and reports evidence-backed findings, or `UNKNOWN` when the evidence is insufficient.

**Non-claims.**

- It is not a general PDF checker. It does not accept arbitrary PDFs in v1.
- It is not a semantic or aesthetic judge. It does not check whether a chart's message is true, whether a citation exists, or whether colors are attractive.
- It is not an ML model. The core is deterministic geometry and text evidence.
- It does not replace human review. `PASS` means "no supported defect found with sufficient coverage", not "the figure is correct".
- It does not claim real-world accuracy, user adoption, stars, or time savings before B2/B4 measurements exist.

## 2. Input contract

A v1 check consumes exactly one of these:

1. A live Matplotlib `Figure` plus the PDF written by `plotproof.export.save(fig, path)`, or
2. A frozen test bundle containing the captured source manifest (JSON) and the exported PDF, created by the same wrapper.

The wrapper must record: Matplotlib version, backend, `pdf.fonttype`, figure size in inches, DPI, save kwargs (`bbox_inches`, `pad_inches`, `transparent`), page size, cropbox, mediabox, rotation, output sha256, source text object IDs, their text, font family list, resolved font files, color, alpha, rotation, bounding boxes in display coordinates, visibility, z-order, and the artist class.

**Rejected as invalid input (ERROR):**

- multi-page PDF, page rotation ≠ 0, cropbox ≠ mediabox;
- encrypted or malformed PDF;
- a PDF not produced by the wrapper (missing source manifest or hash mismatch);
- a non-PDF export (`png`, `svg`, `eps`);
- a figure whose text contains a path-only or mathtext object that cannot be mapped to Unicode **and** no supported text objects remain (the latter is `UNKNOWN`, not `ERROR`; see §3).

**Coordinate normalization.** All comparisons happen in PDF points with the origin at the bottom-left of the page. Matplotlib display coordinates (origin top-left) are converted through the figure's DPI and page size; the wrapper records the exact transform. No DPI is guessed from the PDF. If the transform cannot be established, the result is `UNKNOWN`.

**Process rule.** Every PDFium call in a process is serialized. Parallel rendering is allowed only across separate processes. This is a hard requirement from the PDFium/pypdfium2 documentation, not an optimization. Object lifetimes are explicit (open → use → close in `try/finally`), and a render subprocess timeout kills only its own PID.

## 3. Supported scope (v1)

### 3.1 In scope

| Dimension | Supported |
|---|---|
| Source | Matplotlib `Figure` in the same process, PDF backend, Agg |
| Pages | exactly one |
| Page geometry | rotation 0, cropbox == mediabox, finite size ≤ A2 |
| Text objects | title, suptitle, axis labels, tick labels, legend text, annotations (`Axes.text` / `annotate`), colorbar labels, `Figure.text` |
| Languages | English; Chinese (Simplified) when a CJK font is available; mixed CJK/English within one label |
| Text features | numbers, negative signs, units, thousands separators, multi-line text, opaque background bboxes; rotation 0 only in v1 |
| Fonts | DejaVu Sans (bundled with Matplotlib) for ASCII; Noto Sans CJK SC or Source Han Sans SC (OFL) for CJK; user-provided fonts are allowed if the wrapper records the file |
| PDF text mode | `pdf.fonttype=42` fully supported; `pdf.fonttype=3` supported for ASCII only |
| Defect classes | D1 clipped text, D2 occluded text, D3 overlapping text, D4 missing glyph (see §4) |

### 3.2 Out of scope (report `UNKNOWN` or reject, never silently `PASS`)

- arbitrary PDFs, scanned PDFs, PDF/A, tagged-PDF semantics, optional content groups;
- multi-page documents, inset axes, tables, images containing text, 3D projections;
- rotated text of any nonzero rotation (30/45/90° labels are excluded from v1 evidence); this is a deliberate scope cut, not an implied pass;
- mathtext and TeX-rendered labels where Unicode mapping is absent (these are `UNKNOWN` unless another supported text object provides a decidable check);
- text rendered as vector paths with no Unicode mapping;
- RTL scripts, vertical text, Indic/Arabic shaping;
- color contrast, aesthetics, chart-message truth, citation truth;
- "label was removed and re-rendered" counterfactual detection (layout changes invalidate it);
- arbitrary PPTX/DOCX/HTML ingestion;
- remote fonts, network access, telemetry.

Out-of-scope objects are listed in `unknown_objects` and reduce the sample's text alignment coverage. A figure with **no supported text objects** is `UNKNOWN`, never `PASS`. A figure whose text alignment coverage is below 0.90 is also `UNKNOWN` (§7.1).

### 3.3 Font policy

- Microsoft fonts (Microsoft YaHei, SimHei, SimSun) are **not** used in public benchmark artifacts and are never committed. The B0 feasibility run used Noto Sans CJK SC instead.
- The public CJK benchmark requires Noto Sans CJK SC (OFL-1.1) or Source Han Sans SC (OFL-1.1). The font binary is downloaded into `.fonts/` (git-ignored) and pinned by sha256 in the prereg. If the font is missing, CJK samples are skipped with a recorded reason; they are not silently replaced by a proprietary font.
- DejaVu Sans is bundled with Matplotlib and is used for ASCII samples.
- Every sample records the resolved font family, file path, and file hash. Changing a font invalidates byte-level comparisons.

## 4. Defect classes and evidence levels

Only **high-confidence** findings may produce `FAIL`. Medium-confidence candidates produce `UNKNOWN` (manual review). Low-confidence candidates are not reported as defects.

### D1 — `clipped_text`

**Definition.** A supported, visible text object has glyph ink outside the visible page in the final PDF.

**High-confidence evidence.**

- At least one aligned PDF character box has less than 50% of its area inside the page rectangle, or its box center lies outside the page rectangle; and
- the source object is visible and the alignment is unique under §7.1.

`in_layout=False` is **not** an exclusion: the text is still drawn, so it is still checked.

**Medium / UNKNOWN.** Any aligned character box intersects the page boundary and is not entirely inside, but does not meet the high-confidence test above (for example, a box 2 pt outside with 90% of its area inside); the whole transformed source bbox is outside the page but no character box can be aligned; the page geometry is unsupported.

**Legal counterexamples.** Text outside the axes patch but inside the page; text within 1 pt of the edge but fully inside; text hidden by `visible=False` (excluded at capture, not a defect); `bbox_inches='tight'` expanding the page to include an annotation.

### D2 — `occluded_text`

**Definition.** An opaque artist painted after a supported text object covers the text's painted character boxes enough that the text cannot be read in the final render.

**High-confidence evidence.**

- The text object is visible, rotation 0, and aligned under §7.1; at least one aligned character box exists;
- one opaque filled artist (facecolor alpha ≥ 0.95 and artist alpha ≥ 0.95) has an effective paint order **after** the text object;
- its filled path covers ≥ 90% of the union of the text object's aligned character boxes, not merely ≥ 90% of the source bounding box;
- the occluder's filled path is inside the page;
- supported occluder geometry is a rectangle, legend frame, or other convex/axis-aligned filled patch, or an image with a known opacity ≥ 0.95. Concave polygons are at most medium;
- the text's characters are present in the PDF text extraction, proving the text object was emitted (this is **not** evidence that glyph ink is visible; it only excludes skipped objects); and
- the occluder is not the text's own background patch and is not painted before the text.

**Effective paint order.** The wrapper records the actual draw order during the save by wrapping each artist's `draw` call and appending the artist to an ordered list; it does not infer order from `zorder` alone. Ties and figure/axes interleaving use the recorded sequence. If paint order cannot be recorded, any occlusion claim is demoted to medium.

**Medium / UNKNOWN.** Coverage 50–90%; multiple artists jointly cover ≥90%; artist alpha 0.5–0.95 or unknown image opacity; a concave polygon; paint order not recorded or ambiguous; the text has an opaque background of its own that overlaps the candidate occluder.

**Legal counterexamples.** A text bbox background painted **behind** the text (lower paint order); a legend frame covering data points but no supported text; `frameon=False`; a semi-transparent frame over text (→ `UNKNOWN`, not `FAIL`).

### D3 — `overlapping_text`

**Definition.** Two distinct supported text objects have painted regions that overlap enough to impair reading, with no opaque background separating them.

**High-confidence evidence.**

- Both objects are visible; neither has an opaque background patch covering the overlap region;
- the overlap area divided by the smaller source bbox area is ≥ 0.50; and
- at least one aligned character box from each object overlaps the other by ≥ 0.5 pt in both axes.

**Medium / UNKNOWN.** Smaller-box coverage 0.15–0.50; character boxes cannot be aligned; one object has an opaque background patch that covers the overlap region. Rotated text is out of scope (§3.2), not a medium D3 finding. Lines within one multi-line text object are not a pair and do not force `UNKNOWN`; the object remains supported for D1/D2/D4.

**Legal counterexamples.** Bounding boxes touch but rendered ink does not overlap; multi-line lines inside one text object; text separated by an opaque background. Rotated labels with separated ink must be `UNKNOWN`, never `FAIL`, because rotated text is outside v1 scope.

**Class precedence and collateral findings.** D3 is only between two distinct text objects; D2 is text versus an opaque artist. When two rules fire on the same object, the report keeps the highest-precedence class in the order `D1 > D4 > D2 > D3` and records the suppressed class as an evidence note. A single injected mutation must not produce a second high-confidence finding on the same sample; if a collateral defect is found during label review, the sample is either regenerated or all instances are labeled and the sample enters a multi-defect subset with every reference recorded. Such a sample is excluded from the single-instance counts in §5 and reported separately.

### D4 — `missing_glyph`

**Definition.** A character intended to be rendered is absent or rendered as `.notdef` (tofu) in the export.

**High-confidence evidence.**

- The character is absent from the cmap of **every** font in the resolved font stack that Matplotlib actually used for that text object (fontTools, Unicode cmap tables), and no fallback in the stack supplies it; and
- Matplotlib emitted a missing-glyph warning naming that character and the resolved primary font during the actual save; and
- the source text object is visible and aligned under §7.1.

If the wrapper cannot resolve which font file was used for the object, the case is at most medium even when a warning exists.

**Medium / UNKNOWN.** cmap absent but no warning; warning present but the resolved font stack cannot be verified; the warning names a font not in the resolved stack; a fallback font may or may not have supplied the glyph; Type 3 text without Unicode mapping; mathtext or path text.

**Explicitly not evidence.** PDF text extraction containing the character does **not** prove the glyph rendered. The B0 spike rendered U+9F98 with DejaVu Sans, emitted a missing-glyph warning, and PDFium still extracted U+9F98. Extraction presence must not turn a tofu into `PASS`.

**Legal counterexample.** A fallback font in the family list supplies the glyph: no warning is emitted (verified), so the sample is `PASS`.

### 4.1 Sample state aggregation

Priority is fixed:

```
ERROR > FAIL > UNKNOWN > PASS
```

- `ERROR`: invalid input, hash mismatch, renderer crash, timeout, or internal error.
- `FAIL`: at least one high-confidence finding.
- `UNKNOWN`: no high-confidence finding, but at least one medium finding, or text alignment coverage below 0.90, or an empty unit set.
- `PASS`: no findings and text alignment coverage ≥ 0.90; out-of-scope objects may exist but are listed in `unknown_objects` and lower the coverage.

A medium finding never becomes `FAIL`. A `FAIL` may coexist with unknown objects in the JSON; the aggregate state is `FAIL`, but the report must still list the unknown objects and coverage. A sample with zero text units is `UNKNOWN` even if no rule fired.

## 5. Sample inventory

The authoritative inventory is `benchmark/manifest.json`. `benchmark/validate_manifest.py` recomputes the counts; the numbers below were printed by that script on 2026-11-13 and must be re-read from the script if the manifest changes.

**Design rule.** 24 templates, 12 dev + 12 holdout. Each template has one clean sample (seed 1) and four defect variants (`clip`, `occlude`, `overlap`, `missing_glyph`) at seeds 1 and 2. Each template declares a `target_role` (the text object that receives the injected defect); every sample record pins that role. Each defect sample contains exactly one injected defect instance and must be checked for collateral high-confidence defects before sealing. Twelve legal counterexamples (6 dev, 6 holdout) are added. The `samples` array in the manifest enumerates all 228 records with ID, variant, seed, expected state, defect class, target role, and split; the counts below are asserted by the validator rather than inferred from prose.

| Quantity | Value |
|---|---|
| Templates | 24 (12 dev / 12 holdout) |
| Samples per template | 9 (1 clean + 4 defects × 2 seeds) |
| Clean samples | 24 |
| Defect samples | 192 |
| Counterexamples | 12 |
| Total samples | 228 |
| Holdout samples | 114 (12 × 9 + 6) |
| Defect instances | 192 |
| Holdout defect instances | 96 |
| Per defect class, total | 48 |
| Per defect class, holdout | 24 |

The 24 templates cover line, multi-line, vertical/grouped/stacked/horizontal bar, scatter, histogram, box, violin, heatmap, contour, pie, errorbar, log scale, datetime axis, twin axes, stacked area, dense ticks, mixed CJK/English, scientific notation, legend outside, 1×2 subplots, and negative/unit formatting. Rotated text and mathtext are deliberately absent from the inventory because they are out of scope (§3.2); the generator bindings below force D11 and H09 onto plain text. The exact templates and features are in the manifest.

Three templates carry a scope note in the manifest and bind the generator; the validator enforces each binding:

- **D11 (log scale)** must render log tick labels as plain text through `FuncFormatter('{:g}')`. Matplotlib 3.10.8's default log labels are `$\mathdefault{10^{n}}$`, which are unsupported (§3.2); with one such unit per tick the clean sample cannot reach 0.90 coverage. The validator requires `log_ticks_plain_text` plus a `FuncFormatter` `tick_formatter` for every template with a `log_` feature, and rejects the ambiguous `scientific_ticks` feature name.
- **D12 (datetime axis)** uses horizontal date tick labels. Rotated date ticks are out of scope and would push the clean sample below the 0.90 coverage gate; the validator rejects any template feature containing `rotated`.
- **H09 (scientific notation)** must render a plain offset text (`1e3`) with `axes.formatter.use_mathtext = False`. A `$`-bearing offset is unsupported (§3.2) and may not be the target role; the validator requires a `ScalarFormatter(useMathText=False)` `tick_formatter`.

**Generator labels are not ground truth.** The mutation script produces traceable labels (a known object and a known injection), but every holdout sample must be reviewed once against the exported PDF before sealing. If only one person reviews, the project must not claim double annotation or inter-annotator agreement.

**Legal counterexamples.** L01–L12 cover white label backgrounds, legends over data but not text, touching bboxes with separated ink, rotated bbox overlap with separated ink (expected `UNKNOWN`, not `FAIL`, because rotated text is out of scope), legal near-edge text, a semi-transparent frame over text (expected `UNKNOWN`), white labels on a heatmap, frameless legend over data, a colorbar label near but not overlapping ticks, an axis label outside the axes but inside the page, tight-bbox expansion, and multi-line line spacing.

## 6. Holdout protocol (frozen before detector development)

1. **Family split.** The split is by template family (template ID), never by sample. Dev and holdout are fixed in the manifest. Similarity groups (e.g. line charts on both sides) are recorded; the holdout is not claimed to be statistically independent.
2. **Generation and seal.** Dev samples may be generated and inspected freely at B1. Holdout samples are generated at B2 by a separate generation script (`benchmark/generate_holdout.py`, created at B2) in a separate process and written to `benchmark/holdout/` (git-ignored). **Before generation, the detector code, every threshold, and the evaluation script are frozen and tagged**; that revision is recorded in the seal. The committed `benchmark/holdout/seal.json` records each sample's sha256 and size, the generator script hash, the frozen detector and evaluation revisions, the label-review log hash, and the generation environment; it does **not** contain labels. Labels live in `benchmark/holdout/labels.json` (git-ignored) and their sha256 is recorded in the seal.
3. **No tuning on holdout.** No parameter selection, rule threshold, prompt, or code change may use holdout outputs or labels. The dev set is the only development signal. Because the detector is frozen before the label-review session of item 5, a label correction cannot feed back into detector code for this prereg version.
4. **One unseal per prereg version.** At B3, before running the evaluation, the seal is verified, the frozen detector and evaluation-script revisions are checked against the seal, and the unsealing is logged with a UTC timestamp. The holdout is then run once.
5. **Label review and corrections.** Before sealing, the project owner acts as the **label reviewer**: they open the holdout PDFs and the machine-generated candidate labels in one logged session, solely to correct a wrong expected state or target unit. Every correction is recorded in `benchmark/holdout/label_review_log.json` (git-ignored) as sample ID, old label hash → new label hash, reason code, and UTC timestamp; the log hash goes into the seal and the log contains no label text. The reviewer must not run the detector on holdout inputs during this session. This session is the **only** permitted pre-seal opening of holdout files; opening them at any other time burns the holdout under item 6. After sealing, a label change requires a new prereg version and a full rerun. No sample may be moved to "unsupported" after seeing results.
6. **Accidental inspection burns the holdout.** Any opening of a holdout sample or label file outside the logged label-review session of item 5, or any detector run on a holdout input before the B3 unseal, burns the holdout: it is moved to dev-only use, a new seed/template set is generated, and a new prereg version is written. The project must report the burn. Filesystem auditing is not available, so this remains a procedural rule; the label-review log and the seal are the only recorded evidence.
7. **Crash and partial-run rule.** A run that crashes before writing any predictions file may be rerun once with the same seal; the crash, timestamp, and environment are logged. Once a predictions file exists, a rerun requires a new prereg version and the first result stands.
8. **Custodian limitation.** For v1 the project owner is the only custodian, the label reviewer, and the detector author. The seal is a procedural commitment verified by hashes and timestamps, not access control; no independent custodian exists. The limited claim is: the detector revision was frozen before the label-review session, no detector run touched holdout inputs before the B3 unseal, and the label-review log and correction hashes are recorded. It is **not** a claim of blindness or independent annotation. Results must say so.
9. **No independence overclaim.** Synthetic templates, shared fonts, and shared code mean the holdout measures generalization across templates, not across the real world. Report this limitation with every result.

## 7. Evaluation units, matching, and deduplication

**Reference defect instance.** A tuple `(sample_id, defect_class, source_object_id)`. A sample may contain more than one instance; v1 generators inject one.

**Finding.** A JSON object with at least: `sample_id`, `defect_class`, `rule_id`, `source_object_id` (nullable), `confidence` (`high`/`medium`), `state` (`FAIL`/`UNKNOWN`), `page`, `box_pdf_points`, `source_text`, `evidence`, `renderer_version`, `input_sha256`.

**Matching.**

- A finding matches a reference if they share `sample_id` and `defect_class`, and either the `source_object_id` is equal, or the finding has no source ID and the IoU of its box and the reference instance's source-object box, transformed to PDF points under §2, is ≥ 0.50.
- One finding matches at most one reference; choose the highest IoU. One reference is matched by at most one finding.
- A reference with no matching finding is a miss, even if the sample state is `UNKNOWN` or `ERROR`. Misses stay in the recall denominator.
- Findings on objects declared out of scope before the run are reported separately and excluded from precision/recall denominators. Adding an object to "out of scope" after seeing results is forbidden.
- Duplicate findings for the same reference count as one TP; any extra non-identical finding for that reference is a false positive. Byte-identical duplicates are collapsed by the key `(sample_id, defect_class, source_object_id, rule_id, box rounded to 0.1 pt)`.
- A finding with `confidence=medium` is not a TP or FP for precision; it forces the sample to at least `UNKNOWN` if no high-confidence finding exists.

**Precision denominator.** All high-confidence findings on supported objects in the holdout, including findings on clean samples and counterexamples. If the denominator is zero, precision is **undefined and the gate fails** (a silent detector cannot pass by returning nothing).

**Recall denominator.** All reference defect instances in the preregistered supported holdout (96). `UNKNOWN`/`ERROR` misses stay in the denominator. A conditional recall on the decidable subset may be reported separately, but never used for the release gate.

### 7.1 Source-to-PDF text alignment

Alignment runs once per sample, before any defect rule. It maps each supported **source unit** to PDF character boxes. D1, D2, D3, D4 and the coverage metric use only aligned units, so this procedure is part of the contract, not an implementation detail.

**Unit.** One Matplotlib `Text` object (including `Annotation`, tick labels, offset text, legend labels, colorbar labels, `Figure.text`) that is visible (`get_visible()` true, text and artist alpha > 0), has non-empty `get_text()` after strip, and has rotation exactly 0.0° as recorded at draw time. A multi-line string is one unit: Matplotlib draws its lines inside one artist draw call, so its characters are contiguous in content order. Units whose text contains `$` (mathtext) or whose rotation is nonzero are **unsupported**: they go to `unknown_objects` and stay in the coverage denominator. Unit ID is the deterministic artist-traversal index recorded by the wrapper.

**Canonical form.** Apply a per-character map to both sides: Unicode whitespace → U+0020; otherwise `NFKC(c)` if it is exactly one character, else `c` unchanged. No case folding, no deletion, no ligature expansion. Canonical strings therefore have the same length as their originals, and every PDF character keeps its char index.

**Candidates.** Take the PDF text page's characters in char-index order. For a unit, a candidate is a contiguous span `[i, j)` whose canonical string equals the unit's canonical string, with `j − i` equal to the unit's canonical length. A candidate is valid only if:

- its span bbox (union of the char boxes) has `IoU ≥ 0.50` with the unit's source bbox transformed into PDF points (§2); and
- `median(char box height) / font size in points ∈ [0.20, 1.50]`.

**Reason precedence.** A unit with no valid candidate is unaligned with exactly one reason: `no_text_match` if no span has the same canonical text; `height_mismatch` if equal-text spans exist but none satisfies the height band; `low_overlap` if equal-text spans satisfy the height band but none reaches IoU 0.50. A unit that has valid candidates but loses every one of them in assignment is `conflict`.

**Assignment.** Sort all valid `(unit, span)` pairs by `(IoU descending, unit ID ascending, span start ascending)` and assign greedily; a pair is accepted only if neither the unit nor the span is already assigned. One unit maps to at most one span, one span to at most one unit. This is deterministic and does not depend on iteration order of dictionaries.

**Ambiguity.** A unit is unaligned with reason `ambiguous` if, after assignment, either:

- another span with the same canonical text — assigned or not — has all four bbox edges within 1.0 pt of its assigned span (two indistinguishable instances at the same place); or
- its two best valid candidates have bbox centers within 2.0 pt of each other and IoU values differing by less than 0.02 (geometry cannot break the tie).

Ambiguous units are removed from the assignment and count as unaligned. Their assigned spans are removed with them and are not reassigned; no second pass runs. This is conservative: an ambiguity can only lower coverage.

**Unaligned reasons.** `no_text_match`, `height_mismatch`, `low_overlap`, `ambiguous`, `conflict`, `unsupported_rotated`, `unsupported_mathtext`. Each is recorded with the unit ID in `unknown_objects`.

**Coverage.** For one sample, `coverage = aligned_units / total_units`, where `total_units = aligned_units + unaligned_units + unsupported_units`. `unaligned_units` is the sum of the five supported-reason counts (`no_text_match`, `height_mismatch`, `low_overlap`, `ambiguous`, `conflict`); `unsupported_units` is the sum of `unsupported_rotated` and `unsupported_mathtext`. The denominator includes unsupported and unaligned units; the numerator includes only units assigned without an ambiguity. The report records all four counts plus `unaligned_by_reason`, so the ratio is recomputable (§11). The §8 metric is the macro-average of this ratio over holdout samples that have at least one unit; samples with zero units are excluded from the macro-average, counted and reported separately, and are always `UNKNOWN` (§3.2). A sample below 0.90 is `UNKNOWN`.

**Use of evidence.** D1's boundary test, D2's character-box coverage, D3's pairwise character-box overlap, and D4's per-character evidence use only aligned character boxes. An unaligned unit may still produce the `D1` medium case ("whole source bbox outside the page, no aligned char box"), but never a high-confidence finding.

**Determinism.** All geometry is float64 PDF points; decisions use unrounded values, and rounding to 0.1 pt happens only for report display and duplicate keys (§7). There is no randomness. Changing this algorithm changes the result and therefore requires a new prereg version once the holdout exists.

## 8. Metrics and release gates

All metrics are computed on the sealed holdout. Wilson intervals are reported for every proportion but are **descriptive only**, because samples cluster inside 12 templates; the template-cluster bootstrap below is the uncertainty statement that must accompany any result.

| Metric | Definition | Gate |
|---|---|---|
| High-confidence precision | matched high-confidence findings / all high-confidence findings | ≥ 0.95 |
| End-to-end recall | matched reference defects / all 96 reference defects | ≥ 0.80 |
| Sample-level UNKNOWN rate | holdout samples with state UNKNOWN / 114 | ≤ 0.20 |
| Sample-level ERROR rate | holdout samples with state ERROR / 114 (valid inputs only) | ≤ 0.05 |
| Text alignment coverage | macro-average over holdout samples with at least one unit of `aligned_units / total_units`, where `total_units = aligned + unaligned + unsupported` (§7.1); zero-unit samples are excluded from the macro-average, counted separately, and are `UNKNOWN` | ≥ 0.90 |
| Clean/counterexample behaviour | holdout clean and counterexample samples (18) that end in `PASS`; none may end in `FAIL` | ≥ 16/18 PASS and 0 FAIL |
| Incremental value over the strongest fair baseline | end-to-end recall at precision ≥ 0.95, minus baseline B's best recall on the same holdout whose own precision is ≥ 0.95 (§9) | ≥ +0.10 absolute; or ≥ +0.05 with the UNKNOWN rate not worse by more than 0.05 |
| False positives per page | high-confidence FP findings / pages (one page per sample) | report only; precision is the gate |
| Runtime | CPU wall-clock per sample, median and p95 over 3 runs | report only; no speed claim without a measured baseline |

If no holdout sample has at least one text unit, coverage is undefined and the coverage gate fails; it cannot pass by having nothing to measure.

**Baseline sweep.** Baseline B's two thresholds are swept over a fixed grid — page margin {0, 0.5, 1, 2} pt and source-bbox overlap ratio {0.15, 0.30, 0.50, 0.75} — and its strongest point at precision ≥ 0.95 is used for the delta. The grid is fixed here, before holdout generation. If no baseline point reaches precision ≥ 0.95, the baseline is reported as having no admissible operating point and the delta gate is failed, not skipped.

**Uncertainty.** Resample the 12 holdout template families with replacement and, independently, the 6 holdout counterexamples with replacement; 10,000 draws, RNG seed 0. A drawn family contributes **all** of its samples as one block — its clean sample and its eight defect samples — so the clean sample travels with its family and samples are never resampled independently within a family. A family drawn k times contributes k copies; a counterexample drawn k times contributes k copies (multiplicity counts). Recompute each statistic from the drawn observations, never from an average of per-family ratios:

- precision = pooled matched high-confidence findings / pooled high-confidence findings;
- recall = pooled matched references / pooled references;
- UNKNOWN rate = pooled UNKNOWN samples / pooled samples;
- ERROR rate = pooled ERROR samples / pooled samples;
- coverage = arithmetic mean of the per-sample ratios defined in §7.1 over drawn samples with at least one unit (each drawn sample, including duplicate draws, counts once; zero-unit samples are excluded);
- clean/counterexample gate = pooled PASS and FAIL counts over the drawn clean samples and counterexamples.

Counterexamples contribute to precision, the UNKNOWN/ERROR rates, coverage, and the clean gate, but not to recall because they contain no references. If a draw has a zero denominator for a statistic, that statistic is marked undefined for the draw and excluded from its percentile range; the number of undefined draws is reported. Report the 2.5–97.5 percentile range next to every gate verdict. The gates are evaluated on point estimates, as preregistered, and no significance claim is made from these data.

**Reporting rules.**

- Report per-class precision/recall and pooled numbers. Do not pool classes to hide a weak class.
- Report both end-to-end recall and conditional-on-decidable recall; the gate uses end-to-end only.
- Report UNKNOWN and ERROR relative to all holdout samples, not only the decidable subset.
- With 24 reference instances per class (12 templates × 2 seeds), class-level intervals are wide; class-level numbers are descriptive, the pooled gate is binding, and no class-level performance claim may be made from this benchmark.
- Never convert `UNKNOWN` to `PASS` to improve a score. Never exclude a hard sample after seeing results.
- The gates are conjunctive: all must hold. No composite score.

**Status of the gates.** These are initial product gates, not measured results. They may be revised only by a new prereg version before holdout unsealing, with the reason recorded.

## 9. Baselines

Baselines get the same inputs, fonts, page size, DPI, and source manifest. No baseline is given a deliberately bad configuration.

| Baseline | What it does | What it can detect |
|---|---|---|
| A. Matplotlib warnings | captures missing-glyph and layout warnings from the same save | D4 only; no geometry |
| B. Source-bbox rules | flags text outside the page and pairwise bbox overlap using source coordinates only, without PDF confirmation | D1/D3 candidates; expected false positives on legal bboxes |
| C. Layout mitigation | re-renders with `constrained_layout` and (where applicable) adjustText, then checks whether the defect remains | mitigation rate, not a detector |
| D. Diff against a clean baseline | pixel/PDF diff when a clean export of the same figure exists | changed regions only; not applicable without a baseline |

**Which baseline counts.** Baseline B is the strongest fair detector baseline, because it sees the same source geometry and can be thresholded. The delta gate in §8 is measured against B only. Baseline A is a lower bound (D4 only, layout warnings only) and is reported for context. Baseline C measures mitigation, not detection, and cannot enter a precision/recall delta. Baseline D requires a clean export that the evaluated sample does not have; its "not applicable" is reported, not treated as a zero.

## 10. Stop rule

The full-format route stops if **two recorded algorithm iterations** fail to produce a useful gain over baseline B. A useful gain is one of:

- +0.10 absolute end-to-end recall at precision ≥ 0.95; or
- +0.05 absolute recall with the UNKNOWN rate not worse by more than 0.05.

**What counts as an iteration.** One recorded algorithm iteration is a numbered change to the detector's decision logic (rule, threshold, alignment, or evidence aggregation) that is committed with its dev-set result and its diff, after which the dev-set metrics are recomputed. Re-running the same code, changing only comments, refactoring without changing behaviour, adding templates, or regenerating samples with the same seeds does not count. At most two such iterations may be spent trying to beat baseline B; the second failed attempt triggers the stop.

**Development data.** Iteration decisions use only the dev split: 12 templates, 108 dev samples, 96 dev defect instances, and the 6 dev counterexamples. Holdout samples are not generated until B2 and are never used to choose a parameter (§6). The benchmark composition is fixed in §5; adding templates or classes after an iteration starts requires a new prereg version.

If the rule triggers, keep the benchmark/plugin or contribute the rule upstream; do not keep expanding formats to chase a launch. The stop decision and its evidence are recorded in the handover. No amount of growth pressure justifies turning `UNKNOWN` into `PASS`.

## 11. Report and evidence contract

Every run writes a JSON report and, optionally, a local HTML report.

**JSON (minimum fields).**

```
schema_version, tool_version, input_sha256, source_manifest_sha256,
matplotlib_version, pdfium_version, page_count, page_size_pt, rotation,
overall_state (PASS|FAIL|UNKNOWN|ERROR),
coverage {total_units, aligned_units, unaligned_units, unsupported_units,
          unaligned_by_reason {reason: count}, ratio},
zero_unit_samples,
findings [ {rule_id, defect_class, source_object_id, confidence, state,
            page, box_pdf_points, source_text, evidence, reason} ],
unknown_objects [ {source_object_id, reason} ],
errors [ {stage, message} ],
timing {wall_ms}
```

`coverage.total_units = aligned_units + unaligned_units + unsupported_units`. `unaligned_by_reason` records all seven reasons listed in §7.1: its five supported-failure keys sum to `unaligned_units`, and its two `unsupported_*` keys sum to `unsupported_units`. `ratio = aligned_units / total_units`; it is `null` exactly when `total_units = 0`, in which case the sample is `UNKNOWN`, is excluded from the §8 macro-average, and increments the run-level `zero_unit_samples` count. A reader must be able to recompute `ratio` from the counts; a report whose counts do not add up is invalid and its sample state is `ERROR`.

Each finding must be reproducible from the input hash, tool version, and renderer version. The HTML report is local-only, escapes all source text, embeds crops as data URIs (no remote assets), and shows coverage and unknown objects next to findings. A `PASS` with coverage below the gate is not allowed: the state becomes `UNKNOWN`.

## 12. Security and privacy

- Local processing only; no telemetry, no network, no remote fonts or scripts in the report.
- PDFs are untrusted: page-count, page-size, render-pixel, and wall-clock limits; render subprocess timeout kills only its own PID. A normal subprocess is not claimed to be a strong sandbox.
- PDFium calls are serialized in-process; parallelism only across processes.
- Reports may contain private text; the user must review before sharing. The project does not upload reports.
- No arbitrary-path HTTP server, no filesystem crawling, no execution of code embedded in input files.

## 13. B0 acceptance checklist

| Check | Evidence | Status |
|---|---|---|
| PDFium text/char-box/bitmap pipeline works | `spikes/b0_pdfium_spike.py`, `artifacts/b0/api-spike.json`, render PNG | PASS (14/14 checks) |
| Fonttype-42 CJK extraction verified | `fonttype_42.inspection`, `ascii_and_cjk_text_extractable` | PASS |
| Fonttype-3 limitation verified | `fonttype_3.inspection`, `fonttype3_loses_cjk_extraction` | PASS (limitation recorded) |
| Missing-glyph evidence rule verified | `missing_glyph_probe`, cmap + warning + extraction-presence checks | PASS (rule corrected by evidence) |
| Dependency licenses verified from installed wheels | `docs/DEPENDENCY_LICENSES.md`, including Pillow (MIT-CMU) | PASS |
| 24-template / 228-sample per-sample inventory frozen | `benchmark/manifest.json`, `benchmark/validate_manifest.py` | PASS (13 count lines plus `MANIFEST PASS`) |
| Source-to-PDF alignment algorithm frozen | this document, §7.1 | PASS (candidate; review pending) |
| Holdout rules, matching, metrics, gates frozen | this document, §6–§10 | PASS (candidate; review pending) |
| Spike reproducible from a clean checkout | pinned font via `spikes/fetch_b0_font.py`; 14/14 checks; evidence written only on pass | PASS |
| Package import does not pull heavy stack | subprocess isolation test in `tests/test_package.py` | PASS (3 passed in `.venv`) |
| Detector code not started | `plotproof/__init__.py` is a version stub | PASS (by design) |
| Independent read-only review | `docs/reviews/B0_REVIEW.md` and project handover | PENDING (round 4 of tag `b0-freeze-r4`) |

## 14. Known limitations

- Only Windows 11 + Python 3.12.3 + Matplotlib 3.10.8 + PDFium 149.0.7825.0 is verified. Other versions may change char boxes or text extraction; results are pinned to the recorded versions.
- The benchmark is synthetic and small. 228 samples and 96 holdout defect instances are enough for initial gates, not for a claim about real-world figures.
- The holdout is a template-family split, not an independent random sample. Line charts and shared fonts appear on both sides.
- Text extraction is not rendering evidence. A character can be present in the PDF text stream while its glyph is missing.
- Bounding-box intersection is not occlusion. v1 requires an opaque artist, a later recorded paint order, and ≥90% coverage; semi-transparent cases remain `UNKNOWN`.
- Rotated text (rotation not exactly 0.0°), mathtext, path text, multi-page PDFs, and arbitrary PDFs are out of scope. Such units stay in the coverage denominator and can only force `UNKNOWN`; they are never silently dropped to raise coverage.
- Alignment failure modes are visible, not hidden. Supported units that fail alignment are recorded as `no_text_match`, `height_mismatch`, `low_overlap`, `ambiguous`, or `conflict`; units excluded by scope are recorded as `unsupported_rotated` or `unsupported_mathtext`. All of them stay in the coverage denominator, and coverage < 0.90 forces `UNKNOWN` for the figure. A detection bug that drops source units therefore cannot turn into a `PASS`.
- Two dev counterexamples are expected `UNKNOWN` by design: L04 (rotated annotation) and L06 (semi-transparent occlusion). The six holdout counterexamples are expected `PASS`. A detector that labels either group `FAIL` fails the clean/counterexample gate.
- Holdout samples are not generated at B0. Only the split, sealing rules, and label expectations exist; the sealed files are produced at B2 and never tuned against.
- Font availability changes results. CJK samples require an OFL CJK font; proprietary fonts are excluded from public artifacts.
- Pillow is a direct runtime dependency (MIT-CMU) used for pixel crops and PNG evidence; Matplotlib already requires it, and the dependency is recorded rather than assumed transitive.
- No real user, star, or time-saving claim exists yet. B4 requires external minimal cases; if none are obtained, the handover must say so.

## 15. Change control

- Typo and clarification edits are allowed with a version bump and a changelog line; they must not change semantics.
- The reviewed revision is pinned by `docs/B0_FREEZE.sha256` and the `b0-freeze-r4` tag. Editing any pinned file invalidates that freeze; a re-review requires a new tag and a new freeze manifest.
- Any change to defect definitions, support scope, split, matching, metrics, or gates after holdout generation requires a new prereg version and a full rerun. Old results are archived, not deleted.
- The sealed holdout is unsealed at most once per prereg version. The unsealing timestamp, evaluation script hash, and input seal hash are recorded.
- If a gate fails, the result is published as a failure. The project may iterate on the dev set and rerun a new prereg version, but may not relabel the holdout to pass.

## 16. Sources

- Project handover, P2 sections 8–9 (`OPEN_SOURCE_PROJECTS_HANDOVER.md`): product boundary, PDFium license/threading constraints, four-state contract, B0–B4 milestones.
- [Matplotlib constrained layout guide](https://matplotlib.org/stable/users/explain/axes/constrainedlayout_guide.html) — existing layout mitigation and its limits.
- [pypdfium2 repository](https://github.com/pypdfium2-team/pypdfium2) — bindings, license metadata, PDFium threading and object-lifetime constraints.
- [PyMuPDF About](https://pymupdf.readthedocs.io/en/latest/about.html) — AGPL/commercial dual licensing; reason PyMuPDF is excluded from the MIT runtime.
- Installed wheel metadata (read on 2026-11-13): `matplotlib-3.10.8.dist-info/LICENSE`, `pypdfium2-5.8.0.dist-info/licenses/`, `fonttools-4.61.1.dist-info/licenses/LICENSE`, `numpy-2.4.6.dist-info/licenses/LICENSE.txt`, `pillow-12.2.0.dist-info/licenses/LICENSE`.
- [Noto CJK fonts](https://github.com/notofonts/noto-cjk) — Noto Sans CJK SC, OFL-1.1; font sha256 recorded in §0.
- `artifacts/b0/api-spike.json` — machine-readable B0 evidence, generated by `spikes/b0_pdfium_spike.py`.
- `benchmark/manifest.json` — authoritative sample inventory; counts validated by `benchmark/validate_manifest.py`.

*This document is a preregistration, not a report of achieved performance. Any later claim of precision, recall, coverage, speed, adoption, or stars must cite a fresh, reproducible measurement and state its sample size and limitations.*
