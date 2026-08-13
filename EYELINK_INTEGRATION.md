# FineVision eye-tracker structure

FineVision keeps separate, clearly named QY and EyeLink entry scripts while
sharing the experiment state machines. This prevents the two hardware versions
of a task from drifting apart.

## Runtime flow

```text
*_QY.py or *_EyeLink.py
        |
        v
shared task module (stimulus, trial state, reward, behavior CSV)
        |
        v
eyetracker.create_tracker_runtime(...)
        |
        +-- QYBackend ------> QY worker process ------> SharedGazeData
        |
        +-- EyeLinkBackend -> PyLink / EyeLink Host --> EDF
        |
        +-- SimulatedBackend -------------------------> mouse gaze
```

Every task receives an object with the same gaze methods:

- `get_latest()` returns the latest source-coordinate left/right sample.
- `get_latest_cal()` returns FineVision task coordinates and validity.
- `set_calibration_left/right()` stores FineVision's custom mapping.

EyeLink is configured with `sample_source: "gaze"`. PyLink supplies EyeLink's
calibrated right-eye screen-pixel coordinates. The backend converts the
top-left EyeLink coordinate system to centered FineVision coordinates and
deliberately bypasses FineVision's affine calibration, preventing accidental
double calibration. HREF plus FineVision affine calibration remains available
as a fallback configuration.

## Entry scripts

| Task | QY entry | EyeLink entry |
| --- | --- | --- |
| Full calibration | `Calibration_Task_QY.py` | `Calibration_Task_EyeLink.py` |
| Quick calibration | `Quick_calib_task_QY.py` | `Quick_calib_task_EyeLink.py` |
| Saccade | `SaccadeTask_QY.py` | `SaccadeTask_EyeLink.py` |
| Multi-stim saccade | `SaccadeMultiStimTask_QY.py` | `SaccadeMultiStimTask_EyeLink.py` |
| Orientation 2AFC training | `Orientation2AFCTrainingTask_QY.py` | `Orientation2AFCTrainingTask_EyeLink.py` |
| Orientation Bar 2AFC training | `OrientationBar2AFCTrainingTask_QY.py` | `OrientationBar2AFCTrainingTask_EyeLink.py` |
| Moving bar | `Fixation_movingbar_QY.py` | `Fixation_movingbar_EyeLink.py` |
| Classic fixation | `FixationTask_QY.py` | `FixationTask_EyeLink.py` |
| Manual heat-map mapping | `FixationTask_hmap_QY.py` | `FixationTask_hmap_EyeLink.py` |
| Fixation with bar | `FixationTask_With_bar_QY.py` | `FixationTask_With_bar_EyeLink.py` |
| Fixation grating | `Fixation_Stim_Grate_QY.py` | `Fixation_Stim_Grate_EyeLink.py` |
| Automatic RF mapping | `RF_Mapping_QY.py` | `RF_Mapping_EyeLink.py` |

The original task filenames remain backward-compatible QY entry points.

## EyeLink setup

1. Install the EyeLink Developers Kit and the matching PyLink package in the
   Python environment used by FineVision. SR Research currently documents:

   ```powershell
   python -m pip install --index-url=https://pypi.sr-support.com sr-research-pylink
   ```
2. Connect the task computer to the EyeLink Host using the dedicated Ethernet
   link.
3. Confirm the Host address in `eyelink_setting.json` (default `100.1.1.1`).
4. On the Host, position the camera and confirm stable right-eye pupil/CR
   tracking.
5. Run `EyeLink_Native_Calibration.py`, complete HV5 calibration and validation,
   and leave that successful EyeLink calibration active.
6. Run the desired `*_EyeLink.py` task. Do not run FineVision's custom
   calibration in the normal GAZE workflow.

For the fallback HREF workflow, change `sample_source` to `href`, select
`eyelink_default_setting.json`, and run `Calibration_Task_EyeLink.py` before
the experiment.

### Native EyeLink calibration from the task computer

`EyeLink_Native_Calibration.py` is a standalone launcher for EyeLink's own
camera setup, calibration, and validation interface.  The EyeLink Host TRACK
application must already be running.  Launching the script without arguments
opens the same categorized, scrollable parameter UI used by the multi-stim
saccade task. HV5 and HV9 are selectable; subject display `1`, HV5, and
automatic reward on target advance are the defaults. Viewing distance, monitor
dimensions, fixation-point radius, calibrated Gray background level, and the
outer target eccentricity can be edited and are saved in
`params_EyeLinkNativeCalibration.json`. The target extent remains limited to
12 degrees per axis. The task reuses FineVision's Arduino controller and writes
both an EDF and a JSON session/event log under `experiment_logs/`.

```powershell
python EyeLink_Native_Calibration.py
```

For a fixed no-dialog launch on display 1:

```powershell
python EyeLink_Native_Calibration.py --screen 1 --no-dialog
```

Use `--reward-mode manual` to disable EyeLink auto-sequencing. In manual mode,
pressing SPACE while a calibration target is visible both submits the target
to EyeLink and delivers the configured reward. Use `--reward-mode off` to run
without opening the Arduino controller. The official
`EyeLinkCoreGraphicsPsychoPy.py` installed with the Developers Kit samples is
loaded in place; it is not copied into FineVision.

The native-calibration EDF includes EyeLink's calibration/validation records
and FineVision messages for session start/end, target on/off, manual acceptance,
reward, and good/error results. EyeLink's native calibration state controls its
own sample collection; this EDF is not a substitute for the continuous 1000-Hz
recording created during a normal task.

EyeLink tasks do not create the QY gaze CSV. The Host records full-rate samples
in EDF and FineVision downloads that EDF when the task closes. Behavior remains
in the task CSV.

## FineVision affine calibration

All task code still reads one hardware-neutral gaze position from
`get_latest_cal()`. QY and the optional EyeLink HREF workflow apply a complete
two-dimensional affine mapping for each eye:

```text
screen_x = ox + gx * raw_x + gxy * raw_y
screen_y = oy + gyx * raw_x + gy * raw_y
```

Legacy QY and EyeLink JSON files containing only `ox`, `oy`, `gx`, and `gy`
remain valid: missing `gxy` and `gyx` values are treated as zero. A new full
calibration saves `model: "affine_2d"` and all six coefficients.

The normal EyeLink GAZE workflow does not apply this equation. GAZE is already
calibrated by the EyeLink Host; the backend only changes coordinate origin and
Y direction.

`Calibration_Task.py` also uses the categorized parameter UI. Its nine target
positions are defined in degrees rather than fixed pixels and converted using
the selected viewing distance and physical monitor dimensions. Fixation point
radius, fixation-window radius, timing, reward duration, and calibrated Gray
background are adjustable in `params_CalibrationTask.json`. In GAZE mode this
task can produce a report, but it does not overwrite the active identity file
or apply a second calibration.

The timestamped `eyelink_calibration_*.json` also contains a
`Calibration_Report`. It records every target, every accepted raw sample and
EyeLink timestamp, the 100-ms raw mean, fitted prediction, residual, and quality
metrics. The quadrant-IV comparison has three distinct quantities:

- `baseline_9_on_extra_q4`: the old nine-point model predicts the four added
  points without having fitted them.
- `affine_all_training_on_extra_q4`: residual on points used in the final fit;
  useful but optimistic.
- `affine_all_leave_one_out_q4`: each added point is predicted after excluding
  that point. `estimated_q4_rmse_improvement_percent` compares this with the
  nine-point baseline and is the preferred estimate of improvement.

## EDF and behavior-file alignment

Calibration writes `CAL_POINT_ONSET`, `CAL_POINT_OFF`, `CAL_SAMPLE_START`,
`CAL_SAMPLE_END`, `CAL_POINT_ACCEPTED`, retry/abort events, and the final
`CAL_MODEL`. Saccade and
2AFC tasks write `TRIALID`, per-trial geometry/timing variables, flip-aligned
display events (`FIX_ON`, `STIM_ON`, `CHOICE_ON`, corresponding off events),
gaze acquisition/target entry/choice, reward, and `TRIAL_RESULT`. Event messages
and gaze samples therefore share the EyeLink Host clock. The behavior CSV uses
the local FineVision clock. Join the files by session identity and trial number;
do not compare the two clock values directly.

EyeLink gaze is intentionally not smoothed for online decisions. QY retains the
existing five-frame operator-view smoothing. For physical display-onset or
neural-system synchronization at millisecond precision, continue to use the
photodiode/TTL signal as the final timing reference.

## In-session recalibration

`SaccadeMultiStimTask_EyeLink.py` and
`Orientation2AFCTrainingTask_EyeLink.py` can reopen EyeLink's native setup
screen from the `N`-key runtime menu. FineVision stops recording, leaves the
current Host EDF open, hides the running subject window, and creates a dedicated
full-screen calibration window on subject screen 1 before calling
`doTrackerSetup()`.
FineVision injects the calibration command through the display-PC graphics
handler, so calibration starts automatically and its targets appear on the
subject display. Starting calibration manually on the Host instead selects the
Host-side target display and should not be used for this workflow. Successful
calibration injects an Escape key into the setup loop so it returns
automatically; the task-computer Escape key remains a manual abort-and-return
path. FineVision then closes the temporary window, restores it without invoking
the task's normal key polling, clears pending key events, and suppresses the
setup-closing Escape for one second. This prevents the same key press from also
aborting the resumed task; a later Escape still works normally. Recording is
then resumed. The same EDF therefore contains the samples before and after the
new calibration. `FINEVISION_RECALIBRATION_*` messages mark the interruption
and recording restart.

The PyLink graphics adapter remains registered after the temporary calibration
window closes. It is released only after the final EDF transfer, because
`receiveDataFile()` can continue polling its keyboard callback. Closing the
adapter at the end of mid-session calibration can otherwise produce
`AttributeError: 'NoneType' object has no attribute 'get_input_key'` and mask
the normal task shutdown.

The 2AFC task offers recalibration only when the operator selects it; unlike
the multi-stim saccade task, it does not run control trials or automatically
judge calibration drift.

Position controls are scheduled in adjacent pairs. Each successful control
writes its final 100-ms gaze center and target error as `CONTROL_GAZE_CHECK`.
Two above-threshold members of the same pair write `CONTROL_DRIFT_ALERT` and
open the runtime menu before the next trial. FineVision uses these checks only
to request a native EyeLink recalibration; it does not transform GAZE samples
with an additional trial-by-trial correction.

## Configuration files

- `eyelink_setting.json`: Host address, sample rate, sample source, and
  calibration filename.
- `eyelink_gaze_identity_setting.json`: safety identity parameters for the
  active GAZE workflow; the backend bypasses affine calibration in code.
- `eyelink_default_setting.json`: fallback FineVision mapping from right-eye
  EyeLink HREF coordinates into task-screen pixels.
- `eyelink_gaze_default_setting.json`: inactive record of an earlier GAZE
  correction; active tasks do not load it.
- `default_setting.json`: existing QY calibration parameters.

Do not copy calibration coefficients between GAZE, HREF, and QY files; these
are different coordinate systems.

## Reading EDF with Python

PyLink is the live tracker interface and does not open an EDF for offline
analysis. The supplied `read_eyelink_edf.py` script calls the official EDF2ASC
program from the Developers Kit, requests right-eye HREF samples, and writes
separate sample, message, and event CSV files:

```powershell
conda activate Monkey
cd D:\Chenghang\FineVision
python read_eyelink_edf.py Calibration_20260805_161454_eyelink.edf
```

The default output folder is `<EDF name>_parsed`. To export EyeLink GAZE rather
than HREF, add `--sample gaze`. The important time column is
`tracker_time_ms`; it is directly comparable to message timestamps in
`messages.csv`. Filter the message column for `CAL_`, `TRIALID`, `STIM_ON`, or
`TRIAL_RESULT` to segment samples into calibration points and task trials.
