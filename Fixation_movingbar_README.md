# Fixation Moving-Bar Task

Run from the FineVision directory:

```powershell
python Fixation_movingbar.py
```

## Trial sequence

1. The monkey acquires and holds the central fixation point.
2. At `Bar On After Fixation Start (ms)` (default 500 ms), a white bar appears.
3. The bar moves for `Bar Motion Duration (s)` (default 1 second).
4. Fixation must be maintained until the bar disappears. A successful trial
   ends at bar offset and is rewarded.

Every eight-trial block contains each combination of:

- Direction: right, left, down, up.
- Angular range: 4 degrees or 20 degrees.

The eight conditions are shuffled independently in every block.

## Scan geometry

With the default 55 cm viewing distance and 54 x 30 cm, 1920 x 1080 subject
display:

- The 4-degree aperture is about 137 x 138 pixels. Its top-left corner is the
  fixation point and it lies entirely in the lower-right quadrant.
- The 20-degree aperture is about 690 x 698 pixels. Its bottom is pinned to the
  screen bottom (`y=-540`), so its top is around `y=+158`; it crosses the
  horizontal midline but remains to the right of the vertical midline.

The bar is perpendicular to its motion. Paper-matched default widths are
0.04 degrees for the 4-degree condition and 0.19 degrees for the 20-degree
condition. Opacity is adjustable from 0 to 1.

## Logs

Each run creates `experiment_logs/FixationMovingBar_<timestamp>/` containing:

- `Fixation_movingbar_task_log_<timestamp>.csv`: one row per trial, including
  block/condition, status, gaze entry, bar onset/offset, fixation-point offset,
  actual pixel trajectory, geometry, and task parameters.
- `Fixation_movingbar_eye_log_<timestamp>.csv`: continuous `Time`,
  `Gaze_Target_X`, `Gaze_Target_Y` samples aligned to the task clock.

Real eye-tracker mode records successful SDK samples at 100 Hz. Mouse simulation
mode also records mouse gaze, at the display-loop rate.
