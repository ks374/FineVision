"""Run manual heat-map mapping with EyeLink and EDF output."""

from eyetracker.legacy_entry import run_legacy_task


if __name__ == "__main__":
    run_legacy_task("FixationTask_hmap", "eyelink")
