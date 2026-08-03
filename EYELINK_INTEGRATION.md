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

- `get_latest()` returns the latest uncalibrated left/right sample.
- `get_latest_cal()` returns FineVision task coordinates and validity.
- `set_calibration_left/right()` stores FineVision's custom mapping.

EyeLink is intentionally configured with `sample_source: "href"`. The existing
FineVision `CalibrationManager` maps HREF values into centered PsychoPy pixels.
FineVision does not run EyeLink's display calibration. Camera positioning and
tracking quality must still be checked on the EyeLink Host.

## Entry scripts

| Task | QY entry | EyeLink entry |
| --- | --- | --- |
| Full calibration | `Calibration_Task_QY.py` | `Calibration_Task_EyeLink.py` |
| Quick calibration | `Quick_calib_task_QY.py` | `Quick_calib_task_EyeLink.py` |
| Saccade | `SaccadeTask_QY.py` | `SaccadeTask_EyeLink.py` |
| Multi-stim saccade | `SaccadeMultiStimTask_QY.py` | `SaccadeMultiStimTask_EyeLink.py` |
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
4. On the Host, position the camera and confirm stable pupil/CR tracking.
5. Run `Calibration_Task_EyeLink.py`. It writes the custom mapping to
   `eyelink_default_setting.json`.
6. Run the desired `*_EyeLink.py` task.

EyeLink tasks do not create the QY gaze CSV. The Host records full-rate samples
in EDF and FineVision downloads that EDF when the task closes. Behavior remains
in the task CSV.

## EDF and behavior-file alignment

Modern tasks send `TRIALID`, display events such as `FIX_ON`, `STIM_ON`, or
`BAR_ON`, trial variables, and `TRIAL_RESULT` to the EDF. Event messages and gaze
samples therefore share the EyeLink Host clock. The behavior CSV uses the local
FineVision clock. Join the files by session identity and trial number; do not
compare the two clock values directly.

EyeLink gaze is intentionally not smoothed for online decisions. QY retains the
existing five-frame operator-view smoothing. For physical display-onset or
neural-system synchronization at millisecond precision, continue to use the
photodiode/TTL signal as the final timing reference.

## Configuration files

- `eyelink_setting.json`: Host address, sample rate, sample source, and
  calibration filename.
- `eyelink_default_setting.json`: FineVision custom calibration parameters for
  EyeLink only.
- `default_setting.json`: existing QY calibration parameters.

Do not copy QY calibration coefficients into the EyeLink calibration file; the
two backends expose different raw coordinate systems.
