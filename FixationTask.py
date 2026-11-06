"""Classic fixation with session records and frame-counted photodiode codes."""
import csv
import json
import math
import os
import time
import traceback
from datetime import datetime, timezone

from psychopy import visual, event
from eyetracker import create_tracker_runtime
from FineVision_Notebook import FineVision_Notebook
from GazeTrackerRenderer import GazeTrackerRenderer
from FineVision_Util import ArduinoController
from SessionNaming import subject_filename, confirm_session_parameters
from FramePulse import DisplaySync

TIME_FIELDS = ["Time_TrialStart", "Time_DrawFinish", "Time_GazeEnter",
               "Time_FixAcquired", "Time_Break", "Time_NoFix", "Time_Success",
               "Time_FixOff", "Time_OutcomePDOn", "Time_OutcomePDOff", "Time_PDOn", "Time_PDOff", "Time_End"]
FIELDS = ["Trial", "Subject_ID", "Status", *TIME_FIELDS,
          "Session_T0_PerfCounter", "Session_T0_UTC", "Parameters_JSON"]


def create_session_dir(root, subject):
    suffix = f"{subject_filename(subject)}_{datetime.now():%Y%m%d_%H%M%S}"
    base = os.path.join(root, "experiment_logs", f"Fixation_{suffix}")
    index = 0
    while True:
        extra = f"_{index:03d}" if index else ""
        folder = base + extra
        try:
            os.makedirs(folder)
            return suffix + extra, folder
        except FileExistsError:
            index += 1


class FixationTask:
    def __init__(self, win_sub, win_ctl, shared_data, task_manager, is_simulating,
                 save_dir, session_id, session_t0, session_utc):
        self.win_sub, self.win_ctl = win_sub, win_ctl
        self.shared_data, self.task_manager = shared_data, task_manager
        self.session_t0, self.session_utc = session_t0, session_utc
        self.save_dir = save_dir
        self.subject_id = str(task_manager.exp_params["Subject ID"])
        self.arduino = ArduinoController()
        sx, sy = win_ctl.size[0] / win_sub.size[0], win_ctl.size[1] / win_sub.size[1]
        self.scale_x = sx
        self.gaze_renderer = GazeTrackerRenderer(win_ctl, shared_data, sx, sy, is_simulating)
        self.stim_fix_point = visual.Circle(win_sub, radius=15, fillColor="white", lineColor="white", pos=(0, 0))
        self.ctl_fix_point = visual.Circle(win_ctl, radius=15 * sx, fillColor="green", pos=(0, 0))
        self.ctl_fix_window = visual.Circle(win_ctl, radius=100, fillColor=None, lineColor="red", pos=(0, 0))
        self.pd = visual.Rect(win_sub, width=80, height=80, units="pix",
                              pos=(win_sub.size[0] / 2 - 50, -win_sub.size[1] / 2 + 50),
                              fillColor="black", lineColor="black", autoLog=False)
        self.pulse = DisplaySync()
        self.behavior_log, self.events, self.frames = [], [], []
        self.current = None
        self.pause_requested = self.quit_requested = False
        self.previous_flip = None
        self.frame_index = 0
        self.nominal_period = float(win_sub.monitorFramePeriod)
        self.update_params()
        self.csv_file = open(os.path.join(save_dir, f"Fixation_task_log_{session_id}.csv"), "w", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(self.csv_file, fieldnames=FIELDS)
        self.writer.writeheader()
        self.csv_file.flush()

    def now(self):
        return time.perf_counter() - self.session_t0

    def send(self, label, at=None, **details):
        at = self.now() if at is None else at
        trial = self.current["Trial"] if self.current else 0
        self.events.append({"event": label, "time": at, "trial": trial, **details})
        if hasattr(self.shared_data, "send_event"):
            self.shared_data.send_event(f"{label} TRIAL {trial} SESSION_TIME {at:.9f}")

    def update_params(self):
        p = self.task_manager.exp_params
        self.wait_time = float(p.get("Wait Time (s)", 2))
        self.stim_duration = float(p.get("Stim Duration (s)", 1))
        self.reward_len = float(p.get("Reward Length (s)", .2))
        self.iti_time = float(p.get("ITI (s)", 1))
        self.timeout_time = float(p.get("Timeout (s)", 2))
        self.fix_radius = float(p.get("Fix Window Radius (pix)", 100))
        values = (self.wait_time, self.stim_duration, self.reward_len,
                  self.iti_time, self.timeout_time, self.fix_radius)
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Fixation parameters must be finite and nonnegative")
        self.ctl_fix_window.radius = self.fix_radius * self.scale_x

    def _flip_mark(self, fix_on, fix_off, edge, label):
        # One timestamp for simultaneous fixation and photodiode transitions.
        at = self.now()
        self.last_flip_session_time = at
        if fix_on:
            self.current["Time_TrialStart"] = self.current["Time_DrawFinish"] = at
            self.send("FIX_ON", at)
        if fix_off:
            self.current["Time_FixOff"] = at
            self.send("FIX_OFF", at)
        if edge:
            self.send(f"PD_{label}_{edge}", at)
            if self.current and label == "FIXATION":
                self.current["Time_PDOn" if edge == "ON" else "Time_PDOff"] = at

    def frame(self, fixation=False, fix_on=False, fix_off=False, poll_gaze=True):
        # Trial loops inspect every sample they poll; do not consume and ignore
        # an extra sample during drawing (it could contain a brief break).
        gaze = self.gaze_renderer.update() if poll_gaze else None
        if fixation:
            self.stim_fix_point.draw()
            self.ctl_fix_point.draw()
            self.ctl_fix_window.draw()
        self.gaze_renderer.draw()
        white, edge, label = self.pulse.next_frame(fixation, "FIXATION")
        self.pd.fillColor = self.pd.lineColor = "white" if white else "black"
        self.pd.draw()
        self.win_sub.callOnFlip(self._flip_mark, fix_on, fix_off, edge, label)
        flip_time = self.win_sub.flip()
        interval = None if self.previous_flip is None else flip_time - self.previous_flip
        self.frames.append({"frame": self.frame_index, "flip_clock_time": flip_time,
                            "session_time": self.last_flip_session_time,
                            "interval_s": interval, "pd_white": white,
                            "pd_code": label, "trial": self.current["Trial"] if self.current else 0,
                            "late": interval is not None and interval > 1.5 * self.nominal_period})
        self.previous_flip = flip_time
        self.frame_index += 1
        self.win_ctl.flip()
        keys = event.getKeys()
        self.quit_requested |= "escape" in keys
        self.pause_requested |= "n" in keys
        return gaze

    def wait(self, duration, fixation=False):
        start = self.now()
        while self.now() - start < duration or self.pulse.busy:
            self.frame(fixation=fixation)
            # Finish an already-started optical code before quitting.
            if self.quit_requested and not self.pulse.busy:
                return False
        return not self.quit_requested

    def inside(self, gaze):
        return gaze["valid"] and math.hypot(gaze["x"], gaze["y"]) <= self.fix_radius

    def save_trial(self):
        if self.current is None:
            return
        self.behavior_log.append(self.current.copy())
        self.writer.writerow(self.current)
        self.csv_file.flush()
        self.current = None

    def run_trial(self, number):
        params = dict(self.task_manager.exp_params)
        params.update({"Fixation Acquire (s)": .150, "Fixation Point Radius (pix)": 15,
                       "Photodiode Size (pix)": 80, "Photodiode Inset (pix)": 10,
                       "Photodiode Protocol": DisplaySync.SPEC})
        self.current = {"Trial": number, "Subject_ID": self.subject_id, "Status": "Aborted",
                        **dict.fromkeys(TIME_FIELDS), "Session_T0_PerfCounter": self.session_t0,
                        "Session_T0_UTC": self.session_utc,
                        "Parameters_JSON": json.dumps(params, ensure_ascii=False)}
        self.send("TRIALID " + str(number))
        self.arduino.trial_start()
        self.ctl_fix_window.lineColor = "red"
        self.frame(fixation=True, fix_on=True)
        candidate = None
        status = "NoFix"
        while not self.quit_requested and self.now() - self.current["Time_DrawFinish"] < self.wait_time:
            gaze = self.gaze_renderer.update()
            detected = self.now()
            if self.inside(gaze):
                if candidate is None:
                    candidate = detected
                if detected - candidate >= .150:
                    self.current["Time_GazeEnter"] = candidate
                    self.current["Time_FixAcquired"] = detected
                    self.send("FIX_ACQUIRED", detected)
                    status = "Success"
                    break
            else:
                candidate = None
            self.frame(fixation=True, poll_gaze=False)
        if status == "Success":
            self.ctl_fix_window.lineColor = "green"
            while not self.quit_requested and self.now() - self.current["Time_FixAcquired"] < self.stim_duration:
                gaze = self.gaze_renderer.update()
                detected = self.now()
                if not self.inside(gaze):
                    status = "Break"
                    self.current["Time_Break"] = detected
                    self.send("BREAK", detected)
                    break
                self.frame(fixation=True, poll_gaze=False)
        if self.quit_requested:
            self.abort_trial()
            return
        at = self.now()
        if status == "NoFix":
            self.current["Time_NoFix"] = at
            self.send("NOFIX", at)
        elif status == "Success":
            self.current["Time_Success"] = at
        self.current["Status"] = status
        self.current["Time_End"] = self.current["Time_Break"] if status == "Break" else at
        self.send("TRIAL_RESULT " + status, self.current["Time_End"])
        if status == "Success":
            self.arduino.trial_success()
            self.arduino.reward(int(self.reward_len * 1000))
        elif status == "Break":
            self.arduino.trial_break()
        else:
            self.arduino.trial_nofix()
        self.frame(fix_off=True)
        self.wait(self.timeout_time if status == "Break" else 0)
        self.save_trial()
        print(f"Trial {number}: {status}")

    def abort_trial(self):
        self.current["Status"] = "Aborted"
        self.current["Time_End"] = self.now()
        self.send("TRIAL_ABORT", self.current["Time_End"])
        self.frame(fix_off=True)
        self.wait(0)
        self.save_trial()

    def run_task(self):
        # Establish a physically dark baseline before the one-frame start code.
        for _ in range(5):
            self.frame()
            if self.quit_requested:
                return
        self.pulse.start("TASK_START")
        self.wait(0)
        number = 1
        while not self.quit_requested:
            if self.pause_requested:
                self.task_manager.prompt_for_runtime_parameters()
                self.update_params()
                event.clearEvents()
                self.pause_requested = False
                self.previous_flip = None
            if not self.wait(self.iti_time):
                break
            if self.pause_requested:
                continue
            self.run_trial(number)
            number += 1

    def close(self):
        try:
            if self.current is not None:
                self.current["Status"] = "Error"
                self.current["Time_End"] = self.now()
                self.save_trial()
        finally:
            self.csv_file.close()
            try:
                for name, rows in (("events.json", self.events), ("frames.json", self.frames)):
                    with open(os.path.join(self.save_dir, name), "w", encoding="utf-8") as stream:
                        json.dump(rows, stream, ensure_ascii=False, indent=2)
            finally:
                self.arduino.close()


def main():
    defaults = {"Subject ID": "Monkey_H18", "Wait Time (s)": 10.,
                "Stim Duration (s)": 1.5, "Fix Window Radius (pix)": 500,
                "Reward Length (s)": .2, "ITI (s)": 5., "Timeout (s)": 2.5}
    manager = FineVision_Notebook(task_name="FixationTask", default_params=defaults)
    if not confirm_session_parameters(manager):
        return
    session_id, folder = create_session_dir(os.path.dirname(os.path.abspath(__file__)), manager.exp_params["Subject ID"])
    session_t0 = time.perf_counter()
    utc = datetime.now(timezone.utc).isoformat()
    metadata = {"session_id": session_id, "session_t0_perf_counter": session_t0,
                "session_t0_utc_approx": utc, "time_units": "seconds relative to session_t0_perf_counter",
                "parameters": dict(manager.exp_params), "photodiode_protocol": DisplaySync.SPEC,
                "sync_note": "EDF uses tracker time. SESSION_ZERO declares PC origin; CLOCK_SYNC carries PC elapsed time at send. Message receipt includes transport latency."}
    metadata_path = os.path.join(folder, "session.json")
    with open(metadata_path, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    runtime = subject = control = task = None
    try:
        runtime = create_tracker_runtime(globals().get("TRACKER_MODE_OVERRIDE", "eyelink"),
            is_simulating=bool(globals().get("IS_SIMULATING_OVERRIDE", 0)),
            session_id=f"Fixation_{session_id}", save_dir=folder, session_t0=session_t0,
            screen_size=(1920, 1080), qy_sample_rate=100)
        runtime.send_event(f"SESSION_ZERO PERF_COUNTER {session_t0:.9f} UTC {utc}")
        runtime.send_event(f"CLOCK_SYNC SESSION_TIME {time.perf_counter() - session_t0:.9f}")
        subject = visual.Window(screen=1, size=[1920, 1080], fullscr=True,
                                waitBlanking=True, color="black", units="pix", allowGUI=False)
        control = visual.Window(screen=0, size=[800, 450], fullscr=False,
                                waitBlanking=False, color="black", units="pix", title="Fixation Control View")
        task = FixationTask(subject, control, runtime.gaze_source, manager,
                            globals().get("IS_SIMULATING_OVERRIDE", 0), folder, session_id, session_t0, utc)
        metadata["nominal_frame_period_s"] = task.nominal_period
        task.run_task()
    finally:
        metadata["session_end_time"] = time.perf_counter() - session_t0
        try:
            with open(metadata_path, "w", encoding="utf-8") as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2)
        finally:
            for resource in (task, runtime, subject, control):
                if resource is not None:
                    try:
                        if resource is runtime:
                            try:
                                runtime.send_event(f"CLOCK_SYNC SESSION_TIME {time.perf_counter() - session_t0:.9f}")
                            finally:
                                runtime.close()
                        else:
                            resource.close()
                    except Exception:
                        traceback.print_exc()


if __name__ == "__main__":
    main()
