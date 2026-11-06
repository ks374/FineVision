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
from SaccadeTask import MONITOR_ID_SUBJECT


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

    def test_failed_trial_repeat_precedes_manual_and_random_orientation(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._repeat_orientation = "Horizontal"
        task._next_orientation_override = "Vertical"
        task._orientation_bag = ["Horizontal"]

        self.assertEqual(task._next_orientation(), "Horizontal")
        self.assertEqual(task._last_orientation_source, "Repeat_After_Failure")
        self.assertEqual(task._next_orientation_override, "Vertical")

        self.assertEqual(task._next_orientation(), "Vertical")
        self.assertEqual(task._last_orientation_source, "Manual_H_or_V")

    def test_any_non_success_outcome_schedules_same_orientation(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        tracker_events = []
        task._send_tracker_event = tracker_events.append

        task._schedule_repeat_after_failure("NoFix", "Vertical", 12)

        self.assertEqual(task._repeat_orientation, "Vertical")
        self.assertIn("STATUS NoFix", tracker_events[0])

        task._repeat_orientation = None
        task._schedule_repeat_after_failure("Success", "Horizontal", 13)
        self.assertIsNone(task._repeat_orientation)

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

    def test_gaze_contingent_stimulus_position_defaults_off(self):
        self.assertFalse(DEFAULT_PARAMS["Gaze-Contingent Stimulus Position"])

    def test_gaze_contingent_cue_moves_in_the_same_direction_as_gaze(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.gaze_contingent_stimulus_position = True
        task.use_visual_cue_as_fixation = False
        task.cue_center_x_px = 10.0
        task.cue_center_y_px = 20.0
        task.fix_x_px = 100.0
        task.fix_y_px = 200.0

        self.assertEqual(
            task._cue_center_for_gaze(
                {"x": 103.0, "y": 196.0, "valid": True}
            ),
            (13.0, 16.0),
        )

    def test_gaze_contingent_cue_position_is_not_clamped_to_screen(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.gaze_contingent_stimulus_position = True
        task.use_visual_cue_as_fixation = False
        task.cue_center_x_px = 10.0
        task.cue_center_y_px = 20.0
        task.fix_x_px = 100.0
        task.fix_y_px = 200.0

        self.assertEqual(
            task._cue_center_for_gaze(
                {"x": 5000.0, "y": -4000.0, "valid": True}
            ),
            (4910.0, -4180.0),
        )

    def test_fixed_cue_position_is_preserved_when_option_is_off_or_gaze_invalid(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.use_visual_cue_as_fixation = False
        task.cue_center_x_px = 10.0
        task.cue_center_y_px = 20.0
        task.fix_x_px = 100.0
        task.fix_y_px = 200.0
        gaze = {"x": 103.0, "y": 196.0, "valid": True}

        task.gaze_contingent_stimulus_position = False
        self.assertEqual(task._cue_center_for_gaze(gaze), (10.0, 20.0))

        task.gaze_contingent_stimulus_position = True
        self.assertEqual(
            task._cue_center_for_gaze(
                {"x": 0.0, "y": 0.0, "valid": False}
            ),
            (10.0, 20.0),
        )

        task.use_visual_cue_as_fixation = True
        self.assertEqual(task._cue_center_for_gaze(gaze), (10.0, 20.0))

    def test_training_frame_reads_gaze_before_drawing_stimulus(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        events = []
        gaze = {"x": 3.0, "y": 4.0, "valid": True}
        task.gaze_renderer = SimpleNamespace(
            update=lambda: events.append("gaze") or gaze,
            draw=lambda: events.append("gaze_draw"),
        )
        task.use_visual_cue_as_fixation = False
        task._draw_cue = (
            lambda orientation, frame_gaze: events.append(
                ("cue", orientation, frame_gaze)
            )
        )
        task.win_sub = SimpleNamespace(flip=lambda: events.append("subject_flip"))
        task.win_ctl = SimpleNamespace(flip=lambda: events.append("control_flip"))
        task._poll_training_commands = lambda **kwargs: False

        returned_gaze, _ = task._present_training_frame(
            cue_visible=True,
            orientation="Horizontal",
        )

        self.assertIs(returned_gaze, gaze)
        self.assertEqual(events[0], "gaze")
        self.assertEqual(events[1], ("cue", "Horizontal", gaze))
        self.assertEqual(events[2], "gaze_draw")

    def test_separate_stimulus_starts_when_fixation_turns_off(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        clock = [1.0]
        task.stim_duration_s = 0.1
        task.now = lambda: clock[0]
        frames = []

        def schedule(trial_data, field):
            if trial_data[field] is None:
                trial_data[field] = clock[0]

        def present(**kwargs):
            frames.append(kwargs)
            clock[0] += 0.05
            return {"x": 999.0, "y": 999.0, "valid": True}, False

        task._schedule_flip_time = schedule
        task._present_training_frame = present
        trial_data = {
            "Time_FixationPointOff": None,
            "Time_StimOn": None,
            "Orientation": "Vertical",
            "Correct_Target": "Up",
        }

        held, pause_requested = task._run_stimulus(trial_data)

        self.assertTrue(held)
        self.assertFalse(pause_requested)
        self.assertEqual(
            trial_data["Time_FixationPointOff"],
            trial_data["Time_StimOn"],
        )
        self.assertTrue(frames[0]["cue_visible"])
        self.assertNotIn("fix_visible", frames[0])
        self.assertNotIn("fix_window_active", frames[0])

    def test_give_feedback_first_defaults_off_with_full_opacity(self):
        self.assertFalse(DEFAULT_PARAMS["Give Feedback First"])
        self.assertEqual(DEFAULT_PARAMS["First Feedback Opacity (0-1)"], 1.0)

    def test_reminder_counters_default_to_disabled(self):
        self.assertEqual(
            DEFAULT_PARAMS["Reminder After Consecutive Errors (X)"],
            0,
        )
        self.assertEqual(DEFAULT_PARAMS["Reminder After Trials (Y)"], 0)
        self.assertEqual(DEFAULT_PARAMS["Reminder Trials (Z)"], 0)

    def test_block_defaults_and_parameter_validation(self):
        self.assertEqual(DEFAULT_PARAMS["Trials per Block (N)"], 40)
        self.assertEqual(DEFAULT_PARAMS["Block Reward Length (s)"], 1.5)

        for invalid_value in (0, -1, 1.5):
            params = DEFAULT_PARAMS.copy()
            params["Training Stage"] = params["Training Stage"][0]
            params["Trials per Block (N)"] = invalid_value
            with self.assertRaisesRegex(ValueError, "positive integer"):
                _validate_params(params)

        params = DEFAULT_PARAMS.copy()
        params["Training Stage"] = params["Training Stage"][0]
        params["Block Reward Length (s)"] = 0
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            _validate_params(params)

    def test_reminder_counters_require_non_negative_integers(self):
        for field, value in (
            ("Reminder After Consecutive Errors (X)", -1),
            ("Reminder After Trials (Y)", 1.5),
            ("Reminder Trials (Z)", -2),
        ):
            params = DEFAULT_PARAMS.copy()
            params["Training Stage"] = params["Training Stage"][0]
            params[field] = value
            with self.assertRaisesRegex(ValueError, "non-negative integer"):
                _validate_params(params)

    @staticmethod
    def _finish_reminder_trial(task, choice_correct):
        task._record_trial_for_reminders(
            {
                "Choice_Correct": choice_correct,
                "Reminder_Feedback_Shown": task._reminder_feedback_active,
                "Reminder_Triggered_By_Errors": (
                    task._reminder_triggered_by_errors
                ),
                "Reminder_Triggered_By_Interval": (
                    task._reminder_triggered_by_interval
                ),
            }
        )

    def test_consecutive_errors_trigger_the_next_trial_reminder(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._configure_reminder_schedule(2, 0, 0)

        task._begin_trial_reminder()
        self.assertFalse(task._reminder_feedback_active)
        self._finish_reminder_trial(task, False)
        task._begin_trial_reminder()
        self.assertFalse(task._reminder_feedback_active)
        self._finish_reminder_trial(task, False)

        task._begin_trial_reminder()
        self.assertTrue(task._reminder_triggered_by_errors)
        self.assertTrue(task._reminder_feedback_active)
        self._finish_reminder_trial(task, True)
        task._begin_trial_reminder()
        self.assertFalse(task._reminder_feedback_active)

    def test_y_trials_are_followed_by_z_periodic_reminder_trials(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._configure_reminder_schedule(0, 3, 2)

        for _ in range(3):
            task._begin_trial_reminder()
            self.assertFalse(task._reminder_triggered_by_interval)
            self._finish_reminder_trial(task, True)

        for _ in range(2):
            task._begin_trial_reminder()
            self.assertTrue(task._reminder_triggered_by_interval)
            self._finish_reminder_trial(task, True)

        task._begin_trial_reminder()
        self.assertFalse(task._reminder_triggered_by_interval)

    def test_error_and_interval_reminders_operate_independently(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._configure_reminder_schedule(2, 2, 1)

        for _ in range(2):
            task._begin_trial_reminder()
            self._finish_reminder_trial(task, False)

        task._begin_trial_reminder()
        self.assertTrue(task._reminder_triggered_by_errors)
        self.assertTrue(task._reminder_triggered_by_interval)
        self.assertTrue(task._reminder_feedback_active)

    def test_pre_choice_abort_does_not_consume_a_due_reminder(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._configure_reminder_schedule(1, 1, 1)

        task._begin_trial_reminder()
        self._finish_reminder_trial(task, False)
        task._begin_trial_reminder()
        self.assertTrue(task._reminder_triggered_by_errors)
        self.assertTrue(task._reminder_triggered_by_interval)
        task._record_trial_for_reminders(
            {
                "Choice_Correct": "",
                "Reminder_Feedback_Shown": False,
                "Reminder_Triggered_By_Errors": True,
                "Reminder_Triggered_By_Interval": True,
            }
        )

        task._begin_trial_reminder()
        self.assertTrue(task._reminder_triggered_by_errors)
        self.assertTrue(task._reminder_triggered_by_interval)

    def test_zero_disables_each_reminder_mechanism(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task._configure_reminder_schedule(0, 0, 3)

        for _ in range(5):
            task._begin_trial_reminder()
            self.assertFalse(task._reminder_feedback_active)
            self._finish_reminder_trial(task, False)

    def test_scheduled_reminder_uses_the_existing_pre_choice_mapping(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.use_visual_cue_as_fixation = True
        task.give_feedback_first = False
        task._reminder_feedback_active = True

        self.assertTrue(task._first_feedback_during_choice())

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
        task._send_tracker_event = lambda message: None
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
        task._send_tracker_event = lambda message: None
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
        self.assertEqual(kwargs["subject_screen_index"], MONITOR_ID_SUBJECT)
        self.assertEqual(
            kwargs["background_color"],
            task.background_psychopy_color,
        )

    def test_runtime_menu_disables_trials_per_block(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        captured = {}

        def prompt_for_runtime_parameters(**kwargs):
            captured.update(kwargs)
            return "confirm"

        task.task_manager = SimpleNamespace(
            exp_params={
                "Training Stage": DEFAULT_PARAMS["Training Stage"][0],
            },
            prompt_for_runtime_parameters=prompt_for_runtime_parameters,
        )
        task.tracker_backend = SimpleNamespace(supports_recalibration=False)

        self.assertEqual(task._prompt_for_runtime_parameters(), "confirm")
        self.assertEqual(
            captured["disabled_parameters"],
            {"Trials per Block (N)"},
        )

    def test_cancel_runtime_menu_resumes_with_standard_reward(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        events = []
        rewards = []
        task._present_training_frame = lambda: events.append("blank")
        task._prompt_for_runtime_parameters = lambda: "cancel"
        task._send_tracker_event = events.append
        task.update_params = lambda: self.fail(
            "Cancel must not apply parameter edits."
        )
        task.reward_len_s = 0.5
        task.arduino = SimpleNamespace(reward=rewards.append)

        with patch("Orientation2AFCTrainingTask.event.clearEvents"):
            action = task._resume_from_runtime_pause()

        self.assertEqual(action, "cancel")
        self.assertEqual(rewards, [500])
        self.assertIn(
            "FINEVISION_PAUSE_ACTION CANCEL_EDITS_CONTINUE",
            events,
        )
        self.assertTrue(
            any(str(item).startswith("TASK_RESUME_REWARD") for item in events)
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

    def test_post_cue_first_frame_is_presented_before_follow_up_action(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.stage = 3
        task.show_teaching_feedback = True
        clock = [0.0]
        events = []
        task.now = lambda: clock[0]

        def schedule(trial_data, field):
            if trial_data[field] is None:
                trial_data[field] = clock[0]

        def present(**kwargs):
            if kwargs.get("teaching_feedback"):
                events.append("post_cue_flip")
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

        task._run_teaching_feedback(
            trial_data,
            after_first_flip=lambda: events.append("reward"),
        )

        self.assertEqual(events[:2], ["post_cue_flip", "reward"])
        self.assertEqual(events.count("reward"), 1)

    def test_success_schedules_reward_through_post_cue_callback(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        events = []
        clock = [0.0]
        task._begin_trial_reminder = lambda: None
        task._next_orientation = lambda: "Horizontal"
        task.rng = SimpleNamespace(uniform=lambda _low, _high: 0.0)
        task.stim_delay_min_s = 0.0
        task.stim_delay_max_s = 0.0
        task._new_trial_data = lambda trial, orientation, delay: {
            "Trial": trial,
            "Correct_Target": "Right",
            "Choice": "",
            "Choice_Correct": "",
            "Time_FixOn": None,
            "Time_StimOn": None,
            "Time_Reward": None,
        }
        task.gaze_renderer = SimpleNamespace(reset_trail=lambda: None)
        task._send_tracker_event = lambda message: events.append(message)
        task._tracker_trial_variable_fields = lambda: ()
        task.now = lambda: clock[0]
        task._schedule_flip_time = lambda trial_data, field: None
        task.use_visual_cue_as_fixation = False
        task._present_training_frame = lambda **kwargs: ({}, False)
        task._wait_for_fixation = lambda trial_data: (0.0, False)
        task._hold_before_stim = (
            lambda trial_data, fixation_start, delay: (True, False)
        )
        task._uses_separate_cue_phase = lambda: False
        task._show_choice_onset = lambda trial_data: ({}, False)

        def run_choice(trial_data, gaze, pause_requested):
            trial_data["Choice"] = "Right"
            trial_data["Choice_Correct"] = True
            return "Success", False

        task._run_choice = run_choice

        def run_feedback(trial_data, after_first_flip=None):
            events.append("post_cue_flip")
            clock[0] = 1.0
            after_first_flip()
            return False

        task._run_teaching_feedback = run_feedback
        task.reward_len_s = 0.5
        task._record_trial_for_reminders = lambda trial_data: None
        task.arduino = SimpleNamespace(
            trial_start=lambda: events.append("trial_start"),
            trial_success=lambda: events.append("trial_success"),
            reward=lambda duration_ms: events.append(("reward", duration_ms)),
            trial_end=lambda: events.append("trial_end"),
        )

        with patch("Orientation2AFCTrainingTask.event.clearEvents"):
            trial_data, _ = task._run_one_trial(7)

        visual_and_reward_events = [
            item
            for item in events
            if item in ("post_cue_flip", "trial_success")
            or isinstance(item, tuple)
        ]
        self.assertEqual(
            visual_and_reward_events,
            ["post_cue_flip", "trial_success", ("reward", 500)],
        )
        self.assertEqual(trial_data["Time_Reward"], 1.0)

    def test_block_end_delivers_independent_extra_reward(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        rewards = []
        tracker_events = []
        task.block_reward_len_s = 1.5
        task.trials_per_block = 20
        task.now = lambda: 12.25
        task.arduino = SimpleNamespace(reward=rewards.append)
        task._send_tracker_event = tracker_events.append
        trial_data = {
            "Trial": 40,
            "Block": 2,
            "Block_End": True,
            "Time_BlockReward": None,
            "Block_Reward_Delivered": False,
        }

        delivered = task._deliver_block_reward_if_due(trial_data)

        self.assertTrue(delivered)
        self.assertEqual(rewards, [1500])
        self.assertEqual(trial_data["Time_BlockReward"], 12.25)
        self.assertTrue(trial_data["Block_Reward_Delivered"])
        self.assertIn("BLOCK_REWARD BLOCK 2", tracker_events[0])

        rewards.clear()
        self.assertFalse(
            task._deliver_block_reward_if_due({"Block_End": False})
        )
        self.assertEqual(rewards, [])

    def test_failed_attempt_does_not_advance_or_finish_block(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.trials_per_block = 4
        failed = {"Block": 1, "Trial_In_Block": 4}
        task._apply_trial_outcome_to_block(failed, "Incorrect")

        self.assertFalse(failed["Counts_Toward_Block"])
        self.assertFalse(failed["Block_End"])
        self.assertEqual(task._block_position(3), (1, 4))
        self.assertEqual(task._block_position(4), (2, 1))

    def test_only_successful_fourth_trial_finishes_block(self):
        task = Orientation2AFCTrainingTask.__new__(
            Orientation2AFCTrainingTask
        )
        task.trials_per_block = 4
        trial_data = {"Trial_In_Block": 4}

        counted = task._apply_trial_outcome_to_block(trial_data, "Success")

        self.assertTrue(counted)
        self.assertTrue(trial_data["Counts_Toward_Block"])
        self.assertTrue(trial_data["Block_End"])

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
