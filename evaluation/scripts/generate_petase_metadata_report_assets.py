#!/usr/bin/env python3
# flake8: noqa
"""Generate charts and summary metrics for the PETase metadata usability report."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = Path(__file__).resolve().parents[1] / "datasets" / "PETase_papers_json"
FIGURES_DIR = DATA_DIR / "figures"

SUBSTRATE_KEYS = ["type", "crystallinity", "Tg", "avg_molecular_weight"]
REACTION_KEYS = [
    "reactor_volume",
    "enzyme_loading",
    "substrate_solid_loading",
    "buffer_type_and_concentration",
    "pH",
    "temperature",
    "agitation_rate",
    "reaction_time",
]
KINETIC_KEYS = [
    "Tm",
    "T0.5",
    "kcat",
    "Km",
    "specific_activity",
    "initial_rate",
    "does_the_study_use_proxy_substrate_or_actual_PET_substrate",
    "does_the_product_analysis_use_HPLC_as_standard_quantification",
    "how_are_degraded_PET_monomers_quantified_absorbance_or_fluorometric",
    "what_are_the_units_of_activity",
    "is_depolymerisation_efficacy_endpoint_or_time_resolved",
]


def get_type(value: Any) -> str:
    if isinstance(value, dict):
        return "multi-assay / nested"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "single value / text"
    if value is None:
        return "missing"
    return type(value).__name__


def is_na(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().upper() in {"NA", "N/A", "NOT AVAILABLE", ""}:
        return True
    if isinstance(value, list):
        return all(is_na(item) for item in value) if value else True
    if isinstance(value, dict):
        return all(is_na(item) for item in value.values()) if value else True
    return False


def flatten_keys(value: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            keys |= flatten_keys(item, path)
    elif isinstance(value, list):
        for item in value:
            keys |= flatten_keys(item, prefix)
    return keys


def load_analysis() -> dict[str, Any]:
    files = sorted(DATA_DIR.glob("*.json"))
    records: list[dict[str, Any]] = []
    type_counts: dict[str, Counter] = defaultdict(Counter)
    assay_keys: dict[str, set[str]] = defaultdict(set)
    unit_counter: Counter = Counter()
    kinetic_populated: dict[str, int] = {}

    for file_path in files:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        substrate = data.get("substrate_property", {})
        enzyme = data.get("enzyme_property", {})
        reaction = data.get("reaction_condition_lab_scale", {})
        kinetic = data.get("kinetic_parameters_and_measurement_analytics", {})

        units = kinetic.get("what_are_the_units_of_activity", [])
        records.append(
            {
                "doi": data.get("doi", file_path.stem),
                "substrates": len(substrate.get("type", []) or []),
                "enzymes": len(enzyme.get("type", []) or []),
                "activity_units": len(units or []) if isinstance(units, list) else 0,
                "paths": len(flatten_keys(data)),
                "hplc": "yes"
                in str(kinetic.get("does_the_product_analysis_use_HPLC_as_standard_quantification", "")).lower(),
            }
        )

        for key in SUBSTRATE_KEYS:
            if key in substrate:
                type_counts[f"substrate: {key}"][get_type(substrate.get(key))] += 1

        for key in REACTION_KEYS:
            value = reaction.get(key)
            type_counts[f"reaction: {key}"][get_type(value)] += 1
            if isinstance(value, dict):
                assay_keys[key].update(value.keys())

        for key in KINETIC_KEYS:
            if key in kinetic:
                type_counts[f"measurement: {key}"][get_type(kinetic.get(key))] += 1

        if isinstance(units, list):
            for unit in units:
                unit_counter[str(unit).strip()] += 1

    for key in ["Tm", "T0.5", "kcat", "Km", "specific_activity", "initial_rate"]:
        populated = 0
        for file_path in files:
            kinetic = json.loads(file_path.read_text(encoding="utf-8")).get(
                "kinetic_parameters_and_measurement_analytics", {}
            )
            if not is_na(kinetic.get(key)):
                populated += 1
        kinetic_populated[key] = populated

    return {
        "files": files,
        "records": records,
        "type_counts": type_counts,
        "assay_key_counts": {key: len(values) for key, values in assay_keys.items()},
        "unit_counter": unit_counter,
        "kinetic_populated": kinetic_populated,
    }


def save_usability_dashboard(analysis: dict[str, Any]) -> None:
    records = analysis["records"]
    type_counts = analysis["type_counts"]
    unit_counter = analysis["unit_counter"]
    n = len(records)
    inconsistent_fields = sum(1 for counts in type_counts.values() if len(counts) > 1)
    tracked_fields = len(type_counts)
    hplc = sum(record["hplc"] for record in records)

    labels = [
        "Same broad sections",
        "Expected fields present",
        "HPLC-based quantification",
        "Fields needing format normalization",
        "Unique activity-unit terms",
    ]
    values = [100, 100, 100 * hplc / n, 100 * inconsistent_fields / tracked_fields, len(unit_counter)]
    value_labels = [
        "100%",
        "100%",
        f"{hplc}/{n} ({100 * hplc / n:.0f}%)",
        f"{inconsistent_fields}/{tracked_fields} ({100 * inconsistent_fields / tracked_fields:.0f}%)",
        str(len(unit_counter)),
    ]
    colors = ["#4C78A8", "#4C78A8", "#72B7B2", "#F58518", "#E45756"]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    y_positions = range(len(labels))
    ax.barh(y_positions, values, color=colors)
    ax.set_yticks(y_positions, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Percent of papers / count, as noted")
    ax.set_title("PETase Metadata Dataset: Usability and Normalization Indicators")
    for index, (value, label) in enumerate(zip(values, value_labels)):
        ax.text(value + 1, index, label, va="center", fontsize=10)
    ax.set_xlim(0, max(110, len(unit_counter) + 10))
    ax.text(0, -0.8, f"Source: {n} expert-curated PETase paper JSON files", fontsize=9, color="dimgray")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "petase_metadata_usability_dashboard.png", dpi=220)
    plt.close(fig)


def save_complexity_distribution(analysis: dict[str, Any]) -> None:
    records = sorted(analysis["records"], key=lambda record: record["paths"])
    n = len(records)
    labels = [record["doi"].replace("10.", "") for record in records]

    fig, ax1 = plt.subplots(figsize=(12, 7))
    x_positions = range(n)
    ax1.bar(x_positions, [record["paths"] for record in records], color="#4C78A8", label="Nested metadata paths")
    ax1.set_ylabel("Nested metadata paths (higher = more complex)")
    ax1.set_xlabel("Paper DOI (shortened)")
    ax1.set_title("Cross-Paper Metadata Complexity Distribution")
    ax1.set_xticks(x_positions, labels, rotation=60, ha="right", fontsize=8)

    ax2 = ax1.twinx()
    ax2.plot(x_positions, [record["enzymes"] for record in records], color="#F58518", marker="o", label="Enzyme variants")
    ax2.plot(x_positions, [record["substrates"] for record in records], color="#54A24B", marker="s", label="Substrate types")
    ax2.set_ylabel("Count per paper")

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    ax1.text(
        0,
        max(record["paths"] for record in records) * 1.04,
        f"Source: {n} expert-curated PETase paper JSON files",
        fontsize=9,
        color="dimgray",
    )
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "petase_cross_paper_complexity_distribution.png", dpi=220)
    plt.close(fig)


def save_normalization_field_chart(analysis: dict[str, Any]) -> None:
    type_counts = analysis["type_counts"]
    n = len(analysis["records"])
    normalization_fields = []
    for field, counts in type_counts.items():
        if len(counts) > 1:
            normalization_fields.append(
                (
                    field,
                    counts.get("multi-assay / nested", 0),
                    counts.get("single value / text", 0),
                    counts.get("list", 0),
                )
            )
    normalization_fields = sorted(normalization_fields, key=lambda item: (item[1], item[2] + item[3]), reverse=True)[:14]

    fig, ax = plt.subplots(figsize=(12, 7))
    y_positions = range(len(normalization_fields))
    nested = [item[1] for item in normalization_fields]
    scalar = [item[2] for item in normalization_fields]
    list_values = [item[3] for item in normalization_fields]
    ax.barh(y_positions, nested, label="Multi-assay / nested values", color="#4C78A8")
    ax.barh(y_positions, scalar, left=nested, label="Single value / text", color="#F58518")
    left_for_list = [left + width for left, width in zip(nested, scalar)]
    ax.barh(y_positions, list_values, left=left_for_list, label="List values", color="#72B7B2")
    ax.set_yticks(y_positions, [item[0] for item in normalization_fields])
    ax.invert_yaxis()
    ax.set_xlabel(f"Number of papers out of {n}")
    ax.set_title("Fields Most Needing FAIRDS Normalization")
    ax.legend(loc="lower right")
    ax.text(0, -0.8, f"Source: {n} expert-curated PETase paper JSON files", fontsize=9, color="dimgray")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "petase_fields_needing_normalization.png", dpi=220)
    plt.close(fig)


def save_kinetic_completeness_chart(analysis: dict[str, Any]) -> None:
    kinetic_populated = analysis["kinetic_populated"]
    n = len(analysis["records"])
    keys = list(kinetic_populated.keys())
    populated = [kinetic_populated[key] for key in keys]
    missing = [n - value for value in populated]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(keys, populated, label="Populated", color="#4C78A8")
    ax.bar(keys, missing, bottom=populated, label="NA / not reported", color="#E45756")
    ax.set_ylabel(f"Number of papers out of {n}")
    ax.set_title("Completeness of Common Kinetic / Activity Fields")
    ax.legend()
    for index, value in enumerate(populated):
        ax.text(index, n + 0.25, f"{value}/{n}", ha="center", fontsize=9)
    ax.set_ylim(0, n + 2)
    ax.text(-0.45, n + 1.2, f"Source: {n} expert-curated PETase paper JSON files", fontsize=9, color="dimgray")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "petase_kinetic_field_completeness.png", dpi=220)
    plt.close(fig)


def write_summary_metrics(analysis: dict[str, Any]) -> None:
    records = analysis["records"]
    type_counts = analysis["type_counts"]
    n = len(records)
    summary = {
        "papers": n,
        "hplc_papers": sum(record["hplc"] for record in records),
        "tracked_fields": len(type_counts),
        "inconsistent_fields": sum(1 for counts in type_counts.values() if len(counts) > 1),
        "unique_activity_units": len(analysis["unit_counter"]),
        "min_paths": min(record["paths"] for record in records),
        "max_paths": max(record["paths"] for record in records),
        "mean_paths": round(statistics.mean(record["paths"] for record in records), 1),
        "substrates_min": min(record["substrates"] for record in records),
        "substrates_max": max(record["substrates"] for record in records),
        "enzymes_min": min(record["enzymes"] for record in records),
        "enzymes_max": max(record["enzymes"] for record in records),
        "activity_units_min": min(record["activity_units"] for record in records),
        "activity_units_max": max(record["activity_units"] for record in records),
        "kinetic_populated": analysis["kinetic_populated"],
        "assay_key_counts": analysis["assay_key_counts"],
    }
    (FIGURES_DIR / "petase_metadata_summary_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> None:
    FIGURES_DIR.mkdir(exist_ok=True)
    analysis = load_analysis()
    save_usability_dashboard(analysis)
    save_complexity_distribution(analysis)
    save_normalization_field_chart(analysis)
    save_kinetic_completeness_chart(analysis)
    write_summary_metrics(analysis)


if __name__ == "__main__":
    main()
