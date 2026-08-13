"""Run FineVision's custom EyeLink calibration/report task.

In the default GAZE workflow the fitted coefficients are saved only in the
session report and are not applied online. Switch to HREF to use this mapping.
"""

from Calibration_Task import main


if __name__ == "__main__":
    main("eyelink")
