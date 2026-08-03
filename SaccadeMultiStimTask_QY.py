"""Run the multi-stimulus saccade task with the QY tracker."""

from multiprocessing import freeze_support

from SaccadeMultiStimTask import main


if __name__ == "__main__":
    freeze_support()
    main("qy")
