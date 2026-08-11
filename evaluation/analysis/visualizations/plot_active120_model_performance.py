"""Generate the publication figure comparing ACTIVE-120 primary-core models."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[3]
PACKAGING = (
    ROOT
    / "output"
    / "benchmark_v2_20260721_release_prep"
    / "active120_packaging_20260725"
)
OUTPUT = ROOT / "docs" / "manuscript" / "figures"
TASK_SUMMARY_OUTPUT = ROOT / "docs" / "manuscript" / "tables" / "active120_task_decomposition.json"
MODEL_COMPARISON_OUTPUT = ROOT / "docs" / "manuscript" / "tables" / "active120_model_comparison.json"

MODEL_ORDER = [
    "deepseek_v4-flash_v1.4.0",
    "ollama_gemma4-26b_v1.4.0",
    "ollama_gpt-oss",
    "ollama_qwen3.6-27b_v1.4.0",
]
MODEL_LABELS = {
    "deepseek_v4-flash_v1.4.0": "DeepSeek V4 Flash",
    "ollama_gemma4-26b_v1.4.0": "Gemma 4-26B",
    "ollama_gpt-oss": "GPT-OSS",
    "ollama_qwen3.6-27b_v1.4.0": "Qwen 3.6-27B",
}
MODEL_COLORS = {
    "deepseek_v4-flash_v1.4.0": "#0072B2",
    "ollama_gemma4-26b_v1.4.0": "#009E73",
    "ollama_gpt-oss": "#E69F00",
    "ollama_qwen3.6-27b_v1.4.0": "#CC79A7",
}
# Interoperability intentionally omitted from publication figures: it was
# near-ceiling for completed runs and did not discriminate model content quality.
AXES = [
    ("information_coverage", "Field recovery / presence", 0.70),
    ("value_accuracy", "GT-wide value score", 0.75),
    ("structural_fidelity", "Structural fidelity", 0.75),
]
SUPPLEMENTAL_INSTANCE = "petase_10_1038_s41467-022-35237-x"


def load_primary_results() -> tuple[list[dict], dict[str, list[dict]]]:
    human_score = json.loads(
        (PACKAGING / "active120_human_gut_score.json").read_text()
    )
    petase_score = json.loads(
        (PACKAGING / "active120_petase3_core_score.json").read_text()
    )
    human = human_score["evaluated_run_index"]["results"]
    petase = [
        row
        for row in petase_score["evaluated_run_index"]["results"]
        if row["instance_id"] != SUPPLEMENTAL_INSTANCE
    ]
    assert len(human) == 60
    assert len(petase) == 40
    return human + petase, {"Human gut": human, "PETase core": petase}


def summarize(
    primary: list[dict], cohorts: dict[str, list[dict]]
) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for model_id in MODEL_ORDER:
        scheduled = [row for row in primary if row["model_id"] == model_id]
        successful = [row for row in scheduled if row["status"] == "success"]
        assert len(scheduled) == 25
        model_summary = {
            "scheduled": len(scheduled),
            "completed": len(successful),
            "scheduled_mean": {},
            "successful_mean": {},
            "cohorts": {},
        }
        for axis_id, _, _ in AXES:
            model_summary["scheduled_mean"][axis_id] = float(
                np.mean([row["axes"][axis_id] for row in scheduled])
            )
            model_summary["successful_mean"][axis_id] = float(
                np.mean([row["axes"][axis_id] for row in successful])
            )
        for cohort_name, cohort_rows in cohorts.items():
            rows = [row for row in cohort_rows if row["model_id"] == model_id]
            model_summary["cohorts"][cohort_name] = {
                axis_id: float(np.mean([row["axes"][axis_id] for row in rows]))
                for axis_id, _, _ in AXES
            }
        summary[model_id] = model_summary
    return summary


def style_axis(ax: plt.Axes) -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#D9D9D9", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)


def generate_figure(summary: dict[str, dict]) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )

    figure = plt.figure(figsize=(14.5, 9.2), constrained_layout=False)
    grid = figure.add_gridspec(2, 2, height_ratios=[1, 1])
    figure.subplots_adjust(
        left=0.16,
        right=0.94,
        top=0.82,
        bottom=0.10,
        hspace=0.42,
        wspace=0.42,
    )
    y_positions = np.arange(len(MODEL_ORDER))[::-1]

    for index, (axis_id, axis_label, threshold) in enumerate(AXES):
        ax = figure.add_subplot(grid[index // 2, index % 2])
        scheduled_values = np.array(
            [summary[model]["scheduled_mean"][axis_id] for model in MODEL_ORDER]
        )
        successful_values = np.array(
            [summary[model]["successful_mean"][axis_id] for model in MODEL_ORDER]
        )
        colors = [MODEL_COLORS[model] for model in MODEL_ORDER]

        ax.barh(
            y_positions,
            scheduled_values,
            height=0.48,
            color=colors,
            alpha=0.88,
            edgecolor="none",
        )
        ax.scatter(
            successful_values,
            y_positions,
            s=72,
            facecolors="white",
            edgecolors=colors,
            linewidths=2,
            zorder=4,
        )
        ax.axvline(
            threshold,
            color="#555555",
            linestyle=(0, (4, 3)),
            linewidth=1.3,
            zorder=2,
        )
        ax.text(
            threshold + 0.01,
            0.98,
            f"provisional {threshold:.0%}",
            color="#555555",
            ha="left",
            va="top",
            fontsize=8.5,
            transform=ax.get_xaxis_transform(),
        )
        for y, scheduled_value, successful_value in zip(
            y_positions, scheduled_values, successful_values
        ):
            ax.text(
                min(max(scheduled_value, successful_value) + 0.025, 0.995),
                y,
                f"{scheduled_value:.1%} / {successful_value:.1%}",
                va="center",
                ha="left",
                fontsize=8.5,
                color="#222222",
            )

        ax.set_title(axis_label, loc="left", pad=12)
        ax.set_xlim(0, 1.05)
        ax.set_xticks(np.arange(0, 1.01, 0.2))
        ax.set_xticklabels([f"{value:.0%}" for value in np.arange(0, 1.01, 0.2)])
        ax.set_yticks(y_positions)
        ax.set_yticklabels([MODEL_LABELS[model] for model in MODEL_ORDER])
        style_axis(ax)

    completion_ax = figure.add_subplot(grid[1, 1])
    completion = np.array(
        [summary[model]["completed"] / summary[model]["scheduled"] for model in MODEL_ORDER]
    )
    colors = [MODEL_COLORS[model] for model in MODEL_ORDER]
    completion_ax.barh(
        y_positions, completion, height=0.5, color=colors, alpha=0.88
    )
    for y, value, model_id in zip(y_positions, completion, MODEL_ORDER):
        completed = summary[model_id]["completed"]
        completion_ax.text(
            min(value + 0.025, 1.015),
            y,
            f"{completed}/25  ({value:.0%})",
            va="center",
            ha="left",
            fontsize=9,
        )
    completion_ax.set_title("Technical completion", loc="left", pad=12)
    completion_ax.set_xlim(0, 1.08)
    completion_ax.set_xticks(np.arange(0, 1.01, 0.2))
    completion_ax.set_xticklabels(
        [f"{value:.0%}" for value in np.arange(0, 1.01, 0.2)]
    )
    completion_ax.set_yticks(y_positions)
    completion_ax.set_yticklabels([MODEL_LABELS[model] for model in MODEL_ORDER])
    completion_ax.text(
        1.0,
        1.04,
        "Provisional joint pass: 0/25 for every model",
        transform=completion_ax.transAxes,
        fontsize=9.5,
        fontweight="bold",
        color="#9B2226",
        ha="right",
        va="bottom",
    )
    style_axis(completion_ax)

    legend = [
        Line2D(
            [0],
            [0],
            color="#777777",
            linewidth=8,
            label="Scheduled-run mean (timeouts retained as zero)",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            markersize=7,
            markerfacecolor="white",
            markeredgecolor="#333333",
            markeredgewidth=1.6,
            linestyle="none",
            label="Successful-output mean",
        ),
        Line2D(
            [0],
            [0],
            color="#555555",
            linestyle=(0, (4, 3)),
            label="Provisional joint-pass target",
        ),
    ]
    figure.legend(
        handles=legend,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.875),
        ncol=3,
        frameon=False,
    )
    figure.suptitle(
        "FAIRiAgent ACTIVE-120: Model performance on the primary core",
        fontsize=20,
        fontweight="bold",
        x=0.03,
        y=0.985,
        ha="left",
    )
    figure.text(
        0.03,
        0.942,
        "100 scheduled runs · 25 per model · 3 independent documents · higher is better",
        fontsize=11,
        color="#555555",
        ha="left",
    )
    figure.text(
        0.03,
        0.025,
        "Values are scheduled-run / successful-output means. "
        "Solid bars retain timeouts as zero; open circles are successful-output means only. "
        "Three-document primary core does not support population-level ranking.",
        fontsize=9.5,
        color="#555555",
        ha="left",
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg", "pdf"):
        figure.savefig(
            OUTPUT / f"fig_active120_model_performance.{extension}",
            dpi=320,
            bbox_inches="tight",
        )
    plt.close(figure)


def generate_radar_figure(summary: dict[str, dict]) -> None:
    axis_labels = [axis_label for _, axis_label, _ in AXES]
    thresholds = np.array([threshold for _, _, threshold in AXES])
    angles = np.linspace(0, 2 * np.pi, len(AXES), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    figure = plt.figure(figsize=(13, 8.5), facecolor="white")
    grid = figure.add_gridspec(
        1,
        2,
        width_ratios=[1.45, 1],
        left=0.06,
        right=0.96,
        top=0.82,
        bottom=0.12,
        wspace=0.22,
    )
    radar_ax = figure.add_subplot(grid[0, 0], polar=True)
    table_ax = figure.add_subplot(grid[0, 1])

    radar_ax.set_theta_offset(np.pi / 2)
    radar_ax.set_theta_direction(-1)
    radar_ax.set_xticks(angles)
    radar_ax.set_xticklabels(axis_labels, fontsize=11, fontweight="bold")
    radar_ax.tick_params(axis="x", pad=14)
    radar_ax.set_ylim(0, 1.0)
    radar_ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    radar_ax.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], color="#666666")
    radar_ax.set_rlabel_position(8)
    radar_ax.grid(color="#D5D5D5", linewidth=0.8)
    radar_ax.spines["polar"].set_color("#BDBDBD")

    closed_thresholds = np.concatenate([thresholds, [thresholds[0]]])
    radar_ax.plot(
        closed_angles,
        closed_thresholds,
        color="#333333",
        linestyle=(0, (5, 3)),
        linewidth=2,
        label="Provisional joint-pass thresholds",
        zorder=5,
    )
    radar_ax.fill(
        closed_angles,
        closed_thresholds,
        color="#777777",
        alpha=0.035,
        zorder=1,
    )

    markers = ["o", "s", "^", "D"]
    line_styles = ["-", "--", "-.", ":"]
    for model_id, marker, line_style in zip(
        MODEL_ORDER, markers, line_styles
    ):
        values = np.array(
            [
                summary[model_id]["scheduled_mean"][axis_id]
                for axis_id, _, _ in AXES
            ]
        )
        closed_values = np.concatenate([values, [values[0]]])
        completed = summary[model_id]["completed"]
        radar_ax.plot(
            closed_angles,
            closed_values,
            color=MODEL_COLORS[model_id],
            linewidth=2.4,
            linestyle=line_style,
            marker=marker,
            markersize=6,
            label=f"{MODEL_LABELS[model_id]}  ·  {completed}/25 completed",
            zorder=4,
        )
        radar_ax.fill(
            closed_angles,
            closed_values,
            color=MODEL_COLORS[model_id],
            alpha=0.045,
            zorder=2,
        )

    radar_ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.27),
        ncol=2,
        frameon=False,
        fontsize=9.5,
        handlelength=2.8,
    )

    table_ax.axis("off")
    table_ax.set_title(
        "Exact scheduled-run means",
        loc="left",
        fontsize=14,
        fontweight="bold",
        pad=18,
    )
    column_labels = ["Model", "Field rec.", "GT-wide val.", "Structure", "Done"]
    cell_text = []
    for model_id in MODEL_ORDER:
        means = summary[model_id]["scheduled_mean"]
        cell_text.append(
            [
                "DeepSeek Flash"
                if model_id == "deepseek_v4-flash_v1.4.0"
                else MODEL_LABELS[model_id],
                f"{means['information_coverage']:.1%}",
                f"{means['value_accuracy']:.1%}",
                f"{means['structural_fidelity']:.1%}",
                f"{summary[model_id]['completed']}/25",
            ]
        )
    table = table_ax.table(
        cellText=cell_text,
        colLabels=column_labels,
        cellLoc="center",
        colLoc="center",
        loc="upper left",
        bbox=[0, 0.43, 1, 0.48],
        colWidths=[0.34, 0.16, 0.18, 0.16, 0.14],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("#D8D8D8")
        cell.set_linewidth(0.7)
        if row == 0:
            cell.set_facecolor("#EEEEEE")
            cell.set_text_props(fontweight="bold")
        elif column == 0:
            cell.set_text_props(ha="left", fontweight="bold")
            cell.set_facecolor("#FAFAFA")
        else:
            cell.set_facecolor("white")

    table_ax.text(
        0,
        0.34,
        "Provisional joint pass",
        transform=table_ax.transAxes,
        fontsize=11,
        fontweight="bold",
    )
    table_ax.text(
        0,
        0.285,
        "0/25 for every model",
        transform=table_ax.transAxes,
        fontsize=15,
        fontweight="bold",
        color="#9B2226",
    )
    table_ax.text(
        0,
        0.19,
        "Radar area is not an overall score.\n"
        "Each axis remains a separate outcome.",
        transform=table_ax.transAxes,
        fontsize=10,
        color="#555555",
        linespacing=1.5,
    )

    figure.suptitle(
        "FAIRiAgent ACTIVE-120: Primary-core model radar",
        x=0.04,
        y=0.97,
        ha="left",
        fontsize=21,
        fontweight="bold",
    )
    figure.text(
        0.04,
        0.91,
        "100 primary runs · 25 per model · 3 independent documents · "
        "supplemental s41467 excluded",
        fontsize=11,
        color="#555555",
        ha="left",
    )
    figure.text(
        0.04,
        0.035,
        "Scheduled-run means retain timeouts as zero. "
        "The radar is descriptive and does not establish statistical significance "
        "or population-level model ranking.",
        fontsize=9.5,
        color="#555555",
        ha="left",
    )

    for extension in ("png", "svg", "pdf"):
        figure.savefig(
            OUTPUT / f"fig_active120_model_radar.{extension}",
            dpi=320,
            bbox_inches="tight",
        )
    plt.close(figure)


def task_decomposition_summary(primary: list[dict]) -> dict[str, dict]:
    """Derive task-specific diagnostics without relabeling the joint estimand.

    The conditional fill value is deliberately marked diagnostic: it is computed only
    for runs with non-zero field recovery and is not an oracle-field Task-B result.
    """

    result: dict[str, dict] = {}
    for model_id in MODEL_ORDER:
        rows = [row for row in primary if row["model_id"] == model_id]
        conditional = [
            row["axes"]["value_accuracy"] / row["axes"]["information_coverage"]
            for row in rows
            if row["axes"]["information_coverage"] > 0
        ]
        result[model_id] = {
            "field_recovery": float(np.mean([row["axes"]["information_coverage"] for row in rows])),
            "structural_fidelity": float(np.mean([row["axes"]["structural_fidelity"] for row in rows])),
            "gt_wide_value": float(np.mean([row["axes"]["value_accuracy"] for row in rows])),
            "conditional_fill": float(np.mean(conditional)) if conditional else None,
            "conditional_n": len(conditional),
            "completed": sum(row["status"] == "success" for row in rows),
        }
    return result


def generate_task_decomposition_figure(
    task_summary: dict[str, dict],
) -> None:
    """Generate a task-decomposed model comparison figure.

    Task A is represented by current metadata-reconstruction proxies. Task B is
    shown with both the failure-preserving GT-wide score and the derived conditional
    diagnostic; the latter is explicitly not an independent oracle-field benchmark.
    """

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    figure = plt.figure(figsize=(16, 10), facecolor="white")
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.05, 0.95],
        left=0.08,
        right=0.97,
        top=0.86,
        bottom=0.12,
        hspace=0.45,
        wspace=0.32,
    )
    y_positions = np.arange(len(MODEL_ORDER))[::-1]
    colors = [MODEL_COLORS[model] for model in MODEL_ORDER]

    reconstruction_ax = figure.add_subplot(grid[0, 0])
    reconstruction_metrics = [
        ("field_recovery", "Field recovery", 0.70),
        ("structural_fidelity", "Structure", 0.75),
    ]
    bar_height = 0.28
    offsets = np.linspace(-bar_height / 2, bar_height / 2, len(reconstruction_metrics))
    metric_colors = {
        "field_recovery": "#0072B2",
        "structural_fidelity": "#009E73",
    }
    for offset, (metric, label, _) in zip(offsets, reconstruction_metrics):
        values = np.array([task_summary[model][metric] for model in MODEL_ORDER])
        reconstruction_ax.barh(
            y_positions + offset,
            values,
            height=bar_height * 0.85,
            color=metric_colors[metric],
            alpha=0.86 if metric != "field_recovery" else 1.0,
            label=label,
        )
        for y, value in zip(y_positions + offset, values):
            reconstruction_ax.text(
                min(value + 0.015, 0.99), y, f"{value:.0%}",
                va="center", fontsize=8.3, color="#222222",
            )
    for _, _, threshold in reconstruction_metrics:
        # These are visual references from the current joint profile, not frozen
        # Task-A thresholds.
        reconstruction_ax.axvline(
            threshold, color="#777777", linestyle=(0, (3, 3)), linewidth=0.8, alpha=0.65
        )
    reconstruction_ax.set_title("Task A proxy — metadata reconstruction", loc="left", pad=12)
    reconstruction_ax.text(
        0.0, 1.02,
        "Field recovery = GT value presence proxy; structure = sheet placement + row alignment.",
        transform=reconstruction_ax.transAxes, fontsize=8.5, color="#555555",
    )
    reconstruction_ax.set_xlim(0, 1.05)
    reconstruction_ax.set_xticks(np.arange(0, 1.01, 0.2))
    reconstruction_ax.set_xticklabels([f"{x:.0%}" for x in np.arange(0, 1.01, 0.2)])
    reconstruction_ax.set_yticks(y_positions)
    reconstruction_ax.set_yticklabels([MODEL_LABELS[model] for model in MODEL_ORDER])
    reconstruction_ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    style_axis(reconstruction_ax)

    filling_ax = figure.add_subplot(grid[0, 1])
    gt_values = np.array([task_summary[model]["gt_wide_value"] for model in MODEL_ORDER])
    conditional_values = np.array([
        task_summary[model]["conditional_fill"] or 0.0 for model in MODEL_ORDER
    ])
    filling_ax.barh(
        y_positions, gt_values, height=0.45, color=colors, alpha=0.82,
        label="GT-wide value score (scheduled)",
    )
    filling_ax.scatter(
        conditional_values, y_positions, marker="o", s=72,
        facecolors="white", edgecolors=colors, linewidths=2,
        zorder=4, label="Conditional fill diagnostic",
    )
    for y, model, gt_value, cond_value in zip(
        y_positions, MODEL_ORDER, gt_values, conditional_values
    ):
        n = task_summary[model]["conditional_n"]
        filling_ax.text(
            min(max(gt_value, cond_value) + 0.02, 0.99), y,
            f"{gt_value:.0%} / {cond_value:.0%} (n={n})",
            va="center", fontsize=8.3, color="#222222",
        )
    filling_ax.axvline(0.75, color="#777777", linestyle=(0, (3, 3)), linewidth=1.0)
    filling_ax.set_title("Task B — value filling", loc="left", pad=12)
    filling_ax.text(
        0.0, 1.02,
        "Conditional values are selection-biased; dashed 75% is a joint reference, not a Task-B threshold.",
        transform=filling_ax.transAxes, fontsize=8.5, color="#555555",
    )
    filling_ax.set_xlim(0, 1.05)
    filling_ax.set_xticks(np.arange(0, 1.01, 0.2))
    filling_ax.set_xticklabels([f"{x:.0%}" for x in np.arange(0, 1.01, 0.2)])
    filling_ax.set_yticks(y_positions)
    filling_ax.set_yticklabels([MODEL_LABELS[model] for model in MODEL_ORDER])
    filling_ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2,
        frameon=False, fontsize=8.5,
    )
    style_axis(filling_ax)

    scatter_ax = figure.add_subplot(grid[1, 0])
    for model, color in zip(MODEL_ORDER, colors):
        row = task_summary[model]
        scatter_ax.scatter(
            row["field_recovery"], row["conditional_fill"],
            s=150, color=color, edgecolor="white", linewidth=1.2,
            label=MODEL_LABELS[model], zorder=3,
        )
        scatter_ax.annotate(
            MODEL_LABELS[model], (row["field_recovery"], row["conditional_fill"]),
            xytext=(7, 5), textcoords="offset points", fontsize=8.4,
        )
    scatter_ax.axvline(0.70, color="#777777", linestyle=(0, (3, 3)), linewidth=0.9)
    scatter_ax.axhline(0.75, color="#777777", linestyle=(0, (3, 3)), linewidth=0.9)
    scatter_ax.set_xlim(0, 0.82)
    scatter_ax.set_ylim(0.55, 0.85)
    scatter_ax.set_xlabel("Field recovery / presence")
    scatter_ax.set_ylabel("Conditional fill diagnostic")
    scatter_ax.set_title("Selection–filling relationship", loc="left", pad=12)
    scatter_ax.text(
        0.02, 0.03,
        "Dashed lines are current joint-profile references;\nnot calibrated task-specific acceptance boundaries.",
        transform=scatter_ax.transAxes, fontsize=8.2, color="#555555",
    )
    scatter_ax.grid(color="#D9D9D9", linewidth=0.7)
    scatter_ax.set_axisbelow(True)
    scatter_ax.spines[["top", "right"]].set_visible(False)

    table_ax = figure.add_subplot(grid[1, 1])
    table_ax.axis("off")
    table_ax.set_title("Primary-100 task decomposition", loc="left", pad=12)
    table_rows = []
    for model in MODEL_ORDER:
        row = task_summary[model]
        table_rows.append([
            MODEL_LABELS[model],
            f"{row['completed']}/25",
            f"{row['field_recovery']:.1%}",
            f"{row['structural_fidelity']:.1%}",
            f"{row['gt_wide_value']:.1%}",
            f"{row['conditional_fill']:.1%} ({row['conditional_n']})",
        ])
    table = table_ax.table(
        cellText=table_rows,
        colLabels=["Model", "Done", "Field\nrecovery", "Structure", "GT-wide\nvalue", "Conditional\nfill†"],
        cellLoc="center", colLoc="center", loc="upper left",
        bbox=[0, 0.14, 1, 0.74],
        colWidths=[0.28, 0.10, 0.15, 0.14, 0.15, 0.18],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.2)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("#D8D8D8")
        cell.set_linewidth(0.6)
        if row == 0:
            cell.set_facecolor("#EEEEEE")
            cell.set_text_props(fontweight="bold")
        elif column == 0:
            cell.set_facecolor("#FAFAFA")
            cell.set_text_props(ha="left", fontweight="bold")
        else:
            cell.set_facecolor("white")
    table_ax.text(
        0, 0.03,
        "† Derived only for runs with field recovery > 0; not an oracle-field Task-B result.",
        transform=table_ax.transAxes, fontsize=8.2, color="#555555",
    )

    figure.suptitle(
        "FAIRiAgent ACTIVE-120: Separate metadata reconstruction from value filling",
        x=0.05, y=0.96, ha="left", fontsize=20, fontweight="bold",
    )
    figure.text(
        0.05, 0.915,
        "Primary core: 100 scheduled runs · 25 per model · 3 independent documents · failures retained",
        fontsize=11, color="#555555", ha="left",
    )
    figure.text(
        0.05, 0.035,
        "Task A uses current metadata-reconstruction proxies. Task B's conditional values are descriptive only;\n"
        "a fixed oracle package/field-list evaluation is required for an independent value-filling claim.",
        fontsize=9.3, color="#555555", ha="left",
    )
    for extension in ("png", "svg", "pdf"):
        figure.savefig(
            OUTPUT / f"fig_active120_task_decomposition.{extension}",
            dpi=320, bbox_inches="tight",
        )
    plt.close(figure)


def write_model_comparison(summary: dict[str, dict], task_summary: dict[str, dict]) -> None:
    """Persist the four-model comparator and its publication claim boundary."""

    payload = {
        "schema_version": "fairiagent.active120_model_comparison.v1",
        "release": "benchmark-v2-20260721.active120_frozen_four_model",
        "status": "frozen_existing_results",
        "scope": {
            "primary_core": {
                "scheduled_count": 100,
                "independent_document_count": 3,
                "models": 4,
                "cells_per_model": 25,
            },
            "supplemental": {
                "scheduled_count": 20,
                "independent_document_count": 1,
                "document": "petase_10_1038_s41467-022-35237-x",
                "excluded_from_primary_inference": True,
            },
            "total_active120": 120,
        },
        "scored_models": [
            {
                "model_id": model_id,
                "label": MODEL_LABELS[model_id],
                "scheduled_primary": summary[model_id]["scheduled"],
                "completed_primary": summary[model_id]["completed"],
                "metrics": task_summary[model_id],
            }
            for model_id in MODEL_ORDER
        ],
        "task_decomposition": {
            "task_a": "metadata_reconstruction_proxy",
            "task_b": "value_filling_diagnostic",
            "task_b_oracle_field_evaluation": "not_available_in_current_runs",
        },
        "publication_assessment": {
            "status": "reporting_ready_with_scope_limits",
            "publishable_as": [
                "a reproducible four-model feasibility and failure-analysis benchmark",
                "a descriptive comparison on the prespecified primary core",
                "a methods template for future matched model extensions",
            ],
            "not_supported": [
                "population-level model ranking or SOTA claim",
                "production-ready autonomous curation claim",
                "independent Task-A metadata-selection accuracy",
                "independent oracle-field Task-B value-filling accuracy",
            ],
            "blocking_limitations": [
                "only three independent primary documents",
                "field recovery is a values-first presence proxy",
                "GT-wide value score conflates selection and filling",
                "joint thresholds are provisional and not a frozen calibration result",
            ],
        },
    }
    MODEL_COMPARISON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    MODEL_COMPARISON_OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    primary, cohorts = load_primary_results()
    summary = summarize(primary, cohorts)
    task_summary = task_decomposition_summary(primary)
    TASK_SUMMARY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TASK_SUMMARY_OUTPUT.write_text(
        json.dumps(
            {
                "schema_version": "fairiagent.active120_task_decomposition.v1",
                "scope": "primary_core",
                "scheduled_count": len(primary),
                "independent_document_count": 3,
                "task_a": {
                    "name": "metadata_reconstruction_proxy",
                    "metrics": ["field_recovery", "structural_fidelity"],
                    "field_recovery_note": "values-first populated GT presence proxy; not a complete selection score",
                },
                "task_b": {
                    "name": "value_filling_diagnostic",
                    "gt_wide_value_note": "failure-preserving score over all populated GT fields",
                    "conditional_fill_note": "derived only for runs with field recovery > 0; not an oracle-field Task-B result",
                },
                "models": task_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generate_figure(summary)
    generate_radar_figure(summary)
    generate_task_decomposition_figure(task_summary)
    write_model_comparison(summary, task_summary)
    print(OUTPUT / "fig_active120_model_performance.png")
    print(OUTPUT / "fig_active120_model_radar.png")
    print(OUTPUT / "fig_active120_task_decomposition.png")
    print(TASK_SUMMARY_OUTPUT)
    print(MODEL_COMPARISON_OUTPUT)


if __name__ == "__main__":
    main()
