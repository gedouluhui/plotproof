# PlotProof

**A source-assisted export checker for Matplotlib figures.** It will capture what a figure intends to draw at save time, compare that record with the rendered PDF, and explain what went wrong — or say `UNKNOWN` when the evidence is not strong enough.

> **Status: B0 design freeze (2026-11-15).** There is no detector, no installable release, and no benchmark result yet. This repository currently contains a reproducible feasibility spike, a frozen benchmark manifest, a preregistration, and a version stub. Nine independent review rounds are recorded in [`docs/reviews/B0_REVIEW.md`](docs/reviews/B0_REVIEW.md); round 9 returned REJECT, its fixes are frozen on tag `b0-freeze-r10`, and the round-10 re-review of that tag is pending. Claims below describe the v1 design, not shipped behavior.

## The problem

A Matplotlib figure can fail quietly:

- a long axis label is clipped at the page edge;
- a legend is drawn on top of data or text;
- labels from different artists collide;
- a CJK character has no glyph, so the PDF shows a blank or a box — while the text layer still contains the original character.

Checking the PDF text layer alone cannot prove that a glyph was drawn. Rasterizing alone cannot tell which pieces of text were meant to be there. PlotProof's plan is to use **both**: a source manifest captured inside Matplotlib, and render evidence from PDFium.

## What v1 will check

| ID | Defect class | Source-assisted evidence |
|---|---|---|
| D1 | `clipped_text` | an aligned character box with positive area has at least half its area outside the page, or its centre strictly outside; zero-area PDFium boxes (CR/LF, tick-separator spaces) are ignored |
| D2 | `occluded_text` | an artist with effective alpha `α_eff ≥ 0.95` (`facecolor` alpha × artist alpha), painted after the text, covers at least 90% of the text's painted character boxes |
| D3 | `overlapping_text` | two text objects' painted character boxes overlap enough to impair reading, with no opaque background separating them |
| D4 | `missing_glyph` | a character is absent from every resolved font in the stack and Matplotlib emitted a missing-glyph warning naming it |

Only high-confidence evidence produces `FAIL`. Medium-confidence evidence forces `UNKNOWN`; low-confidence evidence is not reported. Results are `PASS`, `FAIL`, `UNKNOWN`, or `ERROR`, with priority `ERROR > FAIL > UNKNOWN > PASS`.

## What it will not do

- It is not a general PDF checker. Arbitrary, multi-page, rotated, or non-wrapper PDFs are rejected in v1.
- Rotated text and mathtext are recorded as unsupported units and force `UNKNOWN`; path-only text is outside the source model and is not claimed checked; multi-page PDFs are rejected as `ERROR`.
- It does not guess a crop. A `bbox_inches='tight'` export is supported only through the origin the wrapper records at save time; without it the coordinate transform is undefined and the result is `UNKNOWN`.
- It is not a semantic or aesthetic judge: it does not check whether the chart's message is true or whether the colors look good.
- It is not an ML model. The core is deterministic text and geometry evidence.
- `PASS` means "no supported defect was found with sufficient coverage", not "the figure is correct".
- It will not claim real-world accuracy before the preregistered benchmark and a sealed holdout have been run.

## B0 evidence (verified, not a detector)

The feasibility spike `spikes/b0_pdfium_spike.py` ran on the development machine and passed 14/14 checks. Machine-readable output: [`artifacts/b0/api-spike.json`](artifacts/b0/api-spike.json). Rendered example: [`artifacts/b0/api-spike-render.png`](artifacts/b0/api-spike-render.png).

Two further owner-run probes back the round-8 fixes: [`spikes/b0_d1_boundary_probe.py`](spikes/b0_d1_boundary_probe.py) checks the single D1 boundary predicate on three pinned fixtures and passed 39/39 (output [`artifacts/b0/d1-boundary-probe.json`](artifacts/b0/d1-boundary-probe.json); re-run for round 9 with the corrected fixture docstring); [`spikes/b0_validator_bypass_repro.py`](spikes/b0_validator_bypass_repro.py) runs four mutations against the round-7 validator and records that all four were accepted with exit 0 while a fifth (a state flip) was rejected — the reproduction of the round-8 validator finding, output [`artifacts/b0/validator-bypass-repro.json`](artifacts/b0/validator-bypass-repro.json). That repro deliberately refuses to run once the validator at HEAD contains the fixed checks, so it documents the round-8 finding rather than re-running on the current tree. The validator itself is pinned by [`tests/test_manifest_mutations.py`](tests/test_manifest_mutations.py): 47 on-disk mutations, each required to fail with its exact diagnostic text, plus six passing controls (56 tests in the whole suite).

Facts the probes established:

- Matplotlib `pdf.fonttype=42` keeps CJK text and character boxes extractable through PDFium (76 characters, 50 non-whitespace, in the test page).
- With `pdf.fonttype=3`, ASCII remains extractable but the CJK title is not — so v1 must return `UNKNOWN`, never a text-based `FAIL`, in that case.
- A missing glyph (U+9F98 in DejaVu Sans) triggers a Matplotlib warning and is absent from the font cmap, **but the character is still present in the PDF text layer**. Text extraction is therefore not rendering evidence; D4 requires the cmap and warning evidence instead.
- Under `pdf.fonttype=3`, PDFium drops U+2212 from extraction (`−1500` is read as `1500`); ASCII U+002D survives under both type 3 and type 42. The benchmark therefore freezes ASCII minus labels and pins `pdf.fonttype=42` in the manifest's `save_binding`.
- A character absent from both benchmark fonts (U+20000) is dropped from extraction under fonttype 42, unlike U+9F98; the alignment rule matches the remaining characters (measured span-vs-source-bbox IoU 0.7045).
- PDFium returns zero-area character boxes for CR/LF and for the spaces that separate x tick labels (measured: 2 of 125 characters on a title-only fixture, 21 of 180 on an axes with six tick labels and a title). D1 keys on positive-area boxes only, so whitespace can never make a text object "clipped".
- A fallback font stack suppresses the missing-glyph warning.
- On the recorded environment and font, identical input produced byte-identical PDFs (`sha256 0800e869b86f66c671e8ccf94c7a3ae15ac25a576291ab5ca0ecb62165fd820a`). Bytes may change with Matplotlib, PDFium, or font versions, so reproducibility is claimed only for the pinned environment.

The CJK part of the spike uses Noto Sans CJK SC (OFL-1.1), pinned in the prereg by sha256; proprietary Windows fonts are not used in public artifacts.

The frozen benchmark inventory is [`benchmark/manifest.json`](benchmark/manifest.json), validated by [`benchmark/validate_manifest.py`](benchmark/validate_manifest.py): 24 templates (12 development, 12 holdout), 228 samples, 192 defect instances, 96 of them in the holdout, 24 per defect class in the holdout. The manifest lists every sample with its variant, seed, split, expected state, and target role. Every sample is captured under one `save_binding` — Matplotlib 3.10.8, Agg, `pdf.fonttype=42`, 100 dpi, 10 × 6 in, 10 pt, constrained layout, `axes.unicode_minus=False`, `transparent=False` — because type 3 drops U+2212 from extraction and the dense-tick template's overlap geometry is figure-size dependent. The 10 × 6 size is retained as the global save binding, and the generator's clean check — no page clipping, and no D3 candidate with smaller-box coverage ≥ 0.15 — is the certifying measurement for H07's label spacing. The round-7 and round-8 per-size coverage table is withdrawn in v1.6: its probe fixed only the forty x ticks, not the rest of the figure, and constrained layout makes the decimals construction-dependent. No figure size is claimed safe or unsafe without that executable check. Every template's axis and colorbar labels are bound to horizontal text (`rotation=0`, `labelpad=4.0`) with fixed alignment: left y-labels `ha='right'`, right (twin) y-labels `ha='left'`, figure-level shared y-labels `ha='left'` under constrained layout. H07's exact forty-tick binding and H12's thousands-separator formatter are pinned in the manifest and enforced by the validator. Matplotlib's default vertical y-label is rotated text, which v1 records as unsupported and forces `UNKNOWN`; a horizontal label with the default centre alignment overlaps its tick column (measured smaller-box coverage 0.214 on the left label, 0.607 on the twin label — a high-confidence `D3` `FAIL`), and a shared label with centre alignment runs off the left page edge. The holdout split is frozen at B0; the holdout samples themselves are generated and sealed at B2. **No samples have been generated yet.**

The evaluation design — input contract, defect definitions, holdout protocol, matching rules, gates, baselines, and the stop rule — is frozen in [`docs/B0_PREREGISTRATION.md`](docs/B0_PREREGISTRATION.md) before any detector code. Two dev counterexamples (a rotated-label case and a semi-transparent occluder) are labeled `UNKNOWN` by design; they must never become `FAIL`. The occluder's construction is pinned in the manifest (`facecolor_alpha` 0.5 × `artist_alpha` 1.0, effective alpha 0.50) and enforced by the validator, so a drift to an opaque fill is rejected before any detector exists that could mislabel it. The six holdout counterexamples are all expected `PASS`.

### Reproducing B0

Requires Python 3.12 on Windows (the verified environment). From the repository root:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python spikes\fetch_b0_font.py
.venv\Scripts\python spikes\b0_pdfium_spike.py
.venv\Scripts\python spikes\b0_d1_boundary_probe.py
.venv\Scripts\python spikes\b0_validator_bypass_repro.py
.venv\Scripts\python benchmark\validate_manifest.py
.venv\Scripts\python -m pytest
```

`fetch_b0_font.py` downloads the pinned Noto Sans CJK SC file into `.fonts/` (git-ignored) and refuses to proceed if its size or sha256 differs from the pin. The spike refuses to run without that exact file, writes evidence only when all 14 checks pass, and writes `api-spike-FAILED.json` otherwise. The font URL is recorded in `docs/B0_PREREGISTRATION.md` §0.

## Planned workflow (not implemented)

The B1 API is not written yet. The intended shape is:

```python
import matplotlib.pyplot as plt
import plotproof

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [2, 1, 3])
ax.set_xlabel("a very long label that might be clipped")

report = plotproof.save_and_check(fig, "figure.pdf")  # planned, not available yet
print(report.state)  # "PASS" | "FAIL" | "UNKNOWN" | "ERROR"
```

The report will carry the captured source manifest, the findings with evidence, the checker version, and the renderer version. This snippet is a design sketch; it will not run against the current stub package.

## Roadmap

| Milestone | Content | Status |
|---|---|---|
| B0 | support scope, defect definitions, sample inventory, holdout and metric freeze, licence audit, PDFium spike | design frozen; nine review rounds recorded (round 9 returned REJECT); the round-9 fixes are frozen on tag `b0-freeze-r10`, round-10 re-review pending |
| B1 | deterministic checker core for D1–D4, dev split only | not started |
| B2 | baseline comparison and threshold calibration on the dev split | not started |
| B3 | one sealed holdout run, preregistered report | not started |
| B4 | documentation, examples, release | not started |

B1 work will not begin until the B0 review is recorded.

## License

MIT. Dependency and font licenses are recorded in [`docs/DEPENDENCY_LICENSES.md`](docs/DEPENDENCY_LICENSES.md) and summarized in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). PyMuPDF/MuPDF is deliberately excluded because it is AGPL/commercial.

## 中文摘要

PlotProof 要解决的是 Matplotlib 出图时的“静默失败”：轴标签被页边裁掉、图例压住数据、文字互相遮挡、中文缺字变成空白或方框。它不是通用 PDF 检查器，也不是审美评分器，而是一个**源码辅助**的导出检查器：在保存时记录文字、几何与样式，再用 PDFium 对导出的单页 PDF 做比对，输出带证据的 `PASS / FAIL / UNKNOWN / ERROR`。

当前仓库处于 **B0 设计冻结阶段**：尚未实现检测器，没有可安装版本，也没有任何准确率或用户数据。预登记文档已更新到 v1.6：第九轮独立审查给出 REJECT（2 个阻断项 + 6 个次要项，逐条复现与处置记录在评审日志中），修复冻结在 `b0-freeze-r10` 标签上，第十轮复审待进行。已完成的是可复现的可行性 spike（14/14 项检查通过）、D1 边界判据探针（39/39）、校验器变异套件（47 条变异 + 6 组对照，全套 56 项测试）、228 个样本的冻结清单、以及写死在代码之前的预登记文档。基准样本尚未生成，保留集尚未解封。D1 只认面积为正的字符框，PDFium 给 CR/LF 和刻度分隔空格返回的零面积框一律忽略（实测标题页 125 字符中有 2 个、带六个刻度标签的坐标轴 180 字符中有 21 个），否则空白字符会把自己"判成"被裁。水平文字的对齐方式也已写死：左侧 y 轴标签 `ha='right'`、右侧（twin）标签 `ha='left'`、整图共享标签 `ha='left'` 配合 constrained layout、`labelpad=4.0`；默认居中方案实测与刻度标签重叠（覆盖率 0.214 / 0.607），共享标签还会跑出页面左边。保存绑定同时写死 `transparent=False`、`pdf.fonttype=42` 与 10 × 6 英寸；H07 的标签间距改由生成器的可执行干净检查认证（无页面裁切、且不存在小框覆盖率 ≥ 0.15 的 D3 候选），第七、八轮的分尺寸覆盖率表在 v1.6 中撤销（该探针只固定了四十个 x 刻度，未固定图的其余部分，constrained layout 下小数随构造而变）。D2 的"不透明"定义为 `α_eff = facecolor alpha × artist alpha ≥ 0.95`；半透明反例的构造（0.5 × 1.0 = 0.50）已钉进清单并由校验器强制，不可能漂移成 `FAIL`。`bbox_inches='tight'` 导出依赖保存时记录的裁切原点，缺失即 `UNKNOWN`，绝不猜裁切。依赖与字体许可已逐项核验，PyMuPDF（AGPL/商业双授权）被明确排除。
