"""Shared in-session EyeLink calibration window for running tasks."""

import json
import os

from psychopy import event, visual


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NATIVE_PARAMS_FILE = os.path.join(
    SCRIPT_DIR,
    "params_EyeLinkNativeCalibration.json",
)


def load_recalibration_options(path=DEFAULT_NATIVE_PARAMS_FILE):
    """Load the most recently saved native-calibration choices."""
    defaults = {
        "Calibration Type": "HV5",
        "Maximum Calibration Eccentricity (deg)": 12.0,
        "Reward Mode": "advance",
        "Reward Duration (ms)": 300,
        "Automatic Pacing (ms)": 1200,
    }
    try:
        with open(path, "r", encoding="utf-8-sig") as source_file:
            saved = json.load(source_file).get("parameters", {})
    except (OSError, ValueError, TypeError):
        saved = {}
    defaults.update(
        {
            key: saved[key]
            for key in defaults
            if key in saved
        }
    )
    return defaults


def _set_window_visible(window, visible):
    """Best-effort visibility/focus control for a PsychoPy window handle."""
    handle = getattr(window, "winHandle", None)
    if handle is None:
        return
    set_visible = getattr(handle, "set_visible", None)
    if callable(set_visible):
        set_visible(bool(visible))
    if visible:
        for method_name in ("activate", "switch_to"):
            method = getattr(handle, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass


def _flip_window(window):
    """Refresh a restored window without polling the task keyboard."""
    flip = getattr(window, "flip", None)
    if callable(flip):
        try:
            flip()
        except Exception:
            pass


def run_in_session_calibration(
    *,
    tracker_backend,
    win_subject,
    win_control,
    background_color,
    viewing_distance_cm,
    monitor_width_cm,
    monitor_height_cm,
    fixation_point_radius_deg,
    arduino,
    subject_screen_index=1,
    blank_callback=None,
    options=None,
):
    """Run native EyeLink setup in a temporary full-screen subject window."""
    if not getattr(tracker_backend, "supports_recalibration", False):
        raise RuntimeError(
            "The active eye tracker does not support native recalibration."
        )
    options = dict(options or load_recalibration_options())
    calibration_window = None
    if blank_callback is not None:
        blank_callback()
    event.clearEvents()
    _set_window_visible(win_subject, False)
    try:
        calibration_window = visual.Window(
            screen=int(subject_screen_index),
            size=[
                int(win_subject.size[0]),
                int(win_subject.size[1]),
            ],
            fullscr=True,
            waitBlanking=True,
            color=background_color,
            colorSpace="rgb",
            units="pix",
            allowGUI=False,
            title="FineVision EyeLink In-session Calibration",
        )
        calibration_window.flip()
        _set_window_visible(calibration_window, True)
        print(
            f"EyeLink calibration is starting automatically on subject "
            f"screen {int(subject_screen_index)}. Successful calibration "
            "returns automatically; Esc returns without completing "
            "calibration."
        )
        tracker_backend.recalibrate(
            calibration_window,
            calibration_type=options["Calibration Type"],
            max_eccentricity_deg=float(
                options["Maximum Calibration Eccentricity (deg)"]
            ),
            viewing_distance_cm=float(viewing_distance_cm),
            monitor_width_cm=float(monitor_width_cm),
            monitor_height_cm=float(monitor_height_cm),
            fixation_point_radius_deg=float(fixation_point_radius_deg),
            background_color=background_color,
            arduino=arduino,
            reward_mode=options["Reward Mode"],
            reward_ms=int(options["Reward Duration (ms)"]),
            pacing_ms=int(options["Automatic Pacing (ms)"]),
        )
    finally:
        if calibration_window is not None:
            try:
                calibration_window.close()
            except Exception:
                pass
        _set_window_visible(win_subject, True)
        win_subject.color = background_color
        if win_control is not None:
            win_control.color = background_color
        # Do not call the task's normal frame renderer here: it also polls
        # Escape, and the key used to leave EyeLink setup can be delivered to
        # the restored task window during its first flip.
        _flip_window(win_subject)
        if win_control is not None:
            _flip_window(win_control)
        event.clearEvents()
