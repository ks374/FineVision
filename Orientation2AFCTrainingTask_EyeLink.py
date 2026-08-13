"""Run orientation 2AFC training with EyeLink and save gaze in EDF."""

from multiprocessing import freeze_support

from Orientation2AFCTrainingTask import main


if __name__ == "__main__":
    freeze_support()
    main("eyelink")
