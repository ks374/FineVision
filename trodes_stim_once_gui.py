"""Single-shot Trodes stimulation dialog. Trodes recording is controlled separately."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from concurrent.futures import ThreadPoolExecutor
import threading
import time

SAMPLE_RATE = 30000
STEPS_UA = {"0.01": "step10nA", "0.02": "step20nA", "0.05": "step50nA",
            "0.1": "step100nA", "0.2": "step200nA", "0.5": "step500nA",
            "1": "step1uA", "2": "step2uA", "5": "step5uA", "10": "step10uA"}
GROUP = 2
SLOT = 1
CLEAR_SETTLE_MS = 2000
POST_TRAIN_WAIT_MS = 1000


def check_reply(reply):
    if isinstance(reply, bytes):
        reply = reply.decode("utf-8", errors="replace")
    if reply is not None and reply != "success":
        raise RuntimeError(f"Trodes rejected command: {reply!r}")


def parse(values):
    p = {k: int(values[k].get()) for k in
         ("cathode_id", "anode_id",
          "code", "phase", "dwell", "period", "count")}
    if any(p[k] < 1 for k in ("cathode_id", "anode_id")):
        raise ValueError("nTrode IDs must be positive.")
    # Saccade_Elec_stim_Eyelink.py uses one channel per nTrode.
    p["cathode_channel"] = p["anode_channel"] = 1
    if not 1 <= p["code"] <= 254:
        raise ValueError("Amplitude code must be 1–254 for the installed trodesnetwork SDK.")
    if p["phase"] < 1 or p["dwell"] < 0 or p["count"] < 1:
        raise ValueError("Phase width and pulse count must be positive; dwell cannot be negative.")
    if p["period"] < 2 * p["phase"] + p["dwell"]:
        raise ValueError("Period must contain both phases and the interphase dwell.")
    if not values["server"].get().strip():
        raise ValueError("TrodesNetwork server address is required.")
    p["step"] = values["step"].get()
    p["current_ua"] = p["code"] * float(p["step"])
    p["frequency_hz"] = SAMPLE_RATE / p["period"]
    return p


def clear_all_slots(hardware):
    for slot in range(256):
        check_reply(hardware.sendClearStimulationParams(slot))


def configure_once(p, hardware):
    from trodesnetwork import trodes

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
    command.setChannels(cathodeID=p["cathode_id"], cathodeChannel=p["cathode_channel"],
                        anodeID=p["anode_id"], anodeChannel=p["anode_channel"])
    command.setGroup(group=GROUP)
    command.setSlot(slot=SLOT)
    check_reply(hardware.sendStimulationParams(command))


def main():
    root = tk.Tk()
    root.title("Trodes single stimulation")
    fields = [
        ("server", "TrodesNetwork server", "tcp://127.0.0.1:49152"),
        ("cathode_id", "Cathode nTrode ID", "1"),
        ("anode_id", "Anode nTrode ID", "1"),
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

    status = tk.StringVar(value="Connecting to Trodes and clearing all slots…")
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
    busy = True
    stopped = False
    stop_requested = False
    executor = ThreadPoolExecutor(max_workers=1)
    hardware_state = {"hardware": None, "server": None}

    def startup_clear():
        try:
            from trodesnetwork import trodes
            server = values["server"].get().strip()
            if not server:
                raise ValueError("TrodesNetwork server address is required.")
            hardware_state["hardware"] = trodes.TrodesHardware(server_address=server)
            hardware_state["server"] = server
            clear_all_slots(hardware_state["hardware"])
            root.after(0, startup_clear_accepted)
        except Exception as exc:
            root.after(0, lambda error=str(exc): finish(error))

    def startup_clear_accepted():
        widgets["server"].config(state="disabled")
        status.set("All 256 clear commands accepted; waiting for the queue to settle…")
        root.after(CLEAR_SETTLE_MS, ready_after_clear)

    def ready_after_clear():
        nonlocal busy
        if stop_requested:
            close_now()
            return
        busy = False
        button.config(state="normal")
        status.set("Slots cleared and queue settled. Ready for another train.")

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
                raise ValueError("TrodesNetwork server changed after startup; restart the program.")
            summary = (f"{p['current_ua']:g} µA per phase; {p['count']} biphasic pulses; "
                       f"{p['frequency_hz']:g} Hz; {p['phase']/SAMPLE_RATE*1e6:.1f} µs/phase; "
                       f"dwell {p['dwell']/SAMPLE_RATE*1e6:.1f} µs.\n"
                       f"Cathode nTrode {p['cathode_id']}:1; "
                       f"anode nTrode {p['anode_id']}:1. Channel within nTrode is fixed at 1.\n"
                       "Send this train once now? Slots were cleared before this trial. "
                       "All slots will be cleared 1 s after the train-length photodiode signal ends. "
                       "Confirm the workspace mapping and a suitable test load.")
            if not messagebox.askokcancel("Confirm stimulation", summary, parent=root):
                return
            busy = True
            button.config(state="disabled")
            status.set("Preparing Trodes parameters; photodiode remains dark until the trigger.")

            def worker():
                try:
                    hardware = hardware_state["hardware"]
                    configure_once(p, hardware)
                    signal = threading.Event()
                    root.after(0, lambda: start_train(p, signal))
                    if not signal.wait(timeout=10):
                        raise RuntimeError("Photodiode display did not become ready.")
                    dispatch = time.perf_counter()
                    check_reply(hardware.sendStimulationStartGroup(GROUP))
                    root.after(0, lambda: accepted(dispatch))
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
                status.set(f"PD OFF {state['pd_off']:.6f}; waiting 1 s before slot clearing…")
                root.after(POST_TRAIN_WAIT_MS, post_train_clear)

        def off():
            state["pd_off"] = hide_pd()
            ready_if_complete()

        root.after(duration_ms, off)
        current["ready"] = ready_if_complete
        signal.set()

    def accepted(dispatch):
        current["state"]["reply"] = True
        status.set(f"Trigger accepted; PD ON {current['pd_on']:.6f}, command dispatch {dispatch:.6f} (PC seconds).")
        current["ready"]()

    def post_train_clear():
        status.set("Clearing all 256 slots after the train…")

        def worker():
            try:
                clear_all_slots(hardware_state["hardware"])
                root.after(0, clear_accepted)
            except Exception as exc:
                root.after(0, lambda error=str(exc): finish(error))

        executor.submit(worker)

    def clear_accepted():
        status.set("All clear commands accepted; waiting for the queue to settle…")
        root.after(CLEAR_SETTLE_MS, ready_after_clear)

    def finish(error):
        nonlocal busy
        if "state" in current:
            current["state"]["failed"] = True
        hide_pd()
        busy = False
        button.config(state="disabled")
        status.set("Stim/clear state uncertain after communication error; restart after checking Trodes.")
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
        status.set("Photodiode preview only: no Trodes command is sent.")

        def preview_off():
            nonlocal busy
            hide_pd()
            busy = False
            if stop_requested:
                close_now()
                return
            button.config(state="normal")
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
        status.set(f"Matched-duration photodiode preview: {duration_ms} ms, no Trodes command.")

        def preview_off():
            nonlocal busy
            pd_off = hide_pd()
            status.set(f"Preview only: PD ON {pd_on:.6f}, OFF {pd_off:.6f} (PC seconds).")
            busy = False
            if stop_requested:
                close_now()
                return
            button.config(state="normal")
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
    root.protocol("WM_DELETE_WINDOW", stop)
    root.after(0, lambda: executor.submit(startup_clear))
    root.mainloop()


if __name__ == "__main__":
    main()
