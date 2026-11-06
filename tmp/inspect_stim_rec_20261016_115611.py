"""Read-only packet/timestamp/DIO audit for the named Trodes recording."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

path = Path(r"E:\20261016\Test_Stim_20261016_115611.rec\Test_Stim_20261016_115611.rec")
with path.open("rb") as file:
    lines = []
    while True:
        line = file.readline()
        lines.append(line)
        if b"</Configuration>" in line:
            break
    header_bytes = file.tell()
root = ET.fromstring(b"".join(lines))
for nt in root.findall(".//SpikeNTrode"):
    if nt.attrib.get("id") == "8":
        print("NTRODE8", [(ch.attrib.get("hwChan"), ch.attrib.get("stimCapable"))
                           for ch in nt.findall("SpikeChannel")])
hw = root.find("HardwareConfiguration")
devices = hw.findall("Device")
aux_bytes = sum(int(device.attrib["numBytes"]) for device in devices)
nchannels = sum(len(nt.findall("SpikeChannel")) for nt in root.findall(".//SpikeNTrode"))
packet_bytes = 1 + aux_bytes + 4 + 2 * nchannels
data_bytes = path.stat().st_size - header_bytes
print("header", header_bytes, "aux", aux_bytes, "channels", nchannels,
      "packet", packet_bytes, "data", data_bytes, "remainder", data_bytes % packet_bytes)
assert data_bytes % packet_bytes == 0
assert devices[0].attrib["name"] == "Controller_DIO" and devices[0].attrib["numBytes"] == "1"
dtype = np.dtype([("marker", "u1"), ("dio", "u1"),
                  ("rest_aux", f"V{aux_bytes - 1}"), ("timestamp", "<u4"),
                  ("neural", f"V{2 * nchannels}")])
record = np.memmap(path, dtype=dtype, mode="r", offset=header_bytes)
print("samples", len(record), "seconds", len(record)/int(hw.attrib["samplingRate"]))
print("marker_bad", np.count_nonzero(record["marker"] != 85))
ticks = np.asarray(record["timestamp"])
diff = np.diff(ticks.astype(np.int64))
bad = np.flatnonzero(diff != 1)
print("tick_first_last", int(ticks[0]), int(ticks[-1]), "gaps", len(bad),
      "gap_samples_total", int(np.sum(diff[bad]-1)) if len(bad) else 0)
for i in bad[:30]:
    print("GAP", int(i), "t_rel_s", round((int(ticks[i])-int(ticks[0]))/30000, 6),
          "delta", int(diff[i]))
dio = np.asarray(record["dio"])
for bit in range(8):
    level = (dio & (1 << bit)) != 0
    changes = np.flatnonzero(level[1:] != level[:-1]) + 1
    if level[0]:
        changes = np.r_[0, changes]
    if level[-1]:
        changes = np.r_[changes, len(level)]
    starts, ends = changes[::2], changes[1::2]
    print("DIN", bit+1, "high_intervals", len(starts), "high_samples", int(np.sum(ends-starts)))
    if bit == 0 and len(starts):
        group_starts = np.r_[0, np.flatnonzero(np.diff(starts) > 0.5*30000)+1]
        group_ends = np.r_[group_starts[1:], len(starts)]
        for a, b in zip(group_starts, group_ends):
            print("GROUP", "edges", int(b-a), "start_s", round((int(ticks[starts[a]])-int(ticks[0]))/30000, 6),
                  "start_tick", int(ticks[starts[a]]), "end_tick", int(ticks[min(ends[b-1],len(ticks)-1)]),
                  "end_s", round((int(ticks[min(ends[b-1],len(ticks)-1)])-int(ticks[0]))/30000, 6),
                  "span_ms", round((int(ends[b-1]-starts[a]))*1000/30000, 3),
                  "median_isi_ms", round(float(np.median(np.diff(starts[a:b])))*1000/30000, 3) if b-a>1 else None)
        neural = np.ndarray((len(record), nchannels), dtype="<i2", buffer=record,
                            offset=1 + aux_bytes + 4, strides=(packet_bytes, 2))
        for group_index, (a, b) in enumerate(zip(group_starts, group_ends)):
            s, e = int(starts[a]), int(ends[b-1])
            pre = neural[max(0,s-5000):s]
            during = neural[s:e]
            post = neural[e:min(len(neural),e+5000)]
            def stats(x):
                return (round(float(np.median(np.std(x.astype(np.float32), axis=0))),2),
                        int(np.count_nonzero(np.ptp(x, axis=0))),
                        round(float(np.mean(np.all(x[1:]==x[:-1],axis=1))),4))
            print("NEURAL_GROUP", group_index, "pre/during/post median_sd, varying_channels, identical_row_fraction",
                  stats(pre), stats(during), stats(post))


