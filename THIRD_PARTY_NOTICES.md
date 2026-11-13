# Third-Party Notices

PlotProof itself is licensed under the MIT License (see `LICENSE`).

PlotProof depends on third-party packages but does not vendor them. When a wheel
or other binary distribution is published, it must include the license texts
required by those packages. The current repository contains source and example
artifacts only.

## Runtime dependencies

This table names each license and where the installed license text lives. It does
not restate copyright lines: those are version-specific and are reproduced from
the package's own license file when a binary distribution is built.

| Component | License | Installed notice |
|---|---|---|
| Matplotlib | PSF-based Matplotlib License | `matplotlib-3.10.8.dist-info/LICENSE` |
| NumPy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | `numpy-2.4.6.dist-info/licenses/LICENSE.txt` and the files beside it |
| pypdfium2 | BSD-3-Clause and Apache-2.0 | `pypdfium2-5.8.0.dist-info/licenses/` |
| PDFium (bundled in pypdfium2 wheels) | BSD-3-Clause plus third-party licenses | notices bundled under `pypdfium2-5.8.0.dist-info/licenses/` |
| fontTools | MIT | `fonttools-4.61.1.dist-info/licenses/LICENSE` |
| Pillow | MIT-CMU | `pillow-12.2.0.dist-info/licenses/LICENSE` |

The exact installed versions and the metadata observed on 2026-11-13 are recorded
in `docs/DEPENDENCY_LICENSES.md`. PyMuPDF/MuPDF is deliberately excluded because
it is AGPL-3.0 or commercially licensed.

## Fonts

- **Noto Sans CJK SC** (SIL Open Font License 1.1) is used for the B0
  feasibility spike and is planned for the CJK benchmark. The font binary is not
  committed; see `docs/DEPENDENCY_LICENSES.md` for the pinned sha256.
- **DejaVu Sans** (Bitstream Vera / Arev license) ships with Matplotlib and is
  used for ASCII rendering.
- Microsoft fonts (YaHei, SimHei, SimSun) are proprietary and are not
  redistributed by this project.

## Example artifacts

`artifacts/b0/api-spike-fonttype42.pdf` and
`artifacts/b0/api-spike-fonttype3.pdf` were produced by
`spikes/b0_pdfium_spike.py`. They embed subsets of the OFL-licensed Noto Sans
CJK SC font, which the OFL permits for documents.
