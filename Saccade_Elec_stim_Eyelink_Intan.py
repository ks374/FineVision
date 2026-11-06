"""Intan RHS version: parameter uploads cause ITI acquisition gaps.
EyeLink saccade-to-phosphene task. Default: green visual simulation.

Run with PsychoPy Python. --mouse enables a desktop-only rehearsal; --preview
writes the complete schedule without opening a window or connecting hardware.
"""
import argparse
from collections import deque
import csv
import json
import math
import os
from pathlib import Path
import queue
import random
import threading
import time
from datetime import datetime
from types import SimpleNamespace

from SaccadeElecLogic import WAVEFORM as ORIGINAL_WAVEFORM, gaze_degrees, qualifies, advance, event_time_ms
from IntanStim import IntanWorker, make_plan, channel_list

WAVEFORM = dict(ORIGINAL_WAVEFORM, backend="Intan RHX", polarity="NegativeFirst",
                enable_amp_settle=True, post_stim_amp_settle_us=1000,
                maintain_amp_settle=False, enable_charge_recovery=False)
WAVEFORM.pop("group", None)
WAVEFORM.pop("slot", None)

ROOT = Path(__file__).resolve().parent
RECORD_GUARD_S = 1.1  # At least 1 s plus scheduling/USB margin on both sides.
REWARD_DELAY_S = 0.3  # Keep a post-result recording window before automatic water.
DEFAULTS = {
    "Subject ID": "Monkey_H18", "Simulate stimulation": True,
    "Random seed": 20261014,
    "RF x_min (deg)": 3.0, "RF x_max (deg)": 12.0,
    "RF y_min (deg)": -6.0, "RF y_max (deg)": 6.0,
    "Control calibrated level": 150, "Target diameter (deg)": 0.5,
    "Wait Time (s)": 5.0, "Fixation Position X (deg)": 0.0,
    "Fixation Position Y (deg)": 0.0, "Fixation Point Radius (deg)": 0.2,
    "Fix Window Radius (deg)": 1.0,
    "Fixation Duration Min (ms)": 300.0, "Fixation Duration Max (ms)": 500.0,
    "Gap Duration (ms)": 100.0, "Control window radius (deg)": 1.0,
    "Control hold (ms)": 50.0, "Saccade threshold (deg)": 0.75,
    "Response after stim (ms)": 300.0,
    "Reward electrical nofix_2": True, "Reward Length (s)": 0.5,
    "ITI (s)": 3.0, "Timeout (s)": 0.5,
    "Viewing Distance (cm)": 60.0, "Subject Monitor Width (cm)": 54.0,
    "Subject Monitor Height (cm)": 30.0,
    "Intan address": "tcp://127.0.0.1:5000",
    "Intan channels": "A-000:A-031,B-000:B-031,C-000:C-031,D-000:D-031",
}


def bounds(p):
    return tuple(float(p[f"RF {name} (deg)"]) for name in ("x_min", "x_max", "y_min", "y_max"))


def session_eyelink_raw_settings(source, destination):
    """Snapshot the user's RAW calibration configuration without changing it."""
    source, destination = Path(source), Path(destination)
    settings = json.loads(source.read_text(encoding="utf-8"))
    # This task uses RAW locally even when other tasks use global GAZE.
    # Never interpret a GAZE calibration file as RAW pupil coefficients.
    if settings.get("sample_source", "").lower() == "raw":
        calibration = Path(settings.get("calibration_file", "eyelink_raw_pupil_setting.json"))
    else:
        calibration = source.parent / "eyelink_raw_pupil_setting.json"
    if not calibration.is_absolute():
        calibration = source.parent / calibration
    calibration_snapshot = destination.parent / "eyelink_raw_calibration_snapshot.json"
    calibration_snapshot.write_text(calibration.read_text(encoding="utf-8"), encoding="utf-8")
    settings.update(sample_source="raw", active_eye="right",
                    calibration_file=str(calibration_snapshot.resolve()),
                    notes="Intan saccade task: RAW right-eye pupil coordinates with the existing affine calibration. Native ENDSACC provides timing only.")
    destination.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(destination)


LOCKED_RUNTIME_PARAMS = {
    "Subject ID", "Simulate stimulation", "Random seed",
    "Intan address", "Intan channels", "Viewing Distance (cm)", "Subject Monitor Width (cm)",
    "Subject Monitor Height (cm)",
    *(f"RF {name} (deg)" for name in ("x_min", "x_max", "y_min", "y_max")),
}


def validate_runtime(candidate, current):
    for key in LOCKED_RUNTIME_PARAMS:
        if candidate[key] != current[key]:
            raise ValueError(f"{key} is locked during this session")
    validate(candidate)


def validate(p):
    for key, default in DEFAULTS.items():
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            if not math.isfinite(float(p[key])):
                raise ValueError(f"{key}: finite number required")
    for key in ("Random seed", "Control calibrated level"):
        if int(p[key]) != float(p[key]):
            raise ValueError(f"{key}: integer required")
    make_plan(0, int(p["Random seed"]), bounds(p), p["Intan channels"], repeats=1)
    for key in ("Wait Time (s)", "Fixation Duration Min (ms)",
                "Fix Window Radius (deg)", "Fixation Point Radius (deg)",
                "Target diameter (deg)", "Control window radius (deg)",
                "Control hold (ms)", "Saccade threshold (deg)",
                "Viewing Distance (cm)", "Subject Monitor Width (cm)",
                "Subject Monitor Height (cm)"):
        if float(p[key]) <= 0:
            raise ValueError(f"{key} must be positive")
    for key in ("Gap Duration (ms)", "Response after stim (ms)", "Reward Length (s)", "Timeout (s)"):
        if float(p[key]) < 0:
            raise ValueError(f"{key} cannot be negative")
    if float(p["ITI (s)"]) < 2.0:
        raise ValueError("ITI (s) must be at least 2 s to clear and prepare during ITI")
    if p["Fixation Duration Max (ms)"] < p["Fixation Duration Min (ms)"]:
        raise ValueError("Fixation maximum must be >= minimum")
    if p["Control hold (ms)"] > WAVEFORM["nominal_train_ms"] + p["Response after stim (ms)"]:
        raise ValueError("Control hold exceeds response window")
    if not 0 <= p["Control calibrated level"] <= 182:
        raise ValueError("White calibration level must be 0..182")
    x0, x1, y0, y1 = bounds(p)
    for lo, hi, center, cm in ((x0, x1, p["Fixation Position X (deg)"], p["Subject Monitor Width (cm)"]),
                                (y0, y1, p["Fixation Position Y (deg)"], p["Subject Monitor Height (cm)"])):
        limit = math.degrees(math.atan(cm / 2 / p["Viewing Distance (cm)"]))
        if max(abs(center+lo), abs(center+hi)) + p["Target diameter (deg)"]/2 >= limit:
            raise ValueError("RF rectangle/target extends beyond subject screen")


class Journal:
    def __init__(self, path):
        self.file = open(path, "w", encoding="utf-8", buffering=1)
    def write(self, row):
        self.file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    def close(self):
        self.file.close()


def export_trials(path):
    """Flatten attempt summaries for MATLAB/Excel, preserving nested event JSON."""
    if not path.exists():
        return
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return
    for row in rows:
        s = row.get("saccade") or {}
        for key in ("start_eyelink", "end_eyelink", "amplitude_deg"):
            row["saccade_"+key] = s.get(key)
        end = s.get("end_deg") or [None, None]
        row["saccade_end_x_deg"], row["saccade_end_y_deg"] = end
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict,list,tuple)) else value
                             for key, value in row.items()})


class EyeEvents:
    def __init__(self, backend, p, journal, sample_journal=None):
        self.backend, self.p, self.log = backend, p, journal
        self.tracker = backend._tracker
        self.api = backend._pylink
        self.raw = backend.sample_source == "raw"
        if backend.sample_source not in ("raw", "gaze"):
            raise ValueError("Unsupported EyeLink coordinate source; use RAW pupil + affine calibration.")
        self.sample_log = sample_journal
        self.raw_samples = deque(maxlen=10000)
        self.pending_saccades = []
        if self.raw:
            self.raw_calibration = backend._gaze_source.get_calibration_right()
            if not all(math.isfinite(float(self.raw_calibration[k]))
                       for k in ("ox", "oy", "gx", "gy", "gxy", "gyx")):
                raise ValueError("RAW right-eye affine calibration must contain finite coefficients.")
        event_fields = "HREF,VELOCITY,STATUS" if self.raw else "GAZE,GAZERES,HREF,VELOCITY,STATUS"
        for command in ("link_event_data = "+event_fields,
                        "file_event_data = "+event_fields,
                        "select_parser_configuration = 0"):
            reply = self.tracker.sendCommand(command)
            if reply not in (None, 0):
                raise RuntimeError(f"EyeLink rejected {command}: {reply}")
        self.offset_ms = 0

    def raw_sample(self, sample, attempt):
        timestamp = float(sample.getTime())
        eye = sample.getRightEye() if sample.isBinocular() or sample.isRightSample() else None
        pair = eye.getRawPupil() if eye is not None else None
        valid = bool(pair is not None and self.backend._is_valid_pair(pair))
        point = None
        if valid:
            x, y = map(float, pair)
            c = self.raw_calibration
            cx = c['ox']+c['gx']*x+c['gxy']*y
            cy = c['oy']+c['gyx']*x+c['gy']*y
            point = (cx+960, 540-cy)  # calibrated center -> top-left screen pixels
            valid = all(math.isfinite(v) for v in point)
        row = dict(attempt=attempt, sample_eyelink_ms=timestamp, valid=valid,
                   calibration_revision=getattr(self, 'calibration_revision', 0),
                   raw_pupil=list(pair) if pair is not None and valid else None,
                   screen_px=list(point) if valid else None)
        if self.raw_samples and timestamp <= self.raw_samples[-1]['sample_eyelink_ms']:
            if timestamp < self.raw_samples[-1]['sample_eyelink_ms']:
                raise RuntimeError("EyeLink RAW sample timestamps moved backwards")
            return
        self.raw_samples.append(row)
        if self.sample_log:
            self.sample_log.write(row)

    def finish_raw_saccades(self):
        result, pending = [], []
        samples = list(self.raw_samples)
        latest = samples[-1]['sample_eyelink_ms'] if samples else -1
        for event in self.pending_saccades:
            if latest < event['end_eyelink'] and time.perf_counter()-event['received_pc'] < .15:
                pending.append(event)
                continue
            # Require actual RAW samples near both boundaries; never substitute
            # Host GAZE endpoints when a pupil sample is missing or a blink occurs.
            def endpoint(t):
                near = min(samples, key=lambda s: abs(s['sample_eyelink_ms']-t)) if samples else None
                return near if near and near['valid'] and abs(near['sample_eyelink_ms']-t) <= 2 else None
            start, end = endpoint(event['start_eyelink']), endpoint(event['end_eyelink'])
            interval = [s for s in samples if event['start_eyelink'] <= s['sample_eyelink_ms'] <= event['end_eyelink']]
            valid = bool(start and end and interval and all(s['valid'] for s in interval)
                         and event['eye'] == 1)
            sd = ed = None
            if valid:
                size = (self.p['Subject Monitor Width (cm)'], self.p['Subject Monitor Height (cm)'])
                sd = gaze_degrees(start['screen_px'], (1920,1080), size, self.p['Viewing Distance (cm)'])
                ed = gaze_degrees(end['screen_px'], (1920,1080), size, self.p['Viewing Distance (cm)'])
            event.update(valid=valid, start_px=start['screen_px'] if start else None,
                         end_px=end['screen_px'] if end else None, start_deg=sd, end_deg=ed,
                         amplitude_deg=math.dist(sd, ed) if valid else None,
                         start_sample_eyelink=start['sample_eyelink_ms'] if start else None,
                         end_sample_eyelink=end['sample_eyelink_ms'] if end else None,
                         source='EyeLink_ENDSACC_RAW_affine', peak_velocity_deg_s=None,
                         invalid_reason=None if valid else 'missing_or_invalid_RAW_samples')
            self.log.write(event)
            result.append(event)
        self.pending_saccades = pending
        return result

    def synchronize(self):
        readings = []
        for _ in range(5):
            a = time.perf_counter()
            tracker_ms = self.tracker.trackerTime()
            b = time.perf_counter()
            readings.append((b-a, tracker_ms-(a+b)*500))
        rtt, self.offset_ms = min(readings)
        return {"clock_offset_ms": self.offset_ms, "clock_query_rtt_ms": rtt*1000}

    def tracker_ms(self, pc):
        return pc*1000 + self.offset_ms

    def discard_pause_data(self, timeout=10):
        """Discard only link data accumulated outside trials; EDF stays recording."""
        start = time.perf_counter()
        self.raw_samples.clear()
        self.pending_saccades.clear()
        items = lost = 0
        while True:
            kind = self.tracker.getNextData()
            if not kind:
                return dict(discarded_items=items, lost_data_markers=lost,
                            elapsed_s=time.perf_counter()-start)
            items += 1
            lost += int(kind == getattr(self.api, "LOST_DATA_EVENT", 0x3F))
            if items % 1000 == 0 and time.perf_counter()-start > timeout:
                raise RuntimeError("EyeLink pause queue could not be cleared; no trial resumed")

    def pump_pause_data(self):
        """Service the ordered link on the UI thread; pause data stay in EDF."""
        for _ in range(20000):
            kind = self.tracker.getNextData()
            if not kind:
                return
            # Advance library conversion state even for unwanted pause data.
            if kind == getattr(self.api, "SAMPLE_TYPE", 200):
                self.tracker.getFloatData()
        raise RuntimeError("EyeLink pause queue could not be serviced promptly.")

    def recover_after_pause(self, timeout=10, max_age_ms=50):
        """Reset SDK link buffers and verify newly received samples are current."""
        self.raw_samples.clear()
        self.pending_saccades.clear()
        self.tracker.resetData()
        result = self.tracker.dataSwitch(
            self.api.RECORD_LINK_SAMPLES | self.api.RECORD_LINK_EVENTS)
        if result not in (None, 0):
            raise RuntimeError(f"EyeLink link reception restart failed: {result}")
        start = time.perf_counter()
        cutoff = float(self.tracker.trackerTime())
        latest = None
        stable_since = None
        discarded = 0
        lag = None
        while time.perf_counter()-start < timeout:
            for _ in range(20000):
                kind = self.tracker.getNextData()
                if not kind:
                    break
                discarded += 1
                if kind == getattr(self.api, "SAMPLE_TYPE", 200):
                    sample = self.tracker.getFloatData()
                    if sample is not None:
                        latest = float(sample.getTime())
            newest = self.tracker.getNewestSample()
            now_tracker = float(self.tracker.trackerTime())
            if newest is not None and latest is not None:
                newest_ms = float(newest.getTime())
                lag = max(now_tracker-latest, newest_ms-latest)
                fresh = latest >= cutoff and -max_age_ms <= lag <= max_age_ms
            else:
                fresh = False
            now = time.perf_counter()
            if fresh:
                if stable_since is None:
                    stable_since = now
                if now-stable_since >= .1:
                    self.backend._last_sample_time = None
                    return dict(discarded_items=discarded, elapsed_s=now-start,
                                queue_sample_eyelink_ms=latest,
                                newest_sample_eyelink_ms=newest_ms,
                                queue_lag_ms=lag, sdk_link_reset=True)
            else:
                stable_since = None
            time.sleep(.005)
        raise RuntimeError(
            f"EyeLink ordered link did not recover after pause (lag={lag} ms). "
            "No new trial started; check link/recording and restart the task.")

    def drain(self, attempt):
        result = []
        for _ in range(20000):
            kind = self.tracker.getNextData()
            if not kind:
                if self.raw and self.raw_samples:
                    newest = self.tracker.getNewestSample()
                    if newest is not None:
                        lag = float(newest.getTime())-self.raw_samples[-1]["sample_eyelink_ms"]
                        if lag > 500:
                            raise RuntimeError(
                                f"EyeLink ordered samples lag newest sample by {lag:.1f} ms; "
                                "event timing is unreliable. Stop rather than classify behavior.")
                return result + (self.finish_raw_saccades() if self.raw else [])
            if kind == getattr(self.api, "LOST_DATA_EVENT", 0x3F):
                raise RuntimeError("EyeLink link queue lost data; stop and inspect EDF")
            if self.raw and kind == getattr(self.api, 'SAMPLE_TYPE', 200):
                self.raw_sample(self.tracker.getFloatData(), attempt)
                continue
            if kind != self.api.ENDSACC:
                continue
            e = self.tracker.getFloatData()
            if self.raw:
                self.pending_saccades.append(dict(attempt=attempt, eye=e.getEye(),
                    start_eyelink=e.getStartTime(), end_eyelink=e.getEndTime(),
                    status_flags=e.getStatus(), received_pc=time.perf_counter()))
                continue
            start, end = e.getStartGaze(), e.getEndGaze()
            valid = all(math.isfinite(v) and abs(v) < 32000 for v in (*start, *end))
            sd = gaze_degrees(start, (1920, 1080),
                (self.p["Subject Monitor Width (cm)"], self.p["Subject Monitor Height (cm)"]),
                self.p["Viewing Distance (cm)"]) if valid else (None, None)
            ed = gaze_degrees(end, (1920, 1080),
                (self.p["Subject Monitor Width (cm)"], self.p["Subject Monitor Height (cm)"]),
                self.p["Viewing Distance (cm)"]) if valid else (None, None)
            row = dict(attempt=attempt, eye=e.getEye(), start_eyelink=e.getStartTime(),
                       end_eyelink=e.getEndTime(), start_px=list(start) if valid else None,
                       end_px=list(end) if valid else None, start_deg=sd, end_deg=ed,
                       amplitude_deg=math.dist(sd, ed) if valid else None,
                       valid=valid, received_pc=time.perf_counter(),
                       source="EyeLink_ENDSACC")
            row["status_flags"] = e.getStatus()
            peak = e.getPeakVelocity()
            row["peak_velocity_deg_s"] = peak if math.isfinite(peak) else None
            self.log.write(row)
            result.append(row)
        raise RuntimeError("EyeLink queue backlog exceeds 20000 items")


def launch(args):
    from psychopy import visual, event
    from FineVision_Notebook import FineVision_Notebook
    from SessionNaming import confirm_session_parameters, subject_filename
    from SaccadeTask import SaccadeTask, DEFAULT_PARAMS as BASE, TaskAbort
    from DisplayCalibration import load_calibrated_gray_level, rgb255_to_psychopy
    from SaccadeMultiStimTask import _load_calibration
    from GazeTrackerRenderer import GazeTrackerRenderer
    from FineVision_Util import ArduinoController
    from eyetracker import create_tracker_runtime

    manager = FineVision_Notebook(task_name="Saccade_Elec_stim_Eyelink_Intan",
        default_params=DEFAULTS, parameter_validator=validate)
    if not confirm_session_parameters(manager):
        return
    p = dict(manager.exp_params)
    if args.mouse:
        p["Simulate stimulation"] = True
    validate(p)
    plan = make_plan(0, int(p["Random seed"]), bounds(p), p["Intan channels"], repeats=1)
    stamp = subject_filename(p["Subject ID"]) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = ROOT / "experiment_logs" / ("Saccade_Elec_Intan_" + stamp)
    out.mkdir(parents=True)
    background = load_calibrated_gray_level(5)
    background_color = rgb255_to_psychopy(background["rgb_255"])
    calibration = _load_calibration()
    level = int(p["Control calibrated level"])
    rgb = calibration["rgb_by_color"]["Gray"][level]
    (out / "session.json").write_text(json.dumps(dict(parameters=p, waveform=WAVEFORM,
        stimulation_marker=dict(output="DIGITAL-OUT-01", recording_input="DIGITAL-IN-02",
            enabled=not p["Simulate stimulation"], period_ms=1, high_ms=0.5,
            pulses=164, last_falling_edge_ms=163.5,
            electrical_last_phase_end_ms=WAVEFORM["last_phase_end_ms"],
            trigger="KeyPressF1_shared_with_electrode", hardware_timing_verified=False),
        calibration=calibration, background=background, mouse=args.mouse, endpoint_frame="screen_center_deg",
        onset_reference="display_flip_simulation_or_Intan_command_dispatch",
        log_schema_version=4, recording_continuous=False,
        response_timing_policy="received_and_qualified_by_deadline_no_grace",
        acquisition_note="RHX stops during ITI parameter uploads; see intan_acquisition.jsonl", timestamp_units=dict(pc="seconds", eyelink="milliseconds"),
        fixation_photodiode_cycles=10, stimulus_duration_s=WAVEFORM["nominal_train_ms"]/1000,
        photodiode_size_px=160,
        photodiode_inset_px=10, photodiode_corner="bottom_right"), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    class Task(SaccadeTask):
        def _to_x_pixels(self, angle_deg):
            return math.tan(math.radians(angle_deg))*self.viewing_distance_cm/self.monitor_width_cm*self.win_sub.size[0]

        def _to_y_pixels(self, angle_deg):
            return math.tan(math.radians(angle_deg))*self.viewing_distance_cm/self.monitor_height_cm*self.win_sub.size[1]

        def __init__(self, backend, sub, ctl):
            self.win_sub, self.win_ctl = sub, ctl
            self.tracker_backend = backend
            self.session_t0 = time.perf_counter()
            self.scale_x, self.scale_y = ctl.size[0]/sub.size[0], ctl.size[1]/sub.size[1]
            self.gaze_renderer = GazeTrackerRenderer(ctl, backend.gaze_source,
                self.scale_x, self.scale_y, args.mouse)
            self.arduino = None if args.mouse else ArduinoController()
            self.events_log = Journal(out / "events.jsonl")
            self.sacc_log = Journal(out / "saccades.jsonl")
            self.trials_log = Journal(out / "trials.jsonl")
            self.frames_log = Journal(out / "frames.jsonl")
            self.raw_gaze_log = Journal(out / "raw_gaze_samples.jsonl")
            self.reader = None if args.mouse else EyeEvents(backend, p, self.sacc_log, self.raw_gaze_log)
            self.worker = None if p["Simulate stimulation"] else IntanWorker(p["Intan address"], p["Intan channels"], out / "intan_acquisition.jsonl")
            self.control_level, self.control_rgb = int(p["Control calibrated level"]), rgb
            bp = dict(BASE)
            bp.update({k: v for k, v in p.items() if k in bp})
            bp.update({"Fixation Acquire Time (ms)": 1, "Stim Hold Time (ms)": p["Control hold (ms)"],
                "Stim Duration (ms)": WAVEFORM["nominal_train_ms"],
                "Stim Major Axis (deg)": p["Target diameter (deg)"],
                "Stim Minor Axis (deg)": p["Target diameter (deg)"],
                "Stim Window Radius (deg)": p["Control window radius (deg)"]})
            self.task_manager = SimpleNamespace(exp_params=bp)
            self.update_params()
            self.pd = visual.Rect(sub, width=160, height=160, units="pix",
                pos=(sub.size[0]/2 - 90, -sub.size[1]/2 + 90),
                colorSpace="rgb255", fillColor=(255, 255, 255),
                lineColor=(255, 255, 255), autoLog=False)
            self.info = visual.TextStim(ctl, pos=(0, 195), height=16, color="white")
            self.frame_id = 0
            self.attempt = 0
            self.condition_attempts = {}
            self.row = None
            self.pending_events = []
            self.fix_pd = 0
            self.last_pd = False
            self.pause = False
            self.paused = False
            self.edit_requested = False
            self.parameter_revision = 0
            self.trigger = None
            self.refresh = sub.getActualFrameRate(nIdentical=10, nMaxFrames=120)
            if not self.refresh:
                raise RuntimeError("Cannot measure stable display refresh rate")
            # Refresh is diagnostic only. Task timing uses elapsed PC time.
            if self.reader:
                self.reader.synchronize()
            self.mark("SESSION", refresh_hz=self.refresh, fixation_pd_cycles=10,
                      stimulus_duration_s=WAVEFORM["nominal_train_ms"]/1000)

        def mark(self, label, pc=None, **data):
            recorded_pc = time.perf_counter()
            pc = recorded_pc if pc is None else pc
            row = dict(event=label, attempt=self.attempt, event_pc=pc, recorded_pc=recorded_pc,
                       session_elapsed_s=pc-self.session_t0, **data)
            if self.reader:
                row["event_eyelink_est"] = self.reader.tracker_ms(pc)
            self.events_log.write(row)
            # Explicit PC event time remains recoverable even if message is delayed.
            message = (f"{label} ATTEMPT {self.attempt} PC {pc:.6f} "
                       f"EL_EST {row.get('event_eyelink_est', -1):.3f}")
            self.tracker_backend.send_event(message)
            # Keep every EDF message below the SDK text limit. Full structured
            # metadata lives in events.jsonl and is mirrored in numbered chunks.
            if data:
                payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
                for i in range(0, len(payload), 160):
                    self.tracker_backend.send_event(f"META {label} A {self.attempt} PART {i//160} {payload[i:i+160]}")
            return pc

        def frame(self, fix=False, stim=False, stim_pd=False, marks=(), callback=None, acquire_fix=False):
            if self.reader:
                if self.reader.tracker.isRecording() != 0:
                    raise RuntimeError("EyeLink is not recording")
                self.pending_events.extend(self.reader.drain(self.attempt))
            gaze = self.gaze_renderer.update()
            sample_eyelink = None if args.mouse else gaze.get("timestamp")
            if sample_eyelink is not None:
                sample_eyelink *= 1000
            if acquire_fix and "fixon_pc" not in self.row and self.in_fix(gaze):
                detected = time.perf_counter()
                self.row.update(fixation_detected_pc=detected, fixation_enter_sample_eyelink=sample_eyelink,
                                fixation_pd_cycles=10, fixation_pd_cycles_completed=0)
                self.row["fixon_pc"] = self.mark("FIXON", pc=detected,
                    fixation_enter_sample_eyelink=sample_eyelink, gaze_x=gaze["x"], gaze_y=gaze["y"])
                self.fix_pd = 10
            self.gaze_renderer.draw()
            if fix:
                self.fix_sub.draw()
                self.fix_ctl.draw()
            if stim:
                self.stim_sub.draw()
                self.stim_ctl.draw()
            if fix or self.fix_pd:
                self.fix_window_ctl.draw()
            if self.row and self.row["kind"] != "stim":
                self.stim_window_ctl.draw()
            pd_on = bool(stim_pd or self.fix_pd)
            if pd_on:
                self.pd.draw()
            self.info.text = f"Plan {self.row['plan_id'] if self.row else '-'} / {len(plan)}   Attempt {self.attempt}\n" + (
                f"{self.row['kind']}  HW {self.row.get('hw', '-')}  {self.row.get('current_uA', '-')} uA" if self.row else "")
            self.info.text += ("\nPAUSED — N: edit / Space: continue" if self.paused
                               else "\nN: edit / Space: pause / Esc: stop")
            self.info.draw()
            def flipped():
                pc = time.perf_counter()
                self.flip_pc = pc
                for label in marks:
                    self.mark(label, pc=pc, frame=self.frame_id)
                if pd_on != self.last_pd:
                    self.mark("PD_ON" if pd_on else "PD_OFF", pc=pc, frame=self.frame_id)
                    if self.row and not stim_pd and "stimon_pc" not in self.row:
                        self.row["fixation_pd_on_pc" if pd_on else "fixation_pd_off_pc"] = pc
                        if not pd_on and "fixation_pd_on_pc" in self.row:
                            self.row["fixation_pd_actual_s"] = pc-self.row["fixation_pd_on_pc"]
                if self.row and self.fix_pd > 0 and not stim_pd:
                    self.row["fixation_pd_cycles_completed"] += 1
                if callback:
                    callback(pc)
            self.win_sub.callOnFlip(flipped)
            self.win_sub.flip()
            self.win_ctl.flip()
            self.frames_log.write(dict(attempt=self.attempt, frame=self.frame_id, flip_pc=self.flip_pc,
                gaze_sample_eyelink=sample_eyelink,
                fix=fix, stim=stim, pd=pd_on, gaze_x=gaze["x"], gaze_y=gaze["y"], valid=bool(gaze["valid"])))
            self.last_pd = pd_on
            self.frame_id += 1
            self.fix_pd = max(0, self.fix_pd-1)
            keys = event.getKeys()
            if "escape" in keys:
                raise TaskAbort()
            if "n" in keys:
                self.edit_requested = True
                self.pause = True
            elif "space" in keys:
                if self.paused:
                    self.paused = False
                else:
                    self.pause = True
            return gaze

        def edit_runtime_parameters(self):
            self.edit_requested = False
            manager.exp_params.clear()
            manager.exp_params.update(p)
            action = manager.prompt_for_runtime_parameters(
                disabled_parameters=LOCKED_RUNTIME_PARAMS,
                parameter_validator=lambda candidate: validate_runtime(candidate, p),
                allow_recalibration=bool(self.reader and self.reader.raw),
                idle_callback=self.reader.pump_pause_data if self.reader else None,
                title="Saccade electrical stimulation / 运行中参数",
                notice="Confirm to continue. Cancel ends and saves the session. "
                       "Gray fields preserve the stimulation plan and hardware connection.")
            # The modal editor blocks frame()/drain() while EyeLink keeps recording.
            # These are pause events, never events belonging to the next trial.
            if self.reader:
                discarded = self.reader.recover_after_pause() if self.reader.raw else self.reader.discard_pause_data()
                clock = self.reader.synchronize()
                self.mark("PAUSE_LINK_QUEUE_CLEARED", **discarded, **clock)
            if action == "cancel":
                self.mark("PARAMETER_EDIT_CANCELLED")
                raise TaskAbort()
            updated = dict(manager.exp_params)
            validate_runtime(updated, p)
            changes = {key: dict(old=p[key], new=updated[key]) for key in p
                       if p[key] != updated[key]}
            p.update(updated)
            bp = dict(BASE)
            bp.update({k: v for k, v in p.items() if k in bp})
            bp.update({"Fixation Acquire Time (ms)": 1,
                "Stim Hold Time (ms)": p["Control hold (ms)"],
                "Stim Duration (ms)": WAVEFORM["nominal_train_ms"],
                "Stim Major Axis (deg)": p["Target diameter (deg)"],
                "Stim Minor Axis (deg)": p["Target diameter (deg)"],
                "Stim Window Radius (deg)": p["Control window radius (deg)"]})
            self.task_manager.exp_params = bp
            self.update_params()
            self.control_level = int(p["Control calibrated level"])
            self.control_rgb = calibration["rgb_by_color"]["Gray"][self.control_level]
            self.parameter_revision += 1
            self.pending_events.clear()
            self.mark("PARAMETERS_UPDATED", revision=self.parameter_revision,
                      changes=changes, parameters=dict(p))
            event.clearEvents()
            if action == 'recalibrate':
                self.recalibrate_four_points()
            else:
                self.paused = False

        def recalibrate_four_points(self):
            from InSessionRawCalibration import run_four_point_calibration
            revision = getattr(self.reader, 'calibration_revision', 0) + 1
            folder = out / f'raw_recalibration_{time.time_ns()}'
            self.pending_events.clear()
            self.gaze_renderer.reset_trail()
            self.mark('RAW_RECALIBRATION_START', revision=revision, directory=str(folder))
            try:
                changed = run_four_point_calibration(backend=self.tracker_backend, reader=self.reader,
                    subject_win=self.win_sub, control_win=self.win_ctl, arduino=self.arduino,
                    params=p, log_dir=folder, active_path=ROOT/'eyelink_raw_pupil_setting.json')
                if changed:
                    self.reader.calibration_revision = revision
                    self.mark('RAW_RECALIBRATION_APPLIED', revision=revision,
                        coefficients=self.reader.raw_calibration, directory=str(folder))
                else:
                    self.mark('RAW_RECALIBRATION_CANCELLED', directory=str(folder))
            finally:
                cleared = self.reader.recover_after_pause() if self.reader.raw else self.reader.discard_pause_data()
                clock = self.reader.synchronize()
                self.pending_events.clear()
                self.gaze_renderer.reset_trail()
                self.mark('RAW_RECALIBRATION_END', **cleared, **clock)
                event.clearEvents()
            self.paused = False
            self.mark('AUTO_RESUME_AFTER_RAW_RECALIBRATION')

        def wait_job(self, job, timeout=90):
            start = time.perf_counter()
            while not job["done"]:
                self.frame()
                self.pending_events.clear()
                if time.perf_counter()-start > timeout:
                    raise RuntimeError("Intan command timed out; stimulation state uncertain; no retry")
            if "error" in job:
                raise RuntimeError(job["error"])

        def delay(self, seconds):
            end = time.perf_counter()+seconds
            while time.perf_counter() < end:
                self.frame()
                self.pending_events.clear()

        def in_fix(self, g):
            return self._in_window(g, self.fix_x_px, self.fix_y_px, self.fix_radius_px)

        def run_attempt(self, condition):
            self.trial_active = True
            self.attempt += 1
            key = condition["plan_id"]
            self.condition_attempts[key] = self.condition_attempts.get(key, 0)+1
            self.row = dict(condition, attempt=self.attempt, delivered=False,
                            condition_attempt=self.condition_attempts[key],
                            status="running", reward=False, saccade=None)
            self.row["parameter_revision"] = self.parameter_revision
            self.row['calibration_revision'] = getattr(self.reader, 'calibration_revision', 0)
            self.mark("TRIALID", plan_id=condition["plan_id"], condition=condition)
            if self.reader:
                self.row.update(self.reader.synchronize())
            x = self.fix_x_deg + condition["target_deg"][0]
            y = self.fix_y_deg + condition["target_deg"][1]
            self.stim_x_px, self.stim_y_px = self._to_x_pixels(x), self._to_y_pixels(y)
            self.stim_sub.pos = (self.stim_x_px, self.stim_y_px)
            self.stim_ctl.pos = (self.stim_x_px*self.scale_x, self.stim_y_px*self.scale_y)
            self.stim_window_ctl.pos = self.stim_ctl.pos
            color = [v/127.5-1 for v in (self.control_rgb if condition["kind"] != "stim" else [0, 255, 0])]
            self.stim_sub.fillColor = self.stim_sub.lineColor = color
            self.stim_ctl.fillColor = self.stim_ctl.lineColor = color
            self.row.update(target_screen_deg=[x, y], control_rgb=self.control_rgb,
                control_luminance=calibration["target_luminance_cd_m2_by_color"]["Gray"][self.control_level])
            self.pending_events.clear()
            self.fix_pd = 0
            self.gaze_renderer.reset_trail()
            if self.arduino:
                self.arduino.trial_start()
            # The initial display flip establishes the onset before acquisition.
            g = self.frame(fix=True, marks=("FIXPOINT_ON",))
            wait_start = self.flip_pc
            self.row["fixpoint_on_pc"] = wait_start
            while "fixon_pc" not in self.row:
                if time.perf_counter()-wait_start >= p["Wait Time (s)"]:
                    return "nofix"
                g = self.frame(fix=True, acquire_fix=True)
                self.pending_events.clear()
            acquired = self.row["fixon_pc"]
            hold = random.uniform(p["Fixation Duration Min (ms)"], p["Fixation Duration Max (ms)"])/1000
            self.row["fixation_hold_s"] = hold
            self.row["fixoff_deadline_pc"] = acquired + hold
            while time.perf_counter() < self.row["fixoff_deadline_pc"]:
                if not self.in_fix(g):
                    return "break_1"
                g = self.frame(fix=True)
                self.pending_events.clear()
                if not self.in_fix(g):
                    return "break_1"
            g = self.frame(marks=("FIXOFF",))
            self.row["fixoff_pc"] = self.flip_pc
            self.row["fixation_hold_actual_s"] = self.flip_pc - acquired
            self.row["fixation_hold_overrun_s"] = max(0., self.flip_pc-self.row["fixoff_deadline_pc"])
            gap_start = self.flip_pc
            self.row["gap_deadline_pc"] = gap_start + p["Gap Duration (ms)"]/1000
            while True:
                if not self.in_fix(g):
                    return "break_1"
                # A short hold may leave some of the ten PD cycles in the gap.
                # Finish the pulse and its OFF flip before starting stimulus PD.
                if time.perf_counter() >= self.row["gap_deadline_pc"] and not self.fix_pd and not self.last_pd:
                    break
                g = self.frame()
                self.pending_events.clear()
            # Drain rather than resetting recording; EDF remains continuous.
            if self.reader:
                self.reader.drain(self.attempt)
            self.pending_events.clear()
            return self.response(condition, g)

        def response(self, condition, initial_gaze):
            self.row["response_timing_policy"] = "received_and_qualified_by_deadline_no_grace"
            control = condition["kind"] != "stim"
            self.row["response_success_criterion"] = (
                "target_window_hold_only" if control else "qualified_saccade")
            visible = control or p["Simulate stimulation"]
            self.trigger = None
            def onset(pc):
                self.row["stimon_pc"] = pc
                self.row["gap_actual_s"] = pc-self.row["fixoff_pc"] if "fixoff_pc" in self.row else None
                self.row["gap_overrun_s"] = max(0., pc-self.row["gap_deadline_pc"]) if "gap_deadline_pc" in self.row else None
                self.row["stimoff_deadline_pc"] = pc + WAVEFORM["nominal_train_ms"]/1000
                if not control:
                    self.row["delivered"] = True
                if self.worker and not control:
                    self.trigger = self.worker.submit("trigger", condition)
            self.frame(stim=visible, stim_pd=True, marks=("STIMON",), callback=onset)
            onset_pc = self.row["stimon_pc"]
            onset_ref = onset_pc
            off_pc = None
            deadline_pc = None
            hold_start = None
            acquired = False
            held = False
            broken = False
            accepted = None
            candidates = []
            mouse_start = (initial_gaze["x"]+960, 540-initial_gaze["y"])
            while True:
                if self.trigger and "command_pc" in self.trigger:
                    onset_ref = self.trigger["command_pc"]
                    if "stim_command_pc" not in self.row:
                        self.row["stim_command_pc"] = onset_ref
                        self.mark("STIM_COMMAND", pc=onset_ref, hardware_onset_verified=False)
                if self.trigger and self.trigger.get("done") and self.trigger.get("error"):
                    raise RuntimeError(self.trigger["error"])
                if self.trigger and "command_pc" not in self.trigger and time.perf_counter()-onset_pc > 10:
                    raise RuntimeError("Stimulation dispatch timed out; no automatic retry")
                show = time.perf_counter() < self.row["stimoff_deadline_pc"]
                marks = ("STIMOFF",) if not show and off_pc is None else ()
                g = self.frame(stim=visible and show, stim_pd=show, marks=marks)
                if marks:
                    off_pc = self.flip_pc
                    self.row["stimoff_pc"] = off_pc
                    self.row["stimulus_display_actual_s"] = off_pc-onset_pc
                # Visual condition follows actual display offset. Electrical
                # condition uses command dispatch + nominal train duration.
                if self.worker and not control and self.trigger and "command_pc" in self.trigger:
                    deadline_pc = onset_ref + (WAVEFORM["nominal_train_ms"] + p["Response after stim (ms)"])/1000
                    self.row["response_deadline_reference"] = "stim_command_pc_plus_nominal_train"
                elif not (self.worker and not control) and off_pc is not None:
                    deadline_pc = off_pc + p["Response after stim (ms)"]/1000
                    self.row["response_deadline_reference"] = "stimoff_pc"
                if deadline_pc is not None:
                    self.row["response_deadline_pc"] = deadline_pc
                candidates.extend(self.pending_events)
                self.pending_events.clear()
                now = time.perf_counter()
                if args.mouse and g["valid"]:
                    end = (g["x"]+960, 540-g["y"])
                    sd = gaze_degrees(mouse_start, (1920,1080), (self.monitor_width_cm,self.monitor_height_cm), self.viewing_distance_cm)
                    ed = gaze_degrees(end, (1920,1080), (self.monitor_width_cm,self.monitor_height_cm), self.viewing_distance_cm)
                    if math.dist(sd, ed) > p["Saccade threshold (deg)"]:
                        candidates.append(dict(valid=True, eye=1, start_pc=now, end_pc=now,
                            start_deg=sd, end_deg=ed, start_px=mouse_start, end_px=end,
                            amplitude_deg=math.dist(sd, ed), source="mouse_displacement_mock"))
                        mouse_start = end
                to_ms = self.reader.tracker_ms if self.reader else lambda pc: pc*1000
                # Before visual offset, the eventual deadline cannot be earlier
                # than the current time. Keep receiving events from STIMON.
                candidate_deadline = deadline_pc if deadline_pc is not None else now
                ready = not (self.worker and not control) or (self.trigger and "command_pc" in self.trigger)
                for s in sorted(candidates if ready and not control else [], key=lambda e: event_time_ms(e, "start")):
                    # Both receipt and qualification must occur by the deadline.
                    # A display frame or RAW reconstruction may finish after it.
                    if deadline_pc is not None and (time.perf_counter() > deadline_pc
                            or s.get("received_pc", now) > deadline_pc):
                        continue
                    if not qualifies(s, to_ms(onset_ref), to_ms(candidate_deadline), p["Saccade threshold (deg)"]):
                        continue
                    if control and math.dist(s["end_deg"], self.row["target_screen_deg"]) > p["Control window radius (deg)"]:
                        continue
                    if accepted is None:
                        qualified_pc = time.perf_counter()
                        if deadline_pc is not None and qualified_pc > deadline_pc:
                            continue
                        accepted = s
                        self.row["saccade_qualified_pc"] = qualified_pc
                # Controls depend only on valid gaze held inside the target.
                # For overlapping targets, gaze already inside at cue onset is
                # eligible; all hold time is measured after target onset.
                if control and (deadline_pc is None or now <= deadline_pc) and not held and not broken:
                    inside = self._in_window(g, self.stim_x_px, self.stim_y_px, self.stim_radius_px)
                    if inside:
                        acquired = True
                        if hold_start is None:
                            hold_start = now
                            self.mark("TARGET_ENTER")
                        if now-hold_start >= p["Control hold (ms)"]/1000:
                            held = True
                    elif hold_start is not None:
                        broken = True
                train_complete = not (self.worker and not control) or (self.trigger and "command_pc" in self.trigger
                    and now >= self.trigger["command_pc"] + WAVEFORM["nominal_train_ms"]/1000)
                if off_pc is not None and train_complete and (
                        (control and held) or (not control and accepted is not None)):
                    if "response_end_pc" not in self.row:
                        self.row["response_end_pc"] = min(now, deadline_pc) if deadline_pc is not None else now
                        self.row["response_end_reason"] = "qualified_saccade" if not control else "target_hold_complete"
                        self.mark("RESPONSE_END", pc=self.row["response_end_pc"], reason=self.row["response_end_reason"])
                    break
                if deadline_pc is not None and now >= deadline_pc and "response_end_pc" not in self.row:
                    self.row["response_end_pc"] = deadline_pc
                    self.row["response_end_reason"] = "deadline"
                    self.mark("RESPONSE_END", pc=deadline_pc, reason="deadline")
                # No additional event-arrival window after the response deadline.
                if off_pc is not None and deadline_pc is not None and now >= deadline_pc:
                    break
            self.row["response_finished_pc"] = time.perf_counter()
            if self.trigger:
                self.wait_job(self.trigger)
                self.row["intan_result"] = dict(self.trigger)
            if accepted:
                self.row["saccade"] = accepted
                self.row["saccade_end_relative_fix_deg"] = [accepted["end_deg"][0]-self.fix_x_deg,
                                                            accepted["end_deg"][1]-self.fix_y_deg]
            if control:
                if broken or (acquired and not held):
                    return "break_2"
                return "success" if held else "nofix_2"
            return "success" if accepted else "nofix_2"

        def finish(self, status):
            self.fix_pd = 0
            self.frame(marks=("TRIAL_BLACKOUT",))
            reward = status == "success" or (self.row["kind"] == "stim" and status == "nofix_2" and p["Reward electrical nofix_2"])
            self.row.update(status=status, reward=bool(reward), end_pc=time.perf_counter())
            if reward:
                self.row["reward_delay_s"] = REWARD_DELAY_S
                self.row["reward_deadline_pc"] = self.row["end_pc"] + REWARD_DELAY_S
                self.mark("REWARD_DELAY_START", delay_s=REWARD_DELAY_S,
                          deadline_pc=self.row["reward_deadline_pc"], reason=status)
                self.delay(max(0., self.row["reward_deadline_pc"]-time.perf_counter()))
                self.row["reward_pc"] = self.mark("REWARD", reason=status)
                if self.arduino:
                    self.arduino.trial_success()
                    self.arduino.reward(round(p["Reward Length (s)"]*1000))
            elif self.arduino:
                if status.startswith("break"):
                    self.arduino.trial_break()
                else:
                    self.arduino.trial_nofix()
            if self.arduino:
                self.arduino.trial_end()
            self.mark("TRIAL_RESULT", status=status)
            # Reward is scheduled asynchronously on Arduino. Treat its expected
            # end, as well as all trial output commands, as protected events.
            reward_end = self.row.get("reward_pc", 0) + (p["Reward Length (s)"] if reward else 0)
            boundary = max(time.perf_counter(), reward_end)
            if time.perf_counter() < boundary:
                self.delay(boundary-time.perf_counter())
            self.row["recording_event_end_pc"] = time.perf_counter()
            self.row["recording_protect_until_pc"] = self.row["recording_event_end_pc"] + RECORD_GUARD_S
            if self.worker:
                self.wait_job(self.worker.submit("protect_trial_tail"))
            self.trial_active = False
            self.trials_log.write(self.row)
            print(f"Plan {self.row['plan_id']}/{len(plan)} attempt {self.attempt}: {status}")
            if status.startswith("break"):
                self.delay(p["Timeout (s)"])

        def run(self):
            if self.worker:
                print("REAL INTAN: RHX must be in Record at 30 kHz / 1 uA step. ITI updates split recording; trials have 1.1 s baseline/tail protection.")
                self.wait_job(self.worker.submit("init"), timeout=60)
                # Startup already cleared and uploaded the detected outputs.
                # Allow the resumed acquisition to settle before the first ITI.
                self.delay(2.0)
            previous_end_pc = time.perf_counter()
            for condition in plan:
                while True:
                    # Old and new waveforms are replaced inside ONE Stop/Record
                    # cycle in ITI. Visual trials do not change hardware settings.
                    # On subsequent trials this starts 1 s after the prior
                    # trial was classified, with at least 1 s remaining.
                    clear_pc = previous_end_pc + RECORD_GUARD_S
                    if time.perf_counter() < clear_pc:
                        self.delay(clear_pc - time.perf_counter())
                    if self.worker:
                        self.wait_job(self.worker.submit("prepare_trial", condition))
                        if condition["kind"] == "stim":
                            self.mark("STIM_CONFIG_REPLACED", backend="Intan",
                                      plan_id=condition["plan_id"], acquisition_restart_count=1)
                            self.mark("STIM_PARAMS_READY", plan_id=condition["plan_id"])
                        else:
                            self.mark("STIM_SOFTWARE_DISARMED", backend="Intan")
                    preparation_done_pc = time.perf_counter()
                    # A long upload must not consume the pretrial baseline.
                    # No trial event is allowed until acquisition has resumed
                    # and a full protection interval has elapsed.
                    iti_end_pc = max(previous_end_pc + p["ITI (s)"],
                                     preparation_done_pc + RECORD_GUARD_S)
                    if time.perf_counter() < iti_end_pc:
                        self.delay(iti_end_pc - time.perf_counter())
                    elif time.perf_counter() > iti_end_pc:
                        self.mark("ITI_EXTENDED_FOR_STIM_PREP", extra_s=time.perf_counter()-iti_end_pc)
                    if self.worker:
                        guard_job = self.worker.submit("verify_trial_recording")
                        self.wait_job(guard_job)
                        self.mark("PRETRIAL_RECORDING_GUARD_PASSED",
                                  seconds=RECORD_GUARD_S, preparation_done_pc=preparation_done_pc,
                                  hardware=guard_job)
                    if self.pause:
                        self.mark("PAUSE")
                        if self.worker:
                            self.wait_job(self.worker.submit("disarm_trial"))
                        event.clearEvents()
                        self.paused = True
                        while self.paused:
                            if self.edit_requested:
                                self.edit_runtime_parameters()
                            else:
                                self.frame()
                            self.pending_events.clear()
                        self.pause = False
                        self.mark("RESUME")
                        # Re-prepare this same condition after a fresh ITI.
                        previous_end_pc = time.perf_counter()
                        continue
                    try:
                        status = self.run_attempt(condition)
                    except BaseException as exc:
                        if self.row:
                            self.row.update(status="aborted", error=repr(exc))
                            if self.trigger:
                                self.row["intan_result"] = dict(self.trigger)
                            self.trials_log.write(self.row)
                        raise
                    self.finish(status)
                    previous_end_pc = self.row.get("recording_event_end_pc", self.row["end_pc"])
                    if advance(condition, status, self.row["delivered"]):
                        break
            self.mark("SESSION_COMPLETE")

        def cleanup(self):
            self.fix_pd = 0
            try:
                # Cleanup must not read the queue that may have caused the failure.
                self.win_sub.flip()
                self.win_ctl.flip()
                self.mark("SESSION_BLACKOUT")
            finally:
                if self.worker:
                    if getattr(self, "trial_active", False):
                        # Esc/error may interrupt a trial. Do not stop neural
                        # acquisition immediately, and do not read a failed
                        # EyeLink queue while preserving the final interval.
                        if self.trigger:
                            deadline = time.perf_counter()+15
                            while not self.trigger.get("done") and time.perf_counter() < deadline:
                                time.sleep(.01)
                            if "command_pc" in self.trigger:
                                train_end = self.trigger["command_pc"] + WAVEFORM["nominal_train_ms"]/1000
                                time.sleep(max(0, train_end-time.perf_counter()))
                        if self.row:
                            reward_end = self.row.get("reward_pc", 0)+p["Reward Length (s)"]
                            time.sleep(max(0, reward_end-time.perf_counter()))
                        tail = self.worker.submit("protect_trial_tail")
                        deadline = time.perf_counter()+15
                        while not tail["done"] and time.perf_counter() < deadline:
                            time.sleep(.01)
                        self.mark("ABORTED_TRIAL_TAIL_PROTECTION_REQUESTED", result=tail)
                    close_job = self.worker.submit("close")
                    self.worker.thread.join(timeout=45)
                    if not close_job["done"] or "error" in close_job:
                        print("Intan cleanup incomplete: check RHX before restarting.", close_job)
                if self.arduino:
                    self.arduino.close()
                for journal in (self.events_log, self.sacc_log, self.trials_log, self.frames_log,
                                getattr(self, "raw_gaze_log", None)):
                    if journal is None:
                        continue
                    journal.close()

    tracker = sub = ctl = task = None
    try:
        eyelink_settings = session_eyelink_raw_settings(ROOT / "eyelink_setting.json",
                                                       out / "eyelink_raw_settings.json")
        if not args.mouse:
            print("EyeLink source: RAW right-eye pupil + existing FineVision affine calibration. Host GAZE endpoints are not used.")
        tracker = create_tracker_runtime("eyelink", is_simulating=args.mouse,
            session_id="SaccadeElec_Intan_"+stamp, save_dir=str(out), screen_size=(1920,1080),
            eyelink_settings_path=eyelink_settings)
        if not args.mouse:
            loaded_calibration = tracker.get_calibration_right()
            expected_calibration = json.loads(
                Path(tracker.calibration_file).read_text(encoding="utf-8"))["default_right_cal"]
            if any(float(loaded_calibration[k]) != float(expected_calibration.get(k, 0.0))
                   for k in ("ox", "oy", "gx", "gy", "gxy", "gyx")):
                raise RuntimeError("Loaded EyeLink RAW calibration differs from the session snapshot.")
            (out / "eyelink_loaded_calibration.json").write_text(json.dumps(
                dict(sample_source=tracker.sample_source, active_eye=tracker.active_eye,
                     calibration_file=tracker.calibration_file,
                     right_eye_coefficients=loaded_calibration), indent=2), encoding="utf-8")
        sub = visual.Window(screen=0 if args.mouse else 1, size=(1920,1080),
            fullscr=False, waitBlanking=True, color=background_color, units="pix", allowGUI=False)
        ctl = visual.Window(screen=0, size=(800,450), fullscr=False, waitBlanking=False,
            color=background_color, units="pix", title="Saccade electrical stimulation — N edit / Space pause / Esc stop")
        task = Task(tracker, sub, ctl)
        task.run()
    except TaskAbort:
        print("Task stopped by operator.")
    finally:
        try:
            if task:
                task.cleanup()
        finally:
            try:
                if tracker:
                    tracker.close()
            finally:
                if sub:
                    sub.close()
                if ctl:
                    ctl.close()
                export_trials(out / "trials.jsonl")
                print("Session files:", out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mouse", action="store_true", help="Mouse rehearsal, no electrical stimulation or water")
    parser.add_argument("--preview", action="store_true", help="Save default 128-channel, 490-condition plan (one per channel/current)")
    args = parser.parse_args()
    if args.preview:
        plan = make_plan(0, DEFAULTS["Random seed"], bounds(DEFAULTS), DEFAULTS["Intan channels"], repeats=1)
        path = ROOT / "Saccade_Elec_plan_preview_Intan.json"
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(path)
    else:
        launch(args)


if __name__ == "__main__":
    main()
