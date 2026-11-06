# Fixation Moving-Bar Task

## Update 2026-09-28 (supersedes geometry/block descriptions below)

Both `Bar Width for 4deg (deg)` and `Bar Width for 20deg (deg)` accept a
positive scalar or an array entered as text, for example `[0.04, 0.2]`.
Each range/width combination runs Right, Left, Down and Up once per block,
in shuffled order. Two widths for each range give 16 successful trials/block.
`Total Blocks` defaults to 10: the task stops after 160 successes. NoFix or
Break repeats exactly the same condition until success. All attempts are
logged with distinct Trial numbers; Block and Trial_In_Block remain the same
during retries. Escape still exits. Widths and block count are fixed at session
start; the runtime parameter menu disables those fields.

`Fixation Diameter (deg)` controls the visible dot diameter, independently of
`Fix Window Radius (pix)`. `Fixation X (deg)` and `Fixation Y (deg)` specify
its screen-centered location (positive X right, positive Y up). The gaze
acceptance window follows the dot. Bar geometry is relative to this dot.

For range R, horizontal sweeps have center endpoints x=-0.1R and x=0.9R,
with bar extent y=-R to 0. Vertical sweeps have center endpoints y=+0.1R
and y=-0.9R, with bar extent x=0 to R. Reverse directions retrace the same
path. Endpoints ignore bar thickness. The task retains its existing
visual-angle-to-pixel conversion. It no longer pins scans to the screen edge:
off-screen portions are clipped. Choose fixation position/display geometry
to show the desired area. The CSV stores actual width, fixation pixel
position, trajectory, and the complete parameters including fixation degrees.

Run from the FineVision directory:

```powershell
python Fixation_movingbar_EyeLink.py
```

## Trial sequence

1. The monkey acquires and holds the central fixation point.
2. At `Bar On After Fixation Start (ms)` (default 500 ms), a white bar appears.
3. The bar moves for `Bar Motion Duration (s)` (default 1 second).
4. Fixation must be maintained until the bar disappears. A successful trial
   ends at bar offset and is rewarded.

`Fixation_movingbar.py` itself retains its QY default; the EyeLink entry above
selects EDF recording. `IS_SIMULATING = 1` in the main module selects mouse gaze
without EyeLink recording; it still initializes the existing Arduino controller.

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

Subject and parameters are confirmed before recording starts. Each run creates
`experiment_logs/FixationMovingBar_<subject>_<timestamp>/` containing:

- `Fixation_movingbar_task_log_<timestamp>.csv`: one row per trial, including
  block/condition, status, gaze entry, bar onset/offset, fixation-point offset,
  actual pixel trajectory, geometry, and task parameters.
- EyeLink mode: `FixationMovingBar_<session>_eyelink.edf`, downloaded on normal
  shutdown. This mode does not also generate an eye CSV.
- QY/mouse mode: `Fixation_movingbar_eye_log_<session>.csv`, containing `Time`,
  `Gaze_Target_X`, `Gaze_Target_Y` samples aligned to the task clock.
- `session.json`: session origin, initial parameters and optical code settings.
- `events.json`: session-relative behavioral, display and optical event times.
- `frames.json`: subject flip intervals, optical state, bar visibility and bar
  position on each presented frame; `late` flags intervals >1.5 nominal periods.

QY mode records successful SDK samples at 100 Hz. Mouse simulation
mode also records mouse gaze, at the display-loop rate.

## Synchronization update (2026-09-24)

`Time_DrawFinish` and `Time_TrialStart` now use the same post-flip callback time
as the first white frame of the trial-start optical code. `Time_GazeEnter` is
the first in-window detection of the successful acquisition interval;
`Time_FixAcquired` is its later confirmation. The bar delay retains the original
reference: `Time_GazeEnter`, not `Time_FixAcquired`.

`Time_Break`, `Time_NoFix` and `Time_Success` capture the behavioral decision.
`Time_End` equals that decision time and excludes timeout and optical transmission.
EDF receives `FIX_ACQUIRED`, `BREAK`, and `NOFIX` immediately when judged, with
`SESSION_TIME` matching the CSV. Break times are software detection times, not
the exact physical onset of eye motion. The pre-bar and bar-motion phases remain
distinguishable through `Break_Phase`. Reward time remains in CSV for compatibility;
the EDF reward message has been removed.

`BAR_ON`, `BAR_OFF`, and `FIX_OFF` remain flip-linked. The bar's first commanded
position lies just outside the scanning edge, as before: `BAR_ON` refers to that
first rendered bar frame, not a photodiode measurement of visible bar entry.
The existing bar trajectory and four-direction/two-range conditions are retained.

All task times use `time.perf_counter() - session_t0`. The PC origin is saved in
each CSV row and `session.json`, and declared in EDF using `SESSION_ZERO`.
The EDF receipt time of that declaration is later than zero. Start/end
`CLOCK_SYNC` messages pair a PC elapsed time with the EDF receipt time; transport
latency remains. EDF samples retain their tracker clock. Approximate UTC is for
session identification, not millisecond alignment.

## Photodiode

The subject screen has an 80 x 80 px square inset 10 px from the bottom/right
edges. It is drawn last. After parameter confirmation, recording/window setup
and five black baseline refreshes, startup is **5 white, 5 black, 5 white**,
followed by black before the first ITI. Both pulse edges are recorded as
PD_TASK_START_1_ON/OFF and PD_TASK_START_2_ON/OFF.

Thereafter it is continuously white exactly while the bar is rendered, and black
during acquisition, pre-bar hold, ITI and timeout. The first bar frame and rising
edge share one flip; bar removal and falling edge share one flip (including Break
and Esc). `Time_PDOn/Off` equal `Time_BarOn/Off`. NoFix and pre-bar Break have no
trial optical signal. EDF/events contain PD_BAR_ON/OFF. Legacy
`Time_OutcomePDOn/Off` columns are retained empty. Session metadata records the
new photodiode_protocol. The old 1/3/5/7/9 outcome codes are no longer emitted;
outcomes remain in CSV/EDF. True photon edges require hardware measurement.

The default scanning aperture stops near x=690 px and the optical square starts
at x=870 px on a 1920 px display, so they are separated. After changing monitor
geometry, check that the scan region does not overlap the sensor square, which
would mask that part of the stimulus. Cover the square with the sensor and opaque
surround. Validate widths and display scanout offset on the actual hardware;
counting flips cannot prevent a dropped refresh from lengthening a pulse.

## Exit and validation

Esc during acquisition, pre-bar hold or motion saves the current trial as
`Aborted`, removes stimuli and turns the optical square black on the same flip.
Esc during startup completes the double pulse before exiting.
Esc during an already decided outcome preserves that outcome.
No outcome code is invented for an aborted trial. Completed trials are flushed
to CSV immediately. Forced process termination cannot guarantee EDF download or
save the in-memory event/frame diagnostics.

Automated checks (fake windows/gaze, no hardware activation):

```powershell
D:\Software\Psychopy\python.exe -m pytest tests/test_movingbar_sync.py tests/test_fixation_sync.py -q
```
