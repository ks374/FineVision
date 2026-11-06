# Classic Fixation task: timing and optical synchronization

Run `FixationTask_EyeLink.py` (or `FixationTask.py`, which defaults to EyeLink).
This change concerns the classic task, not the separate bar, grating, moving-bar,
heatmap or pretraining tasks. The subject display now runs fullscreen on screen 1;
the control display stays windowed on screen 0. Acquisition still requires 150 ms
continuously inside the fixation window, followed by the configured hold duration.

## Session output

Confirm Subject ID and parameters before recording starts. Each run creates a
unique `experiment_logs/Fixation_<Subject>_<YYYYMMDD_HHMMSS>/` directory (with a
collision suffix if necessary). It contains:

- `Fixation_task_log_<session>.csv`: one flushed row per trial, including the
  current parameter snapshot in `Parameters_JSON`.
- `Fixation_<session>_eyelink.edf`: downloaded on orderly shutdown in EyeLink mode.
- `session.json`: PC clock origin, approximate UTC origin, starting parameters,
  nominal frame period and session end time.
- `events.json`: task and optical events, in session-relative seconds.
- `frames.json`: each subject flip, session time, native PsychoPy flip clock time,
  interval, optical state and an interval warning (`late`, >1.5 nominal periods).

Esc ends the session instead of restarting it. A trial interrupted during waiting
or holding is saved as `Aborted`; a result already decided stays Success/Break/NoFix.
An optical code already in progress is completed and returned to black before
exit. Aborted trials have an EDF `TRIAL_ABORT` message but no invented outcome
optical code. No extra optical session-end code is defined. N opens the runtime
parameter panel at the next safe boundary. Each subsequent trial saves its new
parameters. Normal exit closes CSV and attempts EDF transfer independently of
other cleanup errors. Forced process termination cannot guarantee EDF download
or preservation of the in-memory event/frame diagnostics.

## Time semantics

All CSV `Time_*` values are seconds relative to the same `time.perf_counter()`
session origin passed to the tracker runtime. The origin precedes tracker/window
initialization; it is distinct from the later optical TASK_START event.

| Field | Meaning |
|---|---|
| Time_TrialStart / Time_DrawFinish | Callback immediately after the first subject flip displaying fixation; coincident with PD_FIXATION_ON |
| Time_GazeEnter | First detected in-window sample of the successful 150 ms acquisition interval |
| Time_FixAcquired | Time that the 150 ms acquisition requirement is confirmed |
| Time_Break | Time the task detects invalid or out-of-window gaze during hold |
| Time_NoFix | Time the acquisition deadline is judged to have expired |
| Time_Success | Time completion of the hold is judged successful |
| Time_End | Behavioral decision time, excluding timeout and optical code duration |
| Time_FixOff | Callback at the flip removing fixation |
| Time_PDOn / Time_PDOff | Flip timestamps for continuous fixation-visible white signal |
| Time_OutcomePDOn / Off | Legacy columns, now empty: outcome pulse codes have been removed |

Break is not classified using a later timeout-completion timestamp. Once fixation
has been acquired, a hold failure is Break. Behavioral times are software detection
times, not a claim about the exact physical onset of an eye movement. Display
times are post-flip software timestamps, not measured photon arrival times.

EDF receives `FIX_ACQUIRED`, `BREAK`, and `NOFIX` immediately at their decisions,
with the CSV time embedded as `SESSION_TIME`. It also receives trial identifiers,
fixation display transitions, trial outcomes and optical edges. No reward event
is added. The original Arduino reward and status commands remain active.

**The PC origin is explicitly written into EDF**, in a `SESSION_ZERO PERF_COUNTER
... UTC ...` message. This declares the origin; the EDF timestamp of that message
is its later receipt time, not zero. Start/end `CLOCK_SYNC SESSION_TIME ...`
messages, and the elapsed times carried by task messages, provide PC/tracker time
pairs. EDF samples still use the tracker clock. Message transport adds latency,
so these pairs do not constitute hardware-level exact clock synchronization.
UTC is approximate and for session identification, not interval measurement.

## Optical codes

The subject display has an 80 x 80 pixel square inset 10 pixels from the right and
bottom edges. Cover it with the sensor and an opaque surround so it does not act
as an additional visible cue. It is black at baseline and white during a code.
After parameter confirmation, recording/window initialization and five black
baseline refreshes, startup is **5 white, 5 black, 5 white**, followed by black.
EDF/events record both pairs of edges as PD_TASK_START_1_ON/OFF and
PD_TASK_START_2_ON/OFF. Startup occurs before the first ITI, not at Python import.

Thereafter the square mirrors fixation-point visibility continuously: white from
fixation onset through acquisition and hold, black on the same flip that removes
fixation (including NoFix, Break and Esc). It does not certify that gaze is inside
the window. The 1/3/5/7/9 outcome codes are no longer emitted; outcomes remain in
CSV/EDF. Time_PDOn/Off and PD_FIXATION_ON/OFF describe the continuous signal.
Session metadata records the new photodiode_protocol. Esc completes a startup
sequence already in progress; during a trial it turns the signal black with the
stimulus. There is no additional optical outcome or session-end code.

Frame counting cannot prevent a missed hardware refresh from lengthening startup
pulses. Validate with the actual photodiode; right-bottom and central stimulus
photon onset may differ due to display scanout.

## Automated verification

`D:\Software\Psychopy\python.exe -m pytest tests/test_fixation_sync.py -q`

Tests use simulated display flips and gaze; they do not operate a tracker, pump,
real display or photodiode. They cover startup edges, continuous visibility, all
outcomes, early and late Esc, parameter persistence, session paths and
independent tracker cleanup.
