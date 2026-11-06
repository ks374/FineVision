"""Offline validation plotting and explicit calibration snapshot persistence."""
import json
import os
from pathlib import Path
import numpy as np


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def predict(cal, raw):
    raw = np.asarray(raw, dtype=float)
    return np.column_stack((cal["ox"] + cal["gx"] * raw[:, 0] + cal.get("gxy", 0) * raw[:, 1],
                            cal["oy"] + cal.get("gyx", 0) * raw[:, 0] + cal["gy"] * raw[:, 1]))


def validation_offsets(data, calibration):
    data = np.asarray(data, dtype=float)
    if not np.all(np.isfinite(data[:, [0, 1, 4, 5]])):
        raise ValueError("Validation requires valid right-eye samples at every target.")
    return predict(calibration, data[:, 4:6]) - data[:, :2]


def require_fit_data(data):
    raw = np.asarray(data, dtype=float)[:, 4:6]
    if not np.all(np.isfinite(raw)) or np.linalg.matrix_rank(np.column_stack((np.ones(len(raw)), raw))) < 3:
        raise ValueError("Right-eye calibration samples are missing or degenerate; active calibration was not replaced.")


def save_mapping(active_path, log_dir, left, right, metadata):
    path = Path(active_path)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    updated = dict(previous, default_left_cal=left, default_right_cal=right, calibration_metadata=metadata)
    # Preserve the old mapping and write the session snapshot before activating.
    write_json(Path(log_dir) / "mapping_before.json", previous)
    write_json(Path(log_dir) / "eyelink_raw_pupil_setting.json", updated)
    write_json(path, updated)


def show_validation(data, current_right, log_dir):
    """Return True only for an explicit Update click; closing means no update."""
    import matplotlib
    matplotlib.use("TkAgg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    offsets = validation_offsets(data, current_right)
    distances = np.linalg.norm(offsets, axis=1)
    write_json(Path(log_dir) / "validation_offsets.json", dict(
        calibration_used=current_right, offsets_right_up_px=offsets.tolist(),
        targets_px=np.asarray(data)[:, :2].tolist(),
        mean_distance_px=float(distances.mean()), median_distance_px=float(np.median(distances)),
        max_distance_px=float(distances.max())))
    fig, ax = plt.subplots(figsize=(8, 7))
    fig.subplots_adjust(bottom=.23)
    ax.axhline(0, color=".8"); ax.axvline(0, color=".8")
    ax.scatter([0], [0], marker="+", s=130, color="black", label="Each target aligned to (0,0)")
    ax.scatter(offsets[:, 0], offsets[:, 1], color="steelblue")
    for i, (x, y) in enumerate(offsets, 1):
        ax.annotate(str(i), (x, y), xytext=(6, 6), textcoords="offset points")
    limit = max(20., float(np.max(np.abs(offsets))) * 1.25)
    ax.set(xlim=(-limit, limit), ylim=(-limit, limit), aspect="equal",
           xlabel="Gaze minus target X (px; right +)", ylabel="Gaze minus target Y (px; up +)",
           title=f"Validation BEFORE update: {len(offsets)} points\nMedian radial offset {np.median(distances):.1f} px")
    ax.legend(fontsize=9)
    fig.text(.5, .16, "Update refits RAW mapping on this collection; run a NEW validation to evaluate it.", ha="center", fontsize=9)
    # Always retain the pre-update result, including when Update is selected.
    fig.savefig(Path(log_dir) / "validation_before_update.png", dpi=180)
    selected = {"update": False}
    update = Button(fig.add_axes([.20, .05, .25, .06]), "Update / 更新")
    keep = Button(fig.add_axes([.55, .05, .25, .06]), "Do not update / 不更新")
    def choose(value):
        selected["update"] = value
        plt.close(fig)
    update.on_clicked(lambda event: choose(True))
    keep.on_clicked(lambda event: choose(False))
    plt.show(block=True)
    return selected["update"]
