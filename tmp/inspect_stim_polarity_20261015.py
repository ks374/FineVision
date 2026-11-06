"""Read-only polarity/saturation audit of recorded stimulus artifacts."""
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET

p = Path(r"E:\20261015\STIM_20261015_121533.rec\STIM_20261015_121533.rec")
with p.open("rb") as f:
    lines = []
    while True:
        z = f.readline(); lines.append(z)
        if b"</Configuration>" in z:
            break
    off = f.tell()
root = ET.fromstring(b"".join(lines))
aux = sum(int(d.attrib["numBytes"]) for d in root.findall(".//HardwareConfiguration/Device"))
nch = sum(len(t.findall("SpikeChannel")) for t in root.findall(".//SpikeNTrode"))
packet = 1 + aux + 4 + 2*nch
raw = np.memmap(p, mode="r", dtype="u1", offset=off)
x = np.ndarray((len(raw)//packet, nch), dtype="<i2", buffer=raw,
               offset=1+aux+4, strides=(packet, 2))
fs = 30000
for optical in (28.256733, 83.9038):
    a = round((optical+1.37)*fs)
    b = round((optical+1.57)*fs)
    y = x[a:b, :]
    print("optical", optical, "window", a/fs, b/fs)
    for ch in (7, 32, 47, 63):
        v = y[:, ch].astype(np.int32)
        print("hw", ch, "min", int(v.min()), "max", int(v.max()),
              "at_min", int(np.argmin(v)), "at_max", int(np.argmax(v)),
              "sat_hi", int(np.count_nonzero(v>=32760)),
              "sat_lo", int(np.count_nonzero(v<=-32760)))
    # Peak polarity of recorded voltages across all channels, not output-current polarity.
    base = np.median(x[a-1500:a, :].astype(np.float32), axis=0)
    d = y.astype(np.float32)-base
    print("median_negative_excursion", float(np.median(d.min(axis=0))),
          "median_positive_excursion", float(np.median(d.max(axis=0))))
