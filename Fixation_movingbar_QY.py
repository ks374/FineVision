"""Run the moving-bar fixation task with the QY tracker."""

from multiprocessing import freeze_support

from Fixation_movingbar import main


if __name__ == "__main__":
    freeze_support()
    main("qy")
