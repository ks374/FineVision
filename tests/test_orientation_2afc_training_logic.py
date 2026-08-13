import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from Orientation2AFCTrainingLogic import (
    choice_accuracy_counts,
    choice_target_arrangement,
    correct_target_for_orientation,
    dot_pair_positions,
    stage_number,
)
from Orientation2AFCTrainingTask import (
    DEFAULT_PARAMS,
    INCORRECT_CHOICE_HOLD_S,
    TEACHING_FEEDBACK_DURATION_S,
    Orientation2AFCTrainingTask,
    _migrate_legacy_saved_params,
    _validate_params,
)


class OrientationTrainingLogicTests(unittest.TestCase):
    def test_stage_and_orientation_mapping(self):
        self.assertEqual(
            stage_number("Stage 3 - dot pair plus two paired-dot targets"),
            3,
        )
        self.assertEqual(
            stage_number("Stage 4 - dot pair plus two single-dot targets"),
            4,
        )
        # Preserve compatibility with a previously saved parameter file.
        self.assertEqual(stage_number("Stage 3 - bar plus two targets"), 3)
        self.assertEqual(correct_target_for_orientation("Horizontal"), "Right")
        self.assertEqual(correct_target_for_orientation("Vertical"), "Up")
        self.assertEqual(choice_target_arrangement("Right"), "Horizontal")
        self.assertEqual(choice_target_arrangement("Up"), "Vertical")

    def test_h_or_v_override_is_used_once_without_consuming_random_bag(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._next_orientation_override = "Vertical"
        task._orientation_bag = ["Horizontal"]

        self.assertEqual(task._next_orientation(), "Vertical")
        self.assertEqual(task._last_orientation_source, "Manual_H_or_V")
        self.assertEqual(task._orientation_bag, ["Horizontal"])
        self.assertIsNone(task._next_orientation_override)

        self.assertEqual(task._next_orientation(), "Horizontal")
        self.assertEqual(task._last_orientation_source, "Random")

    def test_iti_h_and_v_keys_set_last_pressed_orientation(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._escape_suppressed_until = 0.0

        with patch(
            "Orientation2AFCTrainingTask.event.getKeys",
            return_value=["h", "v"],
        ), patch("Orientation2AFCTrainingTask.time.perf_counter", return_value=1.0):
            pause_requested = task._poll_training_commands(
                allow_orientation_override=True
            )

        self.assertFalse(pause_requested)
        self.assertEqual(task._next_orientation_override, "Vertical")

    def test_h_or_v_is_ignored_outside_iti(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._escape_suppressed_until = 0.0

        with patch(
            "Orientation2AFCTrainingTask.event.getKeys",
            return_value=["h"],
        ), patch("Orientation2AFCTrainingTask.time.perf_counter", return_value=1.0):
            task._poll_training_commands(allow_orientation_override=False)

        self.assertFalse(hasattr(task, "_next_orientation_override"))

    def test_wrong_choice_commits_at_50ms_but_correct_uses_parameter(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.correct_choice_hold_s = 0.5

        self.assertEqual(INCORRECT_CHOICE_HOLD_S, 0.05)
        self.assertEqual(
            task._required_choice_hold_s("Up", "Right"),
            0.05,
        )
        self.assertEqual(
            task._required_choice_hold_s("Right", "Right"),
            0.5,
        )
        self.assertEqual(
            DEFAULT_PARAMS["Correct Choice Hold Time (ms)"],
            500,
        )

    def test_cue_as_fixation_skips_separate_cue_phase(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.use_visual_cue_as_fixation = True
        self.assertFalse(task._uses_separate_cue_phase())

        task.use_visual_cue_as_fixation = False
        self.assertTrue(task._uses_separate_cue_phase())

        task.stage = 1
        self.assertFalse(task._uses_separate_cue_phase())

    def test_visual_cue_as_fixation_defaults_off(self):
        self.assertFalse(DEFAULT_PARAMS["Use Visual Cue as Fixation Point"])

    def test_keep_cue_visible_during_choice_defaults_off(self):
        self.assertFalse(DEFAULT_PARAMS["Keep Cue Visible During Choice"])

    def test_give_feedback_first_defaults_off_with_full_opacity(self):
        self.assertFalse(DEFAULT_PARAMS["Give Feedback First"])
        self.assertEqual(DEFAULT_PARAMS["First Feedback Opacity (0-1)"], 1.0)

    def test_choice_onset_keeps_cue_visible_when_enabled(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.use_visual_cue_as_fixation = True
        task.keep_cue_visible_during_choice = True
        task.give_feedback_first = False
        scheduled_fields = []
        presented_frames = []
        task._schedule_flip_time = (
            lambda trial_data, field: scheduled_fields.append(field)
        )
        task._present_training_frame = lambda **kwargs: (
            presented_frames.append(kwargs) or ({}, False)
        )
        trial_data = {
            "Time_StimOn": 0.0,
            "Orientation": "Horizontal",
            "Correct_Target": "Right",
            "Wrong_Target_Opacity": 0.1,
        }

        task._show_choice_onset(trial_data)

        self.assertNotIn("Time_StimOff", scheduled_fields)
        self.assertIn("Time_FixationPointOff", scheduled_fields)
        self.assertIn("Time_ChoiceOn", scheduled_fields)
        self.assertTrue(presented_frames[0]["cue_visible"])

    def test_choice_onset_hides_cue_when_option_is_disabled(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.use_visual_cue_as_fixation = True
        task.keep_cue_visible_during_choice = False
        task.give_feedback_first = False
        scheduled_fields = []
        presented_frames = []
        task._schedule_flip_time = (
            lambda trial_data, field: scheduled_fields.append(field)
        )
        task._present_training_frame = lambda **kwargs: (
            presented_frames.append(kwargs) or ({}, False)
        )
        trial_data = {
            "Time_StimOn": 0.0,
            "Orientation": "Horizontal",
            "Correct_Target": "Right",
            "Wrong_Target_Opacity": 0.1,
        }

        task._show_choice_onset(trial_data)

        self.assertIn("Time_StimOff", scheduled_fields)
        self.assertFalse(presented_frames[0]["cue_visible"])

    def test_keep_cue_option_does_not_introduce_a_stage_1_cue(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 1
        task.use_visual_cue_as_fixation = False
        task.keep_cue_visible_during_choice = True
        task.give_feedback_first = False

        self.assertFalse(task._cue_visible_during_choice())

        task.keep_cue_visible_during_choice = False
        task.give_feedback_first = True
        self.assertFalse(task._cue_visible_during_choice())
        self.assertFalse(task._first_feedback_during_choice())

    def test_give_feedback_first_keeps_cue_and_is_shown_at_choice_onset(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.use_visual_cue_as_fixation = True
        task.keep_cue_visible_during_choice = False
        task.give_feedback_first = True
        scheduled_fields = []
        presented_frames = []
        task._schedule_flip_time = (
            lambda trial_data, field: scheduled_fields.append(field)
        )
        task._present_training_frame = lambda **kwargs: (
            presented_frames.append(kwargs) or ({}, False)
        )
        trial_data = {
            "Time_StimOn": 0.0,
            "Orientation": "Vertical",
            "Correct_Target": "Up",
            "Wrong_Target_Opacity": 0.1,
        }

        task._show_choice_onset(trial_data)

        self.assertNotIn("Time_StimOff", scheduled_fields)
        self.assertTrue(presented_frames[0]["cue_visible"])
        self.assertTrue(presented_frames[0]["first_feedback"])

    def test_first_feedback_draws_cue_box_and_line_without_target_box(self):
        class FakeStimulus:
            def __init__(self):
                self.draw_count = 0
                self.opacity = None

            def draw(self):
                self.draw_count += 1

        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 4
        task.cue_dot_radius_px = 5.0
        task.cue_dot_distance_x_px = 12.0
        task.cue_dot_distance_y_px = 10.0
        task.target_point_radius_px = 5.0
        task.choice_dot_distance_x_px = 8.0
        task.choice_dot_distance_y_px = 8.0
        task.cue_center_x_px = 0.0
        task.cue_center_y_px = 0.0
        task.target_positions_px = {"Right": (100.0, 0.0)}
        task.scale_x = 1.0
        task.scale_y = 1.0
        task.feedback_cue_box_sub = FakeStimulus()
        task.feedback_cue_box_ctl = FakeStimulus()
        task.feedback_target_box_sub = FakeStimulus()
        task.feedback_target_box_ctl = FakeStimulus()
        task.feedback_connection_sub = FakeStimulus()
        task.feedback_connection_ctl = FakeStimulus()

        task._draw_feedback_mapping(
            "Horizontal",
            "Right",
            include_target_box=False,
            opacity=0.35,
        )

        for stimulus in (
            task.feedback_cue_box_sub,
            task.feedback_cue_box_ctl,
            task.feedback_connection_sub,
            task.feedback_connection_ctl,
        ):
            self.assertEqual(stimulus.draw_count, 1)
            self.assertEqual(stimulus.opacity, 0.35)
        self.assertEqual(task.feedback_target_box_sub.draw_count, 0)
        self.assertEqual(task.feedback_target_box_ctl.draw_count, 0)

    def test_first_feedback_opacity_must_be_between_zero_and_one(self):
        for value in (-0.1, 1.1):
            params = DEFAULT_PARAMS.copy()
            params["Training Stage"] = params["Training Stage"][0]
            params["First Feedback Opacity (0-1)"] = value
            with self.assertRaisesRegex(ValueError, "range 0-1"):
                _validate_params(params)

    def test_horizontal_dot_pair_uses_adjustable_center_and_distance(self):
        self.assertEqual(
            dot_pair_positions(1.0, -2.0, 4.0, 6.0, "Horizontal"),
            ((-1.0, -2.0), (3.0, -2.0)),
        )

    def test_vertical_dot_pair_uses_adjustable_center_and_distance(self):
        self.assertEqual(
            dot_pair_positions(1.0, -2.0, 4.0, 6.0, "Vertical"),
            ((1.0, -5.0), (1.0, 1.0)),
        )

    def test_dot_pair_parameters_require_separate_dots(self):
        params = DEFAULT_PARAMS.copy()
        params["Training Stage"] = params["Training Stage"][0]
        params["Cue Dot Radius (deg)"] = 0.5
        params["Cue Dot Center Distance (deg)"] = 1.0
        with self.assertRaisesRegex(ValueError, "remain separate"):
            _validate_params(params)

    def test_2afc_recalibration_uses_shared_subject_screen_flow(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.tracker_backend = SimpleNamespace(supports_recalibration=True)
        task.win_sub = object()
        task.win_ctl = object()
        task.viewing_distance_cm = 60.0
        task.monitor_width_cm = 54.0
        task.monitor_height_cm = 30.0
        task.fix_point_radius_deg = 0.2
        task.background_psychopy_color = (-0.6863, -0.6863, -0.6863)
        task.arduino = object()
        task.gaze_renderer = SimpleNamespace(reset_trail=lambda: None)
        task._send_tracker_event = lambda message: None
        task._present_training_frame = lambda: (None, False)

        with patch(
            "Orientation2AFCTrainingTask.run_in_session_calibration"
        ) as recalibrate, patch(
            "Orientation2AFCTrainingTask.event.clearEvents"
        ):
            task._recalibrate_eyelink()

        kwargs = recalibrate.call_args.kwargs
        self.assertIs(kwargs["tracker_backend"], task.tracker_backend)
        self.assertIs(kwargs["win_subject"], task.win_sub)
        self.assertEqual(kwargs["subject_screen_index"], 1)
        self.assertEqual(
            kwargs["background_color"],
            task.background_psychopy_color,
        )

    def test_2afc_background_defaults_to_calibrated_gray_five(self):
        params = DEFAULT_PARAMS.copy()
        params["Training Stage"] = params["Training Stage"][0]
        self.assertEqual(params["Background Gray Level (0-182)"], 5)
        _validate_params(params)

        params["Background Gray Level (0-182)"] = 183
        with self.assertRaisesRegex(ValueError, "between 0 and 182"):
            _validate_params(params)

    def test_cue_and_choice_brightness_default_to_level_160(self):
        self.assertEqual(DEFAULT_PARAMS["Cue Brightness Level (0-182)"], 160)
        self.assertEqual(
            DEFAULT_PARAMS["Choice Target Brightness Level (0-182)"],
            160,
        )

    def test_teaching_feedback_is_fixed_at_two_seconds_and_optional(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.show_teaching_feedback = True
        trial_data = {"Time_ChoiceOn": 1.0, "Choice": "Right"}

        self.assertEqual(TEACHING_FEEDBACK_DURATION_S, 2.0)
        self.assertTrue(task._teaching_feedback_is_due(trial_data))

        task.show_teaching_feedback = False
        self.assertFalse(task._teaching_feedback_is_due(trial_data))
        task.show_teaching_feedback = True
        task.stage = 2
        self.assertFalse(task._teaching_feedback_is_due(trial_data))
        task.stage = 3
        trial_data["Choice"] = ""
        self.assertFalse(task._teaching_feedback_is_due(trial_data))

    def test_correct_choice_feedback_replays_choice_with_yellow_mapping(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.show_teaching_feedback = True
        clock = [0.0]
        presented_frames = []
        task.now = lambda: clock[0]

        def schedule(trial_data, field):
            if trial_data[field] is None:
                trial_data[field] = clock[0]

        def present(**kwargs):
            presented_frames.append(kwargs)
            clock[0] += 0.5
            return {}, False

        task._schedule_flip_time = schedule
        task._present_training_frame = present
        trial_data = {
            "Time_FixOn": 0.0,
            "Time_FixationPointOff": 0.0,
            "Time_StimOn": 0.5,
            "Time_StimOff": 1.0,
            "Time_ChoiceOn": 1.0,
            "Time_ChoiceOff": None,
            "Time_FeedbackOn": None,
            "Time_FeedbackOff": None,
            "Orientation": "Horizontal",
            "Correct_Target": "Right",
            "Choice": "Right",
            "Choice_Correct": True,
            "Wrong_Target_Opacity": 0.15,
            "Teaching_Feedback_Shown": False,
        }

        pause_requested = task._run_teaching_feedback(trial_data)

        feedback_frames = [
            frame for frame in presented_frames if frame.get("teaching_feedback")
        ]
        self.assertFalse(pause_requested)
        self.assertTrue(trial_data["Teaching_Feedback_Shown"])
        self.assertEqual(trial_data["Time_FeedbackOn"], 0.0)
        self.assertEqual(trial_data["Time_FeedbackOff"], 2.0)
        self.assertEqual(len(feedback_frames), 4)
        self.assertEqual(feedback_frames[0]["orientation"], "Horizontal")
        self.assertEqual(feedback_frames[0]["target_only"], "Right")
        self.assertTrue(feedback_frames[0]["teaching_feedback"])
        self.assertNotIn("force_all_targets", feedback_frames[0])

    def test_incorrect_choice_feedback_replays_wrong_choice_without_yellow(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.show_teaching_feedback = True
        clock = [0.0]
        presented_frames = []
        task.now = lambda: clock[0]

        def schedule(trial_data, field):
            if trial_data[field] is None:
                trial_data[field] = clock[0]

        def present(**kwargs):
            presented_frames.append(kwargs)
            clock[0] += 0.5
            return {}, False

        task._schedule_flip_time = schedule
        task._present_training_frame = present
        trial_data = {
            "Time_FixOn": 0.0,
            "Time_FixationPointOff": 0.0,
            "Time_StimOn": 0.5,
            "Time_StimOff": 1.0,
            "Time_ChoiceOn": 1.0,
            "Time_ChoiceOff": None,
            "Time_FeedbackOn": None,
            "Time_FeedbackOff": None,
            "Orientation": "Horizontal",
            "Correct_Target": "Right",
            "Choice": "Up",
            "Choice_Correct": False,
            "Wrong_Target_Opacity": 0.15,
            "Teaching_Feedback_Shown": False,
        }

        task._run_teaching_feedback(trial_data)

        choice_frames = [
            frame for frame in presented_frames if frame.get("targets_visible")
        ]
        self.assertEqual(len(choice_frames), 4)
        self.assertTrue(trial_data["Teaching_Feedback_Shown"])
        self.assertEqual(choice_frames[0]["target_only"], "Up")
        self.assertEqual(choice_frames[0]["correct_target"], "Right")
        self.assertFalse(choice_frames[0]["teaching_feedback"])
        self.assertTrue(choice_frames[0]["cue_visible"])

    def test_feedback_line_connects_nearest_frame_edges(self):
        start, end = (
            Orientation2AFCTrainingTask._feedback_connection_endpoints(
                cue_center=(0.0, 0.0),
                cue_size=(4.0, 2.0),
                target_center=(10.0, 0.0),
                target_size=(2.0, 2.0),
            )
        )

        self.assertEqual(start, (2.0, 0.0))
        self.assertEqual(end, (9.0, 0.0))

    def test_recent_accuracy_uses_last_40_completed_choices(self):
        trials = [
            {"Choice_Correct": index % 3 != 0}
            for index in range(50)
        ]
        trials.insert(45, {"Choice_Correct": ""})
        trials.insert(48, {"Choice_Correct": ""})
        trials.append({"Status": "NoChoice"})

        total_correct, total_choices = choice_accuracy_counts(trials)
        recent_correct, recent_choices = choice_accuracy_counts(
            trials,
            recent_limit=40,
        )

        self.assertEqual(total_choices, 50)
        self.assertEqual(total_correct, 33)
        self.assertEqual(recent_choices, 40)
        self.assertEqual(recent_correct, 27)

    def test_legacy_stage_and_opacity_are_migrated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            param_file = os.path.join(temp_dir, "params.json")
            with open(param_file, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "parameters": {
                            "Training Stage": (
                                "Stage 3 - dot pair plus two targets"
                            ),
                            "Wrong Target Opacity Start (0-1)": 0.65,
                        }
                    },
                    stream,
                )
            manager = SimpleNamespace(
                param_file=param_file,
                exp_params={
                    "Training Stage": DEFAULT_PARAMS[
                        "Training Stage"
                    ].copy(),
                    "Wrong Target Opacity (0-1)": 0.0,
                },
            )

            _migrate_legacy_saved_params(manager)

        self.assertEqual(
            manager.exp_params["Training Stage"][0],
            "Stage 3 - dot pair plus two paired-dot targets",
        )
        self.assertEqual(
            manager.exp_params["Wrong Target Opacity (0-1)"],
            0.65,
        )


if __name__ == "__main__":
    unittest.main()
