"""Read EDF events directly and audit 0.25-degree saccade criterion."""
import csv
import ctypes
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path
import statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"D:\Chenghang\FineVision")
SOURCE = Path(r"D:\Chenghang\Training_Log_Huanhuan\20260805\SaccadeMultiStim_20260805_161709")
EDF = SOURCE / "SaccadeMultiStim_20260805_161709_eyelink.edf"
DLL = Path(r"C:\Program Files (x86)\SR Research\EyeLink\libs\x64\edfapi64.dll")
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gain", ROOT/"analysis"/"saccade_gain_models"/"analyze_saccade_models.py")
gain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gain)

lib = ctypes.CDLL(str(DLL))
lib.edf_open_file.argtypes = [ctypes.c_char_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_int)]
lib.edf_open_file.restype = ctypes.c_void_p
lib.edf_get_next_data.argtypes = [ctypes.c_void_p]
lib.edf_get_next_data.restype = ctypes.c_int
lib.edf_get_float_data.argtypes = [ctypes.c_void_p]
lib.edf_get_float_data.restype = ctypes.c_void_p
lib.edf_close_file.argtypes = [ctypes.c_void_p]
error = ctypes.c_int()
handle = lib.edf_open_file(str(EDF).encode("utf-8"),0,1,0,ctypes.byref(error))
if not handle:
    raise RuntimeError(f"EDF open failed {error.value}")
messages=[]
saccades=[]
types=Counter()
try:
    while True:
        kind=lib.edf_get_next_data(handle)
        if kind==0: break
        types[kind]+=1
        if kind not in (6,24): continue
        pointer=lib.edf_get_float_data(handle)
        if not pointer: continue
        ev=gain._EdfAccessEvent.from_address(pointer)
        if kind==24 and ev.message:
            length=ctypes.c_int16.from_address(ev.message).value
            message=ctypes.string_at(ev.message+2,max(0,length)).decode("utf-8",errors="replace")
            messages.append(dict(ms=int(ev.start_time),text=message))
        elif kind==6 and ev.eye==1:
            m=list(ev.measurements)
            sx,sy,ex,ey=m[2],m[3],m[7],m[8]
            if not all(math.isfinite(v) and -10000<v<10000 for v in (sx,sy,ex,ey)):
                continue
            px_per_deg_x=1920/54*58
            px_per_deg_y=1080/30*58
            sxdeg=math.degrees(math.atan((sx-960)*54/1920/58))
            sydeg=math.degrees(math.atan((540-sy)*30/1080/58))
            exdeg=math.degrees(math.atan((ex-960)*54/1920/58))
            eydeg=math.degrees(math.atan((540-ey)*30/1080/58))
            amp=math.hypot(exdeg-sxdeg,eydeg-sydeg)
            ppdx=(m[19]+m[20])/2
            ppdy=(m[21]+m[22])/2
            vendor_amp=(math.hypot((ex-sx)/ppdx,(ey-sy)/ppdy)
                        if ppdx>0 and ppdy>0 else None)
            saccades.append(dict(start_ms=int(ev.start_time),end_ms=int(ev.end_time),
                amplitude_deg=amp, vendor_amp=vendor_amp, duration_ms=int(ev.end_time-ev.start_time),
                peak_velocity=m[16], start_deg=[sxdeg,sydeg],end_deg=[exdeg,eydeg],
                start_px=[sx,sy],end_px=[ex,ey],status_flags=ev.status))
finally:
    lib.edf_close_file(handle)

with (SOURCE/"SaccadeMultiStim_task_log_20260805_161709.csv").open(encoding="utf-8-sig",newline="") as f:
    trials=list(csv.DictReader(f))
msg_by_trial={}
current=None
for item in messages:
    t=item["text"]
    if t.startswith("TRIALID ") and t[8:].isdigit(): current=int(t[8:])
    if current is not None:
        msg_by_trial.setdefault(current,{})
        for code in ("FIX_ON", "GAZE_ACQUIRED", "FIX_OFF", "STIM_ON", "STIM_OFF", "STIM_WINDOW_END", "TRIAL_RESULT"):
            if t.startswith(code+" TRIAL "):
                msg_by_trial[current][code]=item["ms"]

def quantile(values,p):
    if not values: return None
    values=sorted(values)
    index=(len(values)-1)*p
    lo=int(index);hi=min(lo+1,len(values)-1)
    return round(values[lo]+(values[hi]-values[lo])*(index-lo),4)

thresholds=[.25,.35,.5,.7,.75,1.0,1.5,2.0]
epoch={key:[] for key in ("fixation", "gap", "postvisual")}
trial_report=[]
for row in trials:
    n=int(row["Trial"])
    marker=msg_by_trial.get(n,{})
    entered=marker.get("GAZE_ACQUIRED")
    fixoff=marker.get("FIX_OFF")
    stim=marker.get("STIM_ON")
    # Only completed fixation epochs: break/nofix have no valid full interval.
    intervals={"fixation":(entered,fixoff), "gap":(fixoff,stim),
               "postvisual":(stim,stim+467 if stim is not None else None)}
    if row["Status"] in ("Break_1", "nofix_1"):
        intervals["fixation"] = (None,None)
    trial_item=dict(trial=n,status=row["Status"],is_control=row["Is_Control"],
                    target=[float(row["Stim_Pos_X_deg"]),float(row["Stim_Pos_Y_deg"])],
                    markers=marker)
    for name,(a,b) in intervals.items():
        selected=([s for s in saccades if a is not None and b is not None and
                   a <= s["start_ms"] <= b and (name!="fixation" or s["end_ms"]<=b)]
                  if a is not None and b is not None and a<=b else [])
        if a is not None and b is not None and a<=b:
            epoch[name].append(dict(trial=n,duration_ms=b-a,saccades=selected,
                                    status=row["Status"],target=trial_item["target"],
                                    is_control=row["Is_Control"]))
        trial_item[name]=dict(duration_ms=b-a if a is not None and b is not None else None,
                              count=len(selected), qualifying_count=sum(s["amplitude_deg"]>.25 for s in selected))
    trial_report.append(trial_item)

result=dict(source=str(SOURCE),edf_bytes=EDF.stat().st_size,trials=len(trials),
            status_counts=dict(Counter(x["Status"] for x in trials)),
            right_eye_saccades=len(saccades),message_count=len(messages),
            event_type_counts=dict(types),sample_event_examples=saccades[:5],
            event_marker_examples=trial_report[:4],thresholds={})
for name,items in epoch.items():
    all_events=[s for x in items for s in x["saccades"]]
    durations=sum(x["duration_ms"] for x in items)
    section=dict(trial_count=len(items),duration_s=durations/1000,
                 event_count=len(all_events),
                 amp_quantiles={str(q):quantile([s["amplitude_deg"] for s in all_events],q)
                                for q in (0,.1,.25,.5,.75,.9,.95,.99,1)},
                 thresholds={})
    for thresh in thresholds:
        qualifying=[s for s in all_events if s["amplitude_deg"]>thresh]
        with_event=[x for x in items if any(s["amplitude_deg"]>thresh for s in x["saccades"])]
        section["thresholds"][str(thresh)]=dict(event_count=len(qualifying),
            trial_count=len(with_event),trial_rate=(len(with_event)/len(items) if items else None),
            events_per_minute=(len(qualifying)*60000/durations if durations else None))
    result["thresholds"][name]=section
    section["vendor_ppd_at_0_25"] = dict(
        event_count=sum(s["vendor_amp"] is not None and s["vendor_amp"]>.25 for s in all_events),
        trial_count=sum(any(s["vendor_amp"] is not None and s["vendor_amp"]>.25
                            for s in x["saccades"]) for x in items))

# Stimulus trials with a known peripheral visual target: a positive comparison
# for how often a >=threshold first response lands near the displayed cue.
positive=[]
for x in epoch["postvisual"]:
    if x["is_control"]=="True" or x["status"]!="Success": continue
    target=x["target"]
    distance=math.hypot(target[0],target[1])
    if distance<3: continue
    positive.append(x)
pos_stats={}
for thresh in thresholds:
    detected=[]
    correct=[]
    first_distances=[]
    for x in positive:
        selected=next((s for s in x["saccades"] if s["amplitude_deg"]>thresh),None)
        if selected is None: continue
        detected.append(x)
        distance_to_target=math.dist(selected["end_deg"],x["target"])
        first_distances.append(distance_to_target)
        if distance_to_target<=2.5: correct.append(x)
    pos_stats[str(thresh)]=dict(detected_count=len(detected),
        detected_rate=len(detected)/len(positive) if positive else None,
        end_within_2_5deg_count=len(correct),
        end_within_2_5deg_rate=len(correct)/len(positive) if positive else None,
        median_first_endpoint_error_deg=quantile(first_distances,.5))
result["positive_visual_noncontrol_success_target_distance_ge3"]={
    "trial_count":len(positive),"thresholds":pos_stats}

latency=[]
direction=[]
for x in positive:
    s=next((s for s in x["saccades"] if s["amplitude_deg"]>.25),None)
    if not s: continue
    stim=msg_by_trial[x["trial"]]["STIM_ON"]
    latency.append(s["start_ms"]-stim)
    displacement=[s["end_deg"][0]-s["start_deg"][0],s["end_deg"][1]-s["start_deg"][1]]
    target=x["target"]
    cosine=sum(a*b for a,b in zip(displacement,target))/(math.hypot(*displacement)*math.hypot(*target))
    direction.append(cosine)
result["positive_visual_first_event_diagnostics"]={
    "latency_quantiles_ms":{str(q):quantile(latency,q) for q in (0,.1,.25,.5,.75,.9,1)},
    "latency_below_80ms":sum(v<80 for v in latency),
    "latency_80_to_300ms":sum(80<=v<=300 for v in latency),
    "first_event_toward_target_cosine_gt_0_5":sum(v>.5 for v in direction),
    "direction_cosine_quantiles":{str(q):quantile(direction,q) for q in (0,.25,.5,.75,1)}}

fixation_events=[]
for item in epoch["fixation"]:
    for event_index, s in enumerate(item["saccades"],1):
        fixation_events.append(dict(trial=item["trial"],event_in_trial=event_index,
            start_ms=s["start_ms"],end_ms=s["end_ms"],
            amplitude_deg=s["amplitude_deg"],vendor_ppd_amplitude_deg=s["vendor_amp"],
            duration_ms=s["duration_ms"],peak_velocity_deg_s=s["peak_velocity"],
            status_flags=s["status_flags"],trial_status=item["status"]))
assert len(fixation_events)==22
with (OUT/"fixation_saccades_22.csv").open("w",encoding="utf-8-sig",newline="") as file:
    writer=csv.DictWriter(file,fieldnames=list(fixation_events[0]))
    writer.writeheader()
    writer.writerows(fixation_events)

ordered=sorted(fixation_events,key=lambda e:e["amplitude_deg"])
fig,ax=plt.subplots(figsize=(11.5,9))
fig.patch.set_facecolor("white")
xs=[x["amplitude_deg"] for x in ordered]
ys=list(range(1,len(xs)+1))
colors=["#b44338" if x>.25 else "#6e7c86" for x in xs]
ax.hlines(ys,0,xs,colors=colors,linewidth=2.5,zorder=1)
ax.scatter(xs,ys,color=colors,s=68,zorder=3)
ax.axvline(.25,color="#263f80",linestyle="--",linewidth=2,label="0.25° decision threshold")
ax.axvline(1.0,color="#a9a9a9",linestyle=":",linewidth=1.4,label="1.0° reference")
ax.set_yticks(ys,[f"Trial {e['trial']}"+(f" · event {e['event_in_trial']}" if e['event_in_trial']>1 else "")
                 for e in ordered],fontsize=10)
ax.set_xlim(0,3.25)
ax.set_ylim(.2,len(xs)+1.4)
ax.set_xlabel("EyeLink saccade start-to-end amplitude (degrees)",fontsize=12)
ax.set_title("22 saccades during completed central fixation\n"
             "Huanhuan · SaccadeMultiStim · 2026-08-05 16:17",fontsize=14,loc="left")
ax.text(.98,.81,"20 / 22 above 0.25°",transform=ax.transAxes,ha="right",va="top",
        fontsize=13,color="#b44338",fontweight="bold")
for x,y in zip(xs,ys):
    ax.text(min(x+.045,3.01),y,f"{x:.3f}°" if x<.3 else f"{x:.2f}°",
            va="center",fontsize=9)
ax.grid(axis="x",color="#e9edf0",linewidth=.8)
ax.set_axisbelow(True)
ax.legend(loc="lower right",frameon=False,fontsize=10)
for spine in ("top","right"):
    ax.spines[spine].set_visible(False)
fig.text(.09,.025,"Completed fixation: GAZE_ACQUIRED to FIX_OFF; right-eye ENDSACC only. "
         "Amplitude uses task screen geometry (58 cm viewing distance).",fontsize=8,color="#46545f")
fig.tight_layout(rect=(0,.045,1,1))
fig.savefig(OUT/"fixation_saccades_22.png",dpi=180)
plt.close(fig)

(OUT/"threshold_audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in result.items() if k in ("trials","status_counts","right_eye_saccades","thresholds","positive_visual_noncontrol_success_target_distance_ge3","positive_visual_first_event_diagnostics")},ensure_ascii=False,indent=2))
