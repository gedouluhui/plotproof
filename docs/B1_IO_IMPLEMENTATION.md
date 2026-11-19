# B1 bounded PDF input implementation plan

> Execute with test-driven development and owner verification. The user authorized continuing the projects and delegated implementation decisions. Existing uncommitted code and B0-pinned files must remain intact; no commit or publication in this slice.

**Goal:** Provide an actual subprocess-only PDFium reader with bounded inputs, outputs and work, ready for the later source-capture/bundle layer.

**Architecture:** A lightweight parent validates the expected hash and local input size, reads one immutable byte snapshot, and starts one isolated Python worker. The worker imports PDFium, validates document geometry, copies text/boxes and optionally a bounded RGB PNG, closes every handle, then emits strict JSON. Parent decoding produces typed records for the existing pure core. The reader does not prove a PDF originated from a wrapper; that remains the bundle layer's obligation.

**Spec:** Frozen `docs/B0_PREREGISTRATION.md` §§2, 3.1, 11–12. The existing core stays unchanged. This is the I/O reader slice, not the complete B1 wrapper or benchmark.

## Limits and protocol

- Defaults/hard ceilings: PDF input 16 MiB; 200,000 PDFium characters; optional bitmap 16,000,000 pixels; child wall timeout 30 seconds. Callers may tighten, not raise, these ceilings.
- Geometry must be finite, positive, single-page, rotation 0, cropbox exactly equal to mediabox, origin (0,0), and fit A2 in either orientation (420×594 mm converted with 72/25.4). Nonzero media origin cannot be normalized by the current source contract, so it is rejected explicitly.
- Encrypted files, including encryption with an empty user password, are rejected. Use PDFium's observed security-handler revision API; byte searches for `/Encrypt` are not authoritative.
- Parent imports no PDFium or rendering stack. No native calls are concurrent within any worker; callers may run independent worker processes concurrently.
- Launch `sys.executable -I <trusted worker script>` with `shell=False`. PDF bytes go through stdin; limits/render options are bounded trusted arguments. PDFium must not open a mutable input path.
- Child timeout kills and waits for that one owned Popen process only. No image-name kills, broad process-tree cleanup or automatic retries.
- Optional rasterization is off by default; validate scale and `ceil(width*scale)*ceil(height*scale)` before rendering. Do not initialize forms or JavaScript, and do not draw annotations/forms in the evidence raster.
- Bounds are resource precautions, not a strong operating-system sandbox. Input file reading and font collection are not included in the child timeout.
- Stable errors carry a reason and sanitized message, never PDF text, a stack trace or a local path. Malformed/nonfinite/unexpected worker output fails closed.

## Files and interfaces

- `plotproof/pdf_input.py`: `PdfLimits`, `PdfSnapshot`, `PdfReadError`, `read_pdf(path, expected_sha256, *, limits=PdfLimits(), render_scale=None)`; parent lifecycle and typed decoding.
- `plotproof/_pdf_worker.py`: standalone trusted subprocess entry; standard library + PDFium/Pillow inside the child only.
- `tests/test_pdf_input.py`: real PDF fixtures, hash/geometry/limits/raster/parent-import tests.
- `tests/test_pdf_process.py`: actual timeout, crash, invalid response and process-isolation controls.
- `tests/_pdf_fixtures.py`: tiny independent PDF constructor, including a standard-security R2 fixture where needed; never preregistered dev/holdout data.

```python
snapshot = read_pdf(pdf_path, expected_sha256=digest)
assert snapshot.input_sha256 == digest
assert snapshot.page_count == 1
assert snapshot.rotation == 0
# Each character is an existing evidence.PdfChar (code point + unrounded Rect).
characters = snapshot.characters
```

Snapshot fields: input_sha256, pypdfium2_version, pdfium_version, page_count, page_size_pt, cropbox, mediabox, rotation, characters, and optional render `{width,height,mode,png_bytes}`. The parent reconciles `char_count`, finite boxes and dimensions rather than trust a claimed successful payload.

## Tasks

- [x] Write red tests for a real one-page PDF's text/boxes, exact hash, round-trip raster dimensions, parent import independence, non-PDF/malformed/encrypted/multi-page/rotated/cropped/oversized input and tighten-only limits.
- [x] Implement the reader and worker; first verify the installed PDFium calls with real bytes. Do not invent upstream API fields.
- [x] Write and run subprocess controls: a real hanging owned child times out, its process is reaped, an unrelated control child survives; a valid read succeeds afterwards. Crash, wrong hash, duplicate/extra fields, missing character records, NaN and malformed JSON never become snapshots.
- [x] Independently review the process and protocol boundary; reproduce every finding and add tests before fixes.
- [x] Run new and complete regression suites, frozen-file verification and source-hash receipt; update handovers with exact scope and unresolved capture work.

## Sources and initial observations

Installed API inspected: `PdfDocument(input,password=None,autoclose=False)`, `PdfPage.render(scale=1,rotation=0,crop=(0,0,0,0),may_draw_forms=True,...)`, `get_charbox(index,loose=False)`. Actual versions are pypdfium2 5.8.0 / PDFium 149.0.7825.0. `FPDFText_GetUnicode` returns an unsigned code point; it avoids assuming text string length equals PDF character count.

[Official API](https://pypdfium2.readthedocs.io/en/stable/python_api.html) documents immutable bytes input and the ban on concurrent PDFium calls even across different documents. Latest online docs mention newer methods (e.g. 5.10); implementation must use only the installed 5.8 interface observed locally.

## Progress

Reader/worker implemented; the owner ran the new input/process tests: **57 passed**. Initial red baselines were 36 input failures and 21 process failures; setup assertions in the first process-test version were moved into test bodies before the recorded all-failing red run. Native API controls proved plain PDF security revision −1, empty-password encrypted revision 2, and nonempty-password load error 4.

The first green attempt found a real numeric-boundary problem: logical A2 is `(1190.5511811023623, 1683.7795275590552)` points but PDFium returns `(1190.5511474609375, 1683.779541015625)`, exactly the binary32 projection. The limit is compared in that observed representation; both orientations pass, +0.01 pt remains rejected, and −0.01 pt passes. No detector threshold changed. A bounded output pipe was added as a separate 64 MiB tighten-only ceiling; output and stderr are drained concurrently by transport-only threads, never native PDFium threads.

## Capture-contract counterexamples (production wrapper not certified)

An independent investigation identified assumptions that the owner then reproduced with separate real saves:

1. A black Rectangle with face alpha 0.6 and artist alpha 0.6 returns those same two getters, whose product is 0.36; the exported PDF actually uses alpha 0.6 and its white-background center pixel is RGB `(102,102,102)`, not the product model's predicted gray 163. The renderer's forced-alpha path overrides rather than multiplies the intrinsic alpha. A wrapper that simply copies both getters into the frozen product formula can incorrectly exclude a real medium occluder.
2. For a 4×3-inch ordinary-layout plot with a horizontal `Value` ylabel and `Time` xlabel, the pre-save Agg tight bbox is `[-0.12277777777777779, -0.10277777777777784, 3.722777777777778, 2.742777777777778]` inches; the actual save's MixedModeRenderer tight call gives `[-0.123046875, -0.09144097222222225, 3.7230468749999996, 2.7314409722222224]`. The frozen Agg-precompute recipe is not a generally exact description of the final crop.

Decision: do not fake capture fields, loosen detection thresholds, or publish a wrapper from the small integration helper. Preserve the B0 tag and every old result. Before a production capture API is accepted, an explicit capture addendum/new prereg revision must define renderer-applied alpha factors (while retaining raw source values) and a final-save crop origin captured during the save, with positive/negative controls and a review of affected evidence. This is an implementation prerequisite, not a claim that the abstract pure core failed its own tests. Holdout remains unopened and ungenerated.

The facts are now persisted by `spikes/b1_capture_semantics_probe.py`, `tests/test_capture_semantics.py` and `artifacts/b1/capture-semantics-probe.json`. The artifact is explicitly `capture_contract_counterexamples`, not a detector PASS. Its raw source values, rendered pixels, pre/save crop measurements, controls, versions and script SHA-256 are recorded. The owner also reproduced and fixed Windows CRLF output in the probe; the pre-fix artifact is retained separately, while the current writer explicitly emits UTF-8/LF.

## Input-boundary review dispositions

Independent review identified two required fixes and a smaller argument error. The owner reproduced all of them before changing code:

- A controlled worker inheritor kept stdin/stdout/stderr open. Killing the owned worker still left three transport threads and delayed a nominal 0.8-second test until about 16 seconds. The initial threaded implementation was replaced, not patched with a longer join: Python 3.12 nonblocking pipes were tested on this Windows host, and the parent now multiplexes raw pipe reads/writes under one deadline without creating transport threads. Once the owned worker exits it does not await an inheritor's EOF. The regression requires closed parent handles, a reaped owned process and no new live threads; the test releases its harmless inheritor by a control file rather than killing another PID.
- PNG headers/CRCs alone accepted empty IDAT, invalid zlib and invalid filter bytes. The parent now performs standard-library bounded streaming decompression in 65,536-byte output chunks, checking row lengths, filters 0–4, total decoded size, stream EOF and trailing data; the declared pixel cap is unchanged. The parent still imports no Pillow/PDFium.
- `render_scale=10**400` raised bare OverflowError. It is now rejected through `PdfReadError('invalid_input')` before worker startup.

Independent scoped re-review confirmed the three original defects were closed on Windows/Python 3.12.3, and identified one further issue: retaining chunk kinds and repeatedly testing list membership made many PNG ancillary chunks cause quadratic parent CPU work. The owner reproduced retained allocations of 1,502,055 bytes for a valid 480,068-byte, 32,000-metadata-chunk input, then replaced the history list with constant state. The added regression checks bounded allocations rather than a machine-speed-dependent timer. The three I/O test modules now pass **76/76**; the last constant-state fix was owner-verified, not claimed to have received another independent review.

## Final owner acceptance for this I/O slice

The owner's final complete run is **310 passed**. `artifacts/b1/io-verification.json` records the actual command, exit code, current tested-source SHA-256 values and **24/24 unchanged B0-pinned files**. The prior pure-core receipt remains an earlier scoped record and was not overwritten. The current capture probe artifact's script hash matches its source; its two counterexamples are scientific findings, not detector accuracy failures or benchmark scores.

Completed: immutable hash-bound PDF reading, bounded isolated native processing, strict result/raster decoding, timeout/handle cleanup, parent-import isolation, and tests/reviews described above. Not yet certified: POSIX execution, a strong OS sandbox, complete artist enumeration, composite images, collection geometry, resolved-font capture and the production save wrapper. The next capture milestone starts with the explicit contract amendment motivated by the real counterexamples. Holdout generation/inspection remains forbidden until its existing freeze procedure is satisfied.
