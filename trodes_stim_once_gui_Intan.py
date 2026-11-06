"""Single-shot Intan RHS dialog. RHX Record/Run resumes after each parameter upload.
Uploads create acquisition gaps; see Intan_scripts_README.md.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from IntanStim import RHXClient, channel_name, channel_list, waveform_settings

SAMPLE_RATE = 30000
STEPS_UA = {"0.01": "step10nA", "0.02": "step20nA", "0.05": "step50nA",
            "0.1": "step100nA", "0.2": "step200nA", "0.5": "step500nA",
            "1": "step1uA", "2": "step2uA", "5": "step5uA", "10": "step10uA"}
CLEAR_SETTLE_MS = 2000
POST_TRAIN_WAIT_MS = 1000


def parse(values):
    p = {k: int(values[k].get()) for k in ("code", "phase", "dwell", "period", "count")}
    p["cathode_id"] = channel_name(values["cathode_id"].get())
    p["anode_id"] = channel_name(values["anode_id"].get())
    names = channel_list(values["channels"].get())
    if p["cathode_id"] not in names or p["anode_id"] not in names:
        raise ValueError("Both selected channels must be in Intan channels.")
    if not 1 <= p["code"] <= 254:
        raise ValueError("Amplitude code must be 1..254, matching the original GUI.")
    p["step"] = values["step"].get()
    if p["step"] not in STEPS_UA:
        raise ValueError("Unknown current step.")
    p["current_ua"] = p["code"] * float(p["step"])
    waveform_settings(p["current_ua"], p["phase"], p["dwell"], p["period"], p["count"])
    p["frequency_hz"] = SAMPLE_RATE / p["period"]
    if not values["server"].get().strip():
        raise ValueError("RHX TCP address is required.")
    return p


def clear_all_slots(hardware):
    # RHX has channel stimulation settings, not Trodes slots.
    hardware.clear()


def configure_once(p, hardware):
    if float(p["step"]) != hardware.step:
        raise ValueError("Restart RHX and this GUI to change the current step.")
    settings = {p["cathode_id"]: waveform_settings(p["current_ua"], p["phase"],
                p["dwell"], p["period"], p["count"], "NegativeFirst")}
    if p["anode_id"] != p["cathode_id"]:
        settings[p["anode_id"]] = waveform_settings(p["current_ua"], p["phase"],
                p["dwell"], p["period"], p["count"], "PositiveFirst")
    hardware.configure(settings)


def main():
    root = tk.Tk()
    root.title("Intan single stimulation")
    fields = [
        ("server", "Intan RHX TCP server", "tcp://127.0.0.1:5000"),
        ("channels", "Intan channels (native names)", "A-000:A-031"),
        ("cathode_id", "Negative-first native channel", "A-000"),
        ("anode_id", "Positive-first channel (same = monopolar)", "A-000"),
        ("step", "Current step (µA / code)", "1"),
        ("code", "Amplitude code (1–254)", "8"),
        ("phase", "Each phase width (30 kHz samples)", "5"),
        ("dwell", "Interphase dwell (samples)", "2"),
        ("period", "Pulse period (samples)", "100"),
        ("count", "Biphasic pulses in train", "50"),
    ]
    values = {}
    widgets = {}
    frame = ttk.Frame(root, padding=16)
    frame.grid()
    for row, (key, label, default) in enumerate(fields):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        values[key] = tk.StringVar(value=default)
        if key == "step":
            widget = ttk.Combobox(frame, textvariable=values[key], values=list(STEPS_UA), state="readonly")
        else:
            widget = ttk.Entry(frame, textvariable=values[key], width=30)
        widget.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=3)
        widgets[key] = widget

    status = tk.StringVar(value="Set RHX address, channels and step, then Connect. RHX must already be in Record or Run.")
    ttk.Label(frame, text="Photodiode: subject screen 1, bottom-right 160×160 px").grid(
        row=len(fields), column=0, columnspan=2, sticky="w")
    ttk.Label(frame, textvariable=status, wraplength=460).grid(row=len(fields)+1, column=0, columnspan=2, pady=10)

    # Match Fixation_movingbar.py: subject screen 1 and a 160 px square
    # inset 10 px from the right and bottom edges.
    # Create it before enabling stimulation, so a missing subject screen fails closed.
    from psychopy import visual
    subject = visual.Window(screen=1, size=[1920, 1080], fullscr=True,
                            waitBlanking=True, color="black", units="pix", allowGUI=False)
    pd_square = visual.Rect(subject, width=160, height=160, units="pix",
                            pos=(subject.size[0] / 2 - 90, -subject.size[1] / 2 + 90),
                            colorSpace="rgb255", fillColor=(0, 0, 0),
                            lineColor=(0, 0, 0), autoLog=False)
    pd_square.draw()
    subject.flip()
    root.lift()
    busy = False
    stopped = False
    stop_requested = False
    executor = ThreadPoolExecutor(max_workers=1)
    hardware_state = {"hardware": None, "server": None}

    startup_values = {}
    audit_path = Path(__file__).resolve().parent / ("trodes_stim_once_gui_Intan_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jsonl")

    def audit(row):
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def startup_clear():
        try:
            server = startup_values["server"].strip()
            if not server:
                raise ValueError("RHX TCP server address is required.")
            hardware_state["hardware"] = RHXClient(server, channel_list(startup_values["channels"]),
                                                   audit, float(startup_values["step"]))
            hardware_state["server"] = server
            clear_all_slots(hardware_state["hardware"])
            root.after(0, startup_clear_accepted)
        except Exception as exc:
            root.after(0, lambda error=str(exc): finish(error))

    def startup_clear_accepted():
        widgets["server"].config(state="disabled")
        widgets["channels"].config(state="disabled")
        widgets["step"].config(state="disabled")
        status.set("RHX stimulus settings cleared; acquisition resumed; waiting…")
        root.after(CLEAR_SETTLE_MS, ready_after_clear)

    def begin_connect():
        nonlocal busy
        if busy or hardware_state["hardware"] is not None:
            return
        startup_values.update({key: value.get() for key, value in values.items()})
        busy = True
        connect_button.config(state="disabled")
        status.set("Connecting, checking RHX, and clearing existing stimulation outputs…")
        executor.submit(startup_clear)

    def ready_after_clear():
        nonlocal busy
        if stop_requested:
            close_now()
            return
        busy = False
        button.config(state="normal")
        status.set("Ready. RHX parameter uploads split acquisition. Neural data are saved only in Record mode.")

    def show_pd():
        pd_square.fillColor = pd_square.lineColor = (255, 255, 255)
        pd_square.draw()
        subject.flip()
        return time.perf_counter()  # PC time after subject-screen flip

    def hide_pd():
        pd_square.fillColor = pd_square.lineColor = (0, 0, 0)
        pd_square.draw()
        subject.flip()
        return time.perf_counter()  # PC time after subject-screen flip

    def close_now():
        nonlocal stopped
        stopped = True
        if hardware_state["hardware"] is not None:
            try:
                hardware_state["hardware"].close()
            except Exception as exc:
                messagebox.showerror("Intan cleanup", str(exc), parent=root)
        executor.shutdown(wait=False, cancel_futures=True)
        subject.close()
        root.destroy()

    def stop():
        nonlocal stop_requested
        if busy:
            stop_requested = True
            status.set("Stopping after the current clearing cycle finishes…")
        else:
            close_now()

    def trigger():
        nonlocal busy
        if busy or stopped:
            return
        try:
            p = parse(values)
            if values["server"].get().strip() != hardware_state["server"]:
                raise ValueError("RHX TCP server changed after startup; restart the program.")
            summary = (f"{p['current_ua']:g} µA per phase; {p['count']} biphasic pulses; "
                       f"{p['frequency_hz']:g} Hz; {p['phase']/SAMPLE_RATE*1e6:.1f} µs/phase; "
                       f"dwell {p['dwell']/SAMPLE_RATE*1e6:.1f} µs.\n"
                       f"Negative-first {p['cathode_id']}; "
                       f"positive-first {p['anode_id']} (same channel = monopolar via stim ground).\n"
                       "Send this train once now? RHX acquisition stops for parameter upload, then resumes. "
                       "After the train, recording continues; old parameters are replaced before the next train. "
                       "Record mode saves separate segments; Run mode saves NO neural data. Confirm wiring and test load.")
            if not messagebox.askokcancel("Confirm stimulation", summary, parent=root):
                return
            busy = True
            button.config(state="disabled")
            status.set("Preparing Intan parameters; photodiode remains dark until the trigger.")

            def worker():
                try:
                    hardware = hardware_state["hardware"]
                    configure_once(p, hardware)
                    signal = threading.Event()
                    root.after(0, lambda: start_train(p, signal))
                    if not signal.wait(timeout=10):
                        raise RuntimeError("Photodiode display did not become ready.")
                    dispatch = time.perf_counter()
                    result = hardware.trigger()
                    root.after(0, lambda: accepted(result["command_pc"]))
                except Exception as exc:
                    root.after(0, lambda error=str(exc): finish(error))

            executor.submit(worker)
        except Exception as exc:
            messagebox.showerror("Stimulation error", str(exc), parent=root)

    current = {}

    def start_train(p, signal):
        pd_on = show_pd()
        duration_ms = round(1000 * p["count"] * p["period"] / SAMPLE_RATE)
        state = {"reply": False, "pd_off": False, "failed": False, "cleanup_scheduled": False}
        current.update(state=state, pd_on=pd_on)

        def ready_if_complete():
            if state["reply"] and state["pd_off"] and not state["failed"] and not state["cleanup_scheduled"]:
                state["cleanup_scheduled"] = True
                status.set(f"PD OFF {state['pd_off']:.6f}; recording continues; ready again in 1 s…")
                root.after(POST_TRAIN_WAIT_MS, post_train_complete)

        def off():
            state["pd_off"] = hide_pd()
            ready_if_complete()

        root.after(duration_ms, off)
        current["ready"] = ready_if_complete
        signal.set()

    def accepted(dispatch):
        current["state"]["reply"] = True
        status.set(f"Trigger command processed (physical onset unverified); PD ON {current['pd_on']:.6f}, command dispatch {dispatch:.6f} (PC seconds).")
        current["ready"]()

    def post_train_complete():
        # trigger() already consumed the software permission. Keep the uploaded
        # configuration until the next configure_once(), which replaces old and
        # new parameters inside one Stop/Record cycle. No TCP command here.
        audit(dict(event="TRAIN_COMPLETE_RECORDING_CONTINUES", pc=time.perf_counter()))
        ready_after_clear()

    def finish(error):
        nonlocal busy
        if "state" in current:
            current["state"]["failed"] = True
        hide_pd()
        busy = False
        button.config(state="disabled")
        status.set("Stim/clear state uncertain after communication error; restart after checking Intan.")
        messagebox.showerror("Stimulation error", error, parent=root)
        if stop_requested:
            close_now()

    def preview_pd():
        nonlocal busy
        if busy or stopped:
            return
        busy = True
        button.config(state="disabled")
        preview_button.config(state="disabled")
        show_pd()
        status.set("Photodiode preview only: no Intan command is sent.")

        def preview_off():
            nonlocal busy
            hide_pd()
            busy = False
            if stop_requested:
                close_now()
                return
            button.config(state="normal" if hardware_state["hardware"] else "disabled")
            preview_button.config(state="normal")

        root.after(1000, preview_off)

    def preview_train_length_pd():
        nonlocal busy
        if busy or stopped:
            return
        try:
            p = parse(values)
        except Exception as exc:
            messagebox.showerror("Invalid parameters", str(exc), parent=root)
            return
        busy = True
        button.config(state="disabled")
        preview_button.config(state="disabled")
        short_preview_button.config(state="disabled")
        pd_on = show_pd()
        duration_ms = round(1000 * p["count"] * p["period"] / SAMPLE_RATE)
        status.set(f"Matched-duration photodiode preview: {duration_ms} ms, no Intan command.")

        def preview_off():
            nonlocal busy
            pd_off = hide_pd()
            status.set(f"Preview only: PD ON {pd_on:.6f}, OFF {pd_off:.6f} (PC seconds).")
            busy = False
            if stop_requested:
                close_now()
                return
            button.config(state="normal" if hardware_state["hardware"] else "disabled")
            preview_button.config(state="normal")
            short_preview_button.config(state="normal")

        root.after(duration_ms, preview_off)

    button = ttk.Button(frame, text="OK — stimulate once", command=trigger, state="disabled")
    button.grid(row=len(fields)+2, column=0, pady=5)
    ttk.Button(frame, text="Stop", command=stop).grid(row=len(fields)+2, column=1, pady=5)
    preview_button = ttk.Button(frame, text="Preview white square (1 s, no stimulation)", command=preview_pd)
    preview_button.grid(row=len(fields)+3, column=0, columnspan=2, pady=5)
    short_preview_button = ttk.Button(frame, text="Preview train-length square (no stimulation)",
                                      command=preview_train_length_pd)
    short_preview_button.grid(row=len(fields)+4, column=0, columnspan=2, pady=5)
    connect_button = ttk.Button(frame, text="Connect to Intan RHX", command=begin_connect)
    connect_button.grid(row=len(fields)+5, column=0, columnspan=2, pady=5)
    root.protocol("WM_DELETE_WINDOW", stop)
    root.mainloop()


if __name__ == "__main__":
    main()
