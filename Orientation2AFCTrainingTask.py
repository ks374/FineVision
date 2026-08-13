"""Four-stage horizontal/vertical 2AFC saccade training task."""

import math
import os
import random
import time
import traceback
from datetime import datetime
from multiprocessing import Queue, Value, freeze_support
from queue import Full

from psychopy import core, event, visual

from DisplayCalibration import (
    load_calibrated_gray_level,
    load_calibrated_gray_level_from_workbook,
    rgb255_to_psychopy,
)
from EyeDataLogger import GazeCsvWriter, STOP_TOKEN
from EyeLinkInSessionCalibration import run_in_session_calibration
from FineVision_Notebook import FineVision_Notebook
from Json_manager import read_json
from Orientation2AFCTrainingLogic import (
    STAGE_OPTIONS,
    choice_accuracy_counts,
    choice_target_arrangement,
    correct_target_for_orientation,
    dot_pair_positions,
    stage_number,
)
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
    "Subject ID": "Monkey_H18",
    "Training Stage": STAGE_OPTIONS.copy(),
    "Random Seed": 20260803,
    "Show Post-Trial Teaching Feedback": True,
    "Give Feedback First": False,
    "First Feedback Opacity (0-1)": 1.0,
    "Use Visual Cue as Fixation Point": False,
    "Keep Cue Visible During Choice": False,
    "Wait Time (s)": 5.0,
    "Fixation Acquire Time (ms)": 150,
    "Fixation Position X (deg)": 0.0,
    "Fixation Position Y (deg)": 0.0,
    "Fixation Point Radius (deg)": 0.2,
    "Fix Window Radius (deg)": 1.5,
    "Stim Onset Delay Min (ms)": 300,
    "Stim Onset Delay Max (ms)": 800,
    "Stim Duration (ms)": 500,
    "Choice Time (ms)": 900,
    "Correct Choice Hold Time (ms)": 500,
    "Cue Center Position X (deg)": 0.0,
    "Cue Center Position Y (deg)": -3.0,
    "Cue Dot Radius (deg)": 0.35,
    "Cue Dot Center Distance (deg)": 4.0,
    "Cue Brightness Level (0-182)": 160,
    "Cue Dot Opacity (0-1)": 1.0,
    "Background Gray Level (0-182)": 5,
    "Right Target Position X (deg)": 8.0,
    "Right Target Position Y (deg)": 0.0,
    "Up Target Position X (deg)": 0.0,
    "Up Target Position Y (deg)": 8.0,
    "Target Point Radius (deg)": 0.35,
    "Choice Dot Center Distance (deg)": 1.0,
    "Target Window Radius (deg)": 2.0,
    "Choice Target Brightness Level (0-182)": 160,
    "Correct Target Opacity (0-1)": 1.0,
    "Wrong Target Opacity (0-1)": 0.0,
    "Viewing Distance (cm)": 60.0,
    "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Reward Length (s)": 0.5,
    "ITI (s)": 3.0,
    "Timeout (s)": 0.5,
}


PARAMETER_GROUPS = {
    "Session / Training": [
        "Subject ID",
        "Training Stage",
        "Random Seed",
        "Show Post-Trial Teaching Feedback",
        "Give Feedback First",
        "First Feedback Opacity (0-1)",
        "Use Visual Cue as Fixation Point",
        "Keep Cue Visible During Choice",
        "Wait Time (s)",
    ],
    "Fixation": [
        "Fixation Acquire Time (ms)",
        "Fixation Position X (deg)",
        "Fixation Position Y (deg)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
    ],
    "Timing": [
        "Stim Onset Delay Min (ms)",
        "Stim Onset Delay Max (ms)",
        "Stim Duration (ms)",
        "Choice Time (ms)",
        "Correct Choice Hold Time (ms)",
    ],
    "Dot-pair Cue": [
        "Cue Center Position X (deg)",
        "Cue Center Position Y (deg)",
        "Cue Dot Radius (deg)",
        "Cue Dot Center Distance (deg)",
        "Cue Brightness Level (0-182)",
        "Cue Dot Opacity (0-1)",
    ],
    "Choice Targets": [
        "Right Target Position X (deg)",
        "Right Target Position Y (deg)",
        "Up Target Position X (deg)",
        "Up Target Position Y (deg)",
        "Target Point Radius (deg)",
        "Choice Dot Center Distance (deg)",
        "Target Window Radius (deg)",
        "Choice Target Brightness Level (0-182)",
        "Correct Target Opacity (0-1)",
        "Wrong Target Opacity (0-1)",
    ],
    "Display": [
        "Background Gray Level (0-182)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
    ],
    "Reward": [
        "Reward Length (s)",
        "ITI (s)",
        "Timeout (s)",
    ],
}


TIME_FIELDS = [
    "Time_TrialStart",
    "Time_FixOn",
    "Time_GazeEnter",
    "Time_StimOn",
    "Time_StimOff",
    "Time_FixationPointOff",
    "Time_ChoiceOn",
    "Time_TargetEnter",
    "Time_ChoiceCommitted",
    "Time_ChoiceOff",
    "Time_FeedbackOn",
    "Time_FeedbackOff",
    "Time_Reward",
    "Time_End",
]


TRIAL_LOG_FIELDS = [
    "Trial",
    "Status",
    "Training_Stage",
    "Orientation",
    "Orientation_Source",
    "Correct_Target",
    "Choice",
    "Choice_Correct",
    *TIME_FIELDS,
    "Subject_ID",
    "Planned_Stim_Onset_Delay_ms",
    "Fixation_Acquire_Time_ms",
    "Stim_Duration_ms",
    "Choice_Time_ms",
    "Correct_Choice_Hold_Time_ms",
    "Incorrect_Choice_Hold_Time_ms",
    "Fixation_Pos_X_deg",
    "Fixation_Pos_Y_deg",
    "Fixation_Point_Radius_deg",
    "Fix_Window_Radius_deg",
    "Cue_Center_Pos_X_deg",
    "Cue_Center_Pos_Y_deg",
    "Cue_Dot_Radius_deg",
    "Cue_Dot_Center_Distance_deg",
    "Cue_Dot_Arrangement",
    "Cue_Brightness_Level",
    "Cue_Target_Luminance_cd_m2",
    "Cue_Estimated_Luminance_cd_m2",
    "Cue_Color_R",
    "Cue_Color_G",
    "Cue_Color_B",
    "Cue_Dot_Opacity",
    "Cue_As_Fixation_Point",
    "Cue_Visible_During_Choice",
    "Background_Gray_Level",
    "Background_Target_Luminance_cd_m2",
    "Background_Color_R",
    "Background_Color_G",
    "Background_Color_B",
    "Right_Target_Pos_X_deg",
    "Right_Target_Pos_Y_deg",
    "Up_Target_Pos_X_deg",
    "Up_Target_Pos_Y_deg",
    "Target_Point_Radius_deg",
    "Choice_Dot_Center_Distance_deg",
    "Choice_Target_Style",
    "Target_Window_Radius_deg",
    "Choice_Target_Brightness_Level",
    "Choice_Target_Target_Luminance_cd_m2",
    "Choice_Target_Estimated_Luminance_cd_m2",
    "Choice_Target_Color_R",
    "Choice_Target_Color_G",
    "Choice_Target_Color_B",
    "Correct_Target_Opacity",
    "Wrong_Target_Opacity",
    "Give_Feedback_First",
    "First_Feedback_Opacity",
    "Teaching_Feedback_Enabled",
    "Teaching_Feedback_Shown",
    "Teaching_Feedback_Duration_ms",
    "Random_Seed",
    "Viewing_Distance_cm",
    "Monitor_Width_cm",
    "Monitor_Height_cm",
]


def _validate_common_params(params, cue_opacity_field):
    stage_number(params["Training Stage"])
    load_calibrated_gray_level(params["Background Gray Level (0-182)"])
    load_calibrated_gray_level_from_workbook(
        params["Cue Brightness Level (0-182)"]
    )
    load_calibrated_gray_level_from_workbook(
        params["Choice Target Brightness Level (0-182)"]
    )

    positive_fields = (
        "Wait Time (s)",
        "Fixation Acquire Time (ms)",
        "Fixation Point Radius (deg)",
        "Fix Window Radius (deg)",
        "Stim Onset Delay Min (ms)",
        "Stim Onset Delay Max (ms)",
        "Stim Duration (ms)",
        "Choice Time (ms)",
        "Correct Choice Hold Time (ms)",
        "Target Point Radius (deg)",
        "Target Window Radius (deg)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
        "Reward Length (s)",
        "ITI (s)",
    )
    for field in positive_fields:
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")

    if float(params["Timeout (s)"]) < 0:
        raise ValueError("Timeout (s) cannot be negative.")
    acquire_ms = float(params["Fixation Acquire Time (ms)"])
    onset_min_ms = float(params["Stim Onset Delay Min (ms)"])
    onset_max_ms = float(params["Stim Onset Delay Max (ms)"])
    if onset_min_ms < acquire_ms:
        raise ValueError(
            "Stim Onset Delay Min (ms) must be at least the fixation "
            "acquire time."
        )
    if onset_max_ms < onset_min_ms:
        raise ValueError(
            "Stim Onset Delay Max (ms) must be at least the minimum."
        )
    if float(params["Choice Time (ms)"]) < float(
        params["Correct Choice Hold Time (ms)"]
    ):
        raise ValueError(
            "Choice Time (ms) must be at least Correct Choice Hold Time "
            "(ms)."
        )
    for field in (
        cue_opacity_field,
        "Correct Target Opacity (0-1)",
        "Wrong Target Opacity (0-1)",
        "First Feedback Opacity (0-1)",
    ):
        value = float(params[field])
        if not 0 <= value <= 1:
            raise ValueError(f"{field} must be in the range 0-1.")

    for field in (
        "Fixation Position X (deg)",
        "Fixation Position Y (deg)",
        "Cue Center Position X (deg)",
        "Cue Center Position Y (deg)",
        "Right Target Position X (deg)",
        "Right Target Position Y (deg)",
        "Up Target Position X (deg)",
        "Up Target Position Y (deg)",
    ):
        if abs(float(params[field])) >= 180:
            raise ValueError(f"{field} must be between -180 and 180 degrees.")

    right_x = float(params["Right Target Position X (deg)"])
    right_y = float(params["Right Target Position Y (deg)"])
    up_x = float(params["Up Target Position X (deg)"])
    up_y = float(params["Up Target Position Y (deg)"])
    target_radius = float(params["Target Window Radius (deg)"])
    if math.hypot(right_x - up_x, right_y - up_y) <= 2 * target_radius:
        raise ValueError("Right and Up target windows must not overlap.")


def _validate_params(params):
    _validate_common_params(params, "Cue Dot Opacity (0-1)")

    for field in (
        "Cue Dot Radius (deg)",
        "Cue Dot Center Distance (deg)",
        "Choice Dot Center Distance (deg)",
    ):
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")

    if float(params["Cue Dot Center Distance (deg)"]) <= 2.0 * float(
        params["Cue Dot Radius (deg)"]
    ):
        raise ValueError(
            "Cue Dot Center Distance (deg) must be greater than twice "
            "Cue Dot Radius (deg), so the two cue dots remain separate."
        )
    if float(params["Choice Dot Center Distance (deg)"]) <= 2.0 * float(
        params["Target Point Radius (deg)"]
    ):
        raise ValueError(
            "Choice Dot Center Distance (deg) must be greater than twice "
            "Target Point Radius (deg), so each Stage 3 dot pair remains "
            "separate."
        )
    if (
        float(params["Choice Dot Center Distance (deg)"]) / 2.0
        + float(params["Target Point Radius (deg)"])
        > float(params["Target Window Radius (deg)"])
    ):
        raise ValueError(
            "The Stage 3 paired-dot choice must fit inside its target window."
        )


def _migrate_legacy_saved_params(task_manager):
    """Carry the old Stage 3 selection and opacity into the new UI fields."""
    saved = read_json(task_manager.param_file).get("parameters", {})

    saved_stage = saved.get("Training Stage")
    stage_options = task_manager.exp_params.get("Training Stage")
    if saved_stage is not None and isinstance(stage_options, list):
        try:
            canonical_stage = STAGE_OPTIONS[stage_number(saved_stage) - 1]
        except ValueError:
            canonical_stage = None
        if canonical_stage in stage_options:
            stage_options.remove(canonical_stage)
            stage_options.insert(0, canonical_stage)

    manual_opacity_field = "Wrong Target Opacity (0-1)"
    legacy_opacity_field = "Wrong Target Opacity Start (0-1)"
    if (
        manual_opacity_field not in saved
        and legacy_opacity_field in saved
    ):
        task_manager.exp_params[manual_opacity_field] = float(
            saved[legacy_opacity_field]
        )


class Orientation2AFCTrainingTask(SaccadeTask):
    """Maintain fixation during the cue, then report with a saccade."""

    stage_options = STAGE_OPTIONS
    task_display_name = "Orientation 2AFC Training Task"
    mapping_description = (
        "Horizontal dot pair -> Right; Vertical dot pair -> Up"
    )

    def _task_log_filename(self):
        return f"Orientation2AFC_task_log_{self.session_timestamp}.csv"

    def _trial_log_fields(self):
        return TRIAL_LOG_FIELDS

    def _validate_current_params(self, params):
        _validate_params(params)

    def _tracker_trial_variable_fields(self):
        return (
            "Subject_ID",
            "Training_Stage",
            "Orientation",
            "Orientation_Source",
            "Correct_Target",
            "Planned_Stim_Onset_Delay_ms",
            "Stim_Duration_ms",
            "Choice_Time_ms",
            "Correct_Choice_Hold_Time_ms",
            "Incorrect_Choice_Hold_Time_ms",
            "Fixation_Pos_X_deg",
            "Fixation_Pos_Y_deg",
            "Fixation_Point_Radius_deg",
            "Fix_Window_Radius_deg",
            "Cue_Center_Pos_X_deg",
            "Cue_Center_Pos_Y_deg",
            "Cue_Dot_Radius_deg",
            "Cue_Dot_Center_Distance_deg",
            "Cue_Dot_Arrangement",
            "Cue_Brightness_Level",
            "Cue_Target_Luminance_cd_m2",
            "Cue_Estimated_Luminance_cd_m2",
            "Cue_Color_R",
            "Cue_Color_G",
            "Cue_Color_B",
            "Cue_Dot_Opacity",
            "Cue_As_Fixation_Point",
            "Cue_Visible_During_Choice",
            "Background_Gray_Level",
            "Background_Target_Luminance_cd_m2",
            "Background_Color_R",
            "Background_Color_G",
            "Background_Color_B",
            "Right_Target_Pos_X_deg",
            "Right_Target_Pos_Y_deg",
            "Up_Target_Pos_X_deg",
            "Up_Target_Pos_Y_deg",
            "Choice_Dot_Center_Distance_deg",
            "Choice_Target_Style",
            "Target_Window_Radius_deg",
            "Target_Point_Radius_deg",
            "Choice_Target_Brightness_Level",
            "Choice_Target_Target_Luminance_cd_m2",
            "Choice_Target_Estimated_Luminance_cd_m2",
            "Choice_Target_Color_R",
            "Choice_Target_Color_G",
            "Choice_Target_Color_B",
            "Correct_Target_Opacity",
            "Wrong_Target_Opacity",
            "Give_Feedback_First",
            "First_Feedback_Opacity",
            "Teaching_Feedback_Enabled",
            "Teaching_Feedback_Duration_ms",
        )

    def _mark_time(self, trial_data, field):
        if trial_data[field] is not None:
            return
        trial_data[field] = self.now()
        tracker_event = {
            "Time_FixOn": "FIX_ON",
            "Time_StimOn": "STIM_ON",
            "Time_StimOff": "STIM_OFF",
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

    def update_params(self):
        params = self.task_manager.exp_params
        self._validate_current_params(params)

        previous_stage = getattr(self, "stage", None)
        self.stage_label = str(params["Training Stage"])
        self.stage = stage_number(self.stage_label)
        self.subject_id = str(params["Subject ID"])
        self.random_seed = int(params["Random Seed"])
        self.show_teaching_feedback = bool(
            params["Show Post-Trial Teaching Feedback"]
        )
        self.give_feedback_first = bool(params["Give Feedback First"])
        self.first_feedback_opacity = float(
            params["First Feedback Opacity (0-1)"]
        )
        self.use_visual_cue_as_fixation = bool(
            params["Use Visual Cue as Fixation Point"]
        )
        self.keep_cue_visible_during_choice = bool(
            params["Keep Cue Visible During Choice"]
        )

        if getattr(self, "_rng_seed", None) != self.random_seed:
            self.rng = random.Random(self.random_seed)
            self._rng_seed = self.random_seed
            self._orientation_bag = []
        elif previous_stage != self.stage:
            self._orientation_bag = []

        self.wait_time_s = float(params["Wait Time (s)"])
        self.fix_acquire_s = float(params["Fixation Acquire Time (ms)"]) / 1000
        self.fix_x_deg = float(params["Fixation Position X (deg)"])
        self.fix_y_deg = float(params["Fixation Position Y (deg)"])
        self.fix_point_radius_deg = float(params["Fixation Point Radius (deg)"])
        self.fix_radius_deg = float(params["Fix Window Radius (deg)"])

        self.stim_delay_min_s = float(params["Stim Onset Delay Min (ms)"]) / 1000
        self.stim_delay_max_s = float(params["Stim Onset Delay Max (ms)"]) / 1000
        self.stim_duration_s = float(params["Stim Duration (ms)"]) / 1000
        self.choice_time_s = float(params["Choice Time (ms)"]) / 1000
        self.correct_choice_hold_s = (
            float(params["Correct Choice Hold Time (ms)"]) / 1000
        )

        configured_cue_center_x_deg = float(
            params["Cue Center Position X (deg)"]
        )
        configured_cue_center_y_deg = float(
            params["Cue Center Position Y (deg)"]
        )
        if self.use_visual_cue_as_fixation:
            self.cue_center_x_deg = self.fix_x_deg
            self.cue_center_y_deg = self.fix_y_deg
        else:
            self.cue_center_x_deg = configured_cue_center_x_deg
            self.cue_center_y_deg = configured_cue_center_y_deg
        self._load_cue_shape_params(params)
        cue_calibration = load_calibrated_gray_level_from_workbook(
            params["Cue Brightness Level (0-182)"]
        )
        self.cue_brightness_level = cue_calibration["level"]
        self.cue_rgb_255 = cue_calibration["rgb_255"]
        self.cue_target_luminance = cue_calibration["luminance_cd_m2"]
        self.cue_estimated_luminance = cue_calibration[
            "estimated_luminance_cd_m2"
        ]
        self.cue_psychopy_color = tuple(
            rgb255_to_psychopy(self.cue_rgb_255)
        )
        self._load_cue_shape_opacity(params)

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
            "Up": (
                float(params["Up Target Position X (deg)"]),
                float(params["Up Target Position Y (deg)"]),
            ),
        }
        self._load_choice_shape_params(params)
        self.target_window_radius_deg = float(params["Target Window Radius (deg)"])
        choice_calibration = load_calibrated_gray_level_from_workbook(
            params["Choice Target Brightness Level (0-182)"]
        )
        self.choice_target_brightness_level = choice_calibration["level"]
        self.choice_target_rgb_255 = choice_calibration["rgb_255"]
        self.choice_target_target_luminance = choice_calibration[
            "luminance_cd_m2"
        ]
        self.choice_target_estimated_luminance = choice_calibration[
            "estimated_luminance_cd_m2"
        ]
        self.choice_target_psychopy_color = tuple(
            rgb255_to_psychopy(self.choice_target_rgb_255)
        )
        self.correct_target_opacity = float(params["Correct Target Opacity (0-1)"])
        self.wrong_target_opacity = float(params["Wrong Target Opacity (0-1)"])

        self.viewing_distance_cm = float(params["Viewing Distance (cm)"])
        self.monitor_width_cm = float(params["Subject Monitor Width (cm)"])
        self.monitor_height_cm = float(params["Subject Monitor Height (cm)"])
        self.reward_len_s = float(params["Reward Length (s)"])
        self.iti_s = float(params["ITI (s)"])
        self.timeout_s = float(params["Timeout (s)"])

        self.fix_x_px = self._to_x_pixels(self.fix_x_deg)
        self.fix_y_px = self._to_y_pixels(self.fix_y_deg)
        self.fix_point_radius_px = self._to_x_pixels(self.fix_point_radius_deg)
        self.fix_radius_px = self._to_x_pixels(self.fix_radius_deg)
        self.cue_center_x_px = self._to_x_pixels(self.cue_center_x_deg)
        self.cue_center_y_px = self._to_y_pixels(self.cue_center_y_deg)
        self._update_shape_pixels()
        self.target_window_radius_px = self._to_x_pixels(
            self.target_window_radius_deg
        )
        self.target_positions_px = {
            name: (self._to_x_pixels(x_deg), self._to_y_pixels(y_deg))
            for name, (x_deg, y_deg) in self.target_positions_deg.items()
        }
        self._build_visuals()

    def _load_cue_shape_params(self, params):
        self.cue_dot_radius_deg = float(params["Cue Dot Radius (deg)"])
        self.cue_dot_distance_deg = float(
            params["Cue Dot Center Distance (deg)"]
        )

    def _load_cue_shape_opacity(self, params):
        self.cue_dot_opacity = float(params["Cue Dot Opacity (0-1)"])

    def _load_choice_shape_params(self, params):
        self.target_point_radius_deg = float(params["Target Point Radius (deg)"])
        self.choice_dot_distance_deg = float(
            params["Choice Dot Center Distance (deg)"]
        )

    def _update_shape_pixels(self):
        self.cue_dot_radius_px = self._to_x_pixels(self.cue_dot_radius_deg)
        self.cue_dot_distance_x_px = self._to_x_pixels(
            self.cue_dot_distance_deg
        )
        self.cue_dot_distance_y_px = self._to_y_pixels(
            self.cue_dot_distance_deg
        )
        self.target_point_radius_px = self._to_x_pixels(
            self.target_point_radius_deg
        )
        self.choice_dot_distance_x_px = self._to_x_pixels(
            self.choice_dot_distance_deg
        )
        self.choice_dot_distance_y_px = self._to_y_pixels(
            self.choice_dot_distance_deg
        )

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

        self.cue_dot_sub = [
            visual.Circle(
                self.win_sub,
                radius=self.cue_dot_radius_px,
                fillColor=self.cue_psychopy_color,
                lineColor=self.cue_psychopy_color,
                opacity=self.cue_dot_opacity,
            )
            for _ in range(2)
        ]
        self.cue_dot_ctl = [
            visual.Circle(
                self.win_ctl,
                radius=self.cue_dot_radius_px * self.scale_x,
                fillColor=self.cue_psychopy_color,
                lineColor=self.cue_psychopy_color,
                opacity=self.cue_dot_opacity,
            )
            for _ in range(2)
        ]

        self.target_sub = {}
        self.target_ctl = {}
        self.target_pair_sub = {}
        self.target_pair_ctl = {}
        self.target_window_ctl = {}
        for name, (x_px, y_px) in self.target_positions_px.items():
            self.target_sub[name] = visual.Circle(
                self.win_sub,
                radius=self.target_point_radius_px,
                fillColor=self.choice_target_psychopy_color,
                lineColor=self.choice_target_psychopy_color,
                pos=(x_px, y_px),
            )
            self.target_ctl[name] = visual.Circle(
                self.win_ctl,
                radius=self.target_point_radius_px * self.scale_x,
                fillColor="white",
                lineColor="white",
                pos=(x_px * self.scale_x, y_px * self.scale_y),
            )
            self.target_pair_sub[name] = [
                visual.Circle(
                    self.win_sub,
                    radius=self.target_point_radius_px,
                    fillColor=self.choice_target_psychopy_color,
                    lineColor=self.choice_target_psychopy_color,
                )
                for _ in range(2)
            ]
            self.target_pair_ctl[name] = [
                visual.Circle(
                    self.win_ctl,
                    radius=self.target_point_radius_px * self.scale_x,
                    fillColor="white",
                    lineColor="white",
                )
                for _ in range(2)
            ]
            self.target_window_ctl[name] = visual.Circle(
                self.win_ctl,
                radius=self.target_window_radius_px * self.scale_x,
                fillColor=None,
                lineColor="cyan",
                lineWidth=2,
                pos=(x_px * self.scale_x, y_px * self.scale_y),
            )

        self.feedback_cue_box_sub = visual.Rect(
            self.win_sub,
            width=1,
            height=1,
            fillColor=None,
            lineColor="yellow",
            lineWidth=4,
        )
        self.feedback_cue_box_ctl = visual.Rect(
            self.win_ctl,
            width=1,
            height=1,
            fillColor=None,
            lineColor="yellow",
            lineWidth=2,
        )
        self.feedback_target_box_sub = visual.Rect(
            self.win_sub,
            width=1,
            height=1,
            fillColor=None,
            lineColor="yellow",
            lineWidth=4,
        )
        self.feedback_target_box_ctl = visual.Rect(
            self.win_ctl,
            width=1,
            height=1,
            fillColor=None,
            lineColor="yellow",
            lineWidth=2,
        )
        self.feedback_connection_sub = visual.Line(
            self.win_sub,
            start=(0, 0),
            end=(0, 0),
            lineColor="yellow",
            lineWidth=4,
        )
        self.feedback_connection_ctl = visual.Line(
            self.win_ctl,
            start=(0, 0),
            end=(0, 0),
            lineColor="yellow",
            lineWidth=2,
        )

    def _next_orientation(self):
        forced_orientation = getattr(self, "_next_orientation_override", None)
        if forced_orientation in ("Horizontal", "Vertical"):
            self._next_orientation_override = None
            self._last_orientation_source = "Manual_H_or_V"
            return forced_orientation

        if not self._orientation_bag:
            self._orientation_bag = ["Horizontal", "Vertical"]
            self.rng.shuffle(self._orientation_bag)
        self._last_orientation_source = "Random"
        return self._orientation_bag.pop()

    def _poll_training_commands(self, allow_orientation_override=False):
        keys = event.getKeys()
        escape_suppressed_until = float(
            getattr(self, "_escape_suppressed_until", 0.0)
        )
        if (
            "escape" in keys
            and time.perf_counter() >= escape_suppressed_until
        ):
            raise TaskAbort()

        if allow_orientation_override:
            override = None
            for key in keys:
                if key == "h":
                    override = "Horizontal"
                elif key == "v":
                    override = "Vertical"
            if override is not None:
                self._next_orientation_override = override
                print(f"[ITI] Next cue forced to {override}.")

        return "n" in keys

    def _visible_targets(self, correct_target):
        if self.stage in (1, 2):
            return [correct_target]
        return ["Right", "Up"]

    def _choice_dot_positions(self, target_name):
        x_px, y_px = self.target_positions_px[target_name]
        return dot_pair_positions(
            x_px,
            y_px,
            self.choice_dot_distance_x_px,
            self.choice_dot_distance_y_px,
            choice_target_arrangement(target_name),
        )

    def _target_opacity(self, target_name, correct_target, wrong_opacity):
        if target_name == correct_target:
            return self.correct_target_opacity
        return wrong_opacity

    def _required_choice_hold_s(self, target_name, correct_target):
        if target_name == correct_target:
            return self.correct_choice_hold_s
        return INCORRECT_CHOICE_HOLD_S

    @staticmethod
    def _set_feedback_box_geometry(
        subject_box,
        control_box,
        center,
        size,
        scale_x,
        scale_y,
    ):
        center_x, center_y = center
        width, height = size
        subject_box.pos = (center_x, center_y)
        subject_box.size = (width, height)
        control_box.pos = (center_x * scale_x, center_y * scale_y)
        control_box.size = (width * scale_x, height * scale_y)

    @staticmethod
    def _feedback_connection_endpoints(
        cue_center,
        cue_size,
        target_center,
        target_size,
    ):
        """Connect the nearest edges of the cue and correct-target frames."""
        delta_x = float(target_center[0]) - float(cue_center[0])
        delta_y = float(target_center[1]) - float(cue_center[1])
        if delta_x == 0.0 and delta_y == 0.0:
            return tuple(cue_center), tuple(target_center)

        def edge_point(center, size, direction_x, direction_y):
            limits = []
            if direction_x != 0.0:
                limits.append((float(size[0]) / 2.0) / abs(direction_x))
            if direction_y != 0.0:
                limits.append((float(size[1]) / 2.0) / abs(direction_y))
            scale = min(limits)
            return (
                float(center[0]) + direction_x * scale,
                float(center[1]) + direction_y * scale,
            )

        cue_edge = edge_point(
            cue_center,
            cue_size,
            delta_x,
            delta_y,
        )
        target_edge = edge_point(
            target_center,
            target_size,
            -delta_x,
            -delta_y,
        )
        return cue_edge, target_edge

    def _feedback_cue_size_px(self, orientation):
        cue_padding = max(4.0, self.cue_dot_radius_px * 0.75)
        cue_width = 2.0 * self.cue_dot_radius_px + 2.0 * cue_padding
        cue_height = cue_width
        if orientation == "Horizontal":
            cue_width += self.cue_dot_distance_x_px
        else:
            cue_height += self.cue_dot_distance_y_px
        return cue_width, cue_height

    def _feedback_target_size_px(self, correct_target):
        target_padding = max(4.0, self.target_point_radius_px * 0.75)
        target_width = 2.0 * self.target_point_radius_px + 2.0 * target_padding
        target_height = target_width
        if self.stage == 3:
            arrangement = choice_target_arrangement(correct_target)
            if arrangement == "Horizontal":
                target_width += self.choice_dot_distance_x_px
            else:
                target_height += self.choice_dot_distance_y_px
        return target_width, target_height

    def _draw_feedback_mapping(
        self,
        orientation,
        correct_target,
        *,
        include_target_box,
        opacity,
    ):
        cue_width, cue_height = self._feedback_cue_size_px(orientation)
        self._set_feedback_box_geometry(
            self.feedback_cue_box_sub,
            self.feedback_cue_box_ctl,
            (self.cue_center_x_px, self.cue_center_y_px),
            (cue_width, cue_height),
            self.scale_x,
            self.scale_y,
        )

        target_width, target_height = self._feedback_target_size_px(
            correct_target
        )
        self._set_feedback_box_geometry(
            self.feedback_target_box_sub,
            self.feedback_target_box_ctl,
            self.target_positions_px[correct_target],
            (target_width, target_height),
            self.scale_x,
            self.scale_y,
        )

        cue_center = (self.cue_center_x_px, self.cue_center_y_px)
        target_center = self.target_positions_px[correct_target]
        line_start, line_end = self._feedback_connection_endpoints(
            cue_center,
            (cue_width, cue_height),
            target_center,
            (target_width, target_height),
        )
        self.feedback_connection_sub.start = line_start
        self.feedback_connection_sub.end = line_end
        self.feedback_connection_ctl.start = (
            line_start[0] * self.scale_x,
            line_start[1] * self.scale_y,
        )
        self.feedback_connection_ctl.end = (
            line_end[0] * self.scale_x,
            line_end[1] * self.scale_y,
        )

        for stimulus in (
            self.feedback_connection_sub,
            self.feedback_connection_ctl,
            self.feedback_cue_box_sub,
            self.feedback_cue_box_ctl,
            self.feedback_target_box_sub,
            self.feedback_target_box_ctl,
        ):
            stimulus.opacity = opacity

        self.feedback_connection_sub.draw()
        self.feedback_connection_ctl.draw()
        self.feedback_cue_box_sub.draw()
        self.feedback_cue_box_ctl.draw()
        if include_target_box:
            self.feedback_target_box_sub.draw()
            self.feedback_target_box_ctl.draw()

    def _draw_teaching_feedback_frames(self, orientation, correct_target):
        self._draw_feedback_mapping(
            orientation,
            correct_target,
            include_target_box=True,
            opacity=1.0,
        )

    def _draw_first_feedback(self, orientation, correct_target):
        self._draw_feedback_mapping(
            orientation,
            correct_target,
            include_target_box=False,
            opacity=self.first_feedback_opacity,
        )

    def _draw_cue(self, orientation):
        positions = dot_pair_positions(
            self.cue_center_x_px,
            self.cue_center_y_px,
            self.cue_dot_distance_x_px,
            self.cue_dot_distance_y_px,
            orientation,
        )
        for subject_dot, control_dot, (x_px, y_px) in zip(
            self.cue_dot_sub,
            self.cue_dot_ctl,
            positions,
        ):
            subject_dot.pos = (x_px, y_px)
            control_dot.pos = (
                x_px * self.scale_x,
                y_px * self.scale_y,
            )
            subject_dot.draw()
            control_dot.draw()

    def _draw_choice_target(self, name, correct_target, wrong_opacity):
        opacity = self._target_opacity(
            name,
            correct_target,
            wrong_opacity,
        )
        control_color = "green" if name == correct_target else "red"
        if self.stage == 3:
            positions = self._choice_dot_positions(name)
            for subject_dot, control_dot, (x_px, y_px) in zip(
                self.target_pair_sub[name],
                self.target_pair_ctl[name],
                positions,
            ):
                subject_dot.pos = (x_px, y_px)
                subject_dot.opacity = opacity
                subject_dot.draw()
                control_dot.pos = (
                    x_px * self.scale_x,
                    y_px * self.scale_y,
                )
                control_dot.opacity = max(opacity, 0.25)
                control_dot.fillColor = control_color
                control_dot.lineColor = control_color
                control_dot.draw()
        else:
            subject_target = self.target_sub[name]
            subject_target.opacity = opacity
            subject_target.draw()

            control_target = self.target_ctl[name]
            control_target.opacity = max(opacity, 0.25)
            control_target.fillColor = control_color
            control_target.lineColor = control_color
            control_target.draw()
        window = self.target_window_ctl[name]
        window.lineColor = control_color
        window.draw()

    def _uses_separate_cue_phase(self):
        return self.stage >= 2 and not self.use_visual_cue_as_fixation

    def _cue_visible_during_choice(self):
        cue_was_already_present = (
            self.stage >= 2 or self.use_visual_cue_as_fixation
        )
        cue_is_needed = (
            self.keep_cue_visible_during_choice
            or self._first_feedback_during_choice()
        )
        return cue_is_needed and cue_was_already_present

    def _first_feedback_during_choice(self):
        cue_was_already_present = (
            self.stage >= 2 or self.use_visual_cue_as_fixation
        )
        return self.give_feedback_first and cue_was_already_present

    def _present_training_frame(
        self,
        *,
        fix_visible=False,
        fix_window_active=False,
        cue_visible=False,
        orientation="Horizontal",
        correct_target="Right",
        targets_visible=False,
        wrong_opacity=0.0,
        force_all_targets=False,
        target_only=None,
        first_feedback=False,
        teaching_feedback=False,
        allow_orientation_override=False,
    ):
        cue_drawn = False
        if fix_visible:
            if self.use_visual_cue_as_fixation:
                self._draw_cue(orientation)
                cue_drawn = True
            else:
                self.fix_sub.draw()
                self.fix_ctl.draw()
        if fix_window_active:
            self.fix_window_ctl.draw()

        if cue_visible and not cue_drawn:
            self._draw_cue(orientation)

        if targets_visible:
            if target_only is not None:
                visible_targets = [target_only]
            elif force_all_targets:
                visible_targets = ["Right", "Up"]
            else:
                visible_targets = self._visible_targets(correct_target)
            for name in visible_targets:
                self._draw_choice_target(name, correct_target, wrong_opacity)

        if first_feedback:
            self._draw_first_feedback(orientation, correct_target)
        if teaching_feedback:
            self._draw_teaching_feedback_frames(orientation, correct_target)

        gaze = self.gaze_renderer.update_and_draw()
        self.win_sub.flip()
        self.win_ctl.flip()
        pause_requested = self._poll_training_commands(
            allow_orientation_override=allow_orientation_override
        )
        return gaze, pause_requested

    def _new_trial_data(self, trial_number, orientation, stim_delay_s):
        correct_target = correct_target_for_orientation(orientation)
        wrong_opacity = self.wrong_target_opacity if self.stage >= 3 else 0.0
        return {
            "Trial": trial_number,
            "Status": None,
            "Training_Stage": self.stage,
            "Orientation": orientation,
            "Orientation_Source": self._last_orientation_source,
            "Correct_Target": correct_target,
            "Choice": "",
            "Choice_Correct": "",
            **{field: None for field in TIME_FIELDS},
            "Subject_ID": self.subject_id,
            "Planned_Stim_Onset_Delay_ms": stim_delay_s * 1000,
            "Fixation_Acquire_Time_ms": self.fix_acquire_s * 1000,
            "Stim_Duration_ms": (
                0.0
                if self.use_visual_cue_as_fixation
                else self.stim_duration_s * 1000
            ),
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
            "Cue_Center_Pos_X_deg": self.cue_center_x_deg,
            "Cue_Center_Pos_Y_deg": self.cue_center_y_deg,
            "Cue_Dot_Radius_deg": self.cue_dot_radius_deg,
            "Cue_Dot_Center_Distance_deg": self.cue_dot_distance_deg,
            "Cue_Dot_Arrangement": orientation,
            "Cue_Brightness_Level": self.cue_brightness_level,
            "Cue_Target_Luminance_cd_m2": self.cue_target_luminance,
            "Cue_Estimated_Luminance_cd_m2": (
                self.cue_estimated_luminance
            ),
            "Cue_Color_R": self.cue_rgb_255[0],
            "Cue_Color_G": self.cue_rgb_255[1],
            "Cue_Color_B": self.cue_rgb_255[2],
            "Cue_Dot_Opacity": self.cue_dot_opacity,
            "Cue_As_Fixation_Point": self.use_visual_cue_as_fixation,
            "Cue_Visible_During_Choice": self._cue_visible_during_choice(),
            "Background_Gray_Level": self.background_gray_level,
            "Background_Target_Luminance_cd_m2": (
                self.background_target_luminance
            ),
            "Background_Color_R": self.background_rgb_255[0],
            "Background_Color_G": self.background_rgb_255[1],
            "Background_Color_B": self.background_rgb_255[2],
            "Right_Target_Pos_X_deg": self.target_positions_deg["Right"][0],
            "Right_Target_Pos_Y_deg": self.target_positions_deg["Right"][1],
            "Up_Target_Pos_X_deg": self.target_positions_deg["Up"][0],
            "Up_Target_Pos_Y_deg": self.target_positions_deg["Up"][1],
            "Target_Point_Radius_deg": self.target_point_radius_deg,
            "Choice_Dot_Center_Distance_deg": self.choice_dot_distance_deg,
            "Choice_Target_Style": (
                "Paired_Dots" if self.stage == 3 else "Single_Dot"
            ),
            "Target_Window_Radius_deg": self.target_window_radius_deg,
            "Choice_Target_Brightness_Level": (
                self.choice_target_brightness_level
            ),
            "Choice_Target_Target_Luminance_cd_m2": (
                self.choice_target_target_luminance
            ),
            "Choice_Target_Estimated_Luminance_cd_m2": (
                self.choice_target_estimated_luminance
            ),
            "Choice_Target_Color_R": self.choice_target_rgb_255[0],
            "Choice_Target_Color_G": self.choice_target_rgb_255[1],
            "Choice_Target_Color_B": self.choice_target_rgb_255[2],
            "Correct_Target_Opacity": self.correct_target_opacity,
            "Wrong_Target_Opacity": wrong_opacity,
            "Give_Feedback_First": self.give_feedback_first,
            "First_Feedback_Opacity": self.first_feedback_opacity,
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

    def _wait_for_fixation(self, trial_data):
        candidate_start = None
        wait_start = self.now()
        pause_requested = False
        orientation = trial_data["Orientation"]
        correct_target = trial_data["Correct_Target"]

        while self.now() - wait_start < self.wait_time_s:
            gaze, requested = self._present_training_frame(
                fix_visible=True,
                fix_window_active=True,
                orientation=orientation,
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
                    return candidate_start, pause_requested
            else:
                candidate_start = None
        return None, pause_requested

    def _hold_before_stim(self, trial_data, fixation_start, stim_delay_s):
        pause_requested = False
        while self.now() - fixation_start < stim_delay_s:
            gaze, requested = self._present_training_frame(
                fix_visible=True,
                fix_window_active=True,
                orientation=trial_data["Orientation"],
                correct_target=trial_data["Correct_Target"],
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

    def _run_stimulus(self, trial_data):
        pause_requested = False
        self._schedule_flip_time(trial_data, "Time_StimOn")
        gaze, requested = self._present_training_frame(
            fix_visible=True,
            fix_window_active=True,
            cue_visible=True,
            orientation=trial_data["Orientation"],
            correct_target=trial_data["Correct_Target"],
        )
        pause_requested = pause_requested or requested
        if not self._in_window(
            gaze,
            self.fix_x_px,
            self.fix_y_px,
            self.fix_radius_px,
        ):
            return False, pause_requested

        while self.now() - trial_data["Time_StimOn"] < self.stim_duration_s:
            gaze, requested = self._present_training_frame(
                fix_visible=True,
                fix_window_active=True,
                cue_visible=True,
                orientation=trial_data["Orientation"],
                correct_target=trial_data["Correct_Target"],
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
        cue_visible = self._cue_visible_during_choice()
        if trial_data["Time_StimOn"] is not None and not cue_visible:
            self._schedule_flip_time(trial_data, "Time_StimOff")
        self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        self._schedule_flip_time(trial_data, "Time_ChoiceOn")
        return self._present_training_frame(
            cue_visible=cue_visible,
            targets_visible=True,
            orientation=trial_data["Orientation"],
            correct_target=trial_data["Correct_Target"],
            wrong_opacity=trial_data["Wrong_Target_Opacity"],
            first_feedback=self._first_feedback_during_choice(),
        )

    def _run_choice(self, trial_data, initial_gaze, initial_pause):
        candidate_target = None
        candidate_start = None
        ever_entered = False
        pause_requested = initial_pause
        gaze = initial_gaze
        visible_targets = self._visible_targets(trial_data["Correct_Target"])

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
                cue_visible=self._cue_visible_during_choice(),
                targets_visible=True,
                orientation=trial_data["Orientation"],
                correct_target=trial_data["Correct_Target"],
                wrong_opacity=trial_data["Wrong_Target_Opacity"],
                first_feedback=self._first_feedback_during_choice(),
            )
            pause_requested = pause_requested or requested

        return ("Break_Choice" if ever_entered else "NoChoice"), pause_requested

    def _black_out_training(self, trial_data):
        if trial_data["Time_FixOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_StimOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_StimOff")
        if trial_data["Time_ChoiceOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_ChoiceOff")
        self._present_training_frame()

    def _teaching_feedback_is_due(self, trial_data):
        return bool(
            self.show_teaching_feedback
            and self.stage >= 3
            and trial_data["Time_ChoiceOn"] is not None
            and trial_data.get("Choice") in ("Right", "Up")
        )

    def _run_teaching_feedback(self, trial_data):
        """Replay the animal's completed choice and its cue for two seconds."""
        if not self._teaching_feedback_is_due(trial_data):
            self._black_out_training(trial_data)
            return False

        selected_target = trial_data["Choice"]
        selected_correctly = trial_data.get("Choice_Correct") is True

        if trial_data["Time_FixOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_FixationPointOff")
        if trial_data["Time_StimOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_StimOff")
        if trial_data["Time_ChoiceOn"] is not None:
            self._schedule_flip_time(trial_data, "Time_ChoiceOff")
        self._schedule_flip_time(trial_data, "Time_FeedbackOn")
        trial_data["Teaching_Feedback_Shown"] = True

        pause_requested = False
        while (
            trial_data["Time_FeedbackOn"] is None
            or self.now() - trial_data["Time_FeedbackOn"]
            < TEACHING_FEEDBACK_DURATION_S
        ):
            _, requested = self._present_training_frame(
                cue_visible=True,
                orientation=trial_data["Orientation"],
                correct_target=trial_data["Correct_Target"],
                targets_visible=True,
                wrong_opacity=trial_data["Wrong_Target_Opacity"],
                target_only=selected_target,
                teaching_feedback=selected_correctly,
            )
            pause_requested = pause_requested or requested

        self._schedule_flip_time(trial_data, "Time_FeedbackOff")
        _, requested = self._present_training_frame()
        return pause_requested or requested

    def _run_one_trial(self, trial_number):
        orientation = self._next_orientation()
        stim_delay_s = self.rng.uniform(
            self.stim_delay_min_s,
            self.stim_delay_max_s,
        )
        trial_data = self._new_trial_data(
            trial_number,
            orientation,
            stim_delay_s,
        )
        event.clearEvents()
        self.gaze_renderer.reset_trail()
        self._send_tracker_event(f"TRIALID {trial_number}")
        for field in self._tracker_trial_variable_fields():
            self._send_tracker_event(
                f"!V TRIAL_VAR {field} {trial_data[field]}"
            )

        self.arduino.trial_start()
        trial_data["Time_TrialStart"] = self.now()
        self._schedule_flip_time(trial_data, "Time_FixOn")
        if self.use_visual_cue_as_fixation:
            self._schedule_flip_time(trial_data, "Time_StimOn")
        _, pause_requested = self._present_training_frame(
            fix_visible=True,
            fix_window_active=True,
            orientation=orientation,
            correct_target=trial_data["Correct_Target"],
        )

        fixation_start, requested = self._wait_for_fixation(trial_data)
        pause_requested = pause_requested or requested
        if fixation_start is None:
            status = "NoFix"
        else:
            held, requested = self._hold_before_stim(
                trial_data,
                fixation_start,
                stim_delay_s,
            )
            pause_requested = pause_requested or requested
            if not held:
                status = "Break_Fix"
            else:
                if self._uses_separate_cue_phase():
                    held, requested = self._run_stimulus(trial_data)
                    pause_requested = pause_requested or requested
                    if not held:
                        status = "Break_Stim"
                    else:
                        gaze, requested = self._show_choice_onset(trial_data)
                        status, requested = self._run_choice(
                            trial_data,
                            gaze,
                            requested,
                        )
                        pause_requested = pause_requested or requested
                else:
                    gaze, requested = self._show_choice_onset(trial_data)
                    status, requested = self._run_choice(
                        trial_data,
                        gaze,
                        requested,
                    )
                    pause_requested = pause_requested or requested

        if status == "Success":
            self.arduino.trial_success()
            trial_data["Time_Reward"] = self.now()
            self._send_tracker_event(f"REWARD TRIAL {trial_number}")
            self.arduino.reward(int(self.reward_len_s * 1000))
        elif status in ("Incorrect", "Break_Fix", "Break_Stim", "Break_Choice"):
            self.arduino.trial_break()
        else:
            self.arduino.trial_nofix()

        requested = self._run_teaching_feedback(trial_data)
        pause_requested = pause_requested or requested
        if status in ("Incorrect", "Break_Fix", "Break_Stim", "Break_Choice"):
            core.wait(self.timeout_s)

        self.arduino.trial_end()
        trial_data["Status"] = status
        trial_data["Time_End"] = self.now()
        self._send_tracker_event(f"!V TRIAL_VAR Status {status}")
        self._send_tracker_event(
            f"!V TRIAL_VAR Choice {trial_data['Choice'] or 'None'}"
        )
        self._send_tracker_event(f"TRIAL_RESULT {status}")
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
            _, pause_requested = self._present_training_frame(
                allow_orientation_override=True
            )
            if pause_requested:
                return True
        return False

    def _prepare_stage_options(self):
        stage_value = self.task_manager.exp_params.get("Training Stage")
        if not isinstance(stage_value, list):
            selected = str(stage_value)
            self.task_manager.exp_params["Training Stage"] = [
                selected,
                *(
                    option
                    for option in self.stage_options
                    if option != selected
                ),
            ]

    def _prompt_for_parameters(self):
        self._prepare_stage_options()
        return self.task_manager.prompt_for_parameters()

    def _prompt_for_runtime_parameters(self):
        self._prepare_stage_options()
        return self.task_manager.prompt_for_runtime_parameters(
            title="Runtime Parameters / 运行中参数",
            allow_recalibration=bool(
                getattr(
                    self.tracker_backend,
                    "supports_recalibration",
                    False,
                )
            ),
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

    def run_task(self):
        if not self._prompt_for_parameters():
            raise TaskAbort()
        self.update_params()
        event.clearEvents()

        print(f"\n=== {self.task_display_name} started ===")
        print(self.mapping_description)
        print(
            "Press Esc to quit; press N to edit parameters or recalibrate "
            "before the next trial."
        )
        print(
            "During ITI: press H for a horizontal next cue or V for a "
            "vertical next cue; press neither for random."
        )

        trial_number = 1
        pause_requested = False
        while True:
            if pause_requested:
                self._present_training_frame()
                pause_action = self._prompt_for_runtime_parameters()
                if pause_action == "cancel":
                    self._send_tracker_event(
                        "FINEVISION_PAUSE_ACTION CANCEL_SESSION"
                    )
                    raise TaskAbort()
                self.update_params()
                if pause_action == "recalibrate":
                    self._recalibrate_eyelink()
                else:
                    self._send_tracker_event(
                        "FINEVISION_PAUSE_ACTION CONFIRM_CONTINUE"
                    )
                event.clearEvents()
                pause_requested = False

            if self._run_iti():
                pause_requested = True
                continue

            print(
                f"\n--- Trial {trial_number} | Stage {self.stage} | "
                f"wrong opacity {self.wrong_target_opacity:.2f} ---"
            )
            trial_data, requested = self._run_one_trial(trial_number)
            self._write_trial(trial_data)
            pause_requested = pause_requested or requested

            total_correct, total_choices = choice_accuracy_counts(
                self.behavior_log
            )
            recent_correct, recent_choices = choice_accuracy_counts(
                self.behavior_log,
                recent_limit=40,
            )
            print(
                f"Result: {trial_data['Status']} | "
                f"cue={trial_data['Orientation']} | "
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
                    "Recent choice accuracy (last 40 completed choices): "
                    f"{recent_correct / recent_choices:.1%} "
                    f"({recent_correct}/{recent_choices})"
                )
            trial_number += 1


def _create_session_dir(script_dir, session_prefix="Orientation2AFC"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    return timestamp, candidate


def main(
    tracker_mode="qy",
    *,
    task_class=Orientation2AFCTrainingTask,
    task_name="Orientation2AFCTrainingTask",
    default_params=DEFAULT_PARAMS,
    parameter_groups=PARAMETER_GROUPS,
    parameter_validator=_validate_params,
    saved_params_migrator=_migrate_legacy_saved_params,
    session_prefix="Orientation2AFC",
    control_title="Orientation 2AFC",
    task_label="Orientation 2AFC training",
):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    session_timestamp, save_dir = _create_session_dir(
        script_dir,
        session_prefix=session_prefix,
    )
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

        task_manager = FineVision_Notebook(
            task_name=task_name,
            default_params=default_params,
            parameter_groups=parameter_groups,
            parameter_validator=parameter_validator,
        )
        if saved_params_migrator is not None:
            saved_params_migrator(task_manager)
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
