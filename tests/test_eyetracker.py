import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from CalibrationManager import (
    CALIBRATION_TAIL_SAMPLE_DURATION_S,
    CalibrationManager,
)
from Shared_Memory_Util import SharedGazeData, normalize_calibration
from eyetracker.eyelink_backend import EyeLinkBackend
from eyetracker.runtime import _host_edf_name, _load_eyelink_settings


class FakeEye:
    def __init__(self, href, gaze=(960.0, 540.0)):
        self.href = href
        self.gaze = gaze

    def getHREF(self):
        return self.href

    def getGaze(self):
        return self.gaze


class FakeSample:
    def __init__(self, left, right, timestamp_ms=1234):
        self.left = left
        self.right = right
        self.timestamp_ms = timestamp_ms

    def getTime(self):
        return self.timestamp_ms

    def isBinocular(self):
        return self.left is not None and self.right is not None

    def isLeftSample(self):
        return self.left is not None and self.right is None

    def isRightSample(self):
        return self.right is not None and self.left is None

    def getLeftEye(self):
        return self.left

    def getRightEye(self):
        return self.right


class FakeTracker:
    def __init__(self, sample):
        self.sample = sample
        self.commands = []
        self.messages = []
        self.received = None
        self.closed = False
        self.recording_starts = 0
        self.recording_stops = 0
        self.setup_count = 0

    def isConnected(self):
        return True

    def setOfflineMode(self):
        pass

    def openDataFile(self, name):
        self.opened = name

    def sendCommand(self, command):
        self.commands.append(command)

    def sendMessage(self, message):
        self.messages.append(message)

    def startRecording(self, *args):
        self.recording_starts += 1
        return 0

    def stopRecording(self):
        self.recording_stops += 1

    def doTrackerSetup(self):
        self.setup_count += 1

    def getCalibrationMessage(self):
        return "VALIDATION GOOD"

    def getNewestSample(self):
        return self.sample

    def closeDataFile(self):
        pass

    def receiveDataFile(self, source, destination):
        self.received = (source, destination)

    def close(self):
        self.closed = True


def fake_pylink_module(tracker):
    return types.SimpleNamespace(
        EyeLink=lambda host: tracker,
        MISSING_DATA=32768.0,
        pumpDelay=lambda milliseconds: None,
        msecDelay=lambda milliseconds: None,
        openGraphicsEx=lambda graphics: None,
        closeGraphics=lambda: None,
    )


class SharedGazeDataTests(unittest.TestCase):
    def test_single_valid_eye_is_not_averaged_with_missing_eye(self):
        store = SharedGazeData(calibration_file="missing-test-settings.json")
        store.update({
            "xl": 10.0,
            "yl": 20.0,
            "xr": -999.0,
            "yr": -999.0,
            "left_valid": True,
            "right_valid": False,
            "timestamp": 1.0,
        })
        gaze = store.get_latest_cal()
        self.assertTrue(gaze["valid"])
        self.assertEqual((gaze["x"], gaze["y"]), (10.0, 20.0))
        self.assertTrue(gaze["left_valid"])
        self.assertFalse(gaze["right_valid"])

    def test_affine_cross_axis_terms_are_applied(self):
        store = SharedGazeData(calibration_file="missing-test-settings.json")
        store.set_calibration_right(
            ox=10.0,
            oy=-20.0,
            gx=2.0,
            gy=3.0,
            gxy=0.5,
            gyx=-0.25,
        )
        store.update({
            "xl": -999.0,
            "yl": -999.0,
            "xr": 4.0,
            "yr": 8.0,
            "left_valid": False,
            "right_valid": True,
            "timestamp": 1.0,
        })
        gaze = store.get_latest_cal()
        self.assertAlmostEqual(gaze["xr"], 22.0)
        self.assertAlmostEqual(gaze["yr"], 3.0)

    def test_legacy_calibration_defaults_cross_terms_to_zero(self):
        calibration = normalize_calibration(
            {"ox": 1.0, "oy": 2.0, "gx": 3.0, "gy": 4.0}
        )
        self.assertEqual(calibration["gxy"], 0.0)
        self.assertEqual(calibration["gyx"], 0.0)


class FakeCalibrationStore:
    def __init__(self):
        self.left = {"ox": 1.0, "oy": 2.0, "gx": 3.0, "gy": 4.0}
        self.right = {"ox": 0.0, "oy": 0.0, "gx": 1.0, "gy": 1.0}

    def get_calibration_left(self):
        return self.left.copy()

    def get_calibration_right(self):
        return self.right.copy()

    def set_calibration_left(self, ox, oy, gx, gy):
        self.left = {"ox": ox, "oy": oy, "gx": gx, "gy": gy}

    def set_calibration_right(self, ox, oy, gx, gy):
        self.right = {"ox": ox, "oy": oy, "gx": gx, "gy": gy}

    def set_calibration_left_dict(self, calibration):
        self.left = normalize_calibration(calibration)

    def set_calibration_right_dict(self, calibration):
        self.right = normalize_calibration(calibration)


class CalibrationManagerTests(unittest.TestCase):
    def test_right_eye_only_calibration_preserves_missing_left_eye(self):
        manager = CalibrationManager.__new__(CalibrationManager)
        manager.shared_data = FakeCalibrationStore()
        data = np.asarray([
            [0.0, 0.0, np.nan, np.nan, 10.0, 20.0],
            [100.0, 0.0, np.nan, np.nan, 20.0, 20.0],
            [0.0, 100.0, np.nan, np.nan, 10.0, 30.0],
        ])

        left, right = manager._calculate_and_apply_3pt(data)

        self.assertEqual(left, normalize_calibration(
            {"ox": 1.0, "oy": 2.0, "gx": 3.0, "gy": 4.0}
        ))
        self.assertAlmostEqual(right["gx"], 10.0)
        self.assertAlmostEqual(right["gy"], 10.0)
        self.assertAlmostEqual(right["ox"], -100.0)
        self.assertAlmostEqual(right["oy"], -200.0)
        self.assertAlmostEqual(right["gxy"], 0.0)
        self.assertAlmostEqual(right["gyx"], 0.0)

    def test_affine_fit_reduces_reconstructed_ninth_point_error(self):
        raw = np.asarray([
            [-367.83, 3232.90],
            [-1683.24, 4514.24],
            [-294.89, 5008.23],
            [1321.00, 5134.73],
            [-1807.23, 2660.13],
            [1198.19, 3597.84],
            [-1741.51, 1255.64],
            [-319.54, 1727.95],
            [1226.76, 2314.14],
        ])
        target = np.asarray([
            [0.0, 0.0],
            [-320.0, 180.0],
            [0.0, 180.0],
            [320.0, 180.0],
            [-320.0, 0.0],
            [320.0, 0.0],
            [-320.0, -180.0],
            [0.0, -180.0],
            [320.0, -180.0],
        ])
        calibration = CalibrationManager._fit_affine(
            raw[:, 0], raw[:, 1], target[:, 0], target[:, 1], {}
        )
        prediction = CalibrationManager._predict_affine(
            calibration, raw[:, 0], raw[:, 1]
        )
        self.assertLess(abs(prediction[8, 1] - target[8, 1]), 25.0)
        self.assertNotAlmostEqual(calibration["gyx"], 0.0)

    def test_quadrant_targets_are_reproducible_and_in_quadrant_four(self):
        first = CalibrationManager._generate_quadrant_targets(
            (1920, 1080), 12345
        )
        second = CalibrationManager._generate_quadrant_targets(
            (1920, 1080), 12345
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertTrue(all(x > 0 and y < 0 for x, y in first))

    def test_fixation_tail_collects_unique_samples_for_100_ms(self):
        class FakeClock:
            def __init__(self):
                self.now = 0.0

            def getTime(self):
                return self.now

        class FakeTailSource:
            def __init__(self):
                self.index = 0

            def get_latest_cal(self):
                return {"x": 0.0, "y": 0.0, "valid": True}

            def get_latest(self):
                self.index += 1
                return {
                    "xl": -999.0,
                    "yl": -999.0,
                    "xr": float(self.index),
                    "yr": float(-self.index),
                    "left_valid": False,
                    "right_valid": True,
                    "valid": True,
                    "timestamp": self.index / 1000.0,
                }

        manager = CalibrationManager.__new__(CalibrationManager)
        manager.shared_data = FakeTailSource()
        clock = FakeClock()

        def advance_clock(duration):
            clock.now += duration

        with patch("CalibrationManager.core.Clock", return_value=clock), patch(
            "CalibrationManager.core.wait", side_effect=advance_clock
        ):
            samples = manager._collect_fixation_tail(0.0, 0.0, 200.0)

        self.assertGreaterEqual(clock.now, CALIBRATION_TAIL_SAMPLE_DURATION_S)
        self.assertGreaterEqual(len(samples), 95)
        self.assertTrue(all(np.isnan(sample[0]) for sample in samples))
        self.assertEqual(
            len({sample[2] for sample in samples}),
            len(samples),
        )

    def test_fixation_tail_rejects_gaze_outside_window(self):
        class OutsideSource:
            def get_latest_cal(self):
                return {"x": 500.0, "y": 0.0, "valid": True}

        manager = CalibrationManager.__new__(CalibrationManager)
        manager.shared_data = OutsideSource()

        samples = manager._collect_fixation_tail(0.0, 0.0, 200.0)

        self.assertIsNone(samples)


class EyeLinkBackendTests(unittest.TestCase):
    def test_project_configuration_uses_gaze_without_href_calibration(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        settings = _load_eyelink_settings(
            os.path.join(project_root, "eyelink_setting.json")
        )
        self.assertEqual(settings["sample_source"], "gaze")
        self.assertEqual(settings["active_eye"], "right")
        self.assertEqual(
            settings["calibration_file"],
            "eyelink_gaze_identity_setting.json",
        )

    def test_href_samples_and_edf_events_share_backend(self):
        tracker = FakeTracker(
            FakeSample(FakeEye((10.0, 20.0)), FakeEye((30.0, 40.0)))
        )
        pylink = fake_pylink_module(tracker)
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules, {"pylink": pylink}
        ):
            backend = EyeLinkBackend(
                host_ip="100.1.1.1",
                host_edf_name="FTEST001.EDF",
                local_edf_path=os.path.join(temp_dir, "session.edf"),
                sample_source="href",
                calibration_file="missing-test-settings.json",
            )
            gaze = backend.get_latest_cal()
            self.assertEqual((gaze["x"], gaze["y"]), (30.0, 40.0))
            self.assertEqual(gaze["timestamp"], 1.234)
            backend.send_event("STIM_ON\nTRIAL 1")
            self.assertIn("STIM_ON TRIAL 1", tracker.messages)
            backend.close()
            self.assertEqual(tracker.received[0], "FTEST001.EDF")
            self.assertTrue(tracker.closed)

    def test_host_edf_name_obeys_eight_character_limit(self):
        name = _host_edf_name("Saccade_20260803_120000")
        base, extension = os.path.splitext(name)
        self.assertEqual(len(base), 8)
        self.assertEqual(extension, ".EDF")

    def test_gaze_samples_convert_to_centered_psychopy_pixels(self):
        tracker = FakeTracker(
            FakeSample(None, FakeEye((0.0, 0.0), gaze=(1060.0, 440.0)))
        )
        pylink = fake_pylink_module(tracker)
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules, {"pylink": pylink}
        ):
            backend = EyeLinkBackend(
                host_ip="100.1.1.1",
                host_edf_name="FTEST002.EDF",
                local_edf_path=os.path.join(temp_dir, "session.edf"),
                screen_size=(1920, 1080),
                sample_source="gaze",
                calibration_file="missing-test-settings.json",
            )
            backend.set_calibration_right(
                ox=500.0,
                oy=-300.0,
                gx=2.0,
                gy=3.0,
                gxy=0.5,
                gyx=-0.25,
            )
            gaze = backend.get_latest_cal()
            self.assertEqual((gaze["x"], gaze["y"]), (100.0, 100.0))
            backend.close()

    def test_href_samples_still_use_finevision_affine_calibration(self):
        tracker = FakeTracker(
            FakeSample(None, FakeEye((10.0, 20.0)))
        )
        pylink = fake_pylink_module(tracker)
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules, {"pylink": pylink}
        ):
            backend = EyeLinkBackend(
                host_ip="100.1.1.1",
                host_edf_name="FTEST003.EDF",
                local_edf_path=os.path.join(temp_dir, "session.edf"),
                sample_source="href",
                calibration_file="missing-test-settings.json",
            )
            backend.set_calibration_right(
                ox=1.0,
                oy=2.0,
                gx=2.0,
                gy=3.0,
                gxy=0.0,
                gyx=0.0,
            )
            gaze = backend.get_latest_cal()
            self.assertEqual((gaze["x"], gaze["y"]), (21.0, 62.0))
            backend.close()

    def test_recalibration_resumes_recording_in_the_same_open_edf(self):
        class FakeGraphics:
            def __init__(self, tracker, window, arduino, reward_mode, reward_ms):
                self._calibInst = types.SimpleNamespace(text="")

            def setCalibrationColors(self, foreground, background):
                pass

            def setTargetType(self, target_type):
                pass

            def setTargetSize(self, size):
                pass

        fake_native = types.ModuleType("EyeLink_Native_Calibration")
        fake_native._axis_calibration_extent = lambda *args: {
            "proportion": 0.5
        }
        fake_native._task_visual_angle_to_pixels = lambda *args: 5.0
        fake_native._load_official_graphics_class = lambda: (
            object,
            "fake-helper.py",
        )
        fake_native._build_rewarding_graphics = (
            lambda *args, **kwargs: FakeGraphics
        )

        tracker = FakeTracker(
            FakeSample(None, FakeEye((0.0, 0.0), gaze=(960.0, 540.0)))
        )
        pylink = fake_pylink_module(tracker)
        graphics_lifecycle = []
        pylink.openGraphicsEx = lambda graphics: graphics_lifecycle.append(
            "open"
        )
        pylink.closeGraphics = lambda: graphics_lifecycle.append("close")
        original_receive = tracker.receiveDataFile

        def receive_after_graphics(source, destination):
            graphics_lifecycle.append("receive")
            original_receive(source, destination)

        tracker.receiveDataFile = receive_after_graphics
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules,
            {
                "pylink": pylink,
                "EyeLink_Native_Calibration": fake_native,
            },
        ):
            backend = EyeLinkBackend(
                host_ip="100.1.1.1",
                host_edf_name="FTEST004.EDF",
                local_edf_path=os.path.join(temp_dir, "session.edf"),
                sample_source="gaze",
                calibration_file="missing-test-settings.json",
            )
            backend.recalibrate(object(), calibration_type="HV5")

            self.assertEqual(tracker.setup_count, 1)
            self.assertEqual(tracker.recording_stops, 1)
            self.assertEqual(tracker.recording_starts, 2)
            self.assertIn(
                "FINEVISION_RECALIBRATION_RECORDING_RESUMED",
                tracker.messages,
            )
            self.assertIsNone(tracker.received)
            self.assertEqual(graphics_lifecycle, ["open"])
            backend.close()
            self.assertEqual(tracker.received[0], "FTEST004.EDF")
            self.assertEqual(
                graphics_lifecycle,
                ["open", "receive", "close"],
            )


if __name__ == "__main__":
    unittest.main()
