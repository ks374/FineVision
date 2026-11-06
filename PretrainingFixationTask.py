"""Manual-reward fixation pretraining with optional EyeLink gaze feedback.

This task deliberately does not run calibration and never gates reward on gaze.
The operator presses W to reward; EyeLink samples and task messages are still
recorded to EDF, and any available gaze is drawn on the control display.
"""

import os
import re
import time
import traceback
from datetime import datetime

import pandas as pd
from psychopy import core, event, visual

from eyetracker import create_tracker_runtime
from FineVision_Notebook import FineVision_Notebook
from FineVision_Util import ArduinoController
from GazeTrackerRenderer import GazeTrackerRenderer
from PretrainingFixationLogic import (
    PretrainingTrialController,
    validate_pretraining_params,
)


SCREEN_SIZE = (1920, 1080)

DEFAULT_PARAMS = {
    "Subject ID": "Monkey_H18",
    "Fixation Point Radius (pix)": 25,
    "Fixation Point Color": "white",
    "Maximum Fixation Display (s)": 5.0,
    "Reward Duration (ms)": 300,
    "Black Screen Duration (s)": 2.0,
    "Subject Screen Index": 1,
    "Control Screen Index": 0,
    "Full Screen": False,
}

PARAMETER_GROUPS = {
    "Session / 会话": [
        "Subject ID",
        "Subject Screen Index",
        "Control Screen Index",
        "Full Screen",
    ],
    "Stimulus / 刺激": [
        "Fixation Point Radius (pix)",
        "Fixation Point Color",
        "Maximum Fixation Display (s)",
    ],
    "Reward & Timing / 奖励与时间": [
        "Reward Duration (ms)",
        "Black Screen Duration (s)",
    ],
}

LOG_COLUMNS = [
    "SessionStart",
    "SubjectID",
    "Trial",
    "FixationOnWallTime",
    "Result",
    "ManualReward",
    "RewardKeyTime_s",
    "RewardDuration_ms",
    "FixationDisplayDuration_s",
    "TrialEndWallTime",
]


class PretrainingFixationTask:
    def __init__(
        self,
        subject_win,
        control_win,
        tracker,
        arduino,
        params,
        session_wall_start,
    ):
        self.subject_win = subject_win
        self.control_win = control_win
        self.tracker = tracker
        self.arduino = arduino
        self.params = params
        self.session_wall_start = session_wall_start
        self.behavior_log = []

        scale_x = control_win.size[0] / subject_win.size[0]
        scale_y = control_win.size[1] / subject_win.size[1]
        radius = float(params["Fixation Point Radius (pix)"])
        color = params["Fixation Point Color"]
        self.subject_point = visual.Circle(
            subject_win,
            radius=radius,
            fillColor=color,
            lineColor=color,
            pos=(0, 0),
        )
        self.control_point = visual.Circle(
            control_win,
            radius=radius * scale_x,
            fillColor="green",
            lineColor="green",
            pos=(0, 0),
        )
        self.gaze_renderer = GazeTrackerRenderer(
            control_win,
            tracker.gaze_source,
            scale_x,
            scale_y,
            is_simulating=0,
        )
        self.clock = core.Clock()

    def _draw_black_interval(self):
        self.subject_win.color = "black"
        self.control_win.color = "black"
        self.subject_win.flip()
        self.control_win.flip()
        self.clock.reset()
        while self.clock.getTime() < float(
            self.params["Black Screen Duration (s)"]
        ):
            self.gaze_renderer.update_and_draw()
            self.subject_win.flip()
            self.control_win.flip()
            if "escape" in event.getKeys(keyList=["escape"]):
                return False
        return True

    def _run_trial(self, trial_number):
        controller = PretrainingTrialController(
            self.params["Maximum Fixation Display (s)"]
        )
        event.clearEvents()
        self.arduino.trial_start()
        self.tracker.send_event(f"TRIALID {trial_number}")
        self.subject_win.callOnFlip(
            self.tracker.send_event,
            f"FIX_ON TRIAL {trial_number}",
        )
        self.clock.reset()
        fixation_on_wall = datetime.now().isoformat(timespec="milliseconds")
        reward_key_s = None
        decision = None
        continue_session = True

        while decision is None or not decision.fixation_finished:
            self.subject_point.draw()
            self.control_point.draw()
            self.gaze_renderer.update_and_draw()
            self.subject_win.flip()
            self.control_win.flip()

            elapsed_s = self.clock.getTime()
            keys = event.getKeys(keyList=["w", "escape"])
            if "escape" in keys:
                decision = controller.abort(elapsed_s)
                continue_session = False
                break
            elif "w" in keys:
                reward_key_s = elapsed_s
                decision = controller.press_reward(elapsed_s)
                if decision.reward_requested:
                    self.tracker.send_event(
                        f"MANUAL_REWARD TRIAL {trial_number} "
                        "DURATION_MS "
                        f"{int(self.params['Reward Duration (ms)'])}"
                    )
                    self.arduino.trial_success()
                    self.arduino.reward(
                        int(self.params["Reward Duration (ms)"])
                    )
            else:
                decision = controller.update(elapsed_s)

        if decision.result == "NoReward":
            self.tracker.send_event(f"NO_REWARD TRIAL {trial_number}")
            self.arduino.trial_nofix()
        elif decision.result == "Aborted":
            self.tracker.send_event(f"TRIAL_ABORTED {trial_number}")
        self.tracker.send_event(
            f"FIX_OFF TRIAL {trial_number} RESULT {decision.result}"
        )
        self.tracker.send_event(f"TRIAL_RESULT {decision.result}")
        self.arduino.trial_end()
        self.behavior_log.append({
            "SessionStart": self.session_wall_start,
            "SubjectID": self.params["Subject ID"],
            "Trial": trial_number,
            "FixationOnWallTime": fixation_on_wall,
            "Result": decision.result,
            "ManualReward": decision.reward_requested,
            "RewardKeyTime_s": reward_key_s,
            "RewardDuration_ms": (
                int(self.params["Reward Duration (ms)"])
                if decision.reward_requested
                else 0
            ),
            "FixationDisplayDuration_s": decision.fixation_duration_s,
            "TrialEndWallTime": datetime.now().isoformat(
                timespec="milliseconds"
            ),
        })
        return continue_session

    def run(self):
        print("\n=== EyeLink Fixation Pretraining / 盯点预训练 ===")
        print("W: manual reward / 人工给水；Esc: finish / 结束")
        trial_number = 1
        while self._draw_black_interval():
            if not self._run_trial(trial_number):
                break
            trial_number += 1


def _safe_subject_id(value):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")
    return cleaned or "subject"


def main(tracker_mode="eyelink", is_simulating=0):
    parameter_manager = FineVision_Notebook(
        task_name="PretrainingFixationTask",
        default_params=DEFAULT_PARAMS,
        parameter_groups=PARAMETER_GROUPS,
        parameter_validator=validate_pretraining_params,
    )
    if not parameter_manager.prompt_for_parameters(
        title="EyeLink Fixation Pretraining / 盯点预训练参数"
    ):
        return None
    params = parameter_manager.exp_params
    validate_pretraining_params(params)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_wall_start = datetime.now().isoformat(timespec="milliseconds")
    session_id = f"PretrainFix_{timestamp}"
    log_path = os.path.join(
        script_dir,
        f"PretrainingFixation_{_safe_subject_id(params['Subject ID'])}_"
        f"{timestamp}.csv",
    )

    tracker = None
    arduino = None
    subject_win = None
    control_win = None
    task = None
    try:
        tracker = create_tracker_runtime(
            tracker_mode,
            is_simulating=bool(is_simulating),
            session_id=session_id,
            save_dir=script_dir,
            session_t0=time.perf_counter(),
            screen_size=SCREEN_SIZE,
            qy_sample_rate=100,
        )
        tracker.send_event(
            "PRETRAINING_START NO_CALIBRATION MANUAL_REWARD_KEY W"
        )
        arduino = ArduinoController()
        subject_win = visual.Window(
            screen=int(params["Subject Screen Index"]),
            size=list(SCREEN_SIZE),
            fullscr=bool(params["Full Screen"]),
            waitBlanking=True,
            color="black",
            units="pix",
            allowGUI=False,
        )
        control_win = visual.Window(
            screen=int(params["Control Screen Index"]),
            size=[800, 450],
            fullscr=False,
            waitBlanking=False,
            color="black",
            units="pix",
            title="EyeLink Fixation Pretraining Control",
        )
        task = PretrainingFixationTask(
            subject_win,
            control_win,
            tracker,
            arduino,
            params,
            session_wall_start,
        )
        task.run()
        return log_path
    except Exception:
        traceback.print_exc()
        raise
    finally:
        if task is not None:
            pd.DataFrame(
                task.behavior_log,
                columns=LOG_COLUMNS,
            ).to_csv(
                log_path,
                index=False,
                encoding="utf-8-sig",
            )
            print(f"Behavior log saved to: {log_path}")
        if tracker is not None:
            try:
                tracker.send_event("PRETRAINING_END")
            except Exception:
                pass
        if arduino is not None:
            try:
                arduino.close()
            except Exception:
                pass
        if tracker is not None:
            try:
                tracker.close()
            except Exception:
                traceback.print_exc()
        if subject_win is not None:
            subject_win.close()
        if control_win is not None:
            control_win.close()
        core.quit()


if __name__ == "__main__":
    tracker_mode = globals().get("TRACKER_MODE_OVERRIDE", "eyelink")
    is_simulating = globals().get("IS_SIMULATING_OVERRIDE", 0)
    main(tracker_mode, is_simulating)
