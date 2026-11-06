"""Plot Trodes-exported Stim band for first nTrode 8 stimulation event."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

p = Path(r"D:\Chenghang\FineVision\tmp\stim_export_20261015\STIM_20261015_121533.stimulation\STIM_20261015_121533.stimulation_nt8ch1.dat")
with p.open("rb") as f:
    header = b""
    while b"<End settings>" not in header:
        header += f.readline()
    offset = f.tell()
x = np.memmap(p, mode="r", dtype="<f4", offset=offset)
fs = 30000
first = int(np.flatnonzero(x)[0])
anchor = first/fs
fig, axes = plt.subplots(2, 1, figsize=(12, 7))
for ax, duration, title in ((axes[0], .18, "Full first train"),
                            (axes[1], .011, "First three pulse periods")):
    a = first-30
    b = first+round(duration*fs)
    tt = (np.arange(a,b)-first)/fs*1000
    ax.step(tt, x[a:b], where="post", color="#7b2f56", lw=1.1)
    ax.axhline(0, color="black", lw=.6)
    ax.set_ylabel("Exported Stim value\n(header says nA)")
    ax.set_title(title)
    ax.grid(alpha=.25)
axes[1].set_xlabel(f"ms relative to first nonzero Stim sample ({anchor:.6f} s)")
fig.suptitle("Trodes 2.8.2 -stim export, nTrode 8 channel 1\n"
             "Both pulse phases are positive in this export; scale/sign not validated as measured electrode output")
fig.tight_layout()
out = Path(r"D:\Chenghang\FineVision\first_stim_20261015_exported_stim_band_nt8.png")
fig.savefig(out, dpi=180)
print("output",out,"first",anchor,"first_values",np.unique(x[first:first+100]))
