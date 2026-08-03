import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from Shared_Memory_Util import SharedGazeData
from eyetracker.eyelink_backend import EyeLinkBackend
from eyetracker.runtime import _host_edf_name


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
        return 0

    def stopRecording(self):
        pass

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


class EyeLinkBackendTests(unittest.TestCase):
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
            self.assertEqual((gaze["x"], gaze["y"]), (20.0, 30.0))
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
            FakeSample(FakeEye((0.0, 0.0), gaze=(1060.0, 440.0)), None)
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
            gaze = backend.get_latest_cal()
            self.assertEqual((gaze["x"], gaze["y"]), (100.0, 100.0))
            backend.close()


if __name__ == "__main__":
    unittest.main()
