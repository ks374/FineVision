"""Run the saccade task with EyeLink and save gaze in EDF."""

from multiprocessing import freeze_support

from SaccadeTask import main


if __name__ == "__main__":
    freeze_support()
    main("eyelink")
