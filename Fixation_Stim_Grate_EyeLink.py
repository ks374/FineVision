"""Run the fixation grating task with EyeLink and EDF output."""

from eyetracker.legacy_entry import run_legacy_task


if __name__ == "__main__":
    run_legacy_task("Fixation_Stim_Grate", "eyelink")
