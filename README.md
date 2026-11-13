# PlotProof

**A source-assisted export checker for Matplotlib figures.** It will capture what a figure intends to draw at save time, compare that record with the rendered PDF, and explain what went wrong — or say `UNKNOWN` when the evidence is not strong enough.

> **Status: B0 design freeze (2026-11-13).** There is no detector, no installable release, and no benchmark result yet. This repository currently contains a reproducible feasibility spike, a frozen benchmark manifest, a preregistration, and a version stub. Claims below describe the v1 design, not shipped behavior.

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
| D1 | `clipped_text` | a text object's aligned character boxes extend past the page boundary in the exported PDF |
| D2 | `occluded_text` | an opaque artist, painted after the text, covers at least 90% of the text's painted character boxes |
| D3 | `overlapping_text` | two text objects' painted character boxes overlap enough to impair reading, with no opaque background separating them |
| D4 | `missing_glyph` | a character is absent from every resolved font in the stack and Matplotlib emitted a missing-glyph warning naming it |

Only high-confidence evidence produces `FAIL`. Medium-confidence evidence forces `UNKNOWN`; low-confidence evidence is not reported. Results are `PASS`, `FAIL`, `UNKNOWN`, or `ERROR`, with priority `ERROR > FAIL > UNKNOWN > PASS`.

## What it will not do

- It is not a general PDF checker. Arbitrary, multi-page, rotated, or non-wrapper PDFs are rejected in v1.
- Rotated text and mathtext are recorded as unsupported units and force `UNKNOWN`; path-only text is outside the source model and is not claimed checked; multi-page PDFs are rejected as `ERROR`.
- It is not a semantic or aesthetic judge: it does not check whether the chart's message is true or whether the colors look good.
- It is not an ML model. The core is deterministic text and geometry evidence.
- `PASS` means "no supported defect was found with sufficient coverage", not "the figure is correct".
- It will not claim real-world accuracy before the preregistered benchmark and a sealed holdout have been run.

## B0 evidence (verified, not a detector)

The feasibility spike `spikes/b0_pdfium_spike.py` ran on the development machine and passed 14/14 checks. Machine-readable output: [`artifacts/b0/api-spike.json`](artifacts/b0/api-spike.json). Rendered example: [`artifacts/b0/api-spike-render.png`](artifacts/b0/api-spike-render.png).

Facts it established:

- Matplotlib `pdf.fonttype=42` keeps CJK text and character boxes extractable through PDFium (76 characters, 50 non-whitespace, in the test page).
- With `pdf.fonttype=3`, ASCII remains extractable but the CJK title is not — so v1 must return `UNKNOWN`, never a text-based `FAIL`, in that case.
- A missing glyph (U+9F98 in DejaVu Sans) triggers a Matplotlib warning and is absent from the font cmap, **but the character is still present in the PDF text layer**. Text extraction is therefore not rendering evidence; D4 requires the cmap and warning evidence instead.
- A fallback font stack suppresses the missing-glyph warning.
- On the recorded environment and font, identical input produced byte-identical PDFs (`sha256 0800e869b86f66c671e8ccf94c7a3ae15ac25a576291ab5ca0ecb62165fd820a`). Bytes may change with Matplotlib, PDFium, or font versions, so reproducibility is claimed only for the pinned environment.

The CJK part of the spike uses Noto Sans CJK SC (OFL-1.1), pinned in the prereg by sha256; proprietary Windows fonts are not used in public artifacts.

The frozen benchmark inventory is [`benchmark/manifest.json`](benchmark/manifest.json), validated by [`benchmark/validate_manifest.py`](benchmark/validate_manifest.py): 24 templates (12 development, 12 holdout), 228 samples, 192 defect instances, 96 of them in the holdout, 24 per defect class in the holdout. The manifest lists every sample with its variant, seed, split, expected state, and target role. The holdout split is frozen at B0; the holdout samples themselves are generated and sealed at B2. **No samples have been generated yet.**

The evaluation design — input contract, defect definitions, holdout protocol, matching rules, gates, baselines, and the stop rule — is frozen in [`docs/B0_PREREGISTRATION.md`](docs/B0_PREREGISTRATION.md) before any detector code. Two dev counterexamples (a rotated-label case and a semi-transparent occluder) are labeled `UNKNOWN` by design; they must never become `FAIL`. The six holdout counterexamples are all expected `PASS`.

### Reproducing B0

Requires Python 3.12 on Windows (the verified environment). From the repository root:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python spikes\fetch_b0_font.py
.venv\Scripts\python spikes\b0_pdfium_spike.py
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
| B0 | support scope, defect definitions, sample inventory, holdout and metric freeze, licence audit, PDFium spike | design frozen; four review rounds recorded, round-5 re-review pending on tag `b0-freeze-r5` |
| B1 | deterministic checker core for D1–D4, dev split only | not started |
| B2 | baseline comparison and threshold calibration on the dev split | not started |
| B3 | one sealed holdout run, preregistered report | not started |
| B4 | documentation, examples, release | not started |

B1 work will not begin until the B0 review is recorded.

## License

MIT. Dependency and font licenses are recorded in [`docs/DEPENDENCY_LICENSES.md`](docs/DEPENDENCY_LICENSES.md) and summarized in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). PyMuPDF/MuPDF is deliberately excluded because it is AGPL/commercial.

## 中文摘要

PlotProof 要解决的是 Matplotlib 出图时的“静默失败”：轴标签被页边裁掉、图例压住数据、文字互相遮挡、中文缺字变成空白或方框。它不是通用 PDF 检查器，也不是审美评分器，而是一个**源码辅助**的导出检查器：在保存时记录文字、几何与样式，再用 PDFium 对导出的单页 PDF 做比对，输出带证据的 `PASS / FAIL / UNKNOWN / ERROR`。

当前仓库处于 **B0 设计冻结阶段**：尚未实现检测器，没有可安装版本，也没有任何准确率或用户数据。已完成的是可复现的可行性 spike（14/14 项检查通过）、228 个样本的冻结清单、以及写死在代码之前的预登记文档。基准样本尚未生成，保留集尚未解封。依赖与字体许可已逐项核验，PyMuPDF（AGPL/商业双授权）被明确排除。
