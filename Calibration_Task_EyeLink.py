"""Record RAW calibration and save the fitted mapping plus EDF session archive.

Uses a session-specific RAW configuration; task GAZE settings stay unchanged.
"""

from Calibration_Task import main


if __name__ == "__main__":
    main("eyelink")
