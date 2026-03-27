#!/usr/bin/env python3
"""Merge multiple memory harness runs and generate comparison charts."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]

MODE_ORDER = ["stateless", "fresh_mem0", "shared_mem0"]
MODE_LABELS = {
    "stateless": "Stateless",
    "fresh_mem0": "Fresh mem0",
    "shared_mem0": "Shared mem0",
}
MODE_COLORS = {
    "stateless": "#B45F06",
    "fresh_mem0": "#2A9D8F",
    "shared_mem0": "#264653",
}
MODEL_LABELS = {
    "local_memory_qwen35_9b": "Qwen3.5 9B",
    "presentation_ollama_qwen35_27b_mem0_mineru": "Qwen3.5 27B",
    "presentation_ollama_qwen35_35b_mem0_mineru": "Qwen3.5 35B",
    "presentation_ollama_nemotron_3_nano_mem0_mineru": "Nemotron-3 Nano",
}
MODEL_ORDER = [
    "local_memory_qwen35_9b",
    "presentation_ollama_qwen35_27b_mem0_mineru",
    "presentation_ollama_qwen35_35b_mem0_mineru",
    "presentation_ollama_nemotron_3_nano_mem0_mineru",
]


@dataclass
class HarnessSource:
    path: Path
    payload: Dict[str, Any]


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _mean(values: Iterable[Any]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None and v != ""]
    if not nums:
        return None
    return float(sum(nums) / len(nums))


def _infer_input_source(document_path: str) -> str:
    text = str(document_path)
    suffix = Path(text).suffix.lower()
    if suffix == ".pdf":
        return "pdf_mineru"
    if "mineru_" in text and suffix == ".md":
        return "preconverted_markdown"
    if suffix:
        return suffix.lstrip(".")
    return "unknown"


def _model_label(config_name: str) -> str:
    return MODEL_LABELS.get(config_name, config_name)


def _sort_key_for_model(config_name: str) -> tuple[int, str]:
    if config_name in MODEL_ORDER:
        return (MODEL_ORDER.index(config_name), config_name)
    return (len(MODEL_ORDER), config_name)


def _load_sources(paths: List[Path]) -> List[HarnessSource]:
    sources: List[HarnessSource] = []
    for path in paths:
        results_path = path / "memory_harness_results.json"
        if not results_path.exists():
            raise FileNotFoundError(f"Missing memory_harness_results.json in {path}")
        sources.append(HarnessSource(path=path, payload=_read_json(results_path)))
    return sources


def _merge_runs(sources: List[HarnessSource]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for source in sources:
        for run in source.payload.get("runs", []):
            row = dict(run)
            row["source_run_dir"] = str(source.path.relative_to(REPO_ROOT))
            row["input_source"] = _infer_input_source(row.get("document_path", ""))
            row["model_label"] = _model_label(row.get("config_name", ""))
            merged.append(row)
    merged.sort(
        key=lambda row: (
            _sort_key_for_model(row.get("config_name", "")),
            row.get("document_id", ""),
            MODE_ORDER.index(row["mode"]) if row.get("mode") in MODE_ORDER else 99,
            int(row.get("run_idx", 0)),
        )
    )
    return merged


def _aggregate_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
    for row in runs:
        key = (row["config_name"], row["document_id"], row["mode"])
        grouped.setdefault(key, []).append(row)

    aggregates: List[Dict[str, Any]] = []
    for (config_name, document_id, mode), rows in grouped.items():
        input_sources = sorted({row.get("input_source", "unknown") for row in rows})
        aggregates.append(
            {
                "config_name": config_name,
                "model_label": _model_label(config_name),
                "document_id": document_id,
                "mode": mode,
                "runs": len(rows),
                "success_rate": _mean([1.0 if row.get("success") else 0.0 for row in rows]),
                "mean_runtime_seconds": _mean(row.get("runtime_seconds") for row in rows),
                "mean_overall_confidence": _mean(row.get("overall_confidence") for row in rows),
                "mean_total_fields": _mean(row.get("total_fields") for row in rows),
                "mean_steps_requiring_retry": _mean(row.get("steps_requiring_retry") for row in rows),
                "shared_scope_level": next(
                    (row.get("shared_scope_level") for row in rows if row.get("shared_scope_level")),
                    None,
                ),
                "memory_scope_id_example": next(
                    (row.get("memory_scope_id") for row in rows if row.get("memory_scope_id")),
                    None,
                ),
                "input_sources": ", ".join(input_sources),
            }
        )

    aggregates.sort(
        key=lambda row: (
            _sort_key_for_model(row["config_name"]),
            row["document_id"],
            MODE_ORDER.index(row["mode"]) if row["mode"] in MODE_ORDER else 99,
        )
    )
    return aggregates


def _copy_output_trees(sources: List[HarnessSource], output_dir: Path) -> None:
    combined_outputs = output_dir / "outputs"
    combined_outputs.mkdir(parents=True, exist_ok=True)
    for source in sources:
        source_outputs = source.path / "outputs"
        if not source_outputs.exists():
            continue
        for item in source_outputs.iterdir():
            target = combined_outputs / item.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)


def _write_runs_csv(path: Path, runs: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "experiment_name",
        "config_name",
        "model_label",
        "document_id",
        "document_path",
        "input_source",
        "mode",
        "run_idx",
        "project_id",
        "memory_scope_id",
        "mem0_enabled",
        "shared_scope_level",
        "runtime_seconds",
        "success",
        "workflow_status",
        "overall_confidence",
        "total_fields",
        "steps_requiring_retry",
        "needs_human_review",
        "output_dir",
        "source_run_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(runs)


def _write_aggregates_csv(path: Path, aggregates: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "config_name",
        "model_label",
        "document_id",
        "mode",
        "runs",
        "success_rate",
        "mean_runtime_seconds",
        "mean_overall_confidence",
        "mean_total_fields",
        "mean_steps_requiring_retry",
        "shared_scope_level",
        "memory_scope_id_example",
        "input_sources",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(aggregates)


def _setup_style() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 15,
            "axes.labelsize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 11,
            "figure.facecolor": "#FAF8F2",
            "axes.facecolor": "#FAF8F2",
            "axes.edgecolor": "#264653",
            "axes.labelcolor": "#264653",
            "text.color": "#264653",
            "grid.color": "#D8D3C4",
        }
    )


def _input_source_note(aggregates_df: pd.DataFrame) -> str:
    sources = sorted(
        {
            source.strip()
            for item in aggregates_df.get("input_sources", pd.Series(dtype=str)).dropna()
            for source in str(item).split(",")
            if source.strip()
        }
    )
    if sources == ["preconverted_markdown"]:
        return (
            "All compared runs use the same preconverted MinerU Markdown input, "
            "so cross-model runtime is directly comparable within this harness."
        )
    if len(sources) == 1:
        return f"All compared runs use the same input source: {sources[0]}."
    return (
        "Input sources are mixed across merged runs, so use within-model deltas as the cleaner "
        "answer to the memory question and treat raw runtime comparisons with caution."
    )


def _ordered_model_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["model_sort"] = df["config_name"].map(
        lambda name: MODEL_ORDER.index(name) if name in MODEL_ORDER else len(MODEL_ORDER)
    )
    df["mode_sort"] = df["mode"].map(
        lambda mode: MODE_ORDER.index(mode) if mode in MODE_ORDER else len(MODE_ORDER)
    )
    return df.sort_values(["model_sort", "mode_sort", "config_name"]).drop(columns=["model_sort", "mode_sort"])


def _plot_grouped_metric(
    aggregates_df: pd.DataFrame,
    value_col: str,
    ylabel: str,
    title: str,
    output_path: Path,
    ylim: Optional[tuple[float, float]] = None,
    annotate_fmt: str = "{:.2f}",
) -> None:
    ordered = _ordered_model_rows(aggregates_df)
    model_names = list(dict.fromkeys(ordered["config_name"].tolist()))
    x = np.arange(len(model_names))
    width = 0.24

    fig, ax = plt.subplots(figsize=(14, 8))
    for idx, mode in enumerate(MODE_ORDER):
        subset = ordered[ordered["mode"] == mode]
        value_map = {row["config_name"]: row[value_col] for _, row in subset.iterrows()}
        vals = [value_map.get(name, np.nan) for name in model_names]
        bars = ax.bar(
            x + (idx - 1) * width,
            vals,
            width=width,
            color=MODE_COLORS[mode],
            label=MODE_LABELS[mode],
            zorder=3,
        )
        for bar, val in zip(bars, vals):
            if pd.isna(val):
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (0.01 if value_col != "mean_runtime_seconds" else 4),
                annotate_fmt.format(val),
                ha="center",
                va="bottom",
                fontsize=10,
            )

    labels = [
        _model_label(name).replace("Nemotron-3 Nano", "Nemotron\n3 Nano")
        for name in model_names
    ]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if ylim:
        ax.set_ylim(*ylim)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.35, zorder=0)
    fig.text(
        0.01,
        0.01,
        _input_source_note(aggregates_df),
        ha="left",
        va="bottom",
        fontsize=9.5,
        color="#5B5B5B",
    )
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_memory_delta(aggregates_df: pd.DataFrame, output_path: Path) -> None:
    ordered = _ordered_model_rows(aggregates_df)
    fig, ax = plt.subplots(figsize=(14, 8))
    for config_name in ordered["config_name"].unique():
        subset = ordered[ordered["config_name"] == config_name].set_index("mode")
        xs = [MODE_ORDER.index(mode) for mode in MODE_ORDER if mode in subset.index]
        ys = [subset.loc[mode, "mean_overall_confidence"] for mode in MODE_ORDER if mode in subset.index]
        ax.plot(
            xs,
            ys,
            marker="o",
            linewidth=2.8,
            markersize=8,
            label=_model_label(config_name),
        )
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.012, f"{y:.2f}", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(range(len(MODE_ORDER)))
    ax.set_xticklabels([MODE_LABELS[m] for m in MODE_ORDER])
    ax.set_ylabel("Mean overall confidence")
    ax.set_ylim(0.72, 0.94)
    ax.set_title("Memory-mode effect on confidence by model")
    ax.legend(frameon=False, loc="lower left")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    fig.text(
        0.01,
        0.01,
        _input_source_note(aggregates_df)
        + " Newer 27B/Nemotron points remain single-run estimates, while 9B/35B are two-run averages.",
        ha="left",
        va="bottom",
        fontsize=9.5,
        color="#5B5B5B",
    )
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _write_summary(output_dir: Path, sources: List[HarnessSource], runs_df: pd.DataFrame, agg_df: pd.DataFrame) -> None:
    best_conf = agg_df.sort_values("mean_overall_confidence", ascending=False).iloc[0]
    fastest = agg_df.sort_values("mean_runtime_seconds", ascending=True).iloc[0]
    most_fields = agg_df.sort_values("mean_total_fields", ascending=False).iloc[0]

    lines = [
        "# Memory Harness Combined Summary",
        "",
        f"- Generated at: `{datetime.now().isoformat()}`",
        f"- Sources merged: `{len(sources)}`",
        "",
        "## Source directories",
        "",
    ]
    for source in sources:
        lines.append(f"- `{source.path.relative_to(REPO_ROOT)}`")

    lines.extend(
        [
            "",
            "## Headline observations",
            "",
            f"- Highest mean confidence: `{_model_label(best_conf['config_name'])}` / `{MODE_LABELS[best_conf['mode']]}` at `{best_conf['mean_overall_confidence']:.3f}`.",
            f"- Most fields: `{_model_label(most_fields['config_name'])}` / `{MODE_LABELS[most_fields['mode']]}` at `{most_fields['mean_total_fields']:.1f}` fields.",
            f"- Fastest average runtime: `{_model_label(fastest['config_name'])}` / `{MODE_LABELS[fastest['mode']]}` at `{fastest['mean_runtime_seconds']:.1f}` seconds.",
            "",
            "## Caveat",
            "",
            f"- {_input_source_note(agg_df)}",
            "",
            "## Files",
            "",
            "- `memory_harness_runs.csv`: merged run-level table",
            "- `memory_harness_aggregates.csv`: merged aggregate table",
            "- `figures/confidence_by_model_mode.png`: grouped confidence bars",
            "- `figures/fields_by_model_mode.png`: grouped field-count bars",
            "- `figures/runtime_by_model_mode.png`: grouped runtime bars",
            "- `figures/confidence_memory_slopes.png`: per-model confidence slope chart",
        ]
    )
    (output_dir / "COMBINED_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        action="append",
        dest="source_dirs",
        required=True,
        help="Path to a memory harness run directory containing memory_harness_results.json.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Where to write the merged results and charts.",
    )
    parser.add_argument(
        "--experiment-name",
        default="memory-harness-combined",
        help="Experiment name to write into the merged JSON.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    source_dirs = [Path(p).resolve() for p in args.source_dirs]
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    sources = _load_sources(source_dirs)
    runs = _merge_runs(sources)
    aggregates = _aggregate_runs(runs)

    _copy_output_trees(sources, output_dir)
    _write_runs_csv(output_dir / "memory_harness_runs.csv", runs)
    _write_aggregates_csv(output_dir / "memory_harness_aggregates.csv", aggregates)

    merged_payload = {
        "experiment_name": args.experiment_name,
        "generated_at": datetime.now().isoformat(),
        "source_dirs": [str(path.relative_to(REPO_ROOT)) for path in source_dirs],
        "model_configs": sorted({row["config_name"] for row in runs}),
        "documents": sorted({row["document_path"] for row in runs}),
        "modes": MODE_ORDER,
        "runs": runs,
        "aggregates": aggregates,
    }
    (output_dir / "memory_harness_results.json").write_text(
        json.dumps(merged_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    agg_df = pd.DataFrame(aggregates)
    _setup_style()
    _plot_grouped_metric(
        agg_df,
        "mean_overall_confidence",
        "Mean overall confidence",
        "Memory harness: confidence by model and mode",
        figures_dir / "confidence_by_model_mode.png",
        ylim=(0.0, 1.0),
        annotate_fmt="{:.2f}",
    )
    _plot_grouped_metric(
        agg_df,
        "mean_total_fields",
        "Mean total fields",
        "Memory harness: field coverage by model and mode",
        figures_dir / "fields_by_model_mode.png",
        annotate_fmt="{:.1f}",
    )
    _plot_grouped_metric(
        agg_df,
        "mean_runtime_seconds",
        "Mean runtime (seconds)",
        "Memory harness: runtime by model and mode",
        figures_dir / "runtime_by_model_mode.png",
        annotate_fmt="{:.0f}",
    )
    _plot_memory_delta(agg_df, figures_dir / "confidence_memory_slopes.png")

    _write_summary(output_dir, sources, pd.DataFrame(runs), agg_df)
    print(f"Merged results written to {output_dir}")


if __name__ == "__main__":
    main()
