"""Two-stage fixation-to-saccade task for FineVision."""

import csv
import math
import os
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


DEFAULT_PARAMS = {
    "Subject ID": "Monkey_H18",
    "Wait Time (s)": 10.0,
    "Fixation Acquire Time (ms)": 150,
    "Fixation Position X (pix)": 0,
    "Fixation Position Y (pix)": 0,
    "Fix Window Radius (pix)": 500,
    "Stim On After Fixation Start (ms)": 500,
    "Fixation Point Off After Fixation Start (ms)": 1500,
    "Stim Off After Fixation Start (ms)": 2000,
    "Stim Hold Time (ms)": 300,
    "Stim Window Radius (pix)": 150,
    "Stim Position X (pix)": 400,
    "Stim Position Y (pix)": 0,
    "Stim Major Axis (pix)": 120,
    "Stim Minor Axis (pix)": 60,
    "Stim Orientation (deg)": 0,
    "Stim Color R": 255,
    "Stim Color G": 0,
    "Stim Color B": 0,
    "Reward Length (s)": 0.2,
    "ITI (s)": 5.0,
    "Timeout (s)": 2.5,
}


TRIAL_LOG_FIELDS = [
    "Trial",
    "Status",
    "Time_TrialStart",
    "Time_DrawFinish",
    "Time_GazeEnter",
    "Time_StimOn",
    "Time_FixationPointOff",
    "Fixation_Position",
    "Time_StimWindowEnter",
    "Time_StimOff",
    "Time_Reward",
    "Time_End",
    "Subject_ID",
    "Fixation_Pos_X",
    "Fixation_Pos_Y",
    "Fix_Window_Radius",
    "Stim_Position",
    "Stim_Pos_X",
    "Stim_Pos_Y",
    "Stim_Window_Radius",
    "Stim_Major_Axis",
    "Stim_Minor_Axis",
    "Stim_Orientation",
    "Stim_Color_R",
    "Stim_Color_G",
    "Stim_Color_B",
    "Fixation_Acquire_Time_ms",
    "Stim_On_After_Fixation_Start_ms",
    "Fixation_Point_Off_After_Fixation_Start_ms",
    "Stim_Off_After_Fixation_Start_ms",
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
    "Time_Reward",
    "Time_End",
]


class TaskAbort(Exception):
    """Raised when Escape is pressed."""


class TrialCsvLogger:
    """Append and flush one row at the end of every trial."""

    def __init__(self, csv_path):
        self.csv_path = csv_path
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


def _make_ellipse_vertices(width, height, count=96):
    return [
        (
            math.cos(2.0 * math.pi * index / count) * width / 2.0,
            math.sin(2.0 * math.pi * index / count) * height / 2.0,
        )
        for index in range(count)
    ]


def _validate_params(params):
    stim_on_ms = float(params["Stim On After Fixation Start (ms)"])
    fix_off_ms = float(params["Fixation Point Off After Fixation Start (ms)"])
    stim_off_ms = float(params["Stim Off After Fixation Start (ms)"])
    stim_hold_ms = float(params["Stim Hold Time (ms)"])

    if not 0 <= stim_on_ms < fix_off_ms < stim_off_ms:
        raise ValueError(
            "Timing must satisfy: 0 <= Stim On < Fixation Point Off < Stim Off."
        )
    if stim_hold_ms <= 0:
        raise ValueError("Stim Hold Time (ms) must be greater than zero.")
    if stim_off_ms - fix_off_ms < stim_hold_ms:
        raise ValueError(
            "Stim Off - Fixation Point Off must be at least Stim Hold Time, "
            "otherwise the second-stage hold cannot be completed."
        )

    positive_fields = [
        "Wait Time (s)",
        "Fixation Acquire Time (ms)",
        "Fix Window Radius (pix)",
        "Stim Window Radius (pix)",
        "Stim Major Axis (pix)",
        "Stim Minor Axis (pix)",
        "Reward Length (s)",
        "ITI (s)",
    ]
    for field in positive_fields:
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")
    if float(params["Stim Major Axis (pix)"]) < float(
        params["Stim Minor Axis (pix)"]
    ):
        raise ValueError(
            "Stim Major Axis (pix) must be greater than or equal to "
            "Stim Minor Axis (pix)."
        )
    if float(params["Timeout (s)"]) < 0:
        raise ValueError("Timeout (s) cannot be negative.")

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
    ):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.task_manager = task_manager
        self.is_simulating = is_simulating
        self.session_t0 = float(session_t0)
        self.save_dir = save_dir
        self.session_timestamp = session_timestamp

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

        task_log_path = os.path.join(
            save_dir, f"Saccade_task_log_{session_timestamp}.csv"
        )
        self.trial_logger = TrialCsvLogger(task_log_path)

    def now(self):
        return time.perf_counter() - self.session_t0

    def update_params(self):
        params = self.task_manager.exp_params
        _validate_params(params)

        self.subject_id = str(params["Subject ID"])
        self.wait_time_s = float(params["Wait Time (s)"])
        self.fix_acquire_s = float(params["Fixation Acquire Time (ms)"]) / 1000.0
        self.fix_x = float(params["Fixation Position X (pix)"])
        self.fix_y = float(params["Fixation Position Y (pix)"])
        self.fix_radius = float(params["Fix Window Radius (pix)"])

        self.stim_on_s = (
            float(params["Stim On After Fixation Start (ms)"]) / 1000.0
        )
        self.fix_off_s = (
            float(params["Fixation Point Off After Fixation Start (ms)"]) / 1000.0
        )
        self.stim_off_s = (
            float(params["Stim Off After Fixation Start (ms)"]) / 1000.0
        )
        self.stim_hold_s = float(params["Stim Hold Time (ms)"]) / 1000.0

        self.stim_radius = float(params["Stim Window Radius (pix)"])
        self.stim_x = float(params["Stim Position X (pix)"])
        self.stim_y = float(params["Stim Position Y (pix)"])
        self.stim_major_axis = float(params["Stim Major Axis (pix)"])
        self.stim_minor_axis = float(params["Stim Minor Axis (pix)"])
        self.stim_orientation = float(params["Stim Orientation (deg)"])
        self.stim_rgb_255 = (
            int(float(params["Stim Color R"])),
            int(float(params["Stim Color G"])),
            int(float(params["Stim Color B"])),
        )

        self.reward_len_s = float(params["Reward Length (s)"])
        self.iti_s = float(params["ITI (s)"])
        self.timeout_s = float(params["Timeout (s)"])
        self._build_visuals()

    def _build_visuals(self):
        self.fix_sub = visual.Circle(
            self.win_sub,
            radius=15,
            fillColor="white",
            lineColor="white",
            pos=(self.fix_x, self.fix_y),
        )
        self.fix_ctl = visual.Circle(
            self.win_ctl,
            radius=15 * self.scale_x,
            fillColor="green",
            lineColor="green",
            pos=(self.fix_x * self.scale_x, self.fix_y * self.scale_y),
        )
        self.fix_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fix_radius * self.scale_x,
            fillColor=None,
            lineColor="red",
            lineWidth=2,
            pos=(self.fix_x * self.scale_x, self.fix_y * self.scale_y),
        )

        color = [channel / 127.5 - 1.0 for channel in self.stim_rgb_255]
        self.stim_sub = visual.ShapeStim(
            self.win_sub,
            vertices=_make_ellipse_vertices(
                self.stim_major_axis, self.stim_minor_axis
            ),
            closeShape=True,
            fillColor=color,
            lineColor=color,
            pos=(self.stim_x, self.stim_y),
            ori=self.stim_orientation,
        )
        self.stim_ctl = visual.ShapeStim(
            self.win_ctl,
            vertices=_make_ellipse_vertices(
                self.stim_major_axis * self.scale_x,
                self.stim_minor_axis * self.scale_y,
            ),
            closeShape=True,
            fillColor=color,
            lineColor=color,
            pos=(self.stim_x * self.scale_x, self.stim_y * self.scale_y),
            ori=self.stim_orientation,
        )
        self.stim_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.stim_radius * self.scale_x,
            fillColor=None,
            lineColor="cyan",
            lineWidth=2,
            pos=(self.stim_x * self.scale_x, self.stim_y * self.scale_y),
        )

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

    def _in_window(self, gaze, center_x, center_y, radius):
        return bool(gaze["valid"]) and math.hypot(
            gaze["x"] - center_x, gaze["y"] - center_y
        ) <= radius

    def _present_frame(self, fix_visible, stim_visible):
        if fix_visible:
            self.fix_sub.draw()
            self.fix_ctl.draw()
            self.fix_window_ctl.draw()
        if stim_visible:
            self.stim_sub.draw()
            self.stim_ctl.draw()
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
        self._present_frame(False, False)

    def _new_trial_data(self, trial_number):
        return {
            "Trial": trial_number,
            "Status": None,
            "Time_TrialStart": None,
            "Time_DrawFinish": None,
            "Time_GazeEnter": None,
            "Time_StimOn": None,
            "Time_FixationPointOff": None,
            "Fixation_Position": f"({self.fix_x:g}, {self.fix_y:g})",
            "Time_StimWindowEnter": None,
            "Time_StimOff": None,
            "Time_Reward": None,
            "Time_End": None,
            "Subject_ID": self.subject_id,
            "Fixation_Pos_X": self.fix_x,
            "Fixation_Pos_Y": self.fix_y,
            "Fix_Window_Radius": self.fix_radius,
            "Stim_Position": f"({self.stim_x:g}, {self.stim_y:g})",
            "Stim_Pos_X": self.stim_x,
            "Stim_Pos_Y": self.stim_y,
            "Stim_Window_Radius": self.stim_radius,
            "Stim_Major_Axis": self.stim_major_axis,
            "Stim_Minor_Axis": self.stim_minor_axis,
            "Stim_Orientation": self.stim_orientation,
            "Stim_Color_R": self.stim_rgb_255[0],
            "Stim_Color_G": self.stim_rgb_255[1],
            "Stim_Color_B": self.stim_rgb_255[2],
            "Fixation_Acquire_Time_ms": self.fix_acquire_s * 1000.0,
            "Stim_On_After_Fixation_Start_ms": self.stim_on_s * 1000.0,
            "Fixation_Point_Off_After_Fixation_Start_ms": self.fix_off_s
            * 1000.0,
            "Stim_Off_After_Fixation_Start_ms": self.stim_off_s * 1000.0,
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
                gaze, self.fix_x, self.fix_y, self.fix_radius
            ):
                if candidate_start is None:
                    candidate_start = detected_at
                elif detected_at - candidate_start >= self.fix_acquire_s:
                    trial_data["Time_GazeEnter"] = candidate_start
                    return candidate_start, pause_requested
            else:
                candidate_start = None

        return None, pause_requested

    def _hold_central_fixation(self, trial_data, fixation_start):
        pause_requested = False

        while True:
            elapsed = self.now() - fixation_start
            stim_visible = elapsed >= self.stim_on_s

            if stim_visible:
                self._schedule_flip_time(trial_data, "Time_StimOn")

            if elapsed >= self.fix_off_s:
                self._schedule_flip_time(trial_data, "Time_FixationPointOff")
                _, requested = self._present_frame(False, True)
                pause_requested = pause_requested or requested
                return "Stage_2", pause_requested

            gaze, requested = self._present_frame(True, stim_visible)
            pause_requested = pause_requested or requested
            if not self._in_window(
                gaze, self.fix_x, self.fix_y, self.fix_radius
            ):
                return "Break_1", pause_requested

    def _finish_stimulus_at_scheduled_time(self, trial_data, fixation_start):
        pause_requested = False
        while self.now() - fixation_start < self.stim_off_s:
            _, requested = self._present_frame(False, True)
            pause_requested = pause_requested or requested
        self._schedule_flip_time(trial_data, "Time_StimOff")
        _, requested = self._present_frame(False, False)
        return pause_requested or requested

    def _run_stage_two(self, trial_data, fixation_start):
        target_enter = None
        pause_requested = False

        while self.now() - fixation_start < self.stim_off_s:
            gaze, requested = self._present_frame(False, True)
            pause_requested = pause_requested or requested
            detected_at = self.now()

            if self._in_window(
                gaze, self.stim_x, self.stim_y, self.stim_radius
            ):
                if target_enter is None:
                    target_enter = detected_at
                    trial_data["Time_StimWindowEnter"] = target_enter
                elif detected_at - target_enter >= self.stim_hold_s:
                    pause_requested = (
                        self._finish_stimulus_at_scheduled_time(
                            trial_data, fixation_start
                        )
                        or pause_requested
                    )
                    return "Success", pause_requested
            elif target_enter is not None:
                return "Break_2", pause_requested

        self._schedule_flip_time(trial_data, "Time_StimOff")
        _, requested = self._present_frame(False, False)
        pause_requested = pause_requested or requested
        if target_enter is None:
            return "nofix_2", pause_requested
        return "Break_2", pause_requested

    def _run_one_trial(self, trial_number):
        trial_data = self._new_trial_data(trial_number)
        event.clearEvents()
        self.gaze_renderer.reset_trail()

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
                trial_data, fixation_start
            )
            pause_requested = pause_requested or requested
            if status == "Stage_2":
                status, requested = self._run_stage_two(
                    trial_data, fixation_start
                )
                pause_requested = pause_requested or requested

        if status == "Success":
            self.arduino.trial_success()
            trial_data["Time_Reward"] = self.now()
            self.arduino.reward(int(self.reward_len_s * 1000.0))
        elif status in ("Break_1", "Break_2"):
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
            print(
                f"Result: {trial_data['Status']} "
                f"(success {success_count}/{trial_number})"
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


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    session_timestamp, save_dir = _create_session_dir(script_dir)
    session_t0 = time.perf_counter()

    gaze_log_path = os.path.join(
        save_dir, f"Saccade_eye_log_{session_timestamp}.csv"
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
            title="Saccade Control View",
        )

        task_manager = FineVision_Notebook(
            task_name="SaccadeTask", default_params=DEFAULT_PARAMS
        )
        task = SaccadeTask(
            win_subject,
            win_control,
            shared_data,
            task_manager,
            IS_SIMULATING,
            session_t0,
            save_dir,
            session_timestamp,
        )
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
