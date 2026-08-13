"""Run orientation Bar 2AFC training with the QY eye tracker."""

from multiprocessing import freeze_support

from OrientationBar2AFCTrainingTask import main


if __name__ == "__main__":
    freeze_support()
    main("qy")
