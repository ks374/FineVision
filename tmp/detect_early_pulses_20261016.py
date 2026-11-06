from pathlib import Path
import numpy as np
from scipy.signal import find_peaks
p=Path(r'E:\20261016\Test_Stim_20261016_112800.rec\Test_Stim_20261016_112800.rec')
with p.open('rb') as f:
    while b'</Configuration>' not in f.readline(): pass
    off=f.tell()
size=278; fs=30000
r=np.memmap(p,dtype=f'V{size}',mode='r',offset=off)
x=np.ndarray((len(r),128),dtype='<i2',buffer=r,offset=22,strides=(size,2))
for ch in (8,33,51,64,100):
    y=x[:,ch-1]
    print('CHANNEL',ch)
    for a,b in ((7.5,8.7),(8.9,9.06),(9.07,10.49),(10.51,10.69),(14.3,14.52),(14.53,15.96),(15.98,16.16)):
        seg=y[round(a*fs):round(b*fs)]
        idx,_=find_peaks(-seg,height=500,distance=60)
        isi=np.median(np.diff(idx))/fs if len(idx)>1 else None
        print(a,b,'count <-97.5uV',len(idx),'rate_Hz',round(len(idx)/(b-a),1),'median_ISI_ms',round(isi*1000,3) if isi else None,'ptp_uV',round(float(np.ptp(seg.astype(np.int32)))*.195,1))
    if ch==33:
        for a,b in ((8.0,10.5),(13.4,15.98)):
            seg=y[round(a*fs):round(b*fs)]
            idx,_=find_peaks(-seg,height=500,distance=60)
            times=(idx/fs+a)
            print('PEAKS',a,b,'first',np.round(times[:12],6),'last',np.round(times[-12:],6))
