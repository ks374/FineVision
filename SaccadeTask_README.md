# SaccadeTask

Run from the FineVision directory:

```powershell
python SaccadeTask.py
```

## Trial sequence

1. The central fixation point appears. The animal must enter its window and
   remain there for `Fixation Acquire Time (ms)`.
2. All following relative times start at the first central-window entry
   (`Time_GazeEnter`).
3. The ellipse appears at `Stim On After Fixation Start (ms)`.
4. Central fixation must be maintained until
   `Fixation Point Off After Fixation Start (ms)`.
5. After the central point disappears, gaze may move freely. The animal must
   enter the ellipse window and stay for `Stim Hold Time (ms)`.
6. The ellipse disappears at `Stim Off After Fixation Start (ms)`. On a
   successful trial the reward is delivered after the ellipse has disappeared.

The parameter editor opens at startup. Press `N` during the task to reopen it
before the next trial, and press `Esc` to stop.

## Status values

- `Success`: both stages completed.
- `nofix_1`: central fixation was not acquired before `Wait Time (s)`.
- `Break_1`: central fixation was acquired and then broken before fixation-point
  offset.
- `nofix_2`: the ellipse window was never entered before ellipse offset.
- `Break_2`: the ellipse window was entered but the required hold was broken or
  could not be completed before ellipse offset.

## Logs

Each run creates `experiment_logs/Saccade_<timestamp>/` with:

- `Saccade_task_log_<timestamp>.csv`: one row per trial. It preserves trial
  start, first display, gaze entry, end, and status, and adds stimulus onset,
  fixation-point offset, fixation position, stimulus-window entry, stimulus
  offset, reward time, and all relevant parameters.
- `Saccade_eye_log_<timestamp>.csv`: continuous `Time`,
  `Gaze_Target_X`, `Gaze_Target_Y` samples. Invalid samples are retained as
  `-999, -999` so the time series remains continuous.

Both files use seconds from the same `time.perf_counter()` session origin.
Eye-sample timestamps are assigned when the tracker process receives the SDK
sample, not when the writer later flushes it to disk.

The SDK remains at 100 Hz. A separate writer process writes rows in batches of
100 and flushes once per second, so CSV I/O is not performed by the PsychoPy
render loop or by the eye-tracker polling loop.
