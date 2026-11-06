"""Run manual-reward fixation pretraining with EyeLink EDF recording."""

from eyetracker.legacy_entry import run_legacy_task


if __name__ == "__main__":
    run_legacy_task("PretrainingFixationTask", "eyelink")
