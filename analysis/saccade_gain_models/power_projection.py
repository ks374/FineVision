"""Approximate cluster-aware power projection for the contrast-to-gain slope.

This is a planning calculation, not a guarantee of future significance. It uses
the current main-model cluster-robust standard error and assumes that new
completed recording sessions have a comparable contrast design, residual
variance, and number of session-by-position clusters.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd
from scipy.stats import nct, t


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(SCRIPT_DIR / "outputs"))
    parser.add_argument(
        "--effect-sizes",
        nargs="+",
        type=float,
        default=[0.028, 0.020, 0.015],
        help="Candidate true gain percentage-point slopes per Weber unit.",
    )
    parser.add_argument("--power-targets", nargs="+", type=float, default=[0.8, 0.9])
    return parser.parse_args()


def power_at_multiplier(effect_size, current_se, multiplier, base_clusters, parameters):
    degrees_freedom = max(1, int(round(base_clusters * multiplier)) - parameters)
    critical = t.ppf(0.975, degrees_freedom)
    noncentrality = effect_size / (current_se / math.sqrt(multiplier))
    return nct.sf(critical, degrees_freedom, noncentrality) + nct.cdf(
        -critical, degrees_freedom, noncentrality
    )


def solve_multiplier(effect_size, current_se, base_clusters, parameters, target):
    lower, upper = 1.0, 2.0
    while power_at_multiplier(effect_size, current_se, upper, base_clusters, parameters) < target:
        upper *= 2.0
        if upper > 1000:
            raise RuntimeError("Could not reach requested power under this projection")
    for _ in range(60):
        midpoint = (lower + upper) / 2.0
        if power_at_multiplier(effect_size, current_se, midpoint, base_clusters, parameters) >= target:
            upper = midpoint
        else:
            lower = midpoint
    return upper


def main():
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    coefficients = pd.read_csv(output_dir / "model_coefficients.csv")
    fit = pd.read_csv(output_dir / "model_fit_summary.csv")
    run_counts = pd.read_csv(output_dir / "run_counts.csv")
    main_trials = pd.read_csv(output_dir / "trial_level_main.csv")

    coefficient = coefficients.loc[
        (coefficients["analysis_set"] == "main")
        & (coefficients["outcome"] == "gain_pct")
        & (coefficients["term"] == "contrast_weber_centered")
    ].iloc[0]
    fit_row = fit.loc[
        (fit["analysis_set"] == "main") & (fit["outcome"] == "gain_pct")
    ].iloc[0]
    completed_runs = run_counts[
        ~run_counts["session_instance"].str.contains("interrupted", case=False, na=False)
    ]
    run_cluster_counts = (
        main_trials.groupby("session_id")["position_cluster"]
        .nunique()
        .reset_index(name="clusters")
    )
    completed_runs = completed_runs.merge(run_cluster_counts, on="session_id", how="left")
    typical_trials = float(completed_runs["main_trials"].median())
    typical_clusters = float(completed_runs["clusters"].median())

    current_trials = int(fit_row["n"])
    current_clusters = int(fit_row["clusters"])
    parameters = 4
    rows = []
    for effect_size in args.effect_sizes:
        for target in args.power_targets:
            multiplier = solve_multiplier(
                effect_size,
                float(coefficient["cluster_se"]),
                current_clusters,
                parameters,
                target,
            )
            total_trials = current_trials * multiplier
            total_clusters = current_clusters * multiplier
            additional_sessions = math.ceil(
                max(0.0, total_clusters - current_clusters) / typical_clusters
            )
            rows.append(
                {
                    "assumed_true_beta_pct_per_weber": effect_size,
                    "target_power": target,
                    "required_information_multiplier": multiplier,
                    "projected_total_main_trials": total_trials,
                    "projected_additional_main_trials": total_trials - current_trials,
                    "projected_total_clusters": total_clusters,
                    "projected_additional_clusters": total_clusters - current_clusters,
                    "typical_completed_session_main_trials": typical_trials,
                    "typical_completed_session_clusters": typical_clusters,
                    "approx_additional_completed_sessions": additional_sessions,
                }
            )
    result = pd.DataFrame(rows)
    result.to_csv(output_dir / "power_projection.csv", index=False)

    lines = [
        "# Approximate power projection for the contrast-to-gain slope",
        "",
        f"Current estimate: beta={coefficient['estimate']:.6g} percentage points per Weber unit; cluster-robust SE={coefficient['cluster_se']:.6g}; current clusters={current_clusters}; current main trials={current_trials}.",
        "",
        "The projection assumes information scales with independent recording-session-by-position clusters and that future completed sessions resemble the current completed sessions.",
        "",
        "| Assumed true beta | Target power | Information multiplier | Additional main trials | Additional completed sessions |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in result.itertuples(index=False):
        lines.append(
            f"| {row.assumed_true_beta_pct_per_weber:.3g} | {row.target_power:.0%} | {row.required_information_multiplier:.2f} | {row.projected_additional_main_trials:.0f} | {row.approx_additional_completed_sessions} |"
        )
    lines.extend(
        [
            "",
            "This is not a promise that a p value will cross 0.05. It does not model new-day heterogeneity, changes in calibration/coordinate source, or publication-selection bias in the current point estimate.",
        ]
    )
    (output_dir / "power_projection.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
