from pathlib import Path
import json,math,csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
plt.rcParams['axes.unicode_minus']=False
root=Path(r'D:\Chenghang\FineVision')
out=root/'analysis/calibration_point_comparison_20261021'
custom=json.loads((root/'params_CalibrationTask.json').read_text(encoding='utf-8'))['parameters']
native_path=root/'experiment_logs/eyelink_native_calibration_Monkey_I18_20261021_104318_620401.json'
native=json.loads(native_path.read_text(encoding='utf-8'))
coords=[]
def angle(px,cm,res,distance):return math.degrees(math.atan(px*cm/res/distance))
for y in [-custom['Calibration Vertical Extent (deg)'],0,custom['Calibration Vertical Extent (deg)']]:
 for x in [-custom['Calibration Horizontal Extent (deg)'],0,custom['Calibration Horizontal Extent (deg)']]:
  px=2*custom['Viewing Distance (cm)']*math.tan(math.radians(x)/2)*custom['Screen Width (px)']/custom['Subject Monitor Width (cm)']
  py=2*custom['Viewing Distance (cm)']*math.tan(math.radians(y)/2)*custom['Screen Height (px)']/custom['Subject Monitor Height (cm)']
  coords.append(dict(group='custom',x_deg=angle(px,54,1920,60),y_deg=angle(py,30,1080,60),parameter_x_deg=x,parameter_y_deg=y))
seen=set()
for event in native['reward_events']:
 if event['reason']=='calibration_or_validation_complete':break
 point=tuple(event['target'])
 if point in seen:continue
 seen.add(point)
 coords.append(dict(group='native',x_deg=angle(point[0]-960,54,1920,61),y_deg=angle(540-point[1],30,1080,61),parameter_x_deg='',parameter_y_deg=''))
assert len(seen)==9
with (out/'point_coordinates.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(coords[0]));w.writeheader();w.writerows(coords)
fig,(ax,zoom)=plt.subplots(1,2,figsize=(14,7),gridspec_kw={'width_ratios':[1.25,1]},layout='constrained')
styles={'custom':dict(color='#1876b9',marker='o',label='自定义 RAW 校准九点'),'native':dict(color='#dc7a1f',marker='s',label='EyeLink 原生 HV9 校准九点')}
for a in (ax,zoom):
 a.set_aspect('equal');a.axhline(0,color='#a6a6a6',lw=.8);a.axvline(0,color='#a6a6a6',lw=.8)
 a.grid(alpha=.2);a.set_xlabel('水平视角（°，右为正）');a.set_ylabel('垂直视角（°，上为正）')
 for group,st in styles.items():
  pts=[r for r in coords if r['group']==group]
  a.scatter([r['x_deg'] for r in pts],[r['y_deg'] for r in pts],s=70,facecolors='white',edgecolors=st['color'],marker=st['marker'],lw=1.8,label=st['label'],zorder=3)
 a.scatter([-3],[5],s=115,c='#b7354e',marker='*',zorder=5,label='指定点 (−3, 5)')
 a.scatter([-3],[6],s=75,c='#673e9c',marker='^',zorder=5,label='指定点 (−3, 6)')
ax.set(xlim=(-14,14),ylim=(-14,14),title='完整位置比较')
for r in coords:
 if abs(r['x_deg'])<.1 and abs(r['y_deg'])<.1:continue
 ax.annotate(f"({r['x_deg']:.2f}, {r['y_deg']:.2f})",(r['x_deg'],r['y_deg']),xytext=(0,9),textcoords='offset points',ha='center',fontsize=8,color=styles[r['group']]['color'])
ax.add_patch(Rectangle((-9,3),10,4,fill=False,ls='--',lw=1.1,color='#666666'))
zoom.set(xlim=(-9,1),ylim=(3,7),title='注视点附近放大')
zoom.set_xticks(range(-9,2,2));zoom.set_yticks([3,4,5,6,7])
zoom.annotate('(−3, 5)',(-3,5),xytext=(12,-19),textcoords='offset points',color='#b7354e',fontsize=12)
zoom.annotate('(−3, 6)',(-3,6),xytext=(12,8),textcoords='offset points',color='#673e9c',fontsize=12)
for r in coords:
 if r['group']=='custom' and r['y_deg']>0 and r['x_deg']<=0:
  zoom.annotate(f"({r['x_deg']:.2f}, {r['y_deg']:.2f})",(r['x_deg'],r['y_deg']),xytext=(0,-20),textcoords='offset points',ha='center',color=styles['custom']['color'],fontsize=10)
zoom.annotate('高出 1°',(-3,5.5),xytext=(-65,0),textcoords='offset points',va='center',fontsize=10)
zoom.annotate('',xy=(-3,5.9),xytext=(-3,5.1),arrowprops=dict(arrowstyle='<->',color='#666666'))
handles,labels=ax.get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=2,frameon=False)
fig.suptitle('校准目标与指定注视点位置',fontsize=17)
fig.savefig(out/'calibration_points.png',dpi=190,bbox_inches='tight')
fig.savefig(out/'calibration_points.pdf',bbox_inches='tight')
(out/'notes.txt').write_text('坐标统一采用 atan(离屏幕中心的物理位移/视距)，屏幕中心(960,540)。自定义读取当前参数：视距60cm，屏幕54×30cm，参数±8°、±5°。原生读取2026-10-21 10:43 HV9记录中的首轮九个实际目标，视距61cm；原生验证阶段的内缩角点不包含。两份配置中的subject ID不同，本图仅比较目标几何。自定义位置函数使用2*d*tan(angle/2)，与统一中心视角定义略不同，因此参数8°/5°在图中为7.96°/4.99°。',encoding='utf-8')
print(out/'calibration_points.png')
print([(round(r['x_deg'],3),round(r['y_deg'],3)) for r in coords if r['group']=='native'])
