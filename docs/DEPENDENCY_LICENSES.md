# Dependency License Audit — PlotProof B0

**Audit date:** 2026-11-13
**Scope:** the exact environment used for the B0 feasibility spike. Versions and license metadata below were read from the installed distributions with `importlib.metadata`; they are observations, not guesses. OS: Windows 11 (`10.0.26300`), Python 3.12.3 (conda-forge build).

**Project license:** MIT (`LICENSE`).
**Policy:** no AGPL, SSPL, or other copyleft runtime dependency may ship in the `plotproof` package or its wheel. Dev-only tools may use weak copyleft (e.g. MPL-2.0) because they are not redistributed with the package.

## 1. Runtime dependencies (planned v1)

| Package | Verified version | License (as installed) | Role | Ships in wheel? |
|---|---|---|---|---|
| matplotlib | 3.10.8 | PSF-based Matplotlib License (`License :: OSI Approved :: Python Software Foundation License`) | draws figures and writes PDF through the wrapper | no (declared dependency) |
| numpy | 2.4.6 | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` | bitmap analysis and numeric geometry | no (declared dependency) |
| pypdfium2 | 5.8.0 | `BSD-3-Clause, Apache-2.0, dependency licenses` (wheel bundles PDFium and its third-party notices) | PDF text, character boxes, geometry, bitmap rendering | no (declared dependency) |
| fontTools | 4.61.1 | MIT | reading font cmap tables for missing-glyph evidence | no (declared dependency) |
| Pillow | 12.2.0 | MIT-CMU | bitmap crop and PNG encoding for evidence crops and the local HTML report; Matplotlib itself requires `pillow>=8`, and the spike calls `PdfBitmap.to_pil()` | no (declared dependency) |

Pillow is a runtime dependency in two senses: Matplotlib requires it for image handling, and PlotProof uses it directly for evidence crops, so it is declared explicitly rather than left implicit.

### Transitive runtime dependencies observed

Matplotlib pulls these into the same environment. Their licenses were also read from installed metadata:

| Package | Version | License |
|---|---|---|
| contourpy | 1.3.3 | BSD-3-Clause |
| cycler | 0.12.1 | BSD-3-Clause |
| kiwisolver | 1.4.9 | BSD-3-Clause |
| pyparsing | 3.3.2 | MIT |
| python-dateutil | 2.9.0.post0 | Dual: BSD-3-Clause / Apache-2.0 |
| packaging | 26.1 | Apache-2.0 OR BSD-2-Clause |
| pillow | 12.2.0 | MIT-CMU (also listed above because PlotProof imports it directly) |

Pillow appears in both tables on purpose: it is a transitive requirement of Matplotlib and a direct requirement of the crop/report code.

## 2. Development-only tools (not redistributed)

| Package | Version | License | Use |
|---|---|---|---|
| pytest | 9.2.0 | MIT | test runner |
| hypothesis | 6.170.15 | MPL-2.0 | property-based tests; dev-only, never imported by the shipped package |
| pluggy | 1.7.0 | MIT | pytest dependency |
| iniconfig | 2.3.1 | MIT | pytest dependency |
| Pygments | 2.19.1 | BSD-2-Clause | pytest output |

MPL-2.0 is acceptable here only because Hypothesis is a development dependency. If any test helper is ever imported by runtime code, this decision must be re-audited.

## 3. Explicit exclusions

| Package / product | License | Decision |
|---|---|---|
| PyMuPDF / MuPDF | AGPL-3.0 or commercial | **Excluded** from all code paths and dependencies. It must not be used to generate committed artifacts either. |
| Any AGPL/SSPL library | — | Excluded by policy. |
| Microsoft YaHei, SimHei, SimSun | proprietary | Never committed, never used in public benchmark artifacts. Local-only experiments are not redistributed. |

`pypdfium2` is not PyMuPDF. It wraps Google's PDFium (BSD-3-Clause plus bundled permissive third-party licenses) and is the only PDF renderer allowed in v1. Because the wheel bundles PDFium, any public binary redistribution must include pypdfium2's own license/notice files; a source-only repository that declares it as a dependency does not vendor those binaries.

## 4. Fonts

| Font | License | Handling |
|---|---|---|
| Noto Sans CJK SC Regular | SIL Open Font License 1.1 | Used for the B0 spike and the planned CJK benchmark. The 16,437,364-byte binary is **not committed** (`.fonts/` is git-ignored) and is pinned by sha256 `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`. |
| DejaVu Sans | Bitstream Vera / Arev license (bundled with Matplotlib) | Used for ASCII rendering; comes with Matplotlib, not vendored by this project. |
| Microsoft CJK fonts | proprietary | Excluded from committed artifacts. |

Subset embedding of an OFL font inside a committed example PDF is permitted by the OFL. The examples under `artifacts/b0/` are small (≈12–15 KB) and embed only the glyphs used on the page.

## 5. Verification commands

Re-run this audit in the environment that will build the package:

```bash
python - <<'PY'
import importlib.metadata as md
for name in ["matplotlib", "numpy", "pypdfium2", "fonttools", "pillow"]:
    d = md.distribution(name)
    meta = d.metadata
    print(name, d.version, meta.get("License-Expression") or meta.get("License"))
PY
```

```bash
python -m pip show matplotlib numpy pypdfium2 fonttools pillow
```

## 6. Status

- Runtime dependency set contains no AGPL/SSPL component.
- PyMuPDF (`pymupdf 1.27.2.3`, AGPL/commercial) is installed in the shared Anaconda environment but is not declared, not imported by the spike, and excluded from the design and from committed artifacts. Its presence in the machine does not put it in the dependency graph; a clean-environment install test is still required before release.
- This audit covers the design-stage dependency set only. It must be repeated when the B1 detector adds any import, and again before any wheel or sdist is published.
- The repository does not yet contain a built wheel; this document does not claim one was audited.
