"""FineVision custom calibration shared by QY and EyeLink entry scripts."""

import json
import math
import os
import time
import traceback
from datetime import datetime
from SessionNaming import subject_filename

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
from CalibrationValidation import write_json, save_mapping, show_validation, require_fit_data
from CalibrationPoints import DEFAULT_POINTS, normalize_points, edit_points


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
    "Viewing Distance (cm)": 60.0,
    "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Subject Screen Index": MONITOR_ID_SUBJECT,
    "Control Screen Index": MONITOR_ID_CONTROL,
    "Full Screen": False,
    "Screen Width (px)": 1920,
    "Screen Height (px)": 1080,
    "Control Width (px)": 800,
    "Control Height (px)": 450,
    "Sample Rate (Hz)": 1000,
    "Sample Duration (ms)": 100,
    "Minimum Samples": 3,
    "Additional Quadrant Points": False,
    "Random Seed": 20261020,
}


CALIBRATION_PARAMETER_GROUPS = {
    "Session / 会话": [
        "Subject ID",
        "Subject Screen Index",
        "Control Screen Index",
        "Full Screen",
        "Screen Width (px)", "Screen Height (px)",
        "Control Width (px)", "Control Height (px)",
    ],
    "Calibration / 校准": [
        "Calibration Horizontal Extent (deg)",
        "Calibration Vertical Extent (deg)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
        "Additional Quadrant Points", "Random Seed",
    ],
    "Timing & Reward / 时间与奖励": [
        "Fixation Duration (ms)",
        "Maximum Wait per Point (s)",
        "ITI (s)",
        "Reward Duration (ms)",
        "Sample Rate (Hz)", "Sample Duration (ms)", "Minimum Samples",
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
    if "Calibration Points" in params:
        return [dict(target=(
            visual_angle_to_pixels(p['x_deg'], distance, monitor_width, screen_size[0]),
            visual_angle_to_pixels(p['y_deg'], distance, monitor_height, screen_size[1])),
            target_deg=(p['x_deg'], p['y_deg']), weight=p['weight'], region='custom')
            for p in normalize_points(params['Calibration Points'])]
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
        int(params.get("Screen Width (px)", 1920)),
    )
    y_px = visual_angle_to_pixels(
        params["Calibration Vertical Extent (deg)"],
        params["Viewing Distance (cm)"],
        params["Subject Monitor Height (cm)"],
        int(params.get("Screen Height (px)", 1080)),
    )
    return (
        f"9-point extent: ±{x_px:.1f} px horizontal, ±{y_px:.1f} px vertical\n"
        f"Background: level {gray['level']}, RGB {gray['rgb_255']}, "
        f"{gray['luminance_cd_m2']:.3f} cd/m²"
    )


def _validate_calibration_params(params):
    for field in ("Screen Width (px)", "Screen Height (px)", "Control Width (px)", "Control Height (px)", "Sample Rate (Hz)", "Sample Duration (ms)"):
        if not math.isfinite(float(params.get(field, DEFAULT_PARAMS[field]))) or float(params.get(field, DEFAULT_PARAMS[field])) <= 0:
            raise ValueError(f"{field} must be finite and positive.")
    if int(params.get("Minimum Samples", 3)) < 3:
        raise ValueError("Minimum Samples must be at least 3.")
    if float(params.get("Sample Duration (ms)", 100)) > float(params["Fixation Duration (ms)"]):
        raise ValueError("Sample Duration must not exceed Fixation Duration.")
    if int(params.get("Random Seed", 0)) < 0:
        raise ValueError("Random Seed cannot be negative.")
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
        if 'Calibration Points' in params and field.startswith('Calibration '):
            continue
        if not math.isfinite(float(params[field])) or float(params[field]) <= 0:
            raise ValueError(f"{field} must be positive.")
    if float(params["Fixation Duration (ms)"]) <= 0:
        raise ValueError("Fixation Duration must be positive.")
    if float(params["ITI (s)"]) < 0:
        raise ValueError("ITI cannot be negative.")
    if int(params["Reward Duration (ms)"]) < 0:
        raise ValueError("Reward Duration cannot be negative.")
    if int(params["Subject Screen Index"]) < 0:
        raise ValueError("Subject Screen Index cannot be negative.")
    if int(params["Control Screen Index"]) < 0:
        raise ValueError("Control Screen Index cannot be negative.")
    load_calibrated_gray_level(params["Background Gray Level (0-182)"])

    screen_size = (int(params.get("Screen Width (px)", 1920)), int(params.get("Screen Height (px)", 1080)))
    target_specs = _build_calibration_target_specs(params, screen_size)
    point_radius_px = visual_angle_to_pixels(
        params["Fixation Point Radius (deg)"],
        params["Viewing Distance (cm)"],
        params["Subject Monitor Width (cm)"],
        screen_size[0],
    )
    half_width = screen_size[0] / 2.0
    half_height = screen_size[1] / 2.0
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


def main(tracker_mode="qy", quick=False, is_simulating=0, validation=False):
    custom_raw = str(tracker_mode).lower() == "eyelink" and not quick
    # Calibration and validation intentionally share the calibration settings.
    task_name = "CalibrationTask"
    point_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              f"params_{task_name}_points.json")
    def validate_parameters(values):
        checked = dict(DEFAULT_PARAMS, **values)
        if custom_raw:
            checked['Calibration Points'] = DEFAULT_POINTS
        return _validate_calibration_params(checked)
    dialog_defaults = dict(DEFAULT_PARAMS)
    if custom_raw:
        for field in ('Calibration Horizontal Extent (deg)', 'Calibration Vertical Extent (deg)', 'Additional Quadrant Points'):
            dialog_defaults.pop(field)
    parameter_manager = FineVision_Notebook(
        task_name=task_name,
        default_params=dialog_defaults,
        parameter_groups=CALIBRATION_PARAMETER_GROUPS,
        parameter_validator=validate_parameters,
        parameter_summary_provider=(lambda p: "下一步编辑RAW目标点：X、Y角度与拟合权重。") if custom_raw else _calibration_parameter_summary,
    )
    if not parameter_manager.prompt_for_parameters(
        title="FineVision Calibration Parameters / 校准参数"
    ):
        return None
    params = parameter_manager.exp_params
    params = dict(DEFAULT_PARAMS, **params)
    if custom_raw:
        points = DEFAULT_POINTS
        if os.path.isfile(point_file):
            with open(point_file, encoding='utf-8') as handle:
                points = json.load(handle)['points']
        points = edit_points(points,
            lambda ps: _validate_calibration_params(dict(params, **{'Calibration Points': ps})),
            title='RAW validation points / RAW验证点' if validation else 'RAW calibration points / RAW校准点')
        if points is None:
            return None
        params['Calibration Points'] = points
        write_json(point_file, dict(points=points))
        _validate_calibration_params(params)
    screen_size = (int(params["Screen Width (px)"]), int(params["Screen Height (px)"]))
    gray_background = load_calibrated_gray_level(
        params["Background Gray Level (0-182)"]
    )
    background_color = rgb255_to_psychopy(gray_background["rgb_255"])

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path, task_path, sample_source = _calibration_paths(
        tracker_mode, subject_filename(params["Subject ID"]) + "_" + timestamp
    )
    default_path = os.path.join(script_dir, default_path)
    session_id = f"{'Validation' if validation else 'Calibration'}_{subject_filename(params['Subject ID'])}_{timestamp}"
    log_dir = os.path.join(script_dir, "experiment_logs", session_id)
    os.makedirs(log_dir, exist_ok=False)
    task_path = os.path.join(log_dir, "session.json")
    settings_override = {}
    if str(tracker_mode).lower() == "eyelink":
        # These standalone tools always collect RAW, independently of task settings.
        default_path = os.path.join(script_dir, "eyelink_raw_pupil_setting.json")
        sample_source = "raw"
        with open(os.path.join(script_dir, "eyelink_setting.json"), encoding="utf-8") as handle:
            settings = json.load(handle)
        settings.update(sample_source="raw", calibration_file=default_path,
                        sample_rate_hz=int(params["Sample Rate (Hz)"]), active_eye="right")
        settings_path = os.path.join(log_dir, "tracker_settings.json")
        write_json(settings_path, settings)
        settings_override["eyelink_settings_path"] = settings_path
    default_left, default_right = _load_defaults(default_path, tracker_mode)
    write_json(os.path.join(log_dir, "mapping_before.json"), dict(default_left_cal=default_left, default_right_cal=default_right))
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
            session_id=session_id,
            save_dir=os.path.dirname(os.path.abspath(task_path)) or ".",
            session_t0=time.perf_counter(),
            screen_size=screen_size,
            qy_sample_rate=100,
            **settings_override,
        )
        gaze_source = tracker_runtime.gaze_source

        win_subject = visual.Window(
            screen=int(params["Subject Screen Index"]),
            size=list(screen_size),
            fullscr=bool(params["Full Screen"]),
            waitBlanking=True,
            color=background_color,
            colorSpace="rgb",
            units="pix",
            allowGUI=False,
        )
        win_control = visual.Window(
            screen=int(params["Control Screen Index"]),
            size=[int(params["Control Width (px)"]), int(params["Control Height (px)"])],
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

        actual_size = tuple(int(value) for value in win_subject.size)
        if actual_size != screen_size:
            raise ValueError(f"Actual subject window {actual_size} differs from EyeLink coordinates {screen_size}.")
        add_quadrant_points = bool(params["Additional Quadrant Points"]) and not quick and not validation
        random_seed = int(params["Random Seed"])
        target_specs = _build_calibration_target_specs(
            params,
            screen_size,
            add_quadrant_points=add_quadrant_points,
            random_seed=random_seed,
        )
        fixation_point_radius_px = visual_angle_to_pixels(
            params["Fixation Point Radius (deg)"],
            params["Viewing Distance (cm)"],
            params["Subject Monitor Width (cm)"],
            screen_size[0],
        )
        fixation_window_radius_px = visual_angle_to_pixels(
            params["Fix Window Radius (deg)"],
            params["Viewing Distance (cm)"],
            params["Subject Monitor Width (cm)"],
            screen_size[0],
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
            sample_duration_s=float(params["Sample Duration (ms)"]) / 1000,
            minimum_samples=int(params["Minimum Samples"]),
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
                default_left, default_right, apply_result=not validation
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
        update_json(task_path, "Mapping_Before", dict(left=default_left, right=default_right))
        if validation:
            # Finish EDF transfer before opening the blocking review window.
            # No model has been fitted or applied to validation samples yet.
            update_json(task_path, "Calibration_Report", manager.calibration_report)
            tracker_runtime.close()
            update_json(task_path, "EDF", dict(path=getattr(tracker_runtime, "local_edf_path", None), downloaded=True))
            win_subject.close(); win_subject = None
            win_control.close(); win_control = None
            should_update = show_validation(manager.collected_data, default_right, log_dir)
            update_json(task_path, "Update_Selected", should_update)
            if should_update:
                require_fit_data(manager.collected_data)
                # Offline fitting: the tracker connection is already closed.
                left_cal = manager._fit_affine(manager.collected_data[:, 2], manager.collected_data[:, 3],
                    manager.collected_data[:, 0], manager.collected_data[:, 1], default_left, weights=manager.collected_weights)
                right_cal = manager._fit_affine(manager.collected_data[:, 4], manager.collected_data[:, 5],
                    manager.collected_data[:, 0], manager.collected_data[:, 1], default_right, weights=manager.collected_weights)
                save_mapping(default_path, log_dir, left_cal, right_cal,
                    dict(session_id=session_id, source="validation_refit", independently_validated=False,
                         sample_source=sample_source, parameters=params))
                update_json(task_path, "Mapping_After", dict(left=left_cal, right=right_cal))
                print("Mapping updated. Run a NEW validation to evaluate the new fit.")
            else:
                print(f"Mapping unchanged. Validation plot and records saved to {log_dir}")
            return left_cal, right_cal
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
            if str(tracker_mode).lower() == "eyelink":
                if hasattr(manager, "collected_data"):
                    require_fit_data(manager.collected_data)
                save_mapping(default_path, log_dir, left_cal, right_cal,
                    dict(session_id=session_id, source="calibration", independently_validated=False,
                         sample_source=sample_source, parameters=params))
            else:
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
                edf_path = getattr(tracker_runtime, "local_edf_path", None)
                update_json(task_path, "EDF", dict(path=edf_path,
                    downloaded=bool(edf_path and os.path.isfile(edf_path))))
            except Exception:
                update_json(task_path, "EDF_Transfer_Error", traceback.format_exc())
                traceback.print_exc()
        if win_subject is not None:
            win_subject.close()
        if win_control is not None:
            win_control.close()


if __name__ == "__main__":
    main("qy")
