"""Manual single-train Trodes stimulation, without display or worker threads.

Run with the Monkey environment. Trodes recording is started separately.
"""

from __future__ import annotations

import json
import math
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

SAMPLE_RATE = 30000
GROUP = 2
SLOT = 1
CLEAR_SETTLE_MS = 2000  # Prior recordings showed ~1.45 s for 256 clear commands.
POST_TRAIN_WAIT_MS = 1000
STEPS_UA = {
    "0.01": "step10nA", "0.02": "step20nA", "0.05": "step50nA",
    "0.1": "step100nA", "0.2": "step200nA", "0.5": "step500nA",
    "1": "step1uA", "2": "step2uA", "5": "step5uA", "10": "step10uA",
}
LOG_PATH = Path(__file__).with_name("trodes_stim_once_no_pd_log.jsonl")


def check_reply(reply):
    if isinstance(reply, bytes):
        reply = reply.decode("utf-8", errors="replace")
    if reply is not None and reply != "success":
        raise RuntimeError(f"Trodes rejected command: {reply!r}")


def parse(values):
    p = {key: int(values[key].get()) for key in
         ("cathode_id", "anode_id", "code", "phase", "dwell", "period", "count")}
    if p["cathode_id"] < 1 or p["anode_id"] < 1:
        raise ValueError("nTrode IDs must be positive.")
    if not 1 <= p["code"] <= 254:
        raise ValueError("Amplitude code must be 1–254 for this trodesnetwork SDK.")
    if p["phase"] < 1 or p["dwell"] < 0 or p["count"] < 1:
        raise ValueError("Phase width and pulse count must be positive; dwell cannot be negative.")
    if p["period"] < 2 * p["phase"] + p["dwell"]:
        raise ValueError("Period must contain both phases and the interphase dwell.")
    p["step"] = values["step"].get()
    p["current_ua"] = p["code"] * float(p["step"])
    p["frequency_hz"] = SAMPLE_RATE / p["period"]
    p["cathode_channel"] = p["anode_channel"] = 1
    return p


def append_log(record):
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    root = tk.Tk()
    root.title("Trodes stimulation test — no photodiode")
    frame = ttk.Frame(root, padding=16)
    frame.grid()
    fields = [
        ("server", "TrodesNetwork server", "tcp://127.0.0.1:49152"),
        ("cathode_id", "Cathode nTrode ID", "8"),
        ("anode_id", "Anode nTrode ID", "8"),
        ("step", "Current step (µA / code)", "1"),
        ("code", "Amplitude code (1–254)", "8"),
        ("phase", "Each phase width (30 kHz samples)", "5"),
        ("dwell", "Interphase dwell (samples)", "2"),
        ("period", "Pulse period (samples)", "100"),
        ("count", "Biphasic pulses in train", "50"),
    ]
    values = {}
    widgets = {}
    for row, (key, label, default) in enumerate(fields):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        values[key] = tk.StringVar(value=default)
        if key == "step":
            widget = ttk.Combobox(frame, textvariable=values[key], values=list(STEPS_UA), state="readonly")
        else:
            widget = ttk.Entry(frame, textvariable=values[key], width=30)
        widget.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=3)
        widgets[key] = widget

    status = tk.StringVar(value="Connecting to Trodes and clearing all slots…")
    ttk.Label(frame, textvariable=status, wraplength=460).grid(
        row=len(fields), column=0, columnspan=2, pady=10)
    state = {"hardware": None, "server": None, "busy": True, "stop_requested": False}

    def clear_all_slots(hardware, record):
        record["clear_call_utc"] = datetime.now().astimezone().isoformat()
        start = time.perf_counter_ns()
        for slot in range(256):
            check_reply(hardware.sendClearStimulationParams(slot))
        record["clear_reply_ms"] = (time.perf_counter_ns() - start) / 1e6
        record["clear_count"] = 256

    def ready_after_clear(record):
        record["ready_utc"] = datetime.now().astimezone().isoformat()
        try:
            append_log(record)
        except Exception as exc:
            state["busy"] = False
            status.set("Could not save the command log; check the log before continuing.")
            messagebox.showerror("Log error", str(exc), parent=root)
            if state["stop_requested"]:
                root.destroy()
            return
        state["busy"] = False
        if state["stop_requested"]:
            root.destroy()
            return
        button.config(state="normal")
        status.set("Slots cleared and command queue allowed to settle. Ready for the next train.")

    def initialize():
        record = {"action": "startup_clear_all", "result": "failed"}
        try:
            from trodesnetwork import trodes

            server = values["server"].get().strip()
            if not server:
                raise ValueError("TrodesNetwork server address is required.")
            state["hardware"] = trodes.TrodesHardware(server_address=server)
            state["server"] = server
            widgets["server"].config(state="disabled")
            record["server"] = server
            clear_all_slots(state["hardware"], record)
            record["result"] = "clear_commands_accepted"
            # Replies confirm acceptance, not that the hardware queue is empty.
            status.set("All 256 clear commands accepted. Waiting for the queue to settle…")
            root.after(CLEAR_SETTLE_MS, lambda: ready_after_clear(record))
        except Exception as exc:
            record["error"] = str(exc)
            state["busy"] = False
            try:
                append_log(record)
            except OSError:
                pass
            status.set("Startup clearing failed. Restart after checking Trodes.")
            messagebox.showerror("Startup error", str(exc), parent=root)
            if state["stop_requested"]:
                root.destroy()

    def finish_train(record):
        status.set("At least 1 s after the planned train end; clearing all slots…")
        root.update_idletasks()
        try:
            clear_all_slots(state["hardware"], record)
            record["result"] = "post_train_clear_accepted"
            status.set("All 256 clear commands accepted. Waiting for the queue to settle…")
            root.after(CLEAR_SETTLE_MS, lambda: ready_after_clear(record))
        except Exception as exc:
            record["result"] = "post_train_clear_failed"
            record["error"] = str(exc)
            state["busy"] = False
            try:
                append_log(record)
            except OSError:
                pass
            status.set("Post-train clearing failed. Check Trodes before another stimulus.")
            messagebox.showerror("Clearing error", str(exc), parent=root)
            if state["stop_requested"]:
                root.destroy()

    def trigger():
        if state["busy"]:
            return
        try:
            p = parse(values)
            server = values["server"].get().strip()
            if not server:
                raise ValueError("TrodesNetwork server address is required.")
            if server != state["server"]:
                raise ValueError("TrodesNetwork server changed after startup; restart the program.")
            summary = (
                f"{p['current_ua']:g} µA/phase, {p['count']} biphasic pulses, "
                f"{p['frequency_hz']:g} Hz; phase {p['phase']/SAMPLE_RATE*1e6:.1f} µs, "
                f"dwell {p['dwell']/SAMPLE_RATE*1e6:.1f} µs.\n"
                f"Cathode nTrode {p['cathode_id']}:1; anode nTrode {p['anode_id']}:1.\n"
                "Slot clearing finished before this trial. This will write slot 1 "
                "in group 2 and send one group trigger. One second after the "
                "planned train end, all slots will be cleared. Confirm the channel map and test load."
            )
            if not messagebox.askokcancel("Confirm stimulation", summary, parent=root):
                return
        except Exception as exc:
            messagebox.showerror("Invalid parameters", str(exc), parent=root)
            return

        state["busy"] = True
        button.config(state="disabled")
        status.set("Configuring stimulation and sending trigger…")
        root.update_idletasks()
        record = {"action": "stimulate_once", "parameters": p, "server": server, "group": GROUP, "slot": SLOT,
                  "result": "not_sent"}
        try:
            from trodesnetwork import trodes

            prep_start = time.perf_counter_ns()
            hardware = state["hardware"]
            settings = trodes.GlobalStimulationSettings()
            settings.setVoltageScale(getattr(trodes.CurrentScaling, STEPS_UA[p["step"]]))
            check_reply(hardware.sendGlobalStimulationSettings(settings))

            command = trodes.StimulationCommand()
            command.setBiphasicPulseShape(
                leadingPulseWidth_Samples=p["phase"], leadingPulseAmplitude=p["code"],
                secondPulseWidth_Samples=p["phase"], secondPulseAmplitude=p["code"],
                interPhaseDwell_Samples=p["dwell"], pulsePeriod_Samples=p["period"],
                startDelay_Samples=0)
            command.setNumPulsesInTrain(numPulsesInTrain=p["count"])
            command.setChannels(cathodeID=p["cathode_id"], cathodeChannel=1,
                                anodeID=p["anode_id"], anodeChannel=1)
            command.setGroup(group=GROUP)
            command.setSlot(slot=SLOT)
            record["params_call_utc"] = datetime.now().astimezone().isoformat()
            check_reply(hardware.sendStimulationParams(command))

            # No display flip, thread handoff, GUI update, or file write here.
            record["trigger_call_utc"] = datetime.now().astimezone().isoformat()
            trigger_start = time.perf_counter_ns()
            record["preparation_ms"] = (trigger_start - prep_start) / 1e6
            record["result"] = "sent_reply_pending"
            reply = hardware.sendStimulationStartGroup(GROUP)
            trigger_end = time.perf_counter_ns()
            check_reply(reply)
            record["reply_ms"] = (trigger_end - trigger_start) / 1e6
            record["result"] = "accepted"
            train_ms = math.ceil(p["count"] * p["period"] * 1000 / SAMPLE_RATE)
            record["planned_train_ms"] = train_ms
            record["post_train_wait_ms"] = POST_TRAIN_WAIT_MS
            record["clear_settle_ms"] = CLEAR_SETTLE_MS
            status.set(f"Trigger accepted. Waiting {train_ms} ms for the planned train "
                       f"and then {POST_TRAIN_WAIT_MS} ms before clearing…")
            root.after(train_ms + POST_TRAIN_WAIT_MS, lambda: finish_train(record))
        except Exception as exc:
            record["error"] = str(exc)
            state["busy"] = False
            status.set("Trigger state uncertain after an error; check Trodes before retrying.")
            messagebox.showerror("Stimulation error", str(exc), parent=root)
            try:
                append_log(record)
            except Exception as log_exc:
                messagebox.showerror("Log error", str(log_exc), parent=root)
            if state["stop_requested"]:
                root.destroy()

    button = ttk.Button(frame, text="OK — stimulate once", command=trigger, state="disabled")
    button.grid(row=len(fields) + 1, column=0, pady=5)
    def request_stop():
        if state["busy"]:
            state["stop_requested"] = True
            status.set("Stopping after the current clearing cycle finishes…")
        else:
            root.destroy()

    ttk.Button(frame, text="Stop", command=request_stop).grid(
        row=len(fields) + 1, column=1, pady=5)
    root.protocol("WM_DELETE_WINDOW", request_stop)
    root.after(0, initialize)
    root.mainloop()


if __name__ == "__main__":
    main()
