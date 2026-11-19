# PlotProof

**Source-assisted export evidence for Matplotlib figures.** PlotProof records what a
figure intends to draw at save time, compares that record with the exported PDF, and
reports what went wrong — or `UNKNOWN` when the evidence is not strong enough.

> **Status: B1 engineering preview (2026-11-19).** The deterministic checker core, the
> bounded PDF reader and the CA1 save-time capture layer are implemented and tested
> (356 tests). An experimental assembly runs the whole path end to end on one figure.
> It is **not** a certified detector: there is no holdout run, no accuracy number, and
> no font evidence, so `D4_missing_glyph` is never assessed. Read
> [What this does not do](#what-this-does-not-do) before trusting any output.

## The problem

A Matplotlib figure can fail quietly:

- a long axis label is clipped at the page edge;
- a legend is drawn on top of data or text;
- labels from different artists collide;
- a CJK character has no glyph, so the PDF shows a blank or a box while the text layer
  still contains the original character.

Checking the PDF text layer alone cannot prove a glyph was drawn. Rasterizing alone
cannot tell which pieces of text were meant to be there. PlotProof uses both: a source
record captured inside Matplotlib at save time, and character boxes read from the PDF
with a bounded PDFium worker.

## Quick start

Requires Python 3.12 and Matplotlib 3.10.8 — the runtime the capture layer is
version-checked against.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # POSIX (the PDF worker is verified on Windows only)

.venv/Scripts/python -m plotproof demo --output plotproof-demo
```

The demo checks two generated figures and writes `clean.{json,html}` and
`clipped.{json,html}`:

```
clean: PASS
clipped: FAIL
```

`clipped` contains a real finding — an annotation that starts inside the page and runs
past its right edge:

```json
{
  "rule_id": "D1",
  "defect_class": "clipped_text",
  "confidence": "high",
  "source_text": "This annotation runs past the edge",
  "box_pdf_points": [276.5, 114.2, 375.9, 124.3]
}
```

To check your own figure, point the CLI at a file that exposes a `figure()` function:

```python
# make_figure.py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def figure():
    fig, ax = plt.subplots(figsize=(4, 3), dpi=100, layout="constrained")
    ax.bar(["alpha", "beta", "gamma"], [3, 5, 2])
    ax.set_xlabel("Category")
    ax.set_ylabel("Count", rotation=0)
    return fig
```

```bash
.venv/Scripts/python -m plotproof check make_figure.py --json report.json --html report.html
# exit 0 for PASS/UNKNOWN, 1 for FAIL, 2 when the figure is outside the contract
```

The library form is the same call:

```python
import plotproof

report = plotproof.check_figure(fig)      # captures, reads, checks
print(report.state, report.assessed)
```

## What is actually checked

| ID | Defect class | Status in this preview |
|---|---|---|
| D1 | `clipped_text` — a positive-area character box has at least half its area outside the page, or its centre strictly outside | assessed |
| D2 | `occluded_text` — one artist with `α_eff ≥ 0.95`, painted after the text, covers at least 90% of it | assessed **only** when no image or collection was painted; otherwise reported as not assessed |
| D3 | `overlapping_text` — two text objects' painted character boxes overlap enough to impair reading | assessed |
| D4 | `missing_glyph` — a character is absent from every resolved font and Matplotlib warned about it | **not assessed** (no font cmap evidence is collected yet) |

Every report states the classes it assessed and why the others were skipped:

```json
{
  "state": "PASS",
  "assessed": ["D1_clipped_text", "D3_overlapping_text"],
  "not_assessed": ["D2_occluded_text", "D4_missing_glyph"],
  "capture_issues": ["collection_capture_pending", "unassociated_material_event"],
  "coverage": {"aligned_units": 13, "total_units": 13, "ratio": 1.0}
}
```

**`PASS` means "no supported defect was found with sufficient coverage in the assessed
classes".** It is not a statement that the figure is correct, and it is not a benchmark
result.

`ERROR` means the run could not make a statement at all: an unmapped unit inventory, an
invalid event geometry, an ambiguous tight-crop origin, or a save outside the pinned
runtime. `UNKNOWN` means the evidence exists but is not decisive: rotated text, math
text, unresolved alignment, coverage below 0.90, or a finding at medium confidence.

## What this does not do

- **No holdout, no accuracy claim.** The benchmark manifest is frozen at B0; its
  holdout has never been generated or inspected. Nothing here is a precision/recall
  measurement.
- **No font evidence yet.** D4 needs cmaps from the resolved font files plus the save's
  missing-glyph warnings. That collector is the next slice.
- **Rotated text is unsupported.** Matplotlib's default vertical y-label forces
  `UNKNOWN`; use `rotation=0` to get an assessment. Mathtext, TeX, wrapped text,
  rasterized text and path effects are also outside the supported set.
- **Collections and images limit D2.** A plotted line's legend handle or a bar container
  is a collection; when one is painted, PlotProof cannot claim the paint inventory is
  complete and skips occlusion rather than guessing.
- **Not a general PDF checker.** Arbitrary, multi-page, rotated or non-wrapper PDFs are
  rejected. It does not guess a crop: `bbox_inches="tight"` is supported only through
  the origin recorded during the save.
- **Not a semantic or aesthetic judge.** It does not check whether the chart's message
  is true or whether the colours look good.
- **Verified on Windows, CPython 3.12.3, Matplotlib 3.10.8, PDFium 149.0.7825.0.** The
  POSIX path of the PDF worker is not exercised by this release.

## How it works

```
live Figure
  └─ capture.py (CA1)        temporary renderer hooks during the real savefig
       ├─ real PDF bytes + sha256
       ├─ draw-order events (sequence, PDF geometry, renderer-applied alpha)
       ├─ source inventory (Text/Patch traversal index, visibility, raw alpha)
       ├─ tight-crop origin (only when exactly one crop call is observed)
       └─ capture_issues (anything this layer could not map)
  └─ pdf_input.py            one owned process, hash-bound input, bounded output
       └─ page size, one character per PDF character with an unrounded box
  └─ units.py / alignment.py frozen §7.1 predicate, canonical form, greedy alignment
  └─ rules.py / core.py      D1–D4 with explicit evidence operands
  └─ export.py               assembly: records, fills, coverage, report
```

The checker is deterministic: float64 PDF points, no randomness, unrounded decisions.
The 0.1 pt rounding happens only in the report.

## Evidence and design record

- [`docs/B0_PREREGISTRATION.md`](docs/B0_PREREGISTRATION.md) — v1.13, frozen before any
  detector code: input contract, defect definitions, §7.1 alignment, metrics, gates.
  Pinned by `docs/B0_FREEZE.sha256` and tag `b0-freeze-r17`.
- [`docs/reviews/B0_REVIEW.md`](docs/reviews/B0_REVIEW.md) — sixteen review rounds;
  rounds 8–15 returned REJECT, round 16 approved `b0-freeze-r16` in an owner-run review
  (the independent dispatch hit its turn cap, so independence was not achieved).
- [`docs/B1_IMPLEMENTATION.md`](docs/B1_IMPLEMENTATION.md) and
  [`docs/B1_IO_IMPLEMENTATION.md`](docs/B1_IO_IMPLEMENTATION.md) — core and reader
  ledgers, including the measurement mistakes that were found and kept.
- [`docs/CAPTURE_AMENDMENT_CA1.md`](docs/CAPTURE_AMENDMENT_CA1.md) — the amendment that
  governs capture, motivated by two reproduced counterexamples: a forced-alpha rectangle
  that renders at 0.6 and not the getter product 0.36, and a tight-crop bbox that differs
  from the Agg pre-draw.
- [`benchmark/manifest.json`](benchmark/manifest.json) — 24 templates, 228 samples,
  192 defect instances, validated by `benchmark/validate_manifest.py`.
- [`spikes/`](spikes) — the feasibility probes, including the missing-glyph alignment
  measurement (U+20000, IoU 0.773) and the PDFium API spike (14/14).

Verified facts worth knowing before extending this:

- with `pdf.fonttype=42`, CJK text and character boxes stay extractable;
- with `pdf.fonttype=3`, ASCII survives but CJK does not, and U+2212 is dropped;
- a missing glyph still appears in the text layer, so text extraction is not rendering
  evidence;
- PDFium returns zero-area boxes for CR/LF and tick separators; D1 ignores them.

## Roadmap

| Milestone | Content | Status |
|---|---|---|
| B0 | scope, defect definitions, sample inventory, holdout and metric freeze, licence audit, PDFium spike | frozen (v1.13, tag `b0-freeze-r17`) |
| B1 | deterministic core for D1–D4, bounded PDF reader, CA1 capture | core/reader/capture implemented and tested |
| B1.5 | end-to-end assembly, D1/D3 assessment, class-scoped reports | this preview |
| B2 | font evidence (D4), complete paint inventory (D2 for collections/images), dev-split calibration | not started |
| B3 | one sealed holdout run, preregistered report | not started |
| B4 | release, documentation, examples | not started |

## Development

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest              # 356 tests
.venv/Scripts/python benchmark/validate_manifest.py
```

CI runs the suite on Ubuntu 3.12 and Windows 3.12 with Matplotlib 3.10.8.

## License

MIT. Dependency and font licences are recorded in
[`docs/DEPENDENCY_LICENSES.md`](docs/DEPENDENCY_LICENSES.md) and summarised in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). PyMuPDF/MuPDF is deliberately
excluded because it is AGPL/commercial.

## 中文摘要

PlotProof 检查 Matplotlib 导出 PDF 时的**静默失败**：轴标签被页边裁掉、图例压住文字、
文字互相遮挡、中文缺字变成空白或方框。它靠两条证据：保存时在 Matplotlib 内部记录的
绘制意图，以及用受限 PDFium 子进程读出的字符框。

当前是 **B1 工程预览**：确定性核心、受限 PDF 读取、CA1 保存期采集都已实现并通过 356 项
测试；端到端装配可以真正跑通一张图，**但不是认证过的检测器**——没有保留集结果、没有
准确率数字、没有字体 cmap 证据。

- 已评估：D1 文字被裁、D3 文字重叠；D2 遮挡仅在“没有图像/集合被绘制”时评估。
- 未评估：D4 缺字（下一步做字体证据）。
- 旋转文字（含默认竖排 y 轴标签）、数学公式、自动换行文字不支持，会强制 `UNKNOWN`。
- `PASS` 只表示“在已评估类别中、覆盖率足够时没发现受支持的缺陷”，不代表图正确。

```bash
python -m plotproof demo --output plotproof-demo        # 干净图 PASS / 故意裁切图 FAIL
python -m plotproof check make_figure.py --html report.html
```

退出码：`0` 表示 PASS/UNKNOWN，`1` 表示 FAIL，`2` 表示超出契约。
