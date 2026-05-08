"""Walk-forward + optimisation heatmaps (R81 + R82).

Both functions produce the SAME shape of output: a 2D matrix +
labelled axes + a structured ``HeatmapData`` payload that operators
hand to whatever renderer is available (matplotlib, seaborn, plotly,
or just the included plain-text dump).

Keeping the data shape uniform means the tearsheet renderer can call
``render_text`` once and the rest is window dressing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np


@dataclass(frozen=True)
class HeatmapData:
    """Generic heatmap payload."""

    title: str
    x_axis_name: str
    y_axis_name: str
    x_labels: List[str]
    y_labels: List[str]
    matrix: np.ndarray  # shape (len(y_labels), len(x_labels))


def walk_forward_heatmap(
    *,
    fold_metrics: Sequence[Dict[str, float]],
    metric_keys: Sequence[str] = ("sharpe", "calmar", "mdd"),
) -> HeatmapData:
    """R81 walk-forward matrix heatmap.

    Args:
        fold_metrics: list of per-fold dict (one entry per OOS window).
        metric_keys: which metric columns to surface, in order.

    Returns:
        :class:`HeatmapData` with x = fold index, y = metric.
    """
    if not fold_metrics:
        raise ValueError("fold_metrics is empty")
    n_folds = len(fold_metrics)
    matrix = np.zeros((len(metric_keys), n_folds), dtype=float)
    for j, fold in enumerate(fold_metrics):
        for i, key in enumerate(metric_keys):
            value = fold.get(key, float("nan"))
            matrix[i, j] = float(value)
    return HeatmapData(
        title="Walk-forward fold performance",
        x_axis_name="fold_index",
        y_axis_name="metric",
        x_labels=[f"f{j}" for j in range(n_folds)],
        y_labels=list(metric_keys),
        matrix=matrix,
    )


def optimisation_heatmap(
    *,
    param_x_name: str,
    param_y_name: str,
    x_values: Sequence[float],
    y_values: Sequence[float],
    fitness: Sequence[Sequence[float]],
    fitness_label: str = "calmar",
) -> HeatmapData:
    """R82 optimisation heatmap for a 2-parameter sweep.

    Args:
        param_x_name: parameter on the X axis.
        param_y_name: parameter on the Y axis.
        x_values: discrete sweep values for X.
        y_values: discrete sweep values for Y.
        fitness: 2D array shape (len(y_values), len(x_values)).
        fitness_label: short label used in the title.

    Returns:
        :class:`HeatmapData` ready for rendering.
    """
    matrix = np.asarray(fitness, dtype=float)
    if matrix.shape != (len(y_values), len(x_values)):
        raise ValueError(
            f"fitness shape {matrix.shape} does not match "
            f"(len(y_values), len(x_values)) = ({len(y_values)}, {len(x_values)})"
        )
    return HeatmapData(
        title=f"Optimisation fitness ({fitness_label})",
        x_axis_name=param_x_name,
        y_axis_name=param_y_name,
        x_labels=[f"{v:g}" for v in x_values],
        y_labels=[f"{v:g}" for v in y_values],
        matrix=matrix,
    )


def render_text(data: HeatmapData) -> str:
    """Plain-text heatmap dump for terminals + log artefacts."""
    rows = []
    rows.append(f"{data.title}  ({data.y_axis_name} x {data.x_axis_name})")
    header = "        " + "  ".join(f"{x:>8}" for x in data.x_labels)
    rows.append(header)
    for i, y_label in enumerate(data.y_labels):
        row_str = "  ".join(f"{v:>8.3f}" for v in data.matrix[i])
        rows.append(f"{y_label:>6}  {row_str}")
    return "\n".join(rows)


__all__ = [
    "HeatmapData",
    "walk_forward_heatmap",
    "optimisation_heatmap",
    "render_text",
]
