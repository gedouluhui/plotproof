# PlotProof

**A source-assisted export checker for Matplotlib figures.** It will capture what a figure intends to draw at save time, compare that record with the rendered PDF, and explain what went wrong — or say `UNKNOWN` when the evidence is not strong enough.

> **Status: B0 design freeze (2026-11-16).** There is no detector, no installable release, and no benchmark result yet. This repository currently contains a reproducible feasibility spike, a frozen benchmark manifest, a preregistration, and a version stub. Fifteen independent review rounds are recorded in [`docs/reviews/B0_REVIEW.md`](docs/reviews/B0_REVIEW.md); rounds 8, 9, 10, 11, 12, 13, 14 and 15 returned REJECT, round 15's fixes (prereg v1.12) are frozen by `docs/B0_FREEZE.sha256` and tag `b0-freeze-r16`, and the round-16 scoped re-review of that tag is pending. Claims below describe the v1 design, not shipped behavior.

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
| D3 | `overlapping_text` | two text objects' painted character boxes overlap enough to impair reading; an own opaque background patch demotes the pair to `UNKNOWN` rather than suppressing it |
| D4 | `missing_glyph` | a character is absent from, or maps to glyph ID 0 in, every resolved font in the stack and Matplotlib emitted a missing-glyph warning naming it |

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

Two further owner-run probes back the round-8 fixes: [`spikes/b0_d1_boundary_probe.py`](spikes/b0_d1_boundary_probe.py) checks the single D1 boundary predicate on three pinned fixtures and passed 39/39 (output [`artifacts/b0/d1-boundary-probe.json`](artifacts/b0/d1-boundary-probe.json); re-run for round 9 with the corrected fixture docstring); [`spikes/b0_validator_bypass_repro.py`](spikes/b0_validator_bypass_repro.py) runs four mutations against the round-7 validator and records that all four were accepted with exit 0 while a fifth (a state flip) was rejected — the reproduction of the round-8 validator finding, output [`artifacts/b0/validator-bypass-repro.json`](artifacts/b0/validator-bypass-repro.json). That repro deliberately refuses to run once the validator at HEAD contains the fixed checks, so it documents the round-8 finding rather than re-running on the current tree. A third probe backs the round-12 missing-glyph fix: [`spikes/b0_missing_glyph_alignment_probe.py`](spikes/b0_missing_glyph_alignment_probe.py) draws the U+20000 unit, checks the pinned cmaps, the recorded warning, extraction absence, the deleted-character control and the height band, and measures the span-vs-source-bbox IoU (output [`artifacts/b0/missing-glyph-alignment-probe.json`](artifacts/b0/missing-glyph-alignment-probe.json)). The validator itself is pinned by [`tests/test_manifest_mutations.py`](tests/test_manifest_mutations.py): 79 on-disk mutations, each required to fail with its expected diagnostic fragment, plus six passing controls (85 tests in this file; 88 in the whole suite).

Facts the probes established (the U+2212, tight-bbox, label-binding and interior-space numbers are owner probes recorded in the review log, not fields of `api-spike.json`; the U+20000 numbers now have their own artifact; §0 and §16 of the preregistration separate the sources):

- Matplotlib `pdf.fonttype=42` keeps CJK text and character boxes extractable through PDFium (76 characters, 50 non-whitespace, in the test page).
- With `pdf.fonttype=3`, ASCII remains extractable but the CJK title is not — so v1 must return `UNKNOWN`, never a text-based `FAIL`, in that case.
- A missing glyph (U+9F98 in DejaVu Sans) triggers a Matplotlib warning and is absent from the font cmap, **but the character is still present in the PDF text layer**. Text extraction is therefore not rendering evidence; D4 requires the cmap and warning evidence instead.
- Under `pdf.fonttype=3`, PDFium drops U+2212 from extraction (`−1500` is read as `1500`); ASCII U+002D survives under both type 3 and type 42. The benchmark therefore freezes ASCII minus labels and pins `pdf.fonttype=42` in the manifest's `save_binding`.
- A character absent from both benchmark fonts (U+20000) is dropped from extraction under fonttype 42, unlike U+9F98; the alignment rule matches the remaining characters (measured span-vs-source-bbox IoU 0.773; 0.7734 centered, 0.7730 left-aligned, [`artifacts/b0/missing-glyph-alignment-probe.json`](artifacts/b0/missing-glyph-alignment-probe.json)).
- PDFium returns zero-area character boxes for CR/LF and for the spaces that separate x tick labels (measured: 2 of 125 characters on a title-only fixture, 21 of 180 on an axes with six tick labels and a title). D1 keys on positive-area boxes only, so whitespace can never make a text object "clipped".
- A fallback font stack suppresses the missing-glyph warning.
- On the recorded environment and font, identical input produced byte-identical PDFs (`sha256 0800e869b86f66c671e8ccf94c7a3ae15ac25a576291ab5ca0ecb62165fd820a`). Bytes may change with Matplotlib, PDFium, or font versions, so reproducibility is claimed only for the pinned environment.

The CJK part of the spike uses Noto Sans CJK SC (OFL-1.1), pinned in the prereg by sha256; proprietary Windows fonts are not used in public artifacts.

The frozen benchmark inventory is [`benchmark/manifest.json`](benchmark/manifest.json), validated by [`benchmark/validate_manifest.py`](benchmark/validate_manifest.py): 24 templates (12 development, 12 holdout), 228 samples, 192 defect instances, 96 of them in the holdout, 24 per defect class in the holdout. The manifest lists every sample with its variant, seed, split, expected state, and target role. Every sample is captured under one `save_binding` — Matplotlib 3.10.8, Agg, `pdf.fonttype=42`, 100 dpi, 10 × 6 in, 10 pt, constrained layout, `axes.unicode_minus=False`, `transparent=False` — because type 3 drops U+2212 from extraction and the dense-tick template's overlap geometry is figure-size dependent. The 10 × 6 size is retained as the global save binding, and the generator's clean check — no page clipping, and no D3 candidate with smaller-union coverage ≥ 0.15 — is the certifying measurement for H07's label spacing. Smaller-union coverage is the ratio on the D3 operand set frozen in the prereg: aligned character-box unions for a pair in which both units are aligned, transformed source bboxes only when a member cannot be aligned (that path is capped at medium). The round-7 and round-8 per-size coverage table is withdrawn in v1.6: its probe fixed only the forty x ticks, not the rest of the figure, and constrained layout makes the decimals construction-dependent. No figure size is claimed safe or unsafe without that executable check. Every template's axis and colorbar labels are bound to horizontal text (`rotation=0`, `labelpad=4.0`) with fixed alignment: left y-labels `ha='right'`, right (twin) y-labels `ha='left'`, figure-level shared y-labels `ha='left'` under constrained layout. H07's exact forty-tick binding and H12's thousands-separator formatter are pinned in the manifest and enforced by the validator. Matplotlib's default vertical y-label is rotated text, which v1 records as unsupported and forces `UNKNOWN`; a horizontal label with the default centre alignment overlaps its tick column (round-6 source-bbox measurements: 0.214 on the left label, 0.607 on the twin label). Those are round-6 source-bbox ratios: under the current D3 rule an aligned pair is measured on aligned character-box unions, so neither number is by itself high-confidence `D3` evidence; the certifying measurement is the generator's executable clean check. A shared label with centre alignment also runs off the left page edge. The holdout split is frozen at B0; the holdout samples themselves are generated and sealed at B2. **No samples have been generated yet.**

The evaluation design — input contract, defect definitions, holdout protocol, matching rules, gates, baselines, and the stop rule — is frozen in [`docs/B0_PREREGISTRATION.md`](docs/B0_PREREGISTRATION.md) before any detector code. Two dev counterexamples (a rotated-label case and a semi-transparent occluder) are labeled `UNKNOWN` by design; they must never become `FAIL`. The occluder's construction is pinned in the manifest (`facecolor_alpha` 0.5 × `artist_alpha` 1.0, effective alpha 0.50) and enforced by the validator, so a drift to an opaque fill is rejected before any detector exists that could mislabel it. The six holdout counterexamples are all expected `PASS`.

### Reproducing B0

Requires Python 3.12 on Windows (the verified environment). From the repository root:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python spikes\fetch_b0_font.py
.venv\Scripts\python spikes\b0_pdfium_spike.py
.venv\Scripts\python spikes\b0_d1_boundary_probe.py
.venv\Scripts\python spikes\b0_missing_glyph_alignment_probe.py
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
| B0 | support scope, defect definitions, sample inventory, holdout and metric freeze, licence audit, PDFium spike | design frozen; fifteen review rounds recorded (rounds 8, 9, 10, 11, 12, 13, 14 and 15 returned REJECT); round 15's fixes (prereg v1.12) are pinned by `docs/B0_FREEZE.sha256` and tag `b0-freeze-r16`, round-16 scoped re-review pending |
| B1 | deterministic checker core for D1–D4, dev split only | not started |
| B2 | baseline comparison and threshold calibration on the dev split | not started |
| B3 | one sealed holdout run, preregistered report | not started |
| B4 | documentation, examples, release | not started |

B1 work will not begin until the B0 review is recorded.

## License

MIT. Dependency and font licenses are recorded in [`docs/DEPENDENCY_LICENSES.md`](docs/DEPENDENCY_LICENSES.md) and summarized in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). PyMuPDF/MuPDF is deliberately excluded because it is AGPL/commercial.

## 中文摘要

PlotProof 要解决的是 Matplotlib 出图时的“静默失败”：轴标签被页边裁掉、图例压住数据、文字互相遮挡、中文缺字变成空白或方框。它不是通用 PDF 检查器，也不是审美评分器，而是一个**源码辅助**的导出检查器：在保存时记录文字、几何与样式，再用 PDFium 对导出的单页 PDF 做比对，输出带证据的 `PASS / FAIL / UNKNOWN / ERROR`。

当前仓库处于 **B0 设计冻结阶段**：尚未实现检测器，没有可安装版本，也没有任何准确率或用户数据。预登记文档已更新到 v1.12：第十二轮审查的修正（D3 自有背景改降级、D2 贡献图元集合与联合覆盖 medium 档、D4 统一为「cmap 缺失或映射到字形 ID 0」、§7.1 唯一对齐定义、D1 发现框改为字符框并集包围矩形、`visible=False` 记为 `is_unit=false`、缺字示例改为注入 U+20000 且 IoU 0.773）冻结在 `b0-freeze-r13`；第十三轮独立审查给出 REJECT（1 阻断 + 2 必需 + 3 次要，逐条复现与处置记录在评审日志中），本轮把 §4/§9 的类别优先级改为**按置信度分域**（只压制同置信度、更低优先级的发现；medium 永不压制 high；D3 的一对文字只有被同置信度的更高优先级发现命中时才整对压制——原先 medium 的 D2 会把 high 的 D3 整对压掉，从而把 FAIL 变成 UNKNOWN）、§7 的 D2 发现记录改称「contributing artist」以与 §4 的 `α_eff ≥ 0.50` 贡献集一致、D4 新增「字形证据成立但删掉缺失字符后仍无唯一对齐（例如剩余被删空）」的 medium 档（携带变换后的源框，不再落进 `no_text_match` 而在覆盖率 ≥ 0.90 时漏成 PASS）并把它列为第二个免对齐 medium 情形、版本历史的贡献集措辞改为「`owner_unit_id` 不是本单元 ID」（含 `null`）、缺字探针与产物改为记录字体文件名与 `relative_to_matplotlib_data`（不再泄漏本机绝对路径）；修复冻结在 `b0-freeze-r14` 标签上。第十四轮独立审查给出 REJECT（1 阻断 + 2 必需 + 3 次要）：紧致裁切（tight）导出时，§7.1 第五项与 D1 边界判据原本拿 `fig.bbox` 当页面，被迫被裁进来的标注会整条掉出单元集——现改为按保存页矩形 `intersects_page`（§2 记录页矩形，首项失败名改为 `outside_page`，L11 标注位置钉死为图坐标 (1.02, 0.5) 并由校验器强制）；端到端召回门槛与 bootstrap 明确只数高置信度命中（medium 既不是 TP 也不吃召回）、D1 补上与 D2/D3 相同的「置信度内高优先」句、§7 的「额外非同一发现算 FP」限缩到高置信度；D3 的免对齐 medium 档要求两成员都是 supported、D4 的无对齐 medium 档要求单元本身 supported；§5 新增逐类注入绑定（clip/occlude/overlap 必须达到高置信带，missing_glyph 固定 U+20000），冻结进清单并由校验器逐字校验；连带缺陷样本不再引用不存在的 single-instance 计数，改为保留在 228/114/96 固定分母中、附带引用单独报告且不计入精确率与召回。修复冻结在 `b0-freeze-r15` 标签上。第十五轮独立审查给出 REJECT（1 阻断 + 1 必需 + 3 次要）：§7.1 第五项被指把显示坐标的窗框与 PDF 点制的页面矩形直接比较——复审重现确认混单位歧义真实存在（L11 标注换成点制后落在 `[0, 826.620] × [0, 440.400]` 之内，直接比较却会越界；评审原文判它越界是漏算了紧致裁切的页面扩张），现改为先按 §2 变换再与页矩形相交，并写出显示坐标拉回式与「两个操作数绝不混单位」；D1 边界判据与 D2 页内判据引用同一页矩形和同一变换，记录的 `fig.bbox` 降级为溯源信息、不再参与任何判据；§5 的逐类注入绑定补全高置信带护栏（clip 必须正面积；occlude 必须是单个图元自身覆盖 ≥ 0.90、几何受支持且 `R_a` 在页内，联合覆盖明确不算；overlap 必须两成员都没有自有不透明背景与重叠区相交）；校验器对 `schema_version`、`seeds`、L11 `save_override` 改类型严格比较，`save_binding` 缺键报错，非许可记录里的显式 `null` 一律拒绝；README 版本号修正。修复冻结在 `b0-freeze-r16` 标签上，第十六轮定向复审待进行。已完成的是可复现的可行性 spike（14/14 项检查通过）、D1 边界判据探针（39/39）、缺字对齐探针（U+20000，23/23，含 cmap、警告、抽取缺失与 IoU 校验）、校验器变异套件（79 条变异 + 6 组对照，本文件 85 项、全套 88 项测试）、228 个样本的冻结清单、以及写死在代码之前的预登记文档。基准样本尚未生成，保留集尚未解封。D1 只认面积为正的字符框，PDFium 给 CR/LF 和刻度分隔空格返回的零面积框一律忽略（实测标题页 125 字符中有 2 个、带六个刻度标签的坐标轴 180 字符中有 21 个），否则空白字符会把自己"判成"被裁。水平文字的对齐方式也已写死：左侧 y 轴标签 `ha='right'`、右侧（twin）标签 `ha='left'`、整图共享标签 `ha='left'` 配合 constrained layout、`labelpad=4.0`；默认居中方案实测与刻度标签重叠（第六轮源框实测 0.214 / 0.607），共享标签还会跑出页面左边。保存绑定同时写死 `transparent=False`、`pdf.fonttype=42` 与 10 × 6 英寸；H07 的标签间距改由生成器的可执行干净检查认证（无页面裁切、且不存在较小并集覆盖率 ≥ 0.15 的 D3 候选；对齐对用对齐字符框并集，成员无法对齐时才退回源框并封顶为 medium），第七、八轮的分尺寸覆盖率表在 v1.6 中撤销（该探针只固定了四十个 x 刻度，未固定图的其余部分，constrained layout 下小数随构造而变）。D2 的"不透明"定义为 `α_eff = facecolor alpha × artist alpha ≥ 0.95`；半透明反例的构造（0.5 × 1.0 = 0.50）已钉进清单并由校验器强制，不可能漂移成 `FAIL`。`bbox_inches='tight'` 导出依赖保存时记录的裁切原点，缺失即 `UNKNOWN`，绝不猜裁切。依赖与字体许可已逐项核验，PyMuPDF（AGPL/商业双授权）被明确排除。
