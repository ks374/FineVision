"""Offline RHX protocol tests. Never connect to real stimulation hardware."""
from collections import Counter
import ast
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from IntanStim import (RHXClient, RHXError, IntanWorker, channel_list, make_plan,
                       waveform_settings, digital_marker_settings)
from SaccadeElecLogic import make_plan as original_plan
import trodes_stim_once_gui_Intan as gui


class FakeSocket:
    """Fragment every response into 7-byte packets; coalesce replies without newline."""
    def __init__(self, mode="Record"):
        self.state = dict(type="ControllerStimRecord", synthetic="False", playback="False",
                          sampleratehertz="30000", stimstepsizemicroamps="1",
                          runmode=mode, version="3.5.2", uploadinprogress="False", expanderconnected="False",
                          **{"filename.basefilename": "test", "filename.path": "D:/test",
                             "filename.activefiletimestamp": "261020_120000"})
        for port, count in zip("abcd", (2, 1, 0, 0)):
            self.state[port+".numberamplifierchannels"] = str(count)
        for channel in ("A-000", "A-001", "B-000", "DIGITAL-OUT-01", "DIGITAL-OUT-02", "ANALOG-OUT-1", "ANALOG-OUT-2"):
            for key, value in dict(nativechannelname=channel, enabled="True",
                                   stimenabled="True", source="KeyPressF1").items():
                self.state[channel.lower()+"."+key] = value
        self.data = b""
        self.commands = []
        self.closed = False
        self.drop_trigger_reply = False
        self.ignore_set = None
        self.busy_reads = 0
        self.round_numeric_replies = False
        self.current_timestamp = 0

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        if data.startswith(b"set runmode ") and b"get " in data:
            raise socket.timeout("RHX acquisition blocks the remainder of the RunMode command batch")
        response = ""
        for command in data.decode().split(";"):
            if not command:
                continue
            self.commands.append(command)
            parts = command.split(" ", 2)
            action, key = parts[:2]
            key = key.lower()
            if action == "get":
                if key == 'currenttimestamp':
                    self.current_timestamp += 33000
                    response += f'Return: {self.current_timestamp}'
                elif key not in self.state:
                    response += "Error: Unrecognized parameter"
                else:
                    value = self.state[key]
                    if self.round_numeric_replies:
                        try:
                            value = format(float(value), '.6g')
                        except ValueError:
                            pass
                    if key == "uploadinprogress" and self.busy_reads:
                        self.busy_reads -= 1
                        value = "True"
                    label = key if key.startswith("filename.") else key.split(".")[-1]
                    if key == "type":
                        label = "Type"
                    response += f"Return: {label} {value}"
            elif action == "set":
                if key != "runmode" and self.state["runmode"].lower() != "stop":
                    response += "Error: Board must be stopped"
                elif key != self.ignore_set:
                    self.state[key] = parts[2]
            elif action == "execute":
                if key == "uploadstimparameters":
                    if self.state["runmode"].lower() != "stop":
                        response += "Error: Cannot upload while running"
                    self.busy_reads = 2
                elif key == "manualstimtriggerpulse":
                    if self.drop_trigger_reply:
                        return
        self.data += response.encode()

    def recv(self, size):
        if not self.data:
            raise socket.timeout("injected timeout")
        chunk, self.data = self.data[:7], self.data[7:]
        return chunk

    def close(self):
        self.closed = True


class NewSaccadeScheduleTests(unittest.TestCase):
    def test_128_channels_once_and_controls(self):
        import Saccade_Elec_stim_Eyelink_Intan as task
        plan = task.make_plan(0, 123, (3,12,-6,6),
                              task.DEFAULTS["Intan channels"], repeats=1)
        self.assertEqual(len(plan), 490)
        self.assertTrue(all(c["kind"] == "precontrol" for c in plan[:10]))
        stim = [c for c in plan if c["kind"] == "stim"]
        self.assertEqual(len(stim), 384)
        self.assertEqual(Counter(c["intan_channel"][0] for c in stim),
                         dict.fromkeys("ABCD", 96))
        self.assertEqual(set(Counter((c["intan_channel"], c["current_uA"])
                                     for c in stim).values()), {1})
        self.assertEqual({c["current_uA"] for c in stim}, {8,14,20})
        self.assertEqual({c["repeat"] for c in stim}, {1})
        controls = plan[14::5]
        self.assertEqual(len(controls), 96)
        self.assertTrue(all(c["kind"] == "control" for c in controls))
        cells = {(int((c["target_deg"][0]-3)/9*8),
                  int((c["target_deg"][1]+6)/12*12)) for c in controls}
        self.assertEqual(len(cells), 96)
        self.assertEqual(plan, task.make_plan(0,123,(3,12,-6,6),
                          task.DEFAULTS["Intan channels"], repeats=1))

    def test_both_record_only_types_receive_queries_only(self):
        for device_type in ("ControllerRecordUSB2", "ControllerRecordUSB3", "ControllerRecord"):
            fake = FakeSocket()
            fake.state["type"] = device_type
            with patch("IntanStim.socket.create_connection", return_value=fake):
                with self.assertRaisesRegex(RHXError, "RHS"):
                    RHXClient("tcp://localhost:5003", ["A-000"])
            self.assertEqual(fake.commands, ["get type"])
            self.assertTrue(fake.closed)


class AdapterTests(unittest.TestCase):
    def test_close_disables_and_stops_without_new_recording_segment(self):
        client, fake, events = self.client()
        client.configure({'A-000': waveform_settings(8)})
        resumes = fake.commands.count('set runmode record')
        segment = client.segment
        client.close()
        self.assertEqual(fake.commands.count('set runmode record'), resumes)
        self.assertEqual(client.segment, segment)
        self.assertEqual(fake.state['runmode'], 'stop')
        self.assertEqual(fake.state['a-000.stimenabled'], 'False')
        self.assertTrue(fake.closed)

    def test_recorded_guard_uses_segment_samples_and_rejects_reset(self):
        client, fake, _ = self.client()
        result = client.verify_trial_recording()
        self.assertGreaterEqual(result['timestamp']-result['segment_start_timestamp'], 33000)
        anchor = client.timestamp()
        fake.current_timestamp = -33000
        with self.assertRaisesRegex(RHXError, 'restarted'):
            client.wait_recorded_since(anchor, 1.1)
        client.close()

    def test_pretrial_stale_timestamp_rebases_but_requires_new_interval(self):
        client = RHXClient.__new__(RHXClient)
        client.mode = "record"
        client.segment = 9
        client.segment_start_timestamp = 900000
        events = []
        client.log = events.append
        client.get = lambda key: "record"
        samples = iter([100, 400, 500])
        client.timestamp = lambda: next(samples)
        with patch("IntanStim.time.monotonic", side_effect=[0, 0, 0, .02, .02, .04]), patch("IntanStim.time.sleep"):
            result = client.wait_recorded_since(900000, .01, allow_pretrial_rebase=True)
        self.assertGreaterEqual(result-client.segment_start_timestamp, 300)
        self.assertEqual(client.segment_start_timestamp, 100)
        self.assertTrue(events[0]["pretrial"])

    def test_tail_protection_delays_hardware_stop(self):
        client, fake, _ = self.client()
        client.configure({'A-000': waveform_settings(8)})
        client.protect_trial_tail(.1)
        before = time.perf_counter()
        client.clear()
        self.assertGreaterEqual(time.perf_counter()-before, .1)
        self.assertIsNone(client.tail_protection)
        client.close()

    def test_eye_task_requires_saving_record_mode(self):
        fake = FakeSocket('Run')
        with self.assertRaisesRegex(RHXError, 'requires RHX Record'), patch('IntanStim.socket.create_connection', return_value=fake):
            RHXClient('tcp://localhost:5000', ['A-000'], require_record=True)
        self.assertNotIn('set runmode stop', fake.commands)

    def test_gui_train_completion_and_next_update_have_only_one_gap(self):
        client, fake, _ = self.client()
        client.configure({'A-000': waveform_settings(8)})
        client.trigger()
        before = list(fake.commands)
        source = ast.parse(Path(gui.__file__).read_text(encoding='utf-8'))
        main = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        complete = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == 'post_train_complete')
        events, ready = [], []
        env = dict(time=time, audit=events.append, ready_after_clear=lambda: ready.append(True))
        exec(compile(ast.Module(body=[complete], type_ignores=[]), '<gui-completion>', 'exec'), env)
        env['post_train_complete']()
        self.assertEqual(fake.commands, before)
        self.assertEqual(ready, [True])
        self.assertFalse(client.armed)
        with self.assertRaises(RHXError):
            client.trigger()
        stops = fake.commands.count('set runmode stop')
        resumes = fake.commands.count('set runmode record')
        client.configure({'A-001': waveform_settings(14)})
        self.assertEqual(fake.commands.count('set runmode stop'), stops+1)
        self.assertEqual(fake.commands.count('set runmode record'), resumes+1)
        self.assertEqual(fake.state['a-000.stimenabled'], 'False')
        self.assertEqual(fake.state['a-001.stimenabled'], 'True')
        client.trigger()
        self.assertEqual(fake.commands.count('execute manualstimtriggerpulse f1'), 2)
        client.close()

    def test_rhx_rounded_duration_readback_keeps_same_sample_count(self):
        fake = FakeSocket()
        fake.round_numeric_replies = True
        client, fake, _ = self.client(fake)
        client.configure({'A-000': waveform_settings(8)})
        self.assertEqual(client.get('A-000.FirstPhaseDurationMicroseconds'), '166.667')
        self.assertEqual(client.get('A-000.InterphaseDelayMicroseconds'), '66.6667')
        self.assertEqual(client.get('A-000.PulseTrainPeriodMicroseconds'), '3333.33')
        client.close()

    def test_real_timing_mismatch_is_still_rejected(self):
        client, fake, _ = self.client()
        key = 'a-000.firstphasedurationmicroseconds'
        fake.state[key] = '200'
        fake.ignore_set = key
        with self.assertRaisesRegex(RHXError, 'mismatch'):
            client.configure({'A-000': waveform_settings(8)})
        self.assertNotIn('execute manualstimtriggerpulse f1', fake.commands)
        client.close()

    def client(self, fake=None):
        fake = fake or FakeSocket()
        events = []
        with patch("IntanStim.socket.create_connection", return_value=fake):
            client = RHXClient("tcp://127.0.0.1:5000", ["A-000", "A-001"], events.append)
        return client, fake, events

    def test_initialize_clears_stale_other_ports_and_digital_output(self):
        client, fake, events = self.client()
        for channel in ("a-000", "a-001", "b-000", "digital-out-01"):
            self.assertEqual(fake.state[channel+".stimenabled"].lower(), "false")
        self.assertEqual(fake.state["runmode"], "record")
        self.assertTrue(any(e["event"] == "RHX_ACQUISITION_RESUMED" for e in events))
        self.assertIn("_Intan_", fake.state["filename.basefilename"])
        self.assertEqual(fake.state["createnewdirectory"], "True")
        client.close()

    def test_digital_marker_lifecycle_and_shared_trigger(self):
        fake = FakeSocket()
        events = []
        with patch("IntanStim.socket.create_connection", return_value=fake):
            client = RHXClient("tcp://localhost:5000", ["A-000"], events.append,
                               digital_marker=True)
        client.configure({"A-000": waveform_settings(8)})
        prefix = "digital-out-01."
        self.assertEqual(fake.state[prefix+"stimenabled"], "True")
        self.assertEqual(fake.state["analogout1thresholdenabled"], "False")
        self.assertEqual(fake.state[prefix+"source"], fake.state["a-000.source"])
        self.assertEqual(fake.state[prefix+"numberofstimpulses"], "164")
        self.assertEqual(fake.state[prefix+"firstphasedurationmicroseconds"], "500")
        self.assertEqual(fake.state[prefix+"pulsetrainperiodmicroseconds"], "1000")
        configuration = next(e for e in events if e["event"] == "RHX_CONFIGURATION")
        self.assertIn("DIGITAL-OUT-01", configuration["waveforms"])
        client.trigger()
        self.assertEqual(fake.commands.count("execute manualstimtriggerpulse f1"), 1)
        self.assertIn("execute uploadstimparameters DIGITAL-OUT-01", fake.commands)
        client.disarm()
        with self.assertRaises(RHXError):
            client.trigger()
        client.configure({"A-000": waveform_settings(14)})
        client.clear()
        self.assertEqual(fake.state[prefix+"stimenabled"], "False")
        client.configure({"A-000": waveform_settings(20)})
        client.close()
        self.assertEqual(fake.state[prefix+"stimenabled"], "False")
        self.assertEqual(fake.state["runmode"], "stop")

    def test_marker_never_extends_past_electrical_last_phase(self):
        marker = digital_marker_settings(waveform_settings(8))
        last_edge_us = ((marker["NumberOfStimPulses"]-1)*marker["PulseTrainPeriodMicroseconds"]
                        + marker["FirstPhaseDurationMicroseconds"])
        electrical_end_us = 4912*1e6/30000
        self.assertEqual(last_edge_us, 163500)
        self.assertLessEqual(last_edge_us, electrical_end_us)
        self.assertLess(electrical_end_us-last_edge_us, 1000)

    def test_marker_readback_failure_prevents_trigger(self):
        fake = FakeSocket()
        with patch("IntanStim.socket.create_connection", return_value=fake):
            client = RHXClient("tcp://localhost:5000", ["A-000"], digital_marker=True)
        key = "digital-out-01.firstphasedurationmicroseconds"
        fake.state[key] = "100"
        fake.ignore_set = key
        with self.assertRaisesRegex(RHXError, "mismatch"):
            client.configure({"A-000": waveform_settings(8)})
        with self.assertRaises(RHXError):
            client.trigger()
        self.assertNotIn("execute manualstimtriggerpulse f1", fake.commands)
        client.close()

    def test_initialize_skips_clear_when_all_outputs_disabled(self):
        fake = FakeSocket()
        for key in fake.state:
            if key.endswith('.stimenabled'):
                fake.state[key] = 'False'
        client, fake, events = self.client(fake)
        self.assertEqual(fake.timeout, 20)
        self.assertFalse(any(c.startswith(('set ', 'execute ')) for c in fake.commands))
        self.assertEqual(fake.state['runmode'], 'Record')
        self.assertGreater(client.segment_start_timestamp, 0)
        skipped = [e for e in events if e['event'] == 'RHX_INITIAL_CLEAR_SKIPPED']
        self.assertEqual(skipped[0]['checked_output_count'], 7)
        self.assertTrue(client.initialized)
        client.configure({'A-000': waveform_settings(8)})
        self.assertEqual(fake.state['a-000.stimenabled'], 'True')
        client.close()

    def test_initialize_rejects_unknown_stim_enable_state(self):
        fake = FakeSocket()
        fake.state['b-000.stimenabled'] = 'Unknown'
        with self.assertRaisesRegex(RHXError, 'Invalid StimEnabled'), patch(
                'IntanStim.socket.create_connection', return_value=fake):
            RHXClient('tcp://localhost:5000', ['A-000'])
        self.assertFalse(any(c.startswith(('set ', 'execute ')) for c in fake.commands))

    def test_roundtrip_waveform_and_trigger_once(self):
        client, fake, events = self.client()
        settings = waveform_settings(14)
        client.configure({"A-001": settings})
        self.assertAlmostEqual(float(fake.state["a-001.firstphasedurationmicroseconds"]), 500/3, places=5)
        self.assertEqual(fake.state["a-001.polarity"], "NegativeFirst")
        self.assertEqual(fake.state["a-001.numberofstimpulses"], "50")
        progress = {}
        result = client.trigger(progress)
        self.assertEqual(progress["command_pc"], result["command_pc"])
        self.assertFalse(result["hardware_onset_verified"])
        with self.assertRaises(RHXError):
            client.trigger()
        self.assertEqual(fake.commands.count("execute manualstimtriggerpulse f1"), 1)
        client.clear()
        self.assertEqual(fake.state["a-001.stimenabled"], "False")
        names = [e["basefilename"] for e in events if e["event"] == "RHX_ACQUISITION_RESUMED"]
        self.assertEqual(len(names), len(set(names)))
        client.close()

    def test_timeout_consumes_trigger_and_never_retries(self):
        client, fake, _ = self.client()
        client.configure({"A-000": waveform_settings(8)})
        fake.drop_trigger_reply = True
        with self.assertRaises(socket.timeout):
            client.trigger()
        with self.assertRaises(RHXError):
            client.trigger()
        self.assertEqual(fake.commands.count("execute manualstimtriggerpulse f1"), 1)
        client.close()
        self.assertEqual(fake.state["runmode"], "stop")

    def test_rejects_wrong_device_rate_step_and_simulation_without_mutation(self):
        for key, value in (("type", "ControllerRecord"), ("synthetic", "True"),
                           ("playback", "True"), ("sampleratehertz", "20000"),
                           ("stimstepsizemicroamps", "5"), ("runmode", "Stop")):
            fake = FakeSocket()
            fake.state[key] = value
            with self.assertRaises(RHXError), patch("IntanStim.socket.create_connection", return_value=fake):
                RHXClient("tcp://localhost:5000", ["A-000"])
            self.assertFalse(any(c.startswith(("set ", "execute ")) for c in fake.commands))
            self.assertTrue(fake.closed)

    def test_rejects_missing_or_disabled_channels(self):
        for name in ("A-002", "A-000"):
            fake = FakeSocket()
            fake.state["a-000.enabled"] = "False"
            with self.assertRaises(RHXError), patch("IntanStim.socket.create_connection", return_value=fake):
                RHXClient("tcp://localhost:5000", [name])
            self.assertFalse(any(c.startswith("set ") for c in fake.commands))

    def test_readback_mismatch_aborts_without_resume_or_trigger(self):
        client, fake, _ = self.client()
        fake.state["a-000.firstphaseamplitudemicroamps"] = "0"
        fake.ignore_set = "a-000.firstphaseamplitudemicroamps"
        with self.assertRaisesRegex(RHXError, "mismatch"):
            client.configure({"A-000": waveform_settings(8)})
        self.assertEqual(fake.state["runmode"], "stop")
        self.assertTrue(client.failed)
        self.assertNotIn("execute manualstimtriggerpulse f1", fake.commands)
        client.close()

    def test_run_mode_does_not_create_record_files(self):
        fake = FakeSocket("Run")
        fake.state["filename.basefilename"] = ""
        client, fake, _ = self.client(fake)
        client.configure({"A-000": waveform_settings(20)})
        self.assertEqual(fake.state["runmode"], "run")
        self.assertFalse(any(c.startswith("set filename.") for c in fake.commands))
        client.close()

    def test_io_preflight_failure_does_not_stop_recording(self):
        fake = FakeSocket()
        del fake.state['digital-out-01.stimenabled']
        with self.assertRaises(RHXError), patch('IntanStim.socket.create_connection', return_value=fake):
            RHXClient('tcp://localhost:5000', ['A-000'])
        self.assertEqual(fake.state['runmode'], 'Record')
        self.assertNotIn('set runmode stop', fake.commands)

    def test_digital_names_match_official_source(self):
        client, fake, _ = self.client()
        self.assertIn('get DIGITAL-OUT-01.StimEnabled', fake.commands)
        self.assertIn('get DIGITAL-OUT-02.StimEnabled', fake.commands)
        self.assertNotIn('get DIGITAL-OUT-1.StimEnabled', fake.commands)
        client.close()

    def test_external_runmode_change_prevents_trigger(self):
        client, fake, _ = self.client()
        client.configure({"A-000": waveform_settings(8)})
        fake.state["runmode"] = "Stop"
        with self.assertRaises(RHXError):
            client.trigger()
        self.assertNotIn("execute manualstimtriggerpulse f1", fake.commands)
        client.close()

    def test_worker_mapping_and_duplicate_guard(self):
        fake = FakeSocket()
        def wait(job):
            deadline = time.monotonic()+5
            while not job["done"] and time.monotonic() < deadline:
                time.sleep(.001)
            self.assertTrue(job["done"])
            return job
        with tempfile.TemporaryDirectory() as directory, patch("IntanStim.socket.create_connection", return_value=fake):
            worker = IntanWorker("tcp://localhost:5000", "A-000:A-001", Path(directory)/"audit.jsonl")
            self.assertNotIn("error", wait(worker.submit("init")))
            condition = dict(kind="stim", plan_id=7, intan_channel="A-001", current_uA=20)
            self.assertNotIn("error", wait(worker.submit("prepare_trial", condition)))
            self.assertNotIn("error", wait(worker.submit("trigger", condition)))
            self.assertIn("error", wait(worker.submit("trigger", condition)))
            stops = fake.commands.count('set runmode stop')
            resumes = fake.commands.count('set runmode record')
            self.assertNotIn("error", wait(worker.submit("prepare_trial", dict(kind="control"))))
            self.assertEqual(fake.commands.count('set runmode stop'), stops)
            self.assertEqual(fake.commands.count('set runmode record'), resumes)
            self.assertFalse(worker.hardware.armed)
            self.assertNotIn('error', wait(worker.submit('disarm_trial')))
            self.assertEqual(fake.commands.count('set runmode stop'), stops)
            next_condition = dict(kind='stim', plan_id=8, intan_channel='A-000', current_uA=14)
            self.assertNotIn('error', wait(worker.submit('prepare_trial', next_condition)))
            self.assertEqual(fake.commands.count('set runmode stop'), stops+1)
            self.assertEqual(fake.commands.count('set runmode record'), resumes+1)
            self.assertEqual(fake.state['a-001.stimenabled'], 'False')
            self.assertEqual(fake.state['a-000.stimenabled'], 'True')
            self.assertNotIn("error", wait(worker.submit("close")))
            worker.thread.join(2)
            self.assertEqual(fake.commands.count("execute manualstimtriggerpulse f1"), 1)


class PlanAndGUITests(unittest.TestCase):
    def test_32_channel_plan_counts_balance_and_mapping(self):
        plan = make_plan(128, 123, (3, 12, -6, 6))
        self.assertEqual(Counter(c["kind"] for c in plan), dict(stim=192, control=48, precontrol=10))
        stim = [c for c in plan if c["kind"] == "stim"]
        self.assertEqual(set(Counter((c["intan_channel"], c["current_uA"]) for c in stim).values()), {2})
        for c in stim:
            self.assertEqual(c["intan_channel"], f"A-{c['hw']-128:03d}")
        self.assertTrue(all(c["kind"] == "control" for c in plan[14::5]))

    def test_128_schedule_matches_original_exactly(self):
        channels = ",".join(f"{port}-000:{port}-031" for port in "ABCD")
        plan = make_plan(0, 99, (3, 12, -6, 6), channels)
        unmapped = [{k: v for k, v in c.items() if k != "intan_channel"} for c in plan]
        self.assertEqual(unmapped, original_plan(0, 99, (3, 12, -6, 6)))

    def test_channel_ranges_and_duplicates(self):
        self.assertEqual(channel_list("a-001:A-002,B-005"), ["A-001", "A-002", "B-005"])
        for text in ("A-001:A-000", "A-128", "A-000,B-000,A-000", "E-000", "A-000:B-001"):
            with self.assertRaises(ValueError):
                channel_list(text)

    def test_waveform_limits(self):
        for kwargs in (dict(count=257), dict(phase=151), dict(period=5), dict(dwell=-1),
                       dict(current=float("nan")), dict(count=1.5)):
            args = dict(current=8)
            args.update(kwargs)
            with self.assertRaises(ValueError):
                waveform_settings(**args)

    def test_gui_monopolar_and_bipolar_programs(self):
        class Hardware:
            step = 1
            def configure(self, values):
                self.values = values
        h = Hardware()
        p = dict(step="1", current_ua=8, phase=5, dwell=2, period=100, count=50,
                 cathode_id="A-000", anode_id="A-000")
        gui.configure_once(p, h)
        self.assertEqual(list(h.values), ["A-000"])
        p["anode_id"] = "A-001"
        gui.configure_once(p, h)
        self.assertEqual(h.values["A-000"]["Polarity"], "NegativeFirst")
        self.assertEqual(h.values["A-001"]["Polarity"], "PositiveFirst")
        self.assertEqual(h.values["A-000"]["Source"], h.values["A-001"]["Source"])


if __name__ == "__main__":
    unittest.main()
