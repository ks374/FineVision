import csv
import json
import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import Fixation_movingbar as mb


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = SimpleNamespace(t=100., frame=0, keys=lambda: [])
    monkeypatch.setattr(mb.time, "perf_counter", lambda: clock.t)
    class Window:
        size = [1920, 1080]
        monitorFramePeriod = .01
        def __init__(self, advance):
            self.advance, self.callbacks = advance, []
        def callOnFlip(self, callback, *args):
            self.callbacks.append((callback, args))
        def flip(self):
            if self.advance:
                clock.t += .01
                clock.frame += 1
            for callback, args in self.callbacks:
                callback(*args)
            self.callbacks.clear()
            return clock.t
    def stimulus(*args, **kwargs):
        obj = Mock()
        obj.pos = kwargs.get("pos", (0, 0))
        return obj
    monkeypatch.setattr(mb.visual, "Circle", stimulus)
    monkeypatch.setattr(mb.visual, "Rect", stimulus)
    monkeypatch.setattr(mb, "ArduinoController", Mock)
    renderer = Mock()
    renderer.update.return_value = {"valid": True, "x": 0, "y": 0}
    monkeypatch.setattr(mb, "GazeTrackerRenderer", lambda *args: renderer)
    monkeypatch.setattr(mb.event, "getKeys", lambda: clock.keys())
    monkeypatch.setattr(mb.event, "clearEvents", Mock())
    params = dict(mb.DEFAULT_PARAMS)
    params.update({"Wait Time (s)": .4, "Bar Motion Duration (s)": .1,
        "Bar On After Fixation Start (ms)": 250, "Timeout (s)": .5,
        "ITI (s)": .01, "Random Seed (0=random)": 99})
    manager = SimpleNamespace(exp_params=params, session_parameters_confirmed=True)
    tracker = Mock()
    task = mb.FixationMovingBarTask(Window(True), Window(False), tracker, manager,
        0, 100., str(tmp_path), "H18_test", None, None, tracker, session_utc="UTC_TEST")
    task.update_params()
    yield task, clock, renderer, tracker, tmp_path
    task.close()


def run_trial(task):
    row, _ = task._run_one_trial(1, 1, 1, {"direction": "Right", "range_deg": 4.})
    task._write_trial(row)
    return row


@pytest.mark.parametrize("outcome", ["Success", "NoFix", "PreBar", "BarMotion"])
def test_outcomes_and_frame_alignment(rig, outcome):
    task, clock, renderer, tracker, folder = rig
    def gaze():
        trial = task.current_trial
        valid = outcome != "NoFix"
        if trial and outcome == "PreBar" and trial["Time_FixAcquired"] is not None:
            valid = False
        if trial and outcome == "BarMotion" and trial["Time_BarOn"] is not None:
            valid = False
        return {"valid": valid, "x": 0, "y": 0}
    renderer.update.side_effect = gaze
    row = run_trial(task)
    status = "Break" if outcome in ("PreBar", "BarMotion") else outcome
    assert row["Status"] == status
    assert row["Time_DrawFinish"] == row["Time_TrialStart"] == pytest.approx(.01)
    assert all(f["pd_white"] == f["bar_visible"] for f in task.frames)
    assert row["Time_PDOn"] == row["Time_BarOn"]
    assert row["Time_PDOff"] == row["Time_BarOff"]
    assert row["Time_OutcomePDOn"] is None
    if outcome in ("PreBar", "BarMotion"):
        assert row["Break_Phase"] == outcome
        assert row["Time_Break"] == row["Time_End"]
        assert task.now() - row["Time_Break"] >= .5
    if outcome == "Success":
        assert row["Time_BarOn"] - row["Time_GazeEnter"] >= .25
        assert row["Time_BarOff"] == row["Time_PDOff"]
        assert row["Time_BarOff"] - row["Time_BarOn"] >= .1
    if outcome == "PreBar":
        assert row["Time_BarOn"] is None
    if outcome != "NoFix":
        assert row["Time_FixAcquired"] - row["Time_GazeEnter"] >= .15
    messages = [c.args[0] for c in tracker.send_event.call_args_list]
    assert not any(m.startswith("REWARD") for m in messages)
    assert any(m.startswith(status.upper() + " TRIAL") for m in messages)
    with open(folder / "Fixation_movingbar_task_log_H18_test.csv", encoding="utf-8-sig") as stream:
        saved = list(csv.DictReader(stream))
    assert len(saved) == 1
    assert json.loads(saved[0]["Parameters_JSON"])["Random Seed (0=random)"] == 99


@pytest.mark.parametrize("escape_frame", [1, 20, 30])
def test_escape_saves_current_trial_and_drains_code(rig, escape_frame):
    task, clock, _, _, folder = rig
    clock.keys = lambda: ["escape"] if clock.frame >= escape_frame else []
    with pytest.raises(mb.TaskAbort):
        run_trial(task)
    assert len(task.behavior_log) == 1
    assert task.behavior_log[0]["Status"] == "Aborted"
    assert task.current_trial is None
    assert not task.pulse.busy
    assert all(f["pd_white"] == f["bar_visible"] for f in task.frames)
    assert task.frames[-1]["pd_white"] is False
    assert task.behavior_log[0]["Time_FixationPointOff"] is not None


def test_escape_during_outcome_preserves_success(rig):
    task, clock, _, _, _ = rig
    clock.keys = lambda: ["escape"] if task.current_trial and task.current_trial["Status"] == "Success" else []
    row = run_trial(task)
    assert row["Status"] == "Success" and task.quit_requested
    assert row["Time_PDOff"] == row["Time_BarOff"]
    assert all(f["pd_white"] == f["bar_visible"] for f in task.frames)


def test_short_trial_codes_are_separated(rig):
    task, _, renderer, _, _ = rig
    task.wait_time_s = .001
    renderer.update.return_value = {"valid": False, "x": 0, "y": 0}
    run_trial(task)
    assert not any(f["pd_white"] for f in task.frames)


def test_task_start_esc_finishes_one_frame_pulse(rig):
    task, clock, _, _, _ = rig
    clock.keys = lambda: ["escape"] if clock.frame >= 6 else []
    with pytest.raises(mb.TaskAbort):
        task.run_task()
    assert [f["pd_white"] for f in task.frames] == [False]*5 + [True]*5 + [False]*5 + [True]*5 + [False]
    assert not task.behavior_log and not task.pulse.busy


def test_conditions_and_subject_session_paths(tmp_path):
    block = mb.make_condition_block(random.Random(5))
    assert len({(c["direction"], c["range_deg"]) for c in block}) == 8
    first, a = mb.create_session_dir(str(tmp_path), "H18")
    second, b = mb.create_session_dir(str(tmp_path), "H18")
    assert a != b and first.startswith("H18_") and second.startswith("H18_")


def test_main_metadata_and_tracker_cleanup(tmp_path, monkeypatch):
    manager = SimpleNamespace(exp_params=dict(mb.DEFAULT_PARAMS))
    monkeypatch.setattr(mb, "FineVision_Notebook", lambda **kw: manager)
    monkeypatch.setattr(mb, "confirm_session_parameters", lambda manager: True)
    monkeypatch.setattr(mb, "create_session_dir", lambda *args: ("H18_test", str(tmp_path)))
    tracker = Mock(mode="eyelink")
    factory = Mock(return_value=tracker)
    monkeypatch.setattr(mb, "create_tracker_runtime", factory)
    monkeypatch.setattr(mb.visual, "Window", Mock())
    task = Mock(nominal_period=.01)
    task.close.side_effect = RuntimeError("Simulated cleanup error")
    constructor = Mock(return_value=task)
    monkeypatch.setattr(mb, "FixationMovingBarTask", constructor)
    mb.main("eyelink")
    tracker.close.assert_called_once()
    assert factory.call_args.kwargs["save_dir"] == str(tmp_path)
    assert constructor.call_args.args[6] == str(tmp_path)
    metadata = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert metadata["session_t0_perf_counter"] == factory.call_args.kwargs["session_t0"]
    messages = [c.args[0] for c in tracker.send_event.call_args_list]
    assert any(m.startswith("SESSION_ZERO") for m in messages)
    assert len([m for m in messages if m.startswith("CLOCK_SYNC")]) == 2
