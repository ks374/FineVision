from pathlib import Path
import numpy as np

folder=Path(r'D:\Chenghang\FineVision\tmp\stim_export_20261016_115611\Test_Stim_20261016_115611.stimulation')
bands=[]
for p in folder.glob('*nt*ch1.dat'):
    with p.open('rb') as f:
        head=b''
        while b'<End settings>' not in head:
            head+=f.readline()
        off=f.tell()
    x=np.memmap(p,mode='r',dtype='<f4',offset=off)
    ids=np.flatnonzero(x)
    if len(ids):
        name=p.stem
        nt=int(name.rsplit('_nt',1)[1].split('ch',1)[0])
        vals,counts=np.unique(x[ids],return_counts=True)
        bands.append((nt,len(ids),round(ids[0]/30000,6),round(ids[-1]/30000,6),list(zip(vals.tolist(),counts.tolist()))))
print('NONZERO_CHANNELS',sorted(bands))
for nt in (1,8):
    p=folder/f'Test_Stim_20261016_115611.stimulation_nt{nt}ch1.dat'
    with p.open('rb') as f:
        head=b''
        while b'<End settings>' not in head:
            head+=f.readline()
        off=f.tell()
    x=np.memmap(p,mode='r',dtype='<f4',offset=off)
    ids=np.flatnonzero(x)
    print('NT',nt,'header',head.decode('ascii',errors='replace').splitlines()[:4])
    print('NT',nt,'nonzero',len(ids),'first',ids[:20]/30000,'first_samples',x[ids[0]-5:ids[0]+20] if len(ids) else None)
