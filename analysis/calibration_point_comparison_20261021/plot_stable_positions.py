from pathlib import Path
import json,csv,re,math,bisect
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
root=Path(r'D:\Chenghang\FineVision');logs=root/'experiment_logs';out=root/'analysis/calibration_point_comparison_20261021';out.mkdir(exist_ok=True)
calroot=logs/'Calibration_Monkey_H18_20261021_104624_135621';valroot=logs/'Validation_Monkey_H18_20261021_110316_945149';taskroot=logs/'Saccade_Elec_Intan_Monkey_H18_20261021_115959_362647'
cal=json.loads((calroot/'session.json').read_text(encoding='utf-8'));val=json.loads((valroot/'session.json').read_text(encoding='utf-8'));session=json.loads((taskroot/'session.json').read_text(encoding='utf-8'));params=session['parameters']
def angles(xy,d=60):
 xy=np.asarray(xy,dtype=float);return np.degrees(np.arctan(xy*np.array([54/1920,30/1080])/d))
def affine(a,c):
 a=np.asarray(a,dtype=float);return np.column_stack((c['ox']+c['gx']*a[:,0]+c['gxy']*a[:,1],c['oy']+c['gyx']*a[:,0]+c['gy']*a[:,1]))
rows=[]
def custom_rows(data,c,group):
 for point in data['Calibration_Report']['points']:
  a=np.array([[s['xr'],s['yr']] for s in point['collection']['samples'] if s['xr'] is not None and s['yr'] is not None]);valid=np.all(np.isfinite(a),axis=1);a=a[valid]
  xy=angles(affine(a,c));target=angles(point['target_px']);median=np.median(xy,axis=0)
  rows.append(dict(group=group,point=point['index'],target_x_deg=target[0],target_y_deg=target[1],gaze_x_deg=median[0],gaze_y_deg=median[1],n_samples=len(a),estimator='coordinatewise_median_RAW_samples_after_affine',window='accepted_final_100ms'))
custom_rows(cal,cal['right_cal'],'custom_calibration_1046_in_sample_fit')
custom_rows(val,val['Mapping_Before']['right'],'custom_validation_1103_current_mapping')
messages=json.loads((out/'native_edf_messages.json').read_text(encoding='utf-8'));native_rows=[]
for message in messages:
 m=re.search(r'VALIDATE R .*?POINT (\d+).*?at (\d+),(\d+)\s+OFFSET ([\d.]+) deg\.\s+([\d.-]+),([\d.-]+) pix',message['message'])
 if not m:continue
 i,x,y,err,dx,dy=m.groups();x,y,dx,dy=map(float,(x,y,dx,dy));target=angles((x-960,540-y),61);gaze=angles((x+dx-960,540-y-dy),61)
 row=dict(group='native_validation_host_report',point=int(i)+1,target_x_deg=target[0],target_y_deg=target[1],gaze_x_deg=gaze[0],gaze_y_deg=gaze[1],n_samples=None,estimator='target_plus_Host_reported_offset_NOT_sample_median',window='Host_validation_report');rows.append(row);native_rows.append(row)
assert len(native_rows)==9
trials=[json.loads(l) for l in (taskroot/'trials.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
intervals=[]
for trial in trials:
 if 'fixoff_pc' not in trial:continue
 end=trial['fixoff_pc']*1000+trial['clock_offset_ms'];start=max(end-100,trial['fixon_pc']*1000+trial['clock_offset_ms'])
 intervals.append((start,end,trial['attempt']))
intervals.sort();starts=[r[0] for r in intervals];by={};last=None
with (taskroot/'raw_gaze_samples.jsonl').open(encoding='utf-8') as f:
 for line in f:
  sample=json.loads(line)
  if not sample.get('valid') or sample.get('screen_px') is None:continue
  t=sample['sample_eyelink_ms']
  if t==last:continue
  last=t;i=bisect.bisect_right(starts,t)-1
  if i>=0 and t<=intervals[i][1]:
   sx,sy=sample['screen_px'];by.setdefault(intervals[i][2],[]).append((sx-960,540-sy))
trialrows=[]
for attempt,a in by.items():
 if len(a)<3:continue
 center=np.median(angles(a),axis=0);trialrows.append(dict(attempt=attempt,n_samples=len(a),median_x_deg=float(center[0]),median_y_deg=float(center[1])))
allcenters=np.array([[r['median_x_deg'],r['median_y_deg']] for r in trialrows]);fix=np.median(allcenters,axis=0)
rows.append(dict(group='task_fixation_minus3_plus5',point=0,target_x_deg=-3.,target_y_deg=5.,gaze_x_deg=fix[0],gaze_y_deg=fix[1],n_samples=sum(r['n_samples'] for r in trialrows),estimator='median_of_per_trial_medians',window='last_100ms_before_FIXOFF'))
for name,data in [('stable_point_positions.csv',rows),('fixation_trial_medians.csv',trialrows)]:
 with (out/name).open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
fig,axs=plt.subplots(2,2,figsize=(14,13),layout='constrained')
colors=['#2378ac','#23865e','#d47a1c']
groups=['custom_calibration_1046_in_sample_fit','custom_validation_1103_current_mapping','native_validation_host_report']
titles=['A  自定义校准 10:46：当次拟合后的采样位置','B  自定义验证 11:03：本次任务实际使用的映射','C  原生 HV9 验证：EDF 内 Host 报告的位置']
for ax,group,title,color in zip(axs.flat,groups,titles,colors):
 rs=[r for r in rows if r['group']==group]
 ax.axhline(0,color='.75',lw=.8);ax.axvline(0,color='.75',lw=.8);ax.grid(alpha=.18)
 ax.scatter([r['target_x_deg'] for r in rs],[r['target_y_deg'] for r in rs],facecolors='none',edgecolors=color,s=100,lw=1.5,label='目标位置',zorder=3)
 ax.scatter([r['gaze_x_deg'] for r in rs],[r['gaze_y_deg'] for r in rs],color=color,s=36,label='Host 报告位置（非中位数）' if group.startswith('native') else '稳定采样窗的中位眼位',zorder=4)
 for r in rs:
  ax.annotate('',xy=(r['gaze_x_deg'],r['gaze_y_deg']),xytext=(r['target_x_deg'],r['target_y_deg']),arrowprops=dict(arrowstyle='->',color=color,lw=1))
  ax.annotate(str(r['point']),(r['target_x_deg'],r['target_y_deg']),xytext=(6,6),textcoords='offset points',color=color,fontsize=9)
 ax.set(xlim=(-14,14),ylim=(-14,14),aspect='equal',title=title,xlabel='水平视角（°，右为正）',ylabel='垂直视角（°，上为正）');ax.legend(loc='lower left',fontsize=9)
 if group=='custom_calibration_1046_in_sample_fit':ax.text(.02,.98,'使用这批点拟合出的系数；不是独立验证\n该次旧映射并非随后 saccade 使用的最终映射',transform=ax.transAxes,va='top',fontsize=9)
 elif group=='custom_validation_1103_current_mapping':ax.text(.02,.98,'每点约 100 ms RAW 样本；使用原映射，未重拟合\n与最近 saccade 会话中的校准快照一致',transform=ax.transAxes,va='top',fontsize=9)
 else:ax.text(.02,.98,'原生 EDF：0 个连续样本，无法算采样中位数\n位置＝验证目标＋报告偏移；角点为内缩验证位置',transform=ax.transAxes,va='top',fontsize=9)
ax=axs[1,1];ax.grid(alpha=.2);ax.scatter(allcenters[:,0],allcenters[:,1],s=12,alpha=.25,c='#777777',label=f'逐试次末尾100ms中位数（n={len(trialrows)}）')
ax.scatter([-3],[5],marker='*',s=180,c='#bd3550',label='任务注视点 (−3, 5)',zorder=5);ax.scatter([-3],[6],marker='^',s=70,c='#7145a0',label='参考点 (−3, 6)')
ax.scatter([fix[0]],[fix[1]],marker='D',s=90,c='#152d4a',label=f'汇总中位眼位 ({fix[0]:.2f}, {fix[1]:.2f})',zorder=6)
ax.annotate('',xy=fix,xytext=(-3,5),arrowprops=dict(arrowstyle='->',color='#152d4a',lw=1.8));ax.annotate(f'右 {fix[0]+3:.2f}°，上 {fix[1]-5:.2f}°',xy=fix,xytext=(14,12),textcoords='offset points',fontsize=11)
ax.set(xlim=(-5,1),ylim=(3,9),aspect='equal',title='D  最近 saccade：注视 (−3, 5) 的稳定位置',xlabel='水平视角（°，右为正）',ylabel='垂直视角（°，上为正）');ax.legend(loc='lower left',fontsize=9)
fig.suptitle('目标位置与记录中的稳定眼位：空心＝目标，实心＝测得/报告位置',fontsize=16)
fig.savefig(out/'stable_eye_positions.png',dpi=180,bbox_inches='tight');fig.savefig(out/'stable_eye_positions.pdf',bbox_inches='tight')
summary=dict(native_edf_continuous_samples=0,native_report_points=9,custom_calibration_points=9,custom_validation_points=9,task_completed_fixation_trials=len(trialrows),task_raw_samples=sum(r['n_samples'] for r in trialrows),fixation_target=[-3,5],fixation_median=fix.tolist(),fixation_offset=(fix-np.array([-3,5])).tolist(),sources=dict(custom_calibration=str(calroot),custom_validation=str(valroot),native_edf=str(logs/'eyelink_native_calibration_Monkey_I18_20261021_104318_620401.edf'),task=str(taskroot)),coordinate_convention='atan(centered_physical_displacement/viewing_distance); custom/task60cm, native61cm; right/up positive',task_estimator='coordinate-wise median of per-trial medians of valid RAW-affine positions during last100ms before completed fixation offset',notes=['Calibration medians after fitting the same data are not independent accuracy estimates.','Native calibration trajectory samples are absent; native VALIDATION offsets are shown instead.','Native session subject label Monkey_I18; custom/task label Monkey_H18; verify identity before biological comparisons.'])
(out/'stable_positions_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
