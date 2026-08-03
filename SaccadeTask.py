"""Two-stage fixation-to-saccade task for FineVision."""

import csv
import math
import os
import random
import time
import traceback
from datetime import datetime
from multiprocessing import Queue, Value, freeze_support
from queue import Full

from psychopy import core, event, visual

from EyeDataLogger import GazeCsvWriter, STOP_TOKEN
from FineVision_Notebook import FineVision_Notebook
from FineVision_Util import ArduinoController
from GazeTrackerRenderer import GazeTrackerRenderer
from eyetracker import create_tracker_runtime


IS_SIMULATING = 0
MONITOR_ID_SUBJECT = 1
MONITOR_ID_CONTROL = 0
EYE_TRACKER_RATE_HZ = 100


DEFAULT_PARAMS = {
    "Subject ID": "Monkey_H18",
    "Wait Time (s)": 5.0,
    "Fixation Acquire Time (ms)": 150,
    "Fixation Position X (deg)": 0.0,
    "Fixation Position Y (deg)": 0.0,
    "Fixation Point Radius (deg)": 0.2,
    "Fix Window Radius (deg)": 2.0,
    "Fixation Duration Min (ms)": 300,
    "Fixation Duration Max (ms)": 500,
    "Gap Duration (ms)": 100,
    "Stim Duration (ms)": 200,
    "Stim Window After Stim Off (ms)": 300,
    "Stim Hold Time (ms)": 100,
    "Stim Window Radius (deg)": 2.0,
    "Stim Position X (deg)": 4.0,
    "Stim Position Y (deg)": -2.0,
    "Stim Major Axis (deg)": 1.0,
    "Stim Minor Axis (deg)": 1.0,
    "Stim Orientation (deg)": 120,
    "Stim Color R": 180,
    "Stim Color G": 0,
    "Stim Color B": 0,
    "Viewing Distance (cm)": 60.0,
    "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Reward Length (s)": 0.5,
    "ITI (s)": 4.0,
    "Timeout (s)": 0.5,
}

SACCADE_PARAMETER_GROUPS = {
    "Session / 会话": [
        "Subject ID",
        "Wait Time (s)",
    ],
    "Fixation / 注视": [
        "Fixation Acquire Time (ms)",
        "Fixation Position X (deg)",
        "Fixation Position Y (deg)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
        "Fixation Duration Min (ms)",
        "Fixation Duration Max (ms)",
    ],
    "Timing / 时间": [
        "Gap Duration (ms)",
        "Stim Duration (ms)",
        "Stim Window After Stim Off (ms)",
        "Stim Hold Time (ms)",
    ],
    "Stimulus / 刺激": [
        "Stim Window Radius (deg)",
        "Stim Position X (deg)",
        "Stim Position Y (deg)",
        "Stim Major Axis (deg)",
        "Stim Minor Axis (deg)",
        "Stim Orientation (deg)",
        "Stim Color R",
        "Stim Color G",
        "Stim Color B",
    ],
    "Display / 屏幕": [
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
    ],
    "Reward / 奖励": [
        "Reward Length (s)",
        "ITI (s)",
        "Timeout (s)",
    ],
}


TRIAL_LOG_FIELDS = [
    "Trial",
    "Status",
    "Time_TrialStart",
    "Time_DrawFinish",
    "Time_GazeEnter",
    "Time_StimOn",
    "Time_FixationPointOff",
    "Fixation_Position_deg",
    "Time_StimWindowEnter",
    "Time_StimOff",
    "Time_StimWindowEnd",
    "Time_Reward",
    "Time_End",
    "Subject_ID",
    "Fixation_Pos_X_deg",
    "Fixation_Pos_Y_deg",
    "Fixation_Point_Radius_deg",
    "Fix_Window_Radius_deg",
    "Stim_Position_deg",
    "Stim_Pos_X_deg",
    "Stim_Pos_Y_deg",
    "Stim_Window_Radius_deg",
    "Stim_Major_Axis_deg",
    "Stim_Minor_Axis_deg",
    "Stim_Orientation_deg",
    "Stim_Color_R",
    "Stim_Color_G",
    "Stim_Color_B",
    "Viewing_Distance_cm",
    "Monitor_Width_cm",
    "Monitor_Height_cm",
    "Fixation_Acquire_Time_ms",
    "Planned_Fixation_Duration_ms",
    "Fixation_Duration_Min_ms",
    "Fixation_Duration_Max_ms",
    "Gap_Duration_ms",
    "Stim_Duration_ms",
    "Stim_Window_After_Stim_Off_ms",
    "Stim_Hold_Time_ms",
]

TIME_FIELDS = [
    "Time_TrialStart",
    "Time_DrawFinish",
    "Time_GazeEnter",
    "Time_StimOn",
    "Time_FixationPointOff",
    "Time_StimWindowEnter",
    "Time_StimOff",
    "Time_StimWindowEnd",
    "Time_Reward",
    "Time_End",
]


class TaskAbort(Exception):
    """Raised when Escape is pressed."""


class TrialCsvLogger:
    """Append and flush one row at the end of every trial."""

    def __init__(self, csv_path, fieldnames=None):
        self.csv_path = csv_path
        self.fieldnames = list(fieldnames or TRIAL_LOG_FIELDS)
        self._file = open(csv_path, "w", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=self.fieldnames,
        )
        self._writer.writeheader()
        self._file.flush()

    def write(self, row):
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        if not self._file.closed:
            self._file.flush()
            self._file.close()


def visual_angle_to_cm(angle_deg, viewing_distance_cm):
    """Convert a full visual angle to its physical size on the display."""
    return (
        2.0
        * viewing_distance_cm
        * math.tan(math.radians(angle_deg) / 2.0)
    )


def visual_angle_to_pixels(
    angle_deg, viewing_distance_cm, monitor_size_cm, resolution_pixels
):
    """Convert degrees of visual angle to pixels along one display axis."""
    return (
        visual_angle_to_cm(angle_deg, viewing_distance_cm)
        * resolution_pixels
        / monitor_size_cm
    )


def _make_ellipse_vertices(width, height, count=96):
    return [
        (
            math.cos(2.0 * math.pi * index / count) * width / 2.0,
            math.sin(2.0 * math.pi * index / count) * height / 2.0,
        )
        for index in range(count)
    ]


def _validate_params(params):
    fix_acquire_ms = float(params["Fixation Acquire Time (ms)"])
    fix_duration_min_ms = float(params["Fixation Duration Min (ms)"])
    fix_duration_max_ms = float(params["Fixation Duration Max (ms)"])
    gap_duration_ms = float(params["Gap Duration (ms)"])
    stim_duration_ms = float(params["Stim Duration (ms)"])
    stim_window_after_off_ms = float(
        params["Stim Window After Stim Off (ms)"]
    )
    stim_hold_ms = float(params["Stim Hold Time (ms)"])

    if fix_duration_min_ms < fix_acquire_ms:
        raise ValueError(
            "Fixation Duration Min (ms) must be greater than or equal to "
            "Fixation Acquire Time (ms)."
        )
    if fix_duration_max_ms < fix_duration_min_ms:
        raise ValueError(
            "Fixation Duration Max (ms) must be greater than or equal to "
            "Fixation Duration Min (ms)."
        )
    if gap_duration_ms < 0:
        raise ValueError("Gap Duration (ms) cannot be negative.")
    if stim_duration_ms <= 0:
        raise ValueError("Stim Duration (ms) must be greater than zero.")
    if stim_window_after_off_ms < 0:
        raise ValueError(
            "Stim Window After Stim Off (ms) cannot be negative."
        )
    if stim_hold_ms <= 0:
        raise ValueError("Stim Hold Time (ms) must be greater than zero.")
    if stim_duration_ms + stim_window_after_off_ms < stim_hold_ms:
        raise ValueError(
            "Stim Duration + Stim Window After Stim Off must be at least "
            "Stim Hold Time."
        )

    positive_fields = [
        "Wait Time (s)",
        "Fixation Acquire Time (ms)",
        "Fixation Duration Min (ms)",
        "Fixation Duration Max (ms)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
        "Stim Window Radius (deg)",
        "Stim Major Axis (deg)",
        "Stim Minor Axis (deg)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
        "Reward Length (s)",
        "ITI (s)",
    ]
    for field in positive_fields:
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")
    for field in (
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
        "Stim Window Radius (deg)",
        "Stim Major Axis (deg)",
        "Stim Minor Axis (deg)",
    ):
        if float(params[field]) >= 180.0:
            raise ValueError(f"{field} must be less than 180 degrees.")
    if float(params["Stim Major Axis (deg)"]) < float(
        params["Stim Minor Axis (deg)"]
    ):
        raise ValueError(
            "Stim Major Axis (deg) must be greater than or equal to "
            "Stim Minor Axis (deg)."
        )
    if float(params["Timeout (s)"]) < 0:
        raise ValueError("Timeout (s) cannot be negative.")

    for field in (
        "Fixation Position X (deg)",
        "Fixation Position Y (deg)",
        "Stim Position X (deg)",
        "Stim Position Y (deg)",
    ):
        if abs(float(params[field])) >= 180.0:
            raise ValueError(f"{field} must be between -180 and 180 degrees.")

    for field in ("Stim Color R", "Stim Color G", "Stim Color B"):
        value = float(params[field])
        if not 0 <= value <= 255:
            raise ValueError(f"{field} must be in the range 0-255.")


class SaccadeTask:
    def __init__(
        self,
        win_sub,
        win_ctl,
        shared_data,
        task_manager,
        is_simulating,
        session_t0,
        save_dir,
        session_timestamp,
        tracker_backend=None,
    ):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.task_manager = task_manager
        self.is_simulating = is_simulating
        self.session_t0 = float(session_t0)
        self.save_dir = save_dir
        self.session_timestamp = session_timestamp
        self.tracker_backend = tracker_backend

        self.scale_x = win_ctl.size[0] / win_sub.size[0]
        self.scale_y = win_ctl.size[1] / win_sub.size[1]
        self.gaze_renderer = GazeTrackerRenderer(
            win_ctl,
            shared_data,
            self.scale_x,
            self.scale_y,
            is_simulating,
        )
        self.arduino = ArduinoController()
        self.behavior_log = []

        task_log_path = os.path.join(save_dir, self._task_log_filename())
        self.trial_logger = TrialCsvLogger(
            task_log_path,
            fieldnames=self._trial_log_fields(),
        )

    def _task_log_filename(self):
        return f"Saccade_task_log_{self.session_timestamp}.csv"

    def _trial_log_fields(self):
        return TRIAL_LOG_FIELDS

    def now(self):
        return time.perf_counter() - self.session_t0

    def update_params(self):
        params = self.task_manager.exp_params
        _validate_params(params)

        self.subject_id = str(params["Subject ID"])
        self.wait_time_s = float(params["Wait Time (s)"])
        self.fix_acquire_s = float(params["Fixation Acquire Time (ms)"]) / 1000.0
        self.fix_x_deg = float(params["Fixation Position X (deg)"])
        self.fix_y_deg = float(params["Fixation Position Y (deg)"])
        self.fix_point_radius_deg = float(
            params["Fixation Point Radius (deg)"]
        )
        self.fix_radius_deg = float(params["Fix Window Radius (deg)"])

        self.fix_duration_min_s = (
            float(params["Fixation Duration Min (ms)"]) / 1000.0
        )
        self.fix_duration_max_s = (
            float(params["Fixation Duration Max (ms)"]) / 1000.0
        )
        self.gap_duration_s = float(params["Gap Duration (ms)"]) / 1000.0
        self.stim_duration_s = (
            float(params["Stim Duration (ms)"]) / 1000.0
        )
        self.stim_window_after_off_s = (
            float(params["Stim Window After Stim Off (ms)"]) / 1000.0
        )
        self.stim_hold_s = float(params["Stim Hold Time (ms)"]) / 1000.0

        self.stim_radius_deg = float(params["Stim Window Radius (deg)"])
        self.stim_x_deg = float(params["Stim Position X (deg)"])
        self.stim_y_deg = float(params["Stim Position Y (deg)"])
        self.stim_major_axis_deg = float(params["Stim Major Axis (deg)"])
        self.stim_minor_axis_deg = float(params["Stim Minor Axis (deg)"])
        self.stim_orientation_deg = float(params["Stim Orientation (deg)"])
        self.stim_rgb_255 = (
            int(float(params["Stim Color R"])),
            int(float(params["Stim Color G"])),
            int(float(params["Stim Color B"])),
        )

        self.viewing_distance_cm = float(params["Viewing Distance (cm)"])
        self.monitor_width_cm = float(params["Subject Monitor Width (cm)"])
        self.monitor_height_cm = float(params["Subject Monitor Height (cm)"])

        # Eye-tracker samples and both PsychoPy windows remain in pixels
        # internally; only experiment-facing parameters are specified in deg.
        self.fix_x_px = self._to_x_pixels(self.fix_x_deg)
        self.fix_y_px = self._to_y_pixels(self.fix_y_deg)
        self.fix_point_radius_px = self._to_x_pixels(
            self.fix_point_radius_deg
        )
        self.fix_radius_px = self._to_x_pixels(self.fix_radius_deg)
        self.stim_radius_px = self._to_x_pixels(self.stim_radius_deg)
        self.stim_x_px = self._to_x_pixels(self.stim_x_deg)
        self.stim_y_px = self._to_y_pixels(self.stim_y_deg)
        self.stim_major_axis_px = self._to_x_pixels(
            self.stim_major_axis_deg
        )
        self.stim_minor_axis_px = self._to_y_pixels(
            self.stim_minor_axis_deg
        )

        self.reward_len_s = float(params["Reward Length (s)"])
        self.iti_s = float(params["ITI (s)"])
        self.timeout_s = float(params["Timeout (s)"])
        self._build_visuals()

    def _to_x_pixels(self, angle_deg):
        return visual_angle_to_pixels(
            angle_deg,
            self.viewing_distance_cm,
            self.monitor_width_cm,
            self.win_sub.size[0],
        )

    def _to_y_pixels(self, angle_deg):
        return visual_angle_to_pixels(
            angle_deg,
            self.viewing_distance_cm,
            self.monitor_height_cm,
            self.win_sub.size[1],
        )

    def _build_visuals(self):
        self.fix_sub = visual.Circle(
            self.win_sub,
            radius=self.fix_point_radius_px,
            fillColor="white",
            lineColor="white",
            pos=(self.fix_x_px, self.fix_y_px),
        )
        self.fix_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fix_point_radius_px * self.scale_x,
            fillColor="green",
            lineColor="green",
            pos=(
                self.fix_x_px * self.scale_x,
                self.fix_y_px * self.scale_y,
            ),
        )
        self.fix_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fix_radius_px * self.scale_x,
            fillColor=None,
            lineColor="red",
            lineWidth=2,
            pos=(
                self.fix_x_px * self.scale_x,
                self.fix_y_px * self.scale_y,
            ),
        )

        color = [channel / 127.5 - 1.0 for channel in self.stim_rgb_255]
        self.stim_sub = visual.ShapeStim(
            self.win_sub,
            vertices=_make_ellipse_vertices(
                self.stim_major_axis_px, self.stim_minor_axis_px
            ),
            closeShape=True,
            fillColor=color,
            lineColor=color,
            pos=(self.stim_x_px, self.stim_y_px),
            ori=self.stim_orientation_deg,
        )
        self.stim_ctl = visual.ShapeStim(
            self.win_ctl,
            vertices=_make_ellipse_vertices(
                self.stim_major_axis_px * self.scale_x,
                self.stim_minor_axis_px * self.scale_y,
            ),
            closeShape=True,
            fillColor=color,
            lineColor=color,
            pos=(
                self.stim_x_px * self.scale_x,
                self.stim_y_px * self.scale_y,
            ),
            ori=self.stim_orientation_deg,
        )
        self.stim_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.stim_radius_px * self.scale_x,
            fillColor=None,
            lineColor="cyan",
            lineWidth=2,
            pos=(
                self.stim_x_px * self.scale_x,
                self.stim_y_px * self.scale_y,
            ),
        )

    def _mark_time(self, trial_data, field):
        if trial_data[field] is None:
            trial_data[field] = self.now()
            tracker_event = {
                "Time_DrawFinish": "FIX_ON",
                "Time_FixationPointOff": "FIX_OFF",
                "Time_StimOn": "STIM_ON",
                "Time_StimOff": "STIM_OFF",
                "Time_StimWindowEnd": "STIM_WINDOW_END",
            }.get(field)
            if tracker_event is not None:
                self._send_tracker_event(
                    f"{tracker_event} TRIAL {trial_data['Trial']}"
                )

    def _send_tracker_event(self, message):
        if self.tracker_backend is not None:
            self.tracker_backend.send_event(message)

    def _send_trial_start_metadata(self, trial_data):
        """Hook for task variants that add EDF trial variables."""

    def _schedule_flip_time(self, trial_data, field):
        if trial_data[field] is None:
            self.win_sub.callOnFlip(self._mark_time, trial_data, field)

    def _poll_commands(self):
        keys = event.getKeys()
        if "escape" in keys:
            raise TaskAbort()
        return "n" in keys

    def _in_window(self, gaze, center_x, center_y, radius):
        return bool(gaze["valid"]) and math.hypot(
            gaze["x"] - center_x, gaze["y"] - center_y
        ) <= radius

    def _present_frame(
        self,
        fix_visible,
        stim_visible,
        stim_window_active=None,
        fix_window_active=None,
    ):
        if stim_window_active is None:
            stim_window_active = stim_visible
        if fix_window_active is None:
            fix_window_active = fix_visible

        if fix_visible:
            self.fix_sub.draw()
            self.fix_ctl.draw()
        if fix_window_active:
            self.fix_window_ctl.draw()
        if stim_visible:
            self.stim_sub.draw()
            self.stim_ctl.draw()
        if stim_window_active:
            self.stim_window_ctl.draw()

        gaze = self.gaze_renderer.update_and_draw()
        self.win_sub.flip()
        self.win_ctl.flip()
        pause_requested = self._poll_commands()
        return gaze, pause_requested

    def _black_out(self, trial_data):
        if trial_data["Time_DrawFinish"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_StimOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_StimOff")
            self._schedule_flip_time(trial_data, "Time_StimWindowEnd")
        self._present_frame(False, False)

    def _new_trial_data(self, trial_number, fixation_duration_s):
        return {
            "Trial": trial_number,
            "Status": None,
            "Time_TrialStart": None,
            "Time_DrawFinish": None,
            "Time_GazeEnter": None,
            "Time_StimOn": None,
            "Time_FixationPointOff": None,
            "Fixation_Position_deg": (
                f"({self.fix_x_deg:g}, {self.fix_y_deg:g}) deg"
            ),
            "Time_StimWindowEnter": None,
            "Time_StimOff": None,
            "Time_StimWindowEnd": None,
            "Time_Reward": None,
            "Time_End": None,
            "Subject_ID": self.subject_id,
            "Fixation_Pos_X_deg": self.fix_x_deg,
            "Fixation_Pos_Y_deg": self.fix_y_deg,
            "Fixation_Point_Radius_deg": self.fix_point_radius_deg,
            "Fix_Window_Radius_deg": self.fix_radius_deg,
            "Stim_Position_deg": (
                f"({self.stim_x_deg:g}, {self.stim_y_deg:g})"
            ),
            "Stim_Pos_X_deg": self.stim_x_deg,
            "Stim_Pos_Y_deg": self.stim_y_deg,
            "Stim_Window_Radius_deg": self.stim_radius_deg,
            "Stim_Major_Axis_deg": self.stim_major_axis_deg,
            "Stim_Minor_Axis_deg": self.stim_minor_axis_deg,
            "Stim_Orientation_deg": self.stim_orientation_deg,
            "Stim_Color_R": self.stim_rgb_255[0],
            "Stim_Color_G": self.stim_rgb_255[1],
            "Stim_Color_B": self.stim_rgb_255[2],
            "Viewing_Distance_cm": self.viewing_distance_cm,
            "Monitor_Width_cm": self.monitor_width_cm,
            "Monitor_Height_cm": self.monitor_height_cm,
            "Fixation_Acquire_Time_ms": self.fix_acquire_s * 1000.0,
            "Planned_Fixation_Duration_ms": fixation_duration_s * 1000.0,
            "Fixation_Duration_Min_ms": self.fix_duration_min_s * 1000.0,
            "Fixation_Duration_Max_ms": self.fix_duration_max_s * 1000.0,
            "Gap_Duration_ms": self.gap_duration_s * 1000.0,
            "Stim_Duration_ms": self.stim_duration_s * 1000.0,
            "Stim_Window_After_Stim_Off_ms": (
                self.stim_window_after_off_s * 1000.0
            ),
            "Stim_Hold_Time_ms": self.stim_hold_s * 1000.0,
        }

    def _wait_for_central_fixation(self, trial_data):
        candidate_start = None
        wait_start = self.now()
        pause_requested = False

        while self.now() - wait_start < self.wait_time_s:
            gaze, requested = self._present_frame(True, False)
            pause_requested = pause_requested or requested
            detected_at = self.now()

            if self._in_window(
                gaze, self.fix_x_px, self.fix_y_px, self.fix_radius_px
            ):
                if candidate_start is None:
                    candidate_start = detected_at
                elif detected_at - candidate_start >= self.fix_acquire_s:
                    trial_data["Time_GazeEnter"] = candidate_start
                    self._send_tracker_event(
                        f"GAZE_ACQUIRED TRIAL {trial_data['Trial']}"
                    )
                    return candidate_start, pause_requested
            else:
                candidate_start = None

        return None, pause_requested

    def _hold_central_fixation(
        self, trial_data, fixation_start, fixation_duration_s
    ):
        pause_requested = False

        while True:
            elapsed = self.now() - fixation_start
            if elapsed >= fixation_duration_s:
                self._schedule_flip_time(trial_data, "Time_FixationPointOff")
                gaze, requested = self._present_frame(
                    False,
                    False,
                    False,
                    True,
                )
                pause_requested = pause_requested or requested
                if not self._in_window(
                    gaze, self.fix_x_px, self.fix_y_px, self.fix_radius_px
                ):
                    return "Break_1", pause_requested
                return "Gap", pause_requested

            gaze, requested = self._present_frame(True, False)
            pause_requested = pause_requested or requested
            if not self._in_window(
                gaze, self.fix_x_px, self.fix_y_px, self.fix_radius_px
            ):
                return "Break_1", pause_requested

    def _run_gap(self, trial_data):
        pause_requested = False
        fixation_off = trial_data["Time_FixationPointOff"]

        while self.now() - fixation_off < self.gap_duration_s:
            gaze, requested = self._present_frame(
                False,
                False,
                False,
                True,
            )
            pause_requested = pause_requested or requested
            if not self._in_window(
                gaze, self.fix_x_px, self.fix_y_px, self.fix_radius_px
            ):
                return "Break_Gap", pause_requested

        return "Response", pause_requested

    def _run_response(self, trial_data):
        target_hold_start = None
        ever_entered = False
        success_locked = False
        pause_requested = False

        while True:
            stim_on = trial_data["Time_StimOn"]
            if stim_on is None:
                self._schedule_flip_time(trial_data, "Time_StimOn")
                _, requested = self._present_frame(
                    False,
                    True,
                    True,
                    False,
                )
                pause_requested = pause_requested or requested
                continue

            elapsed = self.now() - stim_on
            response_duration_s = (
                self.stim_duration_s + self.stim_window_after_off_s
            )
            if elapsed >= response_duration_s:
                if ever_entered:
                    return "Break_2", pause_requested
                return "nofix_2", pause_requested

            stim_visible = elapsed < self.stim_duration_s
            if (
                not stim_visible
                and trial_data["Time_StimOff"] is None
            ):
                self._schedule_flip_time(trial_data, "Time_StimOff")

            gaze, requested = self._present_frame(
                False,
                stim_visible,
                True,
                False,
            )
            pause_requested = pause_requested or requested
            detected_at = self.now()

            if self._in_window(
                gaze, self.stim_x_px, self.stim_y_px, self.stim_radius_px
            ):
                if not ever_entered:
                    ever_entered = True
                    trial_data["Time_StimWindowEnter"] = detected_at
                    self._send_tracker_event(
                        f"TARGET_ENTER TRIAL {trial_data['Trial']}"
                    )
                if target_hold_start is None:
                    target_hold_start = detected_at
                elif detected_at - target_hold_start >= self.stim_hold_s:
                    success_locked = True
            elif not success_locked:
                target_hold_start = None

            # Preserve the configured stimulus duration even when the target
            # hold is completed early. Reward follows the scheduled offset.
            if (
                success_locked
                and detected_at - stim_on >= self.stim_duration_s
            ):
                return "Success", pause_requested

    def _run_one_trial(self, trial_number):
        fixation_duration_s = random.uniform(
            self.fix_duration_min_s,
            self.fix_duration_max_s,
        )
        trial_data = self._new_trial_data(
            trial_number,
            fixation_duration_s,
        )
        event.clearEvents()
        self.gaze_renderer.reset_trail()
        self._send_tracker_event(f"TRIALID {trial_number}")
        self._send_trial_start_metadata(trial_data)

        self.arduino.trial_start()
        trial_data["Time_TrialStart"] = self.now()
        self._schedule_flip_time(trial_data, "Time_DrawFinish")
        _, pause_requested = self._present_frame(True, False)

        fixation_start, requested = self._wait_for_central_fixation(trial_data)
        pause_requested = pause_requested or requested

        if fixation_start is None:
            status = "nofix_1"
        else:
            status, requested = self._hold_central_fixation(
                trial_data,
                fixation_start,
                fixation_duration_s,
            )
            pause_requested = pause_requested or requested
            if status == "Gap":
                status, requested = self._run_gap(trial_data)
                pause_requested = pause_requested or requested
            if status == "Response":
                status, requested = self._run_response(trial_data)
                pause_requested = pause_requested or requested

        # Every outcome ends the visual trial immediately. This also records
        # the actual stimulus-off flip before reward delivery or timeout.
        self._black_out(trial_data)

        if self._trial_should_reward(status, trial_data):
            self.arduino.trial_success()
            trial_data["Time_Reward"] = self.now()
            self._send_tracker_event(f"REWARD TRIAL {trial_number}")
            self.arduino.reward(int(self.reward_len_s * 1000.0))
        elif status in ("Break_1", "Break_Gap", "Break_2"):
            self.arduino.trial_break()
            core.wait(self.timeout_s)
        else:
            self.arduino.trial_nofix()

        self.arduino.trial_end()
        trial_data["Status"] = self._trial_status_for_log(
            status,
            trial_data,
        )
        trial_data["Time_End"] = self.now()
        self._send_tracker_event(
            f"!V TRIAL_VAR Status {trial_data['Status']}"
        )
        self._send_tracker_event(
            f"!V TRIAL_VAR Subject_ID {trial_data['Subject_ID']}"
        )
        self._send_tracker_event(
            f"TRIAL_RESULT {trial_data['Status']}"
        )
        return trial_data, pause_requested

    def _trial_should_reward(self, status, trial_data):
        """Return whether the completed trial should deliver reward."""
        return status == "Success"

    def _trial_status_for_log(self, status, trial_data):
        """Return the status string written to the behavior log."""
        return status

    def _write_trial(self, trial_data):
        csv_row = trial_data.copy()
        for field in TIME_FIELDS:
            if csv_row[field] is not None:
                csv_row[field] = f"{float(csv_row[field]):.6f}"
        self.behavior_log.append(trial_data.copy())
        self.trial_logger.write(csv_row)

    def _run_iti(self):
        iti_start = self.now()
        while self.now() - iti_start < self.iti_s:
            _, pause_requested = self._present_frame(False, False)
            if pause_requested:
                return True
        return False

    def run_task(self):
        if not self.task_manager.prompt_for_parameters():
            raise TaskAbort()
        self.update_params()
        event.clearEvents()

        print("\n=== Saccade Task started ===")
        print("Press Esc to quit; press N to edit parameters before the next trial.")

        trial_number = 1
        success_count = 0
        pause_requested = False

        while True:
            if pause_requested:
                self._present_frame(False, False)
                if not self.task_manager.prompt_for_parameters():
                    raise TaskAbort()
                self.update_params()
                event.clearEvents()
                pause_requested = False

            if self._run_iti():
                pause_requested = True
                continue

            print(f"\n--- Trial {trial_number} ---")
            trial_data, requested = self._run_one_trial(trial_number)
            self._write_trial(trial_data)
            pause_requested = pause_requested or requested

            if trial_data["Status"] == "Success":
                success_count += 1
            recent_trials = self.behavior_log[-40:]
            recent_success_count = sum(
                trial["Status"] == "Success" for trial in recent_trials
            )
            print(
                f"Result: {trial_data['Status']} "
                f"(success {success_count}/{trial_number})"
            )
            print(
                f"总体成功率: {success_count / trial_number:.1%} "
                f"({success_count}/{trial_number})"
            )
            print(
                f"最近40个 trial 的成功率: "
                f"{recent_success_count / len(recent_trials):.1%} "
                f"({recent_success_count}/{len(recent_trials)})"
            )
            trial_number += 1

    def close(self):
        self.trial_logger.close()
        self.arduino.close()


def _create_session_dir(script_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(script_dir, "experiment_logs", f"Saccade_{timestamp}")
    candidate = base
    suffix = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{suffix:03d}"
        suffix += 1
    os.makedirs(candidate)
    return timestamp, candidate


def main(tracker_mode="qy"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    session_timestamp, save_dir = _create_session_dir(script_dir)
    session_t0 = time.perf_counter()

    save_gaze_csv = str(tracker_mode).lower() != "eyelink"
    gaze_log_queue = Queue(maxsize=20000) if save_gaze_csv else None
    dropped_samples = Value("i", 0)
    gaze_writer = None
    if save_gaze_csv:
        gaze_log_path = os.path.join(
            save_dir, f"Saccade_eye_log_{session_timestamp}.csv"
        )
        gaze_writer = GazeCsvWriter(gaze_log_queue, gaze_log_path)
        gaze_writer.start()

    tracker_runtime = None
    win_subject = None
    win_control = None
    task = None

    try:
        tracker_runtime = create_tracker_runtime(
            tracker_mode,
            is_simulating=bool(IS_SIMULATING),
            session_id=f"Saccade_{session_timestamp}",
            save_dir=save_dir,
            session_t0=session_t0,
            screen_size=(1920, 1080),
            qy_sample_rate=EYE_TRACKER_RATE_HZ,
            gaze_log_queue=gaze_log_queue,
            dropped_samples=dropped_samples,
        )
        gaze_source = tracker_runtime.gaze_source

        win_subject = visual.Window(
            screen=MONITOR_ID_SUBJECT,
            size=[1920, 1080],
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
            title=f"Saccade Control View ({tracker_runtime.mode})",
        )

        task_manager = FineVision_Notebook(
            task_name="SaccadeTask",
            default_params=DEFAULT_PARAMS,
            parameter_groups=SACCADE_PARAMETER_GROUPS,
            parameter_validator=_validate_params,
        )
        task = SaccadeTask(
            win_subject,
            win_control,
            gaze_source,
            task_manager,
            IS_SIMULATING,
            session_t0,
            save_dir,
            session_timestamp,
            tracker_runtime,
        )
        print(f"[Session] Tracker: {tracker_runtime.mode}")
        print(f"[Session] Logs: {save_dir}")
        task.run_task()

    except (TaskAbort, SystemExit):
        print("Saccade task stopped by user.")
    except Exception as exc:
        print(f"Saccade task error: {exc}")
        traceback.print_exc()
    finally:
        if task is not None:
            try:
                task.close()
            except Exception:
                traceback.print_exc()

        if tracker_runtime is not None:
            try:
                tracker_runtime.close()
            except Exception:
                traceback.print_exc()

        if gaze_writer is not None:
            try:
                gaze_log_queue.put(STOP_TOKEN, timeout=2)
            except Full:
                print("[Warning] Gaze log queue was full during shutdown.")
            gaze_writer.join(timeout=10)
            if gaze_writer.is_alive():
                gaze_writer.terminate()
                gaze_writer.join(timeout=2)

            if gaze_writer.exitcode == 0:
                gaze_log_queue.close()
                gaze_log_queue.join_thread()
            else:
                gaze_log_queue.cancel_join_thread()
                gaze_log_queue.close()

            if gaze_writer.exitcode not in (0, None):
                print(
                    f"[Warning] Gaze CSV writer exited with code "
                    f"{gaze_writer.exitcode}."
                )

        if dropped_samples.value:
            print(
                f"[Warning] Dropped {dropped_samples.value} gaze samples "
                "because the logging queue was full."
            )
        if win_subject is not None:
            win_subject.close()
        if win_control is not None:
            win_control.close()
        print(f"[Session] Data saved in: {save_dir}")


if __name__ == "__main__":
    freeze_support()
    main()
