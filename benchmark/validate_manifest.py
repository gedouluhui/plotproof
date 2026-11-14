"""Validate benchmark/manifest.json and print the authoritative sample counts.

Stdlib only. This script does not generate samples and does not run any detector.

Run:
    python benchmark/validate_manifest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmark" / "manifest.json"


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []

    if data.get("schema_version") != 1:
        fail(errors, "schema_version must be 1")
    if data.get("split_policy") != "template_family":
        fail(errors, "split_policy must be template_family")

    binding = data.get("label_binding")
    if not isinstance(binding, dict):
        fail(errors, "manifest must declare a label_binding object")
    else:
        expected_binding = {
            "layout": "constrained",
            "axis_label_rotation": 0,
            "left_ylabel_ha": "right",
            "right_ylabel_ha": "left",
            "supylabel_ha": "left",
            "colorbar_orientation": "horizontal",
            "colorbar_label_rotation": 0,
            "colorbar_label_role": "xlabel",
            "clean_sample_check": (
                "no page clipping and no D3 candidate with smaller-box coverage >= 0.15"
            ),
        }
        for key, value in expected_binding.items():
            if binding.get(key) != value:
                fail(errors, f"label_binding.{key} must be {value!r}")
        unexpected = sorted(set(binding) - set(expected_binding))
        if unexpected:
            fail(errors, f"label_binding has unexpected keys: {unexpected}")

    templates = data.get("templates", [])
    counters = data.get("counterexamples", [])
    variants = data.get("variants", [])
    defect_variants = data.get("defect_variants", [])
    seeds = data.get("seeds", {})
    clean_seeds = seeds.get("clean", [])
    defect_seeds = seeds.get("defect", [])

    if len(templates) < 24:
        fail(errors, f"need at least 24 templates, found {len(templates)}")
    if len(counters) != 12:
        fail(errors, f"need exactly 12 counterexamples, found {len(counters)}")
    if set(defect_variants) - set(variants):
        fail(errors, "defect_variants must be a subset of variants")
    if len(clean_seeds) != 1:
        fail(errors, "clean seeds must contain exactly one seed")
    if len(defect_seeds) != 2:
        fail(errors, "defect seeds must contain exactly two seeds")

    seen_ids: set[str] = set()
    seen_families: set[str] = set()
    split_counts = {"dev": 0, "holdout": 0}
    for item in templates:
        tid = item.get("id", "")
        family = item.get("family", "")
        split = item.get("split", "")
        if not tid or tid in seen_ids:
            fail(errors, f"template id missing or duplicated: {tid!r}")
        seen_ids.add(tid)
        if not family or family in seen_families:
            fail(errors, f"template family missing or duplicated: {family!r}")
        seen_families.add(family)
        if split not in split_counts:
            fail(errors, f"template {tid}: invalid split {split!r}")
        else:
            split_counts[split] += 1
        features = item.get("features", [])
        if not isinstance(features, list) or not features:
            fail(errors, f"template {tid}: features must be a non-empty list")
        if any("rotated" in str(feature) for feature in features):
            fail(errors, f"template {tid}: rotated features are out of scope in v1")
        if "scientific_ticks" in features:
            fail(
                errors,
                f"template {tid}: scientific_ticks is ambiguous; declare log_ticks_plain_text",
            )
        is_log = any(str(feature).startswith("log_") for feature in features)
        family_lower = str(item.get("family", "")).lower()
        if ("log" in family_lower or is_log) and "log_ticks_plain_text" not in features:
            fail(
                errors,
                f"template {tid}: log axes must declare log_ticks_plain_text "
                "(default mathdefault labels are out of scope)",
            )
        if family_lower.split("_")[0] in {"date", "datetime"} and "date_ticks_horizontal" not in features:
            fail(errors, f"template {tid}: date axes must declare date_ticks_horizontal")
        needs_horizontal = any("ylabel" in str(feature) for feature in features) or (
            "colorbar_label" in features
        )
        if needs_horizontal and item.get("labels_horizontal") is not True:
            fail(
                errors,
                f"template {tid}: y-label or colorbar-label templates must declare "
                '"labels_horizontal": true (rotated labels are out of scope in v1)',
            )
        if "labels_horizontal" in item and not isinstance(item["labels_horizontal"], bool):
            fail(errors, f"template {tid}: labels_horizontal must be a boolean")
        if "colorbar_label" in features and "colorbar_horizontal" not in features:
            fail(
                errors,
                f"template {tid}: colorbar_label requires colorbar_horizontal "
                "(a vertical colorbar with a horizontal label overlaps its tick labels)",
            )
        if "colorbar_horizontal" in features and "colorbar" not in features:
            fail(errors, f"template {tid}: colorbar_horizontal requires a colorbar feature")
        formatter = item.get("tick_formatter", "")
        if "$" in str(formatter):
            fail(errors, f"template {tid}: tick_formatter must not contain '$' "
                         "(mathtext is out of scope)")
        if "mathtext" in str(formatter).lower() and "usemathtext=false" not in str(
            formatter
        ).lower():
            fail(errors, f"template {tid}: tick_formatter must not use mathtext")
        if "log_ticks_plain_text" in features:
            if formatter != "FuncFormatter('{:g}'.format)":
                fail(
                    errors,
                    f"template {tid}: log_ticks_plain_text requires the exact binding "
                    "\"FuncFormatter('{:g}'.format)\"",
                )
        if "scientific_offset" in features:
            if formatter != "ScalarFormatter(useMathText=False)":
                fail(
                    errors,
                    f"template {tid}: scientific_offset requires the exact binding "
                    "\"ScalarFormatter(useMathText=False)\"",
                )
        note = str(item.get("note", "")).strip()
        if "date_ticks_horizontal" in features and not note:
            fail(errors, f"template {tid}: date_ticks_horizontal requires a scope note")
        if any(str(feature).startswith("date_ticks_") for feature in features) and (
            "date_ticks_horizontal" not in features
        ):
            fail(errors, f"template {tid}: date ticks must declare date_ticks_horizontal")
        if ("log_ticks_plain_text" in features or "scientific_offset" in features) and not note:
            fail(errors, f"template {tid}: plain tick labels require an explicit scope note")
        target_role = item.get("target_role", "")
        if not isinstance(target_role, str) or not target_role:
            fail(errors, f"template {tid}: target_role must be a non-empty string")

    if split_counts != {"dev": 12, "holdout": 12}:
        fail(errors, f"split must be 12 dev / 12 holdout, found {split_counts}")

    seen_counter_ids: set[str] = set()
    counter_splits = {"dev": 0, "holdout": 0}
    for item in counters:
        cid = item.get("id", "")
        if not cid or cid in seen_counter_ids:
            fail(errors, f"counterexample id missing or duplicated: {cid!r}")
        seen_counter_ids.add(cid)
        if item.get("family", "") in seen_families:
            fail(errors, f"counterexample family collides with template: {item.get('family')!r}")
        split = item.get("split", "")
        if split not in counter_splits:
            fail(errors, f"counterexample {cid}: invalid split {split!r}")
        else:
            counter_splits[split] += 1
        if item.get("expected_state") not in {"PASS", "UNKNOWN"}:
            fail(errors, f"counterexample {cid}: expected_state must be PASS or UNKNOWN")
        if cid == "L04":
            if "labels_horizontal" in item:
                fail(
                    errors,
                    "counterexample L04: the rotated-text counterexample must not "
                    "declare labels_horizontal",
                )
        elif item.get("labels_horizontal") is not True:
            fail(
                errors,
                f"counterexample {cid}: must declare "
                '"labels_horizontal": true (rotated labels are out of scope in v1)',
            )
        fixed_states = {"L04": "UNKNOWN", "L06": "UNKNOWN"}
        if cid in fixed_states and item.get("expected_state") != fixed_states[cid]:
            fail(
                errors,
                f"counterexample {cid}: expected_state must be {fixed_states[cid]}",
            )
        if split == "holdout" and item.get("expected_state") != "PASS":
            fail(errors, f"counterexample {cid}: holdout counterexamples must expect PASS")

    if counter_splits != {"dev": 6, "holdout": 6}:
        fail(errors, f"counterexamples must be 6 dev / 6 holdout, found {counter_splits}")

    samples_per_template = len(clean_seeds) + len(defect_variants) * len(defect_seeds)
    clean_samples = len(templates) * len(clean_seeds)
    defect_samples = len(templates) * len(defect_variants) * len(defect_seeds)
    samples_total = clean_samples + defect_samples + len(counters)
    holdout_templates = [t for t in templates if t.get("split") == "holdout"]
    holdout_samples = len(holdout_templates) * samples_per_template + counter_splits["holdout"]
    per_class_total = len(templates) * len(defect_seeds)
    per_class_holdout = len(holdout_templates) * len(defect_seeds)

    counts = {
        "templates_total": len(templates),
        "templates_dev": split_counts["dev"],
        "templates_holdout": split_counts["holdout"],
        "samples_per_template": samples_per_template,
        "clean_samples_total": clean_samples,
        "defect_samples_total": defect_samples,
        "counterexamples_total": len(counters),
        "samples_total": samples_total,
        "holdout_samples": holdout_samples,
        "defect_instances_total": defect_samples,
        "defect_instances_holdout": len(holdout_templates)
        * len(defect_variants)
        * len(defect_seeds),
        "per_defect_class_total": per_class_total,
        "per_defect_class_holdout": per_class_holdout,
    }
    declared = data.get("counts")
    if declared is None:
        fail(errors, "manifest must declare counts")
    elif declared != counts:
        fail(errors, f"declared counts do not match computed counts:\n{declared}\n{counts}")

    samples = data.get("samples", [])
    if len(samples) != samples_total:
        fail(errors, f"need {samples_total} sample records, found {len(samples)}")

    variant_to_class = {
        "clip": "clipped_text",
        "occlude": "occluded_text",
        "overlap": "overlapping_text",
        "missing_glyph": "missing_glyph",
    }
    template_by_id = {t.get("id"): t for t in templates}
    counter_by_id = {c.get("id"): c for c in counters}
    expected_sample_ids: set[str] = set()
    for template in templates:
        tid = template.get("id")
        for seed in clean_seeds:
            expected_sample_ids.add(f"{tid}.clean.s{seed}")
        for variant in defect_variants:
            for seed in defect_seeds:
                expected_sample_ids.add(f"{tid}.{variant}.s{seed}")
    for counter in counters:
        expected_sample_ids.add(f"{counter.get('id')}.counterexample")

    seen_sample_ids: set[str] = set()
    sample_counts = {
        "clean": 0,
        "defect": 0,
        "counterexample": 0,
        "holdout": 0,
        "defect_holdout": 0,
    }
    defect_by_class_total: dict[str, int] = {}
    defect_by_class_holdout: dict[str, int] = {}
    for sample in samples:
        sid = sample.get("id", "")
        if not sid or sid in seen_sample_ids:
            fail(errors, f"sample id missing or duplicated: {sid!r}")
        seen_sample_ids.add(sid)
        variant = sample.get("variant", "")
        split = sample.get("split", "")
        expected_state = sample.get("expected_state", "")
        if variant not in variants and variant != "counterexample":
            fail(errors, f"sample {sid}: invalid variant {variant!r}")
            continue
        if split not in split_counts:
            fail(errors, f"sample {sid}: invalid split {split!r}")
        if expected_state not in {"PASS", "FAIL", "UNKNOWN"}:
            fail(errors, f"sample {sid}: invalid expected_state {expected_state!r}")
        if variant == "counterexample":
            cid = sample.get("counterexample_id", "")
            counter = counter_by_id.get(cid)
            if counter is None:
                fail(errors, f"sample {sid}: unknown counterexample {cid!r}")
            else:
                if sample.get("split") != counter.get("split"):
                    fail(errors, f"sample {sid}: split disagrees with counterexample")
                if expected_state != counter.get("expected_state"):
                    fail(errors, f"sample {sid}: expected_state disagrees with counterexample")
            sample_counts["counterexample"] += 1
            if split == "holdout":
                sample_counts["holdout"] += 1
            continue

        tid = sample.get("template_id", "")
        template = template_by_id.get(tid)
        if template is None:
            fail(errors, f"sample {sid}: unknown template {tid!r}")
            continue
        if sample.get("split") != template.get("split"):
            fail(errors, f"sample {sid}: split disagrees with template {tid}")
        if sample.get("seed") not in (clean_seeds if variant == "clean" else defect_seeds):
            fail(errors, f"sample {sid}: seed not allowed for variant {variant}")
        target_role = sample.get("target_role", "")
        if not isinstance(target_role, str) or not target_role:
            fail(errors, f"sample {sid}: target_role must be a non-empty string")
        elif target_role != template.get("target_role"):
            fail(errors, f"sample {sid}: target_role disagrees with template {tid}")
        if variant == "clean":
            if expected_state != "PASS":
                fail(errors, f"sample {sid}: clean samples must expect PASS")
            if sample.get("defect_class") is not None:
                fail(errors, f"sample {sid}: clean samples must not declare a defect_class")
            sample_counts["clean"] += 1
        else:
            if expected_state != "FAIL":
                fail(errors, f"sample {sid}: defect samples must expect FAIL")
            defect_class = sample.get("defect_class", "")
            if defect_class != variant_to_class.get(variant):
                fail(errors, f"sample {sid}: defect_class {defect_class!r} does not match {variant}")
            defect_by_class_total[defect_class] = defect_by_class_total.get(defect_class, 0) + 1
            sample_counts["defect"] += 1
            if split == "holdout":
                sample_counts["defect_holdout"] += 1
                defect_by_class_holdout[defect_class] = (
                    defect_by_class_holdout.get(defect_class, 0) + 1
                )
        if split == "holdout":
            sample_counts["holdout"] += 1

    if seen_sample_ids != expected_sample_ids:
        missing = sorted(expected_sample_ids - seen_sample_ids)
        extra = sorted(seen_sample_ids - expected_sample_ids)
        fail(errors, f"sample id set mismatch; missing={missing[:5]} extra={extra[:5]}")

    expected_sample_counts = {
        "clean": counts["clean_samples_total"],
        "defect": counts["defect_samples_total"],
        "counterexample": counts["counterexamples_total"],
        "holdout": counts["holdout_samples"],
        "defect_holdout": counts["defect_instances_holdout"],
    }
    if sample_counts != expected_sample_counts:
        fail(errors, f"sample record counts do not match: {sample_counts} != {expected_sample_counts}")

    for defect_class in variant_to_class.values():
        if defect_by_class_total.get(defect_class, 0) != per_class_total:
            fail(errors, f"{defect_class}: expected {per_class_total} total defect records")
        if defect_by_class_holdout.get(defect_class, 0) != per_class_holdout:
            fail(errors, f"{defect_class}: expected {per_class_holdout} holdout defect records")

    for key, value in counts.items():
        print(f"{key}={value}")

    if errors:
        print("MANIFEST FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("MANIFEST PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
