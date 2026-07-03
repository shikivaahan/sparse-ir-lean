#!/usr/bin/env python3
"""Regenerate Stage 6 cleanup figures from committed JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parent


def _load() -> tuple[list[dict], dict]:
    rows = [json.loads(line) for line in (ROOT / "results.jsonl").read_text().splitlines()]
    metrics = json.loads((ROOT / "metrics.json").read_text())
    return rows, metrics


def h2(metrics: dict) -> None:
    houses = list(metrics["H11"]["primary_bins"])
    wrong = [
        metrics["H11"]["primary_bins"][house]["confident_wrong_rate"]["estimate"]
        for house in houses
    ]
    x = range(len(houses))
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar([index - 0.18 for index in x], wrong, width=0.36, label="Unchecked wrong")
    ax.bar([index + 0.18 for index in x], [0] * len(houses), width=0.36, label="Mode-0 catastrophic")
    ax.set(xticks=list(x), xticklabels=houses, xlabel="Houses", ylabel="Rate", ylim=(0, 1))
    ax.set_title("H2: Lean gating removes committed wrong answers")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "h2_catastrophic_rate.png", dpi=180)
    plt.close(fig)


def h3(metrics: dict) -> None:
    curve = metrics["H3"]["ptrue_curve"]
    point = metrics["H3"]["lean_point"]
    fig, ax = plt.subplots(figsize=(6.4, 4.5))
    ax.plot(
        [item["coverage"] for item in curve],
        [item["selective_risk"] for item in curve],
        marker="o",
        label="P(True) sweep",
    )
    ax.scatter([point["coverage"]], [point["selective_risk"]], s=90, label="Lean Mode-0")
    ax.set(xlabel="Coverage", ylabel="Selective risk", xlim=(0, 1.02), ylim=(-0.02, 1))
    ax.set_title("H3: Lean point vs P(True) risk-coverage")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "h3_risk_coverage.png", dpi=180)
    plt.close(fig)


def h11(metrics: dict) -> None:
    bins = metrics["H11"]["primary_bins"]
    houses = [int(value) for value in bins]
    wrong = [bins[str(house)]["confident_wrong_rate"] for house in houses]
    coverage = [bins[str(house)]["mode0_coverage"] for house in houses]

    def errors(values: list[dict]) -> list[list[float]]:
        return [
            [max(0.0, value["estimate"] - value["low"]) for value in values],
            [max(0.0, value["high"] - value["estimate"]) for value in values],
        ]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.errorbar(
        houses,
        [value["estimate"] for value in wrong],
        yerr=errors(wrong),
        marker="o",
        capsize=4,
        label="Unchecked wrong",
    )
    ax.errorbar(
        houses,
        [value["estimate"] for value in coverage],
        yerr=errors(coverage),
        marker="o",
        capsize=4,
        label="Mode-0 coverage",
    )
    ax.set(xticks=houses, xlabel="Houses", ylabel="Rate", ylim=(0, 1))
    ax.set_title("H11: difficulty scaling (Wilson 95% CI)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "h11_difficulty_scaling.png", dpi=180)
    plt.close(fig)


def h5(metrics: dict) -> None:
    h5_metrics = metrics["H5_single_shot"]
    arms = ["cheap_mode0", "frontier_mode0"]
    labels = ["DeepSeek + Lean", "Opus + Lean"]
    coverage = [h5_metrics[arm]["coverage"] for arm in arms]
    cost = [h5_metrics[arm]["cost_per_verified_correct"] for arm in arms]
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.scatter(coverage, cost, s=110)
    for label, x_value, y_value in zip(labels, coverage, cost, strict=True):
        ax.annotate(label, (x_value, y_value), xytext=(7, 7), textcoords="offset points")
    ax.set(xlabel="Mode-0 coverage", ylabel="Cost per verified correct (USD)", xlim=(0, 1.02))
    ax.set_title("H5 single-shot: paired cost vs coverage")
    fig.tight_layout()
    fig.savefig(ROOT / "h5_cost_coverage.png", dpi=180)
    plt.close(fig)


def main() -> int:
    _, metrics = _load()
    h2(metrics)
    h3(metrics)
    h11(metrics)
    h5(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
