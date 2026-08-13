import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


SESSION = Path(
    r"D:\Chenghang\Training_Log\20260807\SaccadeMultiStim_20260807_141246"
)
PARSED = Path(
    r"D:\Chenghang\FineVision\tmp\SaccadeMultiStim_20260807_141246_gaze"
)
TASK_LOG = SESSION / "SaccadeMultiStim_task_log_20260807_141246.csv"
PARAMS = SESSION / "SaccadeMultiStim_parameters_20260807_141246.json"
MESSAGES = PARSED / "messages.csv"
SAMPLES = PARSED / "samples.csv"


def pixels_to_degrees(pixels, distance_cm, monitor_cm, resolution):
    physical_cm = np.asarray(pixels, dtype=float) * monitor_cm / resolution
    return np.degrees(2.0 * np.arctan(physical_cm / (2.0 * distance_cm)))


def load_trial_events():
    event_patterns = {
        "trial_start_ms": re.compile(r"^TRIALID\s+(\d+)$"),
        "fix_on_ms": re.compile(r"^FIX_ON TRIAL\s+(\d+)$"),
        "gaze_acquired_ms": re.compile(r"^GAZE_ACQUIRED TRIAL\s+(\d+)$"),
        "fix_off_ms": re.compile(r"^FIX_OFF TRIAL\s+(\d+)$"),
        "stim_on_ms": re.compile(r"^STIM_ON TRIAL\s+(\d+)$"),
        "target_enter_ms": re.compile(r"^TARGET_ENTER TRIAL\s+(\d+)$"),
        "stim_window_end_ms": re.compile(r"^STIM_WINDOW_END TRIAL\s+(\d+)$"),
    }
    events = {}
    with MESSAGES.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            message = row["message"].strip()
            for name, pattern in event_patterns.items():
                match = pattern.match(message)
                if match:
                    trial = int(match.group(1))
                    events.setdefault(trial, {})[name] = int(
                        float(row["tracker_time_ms"])
                    )
                    break
    return events


def window_mean(sample_times, sample_x, sample_y, end_ms, duration_ms=100):
    left = np.searchsorted(sample_times, end_ms - duration_ms, side="left")
    right = np.searchsorted(sample_times, end_ms, side="right")
    x = sample_x[left:right]
    y = sample_y[left:right]
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < duration_ms * 0.7:
        return None
    return float(np.mean(x[valid])), float(np.mean(y[valid])), int(valid.sum())


def trailing_median(values, window):
    output = np.full_like(values, np.nan, dtype=float)
    for index in range(window - 1, len(values)):
        output[index] = np.median(values[index - window + 1:index + 1])
    return output


def main():
    with PARAMS.open("r", encoding="utf-8") as handle:
        params = json.load(handle)
    task = pd.read_csv(TASK_LOG)
    task["Trial"] = pd.to_numeric(task["Trial"], errors="coerce")
    task = task.dropna(subset=["Trial"]).copy()
    task["Trial"] = task["Trial"].astype(int)
    events = load_trial_events()

    samples = pd.read_csv(
        SAMPLES,
        usecols=["tracker_time_ms", "gaze_x", "gaze_y"],
        na_values=["."],
    )
    sample_times = samples["tracker_time_ms"].to_numpy(dtype=np.int64)
    sample_x = pd.to_numeric(samples["gaze_x"], errors="coerce").to_numpy()
    sample_y = pd.to_numeric(samples["gaze_y"], errors="coerce").to_numpy()

    distance = float(params["Viewing Distance (cm)"])
    monitor_width = float(params["Subject Monitor Width (cm)"])
    monitor_height = float(params["Subject Monitor Height (cm)"])
    fix_target_x = float(params["Fixation Position X (deg)"])
    fix_target_y = float(params["Fixation Position Y (deg)"])

    rows = []
    formal_success = task[
        (task["Status"] == "Success")
        & (~task["Is_Control"].astype(str).str.lower().eq("true"))
    ]
    for _, trial_row in formal_success.iterrows():
        trial = int(trial_row["Trial"])
        trial_events = events.get(trial, {})
        fix_end = trial_events.get("fix_off_ms")
        stim_end = trial_events.get("stim_window_end_ms")
        if fix_end is None or stim_end is None:
            continue
        fix_mean = window_mean(
            sample_times, sample_x, sample_y, fix_end, duration_ms=100
        )
        stim_mean = window_mean(
            sample_times, sample_x, sample_y, stim_end, duration_ms=100
        )
        if fix_mean is None or stim_mean is None:
            continue

        fix_px_x = fix_mean[0] - 1920.0 / 2.0
        fix_px_y = 1080.0 / 2.0 - fix_mean[1]
        stim_px_x = stim_mean[0] - 1920.0 / 2.0
        stim_px_y = 1080.0 / 2.0 - stim_mean[1]
        fix_gaze_x = float(
            pixels_to_degrees(fix_px_x, distance, monitor_width, 1920)
        )
        fix_gaze_y = float(
            pixels_to_degrees(fix_px_y, distance, monitor_height, 1080)
        )
        stim_gaze_x = float(
            pixels_to_degrees(stim_px_x, distance, monitor_width, 1920)
        )
        stim_gaze_y = float(
            pixels_to_degrees(stim_px_y, distance, monitor_height, 1080)
        )
        stim_target_x = float(trial_row["Stim_Pos_X_deg"])
        stim_target_y = float(trial_row["Stim_Pos_Y_deg"])
        fix_error_x = fix_gaze_x - fix_target_x
        fix_error_y = fix_gaze_y - fix_target_y
        raw_error_x = stim_gaze_x - stim_target_x
        raw_error_y = stim_gaze_y - stim_target_y
        corrected_error_x = raw_error_x - fix_error_x
        corrected_error_y = raw_error_y - fix_error_y
        rows.append({
            "trial": trial,
            "minute": float(trial_row["Time_TrialStart"]) / 60.0,
            "stim_x": stim_target_x,
            "stim_y": stim_target_y,
            "fix_ex": fix_error_x,
            "fix_ey": fix_error_y,
            "raw_ex": raw_error_x,
            "raw_ey": raw_error_y,
            "cor_ex": corrected_error_x,
            "cor_ey": corrected_error_y,
            "fix_n": fix_mean[2],
            "stim_n": stim_mean[2],
        })

    analysis = pd.DataFrame(rows).sort_values("trial").reset_index(drop=True)
    for prefix in ("fix", "raw", "cor"):
        analysis[f"{prefix}_norm"] = np.hypot(
            analysis[f"{prefix}_ex"], analysis[f"{prefix}_ey"]
        )

    pearson_x = stats.pearsonr(analysis["fix_ex"], analysis["raw_ex"])
    pearson_y = stats.pearsonr(analysis["fix_ey"], analysis["raw_ey"])
    wilcoxon = stats.wilcoxon(
        analysis["raw_norm"],
        analysis["cor_norm"],
        alternative="greater",
    )

    design = np.column_stack([
        np.ones(len(analysis)), analysis["fix_ex"], analysis["fix_ey"]
    ])
    response = analysis[["raw_ex", "raw_ey"]].to_numpy()
    coefficients, _, _, _ = np.linalg.lstsq(design, response, rcond=None)
    predicted = design @ coefficients
    residual_ss = np.sum((response - predicted) ** 2)
    total_ss = np.sum((response - response.mean(axis=0)) ** 2)
    r_squared = 1.0 - residual_ss / total_ss

    rng = np.random.default_rng(20260807)
    observed_median = float(analysis["cor_norm"].median())
    shuffled_medians = []
    raw_error = analysis[["raw_ex", "raw_ey"]].to_numpy()
    fix_error = analysis[["fix_ex", "fix_ey"]].to_numpy()
    for _ in range(5000):
        shuffled = fix_error[rng.permutation(len(fix_error))]
        shuffled_medians.append(
            float(np.median(np.linalg.norm(raw_error - shuffled, axis=1)))
        )
    shuffled_medians = np.asarray(shuffled_medians)
    shuffle_p = float(
        (1 + np.sum(shuffled_medians <= observed_median))
        / (len(shuffled_medians) + 1)
    )

    minimum_segment = 15
    vectors = analysis[["fix_ex", "fix_ey"]].to_numpy()
    split_scores = []
    for split in range(minimum_segment, len(vectors) - minimum_segment + 1):
        left = vectors[:split]
        right = vectors[split:]
        score = np.sum((left - left.mean(axis=0)) ** 2)
        score += np.sum((right - right.mean(axis=0)) ** 2)
        split_scores.append((score, split))
    _, best_split = min(split_scores)
    early_bias = np.mean(vectors[:best_split], axis=0)
    late_bias = np.mean(vectors[best_split:], axis=0)
    shift_vector = late_bias - early_bias
    shift_size = float(np.linalg.norm(shift_vector))
    change_trial = int(analysis.iloc[best_split]["trial"])
    change_minute = float(analysis.iloc[best_split]["minute"])

    rolling_window = 15
    analysis["roll_fix_x"] = trailing_median(
        analysis["fix_ex"].to_numpy(), rolling_window
    )
    analysis["roll_fix_y"] = trailing_median(
        analysis["fix_ey"].to_numpy(), rolling_window
    )
    analysis["roll_fix_norm"] = np.hypot(
        analysis["roll_fix_x"], analysis["roll_fix_y"]
    )
    over_one = analysis["roll_fix_norm"].to_numpy() > 1.0
    sustained_index = None
    for index in range(rolling_window - 1, len(over_one) - 4):
        if np.all(over_one[index:index + 5]):
            sustained_index = index
            break

    status_bins = []
    task["minute"] = pd.to_numeric(task["Time_TrialStart"], errors="coerce") / 60.0
    task = task.dropna(subset=["minute"])
    max_minute = float(task["minute"].max())
    for start in np.arange(0.0, math.ceil(max_minute / 5.0) * 5.0, 5.0):
        subset = task[(task["minute"] >= start) & (task["minute"] < start + 5.0)]
        if subset.empty:
            continue
        success = subset["Status"].isin(["Success", "Control_Success"]).sum()
        status_bins.append({
            "start": float(start),
            "end": float(start + 5.0),
            "n": int(len(subset)),
            "success_rate": float(success / len(subset)),
            "nofix_rate": float(subset["Status"].str.contains("nofix", case=False).sum() / len(subset)),
            "break_rate": float(subset["Status"].str.contains("Break", case=False).sum() / len(subset)),
        })

    summary = {
        "formal_success_in_log": int(len(formal_success)),
        "analyzed_trials": int(len(analysis)),
        "fixation_target_deg": [fix_target_x, fix_target_y],
        "raw_error_median_deg": float(analysis["raw_norm"].median()),
        "corrected_error_median_deg": observed_median,
        "raw_error_mean_deg": float(analysis["raw_norm"].mean()),
        "corrected_error_mean_deg": float(analysis["cor_norm"].mean()),
        "fraction_improved": float(
            np.mean(analysis["cor_norm"] < analysis["raw_norm"])
        ),
        "pearson_x": [float(pearson_x.statistic), float(pearson_x.pvalue)],
        "pearson_y": [float(pearson_y.statistic), float(pearson_y.pvalue)],
        "wilcoxon": [float(wilcoxon.statistic), float(wilcoxon.pvalue)],
        "paired_shuffle_p": shuffle_p,
        "shuffle_median_mean_deg": float(shuffled_medians.mean()),
        "regression_coefficients": coefficients.tolist(),
        "regression_r_squared": float(r_squared),
        "change_trial": change_trial,
        "change_minute": change_minute,
        "early_fix_bias_deg": early_bias.tolist(),
        "late_fix_bias_deg": late_bias.tolist(),
        "fix_bias_shift_deg": shift_vector.tolist(),
        "fix_bias_shift_magnitude_deg": shift_size,
        "sustained_over_one_degree_trial": (
            int(analysis.iloc[sustained_index]["trial"])
            if sustained_index is not None else None
        ),
        "sustained_over_one_degree_minute": (
            float(analysis.iloc[sustained_index]["minute"])
            if sustained_index is not None else None
        ),
        "status_counts": task["Status"].value_counts().to_dict(),
        "status_bins": status_bins,
    }
    epoch_metrics = {}
    for label, threshold in (
        ("before_change", change_trial),
        ("after_change", change_trial),
        ("before_sustained_1deg", (
            int(analysis.iloc[sustained_index]["trial"])
            if sustained_index is not None else None
        )),
        ("after_sustained_1deg", (
            int(analysis.iloc[sustained_index]["trial"])
            if sustained_index is not None else None
        )),
    ):
        if threshold is None:
            continue
        subset = (
            analysis[analysis["trial"] < threshold]
            if label.startswith("before")
            else analysis[analysis["trial"] >= threshold]
        )
        epoch_metrics[label] = {
            "threshold_trial": int(threshold),
            "n": int(len(subset)),
            "raw_median_deg": float(subset["raw_norm"].median()),
            "corrected_median_deg": float(subset["cor_norm"].median()),
            "fraction_improved": float(
                np.mean(subset["cor_norm"] < subset["raw_norm"])
            ),
        }
    summary["epoch_metrics"] = epoch_metrics
    payload_columns = [
        "trial", "minute", "stim_x", "stim_y", "fix_ex", "fix_ey",
        "raw_ex", "raw_ey", "cor_ex", "cor_ey", "raw_norm",
        "cor_norm", "roll_fix_x", "roll_fix_y", "roll_fix_norm",
    ]
    payload = analysis[payload_columns].round(4).replace({np.nan: None})
    compact_payload = json.dumps(
        payload.to_dict(orient="records"), separators=(",", ":")
    )
    if "--payload-only" in sys.argv:
        print(compact_payload)
        return
    print("SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("PAYLOAD")
    print(compact_payload)


if __name__ == "__main__":
    main()
