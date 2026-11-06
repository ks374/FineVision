from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=Path(r'E:\20261016\Test_Stim_20261016_115611.rec\Test_Stim_20261016_115611.rec')
with p.open('rb') as f:
    while b'</Configuration>' not in f.readline(): pass
    off=f.tell()
fs=30000; stride=278
r=np.memmap(p,dtype=f'V{stride}',mode='r',offset=off)
x=np.ndarray((len(r),128),dtype='<i2',buffer=r,offset=22,strides=(stride,2))
dio=np.ndarray((len(r),),dtype='u1',buffer=r,offset=1,strides=(stride,))
tick=np.ndarray((len(r),),dtype='<u4',buffer=r,offset=18,strides=(stride,))
pd=(dio&1)!=0
starts=np.flatnonzero(pd[1:]&~pd[:-1])+1
groups=np.r_[0,np.flatnonzero(np.diff(starts)>fs*.5)+1]
pd_on=starts[groups]
assert len(pd_on)==2, pd_on
print('PD_ON',[(int(i),round(i/fs,6)) for i in pd_on])
fig,axes=plt.subplots(2,2,figsize=(14,8))
for row,first in enumerate(pd_on):
    # Large artifact begins near the optical event; use high-amplitude nTrode 33.
    a=first-round(.01*fs); b=first+round(.03*fs)
    hit=np.flatnonzero(np.abs(x[a:b,32].astype(np.int32))>3000)
    stim=a+int(hit[0]) if len(hit) else first
    print('TRAIN',row+1,'pd_s',first/fs,'first_large_artifact_s',stim/fs,
          'delta_ms',(stim-first)/fs*1000,'tick',int(tick[stim]))
    ax=axes[row,0]
    a=first-round(.08*fs); b=first+round(.24*fs)
    for nt in (8,33,51,64):
        y=x[a:b:5,nt-1].astype(np.float32)*.195
        ax.plot((np.arange(a,b,5)-first)/fs*1000,y,label=f'nTrode {nt}',lw=.55)
    ax.axvline(0,color='black',ls='--',lw=1,label='photodiode onset')
    ax.set(xlabel='ms from photodiode onset',ylabel='Raw neural voltage (µV)',
           title=f'Stimulation {row+1}: full train');ax.grid(alpha=.2)
    ax=axes[row,1]
    a=stim-round(.5e-3*fs); b=stim+round(10.5e-3*fs)
    for nt in (8,33,51,64):
        y=x[a:b,nt-1].astype(np.float32)*.195
        ax.plot((np.arange(a,b)-stim)/fs*1000,y,label=f'nTrode {nt}',lw=.65)
    ax.axhline(0,color='black',lw=.5)
    ax.set(xlabel='ms from first large artifact',ylabel='Raw neural voltage (µV)',
           title=f'Stimulation {row+1}: first ~3 pulses');ax.grid(alpha=.2)
axes[0,0].legend(ncol=2,fontsize=8)
fig.suptitle('Trodes raw voltage traces on non-stim channels; exported Stim identifies nTrode 1:1\n'
             'Artifact sign is not a direct measurement of injected-current polarity')
fig.tight_layout()
out=Path(r'D:\Chenghang\FineVision\latest_stim_20261016_two_trains_raw_voltage.png')
fig.savefig(out,dpi=180)
print('OUTPUT',out)
