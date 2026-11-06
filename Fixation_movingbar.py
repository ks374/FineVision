"""Fixation training task with moving bars in the lower-right visual field."""

import csv
import json
import math
import os
import random
import time
import traceback
from datetime import datetime, timezone
from multiprocessing import Queue, Value, freeze_support
from queue import Full

from psychopy import core, event, visual

from EyeDataLogger import GazeCsvWriter, STOP_TOKEN
from FineVision_Notebook import FineVision_Notebook
from FineVision_Util import ArduinoController
from GazeTrackerRenderer import GazeTrackerRenderer
from eyetracker import create_tracker_runtime
from FramePulse import DisplaySync
from SessionNaming import confirm_session_parameters, subject_filename


IS_SIMULATING = 0
MONITOR_ID_SUBJECT = 1
MONITOR_ID_CONTROL = 0
EYE_TRACKER_RATE_HZ = 100

DIRECTIONS = ("Right", "Left", "Down", "Up")
RANGES_DEG = (4.0, 20.0)


DEFAULT_PARAMS = {
    "Subject ID": "Monkey_H18",
    "Wait Time (s)": 10.0,
    "Fixation Acquire Time (ms)": 150,
    "Fix Window Radius (pix)": 500,
    "Bar On After Fixation Start (ms)": 500,
    "Bar Motion Duration (s)": 1.0,
    "Bar Width for 4deg (deg)": "[0.04, 0.2]",
    "Bar Width for 20deg (deg)": "[0.04, 0.2]",
    "Total Blocks": 10,
    "Fixation Diameter (deg)": 0.2,
    "Fixation X (deg)": 0.0,
    "Fixation Y (deg)": 0.0,
    "Bar Opacity (0-1)": 1.0,
    "Viewing Distance (cm)": 55.0,
    "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Reward Length (s)": 0.2,
    "ITI (s)": 5.0,
    "Timeout (s)": 2.5,
    "Random Seed (0=random)": 0,
}


TRIAL_LOG_FIELDS = [
    "Trial",
    "Block",
    "Trial_In_Block",
    "Status",
    "Break_Phase",
    "Time_TrialStart",
    "Time_DrawFinish",
    "Time_GazeEnter",
    "Time_BarOn",
    "Time_BarOff",
    "Time_FixationPointOff",
    "Time_Reward",
    "Time_End",
    "Subject_ID",
    "Fixation_Position",
    "Fix_Window_Radius",
    "Wait_Time_s",
    "Fixation_Acquire_Time_ms",
    "Bar_On_After_Fixation_Start_ms",
    "Direction",
    "Range_deg",
    "Bar_Length_deg",
    "Bar_Width_deg",
    "Bar_Opacity",
    "Bar_Motion_Duration_s",
    "Bar_Start_X_pix",
    "Bar_Start_Y_pix",
    "Bar_End_X_pix",
    "Bar_End_Y_pix",
    "Scan_X_Min_pix",
    "Scan_X_Max_pix",
    "Scan_Y_Bottom_pix",
    "Scan_Y_Top_pix",
    "Viewing_Distance_cm",
    "Monitor_Width_cm",
    "Monitor_Height_cm",
    "Reward_Length_s",
    "ITI_s",
    "Timeout_s",
    "Random_Seed",
]

TIME_FIELDS = [
    "Time_TrialStart",
    "Time_DrawFinish",
    "Time_GazeEnter",
    "Time_BarOn",
    "Time_BarOff",
    "Time_FixationPointOff",
    "Time_Reward",
    "Time_End",
]

SYNC_TIME_FIELDS = ["Time_FixAcquired", "Time_Break", "Time_NoFix", "Time_Success",
                    "Time_OutcomePDOn", "Time_OutcomePDOff", "Time_PDOn", "Time_PDOff"]
TIME_FIELDS.extend(SYNC_TIME_FIELDS)
TRIAL_LOG_FIELDS.extend(SYNC_TIME_FIELDS + ["Session_T0_PerfCounter",
    "Session_T0_UTC", "Parameters_JSON"])


class TaskAbort(Exception):
    """Raised when Escape is pressed."""


class TrialCsvLogger:
    """Append and flush one row at the end of every trial."""

    def __init__(self, csv_path):
        self._file = open(csv_path, "w", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(self._file, fieldnames=TRIAL_LOG_FIELDS)
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
    return 2.0 * viewing_distance_cm * math.tan(math.radians(angle_deg) / 2.0)


def visual_angle_to_pixels(
    angle_deg, viewing_distance_cm, monitor_size_cm, resolution_pixels
):
    return (
        visual_angle_to_cm(angle_deg, viewing_distance_cm)
        * resolution_pixels
        / monitor_size_cm
    )


def parse_widths(value):
    """Accept a scalar or a JSON array; keep the editor field as free text."""
    if isinstance(value, str):
        value = json.loads(value)
    values = value if isinstance(value, (list, tuple)) else [value]
    if not values or any(isinstance(v, bool) or not isinstance(v, (int, float))
                         or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Bar widths must be positive finite numbers, e.g. [0.04, 0.2].')
    if len(set(values)) != len(values):
        raise ValueError('Bar widths must not contain duplicates.')
    return [float(v) for v in values]


def make_condition_block(rng, widths_by_range=None):
    """Each range/width/direction combination occurs exactly once."""
    if widths_by_range is None:
        widths_by_range = {r: parse_widths(DEFAULT_PARAMS[f"Bar Width for {r:g}deg (deg)"])
                           for r in RANGES_DEG}
    conditions = [
        {"direction": direction, "range_deg": range_deg, "bar_width_deg": width}
        for range_deg in RANGES_DEG
        for width in widths_by_range[range_deg]
        for direction in DIRECTIONS
    ]
    rng.shuffle(conditions)
    return conditions


def calculate_scan_geometry(
    direction,
    range_deg,
    bar_width_deg,
    viewing_distance_cm,
    monitor_width_cm,
    monitor_height_cm,
    screen_width_px,
    screen_height_px,
    fixation_pos=(0.0, 0.0),
):
    """
    Build a fixation-relative aperture, shifted 10% along the motion axis.
    Endpoints describe bar centers, independent of thickness. Off-screen
    portions are clipped by the display; never reposition the requested scan.
    """
    x_span = visual_angle_to_pixels(
        range_deg, viewing_distance_cm, monitor_width_cm, screen_width_px
    )
    y_span = visual_angle_to_pixels(
        range_deg, viewing_distance_cm, monitor_height_cm, screen_height_px
    )
    thickness_x = visual_angle_to_pixels(
        bar_width_deg,
        viewing_distance_cm,
        monitor_width_cm,
        screen_width_px,
    )
    thickness_y = visual_angle_to_pixels(
        bar_width_deg,
        viewing_distance_cm,
        monitor_height_cm,
        screen_height_px,
    )

    # Shift only the motion axis by 10%; PsychoPy uses positive Y upward.
    fx, fy = fixation_pos
    horizontal = direction in ("Right", "Left")
    x_min = fx - (0.1 * x_span if horizontal else 0.0)
    x_max = x_min + x_span
    y_top = fy + (0.0 if horizontal else 0.1 * y_span)
    y_bottom = y_top - y_span

    center_x = (x_min + x_max) / 2.0
    center_y = (y_bottom + y_top) / 2.0

    if direction == "Right":
        bar_size = (thickness_x, y_span)
        start_pos = (x_min, center_y)
        end_pos = (x_max, center_y)
    elif direction == "Left":
        bar_size = (thickness_x, y_span)
        start_pos = (x_max, center_y)
        end_pos = (x_min, center_y)
    elif direction == "Down":
        bar_size = (x_span, thickness_y)
        start_pos = (center_x, y_top)
        end_pos = (center_x, y_bottom)
    elif direction == "Up":
        bar_size = (x_span, thickness_y)
        start_pos = (center_x, y_bottom)
        end_pos = (center_x, y_top)
    else:
        raise ValueError(f"Unknown direction: {direction}")

    return {
        "bar_width_px": bar_size[0],
        "bar_height_px": bar_size[1],
        "start_x": start_pos[0],
        "start_y": start_pos[1],
        "end_x": end_pos[0],
        "end_y": end_pos[1],
        "x_min": x_min,
        "x_max": x_max,
        "y_bottom": y_bottom,
        "y_top": y_top,
        "x_span": x_span,
        "y_span": y_span,
    }


def validate_params(params):
    positive_fields = [
        "Wait Time (s)",
        "Fixation Acquire Time (ms)",
        "Fix Window Radius (pix)",
        "Bar Motion Duration (s)",
        "Fixation Diameter (deg)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
        "Reward Length (s)",
        "ITI (s)",
    ]
    for field in positive_fields:
        if not math.isfinite(float(params[field])) or float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")
    if float(params["Bar On After Fixation Start (ms)"]) < 0:
        raise ValueError("Bar On After Fixation Start (ms) cannot be negative.")
    if float(params["Timeout (s)"]) < 0:
        raise ValueError("Timeout (s) cannot be negative.")
    opacity = float(params["Bar Opacity (0-1)"])
    if not 0.0 <= opacity <= 1.0:
        raise ValueError("Bar Opacity (0-1) must be between 0 and 1.")
    for r in RANGES_DEG:
        parse_widths(params[f"Bar Width for {r:g}deg (deg)"])
    blocks = float(params['Total Blocks'])
    if not math.isfinite(blocks) or blocks < 1 or not blocks.is_integer():
        raise ValueError('Total Blocks must be a positive integer.')
    for key in ('Fixation X (deg)', 'Fixation Y (deg)'):
        if not math.isfinite(float(params[key])):
            raise ValueError(f'{key} must be finite.')


def parameter_summary(params):
    validate_params(params)
    count = 4 * sum(len(parse_widths(params[f'Bar Width for {r:g}deg (deg)'])) for r in RANGES_DEG)
    return f'{count} conditions/block x {int(float(params["Total Blocks"]))} blocks = {count * int(float(params["Total Blocks"]))} successful trials; failures repeat.'


class FixationMovingBarTask:
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
        gaze_log_queue,
        dropped_samples,
        tracker_backend=None,
        session_utc=None,
    ):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.task_manager = task_manager
        self.is_simulating = is_simulating
        self.session_t0 = float(session_t0)
        self.save_dir = save_dir
        self.session_timestamp = session_timestamp
        self.gaze_log_queue = gaze_log_queue
        self.dropped_samples = dropped_samples
        self.tracker_backend = tracker_backend
        self.session_utc = session_utc
        self.current_trial = None
        self.pulse = DisplaySync()
        self.events, self.frames = [], []
        self.quit_requested = False
        self._finishing_code = False
        self._previous_flip = None
        self._flip_session_time = None
        self._pending_marks = []
        self.nominal_period = float(win_sub.monitorFramePeriod)
        self.pd = visual.Rect(win_sub, width=160, height=160, units="pix",
            pos=(win_sub.size[0] / 2 - 90, -win_sub.size[1] / 2 + 90),
            colorSpace="rgb255", fillColor=(0, 0, 0), lineColor=(0, 0, 0), autoLog=False)
        self._last_sim_gaze_log_time = -math.inf

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
        self._configured_seed = None
        self.random_seed = None
        self.rng = None

        task_log_path = os.path.join(
            save_dir,
            f"Fixation_movingbar_task_log_{session_timestamp}.csv",
        )
        self.trial_logger = TrialCsvLogger(task_log_path)

    def now(self):
        return time.perf_counter() - self.session_t0

    def update_params(self):
        params = self.task_manager.exp_params
        validate_params(params)

        self.subject_id = str(params["Subject ID"])
        self.wait_time_s = float(params["Wait Time (s)"])
        self.fix_acquire_s = float(params["Fixation Acquire Time (ms)"]) / 1000.0
        self.fix_radius = float(params["Fix Window Radius (pix)"])
        self.bar_on_delay_s = (
            float(params["Bar On After Fixation Start (ms)"]) / 1000.0
        )
        self.bar_duration_s = float(params["Bar Motion Duration (s)"])
        self.bar_width_by_range = {
            r: parse_widths(params[f"Bar Width for {r:g}deg (deg)"])
            for r in RANGES_DEG
        }
        self.total_blocks = int(float(params['Total Blocks']))
        self.bar_opacity = float(params["Bar Opacity (0-1)"])
        self.viewing_distance_cm = float(params["Viewing Distance (cm)"])
        self.monitor_width_cm = float(params["Subject Monitor Width (cm)"])
        self.monitor_height_cm = float(params["Subject Monitor Height (cm)"])
        self.fixation_pos = (
            visual_angle_to_pixels(float(params['Fixation X (deg)']), self.viewing_distance_cm,
                                   self.monitor_width_cm, self.win_sub.size[0]),
            visual_angle_to_pixels(float(params['Fixation Y (deg)']), self.viewing_distance_cm,
                                   self.monitor_height_cm, self.win_sub.size[1]),
        )
        self.fixation_diameter_px = visual_angle_to_pixels(
            float(params['Fixation Diameter (deg)']), self.viewing_distance_cm,
            self.monitor_width_cm, self.win_sub.size[0])
        self.reward_len_s = float(params["Reward Length (s)"])
        self.iti_s = float(params["ITI (s)"])
        self.timeout_s = float(params["Timeout (s)"])

        configured_seed = int(float(params["Random Seed (0=random)"]))
        if self.rng is None or configured_seed != self._configured_seed:
            self._configured_seed = configured_seed
            self.random_seed = (
                configured_seed
                if configured_seed != 0
                else int(time.time_ns() & 0xFFFFFFFF)
            )
            self.rng = random.Random(self.random_seed)

        self._build_static_visuals()
        # Validate both angular ranges immediately, before the first trial.
        for range_deg in RANGES_DEG:
            calculate_scan_geometry(
                "Right",
                range_deg,
                self.bar_width_by_range[range_deg][0],
                self.viewing_distance_cm,
                self.monitor_width_cm,
                self.monitor_height_cm,
                self.win_sub.size[0],
                self.win_sub.size[1],
                self.fixation_pos,
            )

    def _build_static_visuals(self):
        self.fix_sub = visual.Circle(
            self.win_sub,
            radius=self.fixation_diameter_px / 2,
            fillColor="white",
            lineColor="white",
            pos=self.fixation_pos,
        )
        self.fix_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fixation_diameter_px / 2 * self.scale_x,
            fillColor="green",
            lineColor="green",
            pos=(self.fixation_pos[0] * self.scale_x, self.fixation_pos[1] * self.scale_y),
        )
        self.fix_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fix_radius * self.scale_x,
            fillColor=None,
            lineColor="red",
            lineWidth=2,
            pos=(self.fixation_pos[0] * self.scale_x, self.fixation_pos[1] * self.scale_y),
        )

    def _prepare_bar(self, condition):
        range_deg = float(condition["range_deg"])
        direction = condition["direction"]
        bar_width_deg = condition.get("bar_width_deg", self.bar_width_by_range[range_deg][0])
        geometry = calculate_scan_geometry(
            direction,
            range_deg,
            bar_width_deg,
            self.viewing_distance_cm,
            self.monitor_width_cm,
            self.monitor_height_cm,
            self.win_sub.size[0],
            self.win_sub.size[1],
            self.fixation_pos,
        )

        self.bar_sub = visual.Rect(
            self.win_sub,
            width=geometry["bar_width_px"],
            height=geometry["bar_height_px"],
            fillColor="white",
            lineColor=None,
            opacity=self.bar_opacity,
            pos=(geometry["start_x"], geometry["start_y"]),
        )
        self.bar_ctl = visual.Rect(
            self.win_ctl,
            width=geometry["bar_width_px"] * self.scale_x,
            height=geometry["bar_height_px"] * self.scale_y,
            fillColor="white",
            lineColor=None,
            opacity=self.bar_opacity,
            pos=(
                geometry["start_x"] * self.scale_x,
                geometry["start_y"] * self.scale_y,
            ),
        )
        self.scan_window_ctl = visual.Rect(
            self.win_ctl,
            width=geometry["x_span"] * self.scale_x,
            height=geometry["y_span"] * self.scale_y,
            fillColor=None,
            lineColor="cyan",
            lineWidth=2,
            pos=(
                (geometry["x_min"] + geometry["x_max"])
                / 2.0
                * self.scale_x,
                (geometry["y_bottom"] + geometry["y_top"])
                / 2.0
                * self.scale_y,
            ),
        )
        return geometry

    def _set_bar_progress(self, geometry, progress):
        progress = max(0.0, min(1.0, progress))
        x = geometry["start_x"] + (
            geometry["end_x"] - geometry["start_x"]
        ) * progress
        y = geometry["start_y"] + (
            geometry["end_y"] - geometry["start_y"]
        ) * progress
        self.bar_sub.pos = (x, y)
        self.bar_ctl.pos = (x * self.scale_x, y * self.scale_y)

    def _mark_time(self, trial_data, field):
        if trial_data[field] is None:
            trial_data[field] = self._flip_session_time
            if field == "Time_DrawFinish":
                trial_data["Time_TrialStart"] = trial_data[field]
            tracker_event = {
                "Time_DrawFinish": "FIX_ON",
                "Time_BarOn": "BAR_ON",
                "Time_BarOff": "BAR_OFF",
                "Time_FixationPointOff": "FIX_OFF",
            }.get(field)
            if tracker_event is not None:
                self._send_tracker_event(
                    f"{tracker_event} TRIAL {trial_data['Trial']}", trial_data[field]
                )

    def _send_tracker_event(self, message, at=None):
        at = self.now() if at is None else at
        self.events.append({"event": message, "time": at})
        if self.tracker_backend is not None:
            # Data Viewer variables must retain their exact values.
            self.tracker_backend.send_event(message if message.startswith("!V ")
                else f"{message} SESSION_TIME {at:.9f}")

    def _schedule_flip_time(self, trial_data, field):
        if trial_data[field] is None:
            self._pending_marks.append((trial_data, field))

    def _poll_commands(self):
        keys = event.getKeys()
        if "escape" in keys:
            self.quit_requested = True
        if self.quit_requested and not self._finishing_code:
            raise TaskAbort()
        return "n" in keys

    def _gaze_in_fixation(self, gaze):
        return bool(gaze["valid"]) and math.hypot(gaze["x"] - self.fixation_pos[0], gaze["y"] - self.fixation_pos[1]) <= (
            self.fix_radius
        )

    def _log_simulated_gaze(self, gaze):
        if not self.is_simulating or self.gaze_log_queue is None:
            return
        sample_time = self.now()
        if sample_time - self._last_sim_gaze_log_time < 1.0 / EYE_TRACKER_RATE_HZ:
            return
        gaze_x = gaze["x"] if gaze["valid"] else -999.0
        gaze_y = gaze["y"] if gaze["valid"] else -999.0
        try:
            self.gaze_log_queue.put_nowait((sample_time, gaze_x, gaze_y))
            self._last_sim_gaze_log_time = sample_time
        except Full:
            with self.dropped_samples.get_lock():
                self.dropped_samples.value += 1

    def _on_flip(self, marks, edge, label):
        self._flip_session_time = self.now()
        for trial_data, field in marks:
            self._mark_time(trial_data, field)
        if edge:
            trial = self.current_trial["Trial"] if self.current_trial else 0
            self._send_tracker_event(f"PD_{label}_{edge} TRIAL {trial}", self._flip_session_time)
            if self.current_trial and label == "BAR":
                field = "Time_PDOn" if edge == "ON" else "Time_PDOff"
                self.current_trial[field] = self._flip_session_time

    def _read_gaze(self):
        gaze = self.gaze_renderer.update()
        self._log_simulated_gaze(gaze)
        return gaze

    def _present_frame(self, fix_visible, bar_visible, gaze=None):
        if gaze is None:
            gaze = self._read_gaze()
        if fix_visible:
            self.fix_sub.draw()
            self.fix_ctl.draw()
            self.fix_window_ctl.draw()
        if bar_visible:
            self.bar_sub.draw()
            self.bar_ctl.draw()
            self.scan_window_ctl.draw()

        self.gaze_renderer.draw()
        white, edge, label = self.pulse.next_frame(bar_visible, "BAR")
        self.pd.fillColor = self.pd.lineColor = (255, 255, 255) if white else (0, 0, 0)
        self.pd.draw()  # Draw last: stimulus motion must never contaminate the code.
        marks, self._pending_marks = self._pending_marks, []
        self.win_sub.callOnFlip(self._on_flip, marks, edge, label)
        flip = self.win_sub.flip()
        interval = None if self._previous_flip is None else flip - self._previous_flip
        self.frames.append({"frame": len(self.frames), "session_time": self._flip_session_time,
            "flip_clock_time": flip, "interval_s": interval, "pd_white": white,
            "pd_code": label, "trial": self.current_trial["Trial"] if self.current_trial else 0,
            "bar_visible": bar_visible,
            "bar_pos": list(self.bar_sub.pos) if bar_visible else None,
            "late": interval is not None and interval > 1.5 * self.nominal_period})
        self._previous_flip = flip
        self.win_ctl.flip()
        pause_requested = self._poll_commands()
        return gaze, pause_requested

    def _decision(self, trial_data, status, phase=""):
        at = self.now()
        trial_data["Status"] = status
        trial_data["Break_Phase"] = phase
        trial_data["Time_End"] = at
        trial_data[{"Break": "Time_Break", "NoFix": "Time_NoFix",
                    "Success": "Time_Success"}[status]] = at
        self._send_tracker_event(f"{status.upper()} TRIAL {trial_data['Trial']}", at)

    def _finish_code(self, trial_data=None, duration=0):
        start = self.now()
        previous = self._finishing_code
        self._finishing_code = True
        try:
            while self.pulse.busy or (not self.quit_requested and self.now() - start < duration):
                if trial_data is None:
                    self._present_frame(False, False)
                else:
                    self._black_out(trial_data)
        finally:
            self._finishing_code = previous

    def _black_out(self, trial_data):
        if trial_data["Time_DrawFinish"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_BarOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_BarOff")
        self._present_frame(False, False)

    def _wait_for_fixation(self, trial_data):
        candidate_start = None
        wait_start = trial_data["Time_DrawFinish"]
        pause_requested = False

        while self.now() - wait_start < self.wait_time_s:
            gaze = self._read_gaze()
            detected_at = self.now()
            if self._gaze_in_fixation(gaze):
                if candidate_start is None:
                    candidate_start = detected_at
                elif detected_at - candidate_start >= self.fix_acquire_s:
                    trial_data["Time_GazeEnter"] = candidate_start
                    trial_data["Time_FixAcquired"] = detected_at
                    self._send_tracker_event(
                        f"FIX_ACQUIRED TRIAL {trial_data['Trial']}", detected_at
                    )
                    return candidate_start, pause_requested
            else:
                candidate_start = None
            _, requested = self._present_frame(True, False, gaze)
            pause_requested = pause_requested or requested
        self._decision(trial_data, "NoFix", "Acquire")
        return None, pause_requested

    def _hold_before_bar(self, fixation_start):
        pause_requested = False
        while self.now() - fixation_start < self.bar_on_delay_s:
            gaze = self._read_gaze()
            if not self._gaze_in_fixation(gaze):
                self._decision(self.current_trial, "Break", "PreBar")
                return False, pause_requested
            _, requested = self._present_frame(True, False, gaze)
            pause_requested = pause_requested or requested
        return True, pause_requested

    def _run_bar_motion(self, trial_data, geometry):
        pause_requested = False
        self._set_bar_progress(geometry, 0.0)
        gaze = self._read_gaze()
        if not self._gaze_in_fixation(gaze):
            self._decision(trial_data, "Break", "PreBar")
            return False, pause_requested
        self._schedule_flip_time(trial_data, "Time_BarOn")
        _, requested = self._present_frame(True, True, gaze)
        pause_requested = pause_requested or requested

        bar_on_time = trial_data["Time_BarOn"]
        while self.now() - bar_on_time < self.bar_duration_s:
            gaze = self._read_gaze()
            if not self._gaze_in_fixation(gaze):
                self._decision(trial_data, "Break", "BarMotion")
                return False, pause_requested
            progress = (self.now() - bar_on_time) / self.bar_duration_s
            self._set_bar_progress(geometry, progress)
            _, requested = self._present_frame(True, True, gaze)
            pause_requested = pause_requested or requested
        if not self._gaze_in_fixation(self._read_gaze()):
            self._decision(trial_data, "Break", "BarMotion")
            return False, pause_requested
        self._decision(trial_data, "Success")
        return True, pause_requested

    def _new_trial_data(
        self, trial_number, block_number, trial_in_block, condition, geometry
    ):
        range_deg = float(condition["range_deg"])
        return {
            "Trial": trial_number,
            "Block": block_number,
            "Trial_In_Block": trial_in_block,
            "Status": None,
            "Break_Phase": "",
            "Time_TrialStart": None,
            "Time_DrawFinish": None,
            "Time_GazeEnter": None,
            "Time_BarOn": None,
            "Time_BarOff": None,
            "Time_FixationPointOff": None,
            "Time_Reward": None,
            "Time_End": None,
            "Subject_ID": self.subject_id,
            "Fixation_Position": str(self.fixation_pos),
            "Fix_Window_Radius": self.fix_radius,
            "Wait_Time_s": self.wait_time_s,
            "Fixation_Acquire_Time_ms": self.fix_acquire_s * 1000.0,
            "Bar_On_After_Fixation_Start_ms": self.bar_on_delay_s
            * 1000.0,
            "Direction": condition["direction"],
            "Range_deg": range_deg,
            "Bar_Length_deg": range_deg,
            "Bar_Width_deg": condition.get("bar_width_deg", self.bar_width_by_range[range_deg][0]),
            "Bar_Opacity": self.bar_opacity,
            "Bar_Motion_Duration_s": self.bar_duration_s,
            "Bar_Start_X_pix": geometry["start_x"],
            "Bar_Start_Y_pix": geometry["start_y"],
            "Bar_End_X_pix": geometry["end_x"],
            "Bar_End_Y_pix": geometry["end_y"],
            "Scan_X_Min_pix": geometry["x_min"],
            "Scan_X_Max_pix": geometry["x_max"],
            "Scan_Y_Bottom_pix": geometry["y_bottom"],
            "Scan_Y_Top_pix": geometry["y_top"],
            "Viewing_Distance_cm": self.viewing_distance_cm,
            "Monitor_Width_cm": self.monitor_width_cm,
            "Monitor_Height_cm": self.monitor_height_cm,
            "Reward_Length_s": self.reward_len_s,
            "ITI_s": self.iti_s,
            "Timeout_s": self.timeout_s,
            "Random_Seed": self.random_seed,
            **dict.fromkeys(SYNC_TIME_FIELDS),
            "Session_T0_PerfCounter": self.session_t0,
            "Session_T0_UTC": self.session_utc,
            "Parameters_JSON": json.dumps(self.task_manager.exp_params, ensure_ascii=False),
        }

    def _run_one_trial(
        self, trial_number, block_number, trial_in_block, condition
    ):
        try:
            return self._run_trial_body(trial_number, block_number, trial_in_block, condition)
        except TaskAbort:
            trial = self.current_trial
            if trial is not None:
                if trial["Status"] is None:
                    trial["Status"] = "Aborted"
                    trial["Time_End"] = self.now()
                    self._send_tracker_event(f"TRIAL_ABORT TRIAL {trial_number}", trial["Time_End"])
                self._finishing_code = True
                try:
                    self._black_out(trial)
                    self._finish_code(trial)
                finally:
                    self._finishing_code = False
                    self._write_trial(trial)
            raise

    def _run_trial_body(
        self, trial_number, block_number, trial_in_block, condition
    ):
        geometry = self._prepare_bar(condition)
        trial_data = self._new_trial_data(
            trial_number,
            block_number,
            trial_in_block,
            condition,
            geometry,
        )
        self.current_trial = trial_data
        event.clearEvents()
        self.gaze_renderer.reset_trail()
        self._send_tracker_event(f"TRIALID {trial_number}")

        self.arduino.trial_start()
        self._schedule_flip_time(trial_data, "Time_DrawFinish")
        _, pause_requested = self._present_frame(True, False)

        fixation_start, requested = self._wait_for_fixation(trial_data)
        pause_requested = pause_requested or requested
        if fixation_start is None:
            status = "NoFix"
            trial_data["Break_Phase"] = "Acquire"
        else:
            held, requested = self._hold_before_bar(fixation_start)
            pause_requested = pause_requested or requested
            if not held:
                status = "Break"
                trial_data["Break_Phase"] = "PreBar"
            else:
                completed, requested = self._run_bar_motion(
                    trial_data, geometry
                )
                pause_requested = pause_requested or requested
                if completed:
                    status = "Success"
                else:
                    status = "Break"

        self._send_tracker_event(f"TRIAL_RESULT {status}", trial_data["Time_End"])
        # Remove the bar and turn the photodiode black on the same subject flip,
        # before reward audio can block the main thread.
        self._finishing_code = True
        try:
            self._black_out(trial_data)
        finally:
            self._finishing_code = False
        self._finish_code(trial_data)

        if status == "Success":
            self.arduino.trial_success()
            trial_data["Time_Reward"] = self.now()
            self.arduino.reward(int(self.reward_len_s * 1000.0))
        elif status == "Break":
            self.arduino.trial_break()
        else:
            self.arduino.trial_nofix()

        self._finishing_code = True
        try:
            self._black_out(trial_data)
            self._finish_code(trial_data, self.timeout_s if status == "Break" else 0)
        finally:
            self._finishing_code = False

        self.arduino.trial_end()
        trial_data["Status"] = status
        self._send_tracker_event(f"!V TRIAL_VAR Status {status}")
        self._send_tracker_event(
            f"!V TRIAL_VAR Direction {trial_data['Direction']}"
        )
        self._send_tracker_event(
            f"!V TRIAL_VAR Range_deg {trial_data['Range_deg']}"
        )
        return trial_data, pause_requested

    def _write_trial(self, trial_data):
        csv_row = trial_data.copy()
        for field in TIME_FIELDS:
            if csv_row[field] is not None:
                csv_row[field] = f"{float(csv_row[field]):.6f}"
        for field, value in tuple(csv_row.items()):
            if isinstance(value, float) and field not in TIME_FIELDS:
                csv_row[field] = f"{value:.6f}"
        self.behavior_log.append(trial_data.copy())
        self.trial_logger.write(csv_row)
        self.current_trial = None

    def _run_iti(self):
        iti_start = self.now()
        while self.now() - iti_start < self.iti_s:
            _, pause_requested = self._present_frame(False, False)
            if pause_requested:
                return True
        return False

    def _prompt_and_update(self):
        self._present_frame(False, False)
        if self.task_manager.prompt_for_runtime_parameters(
            disabled_parameters={'Total Blocks', 'Bar Width for 4deg (deg)', 'Bar Width for 20deg (deg)'},
            notice='Block count and width conditions are fixed for this session.',
        ) != 'confirm':
            raise TaskAbort()
        self.update_params()
        event.clearEvents()
        self._previous_flip = None

    def run_task(self):
        if (not getattr(self.task_manager, "session_parameters_confirmed", False)
                and not self.task_manager.prompt_for_parameters()):
            raise TaskAbort()
        self.update_params()
        event.clearEvents()
        for _ in range(5):
            self._present_frame(False, False)
        self.pulse.start("TASK_START")
        self._finish_code()
        if self.quit_requested:
            raise TaskAbort()

        print("\n=== Fixation Moving-Bar Task started ===")
        print(parameter_summary(self.task_manager.exp_params))
        print("Press Esc to quit; press N to edit parameters before the next trial.")

        trial_number = 1
        block_number = 0
        success_count = 0
        pause_requested = False

        # Freeze the planned counts/widths for this session, including retries.
        planned_blocks = self.total_blocks
        planned_widths = {r: list(w) for r, w in self.bar_width_by_range.items()}
        while block_number < planned_blocks:
            block_number += 1
            block_conditions = make_condition_block(self.rng, planned_widths)
            print(f"\n=== Block {block_number} ===")

            trial_in_block = 1
            while trial_in_block <= len(block_conditions):
                condition = block_conditions[trial_in_block - 1]
                if pause_requested:
                    self._prompt_and_update()
                    pause_requested = False

                while self._run_iti():
                    self._prompt_and_update()

                print(
                    f"\n--- Trial {trial_number} "
                    f"(block {block_number}/{planned_blocks}, {trial_in_block}/{len(block_conditions)}): "
                    f"{condition['range_deg']:g}deg {condition['direction']} "
                    f"width={condition['bar_width_deg']:g}deg ---"
                )
                trial_data, requested = self._run_one_trial(
                    trial_number,
                    block_number,
                    trial_in_block,
                    condition,
                )
                self._write_trial(trial_data)
                if self.quit_requested:
                    raise TaskAbort()
                pause_requested = pause_requested or requested

                if trial_data["Status"] == "Success":
                    success_count += 1
                    trial_in_block += 1
                print(
                    f"Result: {trial_data['Status']} "
                    f"(success {success_count}/{trial_number})"
                )
                trial_number += 1
        print(f"Completed {planned_blocks} blocks: {success_count} successes in {trial_number - 1} attempts.")

    def close(self):
        try:
            if self.current_trial is not None:
                if self.current_trial["Status"] is None:
                    self.current_trial["Status"] = "Error"
                    self.current_trial["Time_End"] = self.now()
                self._write_trial(self.current_trial)
        finally:
            self.trial_logger.close()
            try:
                for name, rows in (("events.json", self.events), ("frames.json", self.frames)):
                    with open(os.path.join(self.save_dir, name), "w", encoding="utf-8") as stream:
                        json.dump(rows, stream, ensure_ascii=False, indent=2)
            finally:
                self.arduino.close()


def create_session_dir(script_dir, subject_id="Unknown"):
    timestamp = subject_filename(subject_id) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(
        script_dir, "experiment_logs", f"FixationMovingBar_{timestamp}"
    )
    candidate = base
    suffix = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{suffix:03d}"
        suffix += 1
    os.makedirs(candidate)
    return timestamp + candidate[len(base):], candidate


def main(tracker_mode="qy"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    task_manager = FineVision_Notebook(task_name="FixationMovingBar", default_params=DEFAULT_PARAMS,
        parameter_validator=validate_params, parameter_summary_provider=parameter_summary)
    # Saved scalars/arrays must become text: lists in this UI mean dropdowns.
    for r in RANGES_DEG:
        key = f"Bar Width for {r:g}deg (deg)"
        value = task_manager.exp_params[key]
        if not isinstance(value, str):
            task_manager.exp_params[key] = json.dumps(value)
    if not confirm_session_parameters(task_manager):
        return
    validate_params(task_manager.exp_params)
    session_timestamp, save_dir = create_session_dir(script_dir, task_manager.exp_params["Subject ID"])
    session_t0 = time.perf_counter()
    session_utc = datetime.now(timezone.utc).isoformat()
    metadata = {"session_id": session_timestamp, "session_t0_perf_counter": session_t0,
        "session_t0_utc_approx": session_utc, "parameters": dict(task_manager.exp_params),
        "photodiode_protocol": DisplaySync.SPEC, "photodiode_size_px": 80,
        "photodiode_inset_px": 10,
        "time_units": "seconds relative to session_t0_perf_counter",
        "sync_note": "EDF uses tracker time; SESSION_ZERO declares the PC origin. CLOCK_SYNC receipt includes transport latency."}
    with open(os.path.join(save_dir, "session.json"), "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)

    save_gaze_csv = bool(IS_SIMULATING) or str(tracker_mode).lower() != "eyelink"
    gaze_log_queue = Queue(maxsize=20000) if save_gaze_csv else None
    dropped_samples = Value("i", 0)
    gaze_writer = None
    if save_gaze_csv:
        gaze_log_path = os.path.join(
            save_dir,
            f"Fixation_movingbar_eye_log_{session_timestamp}.csv",
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
            session_id=f"FixationMovingBar_{session_timestamp}",
            save_dir=save_dir,
            session_t0=session_t0,
            screen_size=(1920, 1080),
            qy_sample_rate=EYE_TRACKER_RATE_HZ,
            gaze_log_queue=gaze_log_queue,
            dropped_samples=dropped_samples,
        )
        gaze_source = tracker_runtime.gaze_source
        tracker_runtime.send_event(f"SESSION_ZERO PERF_COUNTER {session_t0:.9f} UTC {session_utc}")
        tracker_runtime.send_event(f"CLOCK_SYNC SESSION_TIME {time.perf_counter() - session_t0:.9f}")

        win_subject = visual.Window(
            screen=MONITOR_ID_SUBJECT,
            size=[1920, 1080],
            fullscr=True,
            waitBlanking=True,
            color="black",
            units="pix",
            allowGUI=False,
        )
        win_control = visual.Window(
            screen=MONITOR_ID_CONTROL,
            size=[800, 450],
            fullscr=False,
            waitBlanking=False,
            color="black",
            units="pix",
            title=f"Fixation Moving-Bar Control View ({tracker_runtime.mode})",
        )

        task = FixationMovingBarTask(
            win_subject,
            win_control,
            gaze_source,
            task_manager,
            IS_SIMULATING,
            session_t0,
            save_dir,
            session_timestamp,
            gaze_log_queue,
            dropped_samples,
            tracker_runtime,
            session_utc=session_utc,
        )
        metadata["nominal_frame_period_s"] = task.nominal_period
        print(f"[Session] Tracker: {tracker_runtime.mode}")
        print(f"[Session] Logs: {save_dir}")
        task.run_task()

    except (TaskAbort, SystemExit):
        print("Fixation moving-bar task stopped by user.")
    except Exception as exc:
        print(f"Fixation moving-bar task error: {exc}")
        traceback.print_exc()
    finally:
        metadata["session_end_time"] = time.perf_counter() - session_t0
        try:
            with open(os.path.join(save_dir, "session.json"), "w", encoding="utf-8") as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2)
        except Exception:
            traceback.print_exc()
        if task is not None:
            try:
                task.close()
            except Exception:
                traceback.print_exc()

        if tracker_runtime is not None:
            try:
                try:
                    tracker_runtime.send_event(f"CLOCK_SYNC SESSION_TIME {time.perf_counter() - session_t0:.9f}")
                finally:
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

        if dropped_samples.value:
            print(
                f"[Warning] Dropped {dropped_samples.value} gaze samples "
                "because the logging queue was full."
            )
        if gaze_writer is not None and gaze_writer.exitcode not in (0, None):
            print(
                f"[Warning] Gaze CSV writer exited with code "
                f"{gaze_writer.exitcode}."
            )

        if win_subject is not None:
            win_subject.close()
        if win_control is not None:
            win_control.close()
        print(f"[Session] Data saved in: {save_dir}")


if __name__ == "__main__":
    freeze_support()
    main()
