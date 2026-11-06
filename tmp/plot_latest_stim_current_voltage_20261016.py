from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

rec=Path(r'E:\20261016\Test_Stim_20261016_115611.rec\Test_Stim_20261016_115611.rec')
stim=Path(r'D:\Chenghang\FineVision\tmp\stim_export_20261016_115611\Test_Stim_20261016_115611.stimulation\Test_Stim_20261016_115611.stimulation_nt1ch1.dat')
with rec.open('rb') as f:
    while b'</Configuration>' not in f.readline(): pass
    roff=f.tell()
with stim.open('rb') as f:
    h=b''
    while b'<End settings>' not in h:h+=f.readline()
    soff=f.tell()
fs=30000
r=np.memmap(rec,mode='r',dtype='V278',offset=roff)
x=np.ndarray((len(r),128),dtype='<i2',buffer=r,offset=22,strides=(278,2))
s=np.memmap(stim,mode='r',dtype='<f4',offset=soff)
assert len(r)==len(s)
ids=np.flatnonzero(s)
cut=np.flatnonzero(np.diff(ids)>fs)+1
events=np.split(ids,cut)
assert len(events)==2

fig,ax=plt.subplots(4,2,figsize=(14,11))
for col,ev in enumerate(events):
    start,end=int(ev[0]),int(ev[-1])
    print('EVENT',col+1,'start_s',start/fs,'last_nonzero_s',end/fs,
          'nonzero_samples',len(ev),'unique_values',np.unique(s[ev]))
    # The file labels the field nA, but all values are 64x the programmed nA.
    # Plot raw exported values, without presenting them as delivered current.
    a=start-30;b=start+round(.18*fs)
    t=(np.arange(a,b)-start)/fs*1000
    ax[0,col].step(t,s[a:b],where='post',lw=.8,color='#7b2f56')
    ax[0,col].set(xlabel='ms from first nonzero Stim sample',ylabel='Exported Stim value',
                  title=f'Event {col+1}: exported Stimulation trace (0 or 512000)')
    ax[0,col].set_xlim(-1,175)
    a=start-15;b=start+round(.011*fs)
    t=(np.arange(a,b)-start)/fs*1000
    ax[1,col].step(t,s[a:b],where='post',lw=1.2,color='#7b2f56')
    ax[1,col].set(xlabel='ms from first nonzero Stim sample',ylabel='Exported Stim value',
                  title=f'Event {col+1}: first ~3 periods')
    ax[2,col].step(t,x[a:b,0],where='post',color='#1966b3',lw=.7)
    ax[2,col].axhline(0,color='black',lw=.4)
    ax[2,col].set(xlabel='ms from first nonzero Stim sample',ylabel='Raw 16-bit word',
                  title=f'Event {col+1}: nTrode 1 raw words (not voltage during stimulation)')
    for nt,color in ((33,'#d25a21'),(8,'#31824b'),(51,'#b74949')):
        ax[3,col].plot(t,x[a:b,nt-1]*.195,label=f'nTrode {nt}',lw=.7,color=color)
    ax[3,col].axhline(0,color='black',lw=.4)
    ax[3,col].set(xlabel='ms from first nonzero Stim sample',ylabel='Raw neural voltage (µV)',
                  title=f'Event {col+1}: non-stim channels')
    ax[3,col].legend(fontsize=8)
    for row in range(4):ax[row,col].grid(alpha=.2)
fig.suptitle('Only nTrode 1:1 has nonzero exported Stimulation data. Both phases are unsigned in this export.\n'
             '512000 is an encoded value, not calibrated delivered current or electrode voltage.')
fig.tight_layout()
out=Path(r'D:\Chenghang\FineVision\latest_stim_20261016_current_and_voltage.png')
fig.savefig(out,dpi=180)
print('OUTPUT',out)
