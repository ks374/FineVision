"""FineVision custom calibration shared by QY and EyeLink entry scripts."""

import json
import math
import os
import time
import traceback
from datetime import datetime

from psychopy import core, visual

from CalibrationManager import CalibrationManager
from DisplayCalibration import (
    load_calibrated_gray_level,
    rgb255_to_psychopy,
)
from FineVision_Notebook import FineVision_Notebook
from FineVision_Util import ArduinoController
from Json_manager import update_json
from eyetracker import create_tracker_runtime


MONITOR_ID_SUBJECT = 1
MONITOR_ID_CONTROL = 0
SCREEN_SIZE = (1920, 1080)


DEFAULT_PARAMS = {
    "Subject ID": "Monkey_H18",
    "Calibration Horizontal Extent (deg)": 9.0,
    "Calibration Vertical Extent (deg)": 5.0,
    "Fixation Point Radius (deg)": 0.2,
    "Fix Window Radius (deg)": 5.5,
    "Fixation Duration (ms)": 500,
    "Maximum Wait per Point (s)": 5.0,
    "ITI (s)": 3.0,
    "Reward Duration (ms)": 300,
    "Background Gray Level (0-182)": 5,
    "Viewing Distance (cm)": 58.0,
    "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Subject Screen Index": MONITOR_ID_SUBJECT,
    "Control Screen Index": MONITOR_ID_CONTROL,
    "Full Screen": False,
}


CALIBRATION_PARAMETER_GROUPS = {
    "Session / 会话": [
        "Subject ID",
        "Subject Screen Index",
        "Control Screen Index",
        "Full Screen",
    ],
    "Calibration / 校准": [
        "Calibration Horizontal Extent (deg)",
        "Calibration Vertical Extent (deg)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
    ],
    "Timing & Reward / 时间与奖励": [
        "Fixation Duration (ms)",
        "Maximum Wait per Point (s)",
        "ITI (s)",
        "Reward Duration (ms)",
    ],
    "Display / 屏幕": [
        "Background Gray Level (0-182)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
    ],
}


def visual_angle_to_pixels(
    angle_deg, viewing_distance_cm, monitor_size_cm, resolution_pixels
):
    """Use the same degree-to-pixel definition as the saccade tasks."""
    size_cm = 2.0 * float(viewing_distance_cm) * math.tan(
        math.radians(float(angle_deg)) / 2.0
    )
    return size_cm * float(resolution_pixels) / float(monitor_size_cm)


def pixels_to_visual_angle(
    pixels, viewing_distance_cm, monitor_size_cm, resolution_pixels
):
    size_cm = float(pixels) * float(monitor_size_cm) / float(resolution_pixels)
    return math.degrees(
        2.0 * math.atan(size_cm / (2.0 * float(viewing_distance_cm)))
    )


def _build_calibration_target_specs(
    params,
    screen_size,
    *,
    add_quadrant_points=False,
    random_seed=0,
):
    distance = float(params["Viewing Distance (cm)"])
    monitor_width = float(params["Subject Monitor Width (cm)"])
    monitor_height = float(params["Subject Monitor Height (cm)"])
    x_extent_deg = float(params["Calibration Horizontal Extent (deg)"])
    y_extent_deg = float(params["Calibration Vertical Extent (deg)"])
    x_extent_px = visual_angle_to_pixels(
        x_extent_deg, distance, monitor_width, screen_size[0]
    )
    y_extent_px = visual_angle_to_pixels(
        y_extent_deg, distance, monitor_height, screen_size[1]
    )
    base_degrees = [
        (0.0, 0.0),
        (-x_extent_deg, y_extent_deg),
        (0.0, y_extent_deg),
        (x_extent_deg, y_extent_deg),
        (-x_extent_deg, 0.0),
        (x_extent_deg, 0.0),
        (-x_extent_deg, -y_extent_deg),
        (0.0, -y_extent_deg),
        (x_extent_deg, -y_extent_deg),
    ]
    base_pixels = [
        (0.0, 0.0),
        (-x_extent_px, y_extent_px),
        (0.0, y_extent_px),
        (x_extent_px, y_extent_px),
        (-x_extent_px, 0.0),
        (x_extent_px, 0.0),
        (-x_extent_px, -y_extent_px),
        (0.0, -y_extent_px),
        (x_extent_px, -y_extent_px),
    ]
    specs = [
        {
            "target": target_px,
            "target_deg": target_deg,
            "region": "base_9",
        }
        for target_px, target_deg in zip(base_pixels, base_degrees)
    ]

    if add_quadrant_points:
        for target_x, target_y in CalibrationManager._generate_quadrant_targets(
            screen_size, random_seed
        ):
            specs.append({
                "target": (float(target_x), float(target_y)),
                "target_deg": (
                    pixels_to_visual_angle(
                        target_x, distance, monitor_width, screen_size[0]
                    ),
                    pixels_to_visual_angle(
                        target_y, distance, monitor_height, screen_size[1]
                    ),
                ),
                "region": "quadrant_4_extra",
            })
    return specs


def _calibration_parameter_summary(params):
    _validate_calibration_params(params)
    gray = load_calibrated_gray_level(
        params["Background Gray Level (0-182)"]
    )
    x_px = visual_angle_to_pixels(
        params["Calibration Horizontal Extent (deg)"],
        params["Viewing Distance (cm)"],
        params["Subject Monitor Width (cm)"],
        SCREEN_SIZE[0],
    )
    y_px = visual_angle_to_pixels(
        params["Calibration Vertical Extent (deg)"],
        params["Viewing Distance (cm)"],
        params["Subject Monitor Height (cm)"],
        SCREEN_SIZE[1],
    )
    return (
        f"9-point extent: ±{x_px:.1f} px horizontal, ±{y_px:.1f} px vertical\n"
        f"Background: level {gray['level']}, RGB {gray['rgb_255']}, "
        f"{gray['luminance_cd_m2']:.3f} cd/m²"
    )


def _validate_calibration_params(params):
    positive_fields = (
        "Calibration Horizontal Extent (deg)",
        "Calibration Vertical Extent (deg)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
        "Maximum Wait per Point (s)",
    )
    for field in positive_fields:
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be positive.")
    if int(params["Fixation Duration (ms)"]) < 100:
        raise ValueError("Fixation Duration must be at least 100 ms.")
    if float(params["ITI (s)"]) < 0:
        raise ValueError("ITI cannot be negative.")
    if int(params["Reward Duration (ms)"]) < 0:
        raise ValueError("Reward Duration cannot be negative.")
    if int(params["Subject Screen Index"]) < 0:
        raise ValueError("Subject Screen Index cannot be negative.")
    if int(params["Control Screen Index"]) < 0:
        raise ValueError("Control Screen Index cannot be negative.")
    load_calibrated_gray_level(params["Background Gray Level (0-182)"])

    target_specs = _build_calibration_target_specs(params, SCREEN_SIZE)
    point_radius_px = visual_angle_to_pixels(
        params["Fixation Point Radius (deg)"],
        params["Viewing Distance (cm)"],
        params["Subject Monitor Width (cm)"],
        SCREEN_SIZE[0],
    )
    half_width = SCREEN_SIZE[0] / 2.0
    half_height = SCREEN_SIZE[1] / 2.0
    for spec in target_specs:
        x, y = spec["target"]
        if abs(x) + point_radius_px >= half_width:
            raise ValueError("Horizontal calibration extent exceeds the screen.")
        if abs(y) + point_radius_px >= half_height:
            raise ValueError("Vertical calibration extent exceeds the screen.")
    return None


def _calibration_paths(tracker_mode, timestamp):
    mode = str(tracker_mode).lower()
    sample_source = "qy"
    if mode == "eyelink":
        settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "eyelink_setting.json",
        )
        with open(settings_path, "r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        default_path = settings.get(
            "calibration_file", "eyelink_default_setting.json"
        )
        sample_source = str(settings.get("sample_source", "href")).lower()
    else:
        default_path = "default_setting.json"
    task_path = f"{mode}_calibration_{timestamp}.json"
    return default_path, task_path, sample_source


def _load_defaults(path, tracker_mode):
    if str(tracker_mode).lower() == "eyelink":
        fallback_left = {"ox": 0.0, "oy": 0.0, "gx": 1.0, "gy": 1.0}
        fallback_right = fallback_left.copy()
    else:
        fallback_left = {
            "ox": -865.6,
            "oy": -301.0,
            "gx": 2023.224,
            "gy": 1287.796,
        }
        fallback_right = {
            "ox": -1008.7,
            "oy": 70.4,
            "gx": 2203.769,
            "gy": 1439.845,
        }

    if not os.path.exists(path):
        settings = {
            "default_left_cal": fallback_left,
            "default_right_cal": fallback_right,
        }
        with open(path, "w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=4)
        return fallback_left, fallback_right

    with open(path, "r", encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    return (
        settings.get("default_left_cal", fallback_left),
        settings.get("default_right_cal", fallback_right),
    )


def main(tracker_mode="qy", quick=False, is_simulating=0):
    parameter_manager = FineVision_Notebook(
        task_name="CalibrationTask",
        default_params=DEFAULT_PARAMS,
        parameter_groups=CALIBRATION_PARAMETER_GROUPS,
        parameter_validator=_validate_calibration_params,
        parameter_summary_provider=_calibration_parameter_summary,
    )
    if not parameter_manager.prompt_for_parameters(
        title="FineVision Calibration Parameters / 校准参数"
    ):
        return None
    params = parameter_manager.exp_params
    gray_background = load_calibrated_gray_level(
        params["Background Gray Level (0-182)"]
    )
    background_color = rgb255_to_psychopy(gray_background["rgb_255"])

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path, task_path, sample_source = _calibration_paths(
        tracker_mode, timestamp
    )
    default_path = os.path.join(script_dir, default_path)
    task_path = os.path.join(script_dir, task_path)
    update_json(task_path, "Session_start_time", timestamp)
    update_json(task_path, "Tracker", tracker_mode)
    update_json(task_path, "Sample_Source", sample_source)
    update_json(task_path, "Subject_ID", params["Subject ID"])
    update_json(task_path, "Parameters", params)
    update_json(task_path, "Background", gray_background)

    tracker_runtime = None
    win_subject = None
    win_control = None
    arduino = None
    try:
        tracker_runtime = create_tracker_runtime(
            tracker_mode,
            is_simulating=bool(is_simulating),
            session_id=f"Calibration_{timestamp}",
            save_dir=os.path.dirname(os.path.abspath(task_path)) or ".",
            session_t0=time.perf_counter(),
            screen_size=SCREEN_SIZE,
            qy_sample_rate=100,
        )
        gaze_source = tracker_runtime.gaze_source

        win_subject = visual.Window(
            screen=int(params["Subject Screen Index"]),
            size=list(SCREEN_SIZE),
            fullscr=bool(params["Full Screen"]),
            waitBlanking=True,
            color=background_color,
            colorSpace="rgb",
            units="pix",
            allowGUI=False,
        )
        win_control = visual.Window(
            screen=int(params["Control Screen Index"]),
            size=[800, 450],
            fullscr=False,
            waitBlanking=False,
            color=background_color,
            colorSpace="rgb",
            units="pix",
            title=f"FineVision Calibration ({tracker_runtime.mode})",
        )

        try:
            arduino = ArduinoController()
        except Exception as exc:
            print(f"Arduino unavailable; calibration continues without reward: {exc}")

        add_quadrant_points = (
            str(tracker_mode).lower() == "eyelink" and not quick
        )
        random_seed = int(timestamp.replace("_", "")) % (2 ** 32)
        target_specs = _build_calibration_target_specs(
            params,
            SCREEN_SIZE,
            add_quadrant_points=add_quadrant_points,
            random_seed=random_seed,
        )
        fixation_point_radius_px = visual_angle_to_pixels(
            params["Fixation Point Radius (deg)"],
            params["Viewing Distance (cm)"],
            params["Subject Monitor Width (cm)"],
            SCREEN_SIZE[0],
        )
        fixation_window_radius_px = visual_angle_to_pixels(
            params["Fix Window Radius (deg)"],
            params["Viewing Distance (cm)"],
            params["Subject Monitor Width (cm)"],
            SCREEN_SIZE[0],
        )

        manager = CalibrationManager(
            subject_win=win_subject,
            control_win=win_control,
            shared_data=gaze_source,
            setting_file_path=task_path,
            arduino_controller=arduino,
            is_simulating=is_simulating,
            tracker_backend=tracker_runtime,
            add_quadrant_points=add_quadrant_points,
            random_seed=random_seed,
            target_specs=target_specs,
            fixation_point_radius_px=fixation_point_radius_px,
            fixation_window_radius_px=fixation_window_radius_px,
            background_color=background_color,
            fixation_duration_s=(
                float(params["Fixation Duration (ms)"]) / 1000.0
            ),
            max_wait_time_s=float(params["Maximum Wait per Point (s)"]),
            iti_s=float(params["ITI (s)"]),
            reward_ms=int(params["Reward Duration (ms)"]),
        )
        manager.calibration_report["parameters"] = dict(params)
        manager.calibration_report["background"] = gray_background
        default_left, default_right = _load_defaults(
            default_path, tracker_mode
        )

        tracker_runtime.send_event(
            "FINEVISION_CUSTOM_CALIBRATION_START "
            f"POINTS {3 if quick else len(manager.targets)} "
            f"MODEL AFFINE_2D BACKGROUND_LEVEL {gray_background['level']}"
        )
        if quick:
            calibration_result = manager.run_quick_calib(
                default_left, default_right
            )
        else:
            calibration_result = manager.run_calibration(
                default_left, default_right
            )
        if calibration_result is None:
            update_json(
                task_path,
                "Calibration_Report",
                manager.calibration_report,
            )
            tracker_runtime.send_event(
                "FINEVISION_CUSTOM_CALIBRATION_ABORTED"
            )
            print(
                "Calibration aborted; existing calibration settings were "
                "not changed."
            )
            return None
        left_cal, right_cal = calibration_result
        update_json(
            task_path,
            "Calibration_Report",
            manager.calibration_report,
        )
        tracker_runtime.send_event(
            "FINEVISION_CUSTOM_CALIBRATION_END"
        )

        writes_active_calibration = not (
            str(tracker_mode).lower() == "eyelink"
            and sample_source == "gaze"
        )
        if writes_active_calibration:
            update_json(default_path, "default_left_cal", left_cal)
            update_json(default_path, "default_right_cal", right_cal)
        else:
            print(
                "EyeLink GAZE bypasses FineVision affine calibration; "
                "the identity runtime file was not overwritten."
            )
        update_json(task_path, "left_cal", left_cal)
        update_json(task_path, "right_cal", right_cal)
        if writes_active_calibration:
            print(f"Calibration saved to {default_path} and {task_path}.")
        else:
            print(f"GAZE calibration report saved to {task_path}.")
        return left_cal, right_cal
    except Exception:
        traceback.print_exc()
        raise
    finally:
        if arduino is not None:
            try:
                arduino.close()
            except Exception:
                pass
        if tracker_runtime is not None:
            try:
                tracker_runtime.close()
            except Exception:
                traceback.print_exc()
        if win_subject is not None:
            win_subject.close()
        if win_control is not None:
            win_control.close()


if __name__ == "__main__":
    main("qy")
