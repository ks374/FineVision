"""Orientation 2AFC training with horizontal and vertical bar stimuli."""

import math
from multiprocessing import freeze_support

from psychopy import visual

from Orientation2AFCTrainingLogic import choice_target_arrangement
from Orientation2AFCTrainingTask import (
    DEFAULT_PARAMS as DOT_DEFAULT_PARAMS,
    TRIAL_LOG_FIELDS,
    Orientation2AFCTrainingTask,
    _validate_common_params,
    main as run_orientation_2afc_session,
)


BAR_STAGE_OPTIONS = [
    "Stage 1 - single target",
    "Stage 2 - bar cue plus single target",
    "Stage 3 - bar cue plus two bar targets",
    "Stage 4 - bar cue plus two single-dot targets",
]


BAR_DEFAULT_PARAMS = DOT_DEFAULT_PARAMS.copy()
BAR_DEFAULT_PARAMS["Training Stage"] = BAR_STAGE_OPTIONS.copy()
for obsolete_field in (
    "Cue Dot Radius (deg)",
    "Cue Dot Center Distance (deg)",
    "Cue Dot Opacity (0-1)",
    "Choice Dot Center Distance (deg)",
):
    BAR_DEFAULT_PARAMS.pop(obsolete_field)
BAR_DEFAULT_PARAMS.update(
    {
        "Cue Bar Length (deg)": 2.0,
        "Cue Bar Width (deg)": 0.4,
        "Cue Bar Opacity (0-1)": 1.0,
        "Choice Bar Length (deg)": 1.5,
        "Choice Bar Width (deg)": 0.35,
    }
)


BAR_PARAMETER_GROUPS = {
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
    "Bar Cue": [
        "Cue Center Position X (deg)",
        "Cue Center Position Y (deg)",
        "Cue Bar Length (deg)",
        "Cue Bar Width (deg)",
        "Cue Brightness Level (0-182)",
        "Cue Bar Opacity (0-1)",
    ],
    "Choice Targets": [
        "Right Target Position X (deg)",
        "Right Target Position Y (deg)",
        "Up Target Position X (deg)",
        "Up Target Position Y (deg)",
        "Target Point Radius (deg)",
        "Choice Bar Length (deg)",
        "Choice Bar Width (deg)",
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


_DOT_SHAPE_LOG_FIELDS = {
    "Cue_Dot_Radius_deg",
    "Cue_Dot_Center_Distance_deg",
    "Cue_Dot_Arrangement",
    "Cue_Dot_Opacity",
    "Choice_Dot_Center_Distance_deg",
}


def _replace_dot_shape_fields(fields):
    bar_fields = []
    for field in fields:
        if field == "Cue_Dot_Radius_deg":
            bar_fields.extend(
                (
                    "Cue_Bar_Length_deg",
                    "Cue_Bar_Width_deg",
                    "Cue_Bar_Orientation",
                )
            )
        elif field == "Cue_Dot_Opacity":
            bar_fields.append("Cue_Bar_Opacity")
        elif field == "Choice_Dot_Center_Distance_deg":
            bar_fields.extend(
                (
                    "Choice_Bar_Length_deg",
                    "Choice_Bar_Width_deg",
                )
            )
        elif field not in _DOT_SHAPE_LOG_FIELDS:
            bar_fields.append(field)
    return tuple(bar_fields)


BAR_TRIAL_LOG_FIELDS = list(_replace_dot_shape_fields(TRIAL_LOG_FIELDS))


def validate_bar_params(params):
    _validate_common_params(params, "Cue Bar Opacity (0-1)")

    for field in (
        "Cue Bar Length (deg)",
        "Cue Bar Width (deg)",
        "Choice Bar Length (deg)",
        "Choice Bar Width (deg)",
    ):
        if float(params[field]) <= 0:
            raise ValueError(f"{field} must be greater than zero.")

    cue_length = float(params["Cue Bar Length (deg)"])
    cue_width = float(params["Cue Bar Width (deg)"])
    if cue_length <= cue_width:
        raise ValueError("Cue Bar Length (deg) must exceed its width.")

    choice_length = float(params["Choice Bar Length (deg)"])
    choice_width = float(params["Choice Bar Width (deg)"])
    if choice_length <= choice_width:
        raise ValueError("Choice Bar Length (deg) must exceed its width.")

    half_diagonal = math.hypot(choice_length / 2.0, choice_width / 2.0)
    if half_diagonal > float(params["Target Window Radius (deg)"]):
        raise ValueError(
            "The Stage 3 choice bar must fit inside its target window."
        )


class OrientationBar2AFCTrainingTask(Orientation2AFCTrainingTask):
    """Use oriented bars while preserving the shared 2AFC trial logic."""

    stage_options = BAR_STAGE_OPTIONS
    task_display_name = "Orientation Bar 2AFC Training Task"
    mapping_description = "Horizontal bar -> Right; Vertical bar -> Up"

    def _task_log_filename(self):
        return f"OrientationBar2AFC_task_log_{self.session_timestamp}.csv"

    def _trial_log_fields(self):
        return BAR_TRIAL_LOG_FIELDS

    def _validate_current_params(self, params):
        validate_bar_params(params)

    def _tracker_trial_variable_fields(self):
        return _replace_dot_shape_fields(
            super()._tracker_trial_variable_fields()
        )

    def _load_cue_shape_params(self, params):
        self.cue_bar_length_deg = float(params["Cue Bar Length (deg)"])
        self.cue_bar_width_deg = float(params["Cue Bar Width (deg)"])
        # Compatibility aliases used only by shared setup code.
        self.cue_dot_radius_deg = self.cue_bar_width_deg / 2.0
        self.cue_dot_distance_deg = self.cue_bar_length_deg

    def _load_cue_shape_opacity(self, params):
        self.cue_bar_opacity = float(params["Cue Bar Opacity (0-1)"])
        self.cue_dot_opacity = self.cue_bar_opacity

    def _load_choice_shape_params(self, params):
        self.target_point_radius_deg = float(params["Target Point Radius (deg)"])
        self.choice_bar_length_deg = float(params["Choice Bar Length (deg)"])
        self.choice_bar_width_deg = float(params["Choice Bar Width (deg)"])
        self.choice_dot_distance_deg = self.choice_bar_length_deg

    def _update_shape_pixels(self):
        super()._update_shape_pixels()
        self.cue_bar_length_x_px = self._to_x_pixels(
            self.cue_bar_length_deg
        )
        self.cue_bar_length_y_px = self._to_y_pixels(
            self.cue_bar_length_deg
        )
        self.cue_bar_width_x_px = self._to_x_pixels(self.cue_bar_width_deg)
        self.cue_bar_width_y_px = self._to_y_pixels(self.cue_bar_width_deg)
        self.choice_bar_length_x_px = self._to_x_pixels(
            self.choice_bar_length_deg
        )
        self.choice_bar_length_y_px = self._to_y_pixels(
            self.choice_bar_length_deg
        )
        self.choice_bar_width_x_px = self._to_x_pixels(
            self.choice_bar_width_deg
        )
        self.choice_bar_width_y_px = self._to_y_pixels(
            self.choice_bar_width_deg
        )

    def _build_visuals(self):
        super()._build_visuals()
        self.cue_bar_sub = visual.Rect(
            self.win_sub,
            width=1,
            height=1,
            fillColor=self.cue_psychopy_color,
            lineColor=self.cue_psychopy_color,
            opacity=self.cue_bar_opacity,
        )
        self.cue_bar_ctl = visual.Rect(
            self.win_ctl,
            width=1,
            height=1,
            fillColor=self.cue_psychopy_color,
            lineColor=self.cue_psychopy_color,
            opacity=self.cue_bar_opacity,
        )

        self.target_bar_sub = {}
        self.target_bar_ctl = {}
        for name, (x_px, y_px) in self.target_positions_px.items():
            self.target_bar_sub[name] = visual.Rect(
                self.win_sub,
                width=1,
                height=1,
                fillColor=self.choice_target_psychopy_color,
                lineColor=self.choice_target_psychopy_color,
                pos=(x_px, y_px),
            )
            self.target_bar_ctl[name] = visual.Rect(
                self.win_ctl,
                width=1,
                height=1,
                fillColor="white",
                lineColor="white",
                pos=(x_px * self.scale_x, y_px * self.scale_y),
            )

    def _bar_size_px(self, orientation, *, choice):
        prefix = "choice_bar" if choice else "cue_bar"
        length_x = getattr(self, f"{prefix}_length_x_px")
        length_y = getattr(self, f"{prefix}_length_y_px")
        width_x = getattr(self, f"{prefix}_width_x_px")
        width_y = getattr(self, f"{prefix}_width_y_px")
        if orientation == "Horizontal":
            return length_x, width_y
        if orientation == "Vertical":
            return width_x, length_y
        raise ValueError(f"Unknown bar orientation: {orientation}")

    def _draw_cue(self, orientation):
        width_px, height_px = self._bar_size_px(orientation, choice=False)
        self.cue_bar_sub.pos = (self.cue_center_x_px, self.cue_center_y_px)
        self.cue_bar_sub.size = (width_px, height_px)
        self.cue_bar_sub.opacity = self.cue_bar_opacity
        self.cue_bar_ctl.pos = (
            self.cue_center_x_px * self.scale_x,
            self.cue_center_y_px * self.scale_y,
        )
        self.cue_bar_ctl.size = (
            width_px * self.scale_x,
            height_px * self.scale_y,
        )
        self.cue_bar_ctl.opacity = self.cue_bar_opacity
        self.cue_bar_sub.draw()
        self.cue_bar_ctl.draw()

    def _draw_choice_target(self, name, correct_target, wrong_opacity):
        if self.stage != 3:
            super()._draw_choice_target(name, correct_target, wrong_opacity)
            return

        opacity = self._target_opacity(name, correct_target, wrong_opacity)
        control_color = "green" if name == correct_target else "red"
        orientation = choice_target_arrangement(name)
        width_px, height_px = self._bar_size_px(orientation, choice=True)
        x_px, y_px = self.target_positions_px[name]

        subject_bar = self.target_bar_sub[name]
        subject_bar.pos = (x_px, y_px)
        subject_bar.size = (width_px, height_px)
        subject_bar.opacity = opacity
        subject_bar.draw()

        control_bar = self.target_bar_ctl[name]
        control_bar.pos = (x_px * self.scale_x, y_px * self.scale_y)
        control_bar.size = (
            width_px * self.scale_x,
            height_px * self.scale_y,
        )
        control_bar.opacity = max(opacity, 0.25)
        control_bar.fillColor = control_color
        control_bar.lineColor = control_color
        control_bar.draw()

        window = self.target_window_ctl[name]
        window.lineColor = control_color
        window.draw()

    def _feedback_cue_size_px(self, orientation):
        width_px, height_px = self._bar_size_px(orientation, choice=False)
        padding = max(4.0, min(width_px, height_px) * 0.75)
        return width_px + 2.0 * padding, height_px + 2.0 * padding

    def _feedback_target_size_px(self, correct_target):
        if self.stage != 3:
            return super()._feedback_target_size_px(correct_target)
        orientation = choice_target_arrangement(correct_target)
        width_px, height_px = self._bar_size_px(orientation, choice=True)
        padding = max(4.0, min(width_px, height_px) * 0.75)
        return width_px + 2.0 * padding, height_px + 2.0 * padding

    def _new_trial_data(self, trial_number, orientation, stim_delay_s):
        trial_data = super()._new_trial_data(
            trial_number,
            orientation,
            stim_delay_s,
        )
        for field in _DOT_SHAPE_LOG_FIELDS:
            trial_data.pop(field, None)
        trial_data.update(
            {
                "Cue_Bar_Length_deg": self.cue_bar_length_deg,
                "Cue_Bar_Width_deg": self.cue_bar_width_deg,
                "Cue_Bar_Orientation": orientation,
                "Cue_Bar_Opacity": self.cue_bar_opacity,
                "Choice_Bar_Length_deg": self.choice_bar_length_deg,
                "Choice_Bar_Width_deg": self.choice_bar_width_deg,
                "Choice_Target_Style": (
                    "Bars" if self.stage == 3 else "Single_Dot"
                ),
            }
        )
        return trial_data


def main(tracker_mode="qy"):
    return run_orientation_2afc_session(
        tracker_mode,
        task_class=OrientationBar2AFCTrainingTask,
        task_name="OrientationBar2AFCTrainingTask",
        default_params=BAR_DEFAULT_PARAMS,
        parameter_groups=BAR_PARAMETER_GROUPS,
        parameter_validator=validate_bar_params,
        saved_params_migrator=None,
        session_prefix="OrientationBar2AFC",
        control_title="Orientation Bar 2AFC",
        task_label="Orientation Bar 2AFC training",
    )


if __name__ == "__main__":
    freeze_support()
    main()
