"""Pure scheduling and event decisions for Saccade_Elec_stim_Eyelink."""
import math
import random

WAVEFORM = dict(sample_rate_hz=30000, phase_samples=5, dwell_samples=2,
                period_samples=100, pulses=50, currents_uA=[8, 14, 20],
                requested_phase_us=170, requested_dwell_us=60,
                phase_us=5000000 / 30000, dwell_us=2000000 / 30000,
                nominal_train_ms=5000 / 30, last_phase_end_ms=4912 / 30,
                polarity="cathode_first", group=2, slot=1)


def make_plan(bank, seed, bounds):
    if bank not in (0, 128):
        raise ValueError("HW bank start must be 0 or 128")
    xmin, xmax, ymin, ymax = bounds
    if not xmin < xmax or not ymin < ymax:
        raise ValueError("RF minima must be smaller than maxima")
    rng = random.Random(seed)
    def point():
        return [rng.uniform(xmin, xmax), rng.uniform(ymin, ymax)]
    # Sixteen columns x twelve rows, one jittered point per cell.
    controls = [[xmin + (x + rng.random()) * (xmax-xmin)/16,
                 ymin + (y + rng.random()) * (ymax-ymin)/12]
                for x in range(16) for y in range(12)]
    rng.shuffle(controls)
    conditions = [(h, a, r) for h in range(bank, bank+128)
                  for a in (8, 14, 20) for r in (1, 2)]
    rng.shuffle(conditions)
    plan = [dict(kind="precontrol", target_deg=point()) for _ in range(10)]
    for i, (hw, current, repeat) in enumerate(conditions, 1):
        plan.append(dict(kind="stim", hw=hw, ntrode=hw+1, current_uA=current,
                         repeat=repeat, target_deg=point()))
        if i % 4 == 0:
            plan.append(dict(kind="control", target_deg=controls.pop()))
    for i, row in enumerate(plan, 1):
        row["plan_id"] = i
    return plan


def gaze_degrees(position, size, physical_cm, distance_cm):
    """EyeLink top-left pixels -> centered visual-angle coordinates."""
    x, y = position
    return (math.degrees(math.atan((x-size[0]/2)*physical_cm[0]/size[0]/distance_cm)),
            math.degrees(math.atan((size[1]/2-y)*physical_cm[1]/size[1]/distance_cm)))


def event_time_ms(event, edge):
    """Native EyeLink timestamps, or PC milliseconds in mouse rehearsal only."""
    if edge + "_eyelink" in event:
        return event[edge + "_eyelink"]
    if edge + "_ms" in event:  # Historical logs remain readable.
        return event[edge + "_ms"]
    return event.get(edge + "_pc", -1) * 1000


def qualifies(event, onset_ms, deadline_ms, threshold=.75):
    return (event.get("valid", False) and event.get("eye") == 1
            and onset_ms <= event_time_ms(event, "start") <= deadline_ms
            and event_time_ms(event, "start") <= event_time_ms(event, "end") <= deadline_ms
            and event["amplitude_deg"] > threshold)


def advance(condition, status, delivered):
    # A failed fixation consumes no electrical dose. Once delivered, do not retry.
    return status == "success" if condition["kind"] != "stim" else delivered
