"""Ivan single-dot brightness 2AFC training task."""

import math
from collections import Counter
from pathlib import Path
import os
import time
import traceback
from datetime import datetime
from SessionNaming import subject_filename, confirm_session_parameters
from multiprocessing import Queue, Value, freeze_support, get_context
from queue import Empty, Full

from psychopy import core, event, visual

from DisplayCalibration import (
    load_calibrated_gray_level,
    load_calibrated_gray_level_from_workbook,
    rgb255_to_psychopy,
)
from EyeDataLogger import GazeCsvWriter, STOP_TOKEN
from EyeLinkInSessionCalibration import run_in_session_calibration
from FineVision_Notebook import FineVision_Notebook
from IvanAdaptive import LEVELS, Schedule
from Orientation2AFCTrainingLogic import choice_accuracy_counts
from SaccadeTask import (
    EYE_TRACKER_RATE_HZ,
    IS_SIMULATING as SACCADE_IS_SIMULATING,
    MONITOR_ID_CONTROL,
    MONITOR_ID_SUBJECT,
    SaccadeTask,
    TaskAbort,
    visual_angle_to_pixels,
)
from eyetracker import create_tracker_runtime


IS_SIMULATING = SACCADE_IS_SIMULATING
TEACHING_FEEDBACK_DURATION_S = 2.0
INCORRECT_CHOICE_HOLD_S = 0.050


DEFAULT_PARAMS = {
    "Subject ID": "Ivan",
    "Random Seed": 20260803,
    "Trials per Block (N)": 40,
    "Show Post-Trial Teaching Feedback": True,
    "Give Feedback First": False,
    "First Feedback Opacity (0-1)": 1.0,
    "Reminder After Consecutive Errors (X)": 0,
    "Reminder After Trials (Y)": 0,
    "Reminder Trials (Z)": 0,
    "Wait Time (s)": 5.0,
    "Fixation Acquire Time (ms)": 150,
    "Fixation Duration (ms)": 200,
    "Fixation Position X (deg)": 0.0,
    "Fixation Position Y (deg)": 0.0,
    "Fixation Point Radius (deg)": 0.2,
    "Fix Window Radius (deg)": 1.5,
    "Choice Time (ms)": 900,
    "Correct Choice Hold Time (ms)": 500,
    "Background Gray Level (0-182)": 5,
    "Right Target Position X (deg)": 8.0,
    "Right Target Position Y (deg)": 0.0,
    "Left Target Position X (deg)": -8.0,
    "Left Target Position Y (deg)": 0.0,
    "Target Point Radius (deg)": 0.35,
    "Target Window Radius (deg)": 2.0,
    "Resume Brightness From (path)": "",
    "Probe Fraction (0-1)": 0.0,
    "Target Opacity (0-1)": 1.0,
    "Viewing Distance (cm)": 60.0,
    "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Reward Length (s)": 0.5,
    "Block Reward Length (s)": 1.5,
    "ITI (s)": 3.0,
    "Timeout (s)": 0.5,
}


PARAMETER_GROUPS = {
    "Session / Training": [
        "Subject ID",
        "Random Seed",
        "Resume Brightness From (path)",
        "Probe Fraction (0-1)",
        "Trials per Block (N)",
        "Show Post-Trial Teaching Feedback",
        "Give Feedback First",
        "First Feedback Opacity (0-1)",
        "Reminder After Consecutive Errors (X)",
        "Reminder After Trials (Y)",
        "Reminder Trials (Z)",
        "Wait Time (s)",
    ],
    "Fixation": [
        "Fixation Acquire Time (ms)",
        "Fixation Duration (ms)",
        "Fixation Position X (deg)",
        "Fixation Position Y (deg)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
    ],
    "Choice Targets": [
        "Choice Time (ms)",
        "Correct Choice Hold Time (ms)",
        "Right Target Position X (deg)",
        "Right Target Position Y (deg)",
        "Left Target Position X (deg)",
        "Left Target Position Y (deg)",
        "Target Point Radius (deg)",
        "Target Window Radius (deg)",
        "Target Opacity (0-1)",
    ],
    "Display": [
        "Background Gray Level (0-182)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
    ],
    "Reward": [
        "Reward Length (s)",
        "Block Reward Length (s)",
        "ITI (s)",
        "Timeout (s)",
    ],
}


TIME_FIELDS = [
    "Time_TrialStart",
    "Time_FixOn",
    "Time_GazeEnter",
    "Time_FixationPointOff",
    "Time_ChoiceOn",
    "Time_TargetEnter",
    "Time_ChoiceCommitted",
    "Time_ChoiceOff",
    "Time_FeedbackOn",
    "Time_FeedbackOff",
    "Time_Reward",
    "Time_BlockReward",
    "Time_End",
]


TRIAL_LOG_FIELDS = [
    "Ivan_Low", "Ivan_High", "Ivan_Mode",
    "Left_Brightness_Level", "Right_Brightness_Level", "Brightness_Delta",
    "Brightness_State_Before", "Brightness_State_After", "Brightness_Valid_Choice",
    "Trial", "Block", "Trial_In_Block", "Trials_Per_Block", "Counts_Toward_Block",
    "Block_End", "Block_Reward_Length_ms", "Block_Reward_Delivered", "Status",
    "Training_Stage", "Correct_Target", "Choice", "Choice_Correct",
    *TIME_FIELDS, "Subject_ID", "Fixation_Duration_ms", "Fixation_Acquire_Time_ms",
    "Choice_Time_ms", "Correct_Choice_Hold_Time_ms", "Incorrect_Choice_Hold_Time_ms",
    "Fixation_Pos_X_deg", "Fixation_Pos_Y_deg", "Fixation_Point_Radius_deg",
    "Fix_Window_Radius_deg", "Background_Gray_Level", "Background_Target_Luminance_cd_m2",
    "Background_Color_R", "Background_Color_G", "Background_Color_B",
    "Right_Target_Pos_X_deg", "Right_Target_Pos_Y_deg",
    "Left_Target_Pos_X_deg", "Left_Target_Pos_Y_deg", "Target_Point_Radius_deg",
    "Choice_Target_Style", "Target_Window_Radius_deg", "Target_Opacity",
    "Give_Feedback_First", "First_Feedback_Opacity", "Reminder_Feedback_Shown",
    "Reminder_Triggered_By_Errors", "Reminder_Triggered_By_Interval",
    "Reminder_Consecutive_Error_X", "Reminder_After_Trials_Y", "Reminder_Trials_Z",
    "Reminder_Error_Streak_Before_Trial", "Reminder_Trials_Since_Batch_Before_Trial",
    "Teaching_Feedback_Enabled", "Teaching_Feedback_Shown", "Teaching_Feedback_Duration_ms",
    "Random_Seed", "Viewing_Distance_cm", "Monitor_Width_cm", "Monitor_Height_cm",
]


def _validate_params(params):
    if params["Subject ID"] != "Ivan":
        raise ValueError("Subject ID must be Ivan for this training history.")
    load_calibrated_gray_level(params["Background Gray Level (0-182)"])
    for name, default in DEFAULT_PARAMS.items():
        if type(default) not in (int, float):
            continue
        value = float(params[name])
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
        if name.endswith("(deg)") and "Position" in name:
            if abs(value) >= 180:
                raise ValueError(f"{name} must be between -180 and 180 degrees.")
        elif name.endswith("(0-1)"):
            if not 0 <= value <= 1 or (name == "Target Opacity (0-1)" and value == 0):
                raise ValueError(f"Invalid value for {name}.")
        elif name.startswith(("Random Seed", "Trials per Block", "Reminder")):
            if not value.is_integer() or value < int(name.startswith("Trials")):
                raise ValueError(f"Invalid integer for {name}.")
        elif name.startswith(("Timeout", "Fixation Duration")):
            if value < 0:
                raise ValueError(f"{name} must be nonnegative.")
        elif name != "Background Gray Level (0-182)" and value <= 0:
            raise ValueError(f"{name} must be positive.")
    if float(params["Choice Time (ms)"]) < float(params["Correct Choice Hold Time (ms)"]):
        raise ValueError("Choice Time must be at least Correct Choice Hold Time.")
    dx = float(params["Right Target Position X (deg)"]) - float(params["Left Target Position X (deg)"])
    dy = float(params["Right Target Position Y (deg)"]) - float(params["Left Target Position Y (deg)"])
    radius = float(params["Target Window Radius (deg)"])
    if math.hypot(dx, dy) <= 2 * radius:
        raise ValueError("Left and right target windows must not overlap.")
    if float(params["Target Point Radius (deg)"]) > radius:
        raise ValueError("Target point must fit inside its target window.")


def _resume_path(script_dir, setting):
    setting = str(setting).strip()
    if setting.lower() == "new":
        return None
    if setting:
        path = Path(setting)
        if not path.is_absolute():
            path = Path(script_dir) / path
        return path / "Ivan_checkpoint.json" if path.is_dir() else path
    root = Path(script_dir) / "experiment_logs"
    checkpoints = list(root.glob("*/Ivan_checkpoint.json"))
    standalone = root / "Ivan_checkpoint.json"
    if standalone.is_file():
        checkpoints.append(standalone)
    return max(checkpoints, key=lambda p: p.stat().st_mtime_ns, default=None)


def _brightness_dashboard(messages, png_path, position):
    """Render in a separate process, keeping GUI work off the stimulus loop."""
    try:
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, axes = plt.subplots(2, 2, figsize=(8, 5))
        fig.canvas.manager.set_window_title("Ivan brightness training progress")
        if position is not None:
            x, y = position
            fig.canvas.manager.window.wm_geometry(f"{x:+d}{y:+d}")
        plt.show(block=False)
        last = None
        while plt.fignum_exists(fig.number):
            stop = False
            update = None
            while True:
                try:
                    update = messages.get_nowait()
                except Empty:
                    break
                last, stop = update
                if stop:
                    break
            if update is not None:
                summary, choices = last
                rate, delta, heat, mastery = axes.flat
                for ax in axes.flat:
                    ax.clear()
                x = np.arange(1, len(choices) + 1)
                cumulative = np.r_[0, np.cumsum(choices)]
                starts = np.maximum(x - 20, 0)
                rate.plot(x, (cumulative[x] - cumulative[starts]) / (x - starts),
                          label="Last 20")
                rate.plot(x, cumulative[x] / x, label="Cumulative")
                rate.set(title=f"Ivan | Training choices {len(x)} | Stage {summary['stage']}", ylim=(0, 1))
                rate.legend(fontsize=7)
                measured = [row for row in summary["by_delta"] if row["n"]]
                delta.bar([row["delta"] for row in measured],
                          [row["accuracy"] for row in measured],
                          width=summary["step"] * 0.8)
                delta.set(title="Accuracy by ΔL (level difference)", ylim=(0, 1))
                levels = list(range(10, 91, summary["step"]))
                grid = np.full((len(levels), len(levels)), np.nan)
                for row in summary["by_pair"]:
                    if row["n"]:
                        grid[levels.index(row["low"]), levels.index(row["high"])] = row["accuracy"]
                heat.imshow(grid, origin="lower", vmin=0, vmax=1)
                tick = list(range(0, len(levels), 10 // summary["step"]))
                labels = [levels[i] for i in tick]
                heat.set(title="Pair accuracy (0–100%)", xlabel="High", ylabel="Low",
                         xticks=tick, yticks=tick, xticklabels=labels, yticklabels=labels)
                states = Counter(row["state"] for row in summary["by_pair"])
                names = ["Untested", "Training", "Difficult", "Provisional", "Confirmed"]
                mastery.barh(names, [states[name] for name in names])
                mastery.set(title="Mastery by pair", xlim=(0, len(summary["by_pair"])))
                fig.tight_layout()
                fig.canvas.draw_idle()
                if stop:
                    fig.savefig(png_path, dpi=140)
                    return
            plt.pause(0.1)
    except Exception:
        traceback.print_exc()


class IvanBrightness2AFCTrainingTask(SaccadeTask):
    """Maintain fixation and select the brighter of two single dots."""

    task_display_name = "Ivan Brightness 2AFC Training Task"
    mapping_description = (
        "Choose the brighter target."
    )

    def _task_log_filename(self):
        return f"Ivan_Brightness2AFC_task_log_{self.session_timestamp}.csv"

    def _trial_log_fields(self):
        return TRIAL_LOG_FIELDS

    def _validate_current_params(self, params):
        _validate_params(params)

    def _tracker_trial_variable_fields(self):
        return (
            "Subject_ID", "Ivan_Low", "Ivan_High", "Ivan_Mode",
            "Training_Stage", "Brightness_State_Before", "Block", "Trial_In_Block",
            "Left_Brightness_Level", "Right_Brightness_Level", "Correct_Target",
            "Fixation_Acquire_Time_ms", "Fixation_Duration_ms", "Choice_Time_ms",
            "Correct_Choice_Hold_Time_ms",
        )

    def _mark_time(self, trial_data, field):
        if trial_data[field] is not None:
            return
        trial_data[field] = self.now()
        tracker_event = {
            "Time_FixOn": "FIX_ON",
            "Time_FixationPointOff": "FIX_OFF",
            "Time_ChoiceOn": "CHOICE_ON",
            "Time_ChoiceOff": "CHOICE_OFF",
            "Time_FeedbackOn": "FEEDBACK_ON",
            "Time_FeedbackOff": "FEEDBACK_OFF",
        }.get(field)
        if tracker_event is not None:
            self._send_tracker_event(
                f"{tracker_event} TRIAL {trial_data['Trial']}"
            )

    def _configure_reminder_schedule(self, error_x, after_y, for_z):
        """Apply reminder parameters, resetting counters only when they change."""
        config = (int(error_x), int(after_y), int(for_z))
        if getattr(self, "_reminder_config", None) == config:
            return

        self._reminder_config = config
        (
            self.reminder_after_consecutive_errors,
            self.reminder_after_trials,
            self.reminder_trials,
        ) = config
        self._reminder_error_streak = 0
        self._reminder_error_pending = False
        self._reminder_trials_since_batch = 0
        self._reminder_interval_remaining = 0
        self._reminder_feedback_active = False
        self._reminder_triggered_by_errors = False
        self._reminder_triggered_by_interval = False

    def _begin_trial_reminder(self):
        """Select the independent error- and interval-based reminder sources."""
        self._reminder_error_streak_before_trial = self._reminder_error_streak
        self._reminder_trials_since_batch_before_trial = (
            self._reminder_trials_since_batch
        )

        error_due = bool(
            self.reminder_after_consecutive_errors > 0
            and self._reminder_error_pending
        )
        if error_due:
            self._reminder_error_pending = False

        interval_due = False
        if self.reminder_after_trials > 0 and self.reminder_trials > 0:
            if (
                self._reminder_interval_remaining == 0
                and self._reminder_trials_since_batch
                >= self.reminder_after_trials
            ):
                self._reminder_interval_remaining = self.reminder_trials
                self._reminder_trials_since_batch = 0
            if self._reminder_interval_remaining > 0:
                interval_due = True
                self._reminder_interval_remaining -= 1

        self._reminder_triggered_by_errors = error_due
        self._reminder_triggered_by_interval = interval_due
        self._reminder_feedback_active = error_due or interval_due

    def _record_trial_for_reminders(self, trial_data):
        """Update the two reminder counters independently after a trial."""
        reminder_shown = trial_data.get("Reminder_Feedback_Shown", False)
        interval_triggered = trial_data.get(
            "Reminder_Triggered_By_Interval",
            False,
        )
        if interval_triggered and not reminder_shown:
            # A pre-choice abort must not consume one of the Z visible reminders.
            self._reminder_interval_remaining += 1
        elif not interval_triggered:
            self._reminder_trials_since_batch += 1

        if (
            trial_data.get("Reminder_Triggered_By_Errors", False)
            and not reminder_shown
        ):
            # Keep the error reminder pending until a choice display is reached.
            self._reminder_error_pending = True

        choice_correct = trial_data.get("Choice_Correct")
        if choice_correct is True:
            self._reminder_error_streak = 0
        elif choice_correct is False:
            self._reminder_error_streak += 1
            if (
                self.reminder_after_consecutive_errors > 0
                and self._reminder_error_streak
                >= self.reminder_after_consecutive_errors
            ):
                self._reminder_error_pending = True
                self._reminder_error_streak = 0

    def update_params(self):
        params = self.task_manager.exp_params
        self._validate_current_params(params)

        self.subject_id = "Ivan"
        self.random_seed = int(params["Random Seed"])
        self.probe_fraction = float(params["Probe Fraction (0-1)"])
        configured_trials_per_block = int(params["Trials per Block (N)"])
        locked_trials_per_block = getattr(
            self,
            "_locked_trials_per_block",
            None,
        )
        if locked_trials_per_block is not None:
            configured_trials_per_block = int(locked_trials_per_block)
            params["Trials per Block (N)"] = configured_trials_per_block
        self.trials_per_block = configured_trials_per_block
        self.show_teaching_feedback = bool(
            params["Show Post-Trial Teaching Feedback"]
        )
        self.give_feedback_first = bool(params["Give Feedback First"])
        self.first_feedback_opacity = float(
            params["First Feedback Opacity (0-1)"]
        )
        self._configure_reminder_schedule(
            int(params["Reminder After Consecutive Errors (X)"]),
            int(params["Reminder After Trials (Y)"]),
            int(params["Reminder Trials (Z)"]),
        )
        self.wait_time_s = float(params["Wait Time (s)"])
        self.fix_acquire_s = float(params["Fixation Acquire Time (ms)"]) / 1000
        self.fix_x_deg = float(params["Fixation Position X (deg)"])
        self.fix_y_deg = float(params["Fixation Position Y (deg)"])
        self.fix_point_radius_deg = float(params["Fixation Point Radius (deg)"])
        self.fix_radius_deg = float(params["Fix Window Radius (deg)"])

        self.fix_duration_s = float(params["Fixation Duration (ms)"]) / 1000
        self.choice_time_s = float(params["Choice Time (ms)"]) / 1000
        self.correct_choice_hold_s = (
            float(params["Correct Choice Hold Time (ms)"]) / 1000
        )

        background = load_calibrated_gray_level(
            params["Background Gray Level (0-182)"]
        )
        self.background_gray_level = background["level"]
        self.background_rgb_255 = background["rgb_255"]
        self.background_target_luminance = background["luminance_cd_m2"]
        self.background_psychopy_color = tuple(
            rgb255_to_psychopy(self.background_rgb_255)
        )
        self.win_sub.color = self.background_psychopy_color
        self.win_ctl.color = self.background_psychopy_color

        self.target_positions_deg = {
            "Right": (
                float(params["Right Target Position X (deg)"]),
                float(params["Right Target Position Y (deg)"]),
            ),
            "Left": (
                float(params["Left Target Position X (deg)"]),
                float(params["Left Target Position Y (deg)"]),
            ),
        }
        self.target_point_radius_deg = float(params["Target Point Radius (deg)"])
        self.target_window_radius_deg = float(params["Target Window Radius (deg)"])
        if not hasattr(self, "brightness"):
            self.brightness = self.task_manager.ivan_schedule
            self.brightness_calibration = {
                level: tuple(rgb255_to_psychopy(
                    load_calibrated_gray_level_from_workbook(level)["rgb_255"]
                ))
                for level in LEVELS
            }
        self.target_opacity = float(params["Target Opacity (0-1)"])

        self.viewing_distance_cm = float(params["Viewing Distance (cm)"])
        self.monitor_width_cm = float(params["Subject Monitor Width (cm)"])
        self.monitor_height_cm = float(params["Subject Monitor Height (cm)"])
        self.reward_len_s = float(params["Reward Length (s)"])
        self.block_reward_len_s = float(params["Block Reward Length (s)"])
        self.iti_s = float(params["ITI (s)"])
        self.timeout_s = float(params["Timeout (s)"])

        self.fix_x_px = self._to_x_pixels(self.fix_x_deg)
        self.fix_y_px = self._to_y_pixels(self.fix_y_deg)
        self.fix_point_radius_px = self._to_x_pixels(self.fix_point_radius_deg)
        self.fix_radius_px = self._to_x_pixels(self.fix_radius_deg)
        self.target_point_radius_px = self._to_x_pixels(self.target_point_radius_deg)
        self.target_window_radius_px = self._to_x_pixels(
            self.target_window_radius_deg
        )
        self.target_positions_px = {
            name: (self._to_x_pixels(x_deg), self._to_y_pixels(y_deg))
            for name, (x_deg, y_deg) in self.target_positions_deg.items()
        }
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
            pos=(self.fix_x_px * self.scale_x, self.fix_y_px * self.scale_y),
        )
        self.fix_window_ctl = visual.Circle(
            self.win_ctl,
            radius=self.fix_radius_px * self.scale_x,
            fillColor=None,
            lineColor="red",
            lineWidth=2,
            pos=(self.fix_x_px * self.scale_x, self.fix_y_px * self.scale_y),
        )

        self.target_sub = {}
        self.target_ctl = {}
        self.target_window_ctl = {}
        for name, (x_px, y_px) in self.target_positions_px.items():
            self.target_sub[name] = visual.Circle(
                self.win_sub,
                radius=self.target_point_radius_px,
                fillColor="white",
                lineColor="white",
                pos=(x_px, y_px),
            )
            self.target_ctl[name] = visual.Circle(
                self.win_ctl,
                radius=self.target_point_radius_px * self.scale_x,
                fillColor="white",
                lineColor="white",
                pos=(x_px * self.scale_x, y_px * self.scale_y),
            )
            self.target_window_ctl[name] = visual.Circle(
                self.win_ctl,
                radius=self.target_window_radius_px * self.scale_x,
                fillColor=None,
                lineColor="cyan",
                lineWidth=2,
                pos=(x_px * self.scale_x, y_px * self.scale_y),
            )

    def _poll_training_commands(self):
        keys = event.getKeys()
        escape_suppressed_until = float(
            getattr(self, "_escape_suppressed_until", 0.0)
        )
        if (
            "escape" in keys
            and time.perf_counter() >= escape_suppressed_until
        ):
            raise TaskAbort()

        return "n" in keys

    def _required_choice_hold_s(self, target_name, correct_target):
        if target_name == correct_target:
            return self.correct_choice_hold_s
        return INCORRECT_CHOICE_HOLD_S

    def _draw_choice_target(self, name, highlight=False):
        color = self.choice_colors[name]
        for dot in (self.target_sub[name], self.target_ctl[name]):
            dot.fillColor = color
            dot.lineColor = color
            dot.opacity = self.target_opacity
            dot.draw()
        window = self.target_window_ctl[name]
        window.lineColor = "yellow" if highlight else "cyan"
        window.opacity = self.first_feedback_opacity if highlight else 1
        window.draw()

    def _first_feedback_during_choice(self):
        return self.give_feedback_first or getattr(
            self,
            "_reminder_feedback_active",
            False,
        )

    def _present_training_frame(
        self, *, fix_visible=False, fix_window_active=False,
        correct_target="Right", targets_visible=False,
        first_feedback=False, teaching_feedback=False,
    ):
        gaze = self.gaze_renderer.update()
        if fix_visible:
            self.fix_sub.draw()
            self.fix_ctl.draw()
        if fix_window_active:
            self.fix_window_ctl.draw()
        if targets_visible:
            for name in ("Left", "Right"):
                self._draw_choice_target(
                    name, name == correct_target and (first_feedback or teaching_feedback)
                )
        self.gaze_renderer.draw()
        self.win_sub.flip()
        self.win_ctl.flip()
        return gaze, self._poll_training_commands()

    def _new_trial_data(
        self,
        trial_number,
        pair,
        mode,
        completed_trials_before=None,
    ):
        left, right = self.brightness_levels
        correct_target = "Right" if right > left else "Left"
        if completed_trials_before is None:
            completed_trials_before = trial_number - 1
        block_number, trial_in_block = self._block_position(
            completed_trials_before
        )
        return {
            "Ivan_Low": pair[0],
            "Ivan_High": pair[1],
            "Ivan_Mode": mode,
            "Left_Brightness_Level": left,
            "Right_Brightness_Level": right,
            "Brightness_Delta": abs(right - left),
            "Brightness_State_Before": self.brightness.pairs[pair]["status"],
            "Brightness_State_After": None,
            "Brightness_Valid_Choice": False,
            "Trial": trial_number,
            "Block": block_number,
            "Trial_In_Block": trial_in_block,
            "Trials_Per_Block": self.trials_per_block,
            "Counts_Toward_Block": False,
            "Block_End": False,
            "Block_Reward_Length_ms": self.block_reward_len_s * 1000,
            "Block_Reward_Delivered": False,
            "Status": None,
            "Training_Stage": "ABC"[self.brightness.stage],
            "Correct_Target": correct_target,
            "Choice": "",
            "Choice_Correct": "",
            **{field: None for field in TIME_FIELDS},
            "Subject_ID": self.subject_id,
            "Fixation_Duration_ms": self.fix_duration_s * 1000,
            "Fixation_Acquire_Time_ms": self.fix_acquire_s * 1000,
            "Choice_Time_ms": self.choice_time_s * 1000,
            "Correct_Choice_Hold_Time_ms": (
                self.correct_choice_hold_s * 1000
            ),
            "Incorrect_Choice_Hold_Time_ms": (
                INCORRECT_CHOICE_HOLD_S * 1000
            ),
            "Fixation_Pos_X_deg": self.fix_x_deg,
            "Fixation_Pos_Y_deg": self.fix_y_deg,
            "Fixation_Point_Radius_deg": self.fix_point_radius_deg,
            "Fix_Window_Radius_deg": self.fix_radius_deg,
            "Background_Gray_Level": self.background_gray_level,
            "Background_Target_Luminance_cd_m2": (
                self.background_target_luminance
            ),
            "Background_Color_R": self.background_rgb_255[0],
            "Background_Color_G": self.background_rgb_255[1],
            "Background_Color_B": self.background_rgb_255[2],
            "Right_Target_Pos_X_deg": self.target_positions_deg["Right"][0],
            "Right_Target_Pos_Y_deg": self.target_positions_deg["Right"][1],
            "Left_Target_Pos_X_deg": self.target_positions_deg["Left"][0],
            "Left_Target_Pos_Y_deg": self.target_positions_deg["Left"][1],
            "Target_Point_Radius_deg": self.target_point_radius_deg,
            "Choice_Target_Style": "Single_Dot",
            "Target_Window_Radius_deg": self.target_window_radius_deg,
            "Target_Opacity": self.target_opacity,
            "Give_Feedback_First": self.give_feedback_first,
            "First_Feedback_Opacity": self.first_feedback_opacity,
            "Reminder_Feedback_Shown": False,
            "Reminder_Triggered_By_Errors": getattr(
                self,
                "_reminder_triggered_by_errors",
                False,
            ),
            "Reminder_Triggered_By_Interval": getattr(
                self,
                "_reminder_triggered_by_interval",
                False,
            ),
            "Reminder_Consecutive_Error_X": getattr(
                self,
                "reminder_after_consecutive_errors",
                0,
            ),
            "Reminder_After_Trials_Y": getattr(
                self,
                "reminder_after_trials",
                0,
            ),
            "Reminder_Trials_Z": getattr(self, "reminder_trials", 0),
            "Reminder_Error_Streak_Before_Trial": getattr(
                self,
                "_reminder_error_streak_before_trial",
                0,
            ),
            "Reminder_Trials_Since_Batch_Before_Trial": getattr(
                self,
                "_reminder_trials_since_batch_before_trial",
                0,
            ),
            "Teaching_Feedback_Enabled": self.show_teaching_feedback,
            "Teaching_Feedback_Shown": False,
            "Teaching_Feedback_Duration_ms": (
                TEACHING_FEEDBACK_DURATION_S * 1000
            ),
            "Random_Seed": self.random_seed,
            "Viewing_Distance_cm": self.viewing_distance_cm,
            "Monitor_Width_cm": self.monitor_width_cm,
            "Monitor_Height_cm": self.monitor_height_cm,
        }

    def _block_position(self, completed_trials_before):
        return (
            completed_trials_before // self.trials_per_block + 1,
            completed_trials_before % self.trials_per_block + 1,
        )

    def _apply_trial_outcome_to_block(self, trial_data, status):
        counts_toward_block = status == "Success"
        trial_in_block = trial_data.get("Trial_In_Block")
        trials_per_block = getattr(self, "trials_per_block", None)
        trial_data["Counts_Toward_Block"] = counts_toward_block
        trial_data["Block_End"] = (
            counts_toward_block
            and trial_in_block is not None
            and trials_per_block is not None
            and trial_in_block == trials_per_block
        )
        return counts_toward_block

    def _wait_for_fixation(self, trial_data):
        candidate_start = None
        wait_start = self.now()
        pause_requested = False
        correct_target = trial_data["Correct_Target"]

        while self.now() - wait_start < self.wait_time_s:
            gaze, requested = self._present_training_frame(
                fix_visible=True,
                fix_window_active=True,
                correct_target=correct_target,
            )
            pause_requested = pause_requested or requested
            detected_at = self.now()
            if self._in_window(
                gaze,
                self.fix_x_px,
                self.fix_y_px,
                self.fix_radius_px,
            ):
                if candidate_start is None:
                    candidate_start = detected_at
                elif detected_at - candidate_start >= self.fix_acquire_s:
                    trial_data["Time_GazeEnter"] = candidate_start
                    self._send_tracker_event(
                        f"GAZE_ACQUIRED TRIAL {trial_data['Trial']}"
                    )
                    return detected_at, pause_requested
            else:
                candidate_start = None
        return None, pause_requested

    def _hold_fixation(self, fixation_start):
        pause_requested = False
        while self.now() - fixation_start < self.fix_duration_s:
            gaze, requested = self._present_training_frame(
                fix_visible=True,
                fix_window_active=True,
            )
            pause_requested = pause_requested or requested
            if not self._in_window(
                gaze,
                self.fix_x_px,
                self.fix_y_px,
                self.fix_radius_px,
            ):
                return False, pause_requested
        return True, pause_requested

    def _show_choice_onset(self, trial_data):
        reminder_feedback = self._first_feedback_during_choice()
        trial_data["Reminder_Feedback_Shown"] = reminder_feedback
        if reminder_feedback:
            sources = []
            if self.give_feedback_first:
                sources.append("MANUAL")
            if trial_data.get("Reminder_Triggered_By_Errors"):
                sources.append("ERRORS")
            if trial_data.get("Reminder_Triggered_By_Interval"):
                sources.append("INTERVAL")
            self._send_tracker_event(
                "PRE_CHOICE_REMINDER "
                f"SOURCES {'+'.join(sources) or 'UNKNOWN'} "
                f"TRIAL {trial_data.get('Trial', 'UNKNOWN')}"
            )
        self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        self._schedule_flip_time(trial_data, "Time_ChoiceOn")
        return self._present_training_frame(
            targets_visible=True,
            correct_target=trial_data["Correct_Target"],
            first_feedback=reminder_feedback,
        )

    def _run_choice(self, trial_data, initial_gaze, initial_pause):
        candidate_target = None
        candidate_start = None
        ever_entered = False
        pause_requested = initial_pause
        gaze = initial_gaze
        visible_targets = ("Left", "Right")

        while self.now() - trial_data["Time_ChoiceOn"] < self.choice_time_s:
            detected_at = self.now()
            entered_target = None
            for target_name in visible_targets:
                target_x, target_y = self.target_positions_px[target_name]
                if self._in_window(
                    gaze,
                    target_x,
                    target_y,
                    self.target_window_radius_px,
                ):
                    entered_target = target_name
                    break

            if entered_target is None:
                candidate_target = None
                candidate_start = None
            elif entered_target != candidate_target:
                candidate_target = entered_target
                candidate_start = detected_at
                ever_entered = True
                if trial_data["Time_TargetEnter"] is None:
                    trial_data["Time_TargetEnter"] = detected_at
                    self._send_tracker_event(
                        f"TARGET_ENTER {entered_target.upper()} "
                        f"TRIAL {trial_data['Trial']}"
                    )
            elif detected_at - candidate_start >= self._required_choice_hold_s(
                candidate_target,
                trial_data["Correct_Target"],
            ):
                trial_data["Time_ChoiceCommitted"] = detected_at
                trial_data["Choice"] = candidate_target
                is_correct = candidate_target == trial_data["Correct_Target"]
                trial_data["Choice_Correct"] = is_correct
                self._send_tracker_event(
                    f"CHOICE {candidate_target.upper()} "
                    f"TRIAL {trial_data['Trial']}"
                )
                return (
                    "Success" if is_correct else "Incorrect",
                    pause_requested,
                )

            gaze, requested = self._present_training_frame(
                targets_visible=True,
                correct_target=trial_data["Correct_Target"],
                first_feedback=self._first_feedback_during_choice(),
            )
            pause_requested = pause_requested or requested

        return ("Break_Choice" if ever_entered else "NoChoice"), pause_requested

    def _black_out_training(self, trial_data):
        if trial_data["Time_FixOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_ChoiceOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_ChoiceOff")
        self._present_training_frame()

    def _teaching_feedback_is_due(self, trial_data):
        return bool(
            self.show_teaching_feedback
            and trial_data["Time_ChoiceOn"] is not None
            and trial_data.get("Choice") in ("Right", "Left")
        )

    def _run_teaching_feedback(self, trial_data, after_first_flip=None):
        """Replay the choice, running an optional action after its first flip."""
        if not self._teaching_feedback_is_due(trial_data):
            self._black_out_training(trial_data)
            if after_first_flip is not None:
                after_first_flip()
            return False


        if trial_data["Time_FixOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_ChoiceOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_ChoiceOff")
        self._schedule_flip_time(trial_data, "Time_FeedbackOn")
        trial_data["Teaching_Feedback_Shown"] = True

        pause_requested = False
        first_frame_presented = False
        while (
            trial_data["Time_FeedbackOn"] is None
            or self.now() - trial_data["Time_FeedbackOn"]
            < TEACHING_FEEDBACK_DURATION_S
        ):
            _, requested = self._present_training_frame(
                correct_target=trial_data["Correct_Target"],
                targets_visible=True,
                teaching_feedback=True,
            )
            pause_requested = pause_requested or requested
            if not first_frame_presented:
                first_frame_presented = True
                if after_first_flip is not None:
                    after_first_flip()

        self._schedule_flip_time(trial_data, "Time_FeedbackOff")
        _, requested = self._present_training_frame()
        return pause_requested or requested

    def _deliver_block_reward_if_due(self, trial_data):
        if not trial_data.get("Block_End", False):
            return False

        duration_ms = int(self.block_reward_len_s * 1000)
        trial_data["Time_BlockReward"] = self.now()
        trial_data["Block_Reward_Delivered"] = True
        self._send_tracker_event(
            f"BLOCK_REWARD BLOCK {trial_data['Block']} "
            f"TRIAL {trial_data['Trial']} DURATION_MS {duration_ms}"
        )
        print(
            f"[Block {trial_data['Block']}] Completed "
            f"{self.trials_per_block} trials; extra reward {duration_ms} ms."
        )
        self.arduino.reward(duration_ms)
        return True

    def _run_one_trial(self, trial_number, completed_trials_before=None):
        pair, mode, bright_side = self.brightness.select(self.probe_fraction)
        low, high = pair
        left, right = (low, high) if bright_side == "Right" else (high, low)
        self.brightness_levels = left, right
        self.choice_colors = {
            "Left": self.brightness_calibration[left],
            "Right": self.brightness_calibration[right],
        }
        self._begin_trial_reminder()
        trial_data = self._new_trial_data(
            trial_number, pair, mode, completed_trials_before=completed_trials_before
        )
        event.clearEvents()
        self.gaze_renderer.reset_trail()
        self._send_tracker_event(f"TRIALID {trial_number}")
        self._send_tracker_event("SUBJECT Ivan")
        for field in self._tracker_trial_variable_fields():
            self._send_tracker_event(
                f"!V TRIAL_VAR {field} {trial_data[field]}"
            )

        self.arduino.trial_start()
        trial_data["Time_TrialStart"] = self.now()
        self._schedule_flip_time(trial_data, "Time_FixOn")
        _, pause_requested = self._present_training_frame(
            fix_visible=True,
            fix_window_active=True,
            correct_target=trial_data["Correct_Target"],
        )

        fixation_start, requested = self._wait_for_fixation(trial_data)
        pause_requested = pause_requested or requested
        if fixation_start is None:
            status = "NoFix"
        else:
            held, requested = self._hold_fixation(fixation_start)
            pause_requested = pause_requested or requested
            if not held:
                status = "Break_Fix"
            else:
                # Brightness task: fixation -> immediate two-choice brightness judgement
                gaze, requested = self._show_choice_onset(trial_data)
                status, requested = self._run_choice(
                    trial_data,
                    gaze,
                    requested,
                )
                pause_requested = pause_requested or requested

        reward_after_first_flip = None
        if status == "Success":
            def reward_after_first_flip():
                self.arduino.trial_success()
                trial_data["Time_Reward"] = self.now()
                self._send_tracker_event(f"REWARD TRIAL {trial_number}")
                self.arduino.reward(int(self.reward_len_s * 1000))
        elif status in ("Incorrect", "Break_Fix", "Break_Choice"):
            self.arduino.trial_break()
        else:
            self.arduino.trial_nofix()

        requested = self._run_teaching_feedback(
            trial_data,
            after_first_flip=reward_after_first_flip,
        )
        pause_requested = pause_requested or requested
        if status in ("Incorrect", "Break_Fix", "Break_Choice"):
            core.wait(self.timeout_s)

        self.arduino.trial_end()
        trial_data["Status"] = status
        self._apply_trial_outcome_to_block(trial_data, status)
        self._deliver_block_reward_if_due(trial_data)
        trial_data["Time_End"] = self.now()
        self._record_trial_for_reminders(trial_data)
        self._send_tracker_event(f"!V TRIAL_VAR Status {status}")
        self._send_tracker_event(
            f"!V TRIAL_VAR Choice {trial_data['Choice'] or 'None'}"
        )
        self._send_tracker_event(f"TRIAL_RESULT {status}")
        return trial_data, pause_requested

    def _write_trial(self, trial_data):
        pair = trial_data["Ivan_Low"], trial_data["Ivan_High"]
        valid = trial_data["Status"] in ("Success", "Incorrect")
        self.brightness.record({
            "Session": self.session_timestamp,
            **{field: trial_data[field] for field in
               ("Trial", "Status", "Ivan_Low", "Ivan_High", "Ivan_Mode", "Choice")},
        })
        self.brightness.save()
        trial_data["Brightness_Valid_Choice"] = valid
        trial_data["Brightness_State_After"] = self.brightness.pairs[pair]["status"]
        csv_row = trial_data.copy()
        for field in TIME_FIELDS:
            if csv_row[field] is not None:
                csv_row[field] = f"{float(csv_row[field]):.6f}"
        self.behavior_log.append(trial_data.copy())
        self.trial_logger.write(csv_row)
        if valid:
            self._publish_brightness()

    def _publish_brightness(self, stop=False):
        if getattr(self, "dashboard_queue", None) is None:
            return
        try:
            payload = (self.brightness.summary(), self.brightness.training_choices())
            self.dashboard_queue.put_nowait((payload, stop))
        except Full:
            pass

    def _run_iti(self):
        iti_start = self.now()
        while self.now() - iti_start < self.iti_s:
            _, pause_requested = self._present_training_frame()
            if pause_requested:
                return True
        return False

    def _prompt_for_parameters(self):
        return self.task_manager.prompt_for_parameters()

    def _prompt_for_runtime_parameters(self):
        return self.task_manager.prompt_for_runtime_parameters(
            title="Runtime Parameters / 运行中参数",
            disabled_parameters={"Trials per Block (N)", "Random Seed", "Subject ID",
                                 "Resume Brightness From (path)"},
            allow_recalibration=bool(
                getattr(
                    self.tracker_backend,
                    "supports_recalibration",
                    False,
                )
            ),
            notice="Trials per Block (N) is locked after the task starts.",
        )

    def _recalibrate_eyelink(self):
        """Pause this task, calibrate on the subject display, then resume."""
        self._send_tracker_event("FINEVISION_PAUSE_ACTION RECALIBRATE")
        run_in_session_calibration(
            tracker_backend=self.tracker_backend,
            win_subject=self.win_sub,
            win_control=self.win_ctl,
            background_color=self.background_psychopy_color,
            viewing_distance_cm=self.viewing_distance_cm,
            monitor_width_cm=self.monitor_width_cm,
            monitor_height_cm=self.monitor_height_cm,
            fixation_point_radius_deg=self.fix_point_radius_deg,
            arduino=self.arduino,
            subject_screen_index=MONITOR_ID_SUBJECT,
            blank_callback=lambda: self._present_training_frame(),
        )
        self._suppress_calibration_escape()
        self._send_tracker_event("FINEVISION_RECALIBRATION_RETURN_TO_TASK")
        self.gaze_renderer.reset_trail()
        event.clearEvents()

    def _deliver_resume_reward(self, pause_action):
        duration_ms = int(self.reward_len_s * 1000)
        self._send_tracker_event(
            f"TASK_RESUME_REWARD ACTION {str(pause_action).upper()} "
            f"DURATION_MS {duration_ms}"
        )
        print(f"[Resume] Task restarting; reward {duration_ms} ms.")
        self.arduino.reward(duration_ms)

    def _resume_from_runtime_pause(self):
        self._present_training_frame()
        pause_action = self._prompt_for_runtime_parameters()
        if pause_action == "cancel":
            self._send_tracker_event(
                "FINEVISION_PAUSE_ACTION CANCEL_EDITS_CONTINUE"
            )
        else:
            self.update_params()
            if pause_action == "recalibrate":
                self._recalibrate_eyelink()
            else:
                self._send_tracker_event(
                    "FINEVISION_PAUSE_ACTION CONFIRM_CONTINUE"
                )
        event.clearEvents()
        self._deliver_resume_reward(pause_action)
        return pause_action

    def run_task(self):
        if (
            not getattr(self.task_manager, "session_parameters_confirmed", False)
            and not self._prompt_for_parameters()
        ):
            raise TaskAbort()
        self.update_params()
        self._locked_trials_per_block = self.trials_per_block
        self._publish_brightness()
        event.clearEvents()

        print(f"\n=== {self.task_display_name} started ===")
        print(self.mapping_description)
        print(
            "Press Esc to quit; press N to edit parameters or recalibrate "
            "before the next trial."
        )
        print(
            f"Blocks contain {self.trials_per_block} trials; block reward "
            f"is {self.block_reward_len_s:.3f} s."
        )
        trial_number = 1
        completed_trials = 0
        pause_requested = False
        while True:
            if pause_requested:
                self._resume_from_runtime_pause()
                pause_requested = False

            if self._run_iti():
                pause_requested = True
                continue

            print(
                f"\n--- Trial {trial_number} | "
                f"Block {completed_trials // self.trials_per_block + 1}, "
                f"{completed_trials % self.trials_per_block + 1}/"
                f"{self.trials_per_block} | Ivan stage {'ABC'[self.brightness.stage]} ---"
            )
            trial_data, requested = self._run_one_trial(
                trial_number,
                completed_trials_before=completed_trials,
            )
            self._write_trial(trial_data)
            pause_requested = pause_requested or requested
            if trial_data["Counts_Toward_Block"]:
                completed_trials += 1

            total_correct, total_choices = choice_accuracy_counts(
                self.behavior_log
            )
            recent_correct, recent_choices = choice_accuracy_counts(
                self.behavior_log,
                recent_limit=20,
            )
            print(
                f"Result: {trial_data['Status']} | "
                f"levels={trial_data['Ivan_Low']}/{trial_data['Ivan_High']} | "
                f"choice={trial_data['Choice'] or 'none'}"
            )
            print(
                f"Total trials: {len(self.behavior_log)} | "
                f"completed choices: {total_choices}"
            )
            if total_choices:
                print(
                    f"Total choice accuracy: "
                    f"{total_correct / total_choices:.1%} "
                    f"({total_correct}/{total_choices})"
                )
                print(
                    "Recent choice accuracy (last 20 completed choices): "
                    f"{recent_correct / recent_choices:.1%} "
                    f"({recent_correct}/{recent_choices})"
                )
            trial_number += 1


def _create_session_dir(script_dir, session_prefix="IvanBrightness2AFC", subject_id="Ivan"):
    # This shared filename suffix includes the confirmed subject and start time.
    timestamp = (
        subject_filename(subject_id) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    base = os.path.join(
        script_dir,
        "experiment_logs",
        f"{session_prefix}_{timestamp}",
    )
    candidate = base
    suffix = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{suffix:03d}"
        suffix += 1
    os.makedirs(candidate)
    return timestamp + candidate[len(base):], candidate


def main(
    tracker_mode="qy",
    *,
    task_class=IvanBrightness2AFCTrainingTask,
    task_name="IvanBrightness2AFCTrainingTask",
    default_params=DEFAULT_PARAMS,
    parameter_groups=PARAMETER_GROUPS,
    parameter_validator=_validate_params,
    session_prefix="IvanBrightness2AFC",
    control_title="Ivan Brightness 2AFC",
    task_label="Ivan Brightness 2AFC training",
):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    task_manager = FineVision_Notebook(
        task_name=task_name,
        default_params=default_params,
        parameter_groups=parameter_groups,
        parameter_validator=parameter_validator,
    )
    if not confirm_session_parameters(task_manager):
        return
    resume = _resume_path(script_dir, task_manager.exp_params["Resume Brightness From (path)"])
    # Validate and replay history before creating the session or opening hardware.
    schedule = Schedule(script_dir, int(task_manager.exp_params["Random Seed"]), resume)
    session_timestamp, save_dir = _create_session_dir(
        script_dir,
        session_prefix=session_prefix,
        subject_id=task_manager.exp_params["Subject ID"],
    )
    schedule.folder = Path(save_dir)
    task_manager.ivan_schedule = schedule
    if resume:
        print(f"[Ivan] Restored {schedule.n} valid training choices from {resume}")
    session_t0 = time.perf_counter()

    save_gaze_csv = str(tracker_mode).lower() != "eyelink"
    gaze_log_queue = Queue(maxsize=20000) if save_gaze_csv else None
    dropped_samples = Value("i", 0)
    gaze_writer = None
    if save_gaze_csv:
        gaze_log_path = os.path.join(
            save_dir,
            f"{session_prefix}_eye_log_{session_timestamp}.csv",
        )
        gaze_writer = GazeCsvWriter(gaze_log_queue, gaze_log_path)
        gaze_writer.start()

    tracker_runtime = None
    win_subject = None
    win_control = None
    task = None
    dashboard = None

    try:
        tracker_runtime = create_tracker_runtime(
            tracker_mode,
            is_simulating=bool(IS_SIMULATING),
            session_id=f"{session_prefix}_{session_timestamp}",
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
            size=[800, 450],
            fullscr=False,
            waitBlanking=False,
            color="black",
            units="pix",
            title=f"{control_title} Control ({tracker_runtime.mode})",
        )

        task = task_class(
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
        dashboard_context = get_context("spawn")
        task.dashboard_queue = dashboard_context.Queue(maxsize=8)
        position = None
        get_location = getattr(win_control.winHandle, "get_location", None)
        if get_location is not None:
            x, y = get_location()
            position = (x, y + 55)
        dashboard = dashboard_context.Process(
            target=_brightness_dashboard,
            args=(task.dashboard_queue, os.path.join(save_dir, "Ivan_brightness_dashboard.png"), position),
            daemon=True,
        )
        dashboard.start()
        task.run_task()

    except (TaskAbort, SystemExit):
        print(f"{task_label} stopped by user.")
    except Exception as exc:
        print(f"{task_label} error: {exc}")
        traceback.print_exc()
    finally:
        if task is not None:
            try:
                task.close()
            except Exception:
                traceback.print_exc()
        if task is not None and hasattr(task, "brightness"):
            try:
                task.brightness.export()
            except Exception:
                print("[Ivan] CSV export failed. Training history is in Ivan_checkpoint.json.")
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
        if dashboard is not None and dashboard.pid is not None:
            if dashboard.is_alive() and hasattr(task, "brightness"):
                try:
                    final = (task.brightness.summary(), task.brightness.training_choices())
                    task.dashboard_queue.put((final, True), timeout=2)
                except Full:
                    print("[Warning] Dashboard did not accept the final update.")
            dashboard.join(timeout=8)
            if dashboard.is_alive():
                dashboard.terminate()
                dashboard.join(timeout=2)
            task.dashboard_queue.cancel_join_thread()
            task.dashboard_queue.close()
        if win_subject is not None:
            win_subject.close()
        if win_control is not None:
            win_control.close()
        print(f"[Session] Data saved in: {save_dir}")


if __name__ == "__main__":
    freeze_support()
    main()
