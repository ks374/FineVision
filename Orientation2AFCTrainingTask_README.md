# Orientation 2AFC training task

This task trains the fixed report mapping:

- horizontally arranged dot pair -> right target
- vertically arranged dot pair -> upper target

The arrangement sequence is balanced in shuffled pairs. The two cue dots share
one adjustable radius and are separated by an adjustable center-to-center
distance. Their common center position, brightness level, and opacity are also
configurable. The center distance must be larger than twice the dot radius so
the dots do not overlap.

`Cue Brightness Level (0-182)` and
`Choice Target Brightness Level (0-182)` are read directly from the `Gray`
sheet of `屏幕RGB_扩展等亮度刺激标定_至255.xlsx`. Both default to brightness
level 160, which maps to RGB `(232, 232, 232)`, target luminance
`188.0 cd/m²`, and estimated luminance about `188.61 cd/m²` in that workbook.
These are calibrated brightness levels, not raw RGB channel values.

`Background Gray Level (0-182)` selects the calibrated display-gray level from
the shared FineVision brightness calibration files. Its default is level 5;
the corresponding RGB and target luminance are saved in the behavior CSV and
written to the EDF as trial variables.

## Trial sequence

The animal acquires and maintains the central fixation point. The report cue
time is sampled uniformly between `Stim Onset Delay Min (ms)` and
`Stim Onset Delay Max (ms)`, measured from the first sample of the acquired
fixation.

When `Use Visual Cue as Fixation Point` is checked, the trial's horizontal or
vertical two-dot cue replaces the single fixation point from the first trial
frame. Its center is the configured fixation position and the usual fixation
window is still used for acquisition and holding. After the sampled
`Stim Onset Delay` has elapsed, the task goes directly to choice: no separate
cue onset occurs and `Stim Duration (ms)` is skipped. This is an explicit
alternative training mode. In the standard mode, leave this option unchecked.
The animal first acquires and holds the normal fixation point; on one display
refresh the fixation point disappears and the cue appears. The cue then remains
visible for `Stim Duration (ms)` without a fixation-hold requirement before the
choice display begins.

When `Gaze-Contingent Stimulus Position` is checked in the standard mode, the
task reads the newest gaze sample before drawing every cue frame. In task-space
pixel coordinates the displayed cue center is
`configured cue center + current gaze position - fixation position`. Thus, for
a configured cue at `(1, 1)`, it is displayed at
`(gaze position - fixation position) + (1, 1)`. Gaze and cue therefore move in
the same direction. The result is not clamped to the screen: when the cue moves
outside the display, PsychoPy simply does not show the off-screen portion. The
choice targets remain at their configured screen positions. If gaze is invalid,
the configured fixed cue
position is used for that frame. When the option is unchecked, behavior is
identical to the original fixed-position task. Gaze compensation is deliberately
disabled when `Use Visual Cue as Fixation Point` is checked so that the
fixation-acquisition target itself does not move.

When `Keep Cue Visible During Choice` is checked, the cue remains on the
subject screen when the fixation interval ends and the choice targets appear.
It stays visible throughout the choice interval, until a choice is committed
or the choice time expires. This also applies when the cue itself is being used
as the fixation point. When the option is unchecked, the cue disappears at
choice onset as before.

When `Give Feedback First` is checked, the choice display immediately adds a
yellow frame around the cue and a yellow line from that frame toward the
correct choice target. No yellow frame is drawn around the choice target. The
cue is retained automatically while this guidance is visible, even if
`Keep Cue Visible During Choice` is unchecked. `First Feedback Opacity (0-1)`
sets the shared opacity of this yellow cue frame and connecting line. This
setting does not change the fixed 2-second post-trial teaching feedback.

The same pre-choice yellow cue frame and connecting line can be scheduled as a
memory reminder without keeping `Give Feedback First` enabled on every trial:

- `Reminder After Consecutive Errors (X)`: after X completed incorrect choices
  in a row, show the reminder on the next trial. A completed correct choice
  resets the streak; trials without a completed choice leave it unchanged.
- `Reminder After Trials (Y)` and `Reminder Trials (Z)`: after Y trials without
  an interval reminder, show the reminder for the next Z trials, then begin a
  new Y-trial interval.
- The two schedules keep independent counters. If both are due on the same
  trial, one reminder is shown and both trigger sources are logged. Set X to 0
  to disable the error schedule; set either Y or Z to 0 to disable the interval
  schedule.

Reward feedback uses six rapid 1200-Hz beeps in one 0.6-second WAV. The same
sound is shared with the Saccade tasks and the manual pump helper.

## Blocks and failed-trial repeats

`Trials per Block (N)` sets the number of successfully completed trials in each
block and defaults to 40. It can be edited in the startup parameter window.
Once the task starts, this field is disabled in the `N`-key runtime menu and the
session keeps the startup value. Block and within-block trial numbers are
written to the behavior CSV and EDF metadata.

Failed attempts do not advance the within-block trial number. After the Nth
successful trial, the task gives one extra water reward. `Block Reward Length
(s)` controls this reward independently of the normal correct-choice reward and
defaults to 1.5 seconds. The Nth success receives both its normal reward and the
later block-completion reward.

Every outcome other than `Success` schedules the same horizontal or vertical
cue for the next trial. This repeat takes priority over random selection and a
manual H/V request. If H or V was requested during the ITI, that manual request
is retained for the trial after the required repeat.

- Stage 1: no cue is shown. At the sampled time fixation disappears and only
  the correct target appears.
- Stage 2: at the sampled time, the fixation point disappears and the horizontal
  or vertical dot pair appears on the same display refresh. After
  `Stim Duration (ms)` (500 ms by default), the correct target appears; the cue
  remains during choice only if `Keep Cue Visible During Choice` is checked.
- Stage 3: the cue timing is identical to Stage 2. Both targets appear at
  response onset as compact dot pairs: the right target is a horizontal pair
  and the upper target is a vertical pair. Their center-to-center spacing is
  set by `Choice Dot Center Distance (deg)`.
- Stage 4: the cue timing is identical to Stage 2. Both targets appear at
  response onset as the original single dots at the right and upper locations.

In Stages 3 and 4, the correct and wrong target opacity values are selected
manually with `Correct Target Opacity (0-1)` and
`Wrong Target Opacity (0-1)`. Opacity is never changed automatically between
trials.

Choice commitment uses asymmetric hold times. Entering the wrong target window
and remaining there continuously for 50 ms ends the trial immediately as an
incorrect choice. Entering the correct target window must be maintained for
`Correct Choice Hold Time (ms)` (500 ms by default) before the trial succeeds
and reward is delivered. Leaving a target window before its threshold resets
that target's timer. Fixation breaks during the pre-cue or cue interval
terminate the trial without opening the choice period.

When `Show Post-Trial Teaching Feedback` is checked, every Stage 3 or Stage 4
trial with a completed choice transitions immediately into a fixed 2-second
display of that trial's cue and the target selected by the animal. After a
correct choice, yellow rectangular frames mark the cue and selected target and
a yellow line connects their nearest edges. After an incorrect choice, only
the cue and incorrectly selected target are shown, without yellow frames or a
line. Trials without a completed choice do not show this feedback. The feedback
duration is fixed and is intentionally not exposed as a parameter. On correct
trials, the first post-trial feedback frame is flipped to the subject display
before the success marker, water command, and reward sound are triggered.

## Starting the task

- QY: `python Orientation2AFCTrainingTask_QY.py`
- EyeLink: `python Orientation2AFCTrainingTask_EyeLink.py`
- Default backend: `python Orientation2AFCTrainingTask.py`

Press `N` to pause safely before the next trial. In an EyeLink session, the
pause menu has `Confirm`, `Recalibrate`, and `Cancel` actions. Recalibration is
started automatically from the task computer and shown full-screen on subject
screen 1. It returns to this task automatically after a successful calibration
and continues writing to the same EDF file. Do not start calibration manually
on the EyeLink Host: that selects the Host-side target display. Pressing `Esc`
during EyeLink setup returns without completing calibration. There is no
automatic calibration-quality decision in this task. With a QY tracker, the
recalibration action is hidden.

Closing the runtime menu with `Cancel` now discards menu edits and resumes the
same session; it does not terminate the task. Every return from an `N`-key pause
(`Cancel`, `Confirm`, or `Recalibrate`) gives one reward using the normal
`Reward Length (s)` setting as a cue that the task is restarting. Use `Esc` in
the running task to terminate the session.

The Escape used to leave EyeLink setup is cleared before the task window
resumes and is ignored for one second, preventing it from also terminating the
2AFC session. A later, new Escape press in the running task still stops it.

The terminal shows the total trial count, total completed-choice accuracy, and
accuracy over the latest 40 completed choices. Trials without a completed
choice do not reduce that recent window below 40 once 40 choices are available.
Press `Esc` in the running task to stop.

During the ITI, press `H` to force the next trial to use a horizontal cue or
`V` to force it to use a vertical cue. The most recently pressed key during
that ITI wins. The override applies to one trial only and does not consume an
entry from the balanced random orientation sequence. If neither key is pressed,
the next orientation remains randomly selected from that sequence. The behavior
CSV records whether each orientation came from `Manual_H_or_V` or `Random`.

All behavior and gaze logs are written under
`experiment_logs/Orientation2AFC_<timestamp>/`.
