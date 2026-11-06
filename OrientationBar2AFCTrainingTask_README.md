# Orientation Bar 2AFC training task

This is the bar-stimulus counterpart of `Orientation2AFCTrainingTask`:

- horizontal bar -> right target
- vertical bar -> upper target

The task reuses the fixation, timing, calibrated brightness, asymmetric choice
hold, reward, H/V override, cue-retention, pre-choice guidance, fixed 2-second
post-trial feedback, EyeLink integration, and total/latest-40 choice statistics
from the dot-pair task.

In the standard mode (`Use Visual Cue as Fixation Point` unchecked), the animal
first acquires and holds the fixation point. On one display refresh the fixation
point disappears and the bar cue appears, then the bar remains visible for
`Stim Duration (ms)` without a fixation-hold requirement before choice onset.
The checkbox is retained as an explicit alternative mode in which the bar itself
is the fixation target and there is no separate cue phase.

`Gaze-Contingent Stimulus Position` applies the same optional per-frame gaze
compensation as the dot-pair task. The displayed bar center is
`configured bar center + current gaze position - fixation position`, so gaze
and bar move in the same direction. The position is not clamped; an off-screen
bar is simply not visible. Choice targets do not move. Invalid gaze falls back
to the configured position;
unchecking the option preserves the original fixed-position behavior. The
compensation is disabled when the bar itself is used as the fixation point.

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
only, without yellow markings. On correct trials, the first post-trial frame is
flipped to the subject display before the success marker, water command, and
reward sound are triggered.

The Bar task also shares the adaptive pre-choice reminder parameters. After
`Reminder After Consecutive Errors (X)` incorrect choices, the next trial shows
the yellow cue frame and line. `Reminder After Trials (Y)` schedules the next
`Reminder Trials (Z)` trials with the same guidance. These schedules are
independent; X=0 disables the error schedule, while Y=0 or Z=0 disables the
interval schedule. Reward feedback is the shared rapid six-beep WAV, lasting
0.6 seconds.

The Bar task also inherits block scheduling and failure repeats. The startup
parameter `Trials per Block (N)` defaults to 40 and is disabled in the runtime
menu after the task starts. Only a `Success` completes the current within-block
trial. Every non-`Success` attempt repeats the same horizontal or vertical
stimulus without advancing the block. The Nth success ends the block and
triggers the independent `Block Reward Length (s)` reward (1.5 seconds by
default). Returning from an `N`-key pause gives one normal-length reward;
`Cancel` discards menu edits and resumes rather than terminating the session.

## Starting the task

- QY: `python OrientationBar2AFCTrainingTask_QY.py`
- EyeLink: `python OrientationBar2AFCTrainingTask_EyeLink.py`
- Default backend: `python OrientationBar2AFCTrainingTask.py`

The Bar task has its own parameter file,
`params_OrientationBar2AFCTrainingTask.json`, and writes sessions under
`experiment_logs/OrientationBar2AFC_<timestamp>/`. It does not modify the
parameters or logs of the original dot-pair task.
