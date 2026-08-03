"""Run the saccade task with the QY eye tracker."""

from multiprocessing import freeze_support

from SaccadeTask import main


if __name__ == "__main__":
    freeze_support()
    main("qy")
