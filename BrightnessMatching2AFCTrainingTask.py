"""Single-sample brightness matching 2AFC task; unchanged parameter notebook UI."""
from multiprocessing import freeze_support
from collections import deque
import random
from psychopy import visual
from DisplayCalibration import load_calibrated_gray_level_from_workbook, rgb255_to_psychopy
from Orientation2AFCTrainingTask import (
    Orientation2AFCTrainingTask, DEFAULT_PARAMS, PARAMETER_GROUPS,
    main, _validate_common_params,
)


# Private copies: do not modify the parameters of other training tasks.
DEFAULT_PARAMS = dict(DEFAULT_PARAMS)
PARAMETER_GROUPS = {name: list(fields) for name, fields in PARAMETER_GROUPS.items()}
DEFAULT_PARAMS.update({
    # Explicit, independently adjustable brightness levels for the two
    # alternatives in regular trials. Keep the match choice aligned with the
    # cue by default, while allowing the experimenter to change either value.
    "Regular Match Choice Brightness Level (0-182)": 160,
    "Regular Distractor Choice Brightness Level (0-182)": 150,
    "Easy Probe Enabled": True,
    "Easy Probe Count per 10 (3 or 4)": 3,
    "Easy Probe Dark Level (0-182)": 10,
    "Easy Probe Bright Level (0-182)": 150,
})
PARAMETER_GROUPS["Choice Targets"] = [
    field for field in PARAMETER_GROUPS.get("Choice Targets", [])
    if field not in ("Choice Target Brightness Level (0-182)",)
] + [
    "Regular Match Choice Brightness Level (0-182)",
    "Regular Distractor Choice Brightness Level (0-182)",
]
PARAMETER_GROUPS["Easy Probe / 插入简单试次"] = [
    "Easy Probe Enabled",
    "Easy Probe Count per 10 (3 or 4)",
    "Easy Probe Dark Level (0-182)",
    "Easy Probe Bright Level (0-182)",
]
PROBE_LOG_FIELDS = (
    "Trial_Type", "Probe_Dark_Level", "Probe_Bright_Level",
    "Probe_Recent20_Correct", "Probe_Recent20_Choices",
    "Probe_All_Correct", "Probe_All_Choices",
    "Regular_All_Correct", "Regular_All_Choices",
    "Regular_Match_Choice_Brightness_Level",
    "Regular_Distractor_Choice_Brightness_Level",
)


def validate_brightness_params(params):
    _validate_common_params(params, "Cue Dot Opacity (0-1)")
    count = int(params["Easy Probe Count per 10 (3 or 4)"])
    if count not in (3, 4) or float(params["Easy Probe Count per 10 (3 or 4)"]) != count:
        raise ValueError("Easy Probe Count per 10 must be 3 or 4")
    regular_match = int(params["Regular Match Choice Brightness Level (0-182)"])
    regular_distractor = int(params["Regular Distractor Choice Brightness Level (0-182)"])
    if not (0 <= regular_match <= 182 and 0 <= regular_distractor <= 182):
        raise ValueError("Regular choice brightness levels must be between 0 and 182")
    load_calibrated_gray_level_from_workbook(regular_match)
    load_calibrated_gray_level_from_workbook(regular_distractor)
    dark = int(params["Easy Probe Dark Level (0-182)"])
    bright = int(params["Easy Probe Bright Level (0-182)"])
    if not (0 <= dark < bright <= 182):
        raise ValueError("Probe brightness must satisfy 0 <= dark < bright <= 182")
    load_calibrated_gray_level_from_workbook(dark)
    load_calibrated_gray_level_from_workbook(bright)
    if float(params["Cue Dot Radius (deg)"]) <= 0:
        raise ValueError("Cue Dot Radius (deg) must be positive.")
    if regular_match == regular_distractor:
        raise ValueError("Regular match and distractor choice brightness levels must differ.")


class BrightnessMatching2AFCTrainingTask(Orientation2AFCTrainingTask):
    task_display_name = "Brightness Matching 2AFC Training Task"
    mapping_description = "Sample brightness -> matching brightness at randomized Right/Up target"

    def _trial_log_fields(self):
        return [*super()._trial_log_fields(), *PROBE_LOG_FIELDS]

    def _tracker_trial_variable_fields(self):
        return (*super()._tracker_trial_variable_fields(), "Trial_Type", "Probe_Dark_Level", "Probe_Bright_Level", "Regular_Match_Choice_Brightness_Level", "Regular_Distractor_Choice_Brightness_Level")

    def _task_log_filename(self):
        return f"BrightnessMatching2AFC_task_log_{self.session_timestamp}.csv"

    def _validate_current_params(self, params):
        validate_brightness_params(params)

    def update_params(self):
        super().update_params()
        # Keep the existing UI and calibrated luminance lookup; override only
        # the visual colors used by the two choice stimuli.
        params = self.task_manager.exp_params
        regular_match_cal = load_calibrated_gray_level_from_workbook(
            params["Regular Match Choice Brightness Level (0-182)"]
        )
        regular_distractor_cal = load_calibrated_gray_level_from_workbook(
            params["Regular Distractor Choice Brightness Level (0-182)"]
        )
        self.regular_match_level = regular_match_cal["level"]
        self.regular_distractor_level = regular_distractor_cal["level"]
        self.match_color = tuple(rgb255_to_psychopy(regular_match_cal["rgb_255"]))
        self.distractor_color = tuple(rgb255_to_psychopy(regular_distractor_cal["rgb_255"]))
        self.probe_enabled = bool(self.task_manager.exp_params["Easy Probe Enabled"])
        self.probe_count = int(self.task_manager.exp_params["Easy Probe Count per 10 (3 or 4)"])
        self.probe_dark = int(self.task_manager.exp_params["Easy Probe Dark Level (0-182)"])
        self.probe_bright = int(self.task_manager.exp_params["Easy Probe Bright Level (0-182)"])
        self.probe_dark_color = tuple(rgb255_to_psychopy(load_calibrated_gray_level_from_workbook(self.probe_dark)["rgb_255"]))
        self.probe_bright_color = tuple(rgb255_to_psychopy(load_calibrated_gray_level_from_workbook(self.probe_bright)["rgb_255"]))
        if not hasattr(self, "_probe_schedule"):
            self._probe_schedule = []
            self._probe_schedule_config = None
            self._probe_rng = random.Random(self.random_seed + 7919)
            self._probe_recent = deque(maxlen=20)
            self._probe_correct = self._probe_choices = 0
            self._regular_correct = self._regular_choices = 0
            self._regular_recent = deque(maxlen=40)
        elif not hasattr(self, "_regular_recent"):
            self._regular_recent = deque(maxlen=40)
        config = (self.probe_enabled, self.probe_count, self.random_seed)
        if self._probe_schedule_config != config:
            self._probe_schedule.clear()
            self._probe_rng = random.Random(self.random_seed + 7919)
            self._probe_schedule_config = config

    def _next_orientation(self):
        # Preserve inherited balanced two-condition scheduler and repeat-on-failure.
        return super()._next_orientation()

    def _draw_cue(self, orientation, gaze=None):
        x, y = self._cue_center_for_gaze(gaze)
        self._current_cue_center_px = (x, y)
        if getattr(self, "_active_probe", False):
            for dot in (self.cue_dot_sub[0], self.cue_dot_ctl[0]):
                dot.fillColor = self.probe_bright_color
                dot.lineColor = self.probe_bright_color
        else:
            for dot in (self.cue_dot_sub[0], self.cue_dot_ctl[0]):
                dot.fillColor = self.cue_psychopy_color
                dot.lineColor = self.cue_psychopy_color
        for dot, scale_x, scale_y in (
            (self.cue_dot_sub[0], 1, 1),
            (self.cue_dot_ctl[0], self.scale_x, self.scale_y),
        ):
            dot.pos = (x * scale_x, y * scale_y)
            dot.draw()

    def _draw_choice_target(self, name, correct_target, wrong_opacity):
        is_match = name == correct_target
        # Both alternatives must be visible for a brightness discrimination.
        opacity = self.correct_target_opacity
        if getattr(self, "_active_probe", False):
            color = self.probe_bright_color if is_match else self.probe_dark_color
        else:
            color = self.match_color if is_match else self.distractor_color
        sub = self.target_sub[name]
        sub.fillColor = color
        sub.lineColor = color
        sub.opacity = opacity
        sub.draw()
        ctl = self.target_ctl[name]
        ctl.fillColor = color
        ctl.lineColor = color
        ctl.opacity = opacity
        ctl.draw()
        window = self.target_window_ctl[name]
        window.lineColor = "green" if is_match else "red"
        window.draw()

    def _visible_targets(self, correct_target):
        return ["Right", "Up"]

    def _feedback_cue_size_px(self, orientation):
        padding = max(4.0, self.cue_dot_radius_px * 0.75)
        size = 2 * (self.cue_dot_radius_px + padding)
        return size, size

    def _feedback_target_size_px(self, correct_target):
        padding = max(4.0, self.target_point_radius_px * 0.75)
        size = 2 * (self.target_point_radius_px + padding)
        return size, size

    def _new_trial_data(self, trial_number, orientation, stim_delay_s,
                        completed_trials_before=None):
        data = super()._new_trial_data(
            trial_number, orientation, stim_delay_s,
            completed_trials_before=completed_trials_before,
        )
        # Existing balanced H/V trial labels are used internally only to select
        # randomized Right/Up correct answers, not to draw orientation cues.
        data["Cue_Dot_Arrangement"] = "Single_Dot"
        data["Choice_Target_Style"] = "Two_Single_Dots_Brightness_Match"
        data["Orientation"] = "Brightness_Match"
        data["Cue_Dot_Center_Distance_deg"] = 0.0
        data["Choice_Dot_Center_Distance_deg"] = 0.0
        data["Wrong_Target_Opacity"] = self.correct_target_opacity
        data["Trial_Type"] = "Easy_Probe" if self._active_probe else "Regular"
        data["Probe_Dark_Level"] = self.probe_dark if self._active_probe else ""
        data["Probe_Bright_Level"] = self.probe_bright if self._active_probe else ""
        data["Regular_Match_Choice_Brightness_Level"] = self.regular_match_level
        data["Regular_Distractor_Choice_Brightness_Level"] = self.regular_distractor_level
        for field in PROBE_LOG_FIELDS[3:]:
            data[field] = 0
        if self._active_probe:
            cal = load_calibrated_gray_level_from_workbook(self.probe_bright)
            data["Cue_Brightness_Level"] = self.probe_bright
            data["Cue_Target_Luminance_cd_m2"] = cal["luminance_cd_m2"]
            data["Cue_Estimated_Luminance_cd_m2"] = cal["estimated_luminance_cd_m2"]
            data["Cue_Color_R"], data["Cue_Color_G"], data["Cue_Color_B"] = cal["rgb_255"]
        return data

    def _run_one_trial(self, trial_number, completed_trials_before=None):
        # Shuffle exactly 3 or 4 probes into each batch of ten attempts.
        if not self._probe_schedule:
            self._probe_schedule = ([True] * self.probe_count +
                                    [False] * (10 - self.probe_count))
            self._probe_rng.shuffle(self._probe_schedule)
        self._active_probe = self.probe_enabled and self._probe_schedule.pop()
        try:
            data, pause = super()._run_one_trial(trial_number, completed_trials_before)
        finally:
            self._active_probe = False
        # Only committed correct/incorrect choices enter accuracy denominators.
        correct = data.get("Choice_Correct")
        if isinstance(correct, bool):
            if data["Trial_Type"] == "Easy_Probe":
                self._probe_recent.append(correct)
                self._probe_choices += 1
                self._probe_correct += int(correct)
            else:
                self._regular_recent.append(correct)
                self._regular_choices += 1
                self._regular_correct += int(correct)
        data.update({
            "Probe_Recent20_Correct": sum(self._probe_recent),
            "Probe_Recent20_Choices": len(self._probe_recent),
            "Probe_All_Correct": self._probe_correct,
            "Probe_All_Choices": self._probe_choices,
            "Regular_All_Correct": self._regular_correct,
            "Regular_All_Choices": self._regular_choices,
        })
        return data, pause

    def _write_trial(self, trial_data):
        super()._write_trial(trial_data)
        # CMD-only readout of the brightness values actually used in this trial.
        # Read the per-trial snapshot so runtime UI edits are reflected correctly.
        correct_side = trial_data["Correct_Target"]
        other_side = "Up" if correct_side == "Right" else "Right"
        if trial_data["Trial_Type"] == "Easy_Probe":
            bright = trial_data["Probe_Bright_Level"]
            dark = trial_data["Probe_Dark_Level"]
            print(
                f"[Brightness] Trial {trial_data['Trial']} | EASY PROBE | "
                f"Cue={trial_data['Cue_Brightness_Level']} | "
                f"Bright={bright} ({correct_side}) | Dark={dark} ({other_side})"
            )
        else:
            match = trial_data["Regular_Match_Choice_Brightness_Level"]
            distractor = trial_data["Regular_Distractor_Choice_Brightness_Level"]
            print(
                f"[Brightness] Trial {trial_data['Trial']} | REGULAR | "
                f"Cue={trial_data['Cue_Brightness_Level']} | "
                f"Match={match} ({correct_side}) | "
                f"Distractor={distractor} ({other_side})"
            )
        def rate(correct, total):
            return f"{correct / total:.1%} ({correct}/{total})" if total else "N/A (0/0)"
        print(f"[Accuracy] Trial type: {trial_data['Trial_Type']}")
        print("[Accuracy] Easy probe last 20: " + rate(sum(self._probe_recent), len(self._probe_recent)))
        print("[Accuracy] Easy probe all: " + rate(self._probe_correct, self._probe_choices))
        print("[Accuracy] Regular last 40: " + rate(sum(self._regular_recent), len(self._regular_recent)))
        print("[Accuracy] Regular all: " + rate(self._regular_correct, self._regular_choices))

    def _poll_training_commands(self, allow_orientation_override=False):
        # Retain Esc/N; H/V can still force Right/Up for experimenter testing.
        return super()._poll_training_commands(allow_orientation_override)


if __name__ == "__main__":
    freeze_support()
    main(
        task_class=BrightnessMatching2AFCTrainingTask,
        task_name="BrightnessMatching2AFCTrainingTask",
        default_params=DEFAULT_PARAMS,
        parameter_groups=PARAMETER_GROUPS,
        parameter_validator=validate_brightness_params,
        saved_params_migrator=None,
        session_prefix="BrightnessMatching2AFC",
        control_title="Brightness Matching 2AFC",
        task_label="Brightness Matching 2AFC training",
    )
