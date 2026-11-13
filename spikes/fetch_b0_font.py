"""Download and verify the pinned OFL CJK font used by the B0 spike.

Stdlib only. The font is written to .fonts/ (git-ignored) and is NOT committed.
The hash is pinned in docs/B0_PREREGISTRATION.md and in the spike itself; if the
upstream file changes, this script fails instead of silently using new bytes.

Run:
    python spikes/fetch_b0_font.py

Exit codes: 0 already present or downloaded and verified; 2 mismatch or refusal.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".fonts" / "NotoSansCJKsc-Regular.otf"
URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/"
    "Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"
)
EXPECTED_BYTES = 16_437_364
EXPECTED_SHA256 = "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if TARGET.is_file():
        size = TARGET.stat().st_size
        digest = sha256_file(TARGET)
        if size == EXPECTED_BYTES and digest == EXPECTED_SHA256:
            print(f"already present: {TARGET.relative_to(ROOT)} ({size} bytes, sha256 ok)")
            return 0
        print(
            "refusing to overwrite an existing file that does not match the pin:\n"
            f"  path     {TARGET}\n"
            f"  expected {EXPECTED_BYTES} bytes {EXPECTED_SHA256}\n"
            f"  actual   {size} bytes {digest}\n"
            "Move or delete that file yourself if it is not needed.",
            file=sys.stderr,
        )
        return 2

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    tmp = TARGET.with_name(TARGET.name + ".part")
    request = urllib.request.Request(URL, headers={"User-Agent": "plotproof-b0-font-fetch"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                print(f"unexpected HTTP status: {response.status}", file=sys.stderr)
                return 2
            with tmp.open("wb") as out:
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    out.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        print(f"download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    size = tmp.stat().st_size
    digest = sha256_file(tmp)
    if size != EXPECTED_BYTES or digest != EXPECTED_SHA256:
        tmp.unlink(missing_ok=True)
        print(
            "downloaded bytes do not match the pin; the file was discarded:\n"
            f"  url      {URL}\n"
            f"  expected {EXPECTED_BYTES} bytes {EXPECTED_SHA256}\n"
            f"  actual   {size} bytes {digest}",
            file=sys.stderr,
        )
        return 2

    os.replace(tmp, TARGET)
    print(f"downloaded: {TARGET.relative_to(ROOT)} ({size} bytes, sha256 ok)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
