"""Read-only channel and frequency comparison for one delayed burst."""
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
from scipy.signal import welch

p=Path(r"E:\20261015\STIM_20261015_121533.rec\STIM_20261015_121533.rec")
with p.open("rb") as f:
    lines=[]
    while True:
        z=f.readline();lines.append(z)
        if b"</Configuration>" in z:break
    off=f.tell()
root=ET.fromstring(b"".join(lines))
aux=sum(int(d.attrib["numBytes"]) for d in root.findall(".//HardwareConfiguration/Device"))
nch=sum(len(t.findall("SpikeChannel")) for t in root.findall(".//SpikeNTrode"))
packet=1+aux+4+2*nch
raw=np.memmap(p,mode="r",dtype="u1",offset=off)
x=np.ndarray((len(raw)//packet,nch),dtype="<i2",buffer=raw,offset=1+aux+4,strides=(packet,2))
fs=30000
opt=83.9038
base=x[round((opt-.8)*fs):round((opt-.1)*fs)].astype(np.float32)
stage=x[round((opt+.1)*fs):round((opt+1.2)*fs)].astype(np.float32)
burst=x[round((opt+1.39)*fs):round((opt+1.54)*fs)].astype(np.float32)
for name,a in (("base",base),("stage",stage),("burst",burst)):
    rms=np.std(a,axis=0)
    print(name,"median_RMS_codes",round(float(np.median(rms)),1),
          "nTrode8_HW7_RMS",round(float(rms[7]),1),
          "HW7_rank_largest_first",int(np.count_nonzero(rms>rms[7])+1),
          "min_med_max",tuple(round(float(v),1) for v in (rms.min(),np.median(rms),rms.max())),
          "top_HW",list(np.argsort(rms)[-10:][::-1]))

for name,a in (("base",base),("stage",stage)):
    a=a-a.mean(axis=0)
    f,psd=welch(a,fs=fs,nperseg=15000,axis=0)
    med=np.median(psd,axis=1)
    inds=np.argsort(med[(f>=50)&(f<=5000)])[-15:][::-1]
    ff=f[(f>=50)&(f<=5000)]; pp=med[(f>=50)&(f<=5000)]
    print(name,"peaks_Hz",[(round(float(ff[i]),1),round(float(pp[i]),2)) for i in inds])
    for hz in (280,300,600,900,2000,3700):
        i=np.argmin(abs(f-hz))
        print(name,"Hz",hz,"median_psd",round(float(med[i]),2),"HW7_psd",round(float(psd[i,7]),2))
