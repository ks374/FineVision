"""EyeLink entry point for brightness-matching 2AFC training."""
from multiprocessing import freeze_support
from BrightnessMatching2AFCTrainingTask import (
    BrightnessMatching2AFCTrainingTask, DEFAULT_PARAMS, PARAMETER_GROUPS,
    validate_brightness_params, main,
)

if __name__ == "__main__":
    freeze_support()
    main(
        "eyelink",
        task_class=BrightnessMatching2AFCTrainingTask,
        task_name="BrightnessMatching2AFCTrainingTask",
        default_params=DEFAULT_PARAMS,
        parameter_groups=PARAMETER_GROUPS,
        parameter_validator=validate_brightness_params,
        saved_params_migrator=None,
        session_prefix="BrightnessMatching2AFC",
        control_title="Brightness Matching 2AFC",
        task_label="Brightness Matching 2AFC training",
    )
