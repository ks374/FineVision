"""Read-only spectral audit of all neural channels around optical preview."""
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
from scipy.signal import welch

path = Path(r"E:\20261015\STIM_20261015_121533.rec\STIM_20261015_121533.rec")
with path.open("rb") as file:
    lines = []
    while True:
        line = file.readline()
        lines.append(line)
        if b"</Configuration>" in line:
            break
    offset = file.tell()
root = ET.fromstring(b"".join(lines))
aux = sum(int(d.attrib["numBytes"]) for d in root.findall(".//HardwareConfiguration/Device"))
nch = sum(len(n.findall("SpikeChannel")) for n in root.findall(".//SpikeNTrode"))
packet = 1 + aux + 4 + 2*nch
n = (path.stat().st_size-offset)//packet
raw = np.memmap(path, mode="r", dtype="u1", offset=offset)
neural = np.ndarray((n,nch),dtype="<i2",buffer=raw,offset=1+aux+4,strides=(packet,2))
dio = np.ndarray((n,),dtype="u1",buffer=raw,offset=1,strides=(packet,))
fs=30000
preview_start=667165
preview_end=697065

def metrics(name,a,b):
    x=neural[a:b].astype(np.float32)
    x-=x.mean(axis=0)
    freq,pow=welch(x,fs=fs,nperseg=15000,axis=0)
    median_pow=np.median(pow,axis=1)
    mask=(freq>=100)&(freq<=3000)
    peaks=np.argsort(median_pow[mask])[-8:][::-1]
    print(name,"time_s",round(a/fs,3),round(b/fs,3),
          "median_sd",round(float(np.median(x.std(axis=0))),2),
          "median_250_320_power",round(float(np.median(np.trapz(pow[(freq>=250)&(freq<=320)],freq[(freq>=250)&(freq<=320)],axis=0))),2))
    print("peaks",[(round(float(freq[mask][i]),1),round(float(median_pow[mask][i]),3)) for i in peaks])
    for f0 in (280,300,560,840,1000,2000):
        i=np.argmin(abs(freq-f0))
        print("freq",f0,"actual",freq[i],"median_psd",round(float(np.median(pow[i,:])),3),
              "channels_psd_gt_10",int(np.count_nonzero(pow[i,:]>10)))

metrics("pre_1s",preview_start-fs,preview_start)
metrics("preview_1s",preview_start,preview_start+fs)
metrics("post_1s",preview_end,preview_end+fs)
metrics("post_2s",preview_end+fs,preview_end+2*fs)
print("dio_preview_high_fraction",round(float(np.mean((dio[preview_start:preview_end]&1)!=0)),4))
