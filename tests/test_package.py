from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import plotproof

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("matplotlib", "numpy", "pypdfium2", "fontTools", "PIL")
PROBE = (
    "import json, sys\n"
    "import plotproof\n"
    "{extra}"
    "heavy = [m for m in {heavy!r} if m in sys.modules]\n"
    "print(json.dumps({{'version': plotproof.__version__, 'heavy': heavy}}))\n"
)


def run_probe(extra: str = "") -> dict[str, object]:
    code = PROBE.format(extra=extra, heavy=HEAVY)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_package_exposes_the_preview_version_and_lazy_api() -> None:
    assert plotproof.__version__ == "0.1.0a2"
    assert sorted(plotproof.__all__) == ["CheckError", "CheckReport",
                                        "check_figure", "render_html"]
    # The attribute exists without importing the heavy assembly at package import.
    assert callable(plotproof.check_figure)


def test_importing_the_package_loads_no_heavy_dependency() -> None:
    probe = run_probe()
    assert probe["version"] == "0.1.0a2"
    assert probe["heavy"] == []


def test_heavy_dependency_probe_can_detect_an_import() -> None:
    """Control: the same predicate must report PIL when the probe imports it."""
    probe = run_probe("import PIL  # noqa: F401\n")
    assert "PIL" in probe["heavy"]
