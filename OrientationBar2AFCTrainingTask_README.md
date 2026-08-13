# Orientation Bar 2AFC training task

This is the bar-stimulus counterpart of `Orientation2AFCTrainingTask`:

- horizontal bar -> right target
- vertical bar -> upper target

The task reuses the fixation, timing, calibrated brightness, asymmetric choice
hold, reward, H/V override, cue-retention, pre-choice guidance, fixed 2-second
post-trial feedback, EyeLink integration, and total/latest-40 choice statistics
from the dot-pair task.

## Stages

- Stage 1: no cue; only the correct single-dot target appears.
- Stage 2: horizontal or vertical bar cue; only the correct single-dot target
  appears at choice onset.
- Stage 3: bar cue plus two bar choice targets. The right target is a horizontal
  bar and the upper target is a vertical bar.
- Stage 4: bar cue plus the two original single-dot choice targets.

The cue bar uses `Cue Bar Length (deg)` and `Cue Bar Width (deg)`. The Stage 3
choice bars use the independent `Choice Bar Length (deg)` and
`Choice Bar Width (deg)` settings. Length must be greater than width, and a
choice bar must fit inside its target window. Cue and choice brightness still
use the calibrated level parameters from the dot-pair task.

`Give Feedback First` displays the yellow cue frame and connection to the
correct choice during the choice interval, without a yellow frame around the
choice target. `First Feedback Opacity (0-1)` controls that pre-choice yellow
guidance. `Keep Cue Visible During Choice` behaves exactly as in the dot-pair
task. The fixed 2-second post-trial display replays the animal's selected bar or
dot with the cue. A correct selection receives yellow cue/choice frames and a
connection; an incorrect selection is shown with the cue and selected target
only, without yellow markings.

## Starting the task

- QY: `python OrientationBar2AFCTrainingTask_QY.py`
- EyeLink: `python OrientationBar2AFCTrainingTask_EyeLink.py`
- Default backend: `python OrientationBar2AFCTrainingTask.py`

The Bar task has its own parameter file,
`params_OrientationBar2AFCTrainingTask.json`, and writes sessions under
`experiment_logs/OrientationBar2AFC_<timestamp>/`. It does not modify the
parameters or logs of the original dot-pair task.
