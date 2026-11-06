import csv
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import FixationTask as ft
from FramePulse import FramePulse, DisplaySync


def test_startup_double_pulse_then_continuous_visibility():
    signal = DisplaySync()
    signal.start("TASK_START")
    frames = []
    while signal.busy:
        frames.append(signal.next_frame())
    assert [f[0] for f in frames] == [True]*5 + [False]*5 + [True]*5 + [False]
    assert [(i, f[1]) for i, f in enumerate(frames) if f[1]] == [(0, "ON"), (5, "OFF"), (10, "ON"), (15, "OFF")]
    assert signal.next_frame(True, "FIXATION")[1] == "ON"
    assert all(signal.next_frame(True, "FIXATION")[:2] == (True, None) for _ in range(30))
    assert signal.next_frame(False, "FIXATION")[1] == "OFF"


@pytest.mark.parametrize("label,count", FramePulse.CODES.items())
def test_pulse_edges_and_black_gap(label, count):
    pulse = FramePulse()
    pulse.start(label)
    with pytest.raises(RuntimeError):
        pulse.start(label)
    frames = []
    while pulse.busy:
        frames.append(pulse.next_frame())
    assert [white for white, _, _ in frames] == [True] * count + [False] * 3
    assert frames[0][1] == "ON"
    assert frames[count][1] == "OFF"
    assert sum(edge is not None for _, edge, _ in frames) == 2
    pulse.start(label)
    assert pulse.next_frame()[1] == "ON"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = SimpleNamespace(t=100., frame=0, keys=lambda: [])
    monkeypatch.setattr(ft.time, "perf_counter", lambda: clock.t)
    class Window:
        size = [1920, 1080]
        monitorFramePeriod = .01
        def __init__(self, advance):
            self.callbacks = []
            self.advance = advance
        def callOnFlip(self, fn, *args):
            self.callbacks.append((fn, args))
        def flip(self):
            if self.advance:
                clock.t += .01
                clock.frame += 1
            for fn, args in self.callbacks:
                fn(*args)
            self.callbacks.clear()
            return clock.t
    monkeypatch.setattr(ft.visual, "Circle", lambda *a, **k: Mock())
    monkeypatch.setattr(ft.visual, "Rect", lambda *a, **k: Mock())
    monkeypatch.setattr(ft, "ArduinoController", Mock)
    renderer = Mock()
    renderer.update.return_value = {"valid": True, "x": 0, "y": 0}
    monkeypatch.setattr(ft, "GazeTrackerRenderer", lambda *a: renderer)
    monkeypatch.setattr(ft.event, "getKeys", lambda: clock.keys())
    manager = SimpleNamespace(exp_params={"Subject ID": "H18", "Wait Time (s)": .4,
        "Stim Duration (s)": .1, "ITI (s)": .01, "Timeout (s)": .5},
        prompt_for_runtime_parameters=Mock())
    tracker = Mock()
    task = ft.FixationTask(Window(True), Window(False), tracker, manager, 0,
                           str(tmp_path), "test", 100., "UTC_TEST")
    yield task, clock, renderer, tracker, tmp_path
    task.close()


@pytest.mark.parametrize("status", ["Success", "Break", "NoFix"])
def test_decision_events_flip_times_and_saved_parameters(rig, status):
    task, clock, renderer, tracker, folder = rig
    def gaze():
        valid = status != "NoFix"
        if status == "Break" and task.current and task.current["Time_FixAcquired"] is not None:
            valid = False
        return {"valid": valid, "x": 0, "y": 0}
    renderer.update.side_effect = gaze
    task.run_trial(1)
    row = task.behavior_log[0]
    assert row["Status"] == status
    assert row["Time_DrawFinish"] == pytest.approx(.01)
    trial_edge = next(e for e in task.events if e["event"] == "PD_FIXATION_ON")
    assert row["Time_DrawFinish"] == trial_edge["time"]
    decision = row[{"Success": "Time_Success", "Break": "Time_Break", "NoFix": "Time_NoFix"}[status]]
    assert row["Time_End"] == decision < row["Time_PDOff"]
    assert row["Time_PDOn"] == row["Time_DrawFinish"]
    assert row["Time_PDOff"] == row["Time_FixOff"]
    assert row["Time_OutcomePDOn"] is None
    assert [f["pd_white"] for f in task.frames] == [True] * (next(i for i, f in enumerate(task.frames) if not f["pd_white"])) + [False] * sum(not f["pd_white"] for f in task.frames)
    if status != "NoFix":
        assert row["Time_FixAcquired"] - row["Time_GazeEnter"] >= .150
        assert any("FIX_ACQUIRED" in c.args[0] for c in tracker.send_event.call_args_list)
    if status == "Break":
        assert task.now() - row["Time_Break"] >= .5
    messages = [c.args[0] for c in tracker.send_event.call_args_list]
    assert not any("REWARD" in m for m in messages)
    if status != "Success":
        assert any(m.startswith(status.upper() + " ") for m in messages)
    with open(folder / "Fixation_task_log_test.csv", encoding="utf-8-sig") as stream:
        saved = list(csv.DictReader(stream))
    assert len(saved) == 1  # Written before close, not just retained in memory.
    assert json.loads(saved[0]["Parameters_JSON"])["Subject ID"] == "H18"


@pytest.mark.parametrize("escape_frame", [1, 20])
def test_escape_saves_aborted_trial_and_completes_current_pulse(rig, escape_frame):
    task, clock, _, _, _ = rig
    clock.keys = lambda: ["escape"] if clock.frame >= escape_frame else []
    task.run_trial(1)
    assert task.behavior_log[0]["Status"] == "Aborted"
    assert task.quit_requested and not task.pulse.busy
    assert not any(e["event"].startswith("PD_SUCCESS") for e in task.events)
    assert sum(f["pd_white"] for f in task.frames) == escape_frame
    assert task.frames[-1]["pd_white"] is False


def test_session_start_escape_exits_without_starting_trial(rig):
    task, clock, _, _, _ = rig
    clock.keys = lambda: ["escape"] if clock.frame >= 6 else []
    task.run_task()
    assert not task.behavior_log
    assert [f["pd_white"] for f in task.frames] == [False]*5 + [True]*5 + [False]*5 + [True]*5 + [False]
    assert not task.pulse.busy


def test_zero_wait_does_not_merge_trial_and_outcome_codes(rig):
    task, _, _, _, _ = rig
    task.wait_time = 0
    task.run_trial(1)
    whites = [f["pd_white"] for f in task.frames]
    assert whites == [True, False]


def test_unique_subject_session_directories(tmp_path):
    first, a = ft.create_session_dir(str(tmp_path), "H18")
    second, b = ft.create_session_dir(str(tmp_path), "H18")
    assert a != b
    assert first.startswith("H18_") and second.startswith("H18_")


def test_escape_during_outcome_preserves_decided_result(rig):
    task, clock, _, _, _ = rig
    clock.keys = lambda: ["escape"] if task.current and task.current["Status"] == "Success" else []
    task.run_trial(1)
    assert task.quit_requested
    assert task.behavior_log[0]["Status"] == "Success"
    assert not any(f["pd_code"] == "SUCCESS" for f in task.frames)
    assert task.behavior_log[0]["Time_PDOff"] is not None


def test_main_uses_one_directory_and_always_closes_tracker(tmp_path, monkeypatch):
    manager = SimpleNamespace(exp_params={"Subject ID": "H18"})
    monkeypatch.setattr(ft, "FineVision_Notebook", lambda **k: manager)
    monkeypatch.setattr(ft, "confirm_session_parameters", lambda m: True)
    monkeypatch.setattr(ft, "create_session_dir", lambda *a: ("H18_test", str(tmp_path)))
    runtime = Mock()
    create_runtime = Mock(return_value=runtime)
    monkeypatch.setattr(ft, "create_tracker_runtime", create_runtime)
    windows = [Mock(), Mock()]
    monkeypatch.setattr(ft.visual, "Window", Mock(side_effect=windows))
    task = Mock(nominal_period=.01)
    task.close.side_effect = RuntimeError("Test log-close failure")
    constructor = Mock(return_value=task)
    monkeypatch.setattr(ft, "FixationTask", constructor)
    ft.main()
    task.run_task.assert_called_once()
    runtime.close.assert_called_once()
    for window in windows:
        window.close.assert_called_once()
    assert create_runtime.call_args.kwargs["save_dir"] == str(tmp_path)
    assert constructor.call_args.args[5] == str(tmp_path)
    meta = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    messages = [c.args[0] for c in runtime.send_event.call_args_list]
    assert any(m.startswith("SESSION_ZERO PERF_COUNTER ") for m in messages)
    assert len([m for m in messages if m.startswith("CLOCK_SYNC ")]) == 2
    assert meta["session_t0_perf_counter"] == create_runtime.call_args.kwargs["session_t0"]
