"""FineVision custom calibration shared by QY and EyeLink entry scripts."""

import json
import os
import time
import traceback
from datetime import datetime

from psychopy import core, visual

from CalibrationManager import CalibrationManager
from FineVision_Util import ArduinoController
from Json_manager import update_json
from eyetracker import create_tracker_runtime


MONITOR_ID_SUBJECT = 1
MONITOR_ID_CONTROL = 0
SCREEN_SIZE = (1920, 1080)


def _calibration_paths(tracker_mode, timestamp):
    mode = str(tracker_mode).lower()
    default_path = (
        "eyelink_default_setting.json"
        if mode == "eyelink"
        else "default_setting.json"
    )
    task_path = f"{mode}_calibration_{timestamp}.json"
    return default_path, task_path


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path, task_path = _calibration_paths(tracker_mode, timestamp)
    default_path = os.path.join(script_dir, default_path)
    task_path = os.path.join(script_dir, task_path)
    update_json(task_path, "Session_start_time", timestamp)
    update_json(task_path, "Tracker", tracker_mode)

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
            screen=MONITOR_ID_SUBJECT,
            size=list(SCREEN_SIZE),
            fullscr=False,
            waitBlanking=True,
            color="black",
            units="pix",
            allowGUI=False,
        )
        win_control = visual.Window(
            screen=MONITOR_ID_CONTROL,
            size=[800, 600],
            fullscr=False,
            waitBlanking=False,
            color="black",
            units="pix",
            title=f"FineVision Calibration ({tracker_runtime.mode})",
        )

        try:
            arduino = ArduinoController()
        except Exception as exc:
            print(f"Arduino unavailable; calibration continues without reward: {exc}")

        manager = CalibrationManager(
            subject_win=win_subject,
            control_win=win_control,
            shared_data=gaze_source,
            setting_file_path=task_path,
            arduino_controller=arduino,
            is_simulating=is_simulating,
        )
        default_left, default_right = _load_defaults(
            default_path, tracker_mode
        )

        tracker_runtime.send_event(
            "FINEVISION_CUSTOM_CALIBRATION_START"
        )
        if quick:
            left_cal, right_cal = manager.run_quick_calib(
                default_left, default_right
            )
        else:
            left_cal, right_cal = manager.run_calibration(
                default_left, default_right
            )
        tracker_runtime.send_event(
            "FINEVISION_CUSTOM_CALIBRATION_END"
        )

        update_json(default_path, "default_left_cal", left_cal)
        update_json(default_path, "default_right_cal", right_cal)
        update_json(task_path, "left_cal", left_cal)
        update_json(task_path, "right_cal", right_cal)
        print(f"Calibration saved to {default_path} and {task_path}.")
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
