"""Read-only figure for first commanded stimulation in 2026-10-15 Trodes rec."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.signal import butter, sosfiltfilt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

recording = Path(r"E:\20261015\STIM_20261015_121533.rec\STIM_20261015_121533.rec")
output = Path(r"D:\Chenghang\FineVision\first_stim_20261015_lfp.png")
with recording.open("rb") as stream:
    lines = []
    while True:
        line = stream.readline()
        lines.append(line)
        if b"</Configuration>" in line:
            break
    offset = stream.tell()
root = ET.fromstring(b"".join(lines))
hwconf = root.find("HardwareConfiguration")
fs = int(hwconf.attrib["samplingRate"])
aux = sum(int(dev.attrib["numBytes"]) for dev in hwconf.findall("Device"))
ntrodes = root.findall(".//SpikeNTrode")
channels = [(int(nt.attrib["id"]), int(ch.attrib["hwChan"]), nt)
            for nt in ntrodes for ch in nt.findall("SpikeChannel")]
packet = 1+aux+4+2*len(channels)
raw = np.memmap(recording, dtype="u1", mode="r", offset=offset)
samples = len(raw)//packet
voltage = np.ndarray((samples, len(channels)), dtype="<i2", buffer=raw,
                     offset=1+aux+4, strides=(packet, 2))
dio = np.ndarray((samples,), dtype="u1", buffer=raw, offset=1, strides=(packet,))
first_stim_pd = 28.256733
# Include margins so zero-phase filtering does not create visible edge artifacts.
start, end = 27.0, 31.0
a, b = round(start*fs), round(end*fs)
rng = np.random.default_rng(20261015)
other_ids = sorted(int(i) for i in rng.choice([n for n, _, _ in channels if n != 8], 3, replace=False))
chosen_ids = [8] + other_ids
selected = []
for ntid in chosen_ids:
    col, hw, nt = next((i, hw, nt) for i, (n, hw, nt) in enumerate(channels) if n == ntid)
    selected.append((ntid, hw, col, nt))
data = voltage[a:b, [col for _, _, col, _ in selected]].astype(np.float64)*0.195
t = np.arange(a, b)/fs
cutoff = 200.0
sos = butter(4, cutoff, btype="lowpass", fs=fs, output="sos")
lfp = sosfiltfilt(sos, data, axis=0)

# Detect onset of the large artifact using the same 5 ms / median-channel rule
# used in the earlier recording audit. This is an artifact marker, not verified current.
search_a = round((first_stim_pd+1.2)*fs)
search_b = round((first_stim_pd+1.6)*fs)
burst = None
for i in range(search_a, search_b-150, 150):
    rms = np.median(np.std(voltage[i:i+150, 32:64].astype(float), axis=0))
    if rms > 1000:
        burst = i/fs
        break
assert burst is not None
zoom_a, zoom_b = burst-0.006, burst+0.032
zm = (t >= zoom_a) & (t <= zoom_b)
pd = (dio[a:b] & 1) != 0

fig, axes = plt.subplots(4, 2, figsize=(15, 11), gridspec_kw={"width_ratios": [1.4, 1]})
for k, (ntid, hw, _, nt) in enumerate(selected):
    ax, zx = axes[k]
    ax.plot(t, lfp[:, k], lw=0.8, color="#135a90")
    ax.axvline(first_stim_pd, color="#c99a00", ls="--", lw=1)
    ax.axvline(burst, color="#a52121", ls="--", lw=1)
    ax.set_xlim(28.0, 30.0)
    ax.set_ylabel(f"nTrode {ntid}:1 / HW {hw}\nµV")
    ax.grid(alpha=.25)
    zx.plot((t[zm]-burst)*1000, data[zm, k], lw=.65, color="#555555", label="raw 30 kHz")
    zx.plot((t[zm]-burst)*1000, lfp[zm, k], lw=1.1, color="#135a90", label="offline ≤200 Hz")
    zx.axvline(0, color="#a52121", ls="--", lw=1)
    zx.set_ylabel("µV")
    zx.grid(alpha=.25)
    if k == 0:
        ax.set_title("Offline LFP low-pass, 200 Hz, zero-phase")
        zx.set_title("Around large artifact onset (raw + offline LFP)")
        zx.legend(loc="upper right", fontsize=8)
    if k == 3:
        ax.set_xlabel("Seconds from recording start")
        zx.set_xlabel("ms from large-artifact onset")

fig.suptitle("2026-10-15 first stimulation command: optical onset 28.257 s; large artifact ~%.3f s\n"
             "nTrode 8:1 is configured stimulation electrode; three other nTrodes chosen with seed 20261015" % burst,
             fontsize=12)
fig.text(.5, .005, "The 22.239 s optical event was a white-square-only test. Recorded voltage polarity does not identify output-current polarity.",
         ha="center", fontsize=9)
fig.tight_layout(rect=[0,.025,1,.945])
fig.savefig(output, dpi=170)
print("output", output)
print("channels", [(n, hw, nt.attrib.get("LFPHighFilter"), nt.attrib.get("lfpFilterOn")) for n, hw, _, nt in selected])
print("optical", first_stim_pd, "large_artifact", burst, "lag_ms", (burst-first_stim_pd)*1000)

fig2, ax2 = plt.subplots(4, 1, figsize=(11, 10), sharex=True)
fine_a, fine_b = burst-0.001, burst+0.003
fine = (t >= fine_a) & (t <= fine_b)
for k, (ntid, hw, _, _) in enumerate(selected):
    ax2[k].plot((t[fine]-burst)*1000, data[fine, k], ".-", ms=2.3, lw=.7)
    ax2[k].axhline(0, color="black", lw=.5)
    ax2[k].axvline(0, color="#a52121", ls="--", lw=.8)
    ax2[k].set_ylabel(f"nTrode {ntid}:1\nHW {hw} / µV")
    ax2[k].grid(alpha=.25)
ax2[-1].set_xlabel("ms from 5-ms-bin artifact onset (NOT exact first-pulse onset)")
fig2.suptitle("First stimulation event: 30 kHz raw voltage near first large artifact\n"
              "Polarity is recorded-voltage polarity, not output-current polarity")
fig2.tight_layout()
fine_output = output.with_name("first_stim_20261015_first_pulse_raw.png")
fig2.savefig(fine_output, dpi=180)
print("fine_output", fine_output)

# A separate absolute-time figure to make clear that the pulses being discussed
# occur AFTER the approximately 1.4 s optical-to-artifact interval.
late_a, late_b = 29.65, 29.86
late = (t >= late_a) & (t <= late_b)
fig3, ax3 = plt.subplots(4, 1, figsize=(13, 10), sharex=True)
for k, (ntid, hw, _, _) in enumerate(selected):
    ax3[k].plot(t[late], data[late, k], lw=.55, color="#555555", label="raw 30 kHz")
    ax3[k].plot(t[late], lfp[late, k], lw=1.3, color="#135a90", label="offline ≤200 Hz")
    ax3[k].axvline(burst, color="#a52121", ls="--", lw=1)
    ax3[k].set_ylabel(f"nTrode {ntid}:1\nHW {hw} / µV")
    ax3[k].grid(alpha=.25)
    if k == 0:
        ax3[k].legend(loc="upper right")
ax3[-1].set_xlabel("Absolute seconds from recording start")
fig3.suptitle("LATE strong artifact, first stimulation event: 29.65–29.86 s\n"
              "Optical onset was 28.257 s; late artifact starts ~29.672 s (1.415 s later)")
fig3.tight_layout()
late_output = output.with_name("first_stim_20261015_late_strong_burst.png")
fig3.savefig(late_output, dpi=180)
print("late_output", late_output)

# Inspect the quieter interval BETWEEN optical onset and the late strong train.
stage_a, stage_b = 28.80, 28.84
detail_a, detail_b = 28.805, 28.808
stage = (t >= stage_a) & (t <= stage_b)
detail = (t >= detail_a) & (t <= detail_b)
fig4, ax4 = plt.subplots(4, 2, figsize=(15, 11))
for k, (ntid, hw, _, _) in enumerate(selected):
    left, right = ax4[k]
    left.plot((t[stage]-stage_a)*1000, data[stage, k], lw=.65, color="#555555", label="raw 30 kHz")
    left.plot((t[stage]-stage_a)*1000, lfp[stage, k], lw=1.2, color="#135a90", label="offline ≤200 Hz")
    right.plot((t[detail]-detail_a)*1000, data[detail, k], ".-", lw=.8, ms=2.2, color="#555555")
    left.set_ylabel(f"nTrode {ntid}:1\nHW {hw} / µV")
    right.set_ylabel("µV")
    left.grid(alpha=.25)
    right.grid(alpha=.25)
    if k == 0:
        left.set_title("28.800–28.840 s: 40 ms raw + offline LFP")
        right.set_title("28.805–28.808 s: 3 ms raw samples")
        left.legend(loc="upper right", fontsize=8)
    if k == 3:
        left.set_xlabel("ms since 28.800 s")
        right.set_xlabel("ms since 28.805 s")
fig4.suptitle("Between optical onset (28.257 s) and late strong train (29.672 s)\n"
              "This interval is not identified as output-current stimulation")
fig4.tight_layout()
stage_output = output.with_name("first_stim_20261015_preburst_28p8s.png")
fig4.savefig(stage_output, dpi=180)
print("stage_output", stage_output)
for k, (ntid, _, _, _) in enumerate(selected):
    q = data[stage, k]
    print("stage_ntrode", ntid, "raw_peak_to_peak_uV", round(float(np.ptp(q)),1),
          "raw_rms_uV", round(float(np.std(q)),1))

# A 1 kHz offline low-pass retains the intended 300 Hz pulse repetition while
# reducing the several-kHz background. Raw traces remain the polarity reference.
one_khz = sosfiltfilt(butter(4, 1000, btype="lowpass", fs=fs, output="sos"), data, axis=0)
fig5, ax5 = plt.subplots(4, 2, figsize=(15, 11))
for k, (ntid, hw, _, _) in enumerate(selected):
    left, right = ax5[k]
    left.plot(t[stage], data[stage, k], color="#999999", lw=.55, label="raw 30 kHz")
    left.plot(t[stage], one_khz[stage, k], color="#135a90", lw=1.2, label="offline ≤1 kHz")
    right.plot(t[late], data[late, k], color="#999999", lw=.45, label="raw 30 kHz")
    right.plot(t[late], one_khz[late, k], color="#135a90", lw=1.2, label="offline ≤1 kHz")
    left.set_ylabel(f"nTrode {ntid}:1\nHW {hw} / µV")
    right.set_ylabel("µV")
    left.grid(alpha=.25)
    right.grid(alpha=.25)
    if k == 0:
        left.set_title("Before late burst: 28.800–28.840 s")
        right.set_title("Late strong burst: 29.650–29.860 s")
        left.legend(fontsize=8)
    if k == 3:
        left.set_xlabel("Absolute seconds")
        right.set_xlabel("Absolute seconds")
fig5.suptitle("First stimulation event: raw and offline 1 kHz low-pass\n"
              "1 kHz cutoff retains 300 Hz repetition; raw is needed for individual phase shape")
fig5.tight_layout()
one_khz_output = output.with_name("first_stim_20261015_raw_and_1khz.png")
fig5.savefig(one_khz_output, dpi=180)
print("one_khz_output", one_khz_output)

# Matched-duration raw close-ups of the pre-burst interval and first late pulse.
early0 = 28.805
late0 = burst-0.001
width = 0.003
windows = [(early0, early0+width), (late0, late0+width)]
fig6, ax6 = plt.subplots(4, 2, figsize=(15, 10), sharex="col")
for k, (ntid, hw, _, _) in enumerate(selected):
    for j, (left_edge, right_edge) in enumerate(windows):
        mask = (t >= left_edge) & (t <= right_edge)
        xx = (t[mask]-left_edge)*1000
        yy = data[mask, k]
        ax6[k, j].plot(xx, yy, ".-", lw=.85, ms=2.2, color="#355a7d" if j == 0 else "#963c30")
        ax6[k, j].axhline(0, color="black", lw=.55)
        ax6[k, j].grid(alpha=.25)
        ax6[k, j].set_ylabel(f"nTrode {ntid}:1\nHW {hw} / µV")
    if k == 0:
        ax6[k, 0].set_title("EARLY: 28.805–28.808 s (within 1.4 s interval)")
        ax6[k, 1].set_title("LATE: first strong pulse near 29.672 s")
    if k == 3:
        ax6[k, 0].set_xlabel("ms since 28.805 s")
        ax6[k, 1].set_xlabel(f"ms since {late0:.6f} s")
fig6.suptitle("First stimulation event: two 3-ms raw-voltage close-ups, 30 kHz samples\n"
              "Each panel uses its own µV scale; compare the tick labels for amplitude")
fig6.tight_layout()
compare_output = output.with_name("first_stim_20261015_early_vs_late_3ms.png")
fig6.savefig(compare_output, dpi=180)
print("compare_output", compare_output)
