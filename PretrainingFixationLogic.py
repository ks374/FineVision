"""Pure trial-state logic for the manual-reward fixation pretraining task."""

from dataclasses import dataclass


def validate_pretraining_params(params):
    if float(params["Fixation Point Radius (pix)"]) <= 0:
        raise ValueError("Fixation Point Radius must be positive")
    if float(params["Maximum Fixation Display (s)"]) <= 0:
        raise ValueError("Maximum Fixation Display must be positive")
    if int(params["Reward Duration (ms)"]) < 0:
        raise ValueError("Reward Duration cannot be negative")
    if float(params["Black Screen Duration (s)"]) < 0:
        raise ValueError("Black Screen Duration cannot be negative")
    if int(params["Subject Screen Index"]) < 0:
        raise ValueError("Subject Screen Index cannot be negative")
    if int(params["Control Screen Index"]) < 0:
        raise ValueError("Control Screen Index cannot be negative")


@dataclass(frozen=True)
class TrialDecision:
    fixation_finished: bool
    reward_requested: bool
    result: str | None = None
    fixation_duration_s: float | None = None


class PretrainingTrialController:
    """Decide when one pretraining fixation presentation should finish."""

    def __init__(self, max_fixation_s):
        self.max_fixation_s = float(max_fixation_s)
        if self.max_fixation_s <= 0:
            raise ValueError("max_fixation_s must be positive")
        self._finished = False

    def press_reward(self, elapsed_s):
        if self._finished:
            return TrialDecision(True, False)
        elapsed_s = max(0.0, float(elapsed_s))
        if elapsed_s >= self.max_fixation_s:
            return self.update(elapsed_s)
        self._finished = True
        return TrialDecision(
            fixation_finished=True,
            reward_requested=True,
            result="ManualReward",
            fixation_duration_s=elapsed_s,
        )

    def abort(self, elapsed_s):
        if self._finished:
            return TrialDecision(True, False)
        self._finished = True
        elapsed_s = max(0.0, float(elapsed_s))
        return TrialDecision(
            fixation_finished=True,
            reward_requested=False,
            result="Aborted",
            fixation_duration_s=elapsed_s,
        )

    def update(self, elapsed_s):
        elapsed_s = max(0.0, float(elapsed_s))
        if self._finished:
            return TrialDecision(True, False)
        if elapsed_s < self.max_fixation_s:
            return TrialDecision(False, False)
        self._finished = True
        return TrialDecision(
            fixation_finished=True,
            reward_requested=False,
            result="NoReward",
            fixation_duration_s=self.max_fixation_s,
        )
