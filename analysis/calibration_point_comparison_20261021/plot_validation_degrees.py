import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path(r'D:\Chenghang\FineVision\experiment_logs\Validation_Monkey_H18_20261021_110316_945149')
d=json.loads((p/'validation_offsets.json').read_text(encoding='utf-8'))
t=np.asarray(d['targets_px']); o=np.asarray(d['offsets_right_up_px'])
cm_per_px=np.array([54/1920,30/1080])
angle=lambda v: np.degrees(np.arctan(v*cm_per_px/60))
e=angle(t+o)-angle(t)
plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'axes.unicode_minus':False,'font.size':11})
fig,ax=plt.subplots(figsize=(9,8))
ax.axhline(0,color='0.7',lw=1);ax.axvline(0,color='0.7',lw=1)
ax.scatter(e[:,0],e[:,1],s=48,color='steelblue',label='验证点 1–9',zorder=4)
for i,(x,y) in enumerate(e,1): ax.annotate(str(i),(x,y),xytext=(6,6),textcoords='offset points',fontsize=10)
ax.scatter([0],[0],marker='+',s=180,c='black',lw=2,label='各目标对齐至 (0, 0)',zorder=5)
ax.axvline(.95,color='darkorange',ls='--',lw=1.6,label='最近实验中位偏移 X = +0.95°')
ax.axhline(1.24,color='crimson',ls='--',lw=1.6,label='最近实验中位偏移 Y = +1.24°')
ax.scatter([.95],[1.24],marker='D',s=65,color='crimson',zorder=5)
ax.annotate('(+0.95°, +1.24°)',(.95,1.24),xytext=(-12,14),textcoords='offset points',ha='right',color='crimson')
ax.set(xlim=(-.55,1.5),ylim=(-.55,1.5),xlabel='眼动 − 目标：水平偏差 (°；右为正)',ylabel='眼动 − 目标：垂直偏差 (°；上为正)',title=f'更新前验证：9 点｜视距 60 cm\n径向偏差中位数 {np.median(np.linalg.norm(e,axis=1)):.3f}°')
ax.set_aspect('equal');ax.grid(alpha=.2);ax.legend(loc='lower right',fontsize=9)
fig.text(.5,.025,'屏幕 54 × 30 cm，1920 × 1080 px；原始验证点保持不变，仅转换坐标单位。',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.045,1,1))
for ext in ['png','pdf']: fig.savefig(p/f'validation_before_update_deg_60cm.{ext}',dpi=200)
np.savetxt(p/'validation_before_update_deg_60cm.csv',np.column_stack([np.arange(1,10),e]),delimiter=',',header='point,x_offset_deg,y_offset_deg',comments='')
print(p/'validation_before_update_deg_60cm.png')
