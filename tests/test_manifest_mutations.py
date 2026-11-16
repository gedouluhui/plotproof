"""On-disk mutation suite for benchmark/validate_manifest.py.

Every case copies the frozen manifest, applies exactly one mutation, and runs
the validator as a subprocess on that copy. A mutation must be rejected for
the intended reason: each case asserts on the diagnostic text, so a mutation
caught by an unrelated rule does not count as detection.

Four cases reproduce round-8 bypasses that the previous validator accepted:

- ``template_role_swap_d01``: D01 and all its samples relabelled to another
  declared feature; the old cross-check passed, so only a hard-coded identity
  catches it
- ``sample_template_swap``: a sample repointed at a template with the same
  split and target role
- ``sample_family_change``: a sample's ``family`` decoupled from its template
- ``save_transparent_int_zero``: JSON ``0`` used for the boolean ``transparent``
  binding (Python treats ``0 == False`` as true)

Negative controls prove the harness can pass: a verbatim copy, a compact
serialization, and a reordered copy must all report MANIFEST PASS.

Run: python -m pytest tests/test_manifest_mutations.py -q
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmark" / "manifest.json"
VALIDATOR = ROOT / "benchmark" / "validate_manifest.py"

Mutation = Callable[[dict[str, object]], None]


def template(manifest: dict, tid: str) -> dict:
    return next(item for item in manifest["templates"] if item["id"] == tid)


def sample(manifest: dict, sid: str) -> dict:
    return next(item for item in manifest["samples"] if item["id"] == sid)


def counterexample(manifest: dict, cid: str) -> dict:
    return next(item for item in manifest["counterexamples"] if item["id"] == cid)


def run_validator(
    tmp_path: Path, manifest: dict, *, compact: bool = False
) -> subprocess.CompletedProcess[str]:
    target = tmp_path / "manifest.json"
    if compact:
        text = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(manifest, ensure_ascii=False, indent=2)
    target.write_text(text + "\n", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(target)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


# --- mutation helpers -------------------------------------------------------


def set_save(manifest: dict, key: str, value: object) -> None:
    manifest["save_binding"][key] = value


def set_label(manifest: dict, key: str, value: object) -> None:
    manifest["label_binding"][key] = value


def set_template(manifest: dict, tid: str, key: str, value: object) -> None:
    template(manifest, tid)[key] = value


def drop_template_key(manifest: dict, tid: str, key: str) -> None:
    del template(manifest, tid)[key]


def set_sample(manifest: dict, sid: str, key: str, value: object) -> None:
    sample(manifest, sid)[key] = value


def drop_sample_key(manifest: dict, sid: str, key: str) -> None:
    del sample(manifest, sid)[key]


def set_counterexample(manifest: dict, cid: str, key: str, value: object) -> None:
    counterexample(manifest, cid)[key] = value


def sample_template_swap(manifest: dict) -> None:
    """Round-8 bypass: D01 and D02 share split, target role and no family check."""
    set_sample(manifest, "D01.clean.s1", "template_id", "D02")


def swap_d01_target_role(manifest: dict) -> None:
    """Round-8 bypass: relabel the template and its samples coherently.

    The old validator only compared each sample's role to its template's, so a
    coordinated relabel to another declared feature passed. Only the hard-coded
    per-template identity rejects it.
    """
    set_template(manifest, "D01", "target_role", "legend_inside")
    for item in manifest["samples"]:
        if item.get("template_id") == "D01":
            item["target_role"] = "legend_inside"


def swap_h11_target_role(manifest: dict) -> None:
    set_template(manifest, "H11", "target_role", "shared_xlabel")
    for item in manifest["samples"]:
        if item.get("template_id") == "H11":
            item["target_role"] = "shared_xlabel"


def retag_template_role(manifest: dict, tid: str, role: str) -> None:
    """Keep a template and its samples coherent so only the intended rule fires."""
    set_template(manifest, tid, "target_role", role)
    for item in manifest["samples"]:
        if item.get("template_id") == tid:
            item["target_role"] = role


def retag_template_family(manifest: dict, tid: str, family: str) -> None:
    set_template(manifest, tid, "family", family)
    for item in manifest["samples"]:
        if item.get("template_id") == tid:
            item["family"] = family


def sample_family_change(manifest: dict) -> None:
    """Round-8 bypass: the old validator never read ``sample.family``."""
    set_sample(manifest, "D01.clean.s1", "family", "bar_vertical")


def counter_sample_pointer_swap(manifest: dict) -> None:
    set_sample(manifest, "L01.counterexample", "counterexample_id", "L02")


def h08_gets_h07_tick_binding(manifest: dict) -> None:
    template(manifest, "H08")["tick_binding"] = copy.deepcopy(
        template(manifest, "H07")["tick_binding"]
    )


def h12_tick_rotation_float(manifest: dict) -> None:
    template(manifest, "H12")["tick_binding"]["y_label_rotation"] = 0.0


def h12_tick_binding_extra_key(manifest: dict) -> None:
    template(manifest, "H12")["tick_binding"]["y_note"] = "extra"


def h12_drop_thousands_feature(manifest: dict) -> None:
    template(manifest, "H12")["features"].remove("thousands_separator")


def add_counter_override(manifest: dict, cid: str) -> None:
    set_counterexample(
        manifest, cid, "save_override", {"bbox_inches": "tight", "pad_inches_effective": 0.1}
    )


def duplicate_counter_family(manifest: dict) -> None:
    """Round-9: counterexample families must be pairwise unique too."""
    family = counterexample(manifest, "L01")["family"]
    set_counterexample(manifest, "L02", "family", family)
    set_sample(manifest, "L02.counterexample", "family", family)


def add_counter_alpha(manifest: dict, cid: str, binding: object) -> None:
    set_counterexample(manifest, cid, "alpha_binding", binding)


MUTATIONS: list[tuple[str, Mutation, str]] = [
    # save_binding and label_binding
    (
        "save_transparent_int_zero",
        lambda m: set_save(m, "transparent", 0),
        "save_binding.transparent must be False",
    ),
    (
        "save_transparent_true",
        lambda m: set_save(m, "transparent", True),
        "save_binding.transparent must be False",
    ),
    (
        "save_transparent_missing",
        lambda m: m["save_binding"].pop("transparent"),
        "save_binding.transparent must be False",
    ),
    (
        "save_unicode_minus_int_zero",
        lambda m: set_save(m, "axes_unicode_minus", 0),
        "save_binding.axes_unicode_minus must be False",
    ),
    (
        "save_dpi_as_float",
        lambda m: set_save(m, "figure_dpi", 100.0),
        "save_binding.figure_dpi must be 100",
    ),
    (
        "save_font_size_as_int",
        lambda m: set_save(m, "base_font_size_pt", 10),
        "save_binding.base_font_size_pt must be 10.0",
    ),
    (
        "save_size_as_ints",
        lambda m: set_save(m, "figure_size_inches", [10, 6]),
        "save_binding.figure_size_inches must be [10.0, 6.0]",
    ),
    (
        "save_pad_effective_drift",
        lambda m: set_save(m, "pad_inches_effective", 0.09),
        "save_binding.pad_inches_effective must be 0.1",
    ),
    (
        "save_extra_key",
        lambda m: set_save(m, "draft", True),
        "save_binding has unexpected keys",
    ),
    (
        "label_labelpad_as_int",
        lambda m: set_label(m, "axis_labelpad_pt", 4),
        "label_binding.axis_labelpad_pt must be 4.0",
    ),
    (
        "label_labelpad_drift",
        lambda m: set_label(m, "axis_labelpad_pt", 3.0),
        "label_binding.axis_labelpad_pt must be 4.0",
    ),
    (
        "label_rotation_as_bool",
        lambda m: set_label(m, "axis_label_rotation", False),
        "label_binding.axis_label_rotation must be 0",
    ),
    (
        "label_extra_key",
        lambda m: set_label(m, "draft", 1),
        "label_binding has unexpected keys",
    ),
    # templates
    (
        "template_role_swap_d01",
        swap_d01_target_role,
        "template D01: target_role must be 'title'",
    ),
    (
        "template_role_swap_h11",
        swap_h11_target_role,
        "template H11: target_role must be 'suptitle'",
    ),
    (
        "template_missing_features",
        lambda m: drop_template_key(m, "D01", "features"),
        "template D01: missing keys",
    ),
    (
        "template_extra_key",
        lambda m: set_template(m, "D01", "defect_class", "clipped_text"),
        "template D01: unexpected keys",
    ),
    (
        "template_formatter_d11_comma",
        lambda m: set_template(m, "D11", "tick_formatter", "FuncFormatter('{:,}'.format)"),
        "template D11: tick_formatter must be",
    ),
    (
        "template_formatter_h09_missing",
        lambda m: drop_template_key(m, "H09", "tick_formatter"),
        "template H09: tick_formatter must be",
    ),
    (
        "template_formatter_h12_g",
        lambda m: set_template(m, "H12", "tick_formatter", "FuncFormatter('{:g}'.format)"),
        "template H12: tick_formatter must be",
    ),
    (
        "template_h12_ticks_rotation_float",
        h12_tick_rotation_float,
        "template H12: tick_binding does not match",
    ),
    (
        "template_h12_ticks_drop_major_tick",
        lambda m: template(m, "H12")["tick_binding"]["y_major_ticks"].remove(5000),
        "template H12: tick_binding does not match",
    ),
    (
        "template_h08_tick_binding",
        h08_gets_h07_tick_binding,
        "template H08: tick_binding is only allowed",
    ),
    (
        "template_h07_minor_subdivisions",
        lambda m: template(m, "H07")["tick_binding"].__setitem__("x_minor_subdivisions", 3),
        "template H07: tick_binding does not match",
    ),
    (
        "template_h12_tick_binding_extra_key",
        h12_tick_binding_extra_key,
        "template H12: tick_binding does not match",
    ),
    (
        "template_h12_drop_thousands_feature",
        h12_drop_thousands_feature,
        "template H12: the thousands-separator formatter requires the "
        "thousands_separator feature",
    ),
    (
        "template_labels_horizontal_false",
        lambda m: set_template(m, "D01", "labels_horizontal", False),
        "template D01: v1 has no rotated template labels",
    ),
    (
        "template_split_flip",
        lambda m: set_template(m, "D01", "split", "holdout"),
        "template D01: split must be 'dev'",
    ),
    # samples
    (
        "sample_template_swap",
        sample_template_swap,
        "sample D01.clean.s1: id must be '<template>.<variant>.s<seed>'",
    ),
    (
        "sample_family_change",
        sample_family_change,
        "sample D01.clean.s1: family disagrees with template D01",
    ),
    (
        "sample_seed_as_float",
        lambda m: set_sample(m, "D01.clean.s1", "seed", 1.0),
        "sample D01.clean.s1: seed must be an integer",
    ),
    (
        "sample_seed_as_bool",
        lambda m: set_sample(m, "D01.clean.s1", "seed", True),
        "sample D01.clean.s1: seed must be an integer",
    ),
    (
        "sample_extra_key",
        lambda m: set_sample(m, "D01.clean.s1", "note", "extra"),
        "sample D01.clean.s1: sample keys are frozen",
    ),
    (
        "sample_target_role_swap",
        lambda m: set_sample(m, "D01.clean.s1", "target_role", "legend_inside"),
        "sample D01.clean.s1: target_role disagrees with template D01",
    ),
    # counterexample records and their samples
    (
        "counter_sample_id_renamed",
        lambda m: set_sample(m, "L01.counterexample", "id", "L01.counterexample2"),
        "id must be '<counterexample>.counterexample'",
    ),
    (
        "counter_sample_pointer_swap",
        counter_sample_pointer_swap,
        "id must be '<counterexample>.counterexample'",
    ),
    (
        "counter_sample_family_change",
        lambda m: set_sample(m, "L01.counterexample", "family", "wrong_family"),
        "family disagrees with counterexample",
    ),
    (
        "counter_sample_target_role",
        lambda m: set_sample(m, "L01.counterexample", "target_role", "title"),
        "counterexample samples must not declare target_role",
    ),
    (
        "counter_sample_seed",
        lambda m: set_sample(m, "L01.counterexample", "seed", 1),
        "counterexample samples must not declare a seed",
    ),
    (
        "counter_sample_extra_key",
        lambda m: set_sample(m, "L01.counterexample", "note", "extra"),
        "counterexample sample keys are frozen",
    ),
    (
        "counter_extra_key",
        lambda m: set_counterexample(m, "L01", "draft", True),
        "counterexample L01: unexpected keys",
    ),
    (
        "counter_state_flip",
        lambda m: set_counterexample(m, "L01", "expected_state", "FAIL"),
        "counterexample L01: expected_state must be 'PASS'",
    ),
    (
        "counter_override_outside_l11",
        lambda m: add_counter_override(m, "L07"),
        "save_override is only allowed for L11",
    ),
    # round-9 findings: family uniqueness and L06's pinned alpha construction
    (
        "counter_family_duplicated",
        duplicate_counter_family,
        "counterexample family missing or duplicated: 'white_label_background'",
    ),
    (
        "counter_alpha_binding_missing",
        lambda m: counterexample(m, "L06").pop("alpha_binding"),
        "counterexample L06: alpha_binding must be",
    ),
    (
        "counter_alpha_binding_opaque",
        lambda m: set_counterexample(
            m,
            "L06",
            "alpha_binding",
            {"facecolor_alpha": 1.0, "artist_alpha": 1.0},
        ),
        "counterexample L06: alpha_binding must be",
    ),
    (
        "counter_alpha_binding_outside_l06",
        lambda m: add_counter_alpha(
            m, "L05", {"facecolor_alpha": 0.5, "artist_alpha": 1.0}
        ),
        "counterexample L05: alpha_binding is only allowed for L06",
    ),
    # round-10 findings: typed counts and the frozen template metadata
    (
        "counts_total_as_float",
        lambda m: m["counts"].__setitem__("templates_total", 24.0),
        "declared counts do not match computed counts",
    ),
    (
        "counts_missing_key",
        lambda m: m["counts"].pop("samples_total"),
        "declared counts do not match computed counts",
    ),
    (
        "template_chart_drift",
        lambda m: set_template(m, "D01", "chart", "bar"),
        "template D01: chart must equal the frozen value",
    ),
    (
        "template_similarity_drift",
        lambda m: set_template(m, "D01", "similarity_group", "bar"),
        "template D01: similarity_group must equal the frozen value",
    ),
    (
        "template_d01_feature_drop",
        lambda m: template(m, "D01")["features"].remove("single_series"),
        "template D01: features must equal the frozen list",
    ),
    # round-11 findings: the nine neutralized guards and three identity pins
    (
        "template_labels_horizontal_missing",
        lambda m: drop_template_key(m, "D01", "labels_horizontal"),
        "y-label or colorbar-label templates must declare",
    ),
    (
        "template_colorbar_horizontal_missing",
        lambda m: template(m, "D08")["features"].remove("colorbar_horizontal"),
        "colorbar_label requires colorbar_horizontal",
    ),
    (
        "template_rotated_feature",
        lambda m: template(m, "D01")["features"].append("rotated_ylabel"),
        "rotated features are out of scope",
    ),
    (
        "template_target_role_not_feature",
        lambda m: retag_template_role(m, "D03", "legend_inside"),
        "must be one of its features",
    ),
    (
        "template_family_duplicated",
        lambda m: retag_template_family(m, "D02", "line_basic"),
        "template family missing or duplicated",
    ),
    (
        "template_scientific_ticks_feature",
        lambda m: template(m, "D01")["features"].append("scientific_ticks"),
        "scientific_ticks is ambiguous",
    ),
    (
        "template_unicode_minus_feature",
        lambda m: template(m, "H08")["features"].append("unicode_minus"),
        "unicode_minus is forbidden",
    ),
    (
        "template_date_axes_without_horizontal",
        lambda m: template(m, "D12")["features"].remove("date_ticks_horizontal"),
        "date axes must declare date_ticks_horizontal",
    ),
    (
        "counter_family_collides_template",
        lambda m: (
            set_counterexample(m, "L01", "family", "line_basic"),
            set_sample(m, "L01.counterexample", "family", "line_basic"),
        ),
        "counterexample family collides with template",
    ),
    (
        "frozen_at_drift",
        lambda m: m.__setitem__("frozen_at", "2026-11-13"),
        "frozen_at must be",
    ),
    (
        "template_language_drift",
        lambda m: set_template(m, "D01", "language", "zh"),
        "template D01: language must be",
    ),
    (
        "template_family_drift",
        lambda m: retag_template_family(m, "D01", "line_renamed"),
        "template D01: family must equal the frozen value",
    ),
]


@pytest.fixture(scope="module")
def base() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_every_case_has_a_unique_name() -> None:
    names = [case[0] for case in MUTATIONS]
    assert len(names) == len(set(names))
    assert len(MUTATIONS) == 64


def test_frozen_manifest_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    assert result.returncode == 0, result.stderr
    assert "MANIFEST PASS" in result.stdout
    assert "MANIFEST FAIL" not in result.stderr


def test_extra_arguments_are_rejected() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "a.json", "b.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 2
    assert "usage: validate_manifest.py" in result.stderr


def test_verbatim_copy_passes(base: dict, tmp_path: Path) -> None:
    result = run_validator(tmp_path, base)
    assert result.returncode == 0, result.stderr
    assert "MANIFEST PASS" in result.stdout


def test_compact_serialization_passes(base: dict, tmp_path: Path) -> None:
    result = run_validator(tmp_path, base, compact=True)
    assert result.returncode == 0, result.stderr
    assert "MANIFEST PASS" in result.stdout


def test_reordered_copy_passes(base: dict, tmp_path: Path) -> None:
    manifest = copy.deepcopy(base)
    manifest["templates"].reverse()
    manifest["samples"].reverse()
    manifest["counterexamples"].reverse()
    result = run_validator(tmp_path, manifest)
    assert result.returncode == 0, result.stderr
    assert "MANIFEST PASS" in result.stdout


@pytest.mark.parametrize("name,mutate,fragment", MUTATIONS, ids=[c[0] for c in MUTATIONS])
def test_mutation_is_rejected_for_the_intended_reason(
    base: dict, tmp_path: Path, name: str, mutate: Mutation, fragment: str
) -> None:
    manifest = copy.deepcopy(base)
    mutate(manifest)
    result = run_validator(tmp_path, manifest)
    assert result.returncode == 1, f"{name}: expected rc=1, got {result.returncode}"
    assert "MANIFEST FAIL" in result.stderr, f"{name}: no failure banner"
    assert fragment in result.stderr, f"{name}: expected diagnostic not emitted:\n{result.stderr}"
