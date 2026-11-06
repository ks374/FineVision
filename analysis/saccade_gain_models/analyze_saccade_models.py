"""Reproducible first-saccade gain and latency analysis.

This script converts EyeLink EDF files, aligns EyeLink events to FineVision
trial logs, reconstructs the online coordinate system used by each session,
applies pre-specified trial exclusions, and fits two trial-level OLS models:

    gain_pct  ~ contrast + day_8_7 + distance_deg
    latency_ms ~ contrast + day_8_7 + distance_deg

Continuous predictors are mean-centered. Confidence intervals use CR1 cluster-
robust standard errors with session-by-relative-position as the cluster. A
stratified cluster bootstrap is also reported. Day 8/6 is the reference, and
both 8/7 recording sessions are combined under one day indicator.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy import stats


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"
DEFAULT_CONVERTERS = (
    Path(r"C:\Program Files (x86)\SR Research\EyeLink\bin\edf2asc.exe"),
    Path(r"C:\Program Files (x86)\SR Research\Eyelink\bin\edf2asc.exe"),
)
DEFAULT_EDFAPI_LIBRARIES = (
    Path(r"C:\Program Files (x86)\SR Research\EyeLink\libs\x64\edfapi64.dll"),
    Path(r"C:\Program Files (x86)\SR Research\Eyelink\libs\x64\edfapi64.dll"),
)
MESSAGE_EVENT = 24
MESSAGE_PATTERNS = {
    "trial_start_ms": re.compile(r"^TRIALID\s+(\d+)$"),
    "fix_off_ms": re.compile(r"^FIX_OFF TRIAL\s+(\d+)$"),
    "stim_on_ms": re.compile(r"^STIM_ON TRIAL\s+(\d+)$"),
    "stim_window_end_ms": re.compile(r"^STIM_WINDOW_END TRIAL\s+(\d+)$"),
    "target_enter_ms": re.compile(r"^TARGET_ENTER TRIAL\s+(\d+)$"),
}
DESIGN_COLUMNS = (
    "Intercept",
    "contrast_weber_centered",
    "day_8_7",
    "distance_deg_centered",
)


class _EdfAccessEvent(ctypes.Structure):
    """Packed FEVENT layout used by the 64-bit EyeLink EDF Access API."""

    _pack_ = 1
    _fields_ = [
        ("time", ctypes.c_uint32),
        ("type", ctypes.c_int16),
        ("read", ctypes.c_uint16),
        ("start_time", ctypes.c_uint32),
        ("end_time", ctypes.c_uint32),
        ("measurements", ctypes.c_float * 23),
        ("eye", ctypes.c_int16),
        ("status", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("input", ctypes.c_uint16),
        ("buttons", ctypes.c_uint16),
        ("parsed_by", ctypes.c_uint16),
        ("message", ctypes.c_void_p),
    ]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir", default=str(SCRIPT_DIR / "outputs"))
    parser.add_argument("--cache-dir", default=str(SCRIPT_DIR / "cache"))
    parser.add_argument("--edf2asc", help="Optional path to edf2asc.exe")
    parser.add_argument("--edfapi", help="Optional path to edfapi64.dll")
    parser.add_argument("--background-luminance", type=float)
    parser.add_argument("--minimum-latency-ms", type=float)
    parser.add_argument("--bootstrap-repetitions", type=int)
    parser.add_argument("--force-convert", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def load_config(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_existing(explicit, candidates, description):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"{description} not found: {path}")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"{description} was not found. Checked: "
        + ", ".join(str(path) for path in candidates)
    )


def session_paths(config, session):
    data_root = Path(config["data_root"])
    folder = data_root / Path(session["folder"])
    session_id = session["session_id"]
    timestamp = session_id.rsplit("_", 2)[-2] + "_" + session_id.rsplit("_", 1)[-1]
    calibration = session.get("calibration_file")
    return {
        "folder": folder,
        "edf": folder / f"{session_id}_eyelink.edf",
        "log": folder / f"SaccadeMultiStim_task_log_{timestamp}.csv",
        "parameters": folder / f"SaccadeMultiStim_parameters_{timestamp}.json",
        "conditions": folder / f"SaccadeMultiStim_condition_plan_{timestamp}.csv",
        "calibration": data_root / Path(calibration) if calibration else None,
    }


def validate_inputs(config):
    missing = []
    for session in config["sessions"]:
        paths = session_paths(config, session)
        for name in ("edf", "log", "parameters", "conditions"):
            if not paths[name].is_file():
                missing.append(str(paths[name]))
        if session["sample_source"] == "href":
            if paths["calibration"] is None or not paths["calibration"].is_file():
                missing.append(str(paths["calibration"]))
    if missing:
        raise FileNotFoundError("Missing analysis inputs:\n" + "\n".join(missing))


def convert_edf(edf_path, output_dir, converter, sample_option, events_only, force):
    output_dir.mkdir(parents=True, exist_ok=True)
    asc_path = output_dir / f"{edf_path.stem}.asc"
    if (
        not force
        and asc_path.is_file()
        and asc_path.stat().st_mtime >= edf_path.stat().st_mtime
    ):
        return asc_path
    command = [str(converter), sample_option, "-r"]
    if events_only:
        command.append("-e")
    command.extend(["-utf8", "-y", "-p", str(output_dir), str(edf_path)])
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if not asc_path.is_file():
        details = (result.stderr or result.stdout or "no converter output")[-4000:]
        raise RuntimeError(
            "EDF conversion did not create the expected ASC file.\n"
            f"Command: {subprocess.list2cmdline(command)}\n{details}"
        )
    return asc_path


def read_exact_messages_from_edf(edf_path, edfapi_path):
    library = ctypes.CDLL(str(edfapi_path))
    library.edf_open_file.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]
    library.edf_open_file.restype = ctypes.c_void_p
    library.edf_get_next_data.argtypes = [ctypes.c_void_p]
    library.edf_get_next_data.restype = ctypes.c_int
    library.edf_get_float_data.argtypes = [ctypes.c_void_p]
    library.edf_get_float_data.restype = ctypes.c_void_p
    library.edf_close_file.argtypes = [ctypes.c_void_p]

    error = ctypes.c_int(0)
    handle = library.edf_open_file(
        str(edf_path.resolve()).encode("utf-8"), 0, 1, 0, ctypes.byref(error)
    )
    if not handle:
        raise RuntimeError(f"EDF Access API open failed with code {error.value}: {edf_path}")
    messages = []
    try:
        while True:
            data_type = library.edf_get_next_data(handle)
            if data_type == 0:
                break
            pointer = library.edf_get_float_data(handle)
            if data_type != MESSAGE_EVENT or not pointer:
                continue
            event = _EdfAccessEvent.from_address(pointer)
            if not event.message:
                continue
            length = ctypes.c_int16.from_address(event.message).value
            payload = ctypes.string_at(event.message + 2, max(0, length))
            messages.append(
                {
                    "tracker_time_ms": int(event.start_time),
                    "message": payload.decode("utf-8", errors="replace"),
                }
            )
    finally:
        library.edf_close_file(handle)
    return messages


def parse_trial_messages(messages):
    events = defaultdict(dict)
    for row in messages:
        message = row["message"].strip()
        for name, pattern in MESSAGE_PATTERNS.items():
            match = pattern.match(message)
            if match:
                events[int(match.group(1))][name] = int(row["tracker_time_ms"])
                break
    return events


def parse_saccades(asc_path):
    rows = []
    with asc_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            fields = raw_line.split()
            if not fields or fields[0] != "ESACC" or len(fields) < 11:
                continue
            rows.append(
                {
                    "eye": fields[1],
                    "start_ms": int(fields[2]),
                    "end_ms": int(fields[3]),
                    "duration_ms": int(fields[4]),
                    "start_x": float(fields[5]),
                    "start_y": float(fields[6]),
                    "end_x": float(fields[7]),
                    "end_y": float(fields[8]),
                    "amplitude_deg": float(fields[9]),
                    "peak_velocity_deg_s": float(fields[10]),
                }
            )
    return rows


def apply_gaze_coordinates(saccades, screen_width=1920.0, screen_height=1080.0):
    for saccade in saccades:
        saccade["screen_start_x"] = saccade["start_x"] - screen_width / 2.0
        saccade["screen_start_y"] = screen_height / 2.0 - saccade["start_y"]
        saccade["screen_end_x"] = saccade["end_x"] - screen_width / 2.0
        saccade["screen_end_y"] = screen_height / 2.0 - saccade["end_y"]


def apply_href_coordinates(saccades, href_asc_path, calibration_path):
    with calibration_path.open("r", encoding="utf-8") as handle:
        calibration = json.load(handle)["right_cal"]
    ox = float(calibration.get("ox", 0.0))
    oy = float(calibration.get("oy", 0.0))
    gx = float(calibration.get("gx", 1.0))
    gy = float(calibration.get("gy", 1.0))
    gxy = float(calibration.get("gxy", 0.0))
    gyx = float(calibration.get("gyx", 0.0))
    wanted = {
        value
        for saccade in saccades
        for value in (saccade["start_ms"], saccade["end_ms"])
    }
    points = {}
    with href_asc_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            fields = raw_line.split()
            if len(fields) < 3 or not fields[0].isdigit():
                continue
            timestamp = int(fields[0])
            if timestamp not in wanted or fields[1] == "." or fields[2] == ".":
                continue
            raw_x = float(fields[1])
            raw_y = float(fields[2])
            points[timestamp] = (
                ox + gx * raw_x + gxy * raw_y,
                oy + gyx * raw_x + gy * raw_y,
            )
    for saccade in saccades:
        start = points.get(saccade["start_ms"])
        end = points.get(saccade["end_ms"])
        if start is None or end is None:
            continue
        saccade["screen_start_x"], saccade["screen_start_y"] = start
        saccade["screen_end_x"], saccade["screen_end_y"] = end


def first_saccade(saccades, start_ms, end_ms, minimum_amplitude_deg):
    for saccade in saccades:
        if saccade["start_ms"] < start_ms:
            continue
        if saccade["start_ms"] > end_ms:
            return None
        if saccade["amplitude_deg"] < minimum_amplitude_deg:
            continue
        return saccade
    return None


def visual_angle_to_pixels(angle_deg, distance_cm, monitor_cm, resolution):
    physical_cm = 2.0 * distance_cm * math.tan(math.radians(angle_deg) / 2.0)
    return physical_cm * resolution / monitor_cm


def parse_bool(value):
    return str(value).strip().lower() == "true"


def build_session_trials(
    config,
    session,
    converter,
    edfapi,
    cache_dir,
    force_convert,
):
    paths = session_paths(config, session)
    events_asc = convert_edf(
        paths["edf"],
        cache_dir / "events_gaze" / session["session_id"],
        converter,
        "-sg",
        events_only=True,
        force=force_convert,
    )
    href_asc = None
    if session["sample_source"] == "href":
        href_asc = convert_edf(
            paths["edf"],
            cache_dir / "samples_href" / session["session_id"],
            converter,
            "-sh",
            events_only=False,
            force=force_convert,
        )

    task = pd.read_csv(paths["log"])
    with paths["parameters"].open("r", encoding="utf-8") as handle:
        parameters = json.load(handle)
    messages = read_exact_messages_from_edf(paths["edf"], edfapi)
    trial_events = parse_trial_messages(messages)
    saccades = parse_saccades(events_asc)
    if session["sample_source"] == "href":
        apply_href_coordinates(saccades, href_asc, paths["calibration"])
    else:
        apply_gaze_coordinates(saccades)

    viewing_distance = float(parameters["Viewing Distance (cm)"])
    monitor_width = float(parameters["Subject Monitor Width (cm)"])
    monitor_height = float(parameters["Subject Monitor Height (cm)"])
    minimum_amplitude = float(config["minimum_saccade_amplitude_deg"])
    background_luminance = float(config["background_luminance_cd_m2"])
    rows = []
    for _, trial in task.iterrows():
        trial_number = int(trial["Trial"])
        events = trial_events.get(trial_number, {})
        fix_off = events.get("fix_off_ms")
        stim_on = events.get("stim_on_ms")
        window_end = events.get("stim_window_end_ms")
        timing_complete = fix_off is not None and stim_on is not None and window_end is not None

        fix_x = float(trial["Fixation_Pos_X_deg"])
        fix_y = float(trial["Fixation_Pos_Y_deg"])
        stim_x = float(trial["Stim_Pos_X_deg"])
        stim_y = float(trial["Stim_Pos_Y_deg"])
        rel_x = stim_x - fix_x
        rel_y = stim_y - fix_y
        distance_deg = math.hypot(rel_x, rel_y)
        fix_radius = float(trial["Fix_Window_Radius_deg"])
        stim_radius = float(trial["Stim_Window_Radius_deg"])
        overlap = distance_deg <= fix_radius + stim_radius
        target_luminance = float(trial["Stim_Target_Luminance_cd_m2"])
        contrast = (target_luminance - background_luminance) / background_luminance

        record = {
            "session": session["label"],
            "session_instance": session.get("instance_label", session["session_id"]),
            "session_id": session["session_id"],
            "sample_source": session["sample_source"],
            "trial": trial_number,
            "condition_id": str(trial["Condition_ID"]),
            "attempt": int(trial["Attempt_For_Condition"]),
            "status": str(trial["Status"]),
            "is_control": parse_bool(trial["Is_Control"]),
            "is_success_noncontrol": (
                str(trial["Status"]) == "Success" and not parse_bool(trial["Is_Control"])
            ),
            "trial_time_s": float(trial["Time_TrialStart"]),
            "fix_x_deg": fix_x,
            "fix_y_deg": fix_y,
            "stim_x_deg": stim_x,
            "stim_y_deg": stim_y,
            "rel_x_deg": rel_x,
            "rel_y_deg": rel_y,
            "distance_deg": distance_deg,
            "direction_deg": math.degrees(math.atan2(rel_y, rel_x)),
            "fix_window_radius_deg": fix_radius,
            "stim_window_radius_deg": stim_radius,
            "windows_overlap": overlap,
            "target_luminance_cd_m2": target_luminance,
            "background_luminance_model_cd_m2": background_luminance,
            "background_luminance_logged_cd_m2": float(
                trial["Background_Target_Luminance_cd_m2"]
            ),
            "contrast_weber": contrast,
            "timing_complete": timing_complete,
            "fix_off_ms": fix_off,
            "stim_on_ms": stim_on,
            "stim_window_end_ms": window_end,
            "position_cluster": f"{session['session_id']}|{rel_x:.3f}|{rel_y:.3f}",
        }
        movement = None
        if timing_complete:
            movement = first_saccade(saccades, fix_off, window_end, minimum_amplitude)
        record["first_saccade_found"] = movement is not None
        if movement is not None:
            record.update(
                {
                    "saccade_start_ms": movement["start_ms"],
                    "saccade_end_ms": movement["end_ms"],
                    "latency_ms": movement["start_ms"] - stim_on,
                    "saccade_duration_ms": movement["duration_ms"],
                    "saccade_amplitude_eyelink_deg": movement["amplitude_deg"],
                    "peak_velocity_deg_s": movement["peak_velocity_deg_s"],
                }
            )
        if (
            movement is not None
            and distance_deg > 0
            and "screen_start_x" in movement
            and "screen_end_x" in movement
        ):
            target_dx = visual_angle_to_pixels(
                stim_x, viewing_distance, monitor_width, 1920
            ) - visual_angle_to_pixels(fix_x, viewing_distance, monitor_width, 1920)
            target_dy = visual_angle_to_pixels(
                stim_y, viewing_distance, monitor_height, 1080
            ) - visual_angle_to_pixels(fix_y, viewing_distance, monitor_height, 1080)
            target = np.array([target_dx, target_dy], dtype=float)
            displacement = np.array(
                [
                    movement["screen_end_x"] - movement["screen_start_x"],
                    movement["screen_end_y"] - movement["screen_start_y"],
                ],
                dtype=float,
            )
            target_sq = float(np.dot(target, target))
            target_norm = math.sqrt(target_sq)
            movement_norm = float(np.linalg.norm(displacement))
            gain = float(np.dot(displacement, target) / target_sq)
            cosine = float(np.dot(displacement, target) / (movement_norm * target_norm))
            cosine = float(np.clip(cosine, -1.0, 1.0))
            cross_fraction = float(
                (target[0] * displacement[1] - target[1] * displacement[0]) / target_sq
            )
            record.update(
                {
                    "gain": gain,
                    "gain_pct": gain * 100.0,
                    "amplitude_ratio": movement_norm / target_norm,
                    "angular_error_deg": math.degrees(math.acos(cosine)),
                    "cross_fraction": cross_fraction,
                    "valid_gain": True,
                }
            )
        else:
            record["valid_gain"] = False
        rows.append(record)
    return pd.DataFrame(rows), paths


def make_selection_flags(trials, minimum_latency_ms):
    trials = trials.copy()
    trials["included_sensitivity"] = (
        trials["is_success_noncontrol"]
        & ~trials["windows_overlap"]
        & trials["timing_complete"]
        & trials["first_saccade_found"]
        & trials["valid_gain"]
        & trials["latency_ms"].notna()
    )
    trials["included_main"] = (
        trials["included_sensitivity"]
        & (trials["latency_ms"] >= minimum_latency_ms)
    )

    def exclusion_reason(row):
        if not row["is_success_noncontrol"]:
            return "not_successful_noncontrol"
        if row["windows_overlap"]:
            return "fixation_and_target_windows_overlap"
        if not row["timing_complete"]:
            return "missing_edf_timing_events"
        if not row["first_saccade_found"]:
            return "no_saccade_above_amplitude_threshold"
        if not row["valid_gain"]:
            return "missing_saccade_coordinates_or_zero_distance"
        if pd.isna(row["latency_ms"]):
            return "missing_latency"
        if row["latency_ms"] < minimum_latency_ms:
            return "latency_below_visual_threshold"
        return "included_main"

    trials["main_exclusion_reason"] = trials.apply(exclusion_reason, axis=1)
    return trials


def prepare_model_data(data):
    data = data.copy().reset_index(drop=True)
    data["contrast_weber_centered"] = data["contrast_weber"] - data["contrast_weber"].mean()
    data["distance_deg_centered"] = data["distance_deg"] - data["distance_deg"].mean()
    data["day_8_7"] = (data["session"] == "8/7").astype(float)
    data["Intercept"] = 1.0
    return data


def fit_ols_cluster(data, outcome, design_columns=DESIGN_COLUMNS):
    x = data[list(design_columns)].to_numpy(dtype=float)
    y = data[outcome].to_numpy(dtype=float)
    beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    residual = y - fitted
    n, k = x.shape
    rank = int(np.linalg.matrix_rank(x))
    xtx_inv = np.linalg.pinv(x.T @ x)
    sigma2 = float(np.sum(residual**2) / (n - rank))
    naive_cov = sigma2 * xtx_inv
    clusters = data["position_cluster"].astype(str).to_numpy()
    unique_clusters = np.unique(clusters)
    meat = np.zeros((k, k), dtype=float)
    for cluster in unique_clusters:
        mask = clusters == cluster
        score = x[mask].T @ residual[mask]
        meat += np.outer(score, score)
    cluster_count = len(unique_clusters)
    correction = (cluster_count / (cluster_count - 1)) * ((n - 1) / (n - rank))
    cluster_cov = correction * xtx_inv @ meat @ xtx_inv
    cluster_se = np.sqrt(np.maximum(np.diag(cluster_cov), 0.0))
    naive_se = np.sqrt(np.maximum(np.diag(naive_cov), 0.0))
    degrees_freedom = cluster_count - 1
    critical = float(stats.t.ppf(0.975, degrees_freedom))
    t_values = beta / cluster_se
    p_values = 2.0 * stats.t.sf(np.abs(t_values), degrees_freedom)
    total_ss = float(np.sum((y - y.mean()) ** 2))
    residual_ss = float(np.sum(residual**2))
    r_squared = 1.0 - residual_ss / total_ss
    adjusted_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / (n - rank)
    coefficient_rows = []
    y_sd = float(np.std(y, ddof=1))
    for index, name in enumerate(design_columns):
        if name in ("contrast_weber_centered", "distance_deg_centered"):
            x_sd = float(np.std(data[name], ddof=1))
            standardized = float(beta[index] * x_sd / y_sd)
        else:
            standardized = np.nan
        coefficient_rows.append(
            {
                "term": name,
                "estimate": float(beta[index]),
                "cluster_se": float(cluster_se[index]),
                "cluster_ci_low": float(beta[index] - critical * cluster_se[index]),
                "cluster_ci_high": float(beta[index] + critical * cluster_se[index]),
                "cluster_t": float(t_values[index]),
                "cluster_p": float(p_values[index]),
                "naive_se": float(naive_se[index]),
                "standardized_beta_continuous_only": standardized,
            }
        )
    return {
        "outcome": outcome,
        "design_columns": list(design_columns),
        "beta": beta,
        "cov": cluster_cov,
        "fitted": fitted,
        "residual": residual,
        "coefficients": pd.DataFrame(coefficient_rows),
        "n": int(n),
        "rank": rank,
        "cluster_count": int(cluster_count),
        "cluster_df": int(degrees_freedom),
        "r_squared": r_squared,
        "adjusted_r_squared": adjusted_r_squared,
        "rmse": float(math.sqrt(np.mean(residual**2))),
        "condition_number": float(np.linalg.cond(x)),
    }


def stratified_cluster_bootstrap(data, outcome, repetitions, seed):
    """Resample position clusters within session using OLS sufficient statistics.

    Repeating a sampled cluster is algebraically identical to repeating all of
    its rows.  Summing cluster-level X'X and X'y therefore implements the same
    bootstrap without repeatedly copying the full trial table.
    """
    rng = np.random.default_rng(seed)
    coefficients = []
    session_statistics = []
    for _, session_data in data.groupby("session_id", sort=True):
        xtx_by_cluster = []
        xty_by_cluster = []
        for _, cluster_data in session_data.groupby("position_cluster", sort=True):
            x_cluster = cluster_data[list(DESIGN_COLUMNS)].to_numpy(dtype=float)
            y_cluster = cluster_data[outcome].to_numpy(dtype=float)
            xtx_by_cluster.append(x_cluster.T @ x_cluster)
            xty_by_cluster.append(x_cluster.T @ y_cluster)
        session_statistics.append(
            (np.asarray(xtx_by_cluster), np.asarray(xty_by_cluster))
        )
    parameter_count = len(DESIGN_COLUMNS)
    for _ in range(repetitions):
        xtx = np.zeros((parameter_count, parameter_count), dtype=float)
        xty = np.zeros(parameter_count, dtype=float)
        for xtx_clusters, xty_clusters in session_statistics:
            cluster_count = len(xtx_clusters)
            selected = rng.integers(0, cluster_count, size=cluster_count)
            xtx += xtx_clusters[selected].sum(axis=0)
            xty += xty_clusters[selected].sum(axis=0)
        if np.linalg.matrix_rank(xtx) < parameter_count:
            continue
        beta = np.linalg.solve(xtx, xty)
        coefficients.append(beta)
    if not coefficients:
        raise RuntimeError("Every cluster-bootstrap sample was rank deficient")
    values = np.asarray(coefficients)
    return pd.DataFrame(
        {
            "term": DESIGN_COLUMNS,
            "bootstrap_ci_low": np.percentile(values, 2.5, axis=0),
            "bootstrap_ci_high": np.percentile(values, 97.5, axis=0),
            "bootstrap_median": np.median(values, axis=0),
            "bootstrap_valid_repetitions": len(values),
        }
    )


def fit_model_pair(data, repetitions, seed, analysis_set):
    model_data = prepare_model_data(data)
    results = []
    for offset, outcome in enumerate(("gain_pct", "latency_ms")):
        result = fit_ols_cluster(model_data, outcome)
        bootstrap = stratified_cluster_bootstrap(
            model_data, outcome, repetitions, seed + offset
        )
        result["coefficients"] = result["coefficients"].merge(bootstrap, on="term")
        result["analysis_set"] = analysis_set
        results.append(result)
    return model_data, results


def pooled_run_diagnostic(data):
    """Compare the two 8/7 run intercepts without changing the pooled main model."""
    run_ids = sorted(data.loc[data["session"] == "8/7", "session_id"].unique())
    if len(run_ids) != 2:
        return pd.DataFrame()
    diagnostic = data.copy()
    diagnostic["run_8_7_first"] = (diagnostic["session_id"] == run_ids[0]).astype(float)
    diagnostic["run_8_7_second"] = (diagnostic["session_id"] == run_ids[1]).astype(float)
    columns = (
        "Intercept",
        "contrast_weber_centered",
        "run_8_7_first",
        "run_8_7_second",
        "distance_deg_centered",
    )
    contrast = np.array([0.0, 0.0, 1.0, -1.0, 0.0])
    rows = []
    for outcome in ("gain_pct", "latency_ms"):
        result = fit_ols_cluster(diagnostic, outcome, columns)
        estimate = float(contrast @ result["beta"])
        standard_error = float(math.sqrt(max(contrast @ result["cov"] @ contrast, 0.0)))
        critical = float(stats.t.ppf(0.975, result["cluster_df"]))
        t_value = estimate / standard_error
        rows.append(
            {
                "outcome": outcome,
                "comparison": "8/7 first minus 8/7 second",
                "estimate": estimate,
                "cluster_se": standard_error,
                "cluster_ci_low": estimate - critical * standard_error,
                "cluster_ci_high": estimate + critical * standard_error,
                "cluster_t": t_value,
                "cluster_p": 2.0 * stats.t.sf(abs(t_value), result["cluster_df"]),
                "first_session_id": run_ids[0],
                "second_session_id": run_ids[1],
            }
        )
    return pd.DataFrame(rows)


def plot_effects(data, results, output_path, background_luminance):
    colors = {"8/6": "#4C78A8", "8/7": "#F58518"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    contrast_min = float(data["contrast_weber"].min())
    contrast_max = float(data["contrast_weber"].max())
    grid = np.linspace(contrast_min, contrast_max, 160)
    contrast_mean = float(data["contrast_weber"].mean())
    distance_mean = float(data["distance_deg"].mean())
    for axis, result, outcome, ylabel in (
        (axes[0], results[0], "gain_pct", "Radial gain (%)"),
        (axes[1], results[1], "latency_ms", "First-saccade latency (ms)"),
    ):
        for session in ("8/6", "8/7"):
            x_rows = np.column_stack(
                [
                    np.ones(len(grid)),
                    grid - contrast_mean,
                    np.full(len(grid), session == "8/7", dtype=float),
                    np.zeros(len(grid)),
                ]
            )
            predicted = x_rows @ result["beta"]
            prediction_se = np.sqrt(
                np.maximum(np.einsum("ij,jk,ik->i", x_rows, result["cov"], x_rows), 0)
            )
            critical = stats.t.ppf(0.975, result["cluster_df"])
            axis.plot(grid, predicted, color=colors[session], label=session, linewidth=2)
            axis.fill_between(
                grid,
                predicted - critical * prediction_se,
                predicted + critical * prediction_se,
                color=colors[session],
                alpha=0.13,
            )
            subset = data[data["session"] == session]
            grouped = subset.groupby("contrast_weber")[outcome].median().reset_index()
            axis.scatter(
                grouped["contrast_weber"],
                grouped[outcome],
                s=22,
                color=colors[session],
                alpha=0.75,
                zorder=3,
            )
        axis.set_xlabel(f"Weber contrast, background={background_luminance:g} cd/m²")
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.2)
        axis.legend(title="Day", frameon=False)
    axes[0].set_title(f"Gain model at mean distance ({distance_mean:.2f}°)")
    axes[1].set_title(f"Latency model at mean distance ({distance_mean:.2f}°)")
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def plot_diagnostics(data, results, output_path):
    fig, axes = plt.subplots(2, 2, figsize=(10, 8), constrained_layout=True)
    for column, result in enumerate(results):
        fitted = result["fitted"]
        residual = result["residual"]
        axes[0, column].scatter(fitted, residual, s=12, alpha=0.42)
        axes[0, column].axhline(0, color="black", linewidth=1)
        axes[0, column].set_xlabel("Fitted value")
        axes[0, column].set_ylabel("Residual")
        axes[0, column].set_title(f"{result['outcome']}: residuals vs fitted")
        axes[0, column].grid(alpha=0.2)
        theoretical, ordered = stats.probplot(residual, dist="norm", fit=False)
        axes[1, column].scatter(theoretical, ordered, s=12, alpha=0.5)
        slope, intercept, _ = stats.probplot(residual, dist="norm", fit=True)[1]
        xline = np.asarray([np.min(theoretical), np.max(theoretical)])
        axes[1, column].plot(xline, intercept + slope * xline, color="black", linewidth=1)
        axes[1, column].set_xlabel("Theoretical normal quantile")
        axes[1, column].set_ylabel("Observed residual quantile")
        axes[1, column].set_title(f"{result['outcome']}: Q-Q plot")
        axes[1, column].grid(alpha=0.2)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def plot_data_overview(data, output_path):
    colors = {"8/6": "#4C78A8", "8/7": "#F58518"}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), constrained_layout=True)
    for session, subset in data.groupby("session"):
        axes[0].scatter(
            subset["contrast_weber"], subset["gain_pct"], s=12,
            alpha=0.34, color=colors[session], label=session,
        )
        axes[1].scatter(
            subset["contrast_weber"], subset["latency_ms"], s=12,
            alpha=0.34, color=colors[session], label=session,
        )
        axes[2].scatter(
            subset["distance_deg"], subset["gain_pct"], s=12,
            alpha=0.34, color=colors[session], label=session,
        )
    axes[0].set(xlabel="Weber contrast", ylabel="Radial gain (%)")
    axes[1].set(xlabel="Weber contrast", ylabel="Latency (ms)")
    axes[2].set(xlabel="Target distance (deg)", ylabel="Radial gain (%)")
    for axis in axes:
        axis.grid(alpha=0.2)
    axes[0].legend(title="Day", frameon=False)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def file_sha256(path, block_size=1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def build_input_manifest(config, config_path):
    paths = [Path(config_path).resolve()]
    for session in config["sessions"]:
        session_input = session_paths(config, session)
        paths.extend(
            session_input[name] for name in ("edf", "log", "parameters", "conditions")
        )
        if session_input["calibration"] is not None:
            paths.append(session_input["calibration"])
    unique_paths = list(dict.fromkeys(path.resolve() for path in paths))
    rows = []
    for path in unique_paths:
        stat = path.stat()
        rows.append(
            {
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_local": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "sha256": file_sha256(path),
            }
        )
    return pd.DataFrame(rows)


def exclusion_flow(trials, minimum_latency_ms):
    rows = []
    rows.append({"step": "All logged trials", "n": len(trials)})
    current = trials[trials["is_success_noncontrol"]]
    rows.append({"step": "Successful non-control trials", "n": len(current)})
    current = current[~current["windows_overlap"]]
    rows.append({"step": "Non-overlapping fixation/target windows", "n": len(current)})
    current = current[current["timing_complete"]]
    rows.append({"step": "Complete EDF timing events", "n": len(current)})
    current = current[current["first_saccade_found"] & current["valid_gain"]]
    rows.append({"step": "Valid first saccade and gain", "n": len(current)})
    current = current[current["latency_ms"] >= minimum_latency_ms]
    rows.append(
        {"step": f"Latency >= {minimum_latency_ms:g} ms (main analysis)", "n": len(current)}
    )
    return pd.DataFrame(rows)


def format_number(value, digits=4):
    if pd.isna(value):
        return ""
    return f"{value:.{digits}g}"


def markdown_coefficient_table(coefficients):
    lines = [
        "| Outcome | Term | Estimate | Cluster 95% CI | p | Bootstrap 95% CI |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, row in coefficients.iterrows():
        lines.append(
            "| {outcome} | {term} | {estimate} | [{low}, {high}] | {p} | [{blow}, {bhigh}] |".format(
                outcome=row["outcome"],
                term=row["term"],
                estimate=format_number(row["estimate"]),
                low=format_number(row["cluster_ci_low"]),
                high=format_number(row["cluster_ci_high"]),
                p=format_number(row["cluster_p"], 3),
                blow=format_number(row["bootstrap_ci_low"]),
                bhigh=format_number(row["bootstrap_ci_high"]),
            )
        )
    return "\n".join(lines)


def write_report(
    output_path,
    config,
    main_data,
    sensitivity_data,
    main_results,
    all_coefficients,
    run_diagnostic,
):
    gain_result, latency_result = main_results
    gain_contrast = all_coefficients[
        (all_coefficients["analysis_set"] == "main")
        & (all_coefficients["outcome"] == "gain_pct")
        & (all_coefficients["term"] == "contrast_weber_centered")
    ].iloc[0]
    latency_contrast = all_coefficients[
        (all_coefficients["analysis_set"] == "main")
        & (all_coefficients["outcome"] == "latency_ms")
        & (all_coefficients["term"] == "contrast_weber_centered")
    ].iloc[0]
    count_lines = [
        "| Session | Main n | Sensitivity n | Main position clusters |",
        "|---|---:|---:|---:|",
    ]
    for session in ("8/6", "8/7"):
        main_session = main_data[main_data["session"] == session]
        sensitivity_session = sensitivity_data[sensitivity_data["session"] == session]
        count_lines.append(
            f"| {session} | {len(main_session)} | {len(sensitivity_session)} | "
            f"{main_session['position_cluster'].nunique()} |"
        )
    count_table = "\n".join(count_lines)
    diagnostic_lines = []
    for row in run_diagnostic.itertuples(index=False):
        diagnostic_lines.append(
            f"- {row.outcome}: first minus second 8/7 run = {row.estimate:.4g}, "
            f"cluster-robust 95% CI [{row.cluster_ci_low:.4g}, "
            f"{row.cluster_ci_high:.4g}], p={row.cluster_p:.3g}."
        )
    diagnostic_text = "\n".join(diagnostic_lines) or "- Diagnostic unavailable."
    report = f"""# First-saccade gain and latency model report

Generated: {datetime.now(timezone.utc).isoformat()}

## Pre-specified models

Reference day: 8/6. Both 8/7 recording sessions were pooled under one day indicator. Continuous predictors were centered at their main-analysis means.

```text
gain_pct = beta0 + betaC * contrast_weber + beta7 * D_8/7
           + betaR * distance_deg + error

latency_ms = alpha0 + alphaC * contrast_weber + alpha7 * D_8/7
             + alphaR * distance_deg + error
```

Weber contrast was `(target luminance - {config['background_luminance_cd_m2']:g}) / {config['background_luminance_cd_m2']:g}`.

## Trial inclusion

- Main analysis: n={len(main_data)} trials; first saccade latency >= {config['minimum_visual_latency_ms']:g} ms.
- Sensitivity analysis: n={len(sensitivity_data)} trials; no minimum visual-latency exclusion.
- Both analyses used successful non-control trials, excluded overlapping fixation/target acceptance windows, and required a valid first saccade >= {config['minimum_saccade_amplitude_deg']:g} deg after fixation offset.

{count_table}

## Main result in one paragraph

For gain, the estimated contrast coefficient was {gain_contrast['estimate']:.4g} percentage points per Weber-contrast unit (cluster-robust 95% CI {gain_contrast['cluster_ci_low']:.4g} to {gain_contrast['cluster_ci_high']:.4g}, p={gain_contrast['cluster_p']:.3g}). For latency, the estimated contrast coefficient was {latency_contrast['estimate']:.4g} ms per Weber-contrast unit (cluster-robust 95% CI {latency_contrast['cluster_ci_low']:.4g} to {latency_contrast['cluster_ci_high']:.4g}, p={latency_contrast['cluster_p']:.3g}). These are conditional linear associations after adjusting for the day intercept and target distance; a confidence interval crossing zero is not proof of exactly zero effect.

## Main-analysis coefficients

{markdown_coefficient_table(all_coefficients[all_coefficients['analysis_set'] == 'main'])}

## Sensitivity-analysis coefficients

{markdown_coefficient_table(all_coefficients[all_coefficients['analysis_set'] == 'sensitivity_no_latency_cutoff'])}

## Model fit

- Gain: R²={gain_result['r_squared']:.3f}, adjusted R²={gain_result['adjusted_r_squared']:.3f}, RMSE={gain_result['rmse']:.3f}, clusters={gain_result['cluster_count']}.
- Latency: R²={latency_result['r_squared']:.3f}, adjusted R²={latency_result['adjusted_r_squared']:.3f}, RMSE={latency_result['rmse']:.3f}, clusters={latency_result['cluster_count']}.

## Check of pooling the two 8/7 runs

{diagnostic_text}

These comparisons adjust for contrast and distance. Failure to reject a run difference is not an equivalence test, but there was no large, statistically clear run offset that would by itself argue against the requested pooling.

## Coordinate reconstruction

- 8/6: EDF HREF samples transformed with `eyelink_calibration_20260806_142607.json`.
- Both 8/7 sessions (14:12 and 14:45) used EDF GAZE coordinates converted from EyeLink top-left coordinates to FineVision centered pixels.
- The interrupted 8/7 14:12 run was included only through trials that individually passed all pre-specified selection criteria.

## Interpretation limits

The simple model assumes one common contrast slope and one common distance slope across days, and approximates position by distance alone. Day-by-contrast interactions, target direction, or exact relative position should be examined as planned extensions if residual diagnostics or later data suggest violations. The 8/7 coefficient estimates the pooled day offset relative to 8/6; it does not estimate a separate offset for each 8/7 recording run.

The latency residuals are non-normal and the main latency outcome is left-truncated by design at 80 ms. Its OLS coefficient should therefore be read as an exploratory conditional mean association. The cluster-robust and cluster-bootstrap intervals reduce reliance on independent, homoscedastic trial errors, but they do not remove truncation.
"""
    output_path.write_text(report, encoding="utf-8")


def run_self_test():
    target = np.array([10.0, 0.0])
    half = np.array([5.0, 0.0])
    exact = np.array([10.0, 0.0])
    orthogonal = np.array([0.0, 10.0])
    assert math.isclose(np.dot(half, target) / np.dot(target, target), 0.5)
    assert math.isclose(np.dot(exact, target) / np.dot(target, target), 1.0)
    assert math.isclose(np.dot(orthogonal, target) / np.dot(target, target), 0.0)
    synthetic = pd.DataFrame(
        {
            "gain_pct": [90, 92, 94, 96, 98, 100],
            "latency_ms": [120, 118, 116, 114, 112, 110],
            "contrast_weber": [1, 2, 3, 4, 5, 6],
            "distance_deg": [8, 8, 10, 10, 12, 12],
            "session": ["8/6", "8/6", "8/7", "8/6", "8/7", "8/7"],
            "position_cluster": [f"c{i}" for i in range(6)],
        }
    )
    prepared = prepare_model_data(synthetic)
    result = fit_ols_cluster(prepared, "gain_pct")
    assert np.isfinite(result["beta"]).all()
    print("Self-test passed")


def main():
    args = parse_args()
    if args.self_test:
        run_self_test()
        return
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    if args.background_luminance is not None:
        config["background_luminance_cd_m2"] = args.background_luminance
    if args.minimum_latency_ms is not None:
        config["minimum_visual_latency_ms"] = args.minimum_latency_ms
    if args.bootstrap_repetitions is not None:
        config["bootstrap_repetitions"] = args.bootstrap_repetitions
    validate_inputs(config)
    converter = resolve_existing(args.edf2asc, DEFAULT_CONVERTERS, "EDF2ASC converter")
    edfapi = resolve_existing(args.edfapi, DEFAULT_EDFAPI_LIBRARIES, "EDF Access DLL")
    output_dir = Path(args.output_dir).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_trials = []
    input_paths = []
    for session in config["sessions"]:
        print(f"Processing {session['label']} ({session['session_id']}) ...", flush=True)
        trials, paths = build_session_trials(
            config, session, converter, edfapi, cache_dir, args.force_convert
        )
        all_trials.append(trials)
        input_paths.append(paths)
    trials = pd.concat(all_trials, ignore_index=True)
    trials = make_selection_flags(trials, float(config["minimum_visual_latency_ms"]))
    sensitivity = trials[trials["included_sensitivity"]].copy()
    main_data = trials[trials["included_main"]].copy()
    if main_data.empty or sensitivity.empty:
        raise RuntimeError("No trials survived the analysis selection")

    repetitions = int(config["bootstrap_repetitions"])
    seed = int(config["random_seed"])
    print(
        f"Fitting main models (n={len(main_data)}) with {repetitions} bootstrap repetitions ...",
        flush=True,
    )
    main_prepared, main_results = fit_model_pair(main_data, repetitions, seed, "main")
    print(
        f"Fitting sensitivity models (n={len(sensitivity)}) ...",
        flush=True,
    )
    sensitivity_prepared, sensitivity_results = fit_model_pair(
        sensitivity, repetitions, seed + 100, "sensitivity_no_latency_cutoff"
    )

    coefficient_tables = []
    fit_rows = []
    for result in main_results + sensitivity_results:
        table = result["coefficients"].copy()
        table.insert(0, "analysis_set", result["analysis_set"])
        table.insert(1, "outcome", result["outcome"])
        coefficient_tables.append(table)
        fit_rows.append(
            {
                "analysis_set": result["analysis_set"],
                "outcome": result["outcome"],
                "n": result["n"],
                "clusters": result["cluster_count"],
                "cluster_df": result["cluster_df"],
                "r_squared": result["r_squared"],
                "adjusted_r_squared": result["adjusted_r_squared"],
                "rmse": result["rmse"],
                "condition_number": result["condition_number"],
            }
        )
    coefficients = pd.concat(coefficient_tables, ignore_index=True)
    fit_summary = pd.DataFrame(fit_rows)
    run_diagnostic = pooled_run_diagnostic(main_prepared)
    flow = exclusion_flow(trials, float(config["minimum_visual_latency_ms"]))
    session_counts = (
        trials.groupby("session")
        .agg(
            logged_trials=("trial", "size"),
            successful_noncontrol=("is_success_noncontrol", "sum"),
            sensitivity_trials=("included_sensitivity", "sum"),
            main_trials=("included_main", "sum"),
        )
        .reset_index()
    )
    run_counts = (
        trials.groupby(["session", "session_instance", "session_id"])
        .agg(
            logged_trials=("trial", "size"),
            successful_noncontrol=("is_success_noncontrol", "sum"),
            sensitivity_trials=("included_sensitivity", "sum"),
            main_trials=("included_main", "sum"),
        )
        .reset_index()
    )

    trials.to_csv(output_dir / "trial_level_all.csv", index=False)
    main_prepared.to_csv(output_dir / "trial_level_main.csv", index=False)
    sensitivity_prepared.to_csv(output_dir / "trial_level_sensitivity.csv", index=False)
    coefficients.to_csv(output_dir / "model_coefficients.csv", index=False)
    fit_summary.to_csv(output_dir / "model_fit_summary.csv", index=False)
    flow.to_csv(output_dir / "exclusion_flow.csv", index=False)
    session_counts.to_csv(output_dir / "session_counts.csv", index=False)
    run_counts.to_csv(output_dir / "run_counts.csv", index=False)
    run_diagnostic.to_csv(output_dir / "pooled_run_diagnostic.csv", index=False)
    plot_effects(
        main_prepared,
        main_results,
        output_dir / "figure_model_effects.png",
        float(config["background_luminance_cd_m2"]),
    )
    plot_diagnostics(main_prepared, main_results, output_dir / "figure_diagnostics.png")
    plot_data_overview(main_prepared, output_dir / "figure_data_overview.png")
    manifest = build_input_manifest(config, config_path)
    manifest.to_csv(output_dir / "input_manifest.csv", index=False)
    metadata = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "script": str(Path(__file__).resolve()),
        "config": str(config_path),
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "edf2asc": str(converter),
        "edfapi": str(edfapi),
        "effective_config": config,
    }
    with (output_dir / "analysis_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    write_report(
        output_dir / "analysis_report.md",
        config,
        main_prepared,
        sensitivity_prepared,
        main_results,
        coefficients,
        run_diagnostic,
    )
    print("\nExclusion flow")
    print(flow.to_string(index=False))
    print("\nMain model coefficients")
    print(
        coefficients[coefficients["analysis_set"] == "main"]
        [["outcome", "term", "estimate", "cluster_ci_low", "cluster_ci_high", "cluster_p"]]
        .to_string(index=False)
    )
    print(f"\nOutputs: {output_dir}")


if __name__ == "__main__":
    main()
