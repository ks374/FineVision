"""RAW affine endpoints, with EyeLink native event times only; no Host GAZE."""
import json
import tempfile
import time
from unittest.mock import Mock
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Saccade_Elec_stim_Eyelink_Intan as task


class Sample:
    def __init__(self, ms, pair): self.ms, self.pair = ms, pair
    def getTime(self): return self.ms
    def isBinocular(self): return False
    def isRightSample(self): return True
    def getRightEye(self): return SimpleNamespace(getRawPupil=lambda: self.pair)


class Event:
    def __init__(self, start=100, end=102): self.start, self.end = start, end
    def getEye(self): return 1
    def getStartTime(self): return self.start
    def getEndTime(self): return self.end
    def getStatus(self): return 0
    def getStartGaze(self): raise AssertionError('Host GAZE must never be read in RAW mode')
    def getEndGaze(self): raise AssertionError('Host GAZE must never be read in RAW mode')


class RawSettingsTests(unittest.TestCase):
    def test_global_gaze_is_preserved_and_local_raw_calibration_snapshotted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "eyelink_setting.json"
            original = json.dumps(dict(sample_source="gaze", host_ip="100.1.1.1",
                                       calibration_file="gaze_calibration.json"))
            source.write_text(original, encoding="utf-8")
            raw = root / "eyelink_raw_pupil_setting.json"
            raw.write_text('{"default_right_cal": {"ox": 123}}', encoding="utf-8")
            session = root / "session"
            session.mkdir()
            dest = session / "eyelink_raw_settings.json"
            task.session_eyelink_raw_settings(source, dest)
            settings = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(settings["sample_source"], "raw")
            self.assertEqual(settings["active_eye"], "right")
            self.assertEqual(settings["host_ip"], "100.1.1.1")
            self.assertEqual(Path(settings["calibration_file"]).read_bytes(), raw.read_bytes())
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_raw_global_keeps_custom_calibration_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "settings.json"
            source.write_text(json.dumps(dict(sample_source="raw",
                              calibration_file="custom.json")), encoding="utf-8")
            (root / "custom.json").write_text("{}", encoding="utf-8")
            task.session_eyelink_raw_settings(source, root / "snapshot.json")
            self.assertEqual(json.loads((root / "snapshot.json").read_text(
                encoding="utf-8"))["sample_source"], "raw")


class RawEventTests(unittest.TestCase):
    def reader(self, payload):
        queue = list(payload)
        last = [None]
        commands, events, samples = [], [], []
        def next_data():
            if not queue: return 0
            kind, last[0] = queue.pop(0)
            return kind
        tracker = SimpleNamespace(getNextData=next_data, getFloatData=lambda: last[0],
                                  getNewestSample=lambda: None,
                                  sendCommand=lambda c: commands.append(c) or 0)
        calibration = dict(ox=0, oy=0, gx=10, gy=-3, gxy=2, gyx=1)
        backend = SimpleNamespace(sample_source='raw', _tracker=tracker,
            _pylink=SimpleNamespace(ENDSACC=6, SAMPLE_TYPE=200),
            _gaze_source=SimpleNamespace(get_calibration_right=lambda: calibration),
            _is_valid_pair=lambda xy: all(math.isfinite(v) and abs(v) < 32000 and v != -999 for v in xy))
        reader = task.EyeEvents(backend, task.DEFAULTS, SimpleNamespace(write=events.append),
                                SimpleNamespace(write=samples.append))
        return reader, queue, events, samples, commands

    def test_stale_ordered_samples_stop_instead_of_causing_nofix(self):
        reader, _, _, _, _ = self.reader([(200, Sample(100, (0,0)))])
        reader.tracker.getNewestSample = lambda: Sample(65100, (0,0))
        with self.assertRaisesRegex(RuntimeError, "lag newest sample"):
            reader.drain(1)

    def recovery_reader(self, lag_ms=0):
        reader, _, _, _, _ = self.reader([])
        pending = [False]
        def now_ms():
            return int(time.perf_counter()*1000)
        def next_data():
            pending[0] = not pending[0]
            return 200 if pending[0] else 0
        reader.api.RECORD_LINK_SAMPLES = 4
        reader.api.RECORD_LINK_EVENTS = 8
        reader.tracker = SimpleNamespace(resetData=Mock(), dataSwitch=Mock(return_value=0),
            trackerTime=now_ms, getNextData=next_data,
            getFloatData=lambda: Sample(now_ms()-lag_ms, (0,0)),
            getNewestSample=lambda: Sample(now_ms(), (0,0)))
        return reader

    def test_pause_recovery_requires_fresh_samples_after_sdk_reset(self):
        reader = self.recovery_reader()
        result = reader.recover_after_pause(timeout=1)
        reader.tracker.resetData.assert_called_once_with()
        reader.tracker.dataSwitch.assert_called_once_with(12)
        self.assertTrue(result["sdk_link_reset"])
        self.assertLessEqual(result["queue_lag_ms"], 50)
        self.assertGreaterEqual(result["elapsed_s"], .1)

    def test_pause_recovery_rejects_queue_that_returns_empty_but_is_old(self):
        reader = self.recovery_reader(lag_ms=65000)
        with self.assertRaisesRegex(RuntimeError, "did not recover"):
            reader.recover_after_pause(timeout=.03)

    def test_full_affine_raw_endpoints_and_native_timestamps(self):
        reader, _, events, samples, commands = self.reader([
            (200, Sample(100, (0,0))), (200, Sample(101, (5,1))),
            (200, Sample(102, (10,2))), (6, Event())])
        result = reader.drain(1)
        self.assertEqual(len(result), 1)
        event = result[0]
        self.assertTrue(event['valid'])
        self.assertEqual(event['start_px'], [960.,540.])
        self.assertEqual(event['end_px'], [1064.,536.])
        expected = task.gaze_degrees((1064,536), (1920,1080), (54,30), 60)
        self.assertAlmostEqual(event['amplitude_deg'], math.hypot(*expected))
        self.assertEqual((event['start_eyelink'], event['end_eyelink']), (100,102))
        self.assertEqual(event['source'], 'EyeLink_ENDSACC_RAW_affine')
        self.assertEqual(len(samples), 3)
        self.assertFalse(any('GAZE' in command for command in commands))

    def test_missing_pupil_inside_saccade_invalidates_event(self):
        reader, _, _, _, _ = self.reader([(200, Sample(100, (0,0))),
            (200, Sample(101, (32768,32768))), (200, Sample(102, (10,2))), (6, Event())])
        event = reader.drain(1)[0]
        self.assertFalse(event['valid'])
        self.assertIsNone(event['amplitude_deg'])

    def test_event_waits_for_raw_end_sample(self):
        reader, queue, _, _, _ = self.reader([(200, Sample(100, (0,0))), (6, Event())])
        self.assertEqual(reader.drain(1), [])
        queue.extend([(200, Sample(101, (5,1))), (200, Sample(102, (10,2)))])
        self.assertTrue(reader.drain(1)[0]['valid'])

    def test_unavailable_start_endpoint_is_not_replaced_with_gaze(self):
        reader, _, _, _, _ = self.reader([(200, Sample(110, (10,2))), (6, Event())])
        event = reader.drain(1)[0]
        self.assertFalse(event['valid'])
        self.assertIsNone(event['start_px'])

    def test_pause_discards_pending_raw_events(self):
        reader, _, _, _, _ = self.reader([(200, Sample(100, (0,0))), (6, Event())])
        reader.drain(1)
        self.assertEqual(len(reader.pending_saccades), 1)
        reader.discard_pause_data()
        self.assertEqual(len(reader.pending_saccades), 0)
        self.assertEqual(len(reader.raw_samples), 0)


if __name__ == '__main__':
    unittest.main()
