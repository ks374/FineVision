"""RHX 3.5 TCP stimulation adapter; no Trodes dependency.

RHX must already be in Run or Record. Parameter uploads stop acquisition, then
resume that mode. Each Record restart gets a unique filename. Never retry a
trigger. See Intan_scripts_README.md for the unavoidable ITI recording gaps.
"""
import math
import queue
import random
import re
import socket
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

from SaccadeElecLogic import make_plan as original_plan


class RHXError(RuntimeError):
    pass


def channel_name(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r"[A-D]-\d{3}", value) or int(value[2:]) > 127:
        raise ValueError("Use an RHX native channel name, e.g. A-000 (zero based).")
    return value


def channel_list(value):
    result = []
    for part in str(value).split(","):
        ends = part.strip().split(":")
        first = channel_name(ends[0])
        if len(ends) == 1:
            result.append(first)
        elif len(ends) == 2:
            last = channel_name(ends[1])
            if first[0] != last[0] or int(first[2:]) > int(last[2:]):
                raise ValueError("Channel ranges must ascend within one port.")
            result.extend(f"{first[0]}-{i:03d}" for i in range(int(first[2:]), int(last[2:])+1))
        else:
            raise ValueError("Use A-000:A-031 or comma-separated native channels.")
    if len(result) != len(set(result)):
        raise ValueError("Duplicate Intan channels are not allowed.")
    return result


def make_plan(bank, seed, bounds, channels="A-000:A-031", repeats=2):
    """Build balanced controls; repeats=2 preserves the legacy schedule."""
    if repeats not in (1, 2):
        raise ValueError("repeats must be 1 or 2.")
    names = channel_list(channels)
    n = len(names)
    if n not in (16, 32, 64, 128):
        raise ValueError("Select exactly 16, 32, 64 or 128 Intan channels.")
    if bank not in (0, 128):
        raise ValueError("HW bank start (legacy electrode labels) must be 0 or 128.")
    xmin, xmax, ymin, ymax = bounds
    if not xmin < xmax or not ymin < ymax:
        raise ValueError("RF minima must be smaller than maxima.")
    if n == 128 and repeats == 2:
        plan = original_plan(bank, seed, bounds)
    else:
        rng = random.Random(seed)
        def point():
            return [rng.uniform(xmin, xmax), rng.uniform(ymin, ymax)]
        control_count = n * 3 * repeats // 4
        columns = 8 if control_count % 8 == 0 else 4
        rows = control_count // columns
        controls = [[xmin+(x+rng.random())*(xmax-xmin)/columns,
                     ymin+(y+rng.random())*(ymax-ymin)/rows]
                    for x in range(columns) for y in range(rows)]
        rng.shuffle(controls)
        conditions = [(h, a, r) for h in range(bank, bank+n)
                      for a in (8, 14, 20) for r in range(1, repeats+1)]
        rng.shuffle(conditions)
        plan = [dict(kind="precontrol", target_deg=point()) for _ in range(10)]
        for i, (hw, current, repeat) in enumerate(conditions, 1):
            plan.append(dict(kind="stim", hw=hw, ntrode=hw+1,
                             current_uA=current, repeat=repeat, target_deg=point()))
            if i % 4 == 0:
                plan.append(dict(kind="control", target_deg=controls.pop()))
        for i, row in enumerate(plan, 1):
            row["plan_id"] = i
    for row in plan:
        if row["kind"] == "stim":
            row["intan_channel"] = names[row["hw"]-bank]
    return plan


def waveform_settings(current, phase=5, dwell=2, period=100, count=50,
                      polarity="NegativeFirst"):
    for name, value in (("phase", phase), ("dwell", dwell), ("period", period), ("count", count)):
        if not math.isfinite(float(value)) or int(value) != value:
            raise ValueError(f"{name} must be an integer number of 30 kHz samples/pulses.")
    if not 1 <= phase <= 150 or not 0 <= dwell <= 150:
        raise ValueError("RHX phase must be 1..150 samples; dwell 0..150 (maximum 5000 us).")
    if not 2*phase+dwell <= period <= 30000 or not 1 <= count <= 256:
        raise ValueError("Period must contain both phases and dwell, max 30000 samples; count 1..256.")
    if not math.isfinite(float(current)) or not 0 < current <= 2550:
        raise ValueError("Current must be positive and at most 2550 uA.")
    if polarity not in ("NegativeFirst", "PositiveFirst"):
        raise ValueError("Unknown polarity.")
    return dict(StimEnabled="True", Source="KeyPressF1", TriggerEdgeOrLevel="Edge",
                TriggerHighOrLow="High", Shape="BiphasicWithInterphaseDelay" if dwell else "Biphasic",
                Polarity=polarity, PulseOrTrain="SinglePulse" if count == 1 else "PulseTrain",
                NumberOfStimPulses=count, FirstPhaseAmplitudeMicroAmps=current,
                SecondPhaseAmplitudeMicroAmps=current,
                FirstPhaseDurationMicroseconds=phase*1e6/30000,
                SecondPhaseDurationMicroseconds=phase*1e6/30000,
                InterphaseDelayMicroseconds=dwell*1e6/30000,
                PulseTrainPeriodMicroseconds=period*1e6/30000,
                PostTriggerDelayMicroseconds=0, RefractoryPeriodMicroseconds=1000,
                EnableAmpSettle="True", MaintainAmpSettle="False",
                PreStimAmpSettleMicroseconds=0, PostStimAmpSettleMicroseconds=1000,
                EnableChargeRecovery="False", PostStimChargeRecovOnMicroseconds=0,
                PostStimChargeRecovOffMicroseconds=0)


def digital_marker_settings(waveform):
    """1 kHz, 50% duty marker; never schedule a high past the final phase."""
    tick_us = 1e6 / 30000
    ticks = lambda key: round(float(waveform[key]) / tick_us)
    count = (1 if waveform["PulseOrTrain"] == "SinglePulse"
             else int(waveform["NumberOfStimPulses"]))
    end = ((count - 1) * ticks("PulseTrainPeriodMicroseconds")
           + ticks("FirstPhaseDurationMicroseconds")
           + ticks("SecondPhaseDurationMicroseconds")
           + (ticks("InterphaseDelayMicroseconds")
              if waveform["Shape"] == "BiphasicWithInterphaseDelay" else 0))
    pulses = (end - 15) // 30 + 1
    if not 1 <= pulses <= 256:
        raise ValueError("Stimulus duration cannot be marked by 1..256 half-ms digital pulses.")
    return dict(StimEnabled="True", Source=waveform["Source"],
                TriggerEdgeOrLevel="Edge", TriggerHighOrLow="High",
                PulseOrTrain="SinglePulse" if pulses == 1 else "PulseTrain",
                NumberOfStimPulses=pulses, FirstPhaseDurationMicroseconds=500,
                PulseTrainPeriodMicroseconds=1000,
                PostTriggerDelayMicroseconds=waveform["PostTriggerDelayMicroseconds"],
                RefractoryPeriodMicroseconds=1000)


class RHXClient:
    REPLY_TIMEOUT_S = 20
    # RHX replies have no newline/length delimiter. A read-only Type query is a
    # known end marker, so fragmented/coalesced TCP packets are handled correctly.
    MARKER = b"Return: Type ControllerStimRecord"

    def __init__(self, address, required_channels, log=None, expected_step=1.0, require_record=False,
                 digital_marker=False):
        url = urlsplit(address if "://" in address else "tcp://"+address)
        if url.scheme != "tcp" or not url.hostname or not url.port:
            raise ValueError("RHX address must be tcp://127.0.0.1:5000.")
        self.sock = socket.create_connection((url.hostname, url.port), timeout=5)
        self.sock.settimeout(self.REPLY_TIMEOUT_S)
        self.log = log or (lambda event: None)
        self.required = [channel_name(c) for c in required_channels]
        self.active = []
        self.digital_marker = digital_marker
        self.armed = False
        self.failed = False
        self.mode = None
        self.base = None
        self.segment = 0
        self.initialized = False
        self.segment_start_timestamp = None
        self.tail_protection = None
        try:
            # Bootstrap separately: the sentinel is only valid for an RHS controller.
            self.sock.sendall(b"get type;")
            data = b""
            deadline = time.monotonic()+self.REPLY_TIMEOUT_S
            while self.MARKER not in data:
                if time.monotonic() > deadline:
                    raise RHXError("RHX did not identify an RHS stimulation/recording controller.")
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise RHXError("RHX disconnected.")
                data += chunk
                if b"ControllerRecord" in data or b"ControllerUSB" in data or b"Error" in data:
                    raise RHXError(f"{address} belongs to a non-stimulating or invalid RHX instance. "
                                   "Select the TCP command port of the RHS stimulation/recording controller; "
                                   "use a different port for the RHD recording device.")
            if self.get("Synthetic").lower() != "false" or self.get("Playback").lower() != "false":
                raise RHXError("Real stimulation mode rejects synthetic/playback RHX. Use task simulation instead.")
            if float(self.get("SampleRateHertz")) != 30000:
                raise RHXError("Restart RHX with 30 kHz sampling to preserve the original waveform.")
            self.step = float(self.get("StimStepSizeMicroAmps"))
            if not math.isclose(self.step, float(expected_step)):
                raise RHXError(f"RHX current step is {self.step:g} uA; restart RHX with {expected_step:g} uA.")
            self.mode = self.get("RunMode").lower()
            if self.mode not in ("record", "run"):
                raise RHXError("First start Record (save data) or Run (no data saved) in RHX, then start this script.")
            if require_record and self.mode != "record":
                raise RHXError("The EyeLink task requires RHX Record mode so trial baseline/tail data are saved.")
            self.base = self.get("Filename.BaseFilename") if self.mode == "record" else ""
            self.path = self.get("Filename.Path") if self.mode == "record" else ""
            if self.mode == "record" and (not self.base or not self.path):
                raise RHXError("RHX recording filename/path is missing.")
            for name in self.required:
                if self.get(name+".NativeChannelName").upper() != name:
                    raise RHXError(f"Channel {name} is not present.")
                if self.get(name+".Enabled").lower() != "true":
                    raise RHXError(f"Recording channel {name} is disabled in RHX.")
            self.log(dict(event="RHX_CONNECTED", pc=time.perf_counter(), mode=self.mode,
                          address=address, controller_type="ControllerStimRecord",
                          channels=self.required, step_uA=self.step,
                          version=self.get("Version"), recording_gaps_in_iti=True))
            # Clear ALL existing stimulus outputs, including unselected channels,
            # so a stale F1 assignment cannot stimulate an unintended electrode.
            candidates = []
            for port in "ABCD":
                count = int(self.get(port+".NumberAmplifierChannels"))
                if not 0 <= count <= 128:
                    raise RHXError(f"Unexpected channel count on port {port}: {count}")
                candidates.extend(f"{port}-{i:03d}" for i in range(count))
            expanded = self.get("ExpanderConnected").lower() == "true"
            candidates += [f"ANALOG-OUT-{i}" for i in range(1, 9 if expanded else 3)]
            candidates += [f"DIGITAL-OUT-{i:02d}" for i in range(1, 17 if expanded else 3)]
            enabled_outputs = []
            for name in candidates:
                enabled = self.get(name+".StimEnabled")
                if enabled.lower() not in ("true", "false"):
                    raise RHXError(f"Invalid StimEnabled state for {name}: {enabled!r}")
                if enabled.lower() == "true":
                    enabled_outputs.append(name)
            # Validate all names while recording still runs. A failed preflight
            # must not leave acquisition stopped before any upload is attempted.
            if enabled_outputs or self.digital_marker:
                self._stop()
                for name in enabled_outputs:
                    self.set_verified(name+".StimEnabled", "False")
                if self.digital_marker:
                    # DIG OUT 1 must use its sequencer, not the DAC comparator.
                    self.set_verified("AnalogOut1ThresholdEnabled", "False")
                upload_start = time.perf_counter()
                self.upload()
                self.log(dict(event="RHX_INITIAL_CLEAR_UPLOAD_COMPLETED",
                              pc=time.perf_counter(), upload_seconds=time.perf_counter()-upload_start,
                              disabled_output_count=len(enabled_outputs)))
                self._resume()
            else:
                self.segment_start_timestamp = self.timestamp()
                self.log(dict(event="RHX_INITIAL_CLEAR_SKIPPED", pc=time.perf_counter(),
                              reason="all_outputs_stim_disabled", checked_output_count=len(candidates),
                              segment_start_timestamp=self.segment_start_timestamp))
            self.initialized = True
        except BaseException:
            self.sock.close()
            raise

    def exchange(self, commands):
        self.sock.sendall((commands.rstrip(";")+";get type;").encode("utf-8"))
        data = b""
        deadline = time.monotonic()+self.REPLY_TIMEOUT_S
        while self.MARKER not in data:
            if time.monotonic() > deadline:
                raise RHXError("TCP reply timed out; stimulation state uncertain; do not retry.")
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RHXError("RHX disconnected; stimulation state uncertain.")
            data += chunk
            if len(data) > 1000000:
                raise RHXError("Unexpected oversized RHX response.")
        before, after = data.split(self.MARKER, 1)
        if after.strip():
            raise RHXError("Unexpected trailing RHX response.")
        reply = before.decode("utf-8", errors="replace").strip()
        if "error" in reply.lower() or "warning" in reply.lower():
            raise RHXError(reply)
        if reply and not commands.lstrip().lower().startswith("get "):
            raise RHXError("Unexpected RHX command response: "+reply)
        return reply

    def get(self, name):
        reply = self.exchange("get "+name)
        # Channel queries return the leaf parameter name, not the channel prefix.
        label = name if name.lower().startswith("filename.") else name.split(".")[-1]
        prefix = "Return: "+label
        if not (reply.lower() == prefix.lower() or reply.lower().startswith(prefix.lower()+" ")):
            raise RHXError(f"Unexpected response to {name}: {reply!r}")
        return reply[len(prefix):].strip()

    def set_verified(self, name, value):
        if any(c in str(value) for c in ";\r\n"):
            raise ValueError("Invalid delimiter in RHX value.")
        value = format(value, ".10g") if isinstance(value, (int, float)) else str(value)
        self.exchange(f"set {name} {value}")
        actual = self.get(name)
        try:
            requested, returned = float(value), float(actual)
            # RHX formats numeric replies with limited significant digits
            # (e.g. 166.6666667 us -> 166.667 us). Allow that text rounding,
            # but require timing parameters to resolve to the same 30 kHz tick.
            same = (math.isfinite(requested) and math.isfinite(returned)
                    and math.isclose(returned, requested, rel_tol=5e-6, abs_tol=1e-9))
            if same and name.lower().endswith("microseconds"):
                to_tick = lambda us: math.floor(us * 30000 / 1e6 + .5)
                same = to_tick(returned) == to_tick(requested)
        except ValueError:
            same = actual.lower() == value.lower()
        if not same:
            raise RHXError(f"RHX readback mismatch: {name}: requested {value}, got {actual}.")

    def wait_value(self, name, value, timeout=30):
        deadline = time.monotonic()+timeout
        while self.get(name).lower() != value.lower():
            if time.monotonic() > deadline:
                raise RHXError(f"Timeout waiting for {name}={value}.")
            time.sleep(.02)

    def upload(self, channel=None):
        self.wait_value("UploadInProgress", "False")
        self.exchange("execute uploadstimparameters"+(" "+channel if channel else ""))
        self.wait_value("UploadInProgress", "False")

    def set_runmode(self, mode):
        # RHX runController() enters its acquisition event loop synchronously.
        # Never append a query to this same command batch: it may not execute
        # until acquisition ends. Send a separate request after RHX enters Run.
        self.log(dict(event="RHX_RUNMODE_REQUEST", pc=time.perf_counter(), mode=mode))
        self.sock.sendall(("set runmode "+mode+";").encode("ascii"))
        time.sleep(.1)
        self.wait_value("RunMode", mode)

    def timestamp(self):
        # RHX's special CurrentTimestamp query returns 'Return: <integer>',
        # unlike ordinary state items, which include a parameter name.
        reply = self.exchange("get currenttimestamp")
        if not reply.startswith("Return: "):
            raise RHXError("Unexpected CurrentTimestamp reply: "+reply)
        value = int(reply[len("Return: "):])
        if value == -1:
            raise RHXError("Acquisition stopped; trial recording continuity is lost.")
        return value & 0xffffffff

    def wait_recorded_since(self, anchor, seconds, allow_pretrial_rebase=False):
        deadline = time.monotonic()+seconds+10
        rebased_pc = None
        previous = anchor
        while True:
            if self.get("RunMode").lower() != self.mode:
                raise RHXError("RHX acquisition mode changed during recording protection.")
            current = self.timestamp()
            elapsed = (current-anchor) & 0xffffffff
            backward = ((current-previous) & 0xffffffff) > 0x7fffffff
            if elapsed > 0x7fffffff or backward:
                self.log(dict(event="RHX_TIMESTAMP_BACKWARD", pc=time.perf_counter(),
                              segment=self.segment, anchor_timestamp=anchor,
                              previous_timestamp=previous, current_timestamp=current,
                              pretrial=allow_pretrial_rebase))
                if not allow_pretrial_rebase:
                    raise RHXError("Hardware timestamp restarted during recording protection.")
                # No trial has begun. Discard the uncertain baseline and require
                # a complete new PC AND sample interval; never relax trial tails.
                anchor = current
                self.segment_start_timestamp = current
                elapsed = 0
                rebased_pc = time.monotonic()
            previous = current
            if (elapsed >= math.ceil(seconds*30000)
                    and (rebased_pc is None or time.monotonic()-rebased_pc >= seconds)):
                return current
            if time.monotonic() >= deadline:
                raise RHXError("Hardware samples did not advance through the recording protection interval.")
            time.sleep(.02)

    def protect_trial_tail(self, seconds=1.1):
        self.tail_protection = (self.timestamp(), time.perf_counter()+seconds, seconds)
        self.log(dict(event="RHX_TRIAL_TAIL_PROTECTED", pc=time.perf_counter(),
                      segment=self.segment, anchor_timestamp=self.tail_protection[0], seconds=seconds))

    def verify_trial_recording(self, seconds=1.1):
        current = self.wait_recorded_since(self.segment_start_timestamp, seconds,
                                           allow_pretrial_rebase=True)
        return dict(segment=self.segment, timestamp=current,
                    segment_start_timestamp=self.segment_start_timestamp,
                    minimum_pretrial_samples=math.ceil(seconds*30000))

    def _stop(self):
        if self.tail_protection:
            anchor, pc_deadline, seconds = self.tail_protection
            remaining = pc_deadline-time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            self.wait_recorded_since(anchor, seconds)
            self.tail_protection = None
        mode = self.get("RunMode").lower()
        if mode != self.mode:
            raise RHXError(f"RHX RunMode changed externally: {mode}; expected {self.mode}.")
        pc = time.perf_counter()
        self.set_runmode("stop")
        self.log(dict(event="RHX_ACQUISITION_STOPPED", request_pc=pc,
                      confirmed_pc=time.perf_counter(), segment=self.segment))

    def _resume(self):
        self.wait_value("UploadInProgress", "False")
        self.segment += 1
        name = self.base
        if self.mode == "record":
            name = f"{self.base}_Intan_{datetime.now():%Y%m%d_%H%M%S_%f}_seg{self.segment:04d}"
            # Per-channel/per-signal .dat names are fixed, so a unique base alone
            # would NOT prevent overwrites when CreateNewDirectory is disabled.
            self.set_verified("CreateNewDirectory", "True")
            self.set_verified("Filename.BaseFilename", name)
        pc = time.perf_counter()
        self.set_runmode(self.mode)
        self.segment_start_timestamp = self.timestamp()
        self.log(dict(event="RHX_ACQUISITION_RESUMED", request_pc=pc,
                      confirmed_pc=time.perf_counter(), segment=self.segment,
                      segment_start_timestamp=self.segment_start_timestamp,
                      mode=self.mode, basefilename=name, path=self.path,
                      create_new_directory=self.mode == "record",
                      file_timestamp=self.get("Filename.ActiveFileTimestamp") if self.mode == "record" else None))

    def configure(self, waveforms):
        """Change configuration only between trials; return after acquisition resumes."""
        if self.failed:
            raise RHXError("Client failed previously; restart after checking RHX.")
        for channel, settings in waveforms.items():
            if channel not in self.required:
                raise ValueError(f"{channel} is not in the selected channel map.")
            for key in ("FirstPhaseAmplitudeMicroAmps", "SecondPhaseAmplitudeMicroAmps"):
                code = float(settings[key])/self.step
                if not 1 <= code <= 255 or not math.isclose(code, round(code), abs_tol=1e-7):
                    raise ValueError("Requested amplitude is not representable with RHX's current step.")
        waveforms = dict(waveforms)
        if self.digital_marker and waveforms:
            if len(waveforms) != 1:
                raise ValueError("Digital marker requires one electrode waveform per trial.")
            waveforms["DIGITAL-OUT-01"] = digital_marker_settings(next(iter(waveforms.values())))
        self.armed = False
        try:
            self._stop()
            if self.digital_marker:
                self.set_verified("AnalogOut1ThresholdEnabled", "False")
            changed = set(self.active) | set(waveforms)
            for channel in self.active:
                self.set_verified(channel+".StimEnabled", "False")
            for channel, settings in waveforms.items():
                for key, value in settings.items():
                    self.set_verified(channel+"."+key, value)
            for channel in sorted(changed):
                self.upload(channel)
            self.active = list(waveforms)
            self._resume()
            self.armed = bool(waveforms)
            self.log(dict(event="RHX_CONFIGURATION", pc=time.perf_counter(),
                          segment=self.segment, waveforms=waveforms))
        except BaseException:
            self.failed = True
            raise

    def clear(self):
        if self.active:
            self.configure({})
        self.armed = False

    def disarm(self):
        """Revoke script trigger permission without stopping acquisition."""
        self.armed = False
        self.log(dict(event="RHX_SOFTWARE_DISARMED", pc=time.perf_counter(), segment=self.segment))

    def trigger(self, progress=None):
        if self.failed or not self.armed:
            raise RHXError("Not prepared, already triggered, or client failed.")
        self.armed = False  # Consume before any network operation: never retry.
        try:
            if self.get("RunMode").lower() != self.mode:
                raise RHXError("RHX is no longer in the expected acquisition mode.")
            dispatch = time.perf_counter()
            if progress is not None:
                progress["command_pc"] = dispatch
            self.exchange("execute manualstimtriggerpulse f1")
            result = dict(command_pc=dispatch, reply="TCP processed; physical onset unverified",
                          segment=self.segment, hardware_onset_verified=False)
            self.log(dict(event="RHX_TRIGGER", **result))
            return result
        except BaseException:
            self.failed = True
            raise

    def close(self):
        try:
            if not self.failed:
                # Final shutdown: preserve the protected tail, end/save the
                # current recording, disable outputs while stopped, and STOP.
                # Do not create a final empty recording segment via configure().
                if self.get("RunMode").lower() != "stop":
                    self._stop()
                for channel in self.active:
                    self.set_verified(channel+".StimEnabled", "False")
                    self.upload(channel)
                self.active = []
                self.armed = False
                self.log(dict(event="RHX_CLOSED_STOPPED", pc=time.perf_counter(), segment=self.segment))
            else:
                self.log(dict(event="RHX_CLEANUP_UNCERTAIN", pc=time.perf_counter(),
                              message="Check RHX manually; no trigger retried."))
                # Stop acquisition/stimulation if communication is still usable.
                # Never re-send a trigger after an ambiguous response.
                if self.get("RunMode").lower() != "stop":
                    self.set_runmode("stop")
        finally:
            self.sock.close()


class IntanWorker:
    """One socket-owning worker; display thread remains responsive."""
    def __init__(self, address, channels, audit_path):
        self.jobs = queue.Queue()
        self.address, self.channels, self.audit_path = address, channel_list(channels), audit_path
        self.hardware = None
        self.prepared = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, action, condition=None):
        result = {"done": False, "action": action}
        self.jobs.put((action, condition, result))
        return result

    def _run(self):
        import json
        with open(self.audit_path, "a", encoding="utf-8", buffering=1) as audit:
            def log(row):
                audit.write(json.dumps(row, ensure_ascii=False)+"\n")
            while True:
                action, condition, result = self.jobs.get()
                try:
                    if action == "init":
                        self.hardware = RHXClient(self.address, self.channels, log, require_record=True,
                                                  digital_marker=True)
                    elif action == "protect_trial_tail":
                        self.hardware.protect_trial_tail()
                    elif action == "verify_trial_recording":
                        result.update(self.hardware.verify_trial_recording())
                    elif action == "clear_trial_slot":
                        self.prepared = None
                        self.hardware.clear()
                    elif action == "disarm_trial":
                        self.prepared = None
                        self.hardware.disarm()
                    elif action == "prepare":
                        self.prepared = None
                        self.hardware.configure({condition["intan_channel"]:
                                                 waveform_settings(condition["current_uA"])})
                        self.prepared = condition["plan_id"]
                    elif action == "prepare_trial":
                        # Clear the previous waveform and upload the next one
                        # in a single acquisition stop/resume cycle.
                        self.prepared = None
                        if condition["kind"] == "stim":
                            self.hardware.configure({condition["intan_channel"]:
                                                     waveform_settings(condition["current_uA"])})
                            self.prepared = condition["plan_id"]
                        else:
                            # Visual trials upload no new waveform. Leave the
                            # hardware configuration for the next joint update.
                            self.hardware.disarm()
                    elif action == "trigger":
                        if self.prepared != condition["plan_id"]:
                            raise RHXError("Trial not prepared or already triggered.")
                        self.prepared = None
                        result.update(self.hardware.trigger(result))
                    elif action == "close":
                        if self.hardware:
                            self.hardware.close()
                        return
                    else:
                        raise ValueError("Unknown worker action: "+action)
                except Exception as exc:
                    result["error"] = repr(exc)
                    log(dict(event="RHX_ERROR", pc=time.perf_counter(), action=action, error=repr(exc)))
                finally:
                    result["return_pc"] = time.perf_counter()
                    result["done"] = True
