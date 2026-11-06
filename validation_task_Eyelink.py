"""Collect editable RAW validation targets, then explicitly choose whether to refit."""
from Calibration_Task import main

if __name__ == "__main__":
    main("eyelink", validation=True)
