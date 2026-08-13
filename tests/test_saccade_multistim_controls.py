import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from SaccadeMultiStimTask import (
    DEFAULT_PARAMS,
    SaccadeMultiStimTask,
    _build_condition_plan,
    _load_calibration,
)
from SaccadeTask import SaccadeTask, TaskAbort


def control_test_params(**updates):
    params = copy.deepcopy(DEFAULT_PARAMS)
    params.update(
        {
            "Stim Position X Min (deg)": 2.0,
            "Stim Position X Max (deg)": 4.0,
            "Stim Position X Step (deg)": 2.0,
            "Stim Position Y Min (deg)": -4.0,
            "Stim Position Y Max (deg)": -4.0,
            "Stim Position Y Step (deg)": 1.0,
            "Stim Colors (comma-separated)": "Gray",
            "Stim Intensity Level Min": 1,
            "Stim Intensity Level Max": 1,
            "Stim Intensity Level Step": 1,
            "Repeats Per Condition": 1,
            "Condition Order": "Sequential",
            "Control Groups": 1,
        }
    )
    params.update(updates)
    return params


class PositionControlPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = _load_calibration()

    def test_each_group_contains_center_and_every_stimulus_position(self):
        params = control_test_params(**{"Control Groups": 2})
        plan = _build_condition_plan(params, self.calibration)
        controls = [condition for condition in plan if condition["Is_Control"]]

        self.assertEqual(len(controls), 12)
        expected_positions = {(0.0, 0.0), (2.0, -4.0), (4.0, -4.0)}
        for group_index in (1, 2):
            group_positions = {
                (condition["Stim_Pos_X_deg"], condition["Stim_Pos_Y_deg"])
                for condition in controls
                if condition["Control_Group_Index"] == group_index
            }
            self.assertEqual(group_positions, expected_positions)
            for position in expected_positions:
                position_controls = [
                    condition
                    for condition in controls
                    if condition["Control_Group_Index"] == group_index
                    and (
                        condition["Stim_Pos_X_deg"],
                        condition["Stim_Pos_Y_deg"],
                    ) == position
                ]
                self.assertEqual(len(position_controls), 2)
                self.assertEqual(
                    [
                        condition["Control_Pair_Member"]
                        for condition in position_controls
                    ],
                    [1, 2],
                )

    def test_center_is_not_duplicated_when_it_is_a_stimulus_position(self):
        params = control_test_params(
            **{
                "Stim Position X Min (deg)": 0.0,
                "Stim Position X Max (deg)": 2.0,
                "Stim Position X Step (deg)": 2.0,
                "Stim Position Y Min (deg)": 0.0,
                "Stim Position Y Max (deg)": 0.0,
            }
        )
        plan = _build_condition_plan(params, self.calibration)
        controls = [condition for condition in plan if condition["Is_Control"]]

        self.assertEqual(len(controls), 4)
        self.assertEqual(
            {
                (condition["Stim_Pos_X_deg"], condition["Stim_Pos_Y_deg"])
                for condition in controls
            },
            {(0.0, 0.0), (2.0, 0.0)},
        )

    def test_zero_groups_disables_controls(self):
        params = control_test_params(**{"Control Groups": 0})
        counts = _build_condition_plan(
            params,
            self.calibration,
            counts_only=True,
        )

        self.assertEqual(counts["control_count"], 0)
        self.assertEqual(counts["planned_count"], counts["experimental_count"])

    def test_control_pair_members_stay_adjacent_in_both_orders(self):
        for order in ("Sequential", "Randomized"):
            params = control_test_params(**{"Condition Order": order})
            plan = _build_condition_plan(params, self.calibration)
            pair_indices = {}
            for index, condition in enumerate(plan):
                if condition["Is_Control"]:
                    pair_indices.setdefault(
                        condition["Control_Pair_ID"], []
                    ).append(index)
            for indices in pair_indices.values():
                self.assertEqual(len(indices), 2)
                self.assertEqual(indices[1], indices[0] + 1)
                self.assertEqual(
                    [
                        plan[index]["Control_Pair_Member"]
                        for index in indices
                    ],
                    [1, 2],
                )


class PositionControlBehaviorTests(unittest.TestCase):
    def test_control_uses_its_position_as_the_fixation_position(self):
        task = SaccadeMultiStimTask.__new__(SaccadeMultiStimTask)
        task.task_fix_x_deg = 0.0
        task.task_fix_y_deg = 0.0
        task._to_x_pixels = lambda value: value * 10.0
        task._to_y_pixels = lambda value: value * 20.0
        task._build_visuals = lambda: None
        condition = {
            "Stim_Pos_X_deg": 6.0,
            "Stim_Pos_Y_deg": -4.0,
            "Stim_Major_Axis_deg": 0.3,
            "Stim_Minor_Axis_deg": 0.3,
            "Stim_Orientation_deg": 0.0,
            "Stim_Color_R": 0,
            "Stim_Color_G": 0,
            "Stim_Color_B": 0,
            "Is_Control": True,
        }

        task._apply_condition(condition)

        self.assertEqual((task.fix_x_deg, task.fix_y_deg), (6.0, -4.0))
        self.assertEqual((task.fix_x_px, task.fix_y_px), (60.0, -80.0))

        condition["Is_Control"] = False
        task._apply_condition(condition)

        self.assertEqual((task.fix_x_deg, task.fix_y_deg), (0.0, 0.0))
        self.assertEqual((task.fix_x_px, task.fix_y_px), (0.0, 0.0))

    def test_control_only_rewards_success_and_labels_outcomes(self):
        task = SaccadeMultiStimTask.__new__(SaccadeMultiStimTask)
        task.current_condition = {"Is_Control": True}

        self.assertTrue(task._trial_should_reward("Success", {}))
        self.assertFalse(task._trial_should_reward("Break_1", {}))
        self.assertEqual(
            task._trial_status_for_log("Success", {}),
            "Control_Success",
        )
        self.assertEqual(
            task._trial_status_for_log("Break_1", {}),
            "Control_Break_1",
        )

    def test_two_exceeded_pair_members_trigger_calibration_alert(self):
        task = SaccadeMultiStimTask.__new__(SaccadeMultiStimTask)
        task.control_error_threshold_deg = 1.5
        task._pending_control_pair = None
        task._drift_alert_pending = None
        task._send_tracker_event = lambda message: None
        task._control_gaze_center_deg = lambda: (2.0, 0.0, 6)

        first = {
            "Trial": 10,
            "Status": "Control_Success",
            "Fixation_Pos_X_deg": 0.0,
            "Fixation_Pos_Y_deg": 0.0,
            "Control_Pair_ID": "G001P0001",
            "Control_Pair_Member": 1,
        }
        second = dict(first, Trial=11, Control_Pair_Member=2)

        self.assertFalse(task._evaluate_control_gaze(first))
        self.assertTrue(task._evaluate_control_gaze(second))
        self.assertTrue(second["Control_Consecutive_Exceeded"])
        self.assertTrue(second["Control_Calibration_Alert"])
        self.assertEqual(task._drift_alert_pending["pair_id"], "G001P0001")

    def test_one_accurate_pair_member_prevents_alert(self):
        task = SaccadeMultiStimTask.__new__(SaccadeMultiStimTask)
        task.control_error_threshold_deg = 1.5
        task._pending_control_pair = None
        task._drift_alert_pending = None
        task._send_tracker_event = lambda message: None
        centers = iter(((2.0, 0.0, 6), (0.5, 0.0, 6)))
        task._control_gaze_center_deg = lambda: next(centers)
        base = {
            "Status": "Control_Success",
            "Fixation_Pos_X_deg": 0.0,
            "Fixation_Pos_Y_deg": 0.0,
            "Control_Pair_ID": "G001P0001",
        }

        task._evaluate_control_gaze(
            dict(base, Trial=10, Control_Pair_Member=1)
        )
        second = dict(base, Trial=11, Control_Pair_Member=2)
        self.assertFalse(task._evaluate_control_gaze(second))
        self.assertFalse(second["Control_Calibration_Alert"])

    def test_recalibration_uses_a_dedicated_subject_screen_window(self):
        class FakeHandle:
            def __init__(self):
                self.visibility = []

            def set_visible(self, visible):
                self.visibility.append(bool(visible))

            def activate(self):
                pass

        class FakeCalibrationWindow:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.winHandle = FakeHandle()
                self.closed = False

            def flip(self):
                pass

            def close(self):
                self.closed = True

        class FakeBackend:
            supports_recalibration = True

            def __init__(self):
                self.window = None

            def recalibrate(self, window, **kwargs):
                self.window = window

        task = SaccadeMultiStimTask.__new__(SaccadeMultiStimTask)
        task.tracker_backend = FakeBackend()
        task.win_sub = SimpleNamespace(
            size=(1920, 1080),
            color=None,
            winHandle=FakeHandle(),
        )
        task.win_ctl = SimpleNamespace(color=None)
        task.background_psychopy_color = (-0.5, -0.5, -0.5)
        task.viewing_distance_cm = 60.0
        task.monitor_width_cm = 54.0
        task.monitor_height_cm = 30.0
        task.fix_point_radius_deg = 0.2
        task.arduino = object()
        task._pending_control_pair = {"pair_id": "test"}
        task._drift_alert_pending = {"pair_id": "test"}
        task._control_gaze_samples = [object()]
        task.gaze_renderer = SimpleNamespace(reset_trail=lambda: None)
        presented_frames = []
        task._present_frame = lambda *args, **kwargs: (
            presented_frames.append((args, kwargs)) or (None, False)
        )
        task._send_tracker_event = lambda message: None
        calibration_options = {
            "Calibration Type": "HV5",
            "Maximum Calibration Eccentricity (deg)": 12.0,
            "Reward Mode": "advance",
            "Reward Duration (ms)": 300,
            "Automatic Pacing (ms)": 1200,
        }
        calibration_window = FakeCalibrationWindow()

        with patch(
            "EyeLinkInSessionCalibration.visual.Window",
            return_value=calibration_window,
        ) as window_factory, patch(
            "EyeLinkInSessionCalibration.load_recalibration_options",
            return_value=calibration_options,
        ), patch(
            "EyeLinkInSessionCalibration.event.clearEvents"
        ), patch(
            "SaccadeMultiStimTask.event.clearEvents"
        ):
            task._recalibrate_eyelink()

        self.assertIs(task.tracker_backend.window, calibration_window)
        self.assertTrue(calibration_window.closed)
        self.assertEqual(
            task.win_sub.winHandle.visibility,
            [False, True],
        )
        self.assertEqual(window_factory.call_args.kwargs["screen"], 1)
        self.assertTrue(window_factory.call_args.kwargs["fullscr"])
        self.assertEqual(len(presented_frames), 1)

    def test_calibration_escape_is_ignored_once_then_works_normally(self):
        task = SaccadeTask.__new__(SaccadeTask)
        with patch(
            "SaccadeTask.time.perf_counter",
            side_effect=[10.0, 10.1, 11.1],
        ), patch(
            "SaccadeTask.event.clearEvents"
        ), patch(
            "SaccadeTask.event.getKeys",
            side_effect=[["escape"], ["escape"]],
        ):
            task._suppress_calibration_escape()
            self.assertFalse(task._poll_commands())
            with self.assertRaises(TaskAbort):
                task._poll_commands()


if __name__ == "__main__":
    unittest.main()
