from pathlib import Path
import numpy as np
from scipy.signal import welch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=Path(r'E:\20261016\Test_Stim_20261016_112800.rec\Test_Stim_20261016_112800.rec')
with p.open('rb') as f:
    while b'</Configuration>' not in f.readline(): pass
    off=f.tell()
size=278; aux=17; nch=128; fs=30000
r=np.memmap(p,dtype=f'V{size}',mode='r',offset=off)
x=np.ndarray((len(r),nch),dtype='<i2',buffer=r,offset=1+aux+4,strides=(size,2))
clock=np.ndarray((len(r),),dtype='<u8',buffer=r,offset=10,strides=(size,))
for n in (8,33,51,64,100):
    print('CHANNEL',n)
    for label,a,b in [('baseline',7.5,8.7),('post-command',9.15,10.35),('before-trigger',14.65,15.85)]:
        y=x[round(a*fs):round(b*fs),n-1].astype(float)
        f,ps=welch(y,fs,nperseg=8192)
        sel=(f>=50)&(f<=5000)
        ids=np.argsort(ps[sel])[-5:]
        peaks=sorted(zip(f[sel][ids],ps[sel][ids]),key=lambda z:-z[1])
        print(label,'sd_uV',round(y.std()*.195,2),'peaks',[(round(q,1),round(v,1)) for q,v in peaks])
fig,ax=plt.subplots(3,1,figsize=(13,9),sharex=False)
for n in (8,33,51,64):
    a=round(8.8*fs);b=round(10.75*fs);step=10
    ax[0].plot(np.arange(a,b,step)/fs,x[a:b:step,n-1]*.195,label=f'nTrode {n}',lw=.45)
ax[0].axvline(9.0699,color='r',label='Python trigger call')
ax[0].axvline(10.51,color='k',ls='--',label='strong train onset')
ax[0].set_ylabel('Recorded raw, µV');ax[0].legend(ncol=3,fontsize=8)
for n in (8,33,51,64):
    a=round(9.1*fs);b=round(9.15*fs)
    ax[1].plot(np.arange(a,b)/fs,x[a:b,n-1]*.195,label=f'nTrode {n}',lw=.6)
ax[1].set_ylabel('Raw, µV');ax[1].set_title('50 ms after command')
for n in (8,33,51,64):
    a=round(10.52*fs);b=round(10.57*fs)
    ax[2].plot(np.arange(a,b)/fs,x[a:b,n-1]*.195,label=f'nTrode {n}',lw=.6)
ax[2].set_ylabel('Raw, µV');ax[2].set_title('50 ms during strong train')
for a in ax:a.grid(alpha=.2);a.set_xlabel('Seconds since first sample')
fig.tight_layout()
out=Path(r'D:\Chenghang\FineVision\test_stim_20261016_command_vs_waveform.png')
fig.savefig(out,dpi=170)
print('OUTPUT',out)
