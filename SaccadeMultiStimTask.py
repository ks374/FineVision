"""Saccade task with a fixed, parameter-generated stimulus condition plan."""

import csv
import json
import math
import os
import random
import re
import time
import traceback
from datetime import datetime
from decimal import Decimal
from multiprocessing import Queue, Value, freeze_support
from queue import Full
from types import SimpleNamespace

from psychopy import event, visual

from EyeDataLogger import GazeCsvWriter, STOP_TOKEN
from FineVision_Notebook import FineVision_Notebook
from eyetracker import create_tracker_runtime
from SaccadeTask import (
    DEFAULT_PARAMS as SACCADE_DEFAULT_PARAMS,
    EYE_TRACKER_RATE_HZ,
    IS_SIMULATING as SACCADE_IS_SIMULATING,
    MONITOR_ID_CONTROL,
    MONITOR_ID_SUBJECT,
    SACCADE_PARAMETER_GROUPS,
    TRIAL_LOG_FIELDS,
    SaccadeTask,
    TaskAbort,
    _validate_params,
)


IS_SIMULATING = SACCADE_IS_SIMULATING
MAX_VALUES_PER_RANGE = 1000
MAX_PLANNED_TRIALS = 100000
CALIBRATION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "stim_calibration_0_20.json",
)
CALIBRATION_EXTENSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "stim_calibration_extension_to_255.json",
)


DEFAULT_PARAMS = {
    "Subject ID": SACCADE_DEFAULT_PARAMS["Subject ID"],
    "Wait Time (s)": SACCADE_DEFAULT_PARAMS["Wait Time (s)"],
    "Fixation Acquire Time (ms)": SACCADE_DEFAULT_PARAMS[
        "Fixation Acquire Time (ms)"
    ],
    "Fixation Position X (deg)": SACCADE_DEFAULT_PARAMS[
        "Fixation Position X (deg)"
    ],
    "Fixation Position Y (deg)": SACCADE_DEFAULT_PARAMS[
        "Fixation Position Y (deg)"
    ],
    "Fixation Point Radius (deg)": SACCADE_DEFAULT_PARAMS[
        "Fixation Point Radius (deg)"
    ],
    "Fix Window Radius (deg)": SACCADE_DEFAULT_PARAMS[
        "Fix Window Radius (deg)"
    ],
    "Fixation Duration Min (ms)": SACCADE_DEFAULT_PARAMS[
        "Fixation Duration Min (ms)"
    ],
    "Fixation Duration Max (ms)": SACCADE_DEFAULT_PARAMS[
        "Fixation Duration Max (ms)"
    ],
    "Gap Duration (ms)": SACCADE_DEFAULT_PARAMS["Gap Duration (ms)"],
    "Stim Duration (ms)": SACCADE_DEFAULT_PARAMS["Stim Duration (ms)"],
    "Stim Window After Stim Off (ms)": SACCADE_DEFAULT_PARAMS[
        "Stim Window After Stim Off (ms)"
    ],
    "Stim Hold Time (ms)": SACCADE_DEFAULT_PARAMS[
        "Stim Hold Time (ms)"
    ],
    "Stim Window Radius (deg)": SACCADE_DEFAULT_PARAMS[
        "Stim Window Radius (deg)"
    ],
    "Stim Position X Min (deg)": 4.0,
    "Stim Position X Max (deg)": 4.0,
    "Stim Position X Step (deg)": 1.0,
    "Stim Position Y Min (deg)": -2.0,
    "Stim Position Y Max (deg)": -2.0,
    "Stim Position Y Step (deg)": 1.0,
    "Stim Major Axis Min (deg)": 1.0,
    "Stim Major Axis Max (deg)": 1.0,
    "Stim Major Axis Step (deg)": 0.5,
    "Stim Minor Axis Min (deg)": 1.0,
    "Stim Minor Axis Max (deg)": 1.0,
    "Stim Minor Axis Step (deg)": 0.5,
    "Stim Orientation Min (deg)": SACCADE_DEFAULT_PARAMS[
        "Stim Orientation (deg)"
    ],
    "Stim Orientation Max (deg)": SACCADE_DEFAULT_PARAMS[
        "Stim Orientation (deg)"
    ],
    "Stim Orientation Step (deg)": 10.0,
    "Stim Colors (comma-separated)": "R,G,B,Gray",
    "Stim Intensity Level Min": 1,
    "Stim Intensity Level Max": 20,
    "Stim Intensity Level Step": 1,
    "Control Trial Proportion (0-1)": 0.10,
    "Background Gray Level (0-182)": 5,
    "Repeats Per Condition": 1,
    "Condition Order": ["Randomized", "Sequential"],
    "Random Seed": 20260731,
    "Viewing Distance (cm)": SACCADE_DEFAULT_PARAMS[
        "Viewing Distance (cm)"
    ],
    "Subject Monitor Width (cm)": SACCADE_DEFAULT_PARAMS[
        "Subject Monitor Width (cm)"
    ],
    "Subject Monitor Height (cm)": SACCADE_DEFAULT_PARAMS[
        "Subject Monitor Height (cm)"
    ],
    "Reward Length (s)": SACCADE_DEFAULT_PARAMS["Reward Length (s)"],
    "ITI (s)": SACCADE_DEFAULT_PARAMS["ITI (s)"],
    "Timeout (s)": SACCADE_DEFAULT_PARAMS["Timeout (s)"],
}


MULTISTIM_PARAMETER_GROUPS = {
    "Session / 会话": SACCADE_PARAMETER_GROUPS["Session / 会话"],
    "Fixation / 注视": SACCADE_PARAMETER_GROUPS["Fixation / 注视"],
    "Timing / 时间": SACCADE_PARAMETER_GROUPS["Timing / 时间"],
    "Plan / 条件表": [
        "Stim Colors (comma-separated)",
        "Stim Intensity Level Min",
        "Stim Intensity Level Max",
        "Stim Intensity Level Step",
        "Control Trial Proportion (0-1)",
        "Repeats Per Condition",
        "Condition Order",
        "Random Seed",
    ],
    "Position / 位置": [
        "Stim Window Radius (deg)",
        "Stim Position X Min (deg)",
        "Stim Position X Max (deg)",
        "Stim Position X Step (deg)",
        "Stim Position Y Min (deg)",
        "Stim Position Y Max (deg)",
        "Stim Position Y Step (deg)",
    ],
    "Shape / 形状": [
        "Stim Major Axis Min (deg)",
        "Stim Major Axis Max (deg)",
        "Stim Major Axis Step (deg)",
        "Stim Minor Axis Min (deg)",
        "Stim Minor Axis Max (deg)",
        "Stim Minor Axis Step (deg)",
        "Stim Orientation Min (deg)",
        "Stim Orientation Max (deg)",
        "Stim Orientation Step (deg)",
    ],
    "Display / 屏幕": [
        "Background Gray Level (0-182)",
        *SACCADE_PARAMETER_GROUPS["Display / 屏幕"],
    ],
    "Reward / 奖励": SACCADE_PARAMETER_GROUPS["Reward / 奖励"],
}


LOCKED_DURING_SESSION_PARAMS = {
    "Subject ID",
    "Fixation Position X (deg)",
    "Fixation Position Y (deg)",
    "Fixation Point Radius (deg)",
    "Stim Position X Min (deg)",
    "Stim Position X Max (deg)",
    "Stim Position X Step (deg)",
    "Stim Position Y Min (deg)",
    "Stim Position Y Max (deg)",
    "Stim Position Y Step (deg)",
    "Stim Major Axis Min (deg)",
    "Stim Major Axis Max (deg)",
    "Stim Major Axis Step (deg)",
    "Stim Minor Axis Min (deg)",
    "Stim Minor Axis Max (deg)",
    "Stim Minor Axis Step (deg)",
    "Stim Orientation Min (deg)",
    "Stim Orientation Max (deg)",
    "Stim Orientation Step (deg)",
    "Stim Colors (comma-separated)",
    "Stim Intensity Level Min",
    "Stim Intensity Level Max",
    "Stim Intensity Level Step",
    "Control Trial Proportion (0-1)",
    "Background Gray Level (0-182)",
    "Repeats Per Condition",
    "Condition Order",
    "Random Seed",
    "Viewing Distance (cm)",
    "Subject Monitor Width (cm)",
    "Subject Monitor Height (cm)",
}


CONDITION_LOG_FIELDS = [
    "Condition_Index",
    "Condition_ID",
    "Attempt_For_Condition",
    "Repeat_Index",
    "Condition_Order",
    "Random_Seed",
    "Stim_Color_Name",
    "Stim_Intensity_Level",
    "Stim_Target_Luminance_cd_m2",
    "Stim_Calibration_Max_Level",
    "Requested_Control_Proportion",
    "Actual_Control_Proportion",
    "Background_Gray_Level",
    "Background_Target_Luminance_cd_m2",
    "Background_Color_R",
    "Background_Color_G",
    "Background_Color_B",
    "Is_Control",
]


PLAN_FIELDS = [
    "Condition_Index",
    "Condition_ID",
    "Repeat_Index",
    "Stim_Pos_X_deg",
    "Stim_Pos_Y_deg",
    "Stim_Major_Axis_deg",
    "Stim_Minor_Axis_deg",
    "Stim_Orientation_deg",
    "Stim_Color_Name",
    "Stim_Intensity_Level",
    "Stim_Target_Luminance_cd_m2",
    "Stim_Color_R",
    "Stim_Color_G",
    "Stim_Color_B",
    "Stim_Calibration_Max_Level",
    "Requested_Control_Proportion",
    "Actual_Control_Proportion",
    "Is_Control",
]


COLOR_ALIASES = {
    "r": "R",
    "red": "R",
    "红": "R",
    "红色": "R",
    "g": "G",
    "green": "G",
    "绿": "G",
    "绿色": "G",
    "b": "B",
    "blue": "B",
    "蓝": "B",
    "蓝色": "B",
    "gray": "Gray",
    "grey": "Gray",
    "灰": "Gray",
    "灰色": "Gray",
}


def _load_calibration():
    with open(CALIBRATION_FILE, "r", encoding="utf-8") as file:
        base_calibration = json.load(file)
    with open(
        CALIBRATION_EXTENSION_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        extension = json.load(file)

    base_luminance = base_calibration.get(
        "target_luminance_cd_m2",
        [],
    )
    base_rgb_by_color = base_calibration.get("rgb_by_color", {})
    if len(base_luminance) != 21:
        raise ValueError(
            "Calibration must contain target luminance levels 0-20."
        )

    luminance_step = float(extension["luminance_step_cd_m2"])
    preserve_through = int(extension["preserve_levels_through"])
    max_level_by_color = extension["max_level_by_color"]
    measured_curves = extension["measured_curve_by_color"]
    if preserve_through != 20:
        raise ValueError(
            "Extended calibration must preserve levels through level 20."
        )

    target_luminance_by_color = {}
    rgb_by_color = {}
    for color_name in ("R", "G", "B", "Gray"):
        base_rgb_values = base_rgb_by_color.get(color_name, [])
        if len(base_rgb_values) != 21:
            raise ValueError(
                f"Calibration color {color_name} must contain levels 0-20."
            )

        max_level = int(max_level_by_color[color_name])
        curve = [
            (float(input_value), float(luminance))
            for input_value, luminance in measured_curves[color_name]
        ]
        if (
            max_level < 20
            or curve[0] != (0.0, 0.0)
            or curve[-1][0] != 255.0
            or any(
                curve[index][0] <= curve[index - 1][0]
                or curve[index][1] < curve[index - 1][1]
                for index in range(1, len(curve))
            )
        ):
            raise ValueError(
                f"Extended calibration curve for {color_name} is invalid."
            )

        luminance_values = list(base_luminance)
        rgb_values = [list(rgb) for rgb in base_rgb_values]
        for level in range(21, max_level + 1):
            target_luminance = min(
                level * luminance_step,
                curve[-1][1],
            )
            input_value = _inverse_interpolate_luminance(
                target_luminance,
                curve,
            )
            integer_input = min(
                255,
                max(0, int(math.floor(input_value + 0.5))),
            )
            rgb = {
                "R": [integer_input, 0, 0],
                "G": [0, integer_input, 0],
                "B": [0, 0, integer_input],
                "Gray": [integer_input, integer_input, integer_input],
            }[color_name]
            luminance_values.append(target_luminance)
            rgb_values.append(rgb)

        if len(luminance_values) != max_level + 1:
            raise ValueError(
                f"Extended calibration for {color_name} is incomplete."
            )
        if rgb_values[-1] != {
            "R": [255, 0, 0],
            "G": [0, 255, 0],
            "B": [0, 0, 255],
            "Gray": [255, 255, 255],
        }[color_name]:
            raise ValueError(
                f"Extended calibration for {color_name} must end at 255."
            )
        target_luminance_by_color[color_name] = luminance_values
        rgb_by_color[color_name] = rgb_values

    return {
        "source": extension["source"],
        "target_luminance_cd_m2_by_color": target_luminance_by_color,
        "rgb_by_color": rgb_by_color,
        "max_level_by_color": {
            color_name: int(max_level_by_color[color_name])
            for color_name in ("R", "G", "B", "Gray")
        },
    }


def _inverse_interpolate_luminance(target_luminance, curve):
    if target_luminance <= curve[0][1]:
        return curve[0][0]
    if target_luminance >= curve[-1][1]:
        return curve[-1][0]

    for index in range(1, len(curve)):
        lower_input, lower_luminance = curve[index - 1]
        upper_input, upper_luminance = curve[index]
        if target_luminance <= upper_luminance:
            luminance_span = upper_luminance - lower_luminance
            if luminance_span <= 0:
                return upper_input
            fraction = (
                (target_luminance - lower_luminance)
                / luminance_span
            )
            return lower_input + fraction * (upper_input - lower_input)
    return curve[-1][0]


def _inclusive_values(start, stop, step, field_name, integers=False):
    start_decimal = Decimal(str(start))
    stop_decimal = Decimal(str(stop))
    step_decimal = Decimal(str(step))

    if step_decimal <= 0:
        raise ValueError(f"{field_name} step must be greater than zero.")
    if stop_decimal < start_decimal:
        raise ValueError(
            f"{field_name} maximum must be greater than or equal to minimum."
        )

    span = stop_decimal - start_decimal
    if span % step_decimal != 0:
        raise ValueError(
            f"{field_name} range must be exactly divisible by its step."
        )

    count = int(span / step_decimal) + 1
    if count > MAX_VALUES_PER_RANGE:
        raise ValueError(
            f"{field_name} generates {count} values; the limit is "
            f"{MAX_VALUES_PER_RANGE}."
        )

    values = [start_decimal + step_decimal * index for index in range(count)]
    if integers:
        if any(value != value.to_integral_value() for value in values):
            raise ValueError(f"{field_name} values must all be integers.")
        return [int(value) for value in values]
    return [float(value) for value in values]


def _parse_colors(raw_colors):
    color_tokens = [
        token
        for token in re.split(r"[,;，、\s]+", str(raw_colors).strip())
        if token
    ]
    if not color_tokens:
        raise ValueError("Stim Colors must contain at least one color.")

    colors = []
    for token in color_tokens:
        canonical = COLOR_ALIASES.get(token.casefold())
        if canonical is None:
            raise ValueError(
                f"Unsupported color '{token}'. Use R, G, B, and/or Gray."
            )
        if canonical not in colors:
            colors.append(canonical)
    return colors


def _require_integer(value, field_name):
    decimal_value = Decimal(str(value))
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"{field_name} must be an integer.")
    return int(decimal_value)


def _interleave_controls(experimental_plan, control_conditions):
    """Spread controls through a sequential plan without changing stim order."""
    if not control_conditions:
        return list(experimental_plan)

    total_count = len(experimental_plan) + len(control_conditions)
    control_count = len(control_conditions)
    plan = []
    experimental_index = 0
    control_index = 0
    for slot in range(total_count):
        controls_through_slot = ((slot + 1) * control_count) // total_count
        if controls_through_slot > control_index:
            plan.append(control_conditions[control_index])
            control_index += 1
        else:
            plan.append(experimental_plan[experimental_index])
            experimental_index += 1
    return plan


def _build_condition_plan(
    params,
    calibration,
    *,
    counts_only=False,
):
    x_values = _inclusive_values(
        params["Stim Position X Min (deg)"],
        params["Stim Position X Max (deg)"],
        params["Stim Position X Step (deg)"],
        "Stim Position X",
    )
    y_values = _inclusive_values(
        params["Stim Position Y Min (deg)"],
        params["Stim Position Y Max (deg)"],
        params["Stim Position Y Step (deg)"],
        "Stim Position Y",
    )
    major_values = _inclusive_values(
        params["Stim Major Axis Min (deg)"],
        params["Stim Major Axis Max (deg)"],
        params["Stim Major Axis Step (deg)"],
        "Stim Major Axis",
    )
    minor_values = _inclusive_values(
        params["Stim Minor Axis Min (deg)"],
        params["Stim Minor Axis Max (deg)"],
        params["Stim Minor Axis Step (deg)"],
        "Stim Minor Axis",
    )
    orientation_values = _inclusive_values(
        params["Stim Orientation Min (deg)"],
        params["Stim Orientation Max (deg)"],
        params["Stim Orientation Step (deg)"],
        "Stim Orientation",
    )
    intensity_values = _inclusive_values(
        params["Stim Intensity Level Min"],
        params["Stim Intensity Level Max"],
        params["Stim Intensity Level Step"],
        "Stim Intensity Level",
        integers=True,
    )
    colors = _parse_colors(params["Stim Colors (comma-separated)"])
    background_gray_level = _require_integer(
        params["Background Gray Level (0-182)"],
        "Background Gray Level",
    )
    gray_max_level = calibration["max_level_by_color"]["Gray"]

    if min(intensity_values) < 1:
        raise ValueError(
            "Formal stimulus intensity levels must start at 1 or higher. "
            "Use Control Trial Proportion to add blank controls."
        )
    if not 0 <= background_gray_level <= gray_max_level:
        raise ValueError(
            "Background Gray Level must stay in the calibrated range "
            f"0-{gray_max_level}."
        )
    if min(major_values) <= 0 or min(minor_values) <= 0:
        raise ValueError("Stimulus axes must be greater than zero.")
    if max(major_values) >= 180 or max(minor_values) >= 180:
        raise ValueError("Stimulus axes must be less than 180 degrees.")
    if min(major_values) < max(minor_values):
        raise ValueError(
            "Every major-axis value must be greater than or equal to every "
            "minor-axis value."
        )
    if any(
        orientation < 0 or orientation >= 180
        for orientation in orientation_values
    ):
        raise ValueError(
            "Stim Orientation values must be at least 0 and less than "
            "180 degrees."
        )
    if any(abs(value) >= 180 for value in x_values + y_values):
        raise ValueError(
            "Every stimulus position must be between -180 and 180 degrees."
        )

    repeats = _require_integer(
        params["Repeats Per Condition"],
        "Repeats Per Condition",
    )
    if repeats <= 0:
        raise ValueError("Repeats Per Condition must be greater than zero.")
    order = str(params["Condition Order"])
    if order not in ("Sequential", "Randomized"):
        raise ValueError(
            "Condition Order must be Sequential or Randomized."
        )
    random_seed = _require_integer(params["Random Seed"], "Random Seed")
    control_proportion = float(
        params["Control Trial Proportion (0-1)"]
    )
    if (
        not math.isfinite(control_proportion)
        or control_proportion < 0
        or control_proportion >= 1
    ):
        raise ValueError(
            "Control Trial Proportion must be at least 0 and less than 1."
        )

    max_level_by_color = calibration["max_level_by_color"]
    intensity_values_by_color = {
        color_name: [
            level
            for level in intensity_values
            if level <= max_level_by_color[color_name]
        ]
        for color_name in colors
    }
    valid_colors = [
        color_name
        for color_name in colors
        if intensity_values_by_color[color_name]
    ]
    if not valid_colors:
        limits = ", ".join(
            f"{color_name}: 1-{max_level_by_color[color_name]}"
            for color_name in colors
        )
        raise ValueError(
            "The requested intensity range is above every selected color's "
            f"calibrated range ({limits})."
        )

    experimental_count = (
        len(x_values)
        * len(y_values)
        * len(major_values)
        * len(minor_values)
        * len(orientation_values)
        * sum(
            len(intensity_values_by_color[color_name])
            for color_name in valid_colors
        )
        * repeats
    )
    control_count = 0
    if control_proportion > 0:
        control_count = max(
            1,
            int(
                experimental_count
                * control_proportion
                / (1.0 - control_proportion)
                + 0.5
            ),
        )
    planned_count = experimental_count + control_count
    if planned_count > MAX_PLANNED_TRIALS:
        raise ValueError(
            f"The parameter grid generates {planned_count} planned trials; "
            f"the safety limit is {MAX_PLANNED_TRIALS}."
        )
    if counts_only:
        return {
            "experimental_count": experimental_count,
            "control_count": control_count,
            "planned_count": planned_count,
            "actual_control_proportion": (
                control_count / planned_count if planned_count else 0.0
            ),
        }

    base_conditions = []
    for x_deg in x_values:
        for y_deg in y_values:
            for major_deg in major_values:
                for minor_deg in minor_values:
                    for orientation in orientation_values:
                        for color_name in valid_colors:
                            for intensity_level in intensity_values_by_color[
                                color_name
                            ]:
                                rgb = calibration["rgb_by_color"][color_name][
                                    intensity_level
                                ]
                                base_conditions.append(
                                    {
                                        "Stim_Pos_X_deg": x_deg,
                                        "Stim_Pos_Y_deg": y_deg,
                                        "Stim_Major_Axis_deg": major_deg,
                                        "Stim_Minor_Axis_deg": minor_deg,
                                        "Stim_Orientation_deg": orientation,
                                        "Stim_Color_Name": color_name,
                                        "Stim_Intensity_Level":
                                            intensity_level,
                                        "Stim_Target_Luminance_cd_m2":
                                            calibration[
                                                "target_luminance_cd_m2_by_color"
                                            ][color_name][intensity_level],
                                        "Stim_Color_R": int(rgb[0]),
                                        "Stim_Color_G": int(rgb[1]),
                                        "Stim_Color_B": int(rgb[2]),
                                        "Stim_Calibration_Max_Level":
                                            max_level_by_color[color_name],
                                        "Is_Control": False,
                                    }
                                )

    experimental_plan = []
    for repeat_index in range(1, repeats + 1):
        for base_condition in base_conditions:
            condition = dict(base_condition)
            condition["Repeat_Index"] = repeat_index
            experimental_plan.append(condition)

    control_conditions = []
    for control_index in range(control_count):
        template_index = (
            control_index * len(experimental_plan) // control_count
        )
        template = experimental_plan[template_index]
        control_conditions.append(
            {
                "Stim_Pos_X_deg": template["Stim_Pos_X_deg"],
                "Stim_Pos_Y_deg": template["Stim_Pos_Y_deg"],
                "Stim_Major_Axis_deg": template["Stim_Major_Axis_deg"],
                "Stim_Minor_Axis_deg": template["Stim_Minor_Axis_deg"],
                "Stim_Orientation_deg": template["Stim_Orientation_deg"],
                "Stim_Color_Name": "Control",
                "Stim_Intensity_Level": 0,
                "Stim_Target_Luminance_cd_m2": 0.0,
                "Stim_Color_R": 0,
                "Stim_Color_G": 0,
                "Stim_Color_B": 0,
                "Stim_Calibration_Max_Level": 0,
                "Repeat_Index": 0,
                "Is_Control": True,
            }
        )

    actual_control_proportion = (
        control_count / planned_count if planned_count else 0.0
    )
    if order == "Randomized":
        plan = experimental_plan + control_conditions
    else:
        plan = _interleave_controls(
            experimental_plan,
            control_conditions,
        )

    if order == "Randomized":
        random.Random(random_seed).shuffle(plan)

    for condition_index, condition in enumerate(plan, start=1):
        condition["Condition_Index"] = condition_index
        condition["Condition_ID"] = f"C{condition_index:06d}"
        condition["Requested_Control_Proportion"] = control_proportion
        condition["Actual_Control_Proportion"] = (
            actual_control_proportion
        )
    return plan


def _base_params_for_validation(params, first_condition):
    base_params = dict(params)
    base_params.update(
        {
            "Stim Position X (deg)": first_condition["Stim_Pos_X_deg"],
            "Stim Position Y (deg)": first_condition["Stim_Pos_Y_deg"],
            "Stim Major Axis (deg)": first_condition[
                "Stim_Major_Axis_deg"
            ],
            "Stim Minor Axis (deg)": first_condition[
                "Stim_Minor_Axis_deg"
            ],
            "Stim Orientation (deg)": first_condition[
                "Stim_Orientation_deg"
            ],
            "Stim Color R": first_condition["Stim_Color_R"],
            "Stim Color G": first_condition["Stim_Color_G"],
            "Stim Color B": first_condition["Stim_Color_B"],
        }
    )
    return base_params


def _validate_multistim_params(params):
    calibration = _load_calibration()
    condition_plan = _build_condition_plan(params, calibration)
    if not condition_plan:
        raise ValueError("The selected parameter ranges produced no trials.")
    first_stimulus = next(
        condition
        for condition in condition_plan
        if not condition["Is_Control"]
    )
    _validate_params(
        _base_params_for_validation(params, first_stimulus)
    )
    control_count = sum(
        bool(condition["Is_Control"])
        for condition in condition_plan
    )
    experimental_count = len(condition_plan) - control_count
    actual_control_proportion = control_count / len(condition_plan)
    selected_colors = _parse_colors(
        params["Stim Colors (comma-separated)"]
    )
    calibration_limits = ", ".join(
        f"{color_name}: {calibration['max_level_by_color'][color_name]}"
        for color_name in selected_colors
    )
    return (
        "计划条件总数 / Total planned conditions: "
        f"{len(condition_plan)}\n"
        f"正式刺激 / Experimental stimuli: {experimental_count}\n"
        f"空白对照 / Blank controls: {control_count} "
        f"({actual_control_proportion:.2%})\n"
        f"所选颜色最高标定等级 / Calibrated maxima: "
        f"{calibration_limits}\n\n"
        "正式刺激失败会重复同一条件；control 不显示刺激且一定给水。\n"
        "A failed experimental trial repeats the same condition; every "
        "blank control is rewarded and advances.\n\n"
        "开始本次 session / Start this session?"
    )


def _multistim_trial_summary(params):
    counts = _build_condition_plan(
        params,
        _load_calibration(),
        counts_only=True,
    )
    return (
        f"Planned trials: {counts['planned_count']:,} = "
        f"{counts['experimental_count']:,} stimuli + "
        f"{counts['control_count']:,} controls "
        f"({counts['actual_control_proportion']:.2%})"
    )


class SaccadeMultiStimTask(SaccadeTask):
    """Run the base saccade state machine over a fixed condition plan."""

    def __init__(self, *args, **kwargs):
        self.calibration = _load_calibration()
        self.condition_plan = []
        self.current_condition = None
        self.current_attempt = 0
        super().__init__(*args, **kwargs)

    def _task_log_filename(self):
        return (
            f"SaccadeMultiStim_task_log_{self.session_timestamp}.csv"
        )

    def _trial_log_fields(self):
        return TRIAL_LOG_FIELDS + CONDITION_LOG_FIELDS

    def _send_trial_start_metadata(self, trial_data):
        for field in (
            "Condition_ID",
            "Is_Control",
            "Stim_Color_Name",
            "Stim_Intensity_Level",
            "Stim_Pos_X_deg",
            "Stim_Pos_Y_deg",
        ):
            self._send_tracker_event(
                f"!V TRIAL_VAR {field} {trial_data[field]}"
            )

    def update_params(self):
        params = self.task_manager.exp_params
        condition_plan = _build_condition_plan(params, self.calibration)
        if not condition_plan:
            raise ValueError("The selected parameter ranges produced no trials.")

        first_stimulus = next(
            condition
            for condition in condition_plan
            if not condition["Is_Control"]
        )
        base_params = _base_params_for_validation(
            params,
            first_stimulus,
        )
        _validate_params(base_params)

        original_manager = self.task_manager
        self.task_manager = SimpleNamespace(exp_params=base_params)
        try:
            super().update_params()
        finally:
            self.task_manager = original_manager

        self._apply_background(params)
        self.condition_plan = condition_plan
        self.condition_order = str(params["Condition Order"])
        self.random_seed = int(params["Random Seed"])
        self.current_condition = self.condition_plan[0]
        self.current_attempt = 0
        self._apply_condition(self.current_condition)

    def _validate_runtime_params(self, params):
        reference_condition = next(
            condition
            for condition in self.condition_plan
            if not condition["Is_Control"]
        )
        _validate_params(
            _base_params_for_validation(params, reference_condition)
        )
        return None

    def _update_runtime_params(self):
        base_params = _base_params_for_validation(
            self.task_manager.exp_params,
            self.current_condition,
        )
        _validate_params(base_params)

        original_manager = self.task_manager
        self.task_manager = SimpleNamespace(exp_params=base_params)
        try:
            super().update_params()
        finally:
            self.task_manager = original_manager
        self._apply_background(self.task_manager.exp_params)

    def _apply_background(self, params):
        self.background_gray_level = _require_integer(
            params["Background Gray Level (0-182)"],
            "Background Gray Level",
        )
        background_rgb = self.calibration["rgb_by_color"]["Gray"][
            self.background_gray_level
        ]
        self.background_rgb_255 = tuple(int(value) for value in background_rgb)
        self.background_target_luminance = self.calibration[
            "target_luminance_cd_m2_by_color"
        ]["Gray"][self.background_gray_level]
        psychopy_color = [
            channel / 127.5 - 1.0
            for channel in self.background_rgb_255
        ]
        self.win_sub.color = psychopy_color
        self.win_ctl.color = psychopy_color

    def _apply_condition(self, condition):
        self.current_condition = condition
        self.stim_x_deg = float(condition["Stim_Pos_X_deg"])
        self.stim_y_deg = float(condition["Stim_Pos_Y_deg"])
        self.stim_major_axis_deg = float(
            condition["Stim_Major_Axis_deg"]
        )
        self.stim_minor_axis_deg = float(
            condition["Stim_Minor_Axis_deg"]
        )
        self.stim_orientation_deg = float(
            condition["Stim_Orientation_deg"]
        )
        self.stim_rgb_255 = (
            int(condition["Stim_Color_R"]),
            int(condition["Stim_Color_G"]),
            int(condition["Stim_Color_B"]),
        )

        self.stim_x_px = self._to_x_pixels(self.stim_x_deg)
        self.stim_y_px = self._to_y_pixels(self.stim_y_deg)
        self.stim_major_axis_px = self._to_x_pixels(
            self.stim_major_axis_deg
        )
        self.stim_minor_axis_px = self._to_y_pixels(
            self.stim_minor_axis_deg
        )
        self._build_visuals()

    def _new_trial_data(self, trial_number, fixation_duration_s):
        trial_data = super()._new_trial_data(
            trial_number,
            fixation_duration_s,
        )
        condition = self.current_condition
        trial_data.update(
            {
                "Condition_Index": condition["Condition_Index"],
                "Condition_ID": condition["Condition_ID"],
                "Attempt_For_Condition": self.current_attempt,
                "Repeat_Index": condition["Repeat_Index"],
                "Condition_Order": self.condition_order,
                "Random_Seed": self.random_seed,
                "Stim_Color_Name": condition["Stim_Color_Name"],
                "Stim_Intensity_Level": condition[
                    "Stim_Intensity_Level"
                ],
                "Stim_Target_Luminance_cd_m2": condition[
                    "Stim_Target_Luminance_cd_m2"
                ],
                "Stim_Calibration_Max_Level": condition[
                    "Stim_Calibration_Max_Level"
                ],
                "Requested_Control_Proportion": condition[
                    "Requested_Control_Proportion"
                ],
                "Actual_Control_Proportion": condition[
                    "Actual_Control_Proportion"
                ],
                "Background_Gray_Level": self.background_gray_level,
                "Background_Target_Luminance_cd_m2":
                    self.background_target_luminance,
                "Background_Color_R": self.background_rgb_255[0],
                "Background_Color_G": self.background_rgb_255[1],
                "Background_Color_B": self.background_rgb_255[2],
                "Is_Control": condition["Is_Control"],
            }
        )
        return trial_data

    def _run_response(self, trial_data):
        if not self.current_condition["Is_Control"]:
            return super()._run_response(trial_data)

        pause_requested = False
        while True:
            stim_on = trial_data["Time_StimOn"]
            if stim_on is None:
                self._schedule_flip_time(trial_data, "Time_StimOn")
                _, requested = self._present_frame(
                    False,
                    False,
                    False,
                    False,
                )
                pause_requested = pause_requested or requested
                continue

            if self.now() - stim_on >= self.stim_duration_s:
                return "Control_Blank", pause_requested

            _, requested = self._present_frame(
                False,
                False,
                False,
                False,
            )
            pause_requested = pause_requested or requested

    def _trial_should_reward(self, status, trial_data):
        if self.current_condition["Is_Control"]:
            return True
        return super()._trial_should_reward(status, trial_data)

    def _trial_status_for_log(self, status, trial_data):
        if self.current_condition["Is_Control"]:
            return "Control_Reward"
        return super()._trial_status_for_log(status, trial_data)

    def _poll_commands(self):
        keys = event.getKeys()
        if "escape" in keys:
            raise TaskAbort()
        return "n" in keys

    def _write_session_plan(self):
        plan_path = os.path.join(
            self.save_dir,
            f"SaccadeMultiStim_condition_plan_{self.session_timestamp}.csv",
        )
        with open(plan_path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=PLAN_FIELDS)
            writer.writeheader()
            writer.writerows(self.condition_plan)

        parameter_path = os.path.join(
            self.save_dir,
            f"SaccadeMultiStim_parameters_{self.session_timestamp}.json",
        )
        with open(parameter_path, "w", encoding="utf-8") as file:
            json.dump(
                self.task_manager.exp_params,
                file,
                ensure_ascii=False,
                indent=4,
            )
        return plan_path

    def run_task(self):
        if not self.task_manager.prompt_for_parameters():
            raise TaskAbort()
        self.update_params()
        plan_path = self._write_session_plan()
        event.clearEvents()

        planned_count = len(self.condition_plan)
        control_count = sum(
            bool(condition["Is_Control"])
            for condition in self.condition_plan
        )
        print("\n=== Saccade Multi-Stim Task started ===")
        print(
            f"Planned conditions: {planned_count}; "
            f"blank controls: {control_count}; order: {self.condition_order}."
        )
        print(f"Condition plan: {plan_path}")
        print(
            "A failed trial repeats the same condition. "
            "Blank controls are always rewarded. Press N to edit unlocked "
            "runtime parameters; press Esc to stop."
        )

        trial_number = 1
        condition_pointer = 0
        attempt_for_condition = 0
        pause_requested = False
        success_count = 0

        while condition_pointer < planned_count:
            if pause_requested:
                self._present_frame(False, False)
                if not self.task_manager.prompt_for_parameters(
                    disabled_parameters=LOCKED_DURING_SESSION_PARAMS,
                    parameter_validator=self._validate_runtime_params,
                    title=(
                        "Runtime Parameters / 运行中参数 "
                        "(gray fields are locked / 灰色项已锁定)"
                    ),
                ):
                    raise TaskAbort()
                self._update_runtime_params()
                event.clearEvents()
                pause_requested = False

            if self._run_iti():
                pause_requested = True
                continue

            condition = self.condition_plan[condition_pointer]
            attempt_for_condition += 1
            self.current_attempt = attempt_for_condition
            self._apply_condition(condition)

            print(
                f"\n--- Trial {trial_number}: "
                f"{condition['Condition_ID']} "
                f"(attempt {attempt_for_condition}) ---"
            )
            trial_data, requested = self._run_one_trial(trial_number)
            self._write_trial(trial_data)
            pause_requested = pause_requested or requested

            trial_succeeded = trial_data["Status"] in (
                "Success",
                "Control_Reward",
            )
            if trial_succeeded:
                success_count += 1
                condition_pointer += 1
                attempt_for_condition = 0
                print(
                    f"Result: {trial_data['Status']}; completed "
                    f"{condition_pointer}/{planned_count} planned conditions."
                )
            else:
                print(
                    f"Result: {trial_data['Status']}; "
                    f"{condition['Condition_ID']} will repeat."
                )

            recent_trials = self.behavior_log[-40:]
            recent_success_count = sum(
                trial["Status"] in ("Success", "Control_Reward")
                for trial in recent_trials
            )
            print(
                f"总体成功率: {success_count / trial_number:.1%} "
                f"({success_count}/{trial_number})"
            )
            print(
                f"最近40个 trial 的成功率: "
                f"{recent_success_count / len(recent_trials):.1%} "
                f"({recent_success_count}/{len(recent_trials)})"
            )
            trial_number += 1

        print(
            f"\n=== Session complete: all {planned_count} planned "
            f"conditions completed in {trial_number - 1} attempts ==="
        )


def _create_session_dir(script_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(
        script_dir,
        "experiment_logs",
        f"SaccadeMultiStim_{timestamp}",
    )
    candidate = base
    suffix = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{suffix:03d}"
        suffix += 1
    os.makedirs(candidate)
    return timestamp, candidate


def main(tracker_mode="qy"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    session_timestamp, save_dir = _create_session_dir(script_dir)
    session_t0 = time.perf_counter()

    save_gaze_csv = str(tracker_mode).lower() != "eyelink"
    gaze_log_queue = Queue(maxsize=20000) if save_gaze_csv else None
    dropped_samples = Value("i", 0)
    gaze_writer = None
    if save_gaze_csv:
        gaze_log_path = os.path.join(
            save_dir,
            f"SaccadeMultiStim_eye_log_{session_timestamp}.csv",
        )
        gaze_writer = GazeCsvWriter(gaze_log_queue, gaze_log_path)
        gaze_writer.start()

    tracker_runtime = None
    win_subject = None
    win_control = None
    task = None

    try:
        tracker_runtime = create_tracker_runtime(
            tracker_mode,
            is_simulating=bool(IS_SIMULATING),
            session_id=f"SaccadeMultiStim_{session_timestamp}",
            save_dir=save_dir,
            session_t0=session_t0,
            screen_size=(1920, 1080),
            qy_sample_rate=EYE_TRACKER_RATE_HZ,
            gaze_log_queue=gaze_log_queue,
            dropped_samples=dropped_samples,
        )
        gaze_source = tracker_runtime.gaze_source

        win_subject = visual.Window(
            screen=MONITOR_ID_SUBJECT,
            size=[1920, 1080],
            fullscr=False,
            waitBlanking=True,
            color="black",
            units="pix",
            allowGUI=False,
        )
        win_control = visual.Window(
            screen=MONITOR_ID_CONTROL,
            size=[800, 600],
            fullscr=False,
            waitBlanking=False,
            color="black",
            units="pix",
            title=f"Saccade Multi-Stim Control View ({tracker_runtime.mode})",
        )

        task_manager = FineVision_Notebook(
            task_name="SaccadeMultiStimTask",
            default_params=DEFAULT_PARAMS,
            parameter_groups=MULTISTIM_PARAMETER_GROUPS,
            parameter_validator=_validate_multistim_params,
            parameter_summary_provider=_multistim_trial_summary,
        )
        task = SaccadeMultiStimTask(
            win_subject,
            win_control,
            gaze_source,
            task_manager,
            IS_SIMULATING,
            session_t0,
            save_dir,
            session_timestamp,
            tracker_runtime,
        )
        print(f"[Session] Tracker: {tracker_runtime.mode}")
        print(f"[Session] Logs: {save_dir}")
        task.run_task()

    except (TaskAbort, SystemExit):
        print("Saccade multi-stim task stopped by user.")
    except Exception as exc:
        print(f"Saccade multi-stim task error: {exc}")
        traceback.print_exc()
    finally:
        if task is not None:
            try:
                task.close()
            except Exception:
                traceback.print_exc()

        if tracker_runtime is not None:
            try:
                tracker_runtime.close()
            except Exception:
                traceback.print_exc()

        if gaze_writer is not None:
            try:
                gaze_log_queue.put(STOP_TOKEN, timeout=2)
            except Full:
                print("[Warning] Gaze log queue was full during shutdown.")
            gaze_writer.join(timeout=10)
            if gaze_writer.is_alive():
                gaze_writer.terminate()
                gaze_writer.join(timeout=2)

            if gaze_writer.exitcode == 0:
                gaze_log_queue.close()
                gaze_log_queue.join_thread()
            else:
                gaze_log_queue.cancel_join_thread()
                gaze_log_queue.close()

        if dropped_samples.value:
            print(
                f"[Warning] Dropped {dropped_samples.value} gaze samples "
                "because the logging queue was full."
            )
        if gaze_writer is not None and gaze_writer.exitcode not in (0, None):
            print(
                f"[Warning] Gaze CSV writer exited with code "
                f"{gaze_writer.exitcode}."
            )

        if win_subject is not None:
            win_subject.close()
        if win_control is not None:
            win_control.close()
        print(f"[Session] Data saved in: {save_dir}")


if __name__ == "__main__":
    freeze_support()
    main()
