"""Read-only event-locked artifact timing around 13 optical markers."""
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
from scipy.signal import welch

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
dio=np.ndarray((n,),dtype="u1",buffer=raw,offset=1,strides=(packet,))
fs=30000
level=(dio&1)!=0
changes=np.flatnonzero(level[1:]!=level[:-1])+1
starts=changes[::2]; ends=changes[1::2]
groups=np.r_[0,np.flatnonzero(np.diff(starts)>fs*.5)+1]
print("STIM optical_s burst_on_s delay_ms burst_ms pre_rms stage1_rms burst_rms")
for j,g in enumerate(groups[1:],1):
    s=int(starts[g]); next_g=int(groups[j+1]) if j+1<len(groups) else len(starts)
    start_s=s/fs
    # 5-ms median channel RMS, within 2.5 s after optical onset.
    bins=[]
    for a in range(s,min(n,s+round(2.5*fs)),150):
        y=x[a:a+150,32:64].astype(np.float32)
        bins.append(float(np.median(np.std(y,axis=0))))
    bins=np.array(bins)
    strong=np.flatnonzero(bins>1000)
    if len(strong):
        # first consecutive burst after the optical marker
        a=strong[0]; b=a
        while b+1<len(bins) and bins[b+1]>1000: b+=1
        print(j,round(start_s,3),round(start_s+a*.005,3),round(a*5,1),round((b-a+1)*5,1),
              round(float(np.median(bins[:min(20,len(bins))])),1),
              round(float(np.median(bins[20:max(a-10,21)])),1) if a>30 else None,
              round(float(np.median(bins[a:b+1])),1))
    else: print(j,round(start_s,3),"none")

# Spectral comparison of baseline and apparent pre-burst stage for one event.
s=int(starts[groups[7]])
for label,a,b in (("base",s-fs,s), ("stage1",s+round(.1*fs),s+round(1.2*fs)),
                  ("burst",s+round(1.38*fs),s+round(1.53*fs))):
    y=x[a:b,32:64].astype(np.float32)
    y-=y.mean(axis=0)
    f,p=welch(y,fs=fs,nperseg=min(15000,len(y)),axis=0)
    med=np.median(p,axis=1)
    peak=np.argsort(med[(f>=100)&(f<=5000)])[-12:][::-1]
    ff=f[(f>=100)&(f<=5000)]
    pp=med[(f>=100)&(f<=5000)]
    print(label,"peaks",[(round(float(ff[i]),1),round(float(pp[i]),2)) for i in peak])
