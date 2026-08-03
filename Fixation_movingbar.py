"""Fixation training task with moving bars in the lower-right visual field."""

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
from QYEyetracker_Server import EyetrackerServer
from Shared_Memory_Util import SharedGazeData


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
    "Bar Width for 4deg (deg)": 0.04,
    "Bar Width for 20deg (deg)": 0.19,
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


def make_condition_block(rng):
    """One balanced block: four directions x two angular ranges."""
    conditions = [
        {"direction": direction, "range_deg": range_deg}
        for range_deg in RANGES_DEG
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
):
    """
    Build a lower-right scan aperture.

    The 4-degree aperture starts at the fixation point and remains entirely in
    the lower-right quadrant.  If the 20-degree aperture is taller than the
    lower half-screen, its bottom is pinned to the screen bottom and its top is
    allowed to cross the horizontal midline.
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

    half_width = screen_width_px / 2.0
    half_height = screen_height_px / 2.0
    if x_span > half_width:
        raise ValueError(
            f"{range_deg:g}deg horizontal scan ({x_span:.1f}px) does not fit "
            f"to the right of fixation ({half_width:.1f}px available)."
        )
    if y_span > screen_height_px:
        raise ValueError(
            f"{range_deg:g}deg vertical scan ({y_span:.1f}px) does not fit "
            f"on the display ({screen_height_px}px available)."
        )

    x_min = 0.0
    x_max = x_span
    if y_span <= half_height:
        y_top = 0.0
        y_bottom = -y_span
    else:
        y_bottom = -half_height
        y_top = y_bottom + y_span

    center_x = (x_min + x_max) / 2.0
    center_y = (y_bottom + y_top) / 2.0

    if direction == "Right":
        bar_size = (thickness_x, y_span)
        start_pos = (x_min - thickness_x / 2.0, center_y)
        end_pos = (x_max - thickness_x / 2.0, center_y)
    elif direction == "Left":
        bar_size = (thickness_x, y_span)
        start_pos = (x_max + thickness_x / 2.0, center_y)
        end_pos = (x_min + thickness_x / 2.0, center_y)
    elif direction == "Down":
        bar_size = (x_span, thickness_y)
        start_pos = (center_x, y_top + thickness_y / 2.0)
        end_pos = (center_x, y_bottom + thickness_y / 2.0)
    elif direction == "Up":
        bar_size = (x_span, thickness_y)
        start_pos = (center_x, y_bottom - thickness_y / 2.0)
        end_pos = (center_x, y_top - thickness_y / 2.0)
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
        "Bar Width for 4deg (deg)",
        "Bar Width for 20deg (deg)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
        "Reward Length (s)",
        "ITI (s)",
    ]
    for field in positive_fields:
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")
    if float(params["Bar On After Fixation Start (ms)"]) < 0:
        raise ValueError("Bar On After Fixation Start (ms) cannot be negative.")
    if float(params["Timeout (s)"]) < 0:
        raise ValueError("Timeout (s) cannot be negative.")
    opacity = float(params["Bar Opacity (0-1)"])
    if not 0.0 <= opacity <= 1.0:
        raise ValueError("Bar Opacity (0-1) must be between 0 and 1.")


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
            4.0: float(params["Bar Width for 4deg (deg)"]),
            20.0: float(params["Bar Width for 20deg (deg)"]),
        }
        self.bar_opacity = float(params["Bar Opacity (0-1)"])
        self.viewing_distance_cm = float(params["Viewing Distance (cm)"])
        self.monitor_width_cm = float(params["Subject Monitor Width (cm)"])
        self.monitor_height_cm = float(params["Subject Monitor Height (cm)"])
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
                self.bar_width_by_range[range_deg],
                self.viewing_distance_cm,
                self.monitor_width_cm,
                self.monitor_height_cm,
                self.win_sub.size[0],
                self.win_sub.size[1],
            )

    def _build_static_visuals(self):
        self.fix_sub = visual.Circle(
            self.win_sub,
            radius=2,
            fillColor="white",
            lineColor="white",
            pos=(0, 0),
        )
        self.fix_ctl = visual.Circle(
            self.win_ctl,
            radius=2 * self.scale_x,
            fillColor="green",
            lineColor="green",
            pos=(0, 0),
        )
        self.fix_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fix_radius * self.scale_x,
            fillColor=None,
            lineColor="red",
            lineWidth=2,
            pos=(0, 0),
        )

    def _prepare_bar(self, condition):
        range_deg = float(condition["range_deg"])
        direction = condition["direction"]
        bar_width_deg = self.bar_width_by_range[range_deg]
        geometry = calculate_scan_geometry(
            direction,
            range_deg,
            bar_width_deg,
            self.viewing_distance_cm,
            self.monitor_width_cm,
            self.monitor_height_cm,
            self.win_sub.size[0],
            self.win_sub.size[1],
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
            trial_data[field] = self.now()

    def _schedule_flip_time(self, trial_data, field):
        if trial_data[field] is None:
            self.win_sub.callOnFlip(self._mark_time, trial_data, field)

    def _poll_commands(self):
        keys = event.getKeys()
        if "escape" in keys:
            raise TaskAbort()
        return "n" in keys

    def _gaze_in_fixation(self, gaze):
        return bool(gaze["valid"]) and math.hypot(gaze["x"], gaze["y"]) <= (
            self.fix_radius
        )

    def _log_simulated_gaze(self, gaze):
        if not self.is_simulating:
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

    def _present_frame(self, fix_visible, bar_visible):
        if fix_visible:
            self.fix_sub.draw()
            self.fix_ctl.draw()
            self.fix_window_ctl.draw()
        if bar_visible:
            self.bar_sub.draw()
            self.bar_ctl.draw()
            self.scan_window_ctl.draw()

        gaze = self.gaze_renderer.update_and_draw()
        self.win_sub.flip()
        self.win_ctl.flip()
        self._log_simulated_gaze(gaze)
        pause_requested = self._poll_commands()
        return gaze, pause_requested

    def _black_out(self, trial_data):
        if trial_data["Time_DrawFinish"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_BarOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_BarOff")
        self._present_frame(False, False)

    def _wait_for_fixation(self, trial_data):
        candidate_start = None
        wait_start = self.now()
        pause_requested = False

        while self.now() - wait_start < self.wait_time_s:
            gaze, requested = self._present_frame(True, False)
            pause_requested = pause_requested or requested
            detected_at = self.now()
            if self._gaze_in_fixation(gaze):
                if candidate_start is None:
                    candidate_start = detected_at
                elif detected_at - candidate_start >= self.fix_acquire_s:
                    trial_data["Time_GazeEnter"] = candidate_start
                    return candidate_start, pause_requested
            else:
                candidate_start = None
        return None, pause_requested

    def _hold_before_bar(self, fixation_start):
        pause_requested = False
        while self.now() - fixation_start < self.bar_on_delay_s:
            gaze, requested = self._present_frame(True, False)
            pause_requested = pause_requested or requested
            if not self._gaze_in_fixation(gaze):
                return False, pause_requested
        return True, pause_requested

    def _run_bar_motion(self, trial_data, geometry):
        pause_requested = False
        self._set_bar_progress(geometry, 0.0)
        self._schedule_flip_time(trial_data, "Time_BarOn")
        gaze, requested = self._present_frame(True, True)
        pause_requested = pause_requested or requested
        if not self._gaze_in_fixation(gaze):
            return False, pause_requested

        bar_on_time = trial_data["Time_BarOn"]
        while self.now() - bar_on_time < self.bar_duration_s:
            progress = (self.now() - bar_on_time) / self.bar_duration_s
            self._set_bar_progress(geometry, progress)
            gaze, requested = self._present_frame(True, True)
            pause_requested = pause_requested or requested
            if not self._gaze_in_fixation(gaze):
                return False, pause_requested

        self._schedule_flip_time(trial_data, "Time_BarOff")
        self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        _, requested = self._present_frame(False, False)
        return True, pause_requested or requested

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
            "Fixation_Position": "(0, 0)",
            "Fix_Window_Radius": self.fix_radius,
            "Wait_Time_s": self.wait_time_s,
            "Fixation_Acquire_Time_ms": self.fix_acquire_s * 1000.0,
            "Bar_On_After_Fixation_Start_ms": self.bar_on_delay_s
            * 1000.0,
            "Direction": condition["direction"],
            "Range_deg": range_deg,
            "Bar_Length_deg": range_deg,
            "Bar_Width_deg": self.bar_width_by_range[range_deg],
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
        }

    def _run_one_trial(
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
        event.clearEvents()
        self.gaze_renderer.reset_trail()

        self.arduino.trial_start()
        trial_data["Time_TrialStart"] = self.now()
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
                    trial_data["Break_Phase"] = "BarMotion"

        if status == "Success":
            self.arduino.trial_success()
            trial_data["Time_Reward"] = self.now()
            self.arduino.reward(int(self.reward_len_s * 1000.0))
        elif status == "Break":
            self._black_out(trial_data)
            self.arduino.trial_break()
            core.wait(self.timeout_s)
        else:
            self._black_out(trial_data)
            self.arduino.trial_nofix()

        self.arduino.trial_end()
        trial_data["Status"] = status
        trial_data["Time_End"] = self.now()
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

    def _run_iti(self):
        iti_start = self.now()
        while self.now() - iti_start < self.iti_s:
            _, pause_requested = self._present_frame(False, False)
            if pause_requested:
                return True
        return False

    def _prompt_and_update(self):
        self._present_frame(False, False)
        if not self.task_manager.prompt_for_parameters():
            raise TaskAbort()
        self.update_params()
        event.clearEvents()

    def run_task(self):
        if not self.task_manager.prompt_for_parameters():
            raise TaskAbort()
        self.update_params()
        event.clearEvents()

        print("\n=== Fixation Moving-Bar Task started ===")
        print("Each block contains 4 directions x 2 ranges in random order.")
        print("Press Esc to quit; press N to edit parameters before the next trial.")

        trial_number = 1
        block_number = 0
        success_count = 0
        pause_requested = False

        while True:
            block_number += 1
            block_conditions = make_condition_block(self.rng)
            print(f"\n=== Block {block_number} ===")

            for trial_in_block, condition in enumerate(block_conditions, 1):
                if pause_requested:
                    self._prompt_and_update()
                    pause_requested = False

                while self._run_iti():
                    self._prompt_and_update()

                print(
                    f"\n--- Trial {trial_number} "
                    f"(block {block_number}, {trial_in_block}/8): "
                    f"{condition['range_deg']:g}deg {condition['direction']} ---"
                )
                trial_data, requested = self._run_one_trial(
                    trial_number,
                    block_number,
                    trial_in_block,
                    condition,
                )
                self._write_trial(trial_data)
                pause_requested = pause_requested or requested

                if trial_data["Status"] == "Success":
                    success_count += 1
                print(
                    f"Result: {trial_data['Status']} "
                    f"(success {success_count}/{trial_number})"
                )
                trial_number += 1

    def close(self):
        self.trial_logger.close()
        self.arduino.close()


def create_session_dir(script_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(
        script_dir, "experiment_logs", f"FixationMovingBar_{timestamp}"
    )
    candidate = base
    suffix = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{suffix:03d}"
        suffix += 1
    os.makedirs(candidate)
    return timestamp, candidate


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    session_timestamp, save_dir = create_session_dir(script_dir)
    session_t0 = time.perf_counter()

    gaze_log_path = os.path.join(
        save_dir,
        f"Fixation_movingbar_eye_log_{session_timestamp}.csv",
    )
    gaze_log_queue = Queue(maxsize=20000)
    dropped_samples = Value("i", 0)
    gaze_writer = GazeCsvWriter(gaze_log_queue, gaze_log_path)
    gaze_writer.start()

    shared_data = None
    p_server = None
    win_subject = None
    win_control = None
    task = None

    try:
        shared_data = SharedGazeData()
        if IS_SIMULATING == 0:
            p_server = EyetrackerServer(
                shared_data,
                "EyeControl_SDK.dll",
                EYE_TRACKER_RATE_HZ,
                gaze_log_queue=gaze_log_queue,
                session_t0=session_t0,
                dropped_samples=dropped_samples,
            )
            p_server.start()
            print("EyeTracker Server started.")
        else:
            print("Running in mouse simulation mode.")

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
            size=[800, 600],
            fullscr=False,
            waitBlanking=False,
            color="black",
            units="pix",
            title="Fixation Moving-Bar Control View",
        )

        task_manager = FineVision_Notebook(
            task_name="FixationMovingBar",
            default_params=DEFAULT_PARAMS,
        )
        task = FixationMovingBarTask(
            win_subject,
            win_control,
            shared_data,
            task_manager,
            IS_SIMULATING,
            session_t0,
            save_dir,
            session_timestamp,
            gaze_log_queue,
            dropped_samples,
        )
        print(f"[Session] Logs: {save_dir}")
        task.run_task()

    except (TaskAbort, SystemExit):
        print("Fixation moving-bar task stopped by user.")
    except Exception as exc:
        print(f"Fixation moving-bar task error: {exc}")
        traceback.print_exc()
    finally:
        if task is not None:
            try:
                task.close()
            except Exception:
                traceback.print_exc()

        if shared_data is not None:
            shared_data.stop()
        if p_server is not None:
            p_server.join(timeout=10)
            if p_server.is_alive():
                p_server.terminate()
                p_server.join(timeout=2)

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
        if gaze_writer.exitcode not in (0, None):
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
