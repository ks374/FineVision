"""Run the moving-bar fixation task with EyeLink and EDF output."""

from multiprocessing import freeze_support

from Fixation_movingbar import main


if __name__ == "__main__":
    freeze_support()
    main("eyelink")
