#!/usr/bin/env python3
"""Generate updated slide-ready figures from current FAIRiAgent runs and baseline."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from fairifier.output_paths import resolve_metadata_output_read_path

GT_PATH = REPO_ROOT / "evaluation/datasets/annotated/ground_truth_filtered.json"
MATRIX_CSV = (
    REPO_ROOT
    / "evaluation/harness/private/reports/final/2026-03-27/matrix_completion_2026-03-26/matrix_completion_summary.csv"
)
MATRIX_QC_CSV = (
    REPO_ROOT
    / "evaluation/harness/private/reports/final/2026-03-27/matrix_completion_2026-03-26/matrix_completion_qc.csv"
)
OUT_ROOT = (
    REPO_ROOT
    / "evaluation/harness/private/reports/final/2026-03-27/presentation_figures_slides_dark_2026-03-27"
)

DOC_ORDER = ["earthworm", "biosensor", "pomato"]
MODEL_ORDER = [
    "gpt-5.4",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "qwen3-max",
    "qwen3.5:35b",
    "qwen3.5:9b",
]

DOC_LABELS = {
    "earthworm": "Earthworm",
    "biosensor": "Biosensor",
    "pomato": "Pomato",
}
MODEL_LABELS = {
    "gpt-5.4": "GPT-5.4",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-opus-4-6": "Claude Opus 4.6",
    "qwen3-max": "Qwen3-Max",
    "qwen3.5:35b": "Qwen3.5 35B",
    "qwen3.5:9b": "Qwen3.5 9B",
}

COLORS = {
    "bg": "#0D1117",
    "panel": "#111827",
    "text": "#E5EDF5",
    "muted": "#9FB0C3",
    "grid": "#2A3647",
    "baseline": "#F28C52",
    "agentic": "#1FB6AA",
    "api": "#5AB1FF",
    "anthropic": "#C084FC",
    "qwen": "#4FD1C5",
    "local": "#F6AD55",
    "warning": "#FF6B6B",
}


@dataclass
class Phase1DocMetric:
    workflow: str
    document: str
    overall: float
    required: float
    recommended: float
    schema: float
    extracted_fields: float
    runtime_seconds: float


def normalize_name(name: str) -> str:
    return " ".join(str(name).strip().lower().replace("_", " ").replace("-", " ").split())


def load_ground_truth() -> Dict[str, dict]:
    data = load_json(GT_PATH)
    docs = {}
    for doc in data["documents"]:
        gt_fields = doc["ground_truth_fields"]
        docs[doc["document_id"]] = {
            "required": {
                normalize_name(f["field_name"]) for f in gt_fields if f.get("is_required", False)
            },
            "recommended": {
                normalize_name(f["field_name"]) for f in gt_fields if f.get("is_recommended", False)
            },
            "optional": {
                normalize_name(f["field_name"])
                for f in gt_fields
                if not f.get("is_required", False) and not f.get("is_recommended", False)
            },
            "all_fields": {normalize_name(f["field_name"]) for f in gt_fields},
        }
    return docs


def iter_baseline_fields(obj, section: str | None = None):
    section_map = {
        "investigation": "investigation",
        "studies": "study",
        "samples": "sample",
        "sequencing_data": "assay",
    }
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in section_map:
                yield from iter_baseline_fields(value, section_map[key])
            elif isinstance(value, (dict, list)):
                yield from iter_baseline_fields(value, section)
            else:
                yield normalize_name(key), section or "unknown"
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_baseline_fields(item, section)


def extract_fields(metadata: dict) -> List[dict]:
    if "isa_structure" in metadata:
        rows = []
        for isa_sheet, sheet_data in metadata.get("isa_structure", {}).items():
            if isa_sheet == "description":
                continue
            for field in sheet_data.get("fields", []):
                name = normalize_name(field.get("field_name", ""))
                if name:
                    rows.append({"field_name": name, "isa_sheet": isa_sheet})
        return rows

    rows = []
    seen = set()
    for name, isa_sheet in iter_baseline_fields(metadata):
        if name and name not in seen:
            rows.append({"field_name": name, "isa_sheet": isa_sheet})
            seen.add(name)
    return rows


def compute_completeness(metadata: dict, gt_doc: dict) -> dict:
    extracted = {row["field_name"] for row in extract_fields(metadata)}
    required = gt_doc["required"]
    recommended = gt_doc["recommended"]
    optional = gt_doc["optional"]
    gt_all = gt_doc["all_fields"]
    return {
        "overall_completeness": len(extracted & gt_all) / len(gt_all) if gt_all else 0.0,
        "required_completeness": len(extracted & required) / len(required) if required else 1.0,
        "recommended_completeness": len(extracted & recommended) / len(recommended) if recommended else 1.0,
        "optional_completeness": len(extracted & optional) / len(optional) if optional else 1.0,
        "total_extracted_fields": len(extracted),
        "covered_fields": len(extracted & gt_all),
        "missing_fields": len(gt_all - extracted),
    }


def setup_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "figure.facecolor": COLORS["bg"],
            "axes.facecolor": COLORS["panel"],
            "savefig.facecolor": COLORS["bg"],
            "axes.edgecolor": COLORS["grid"],
            "axes.labelcolor": COLORS["text"],
            "xtick.color": COLORS["text"],
            "ytick.color": COLORS["text"],
            "text.color": COLORS["text"],
            "axes.titleweight": "bold",
            "font.size": 12,
            "axes.titlesize": 18,
            "axes.labelsize": 13,
            "legend.fontsize": 11,
            "axes.titlepad": 12,
        }
    )


def safe_mkdir() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_runtime_seconds(run_dir: Path) -> float:
    eval_result = run_dir / "eval_result.json"
    if eval_result.exists():
        data = load_json(eval_result)
        if data.get("runtime_seconds") is not None:
            return float(data["runtime_seconds"])

    workflow_report = run_dir / "workflow_report.json"
    if workflow_report.exists():
        data = load_json(workflow_report)
        summary = data.get("execution_summary", {})
        start = summary.get("processing_start")
        end = summary.get("processing_end")
        if start and end:
            return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    return float("nan")


def load_phase1() -> pd.DataFrame:
    rows: List[Phase1DocMetric] = []
    bundles: List[Tuple[str, Path, str]] = [
        (
            "Baseline",
            REPO_ROOT / "evaluation/harness/runs/presentation_phase1_baseline_qwenflash/results/evaluation_results.json",
            "baseline_qwen_flash_presentation",
        ),
        (
            "FAIRiAgent",
            REPO_ROOT / "evaluation/harness/runs/presentation_phase1_agentic_qwenflash_r2/results/evaluation_results.json",
            "presentation_qwen_flash",
        ),
    ]
    for workflow, results_path, model_key in bundles:
        data = load_json(results_path)
        mv = data["per_model_results"][model_key]
        for doc in DOC_ORDER:
            output_dir = (
                REPO_ROOT
                / ("evaluation/harness/runs/presentation_phase1_baseline_qwenflash/outputs/baseline_qwen_flash_presentation" if workflow == "Baseline" else "evaluation/harness/runs/presentation_phase1_agentic_qwenflash_r2/outputs/presentation_qwen_flash")
                / doc
                / "run_1"
            )
            comp = mv["completeness"]["per_document"][doc]["overall_metrics"]
            workflow_report_path = output_dir / "workflow_report.json"
            if workflow_report_path.exists():
                schema_confidence = load_json(workflow_report_path)["quality_metrics"]["validation_confidence"]
            else:
                schema_confidence = mv["schema_validation"]["per_document"][doc]["schema_compliance_rate"]
            rows.append(
                Phase1DocMetric(
                    workflow=workflow,
                    document=doc,
                    overall=comp["overall_completeness"],
                    required=comp["required_completeness"],
                    recommended=comp["recommended_completeness"],
                    schema=schema_confidence,
                    extracted_fields=comp["total_extracted_fields"],
                    runtime_seconds=load_runtime_seconds(output_dir),
                )
            )
    return pd.DataFrame([r.__dict__ for r in rows])


def load_matrix() -> pd.DataFrame:
    rows = []
    gt_docs = load_ground_truth()
    qc_rows = {}
    with MATRIX_QC_CSV.open() as f:
        for row in csv.DictReader(f):
            qc_rows[(row["model"], row["document"])] = row

    with MATRIX_CSV.open() as f:
        base_rows = list(csv.DictReader(f))

    for row in base_rows:
        model = row["model"]
        document = row["document"]
        run_path = REPO_ROOT / row["run_path"]
        if not run_path.exists():
            continue

        meta_path = resolve_metadata_output_read_path(run_path)
        if not meta_path:
            continue
        metadata = load_json(meta_path)
        workflow = load_json(run_path / "workflow_report.json")
        comp_metrics = compute_completeness(metadata, gt_docs[document])
        quality = workflow["quality_metrics"]
        retry = workflow["retry_analysis"]
        retry_rate = retry.get("retry_rate")
        total_retries = retry.get("steps_requiring_retry")
        if retry_rate is None:
            total_steps = workflow.get("execution_summary", {}).get("total_steps") or 0
            total_retries = retry.get("global_retries_used", 0) if total_retries is None else total_retries
            retry_rate = (total_retries / total_steps) if total_steps else 0.0
        if total_retries is None:
            total_retries = retry.get("global_retries_used", 0)
        runtime = load_runtime_seconds(run_path)

        rows.append(
            {
                "model": model,
                "document": document,
                "overall_completeness": comp_metrics["overall_completeness"],
                "required_completeness": comp_metrics["required_completeness"],
                "recommended_completeness": comp_metrics["recommended_completeness"],
                "schema_compliance_rate": quality["validation_confidence"],
                "schema_valid": float(quality["validation_confidence"] >= 0.99),
                "runtime_seconds": runtime,
                "total_extracted_fields": comp_metrics["total_extracted_fields"],
                "covered_fields": comp_metrics["covered_fields"],
                "missing_fields": comp_metrics["missing_fields"],
                "workflow_confidence": quality["overall_confidence"],
                "total_fields": quality["total_fields"],
                "confirmed_fields": quality["confirmed_fields"],
                "retry_rate": retry_rate,
                "total_retries": total_retries,
                "success_required": float(comp_metrics["required_completeness"] == 1.0),
                "status": "OK" if comp_metrics["required_completeness"] == 1.0 else "INCOMPLETE",
                "critical_missing": len(gt_docs[document]["required"] - {row["field_name"] for row in extract_fields(metadata)}),
                "qc_status": qc_rows[(model, document)]["status"],
                "retain_for_matrix": qc_rows[(model, document)]["retain_for_matrix"],
                "qc_notes": qc_rows[(model, document)]["notes"],
            }
        )
    df = pd.DataFrame(rows)
    df["model"] = pd.Categorical(df["model"], MODEL_ORDER, ordered=True)
    df["document"] = pd.Categorical(df["document"], DOC_ORDER, ordered=True)
    return df.sort_values(["document", "model"]).reset_index(drop=True)


def check_missing(df_phase1: pd.DataFrame, df_matrix: pd.DataFrame) -> Dict[str, List[str]]:
    issues: Dict[str, List[str]] = {"phase1": [], "matrix": [], "notes": []}

    for col in ["overall", "required", "recommended", "extracted_fields", "runtime_seconds"]:
        n_missing = int(df_phase1[col].isna().sum())
        if n_missing:
            issues["phase1"].append(f"{col}: {n_missing} missing")

    critical_cols = [
        "overall_completeness",
        "required_completeness",
        "schema_compliance_rate",
        "runtime_seconds",
        "total_extracted_fields",
        "workflow_confidence",
    ]
    for col in critical_cols:
        n_missing = int(df_matrix[col].isna().sum())
        if n_missing:
            issues["matrix"].append(f"{col}: {n_missing} missing")

    issues["notes"].append(
        "LLM judge metrics are intentionally omitted from slide figures because current evaluator output is unreliable in multiple recent batches."
    )
    issues["notes"].append(
        "Matrix completeness metrics in the slide figures are recomputed directly from metadata.json against ground truth so that all current matrix cells are evaluated on the same per-document basis."
    )
    issues["notes"].append(
        "Anthropic pomato cells are retained for coverage but marked provider-affected based on QC."
    )
    return issues


def add_provider_flags(ax, data: pd.DataFrame, x_lookup: Dict[str, int], y_lookup: Dict[str, int]) -> None:
    flagged = data[data["qc_status"] == "provider_affected"]
    for _, row in flagged.iterrows():
        x = x_lookup[str(row["document"])]
        y = y_lookup[str(row["model"])]
        rect = plt.Rectangle((x, y), 1, 1, fill=False, ec=COLORS["warning"], lw=2.8)
        ax.add_patch(rect)
        ax.text(
            x + 0.98,
            y + 0.08,
            "!",
            color=COLORS["warning"],
            fontsize=15,
            fontweight="bold",
            ha="right",
            va="bottom",
        )


def annotate_heatmap(ax, pivot: pd.DataFrame, fmt: str, threshold: float | None = None) -> None:
    vals = pivot.to_numpy(dtype=float)
    finite = vals[np.isfinite(vals)]
    if threshold is None:
        threshold = float((finite.min() + finite.max()) / 2.0) if finite.size else 0.5
    for iy in range(vals.shape[0]):
        for ix in range(vals.shape[1]):
            val = vals[iy, ix]
            if not np.isfinite(val):
                continue
            color = "white" if val >= threshold else COLORS["text"]
            ax.text(ix + 0.5, iy + 0.5, format(val, fmt), ha="center", va="center", color=color, fontsize=11, fontweight="semibold")


def fig01_phase1(df: pd.DataFrame) -> None:
    df_matrix = load_matrix()
    fig, axes = plt.subplots(1, 2, figsize=(24, 9.5))
    fig.subplots_adjust(left=0.05, right=0.985, top=0.86, bottom=0.22, wspace=0.16)
    fig.suptitle("Baseline vs FAIRiAgent by Model Family", fontsize=22, fontweight="bold", y=0.955)

    baseline_map = {
        "gpt-5.4": {
            "label": "GPT-5.1 baseline",
            "overall": 0.38278388278388276,
            "runtime_seconds": 374.720392 / (2 * 10),
        },
        "claude-opus-4-6": {
            "label": "Claude Haiku 4.5 baseline",
            "overall": 0.35714285714285715,
            "runtime_seconds": ((14 * 3600 + 35 * 60 + 27) - (14 * 3600 + 6 * 60 + 21)) / 10,
        },
        "qwen3-max": {
            "label": "Qwen-Flash baseline",
            "overall": 0.0,
            "runtime_seconds": 18.47,
        },
    }

    fairiagent_summary = (
        df_matrix.groupby("model", observed=False)
        .agg(
            overall=("overall_completeness", "mean"),
            runtime_seconds=("runtime_seconds", "mean"),
        )
        .reset_index()
    )
    fairiagent_summary = fairiagent_summary[fairiagent_summary["model"].isin(list(baseline_map.keys()))].copy()
    fairiagent_summary["model"] = pd.Categorical(fairiagent_summary["model"], list(baseline_map.keys()), ordered=True)
    fairiagent_summary = fairiagent_summary.sort_values("model")

    x = np.arange(len(fairiagent_summary))
    width = 0.34
    tick_labels = [MODEL_LABELS[m] for m in fairiagent_summary["model"]]

    baseline_overall = [baseline_map[m]["overall"] for m in fairiagent_summary["model"]]
    agent_overall = fairiagent_summary["overall"].tolist()
    baseline_runtime = [baseline_map[m]["runtime_seconds"] for m in fairiagent_summary["model"]]
    agent_runtime = fairiagent_summary["runtime_seconds"].tolist()

    metric_specs = [
        (axes[0], baseline_overall, agent_overall, "Overall Completeness", "Fraction of ground-truth fields covered", 1.08, ".2f"),
        (axes[1], baseline_runtime, agent_runtime, "Runtime", "Mean runtime per document (seconds)", None, ".0f"),
    ]

    for ax, base_vals, agent_vals, title, ylabel, ylim, fmt in metric_specs:
        ax.bar(x - width / 2, base_vals, width=width, color=COLORS["baseline"], alpha=0.92, label="Baseline")
        ax.bar(x + width / 2, agent_vals, width=width, color=COLORS["agentic"], alpha=0.92, label="FAIRiAgent")
        for xi, yi in zip(x - width / 2, base_vals):
            ax.text(xi, yi + (0.015 if ylim else 6), format(yi, fmt), ha="center", va="bottom", fontsize=9.5)
        for xi, yi in zip(x + width / 2, agent_vals):
            ax.text(xi, yi + (0.015 if ylim else 6), format(yi, fmt), ha="center", va="bottom", fontsize=9.5)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticks(x)
        ax.set_xticklabels(tick_labels, rotation=0, ha="center")
        ax.grid(axis="y", color=COLORS["grid"], alpha=0.6)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if ylim:
            ax.set_ylim(0, ylim)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.90), ncol=2, frameon=False)
    fig.savefig(OUT_ROOT / "fig01_phase1_baseline_vs_agentic.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT_ROOT / "fig01_phase1_baseline_vs_agentic.svg", bbox_inches="tight")
    plt.close(fig)


def fig02_quality_heatmaps(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(26, 12.5))
    fig.subplots_adjust(left=0.10, right=0.98, top=0.90, bottom=0.10, wspace=0.28)
    fig.suptitle("Latest FAIRiAgent Matrix: Quality Across Models and Datasets", fontsize=22, fontweight="bold")

    metrics = [
        ("overall_completeness", "Overall completeness", ".2f"),
        ("schema_compliance_rate", "Schema compliance", ".2f"),
        ("workflow_confidence", "Workflow confidence", ".2f"),
    ]
    model_labels = [MODEL_LABELS[m] for m in MODEL_ORDER]
    doc_labels = [DOC_LABELS[d] for d in DOC_ORDER]
    x_lookup = {doc: i for i, doc in enumerate(DOC_ORDER)}
    y_lookup = {model: i for i, model in enumerate(MODEL_ORDER)}

    for ax, (metric, title, fmt) in zip(axes, metrics):
        pivot = (
            df.pivot(index="model", columns="document", values=metric)
            .reindex(index=MODEL_ORDER, columns=DOC_ORDER)
        )
        sns.heatmap(
            pivot,
            ax=ax,
            annot=False,
            cmap="mako",
            vmin=0,
            vmax=1,
            cbar=ax is axes[-1],
            linewidths=0.8,
            linecolor=COLORS["panel"],
        )
        annotate_heatmap(ax, pivot, fmt)
        ax.set_title(title)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.set_xticklabels(doc_labels, rotation=0)
        ax.set_yticklabels(model_labels, rotation=0)
        add_provider_flags(ax, df, x_lookup, y_lookup)
    fig.savefig(OUT_ROOT / "fig02_latest_matrix_quality_heatmaps.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT_ROOT / "fig02_latest_matrix_quality_heatmaps.svg", bbox_inches="tight")
    plt.close(fig)


def fig03_operational_heatmaps(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(26, 12.5))
    fig.subplots_adjust(left=0.10, right=0.98, top=0.90, bottom=0.10, wspace=0.28)
    fig.suptitle("Latest FAIRiAgent Matrix: Operational Trade-offs", fontsize=22, fontweight="bold")

    metrics = [
        ("runtime_seconds", "Runtime (s)", "rocket_r", ".0f", None),
        ("total_extracted_fields", "Extracted fields", "crest", ".0f", None),
        ("workflow_confidence", "Workflow confidence", "mako", ".2f", (0, 1)),
    ]
    model_labels = [MODEL_LABELS[m] for m in MODEL_ORDER]
    doc_labels = [DOC_LABELS[d] for d in DOC_ORDER]
    x_lookup = {doc: i for i, doc in enumerate(DOC_ORDER)}
    y_lookup = {model: i for i, model in enumerate(MODEL_ORDER)}

    for ax, (metric, title, cmap, fmt, limits) in zip(axes, metrics):
        pivot = (
            df.pivot(index="model", columns="document", values=metric)
            .reindex(index=MODEL_ORDER, columns=DOC_ORDER)
        )
        kwargs = {}
        if limits is not None:
            kwargs["vmin"], kwargs["vmax"] = limits
        sns.heatmap(
            pivot,
            ax=ax,
            annot=False,
            cmap=cmap,
            cbar=ax is axes[-1],
            linewidths=0.8,
            linecolor=COLORS["panel"],
            **kwargs,
        )
        annotate_heatmap(ax, pivot, fmt, threshold=float(np.nanmedian(pivot.to_numpy(dtype=float))))
        ax.set_title(title)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.set_xticklabels(doc_labels, rotation=0)
        ax.set_yticklabels(model_labels, rotation=0)
        add_provider_flags(ax, df, x_lookup, y_lookup)
    fig.savefig(OUT_ROOT / "fig03_latest_matrix_operational_heatmaps.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT_ROOT / "fig03_latest_matrix_operational_heatmaps.svg", bbox_inches="tight")
    plt.close(fig)


def fig04_document_profiles(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(20, 19))
    fig.subplots_adjust(left=0.16, right=0.98, top=0.94, bottom=0.06, hspace=0.30)
    fig.suptitle("Document-Level Model Profiles on the Current FAIRiAgent Matrix", fontsize=22, fontweight="bold", y=0.99)

    for ax, doc in zip(axes, DOC_ORDER):
        sub = df[df["document"] == doc].copy()
        sub = sub.sort_values("overall_completeness", ascending=True)
        y = np.arange(len(sub))
        colors = []
        for _, row in sub.iterrows():
            if row["model"].startswith("claude"):
                colors.append(COLORS["anthropic"])
            elif row["model"].startswith("qwen3.5"):
                colors.append(COLORS["local"])
            elif row["model"] == "qwen3-max":
                colors.append(COLORS["qwen"])
            else:
                colors.append(COLORS["api"])

        bars = ax.barh(y, sub["overall_completeness"], color=colors, alpha=0.9)
        for bar, (_, row) in zip(bars, sub.iterrows()):
            label = (
                f"{row['runtime_seconds']:.0f}s | {int(row['total_extracted_fields'])} fields | schema {row['schema_compliance_rate']:.2f}"
            )
            ax.text(
                min(bar.get_width() + 0.015, 1.01),
                bar.get_y() + bar.get_height() / 2,
                label,
                va="center",
                fontsize=9.5,
            )
            if row["qc_status"] == "provider_affected":
                ax.text(1.06, bar.get_y() + bar.get_height() / 2, "provider-affected", color=COLORS["warning"], va="center", fontsize=9.5, fontweight="bold")

        ax.set_yticks(y)
        ax.set_yticklabels([MODEL_LABELS[m] for m in sub["model"]])
        ax.set_xlim(0, 1.16)
        ax.set_xlabel("Overall completeness")
        ax.set_title(DOC_LABELS[doc])
        ax.grid(axis="x", color=COLORS["grid"], alpha=0.6)
        ax.axvline(1.0, color=COLORS["grid"], lw=1.0, ls="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.savefig(OUT_ROOT / "fig04_document_level_profiles.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT_ROOT / "fig04_document_level_profiles.svg", bbox_inches="tight")
    plt.close(fig)


def write_tables(df_phase1: pd.DataFrame, df_matrix: pd.DataFrame, issues: Dict[str, List[str]]) -> None:
    phase1_csv = OUT_ROOT / "phase1_baseline_agentic_metrics.csv"
    matrix_csv = OUT_ROOT / "latest_matrix_metrics.csv"
    df_phase1.to_csv(phase1_csv, index=False)
    df_matrix.to_csv(matrix_csv, index=False)

    manifest = {
        "description": "Slide-ready figure package generated from current FAIRiAgent matrix runs and current comparable baseline.",
        "figures": [
            "fig01_phase1_baseline_vs_agentic.png",
            "fig02_latest_matrix_quality_heatmaps.png",
            "fig03_latest_matrix_operational_heatmaps.png",
            "fig04_document_level_profiles.png",
        ],
        "phase1_rows": len(df_phase1),
        "matrix_rows": len(df_matrix),
        "quality_notes": issues,
    }
    (OUT_ROOT / "figure_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    notes = [
        "# Data Quality Notes",
        "",
        "## Missing-value check",
        "",
    ]
    if not issues["phase1"] and not issues["matrix"]:
        notes.append("- No missing values were found in the metrics actually used by the updated slide figures.")
    else:
        for section in ["phase1", "matrix"]:
            for item in issues[section]:
                notes.append(f"- {section}: {item}")

    notes.extend(
        [
            "",
            "## Intentional exclusions",
            "",
        ]
    )
    for item in issues["notes"]:
        notes.append(f"- {item}")

    notes.extend(
        [
            "",
            "## Expected patterns in the updated figures",
            "",
            "- FAIRiAgent should strongly outperform the current qwen-flash baseline on the shared 3-document set.",
            "- Earthworm and biosensor should appear substantially easier than pomato across the current matrix.",
            "- Earthworm and biosensor should show strong overall completeness across most models, while pomato remains the hardest document.",
            "- The two Anthropic pomato cells should stand out as provider-affected outliers rather than representative low performers.",
        ]
    )
    (OUT_ROOT / "DATA_QUALITY_NOTES.md").write_text("\n".join(notes), encoding="utf-8")

    readme = [
        "# Slide Figure Pack",
        "",
        "This figure pack is built from:",
        "",
        "- the current comparable baseline: `presentation_phase1_baseline_qwenflash`",
        "- the current FAIRiAgent phase-1 workflow comparison: `presentation_phase1_agentic_qwenflash_r2`",
        "- the completed FAIRiAgent model × dataset matrix summarized in `matrix_completion_summary.csv`",
        "",
        "## Figures",
        "",
        "- `fig01_phase1_baseline_vs_agentic.png`: current baseline vs FAIRiAgent on the shared qwen-flash 3-document set",
        "- `fig02_latest_matrix_quality_heatmaps.png`: overall completeness, schema compliance, and workflow confidence across the current matrix",
        "- `fig03_latest_matrix_operational_heatmaps.png`: runtime, extracted fields, workflow confidence across the current matrix",
        "- `fig04_document_level_profiles.png`: per-document model comparison with overall completeness, runtime, field breadth, and schema quality",
        "",
        "## Notes",
        "",
        "- These figures intentionally avoid LLM-judge metrics because current evaluator output is unreliable in several recent runs.",
        "- These figures intentionally avoid per-cell use of batch-level `aggregate_score` because some source batches mix multiple documents.",
        "- Anthropic pomato cells are retained for coverage but explicitly marked as provider-affected in the figures and QC notes.",
    ]
    (OUT_ROOT / "README.md").write_text("\n".join(readme), encoding="utf-8")


def main() -> None:
    setup_style()
    safe_mkdir()
    df_phase1 = load_phase1()
    df_matrix = load_matrix()
    issues = check_missing(df_phase1, df_matrix)
    fig01_phase1(df_phase1)
    fig02_quality_heatmaps(df_matrix)
    fig03_operational_heatmaps(df_matrix)
    fig04_document_profiles(df_matrix)
    write_tables(df_phase1, df_matrix, issues)
    print(f"Updated slide figure pack written to {OUT_ROOT}")


if __name__ == "__main__":
    main()
