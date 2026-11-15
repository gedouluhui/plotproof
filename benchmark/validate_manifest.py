"""Validate benchmark/manifest.json and print the authoritative sample counts.

Stdlib only. This script does not generate samples and does not run any detector.

Run:
    python benchmark/validate_manifest.py [path/to/manifest.json]

With no argument it validates the frozen benchmark/manifest.json. The optional
path exists so tests can run the same validator against mutated copies; the
release gate always calls it with no argument.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmark" / "manifest.json"


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def strict_equal(value: object, expected: object) -> bool:
    """Compare JSON values including scalar types.

    JSON ``0``/``1`` must not satisfy a boolean binding: Python treats
    ``0 == False`` as true, which would let ``"transparent": 0`` pass a
    ``false`` requirement. Containers compare recursively so nested ints,
    floats and booleans keep their JSON types.
    """
    if isinstance(expected, bool):
        return isinstance(value, bool) and value is expected
    if isinstance(expected, list):
        return (
            isinstance(value, list)
            and len(value) == len(expected)
            and all(strict_equal(v, e) for v, e in zip(value, expected))
        )
    if isinstance(expected, dict):
        return (
            isinstance(value, dict)
            and set(value) == set(expected)
            and all(strict_equal(value[k], expected[k]) for k in expected)
        )
    if expected is None:
        return value is None
    if isinstance(expected, (int, float)):
        return type(value) is type(expected) and value == expected
    return isinstance(value, str) and value == expected


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: validate_manifest.py [path/to/manifest.json]", file=sys.stderr)
        return 2
    target = Path(sys.argv[1]) if len(sys.argv) == 2 else MANIFEST
    data = json.loads(target.read_text(encoding="utf-8"))
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
            "axis_labelpad_pt": 4.0,
            "left_ylabel_ha": "right",
            "right_ylabel_ha": "left",
            "supylabel_ha": "left",
            "colorbar_orientation": "horizontal",
            "colorbar_label_rotation": 0,
            "colorbar_label_role": "xlabel",
            "clean_sample_check": (
                "no page clipping and no D3 candidate with smaller-union coverage >= 0.15"
            ),
        }
        for key, value in expected_binding.items():
            if not strict_equal(binding.get(key), value):
                fail(errors, f"label_binding.{key} must be {value!r}")
        unexpected = sorted(set(binding) - set(expected_binding))
        if unexpected:
            fail(errors, f"label_binding has unexpected keys: {unexpected}")

    save_binding = data.get("save_binding")
    if not isinstance(save_binding, dict):
        fail(errors, "manifest must declare a save_binding object")
    else:
        expected_save = {
            "matplotlib_version": "3.10.8",
            "backend": "Agg",
            "pdf_fonttype": 42,
            "figure_dpi": 100,
            "figure_size_inches": [10.0, 6.0],
            "base_font_size_pt": 10.0,
            "layout": "constrained",
            "axes_unicode_minus": False,
            "transparent": False,
            "font_family_ascii": "DejaVu Sans",
            "font_family_cjk": "Noto Sans CJK SC",
            "cjk_font_scope": "per-text fontproperties",
            "bbox_inches": None,
            "pad_inches": None,
            "pad_inches_effective": 0.1,
        }
        for key, value in expected_save.items():
            if not strict_equal(save_binding.get(key), value):
                fail(errors, f"save_binding.{key} must be {value!r}")
        unexpected = sorted(set(save_binding) - set(expected_save))
        if unexpected:
            fail(errors, f"save_binding has unexpected keys: {unexpected}")

    expected_template_splits = {
        **{f"D{i:02d}": "dev" for i in range(1, 13)},
        **{f"H{i:02d}": "holdout" for i in range(1, 13)},
    }
    expected_counter_splits = {
        **{f"L{i:02d}": "dev" for i in range(1, 7)},
        **{f"L{i:02d}": "holdout" for i in range(7, 13)},
    }
    expected_counter_states = {cid: "PASS" for cid in expected_counter_splits}
    expected_counter_states["L04"] = "UNKNOWN"
    expected_counter_states["L06"] = "UNKNOWN"
    # Round-9: L06's translucency must be facecolor-only at alpha 0.5 with an
    # opaque artist, so the effective alpha is 0.50 and the D2 medium band is
    # exercised; an unpinned construction could silently become opaque.
    expected_counter_alpha_binding = {
        "L06": {"facecolor_alpha": 0.5, "artist_alpha": 1.0}
    }

    # Hard-coded identities: a template must not change what it measures.
    expected_template_roles = {tid: "title" for tid in expected_template_splits}
    expected_template_roles["H11"] = "suptitle"
    # Round-10: the descriptive and generative template fields are frozen
    # verbatim too. features drive the generator's construction; chart and
    # similarity_group are part of the recorded inventory. A coordinated edit
    # to a declared feature must fail here even when it stays self-consistent.
    expected_template_metadata = {
        "D01": ("line", "line", ["title", "xlabel", "ylabel", "xticks", "yticks", "legend_inside", "single_series"]),
        "D02": ("line", "line", ["title", "xlabel", "ylabel", "legend_inside", "three_series", "y_unit"]),
        "D03": ("bar", "bar", ["title", "xlabel", "ylabel", "xticks", "value_labels"]),
        "D04": ("bar", "bar", ["title", "xlabel", "ylabel", "legend_inside", "two_groups", "xticks"]),
        "D05": ("scatter", "scatter", ["title", "xlabel", "ylabel", "annotations", "grid"]),
        "D06": ("histogram", "distribution", ["title", "xlabel", "ylabel", "xticks"]),
        "D07": ("box", "distribution", ["title", "xlabel", "ylabel", "xticks", "four_groups"]),
        "D08": ("heatmap", "matrix", ["title", "colorbar", "colorbar_label", "xticks", "yticks", "colorbar_horizontal"]),
        "D09": ("pie", "part_to_whole", ["title", "slice_labels", "percent_labels"]),
        "D10": ("errorbar", "line", ["title", "xlabel", "ylabel", "legend_inside", "five_points"]),
        "D11": ("line", "line", ["title", "xlabel", "ylabel", "log_y", "log_ticks_plain_text"]),
        "D12": ("line", "time", ["title", "xlabel", "ylabel", "date_ticks_horizontal"]),
        "H01": ("violin", "distribution", ["title", "xlabel", "ylabel", "xticks", "four_groups"]),
        "H02": ("bar", "bar", ["title", "xlabel", "ylabel", "legend_inside", "three_stacks", "xticks"]),
        "H03": ("barh", "bar", ["title", "xlabel", "long_category_labels", "six_bars"]),
        "H04": ("contour", "matrix", ["title", "colorbar", "colorbar_label", "xticks", "yticks", "colorbar_horizontal"]),
        "H05": ("line", "line", ["title", "xlabel", "two_ylabels", "legend_inside", "dual_y"]),
        "H06": ("area", "area", ["title", "xlabel", "ylabel", "legend_inside", "two_series", "stacked"]),
        "H07": ("line", "line", ["title", "xlabel", "ylabel", "forty_xticks", "minor_ticks"]),
        "H08": ("line", "line", ["title_cjk", "title", "xlabel_cjk", "ylabel_en_unit", "negative_values", "ascii_minus", "legend_inside"]),
        "H09": ("line", "line", ["title", "xlabel", "ylabel", "scientific_offset", "xticks"]),
        "H10": ("line", "line", ["title", "xlabel", "ylabel", "legend_below_axes", "bbox_to_anchor"]),
        "H11": ("subplots_1x2", "layout", ["suptitle", "shared_xlabel", "shared_ylabel", "two_axes", "legends"]),
        "H12": ("bar", "bar", ["title_cjk", "title", "ylabel_cjk_unit", "negative_values", "ascii_minus", "thousands_separator"]),
    }
    expected_formatters = {
        "D11": "FuncFormatter('{:g}'.format)",
        "H09": "ScalarFormatter(useMathText=False)",
        "H12": "FuncFormatter('{:,}'.format)",
    }
    expected_tick_bindings = {
        "H07": {
            "x_major_ticks": list(range(40)),
            "x_limits": [-0.5, 39.5],
            "x_minor_subdivisions": 4,
            "x_label_rotation": 0,
            "x_label_format": "{:d}",
        },
        "H12": {
            "y_limits": [-10000, 10000],
            "y_major_ticks": [-10000, -5000, 0, 5000, 10000],
            "y_label_rotation": 0,
            "y_label_format": "{:,d}",
        },
    }
    template_required_keys = {
        "id",
        "family",
        "split",
        "chart",
        "language",
        "similarity_group",
        "features",
        "target_role",
    }
    template_optional_keys = {"labels_horizontal", "note", "tick_formatter", "tick_binding"}
    counter_required_keys = {"id", "family", "split", "expected_state", "note"}
    counter_optional_keys = {"alpha_binding", "labels_horizontal", "save_override"}
    template_sample_keys = {
        "id",
        "template_id",
        "family",
        "split",
        "variant",
        "seed",
        "target_role",
        "defect_class",
        "expected_state",
    }
    counter_sample_keys = {
        "id",
        "counterexample_id",
        "family",
        "split",
        "variant",
        "seed",
        "target_role",
        "defect_class",
        "expected_state",
    }

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
    if variants != ["clean", "clip", "occlude", "overlap", "missing_glyph"]:
        fail(errors, f"variants are frozen; found {variants!r}")
    if defect_variants != ["clip", "occlude", "overlap", "missing_glyph"]:
        fail(errors, f"defect_variants are frozen; found {defect_variants!r}")
    if seeds != {"clean": [1], "defect": [1, 2]}:
        fail(
            errors,
            f'seeds must be exactly {{"clean": [1], "defect": [1, 2]}}, found {seeds!r}',
        )

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
        if tid not in expected_template_splits:
            fail(errors, f"unexpected template id {tid!r}; the template set is frozen")
        elif split != expected_template_splits[tid]:
            fail(
                errors,
                f"template {tid}: split must be {expected_template_splits[tid]!r}",
            )
        if not family or family in seen_families:
            fail(errors, f"template family missing or duplicated: {family!r}")
        seen_families.add(family)
        if split not in split_counts:
            fail(errors, f"template {tid}: invalid split {split!r}")
        else:
            split_counts[split] += 1
        keys = set(item)
        missing = sorted(template_required_keys - keys)
        extra = sorted(keys - (template_required_keys | template_optional_keys))
        if missing:
            fail(errors, f"template {tid}: missing keys {missing}")
        if extra:
            fail(errors, f"template {tid}: unexpected keys {extra}")
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
        if "unicode_minus" in features:
            fail(
                errors,
                f"template {tid}: unicode_minus is forbidden (PDFium drops U+2212 under "
                "the default fonttype); declare ascii_minus",
            )
        if "negative_values" in features and "ascii_minus" not in features:
            fail(errors, f"template {tid}: negative_values requires ascii_minus")
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
        if "labels_horizontal" in item and item["labels_horizontal"] is not True:
            fail(
                errors,
                f"template {tid}: v1 has no rotated template labels; "
                "labels_horizontal must be true when declared",
            )
        if "colorbar_label" in features and "colorbar_horizontal" not in features:
            fail(
                errors,
                f"template {tid}: colorbar_label requires colorbar_horizontal "
                "(a vertical colorbar with a horizontal label overlaps its tick labels)",
            )
        if "colorbar_horizontal" in features and "colorbar" not in features:
            fail(errors, f"template {tid}: colorbar_horizontal requires a colorbar feature")
        formatter = item.get("tick_formatter")
        if "$" in str(formatter):
            fail(errors, f"template {tid}: tick_formatter must not contain '$' "
                         "(mathtext is out of scope)")
        if "mathtext" in str(formatter).lower() and "usemathtext=false" not in str(
            formatter
        ).lower():
            fail(errors, f"template {tid}: tick_formatter must not use mathtext")
        expected_formatter = expected_formatters.get(tid)
        if not strict_equal(formatter, expected_formatter):
            fail(
                errors,
                f"template {tid}: tick_formatter must be {expected_formatter!r}",
            )
        tick_binding = item.get("tick_binding")
        expected_ticks = expected_tick_bindings.get(tid)
        if expected_ticks is None:
            if tick_binding is not None:
                fail(
                    errors,
                    f"template {tid}: tick_binding is only allowed for H07 and H12",
                )
        elif not strict_equal(tick_binding, expected_ticks):
            fail(errors, f"template {tid}: tick_binding does not match the frozen binding")
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
        if "thousands_separator" in features and formatter != "FuncFormatter('{:,}'.format)":
            fail(
                errors,
                f"template {tid}: thousands_separator requires the exact binding "
                "\"FuncFormatter('{:,}'.format)\"",
            )
        if formatter == "FuncFormatter('{:,}'.format)" and "thousands_separator" not in features:
            fail(
                errors,
                f"template {tid}: the thousands-separator formatter requires the "
                "thousands_separator feature",
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
        elif target_role not in features:
            fail(
                errors,
                f"template {tid}: target_role {target_role!r} must be one of its features",
            )
        if tid in expected_template_roles:
            expected_role = expected_template_roles[tid]
            if target_role != expected_role:
                fail(
                    errors,
                    f"template {tid}: target_role must be {expected_role!r}",
                )
        expected_metadata = expected_template_metadata.get(tid)
        if expected_metadata is not None:
            chart, similarity_group, expected_features = expected_metadata
            if item.get("chart") != chart:
                fail(
                    errors,
                    f"template {tid}: chart must equal the frozen value {chart!r}",
                )
            if item.get("similarity_group") != similarity_group:
                fail(
                    errors,
                    f"template {tid}: similarity_group must equal the frozen value "
                    f"{similarity_group!r}",
                )
            if not strict_equal(item.get("features"), expected_features):
                fail(
                    errors,
                    f"template {tid}: features must equal the frozen list "
                    f"{expected_features!r}",
                )

    if seen_ids != set(expected_template_splits):
        fail(
            errors,
            "template id set mismatch: "
            f"missing={sorted(set(expected_template_splits) - seen_ids)} "
            f"extra={sorted(seen_ids - set(expected_template_splits))}",
        )

    if split_counts != {"dev": 12, "holdout": 12}:
        fail(errors, f"split must be 12 dev / 12 holdout, found {split_counts}")

    seen_counter_ids: set[str] = set()
    seen_counter_families: set[str] = set()
    counter_splits = {"dev": 0, "holdout": 0}
    for item in counters:
        cid = item.get("id", "")
        if not cid or cid in seen_counter_ids:
            fail(errors, f"counterexample id missing or duplicated: {cid!r}")
        seen_counter_ids.add(cid)
        keys = set(item)
        missing = sorted(counter_required_keys - keys)
        extra = sorted(keys - (counter_required_keys | counter_optional_keys))
        if missing:
            fail(errors, f"counterexample {cid}: missing keys {missing}")
        if extra:
            fail(errors, f"counterexample {cid}: unexpected keys {extra}")
        family = item.get("family", "")
        if not family or family in seen_counter_families:
            fail(errors, f"counterexample family missing or duplicated: {family!r}")
        seen_counter_families.add(family)
        if family in seen_families:
            fail(errors, f"counterexample family collides with template: {family!r}")
        split = item.get("split", "")
        if split not in counter_splits:
            fail(errors, f"counterexample {cid}: invalid split {split!r}")
        else:
            counter_splits[split] += 1
        if item.get("expected_state") not in {"PASS", "UNKNOWN"}:
            fail(errors, f"counterexample {cid}: expected_state must be PASS or UNKNOWN")
        if cid not in expected_counter_splits:
            fail(
                errors,
                f"unexpected counterexample id {cid!r}; the counterexample set is frozen",
            )
        elif split != expected_counter_splits[cid]:
            fail(
                errors,
                f"counterexample {cid}: split must be {expected_counter_splits[cid]!r}",
            )
        if item.get("expected_state") != expected_counter_states.get(cid):
            fail(
                errors,
                f"counterexample {cid}: expected_state must be "
                f"{expected_counter_states.get(cid)!r}",
            )
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
        expected_alpha = expected_counter_alpha_binding.get(cid)
        if expected_alpha is not None:
            if not strict_equal(item.get("alpha_binding"), expected_alpha):
                fail(
                    errors,
                    f"counterexample {cid}: alpha_binding must be "
                    f"{json.dumps(expected_alpha, sort_keys=True)}",
                )
        elif "alpha_binding" in item:
            fail(
                errors,
                f"counterexample {cid}: alpha_binding is only allowed for L06",
            )
        override = item.get("save_override")
        if cid == "L11":
            if override != {"bbox_inches": "tight", "pad_inches_effective": 0.1}:
                fail(
                    errors,
                    "counterexample L11 (tight-bbox counterexample) must declare "
                    'save_override {"bbox_inches": "tight", "pad_inches_effective": 0.1}',
                )
        elif override is not None:
            fail(errors, f"counterexample {cid}: save_override is only allowed for L11")

    if seen_counter_ids != set(expected_counter_splits):
        fail(
            errors,
            "counterexample id set mismatch: "
            f"missing={sorted(set(expected_counter_splits) - seen_counter_ids)} "
            f"extra={sorted(seen_counter_ids - set(expected_counter_splits))}",
        )

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
    elif not strict_equal(declared, counts):
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
            if set(sample) != counter_sample_keys:
                fail(errors, f"sample {sid}: counterexample sample keys are frozen")
            cid = sample.get("counterexample_id", "")
            counter = counter_by_id.get(cid)
            if sid != f"{cid}.counterexample":
                fail(
                    errors,
                    f"sample {sid}: id must be '<counterexample>.counterexample'",
                )
            if sample.get("seed") is not None:
                fail(errors, f"sample {sid}: counterexample samples must not declare a seed")
            if sample.get("target_role") is not None:
                fail(
                    errors,
                    f"sample {sid}: counterexample samples must not declare target_role",
                )
            if sample.get("defect_class") is not None:
                fail(
                    errors,
                    f"sample {sid}: counterexample samples must not declare defect_class",
                )
            if counter is None:
                fail(errors, f"sample {sid}: unknown counterexample {cid!r}")
            else:
                if sample.get("family") != counter.get("family"):
                    fail(errors, f"sample {sid}: family disagrees with counterexample")
                if sample.get("split") != counter.get("split"):
                    fail(errors, f"sample {sid}: split disagrees with counterexample")
                if expected_state != counter.get("expected_state"):
                    fail(errors, f"sample {sid}: expected_state disagrees with counterexample")
            sample_counts["counterexample"] += 1
            if split == "holdout":
                sample_counts["holdout"] += 1
            continue

        if set(sample) != template_sample_keys:
            fail(errors, f"sample {sid}: sample keys are frozen")
        tid = sample.get("template_id", "")
        template = template_by_id.get(tid)
        if template is None:
            fail(errors, f"sample {sid}: unknown template {tid!r}")
            continue
        if sid != f"{tid}.{variant}.s{sample.get('seed')}":
            fail(
                errors,
                f"sample {sid}: id must be '<template>.<variant>.s<seed>'",
            )
        if sample.get("family") != template.get("family"):
            fail(errors, f"sample {sid}: family disagrees with template {tid}")
        if sample.get("split") != template.get("split"):
            fail(errors, f"sample {sid}: split disagrees with template {tid}")
        seed_value = sample.get("seed")
        if type(seed_value) is not int:
            fail(errors, f"sample {sid}: seed must be an integer")
        elif seed_value not in (clean_seeds if variant == "clean" else defect_seeds):
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
