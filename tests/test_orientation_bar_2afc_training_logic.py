import unittest
from types import SimpleNamespace

from OrientationBar2AFCTrainingTask import (
    BAR_DEFAULT_PARAMS,
    BAR_PARAMETER_GROUPS,
    BAR_STAGE_OPTIONS,
    BAR_TRIAL_LOG_FIELDS,
    OrientationBar2AFCTrainingTask,
    validate_bar_params,
)
from Orientation2AFCTrainingTask import DEFAULT_PARAMS as DOT_DEFAULT_PARAMS
from Orientation2AFCTrainingTask import Orientation2AFCTrainingTask


class FakeStimulus:
    def __init__(self):
        self.draw_count = 0
        self.opacity = None

    def draw(self):
        self.draw_count += 1


class OrientationBarTrainingTests(unittest.TestCase):
    def test_bar_task_has_independent_stage_labels_and_parameters(self):
        self.assertEqual(
            BAR_STAGE_OPTIONS[2],
            "Stage 3 - bar cue plus two bar targets",
        )
        self.assertIn("Cue Bar Length (deg)", BAR_DEFAULT_PARAMS)
        self.assertIn("Choice Bar Width (deg)", BAR_DEFAULT_PARAMS)
        self.assertNotIn("Cue Dot Radius (deg)", BAR_DEFAULT_PARAMS)
        self.assertNotIn("Choice Dot Center Distance (deg)", BAR_DEFAULT_PARAMS)

        assigned = {
            field
            for fields in BAR_PARAMETER_GROUPS.values()
            for field in fields
        }
        self.assertEqual(set(BAR_DEFAULT_PARAMS), assigned)

    def test_shared_training_features_keep_the_same_defaults(self):
        for field in (
            "Show Post-Trial Teaching Feedback",
            "Give Feedback First",
            "First Feedback Opacity (0-1)",
            "Use Visual Cue as Fixation Point",
            "Keep Cue Visible During Choice",
            "Cue Brightness Level (0-182)",
            "Choice Target Brightness Level (0-182)",
            "Correct Choice Hold Time (ms)",
        ):
            self.assertEqual(BAR_DEFAULT_PARAMS[field], DOT_DEFAULT_PARAMS[field])

    def test_bar_task_inherits_the_shared_choice_feedback_logic(self):
        self.assertIs(
            OrientationBar2AFCTrainingTask._run_teaching_feedback,
            Orientation2AFCTrainingTask._run_teaching_feedback,
        )

    def test_bar_dimensions_are_validated(self):
        params = BAR_DEFAULT_PARAMS.copy()
        params["Training Stage"] = BAR_STAGE_OPTIONS[2]
        validate_bar_params(params)

        params["Cue Bar Length (deg)"] = params["Cue Bar Width (deg)"]
        with self.assertRaisesRegex(ValueError, "must exceed its width"):
            validate_bar_params(params)

    def test_choice_bar_must_fit_inside_target_window(self):
        params = BAR_DEFAULT_PARAMS.copy()
        params["Training Stage"] = BAR_STAGE_OPTIONS[2]
        params["Choice Bar Length (deg)"] = 5.0
        params["Target Window Radius (deg)"] = 2.0
        with self.assertRaisesRegex(ValueError, "fit inside"):
            validate_bar_params(params)

    def test_horizontal_and_vertical_bar_sizes_swap_axes(self):
        task = OrientationBar2AFCTrainingTask.__new__(
            OrientationBar2AFCTrainingTask
        )
        task.cue_bar_length_x_px = 100.0
        task.cue_bar_length_y_px = 120.0
        task.cue_bar_width_x_px = 20.0
        task.cue_bar_width_y_px = 24.0

        self.assertEqual(
            task._bar_size_px("Horizontal", choice=False),
            (100.0, 24.0),
        )
        self.assertEqual(
            task._bar_size_px("Vertical", choice=False),
            (20.0, 120.0),
        )

    def test_stage_3_choice_uses_oriented_bar(self):
        task = OrientationBar2AFCTrainingTask.__new__(
            OrientationBar2AFCTrainingTask
        )
        task.stage = 3
        task.correct_target_opacity = 0.8
        task.scale_x = 0.5
        task.scale_y = 0.5
        task.choice_bar_length_x_px = 100.0
        task.choice_bar_length_y_px = 120.0
        task.choice_bar_width_x_px = 20.0
        task.choice_bar_width_y_px = 24.0
        task.target_positions_px = {"Right": (200.0, 10.0)}
        task.target_bar_sub = {"Right": FakeStimulus()}
        task.target_bar_ctl = {"Right": FakeStimulus()}
        task.target_window_ctl = {"Right": FakeStimulus()}

        task._draw_choice_target("Right", "Right", wrong_opacity=0.1)

        subject_bar = task.target_bar_sub["Right"]
        control_bar = task.target_bar_ctl["Right"]
        self.assertEqual(subject_bar.size, (100.0, 24.0))
        self.assertEqual(subject_bar.pos, (200.0, 10.0))
        self.assertEqual(subject_bar.opacity, 0.8)
        self.assertEqual(control_bar.size, (50.0, 12.0))
        self.assertEqual(subject_bar.draw_count, 1)
        self.assertEqual(task.target_window_ctl["Right"].draw_count, 1)

    def test_bar_logs_replace_dot_geometry_fields(self):
        self.assertIn("Cue_Bar_Length_deg", BAR_TRIAL_LOG_FIELDS)
        self.assertIn("Cue_Bar_Width_deg", BAR_TRIAL_LOG_FIELDS)
        self.assertIn("Choice_Bar_Length_deg", BAR_TRIAL_LOG_FIELDS)
        self.assertNotIn("Cue_Dot_Radius_deg", BAR_TRIAL_LOG_FIELDS)
        self.assertNotIn(
            "Choice_Dot_Center_Distance_deg",
            BAR_TRIAL_LOG_FIELDS,
        )

        task = OrientationBar2AFCTrainingTask.__new__(
            OrientationBar2AFCTrainingTask
        )
        tracker_fields = task._tracker_trial_variable_fields()
        self.assertIn("Cue_Bar_Orientation", tracker_fields)
        self.assertIn("Choice_Bar_Width_deg", tracker_fields)
        self.assertNotIn("Cue_Dot_Arrangement", tracker_fields)

    def test_bar_parameters_load_and_produce_a_complete_trial_row(self):
        params = BAR_DEFAULT_PARAMS.copy()
        params["Training Stage"] = BAR_STAGE_OPTIONS[2]
        task = OrientationBar2AFCTrainingTask.__new__(
            OrientationBar2AFCTrainingTask
        )
        task.task_manager = SimpleNamespace(exp_params=params)
        task.win_sub = SimpleNamespace(size=(1920, 1080), color=None)
        task.win_ctl = SimpleNamespace(size=(800, 450), color=None)
        task._build_visuals = lambda: None

        task.update_params()
        task._last_orientation_source = "Random"
        trial_data = task._new_trial_data(1, "Horizontal", 0.5)

        self.assertEqual(task.cue_bar_length_deg, 2.0)
        self.assertEqual(task.choice_bar_width_deg, 0.35)
        self.assertEqual(set(trial_data), set(BAR_TRIAL_LOG_FIELDS))
        self.assertEqual(trial_data["Choice_Target_Style"], "Bars")
        self.assertNotIn("Cue_Dot_Radius_deg", trial_data)


if __name__ == "__main__":
    unittest.main()
