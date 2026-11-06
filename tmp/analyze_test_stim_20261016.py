from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

p = Path(r"E:\20261016\Test_Stim_20261016_112800.rec\Test_Stim_20261016_112800.rec")
with p.open('rb') as f:
    header = b''
    while b'</Configuration>' not in header:
        header += f.readline()
    off = f.tell()
root = ET.fromstring(header)
hw = root.find('HardwareConfiguration')
aux = sum(int(d.attrib['numBytes']) for d in hw.findall('Device'))
nch = sum(len(n.findall('SpikeChannel')) for n in root.findall('.//SpikeNTrode'))
size = 1+aux+4+nch*2
dt = np.dtype([('mark','u1'),('aux',f'V{aux}'),('tick','<u4'),('neural',f'V{nch*2}')])
r = np.memmap(p, dtype=dt, mode='r', offset=off)
x = np.ndarray((len(r),nch), dtype='<i2', buffer=r, offset=1+aux+4, strides=(size,2))
clock = np.ndarray((len(r),), dtype='<u8', buffer=r, offset=1+1+8, strides=(size,))
print('n',len(r),'duration',len(r)/30000,'aux',aux,'nch',nch,'clock_first_last',clock[:5],clock[-5:])
print('tick_first_last',r['tick'][0],r['tick'][-1])
from datetime import datetime, timezone, timedelta
for val in (clock[0],clock[-1],clock[round(10.51*30000)],clock[round(15.98*30000)]):
    print('CLOCK',int(val),datetime.fromtimestamp(int(val)/1e9,timezone(timedelta(hours=8))))
for stamp in ('2026-10-16T11:28:36.839951+08:00','2026-10-16T11:28:42.298730+08:00'):
    ns=int(datetime.fromisoformat(stamp).timestamp()*1e9)
    idx=int(np.searchsorted(clock,ns))
    print('CALL',stamp,'sample_by_clock',idx,'relative_s',idx/30000,'clock',int(clock[idx]) if idx<len(clock) else 'beyond')
print('clock_diff',np.percentile(np.diff(clock.astype(np.int64)),[0,1,50,99,100]))
# 10 ms bins: common-mode artifact and across-channel RMS in the voltage recording.
step=300
for a in range(0,len(r)-step,step):
    z=x[a:a+step].astype(np.float32)
    med=np.median(np.abs(z),axis=1)
    score=float(np.median(med))
    rms=float(np.median(np.std(z,axis=0)))
    if score>500 or rms>600:
        print('HOT',round(a/30000,3),'score',round(score,1),'rms',round(rms,1))
# summarize every 100 ms for short output
for a in range(0,len(r)-3000,3000):
    z=x[a:a+3000].astype(np.float32)
    med=np.median(z,axis=1)
    rms=float(np.median(np.std(z,axis=0)))
    p95=float(np.percentile(np.abs(med),95))
    print('BIN',round(a/30000,2),'rms',round(rms,1),'common95',round(p95,1))
