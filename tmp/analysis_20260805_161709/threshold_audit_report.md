# 2026-08-05 16:17 EyeLink amplitude-threshold audit

Source: `D:\Chenghang\Training_Log_Huanhuan\20260805\SaccadeMultiStim_20260805_161709` (EDF plus task CSV). EDF was read with the installed 64-bit EDF Access API because `edf2asc.exe` could not start on this host (Windows DLL relocation error). Extraction code: `audit_threshold.py`; machine-readable counts: `threshold_audit.json`. The source directory was not modified.

101 attempted trials: 81 Success, 2 Control_Reward, 3 Break_2, 4 Break_1, 11 nofix_1. Right-eye EDF events: 1,021 ENDSACC over the full recording. Analysis below uses the 86 trials with completed central fixation, gap and visual-stimulus markers. The completed fixation epoch begins at the EDF `GAZE_ACQUIRED` message and ends at `FIX_OFF`; the stimulus epoch runs from EDF `STIM_ON` for 467 ms, matching the proposed 167 + 300 ms electrical response window. Each event is assigned by its **start** timestamp. Events ending after fixation offset are excluded from the fixation count. Angles are reconstructed from EyeLink GAZE event start/end pixels using the session's logged 58 cm viewing distance and 54×30 cm screen, matching the geometry-based calculation in the new task.

| Strict amplitude criterion | Completed fixation trials with at least one event (n=86) | Gap trials with event (n=86) | Visual-period trials with event (n=86) | Peripheral noncontrol successful trials with event (n=72) |
|---|---:|---:|---:|---:|
| >0.25° | 19 (22.1%) | 5 (5.8%) | 77 (89.5%) | 72 (100%) |
| >0.50° | 15 (17.4%) | 2 (2.3%) | 77 (89.5%) | 72 (100%) |
| >0.70° | 6 (7.0%) | 0 | 76 (88.4%) | 71 (98.6%) |
| >0.75° | 6 (7.0%) | 0 | 76 (88.4%) | 71 (98.6%) |
| >1.00° | 3 (3.5%) | 0 | 76 (88.4%) | 71 (98.6%) |
| >2.00° | 2 (2.3%) | 0 | 75 (87.2%) | 71 (98.6%) |

Among the 86 completed fixation periods (34.148 s total), 22 ENDSACC events were recorded; 20 events across 19 trials were above 0.25°. The median event amplitude was 0.56°; the 75th percentile was 0.80°. Of the 20 events above 0.25°, 17 were no larger than 1°. EyeLink's own pixel-per-degree conversion gives 18 trials with an event above 0.25°, close to the geometry-based count of 19.

The fixation-period events occurred **before** STIM_ON. The new task's timestamp gate excludes them even if their ENDSACC message arrives late. This recording contains no no-stim/no-visual response epoch, so it does not directly measure the false-success rate after an electrical trigger. As a rough rate comparison only, completed fixation produced 20 events above 0.25° in 34.148 s (~0.59/s), whereas a 467 ms electrical response window is much shorter. That rate must not be treated as an experimentally measured false-positive probability because eye movement is not necessarily stationary across task phases.

The 72 peripheral successful visual trials show why >1° may be a useful *candidate* for large orienting movements: 71/72 still had some ENDSACC above 1° during the proposed electrical response window. Yet the first >0.25° event began before 80 ms in 44/72, and **none of those first-event endpoints fell within 2.5° of the logged visual target** when using EDF GAZE coordinates. This conflicts with online Success labels. Therefore event presence in those trials is **not** validated sensitivity for true target-directed eye movements. The historical online coordinate source/calibration cannot be fully reconstructed from this folder alone, and this 8/5 session was excluded from a separate gain analysis. A verified calibrated session or direct offline sample-to-target mapping is needed before setting a final sensitivity threshold.

Interpretation: >0.25° is too permissive as a sole indicator of a stimulation-evoked orienting saccade. Raising it to around 1° reduces fixation-period event prevalence here, with little loss of event presence in these large-target successful trials; this does **not** establish 1° as a universal criterion, especially for RF points close to fixation. Keep event start time, amplitude, direction, endpoint, and latency for every trial. Add sham electrical/no-visual trials to estimate post-trigger spontaneous saccades directly; use spatially and temporally matched conditions when deciding the online reward criterion. Physical EyeLink/display alignment should be verified on the current setup.
