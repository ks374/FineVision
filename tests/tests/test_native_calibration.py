import types
import unittest
from datetime import datetime

from EyeLink_Native_Calibration import (
    _calibration_area,
    _build_rewarding_graphics,
    _config_from_args,
    _load_task_display_profile,
    _native_edf_paths,
    _parse_args,
)


class FakeArduino:
    def __init__(self):
        self.rewards = []

    def reward(self, duration_ms):
        self.rewards.append(duration_ms)


class FakeMessageTracker:
    def __init__(self):
        self.messages = []

    def sendMessage(self, message):
        self.messages.append(message)


class FakeBaseGraphics:
    def __init__(self, tracker, win, disable_audio):
        self.base_calls = []

    def draw_cal_target(self, x, y):
        self.base_calls.append(("draw", x, y))

    def erase_cal_target(self):
        self.base_calls.append(("erase",))

    def get_input_key(self):
        return getattr(self, "next_keys", [])

    def play_beep(self, beepid):
        self.base_calls.append(("beep", beepid))


class NativeCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.pylink = types.SimpleNamespace(
            CAL_GOOD_BEEP=0,
            CAL_ERR_BEEP=-1,
            CAL_TARG_BEEP=1,
            KeyInput=lambda key, modifiers: types.SimpleNamespace(
                __key__=key,
                modifiers=modifiers,
            ),
        )
        self.graphics_class = _build_rewarding_graphics(
            FakeBaseGraphics, self.pylink
        )

    def test_command_line_defaults_to_subject_screen_one(self):
        args = _parse_args(["--no-dialog"])
        config = _config_from_args(args)
        self.assertEqual(config.screen, 1)
        self.assertEqual(config.calibration_type, "HV5")
        self.assertEqual(config.background_gray_level, 5)
        self.assertEqual(config.background_rgb_255, (40, 40, 40))
        self.assertEqual(config.reward_mode, "advance")

    def test_background_matches_calibrated_gray_level_five(self):
        profile = _load_task_display_profile()
        self.assertEqual(profile["background_rgb_255"], (40, 40, 40))
        self.assertAlmostEqual(
            profile["background_luminance_cd_m2"], 5.875
        )
        self.assertAlmostEqual(profile["viewing_distance_cm"], 58.0)
        self.assertAlmostEqual(profile["monitor_width_cm"], 54.0)
        self.assertAlmostEqual(profile["monitor_height_cm"], 30.0)

    def test_five_point_extent_does_not_exceed_twelve_degrees(self):
        config = _config_from_args(_parse_args(["--no-dialog"]))
        area = _calibration_area(config, 1920, 1080)
        self.assertLessEqual(area["x"]["eccentricity_deg"], 12.0)
        self.assertLessEqual(area["y"]["eccentricity_deg"], 12.0)
        self.assertGreater(area["x"]["eccentricity_deg"], 11.9)
        self.assertGreater(area["y"]["eccentricity_deg"], 11.9)
        self.assertEqual(area["x"]["offset_px"], 438)
        self.assertEqual(area["y"]["offset_px"], 443)

    def test_command_line_rejects_more_than_twelve_degrees(self):
        args = _parse_args(
            ["--no-dialog", "--max-eccentricity-deg", "12.1"]
        )
        with self.assertRaises(ValueError):
            _config_from_args(args)

    def test_command_line_supports_hv9_and_adjustable_display(self):
        args = _parse_args([
            "--no-dialog",
            "--calibration", "HV9",
            "--background-gray-level", "30",
            "--viewing-distance-cm", "60",
            "--monitor-width-cm", "55",
            "--monitor-height-cm", "31",
            "--fixation-point-radius-deg", "0.3",
        ])
        config = _config_from_args(args)
        self.assertEqual(config.calibration_type, "HV9")
        self.assertEqual(config.background_gray_level, 30)
        self.assertNotEqual(config.background_rgb_255, (40, 40, 40))
        self.assertAlmostEqual(config.viewing_distance_cm, 60.0)
        self.assertAlmostEqual(config.monitor_width_cm, 55.0)
        self.assertAlmostEqual(config.monitor_height_cm, 31.0)
        self.assertAlmostEqual(config.fixation_point_radius_deg, 0.3)

    def test_native_edf_host_name_obeys_eight_character_limit(self):
        session_id, host_name, local_path = _native_edf_paths(
            datetime(2026, 8, 7, 9, 30, 15, 123456)
        )
        self.assertEqual(session_id, "20260807_093015_123456")
        self.assertEqual(len(host_name.split(".")[0]), 8)
        self.assertTrue(host_name.endswith(".EDF"))
        self.assertTrue(str(local_path).endswith(".edf"))

    def test_target_and_result_events_are_sent_to_edf(self):
        tracker = FakeMessageTracker()
        graphics = self.graphics_class(tracker, None, None, "off", 0)
        graphics.draw_cal_target(960, 540)
        graphics.erase_cal_target()
        graphics.play_beep(self.pylink.CAL_GOOD_BEEP)
        self.assertIn(
            "NATIVE_CAL_TARGET_ON PHASE SETUP INDEX 1 X 960 Y 540",
            tracker.messages,
        )
        self.assertIn(
            "NATIVE_CAL_TARGET_OFF PHASE SETUP INDEX 1 X 960 Y 540",
            tracker.messages,
        )
        self.assertIn(
            "NATIVE_CAL_RESULT PHASE SETUP RESULT GOOD",
            tracker.messages,
        )

    def test_automatic_reward_on_transition_and_final_good_beep(self):
        arduino = FakeArduino()
        graphics = self.graphics_class(None, None, arduino, "advance", 300)
        graphics.draw_cal_target(100, 100)
        self.assertEqual(arduino.rewards, [])
        graphics.draw_cal_target(200, 100)
        self.assertEqual(arduino.rewards, [300])
        graphics.play_beep(self.pylink.CAL_GOOD_BEEP)
        self.assertEqual(arduino.rewards, [300, 300])

    def test_redrawing_same_target_does_not_reward(self):
        arduino = FakeArduino()
        graphics = self.graphics_class(None, None, arduino, "advance", 200)
        graphics.draw_cal_target(100, 100)
        graphics.draw_cal_target(100, 100)
        self.assertEqual(arduino.rewards, [])

    def test_manual_space_rewards_only_while_target_visible(self):
        arduino = FakeArduino()
        graphics = self.graphics_class(None, None, arduino, "manual", 250)
        graphics.next_keys = [types.SimpleNamespace(__key__=ord(" "))]
        graphics.get_input_key()
        self.assertEqual(arduino.rewards, [])
        graphics.draw_cal_target(100, 100)
        graphics.get_input_key()
        self.assertEqual(arduino.rewards, [250])
        graphics.erase_cal_target()
        graphics.get_input_key()
        self.assertEqual(arduino.rewards, [250])

    def test_in_session_graphics_returns_after_successful_calibration(self):
        tracker = FakeMessageTracker()
        graphics_class = _build_rewarding_graphics(
            FakeBaseGraphics,
            self.pylink,
            auto_exit_after_success=True,
        )
        graphics = graphics_class(tracker, None, None, "off", 0)

        graphics.play_beep(self.pylink.CAL_GOOD_BEEP)
        keys = graphics.get_input_key()

        self.assertEqual([key.__key__ for key in keys], [27])
        self.assertIn("NATIVE_CAL_RETURN_TO_TASK", tracker.messages)

    def test_in_session_graphics_starts_calibration_from_display_pc(self):
        tracker = FakeMessageTracker()
        graphics_class = _build_rewarding_graphics(
            FakeBaseGraphics,
            self.pylink,
            auto_start_calibration=True,
        )
        graphics = graphics_class(tracker, None, None, "off", 0)

        first_keys = graphics.get_input_key()
        second_keys = graphics.get_input_key()

        self.assertEqual([key.__key__ for key in first_keys], [ord("c")])
        self.assertEqual(second_keys, [])
        self.assertIn("NATIVE_CAL_AUTO_START_REQUESTED", tracker.messages)
        self.assertIn(
            "NATIVE_CAL_PHASE_START PHASE CALIBRATION",
            tracker.messages,
        )


if __name__ == "__main__":
    unittest.main()
