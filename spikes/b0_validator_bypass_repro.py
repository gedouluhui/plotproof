"""Reproduce the round-8 validator bypasses against the round-7 validator.

The round-8 review found that ``benchmark/validate_manifest.py`` accepted
manifests that changed what a template measures. This spike proves the claim
instead of asserting it: it loads the validator and manifest from HEAD
(the round-7 commit), applies each bypass on disk, and records the exit code.

Cases that must be ACCEPTED by the old validator (rc 0):

- ``template_role_swap_d01``: D01 and all of its samples relabelled
  ``target_role`` -> ``legend_inside``, which is one of D01's declared features.
  A template-only swap is already caught by the sample cross-check; the
  coordinated relabel is what the old validator accepted.
- ``sample_template_swap``: ``D01.clean.s1`` repointed at ``D02`` (same split,
  same target role, same seed, no family check).
- ``sample_family_change``: ``D01.clean.s1`` family -> ``bar_vertical``.
- ``save_unicode_minus_int_zero``: ``axes_unicode_minus`` -> ``0``; the old
  check used ``!=`` so ``0 != False`` was false. This is the same scalar
  comparison defect that made ``"transparent": 0`` acceptable once the field
  was bound.

Positive control that must be REJECTED by the old validator (rc 1):

- ``sample_expected_state_flip``: a defect sample declared PASS.

Writes artifacts/b0/validator-bypass-repro.json only when every expectation
holds; a failed run writes artifacts/b0/validator-bypass-repro-FAILED.json.

Run:
    python spikes/b0_validator_bypass_repro.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "b0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_show(path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"git show HEAD:{path} failed:\n{result.stderr.decode()}", file=sys.stderr)
        raise SystemExit(2)
    return result.stdout


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def set_template_role(manifest: dict) -> None:
    template = next(t for t in manifest["templates"] if t["id"] == "D01")
    template["target_role"] = "legend_inside"
    for sample in manifest["samples"]:
        if sample.get("template_id") == "D01":
            sample["target_role"] = "legend_inside"


def swap_sample_template(manifest: dict) -> None:
    sample = next(s for s in manifest["samples"] if s["id"] == "D01.clean.s1")
    sample["template_id"] = "D02"


def change_sample_family(manifest: dict) -> None:
    sample = next(s for s in manifest["samples"] if s["id"] == "D01.clean.s1")
    sample["family"] = "bar_vertical"


def set_unicode_minus_zero(manifest: dict) -> None:
    manifest["save_binding"]["axes_unicode_minus"] = 0


def flip_sample_expected_state(manifest: dict) -> None:
    sample = next(s for s in manifest["samples"] if s["id"] == "D01.clip.s1")
    sample["expected_state"] = "PASS"


ACCEPTED_CASES = [
    ("template_role_swap_d01", set_template_role),
    ("sample_template_swap", swap_sample_template),
    ("sample_family_change", change_sample_family),
    ("save_unicode_minus_int_zero", set_unicode_minus_zero),
]
REJECTED_CASES = [
    ("sample_expected_state_flip", flip_sample_expected_state),
]


def run_old_validator(validator: bytes, manifest: dict) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="plotproof-bypass-") as tmp:
        root = Path(tmp)
        (root / "benchmark").mkdir()
        (root / "benchmark" / "validate_manifest.py").write_bytes(validator)
        (root / "benchmark" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result = subprocess.run(
            [sys.executable, str(root / "benchmark" / "validate_manifest.py")],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
    return {
        "returncode": result.returncode,
        "stdout_tail": result.stdout.strip().splitlines()[-1:] or [],
        "stderr_tail": result.stderr.strip().splitlines()[-3:] or [],
    }


def main() -> int:
    old_validator = git_show("benchmark/validate_manifest.py")
    old_manifest_bytes = git_show("benchmark/manifest.json")
    if b"strict_equal" in old_validator:
        print(
            "HEAD already carries the hardened validator; this reproduction must "
            "run against the round-7 commit.",
            file=sys.stderr,
        )
        return 2
    old_manifest = json.loads(old_manifest_bytes)
    if "transparent" in old_manifest.get("save_binding", {}):
        print("HEAD manifest already binds transparent; wrong baseline.", file=sys.stderr)
        return 2

    record: dict[str, object] = {
        "spike_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head(),
        "old_validator_sha256": sha256_bytes(old_validator),
        "old_manifest_sha256": sha256_bytes(old_manifest_bytes),
        "python": sys.version,
        "controls": {},
        "accepted_by_old_validator": {},
        "rejected_by_old_validator": {},
        "checks": [],
        "overall": None,
    }

    def check(check_id: str, ok: bool, detail: object) -> None:
        record["checks"].append(
            {"id": check_id, "status": "PASS" if ok else "FAIL", "detail": detail}
        )

    baseline = run_old_validator(old_validator, copy.deepcopy(old_manifest))
    record["controls"]["unmutated_head_manifest"] = baseline
    check("old_validator_accepts_head_manifest", baseline["returncode"] == 0, baseline)

    for name, mutate in ACCEPTED_CASES:
        manifest = copy.deepcopy(old_manifest)
        mutate(manifest)
        result = run_old_validator(old_validator, manifest)
        record["accepted_by_old_validator"][name] = result
        check(
            f"old_validator_accepts_{name}",
            result["returncode"] == 0,
            {"returncode": result["returncode"], "stderr_tail": result["stderr_tail"]},
        )

    for name, mutate in REJECTED_CASES:
        manifest = copy.deepcopy(old_manifest)
        mutate(manifest)
        result = run_old_validator(old_validator, manifest)
        record["rejected_by_old_validator"][name] = result
        check(
            f"old_validator_rejects_{name}",
            result["returncode"] == 1,
            {"returncode": result["returncode"], "stderr_tail": result["stderr_tail"]},
        )

    failed = any(item["status"] == "FAIL" for item in record["checks"])
    record["overall"] = "FAIL" if failed else "PASS"
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / (
        "validator-bypass-repro-FAILED.json" if failed else "validator-bypass-repro.json"
    )
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(tmp, target)

    for item in record["checks"]:
        print(f"{item['status']:4s} {item['id']}")
    print(f"OVERALL {record['overall']} -> {target}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
