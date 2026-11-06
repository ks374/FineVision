"""Read-only, time-resolved audit of apparent two-stage artifact near preview."""
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
from scipy.signal import periodogram

path=Path(r"E:\20261015\STIM_20261015_121533.rec\STIM_20261015_121533.rec")
with path.open("rb") as f:
    lines=[]
    while True:
        line=f.readline(); lines.append(line)
        if b"</Configuration>" in line: break
    off=f.tell()
root=ET.fromstring(b"".join(lines))
aux=sum(int(d.attrib["numBytes"]) for d in root.findall(".//HardwareConfiguration/Device"))
nch=sum(len(n.findall("SpikeChannel")) for n in root.findall(".//SpikeNTrode"))
packet=1+aux+4+2*nch
raw=np.memmap(path,mode="r",dtype="u1",offset=off)
n=len(raw)//packet
x=np.ndarray((n,nch),dtype="<i2",buffer=raw,offset=1+aux+4,strides=(packet,2))
fs=30000
first=round(83.9038*fs)
for t in np.arange(-0.2,1.8,0.05):
    a=first+round(t*fs); b=a+round(.05*fs)
    z=x[a:b,32:64].astype(np.float32)
    z-=z.mean(axis=0)
    f,p=periodogram(z,fs=fs,axis=0)
    p=np.median(p,axis=1)
    band=(f>=200)&(f<=3000)
    peak=f[band][np.argmax(p[band])]
    rms=np.median(np.std(z,axis=0))
    peakabs=np.max(np.abs(z))
    # Fourier amplitudes of candidate components over the 50-ms window.
    a300=np.sqrt(2*np.max(p[(f>=260)&(f<=340)])*20)
    a2000=np.sqrt(2*np.max(p[(f>=1900)&(f<=2100)])*20)
    print(f"{t:+.2f}..{t+.05:+.2f} sec  rms={rms:.1f}  max={peakabs:.0f}  peakHz={peak:.0f}  A300={a300:.1f} A2k={a2000:.1f}")

print("TOP_BURSTS (50-ms bins, channels 33-64)")
bursts=[]
for a in range(0,n,1500):
    b=min(n,a+1500)
    z=x[a:b,32:64].astype(np.float32)
    score=float(np.median(z.std(axis=0)))
    bursts.append((score,a/fs))
for score,t in sorted(bursts,reverse=True)[:30]:
    print(round(t,3),round(score,1))
