# SaccadeTask

Run from the FineVision directory:

```powershell
python SaccadeTask.py
```

## Trial sequence

1. The central fixation point appears. The animal must enter its window and
   remain there for `Fixation Acquire Time (ms)`.
2. At the first central-window entry (`Time_GazeEnter`), one fixation duration
   is sampled uniformly between `Fixation Duration Min (ms)` and
   `Fixation Duration Max (ms)`. The acquisition interval is included in this
   total duration.
3. The central point then disappears. During `Gap Duration (ms)`, the subject
   display is blank but the central fixation window remains active. Leaving it
   fails the trial.
4. At gap end, the ellipse and its target window become active simultaneously.
   The ellipse remains visible for exactly `Stim Duration (ms)`. The target
   window is only shown on the control display.
5. The target window remains active for
   `Stim Window After Stim Off (ms)` after the ellipse disappears.
6. During the complete target-window interval, gaze must remain continuously
   inside the target window for `Stim Hold Time (ms)`. Leaving the target
   window before completing the hold resets the hold timer; the animal may
   re-enter while the response window is still active.
7. If the hold completes before stimulus offset, success is locked but the
   stimulus still runs to its scheduled offset. Reward is delivered only after
   stimulus offset and trial blackout.

The timing parameters must satisfy:

```text
Fixation Acquire <= Fixation Duration Min <= Fixation Duration Max
Stim Hold <= Stim Duration + Stim Window After Stim Off
```

The parameter editor opens at startup. Its fields are grouped into Session,
Fixation, Timing, Stimulus, Display, and Reward tabs so related settings stay
together. Press `N` during the task to reopen it before the next trial, and
press `Esc` to stop.

## Status values

- `Success`: both stages completed.
- `nofix_1`: central fixation was not acquired before `Wait Time (s)`.
- `Break_1`: central fixation was acquired and then broken before fixation-point
  offset.
- `Break_Gap`: gaze left the central fixation window during the blank gap.
- `nofix_2`: the target window was never entered before the target-window
  deadline.
- `Break_2`: the target window was entered at least once but no uninterrupted
  hold reached the required duration before the deadline.

## Logs

Each run creates `experiment_logs/Saccade_<timestamp>/` with:

- `Saccade_task_log_<timestamp>.csv`: one row per trial. It preserves trial
  start, first display, gaze entry, end, and status, and adds stimulus onset,
  fixation-point offset, fixation position, stimulus-window entry, stimulus
  offset, target-window end, reward time, the sampled fixation duration, and
  all relevant parameters.
- `Saccade_eye_log_<timestamp>.csv`: continuous `Time`,
  `Gaze_Target_X`, `Gaze_Target_Y` samples. Invalid samples are retained as
  `-999, -999` so the time series remains continuous.

Both files use seconds from the same `time.perf_counter()` session origin.
Eye-sample timestamps are assigned when the tracker process receives the SDK
sample, not when the writer later flushes it to disk.

The SDK remains at 100 Hz. A separate writer process writes rows in batches of
100 and flushes once per second, so CSV I/O is not performed by the PsychoPy
render loop or by the eye-tracker polling loop.

Online task success is based only on gaze-window entry and continuous hold.
Saccade detection, latency, first-saccade endpoint, and corrective-saccade
analysis are intentionally left for offline analysis of the continuous eye log.
