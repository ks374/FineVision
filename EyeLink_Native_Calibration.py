"""Run EyeLink's native camera setup/calibration from the task computer.

The EyeLink Host TRACK application must already be running.  This standalone
task opens the official EyeLink PsychoPy calibration graphics on a selectable
display and can use FineVision's Arduino reward controller during calibration.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from DisplayCalibration import (
    load_calibrated_gray_level,
    rgb255_to_psychopy,
)


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = SCRIPT_DIR / "eyelink_setting.json"
DEFAULT_TASK_PARAMS_PATH = SCRIPT_DIR / "params_SaccadeMultiStimTask.json"
DEFAULT_BRIGHTNESS_CALIBRATION_PATH = SCRIPT_DIR / "stim_calibration_0_20.json"
DEFAULT_SCREEN = 1
DEFAULT_SCREEN_SIZE = (1920, 1080)
DEFAULT_CALIBRATION_TYPE = "HV5"
BACKGROUND_GRAY_LEVEL = 5
MAX_CALIBRATION_ECCENTRICITY_DEG = 12.0


@dataclass
class NativeCalibrationConfig:
    host_ip: str = "100.1.1.1"
    screen: int = DEFAULT_SCREEN
    width: int = DEFAULT_SCREEN_SIZE[0]
    height: int = DEFAULT_SCREEN_SIZE[1]
    calibration_type: str = DEFAULT_CALIBRATION_TYPE
    max_eccentricity_deg: float = MAX_CALIBRATION_ECCENTRICITY_DEG
    viewing_distance_cm: float = 58.0
    monitor_width_cm: float = 54.0
    monitor_height_cm: float = 30.0
    fixation_point_radius_deg: float = 0.2
    background_gray_level: int = BACKGROUND_GRAY_LEVEL
    background_rgb_255: tuple[int, int, int] = (40, 40, 40)
    background_luminance_cd_m2: float = 5.875
    task_params_path: str = str(DEFAULT_TASK_PARAMS_PATH)
    brightness_calibration_path: str = str(
        DEFAULT_BRIGHTNESS_CALIBRATION_PATH
    )
    reward_mode: str = "advance"
    reward_ms: int = 300
    pacing_ms: int = 1200
    fullscreen: bool = True
    dummy: bool = False


def _load_json_object(path, description):
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8-sig") as source_file:
            payload = json.load(source_file)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read {description}: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} must contain a JSON object: {path}")
    return payload


def _load_task_display_profile(
    task_params_path=DEFAULT_TASK_PARAMS_PATH,
    brightness_calibration_path=DEFAULT_BRIGHTNESS_CALIBRATION_PATH,
    background_gray_level=BACKGROUND_GRAY_LEVEL,
):
    """Load the exact display geometry and gray background used by the task."""
    task_payload = _load_json_object(task_params_path, "saccade task settings")
    params = task_payload.get("parameters")
    if not isinstance(params, dict):
        raise RuntimeError(
            f"Missing 'parameters' in saccade task settings: {task_params_path}"
        )

    gray = load_calibrated_gray_level(
        background_gray_level,
        base_path=brightness_calibration_path,
    )

    try:
        return {
            "viewing_distance_cm": float(params["Viewing Distance (cm)"]),
            "monitor_width_cm": float(params["Subject Monitor Width (cm)"]),
            "monitor_height_cm": float(params["Subject Monitor Height (cm)"]),
            "fixation_point_radius_deg": float(
                params["Fixation Point Radius (deg)"]
            ),
            "background_rgb_255": gray["rgb_255"],
            "background_luminance_cd_m2": gray["luminance_cd_m2"],
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "Saccade task display geometry contains a missing or invalid value."
        ) from exc


def _axis_calibration_extent(
    max_eccentricity_deg,
    viewing_distance_cm,
    monitor_size_cm,
    resolution_pixels,
):
    """Return an EyeLink area proportion that cannot exceed the angle limit."""
    if not 0.0 < float(max_eccentricity_deg) <= 12.0:
        raise ValueError("Maximum calibration eccentricity must be > 0 and <= 12 deg.")
    if float(viewing_distance_cm) <= 0 or float(monitor_size_cm) <= 0:
        raise ValueError("Viewing distance and monitor dimensions must be positive.")
    if int(resolution_pixels) < 3:
        raise ValueError("Screen resolution is too small for calibration.")

    offset_cm = float(viewing_distance_cm) * math.tan(
        math.radians(float(max_eccentricity_deg))
    )
    requested_offset_px = (
        offset_cm * int(resolution_pixels) / float(monitor_size_cm)
    )
    maximum_visible_offset_px = int(resolution_pixels) // 2 - 1
    offset_px = min(math.floor(requested_offset_px), maximum_visible_offset_px)
    if offset_px < 1:
        raise ValueError("Calibration extent is smaller than one pixel.")

    proportion = 2.0 * offset_px / int(resolution_pixels)
    actual_offset_cm = (
        offset_px * float(monitor_size_cm) / int(resolution_pixels)
    )
    actual_eccentricity_deg = math.degrees(
        math.atan(actual_offset_cm / float(viewing_distance_cm))
    )
    return {
        "proportion": proportion,
        "offset_px": offset_px,
        "eccentricity_deg": actual_eccentricity_deg,
    }


def _calibration_area(config, width, height):
    return {
        "x": _axis_calibration_extent(
            config.max_eccentricity_deg,
            config.viewing_distance_cm,
            config.monitor_width_cm,
            width,
        ),
        "y": _axis_calibration_extent(
            config.max_eccentricity_deg,
            config.viewing_distance_cm,
            config.monitor_height_cm,
            height,
        ),
    }


def _task_visual_angle_to_pixels(
    angle_deg, viewing_distance_cm, monitor_size_cm, resolution_pixels
):
    """Match SaccadeTask.visual_angle_to_pixels for target dimensions."""
    size_cm = 2.0 * float(viewing_distance_cm) * math.tan(
        math.radians(float(angle_deg)) / 2.0
    )
    return size_cm * int(resolution_pixels) / float(monitor_size_cm)


def _native_edf_paths(started_at=None):
    """Create an eight-character Host name and a readable local EDF path."""
    started_at = started_at or datetime.now()
    session_id = started_at.strftime("%Y%m%d_%H%M%S_%f")
    digest = hashlib.sha1(session_id.encode("ascii")).hexdigest()[:7]
    host_edf_name = f"N{digest}.EDF".upper()
    local_edf_path = (
        SCRIPT_DIR
        / "experiment_logs"
        / f"eyelink_native_calibration_{session_id}.edf"
    )
    return session_id, host_edf_name, local_edf_path


def _default_host_ip():
    try:
        with DEFAULT_SETTINGS_PATH.open("r", encoding="utf-8") as settings_file:
            return str(json.load(settings_file).get("host_ip", "100.1.1.1"))
    except (OSError, ValueError, TypeError):
        return "100.1.1.1"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run native EyeLink calibration on a selected display."
    )
    parser.add_argument("--screen", type=int, default=None,
                        help="PsychoPy display index; default dialog value is 1.")
    parser.add_argument("--width", type=int, default=DEFAULT_SCREEN_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SCREEN_SIZE[1])
    parser.add_argument("--host", default=_default_host_ip())
    parser.add_argument(
        "--calibration",
        choices=("HV5", "HV9"),
        default=DEFAULT_CALIBRATION_TYPE,
    )
    parser.add_argument(
        "--max-eccentricity-deg",
        type=float,
        default=MAX_CALIBRATION_ECCENTRICITY_DEG,
        help="Outermost horizontal/vertical target angle (maximum 12 deg).",
    )
    parser.add_argument(
        "--task-params",
        default=str(DEFAULT_TASK_PARAMS_PATH),
        help="SaccadeMultiStimTask parameter JSON used for display geometry.",
    )
    parser.add_argument(
        "--brightness-calibration",
        default=str(DEFAULT_BRIGHTNESS_CALIBRATION_PATH),
        help="Base brightness calibration JSON containing Gray levels 0-20.",
    )
    parser.add_argument(
        "--background-gray-level",
        type=int,
        default=BACKGROUND_GRAY_LEVEL,
    )
    parser.add_argument("--viewing-distance-cm", type=float, default=None)
    parser.add_argument("--monitor-width-cm", type=float, default=None)
    parser.add_argument("--monitor-height-cm", type=float, default=None)
    parser.add_argument(
        "--fixation-point-radius-deg", type=float, default=None
    )
    parser.add_argument("--reward-mode", choices=("advance", "manual", "off"),
                        default="advance")
    parser.add_argument("--reward-ms", type=int, default=300)
    parser.add_argument("--pacing-ms", type=int, default=1200)
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--dummy", action="store_true",
                        help="Use EyeLink mouse simulation without hardware.")
    parser.add_argument("--no-dialog", action="store_true",
                        help="Use command-line settings without the startup dialog.")
    return parser.parse_args(argv)


def _config_from_args(args):
    profile = _load_task_display_profile(
        args.task_params,
        args.brightness_calibration,
        args.background_gray_level,
    )
    max_eccentricity_deg = float(args.max_eccentricity_deg)
    if not 0.0 < max_eccentricity_deg <= MAX_CALIBRATION_ECCENTRICITY_DEG:
        raise ValueError(
            "--max-eccentricity-deg must be greater than 0 and no more than 12."
        )
    config = NativeCalibrationConfig(
        host_ip=str(args.host),
        screen=DEFAULT_SCREEN if args.screen is None else int(args.screen),
        width=int(args.width),
        height=int(args.height),
        calibration_type=str(args.calibration),
        max_eccentricity_deg=max_eccentricity_deg,
        viewing_distance_cm=(
            profile["viewing_distance_cm"]
            if args.viewing_distance_cm is None
            else float(args.viewing_distance_cm)
        ),
        monitor_width_cm=(
            profile["monitor_width_cm"]
            if args.monitor_width_cm is None
            else float(args.monitor_width_cm)
        ),
        monitor_height_cm=(
            profile["monitor_height_cm"]
            if args.monitor_height_cm is None
            else float(args.monitor_height_cm)
        ),
        fixation_point_radius_deg=(
            profile["fixation_point_radius_deg"]
            if args.fixation_point_radius_deg is None
            else float(args.fixation_point_radius_deg)
        ),
        background_gray_level=int(args.background_gray_level),
        background_rgb_255=profile["background_rgb_255"],
        background_luminance_cd_m2=profile["background_luminance_cd_m2"],
        task_params_path=str(Path(args.task_params).resolve()),
        brightness_calibration_path=str(
            Path(args.brightness_calibration).resolve()
        ),
        reward_mode=str(args.reward_mode),
        reward_ms=max(0, int(args.reward_ms)),
        pacing_ms=max(250, int(args.pacing_ms)),
        fullscreen=not bool(args.windowed),
        dummy=bool(args.dummy),
    )
    _validate_native_config(config)
    return config


def _validate_native_config(config):
    if config.calibration_type not in {"HV5", "HV9"}:
        raise ValueError("Calibration Type must be HV5 or HV9.")
    if not 0.0 < config.max_eccentricity_deg <= 12.0:
        raise ValueError("Maximum Calibration Eccentricity must be <= 12 deg.")
    if config.viewing_distance_cm <= 0:
        raise ValueError("Viewing Distance must be positive.")
    if config.monitor_width_cm <= 0 or config.monitor_height_cm <= 0:
        raise ValueError("Monitor dimensions must be positive.")
    if config.fixation_point_radius_deg <= 0:
        raise ValueError("Fixation Point Radius must be positive.")
    if config.width < 3 or config.height < 3:
        raise ValueError("Screen resolution is too small.")
    if config.screen < 0:
        raise ValueError("Subject Screen Index cannot be negative.")
    if config.reward_ms < 0 or config.pacing_ms < 250:
        raise ValueError("Reward and pacing values are invalid.")
    load_calibrated_gray_level(
        config.background_gray_level,
        base_path=config.brightness_calibration_path,
    )
    _calibration_area(config, config.width, config.height)


def _native_dialog_params(config):
    calibration_choices = [config.calibration_type] + [
        value for value in ("HV5", "HV9")
        if value != config.calibration_type
    ]
    reward_choices = [config.reward_mode] + [
        value for value in ("advance", "manual", "off")
        if value != config.reward_mode
    ]
    return {
        "EyeLink Host IP": config.host_ip,
        "Calibration Type": calibration_choices,
        "Maximum Calibration Eccentricity (deg)": config.max_eccentricity_deg,
        "Fixation Point Radius (deg)": config.fixation_point_radius_deg,
        "Background Gray Level (0-182)": config.background_gray_level,
        "Viewing Distance (cm)": config.viewing_distance_cm,
        "Subject Monitor Width (cm)": config.monitor_width_cm,
        "Subject Monitor Height (cm)": config.monitor_height_cm,
        "Subject Screen Index": config.screen,
        "Screen Width (px)": config.width,
        "Screen Height (px)": config.height,
        "Full Screen": config.fullscreen,
        "Reward Mode": reward_choices,
        "Reward Duration (ms)": config.reward_ms,
        "Automatic Pacing (ms)": config.pacing_ms,
    }


NATIVE_PARAMETER_GROUPS = {
    "Connection / 连接": [
        "EyeLink Host IP",
        "Subject Screen Index",
        "Screen Width (px)",
        "Screen Height (px)",
        "Full Screen",
    ],
    "Calibration / 校准": [
        "Calibration Type",
        "Maximum Calibration Eccentricity (deg)",
        "Fixation Point Radius (deg)",
    ],
    "Display / 屏幕": [
        "Background Gray Level (0-182)",
        "Viewing Distance (cm)",
        "Subject Monitor Width (cm)",
        "Subject Monitor Height (cm)",
    ],
    "Reward / 奖励": [
        "Reward Mode",
        "Reward Duration (ms)",
        "Automatic Pacing (ms)",
    ],
}


def _config_from_dialog_params(config, params):
    gray = load_calibrated_gray_level(
        params["Background Gray Level (0-182)"],
        base_path=config.brightness_calibration_path,
    )
    updated = replace(
        config,
        host_ip=str(params["EyeLink Host IP"]).strip(),
        calibration_type=str(params["Calibration Type"]),
        max_eccentricity_deg=float(
            params["Maximum Calibration Eccentricity (deg)"]
        ),
        fixation_point_radius_deg=float(
            params["Fixation Point Radius (deg)"]
        ),
        background_gray_level=int(
            params["Background Gray Level (0-182)"]
        ),
        background_rgb_255=gray["rgb_255"],
        background_luminance_cd_m2=gray["luminance_cd_m2"],
        viewing_distance_cm=float(params["Viewing Distance (cm)"]),
        monitor_width_cm=float(params["Subject Monitor Width (cm)"]),
        monitor_height_cm=float(params["Subject Monitor Height (cm)"]),
        screen=int(params["Subject Screen Index"]),
        width=int(params["Screen Width (px)"]),
        height=int(params["Screen Height (px)"]),
        fullscreen=bool(params["Full Screen"]),
        reward_mode=str(params["Reward Mode"]),
        reward_ms=int(params["Reward Duration (ms)"]),
        pacing_ms=int(params["Automatic Pacing (ms)"]),
    )
    _validate_native_config(updated)
    return updated


def _validate_native_dialog_params(config, params):
    _config_from_dialog_params(config, params)
    return None


def _native_parameter_summary(config, params):
    updated = _config_from_dialog_params(config, params)
    area = _calibration_area(updated, updated.width, updated.height)
    return (
        f"{updated.calibration_type}: outer targets "
        f"±{area['x']['eccentricity_deg']:.2f}° horizontal, "
        f"±{area['y']['eccentricity_deg']:.2f}° vertical\n"
        f"Background: level {updated.background_gray_level}, "
        f"RGB {updated.background_rgb_255}, "
        f"{updated.background_luminance_cd_m2:.3f} cd/m²"
    )


def _show_config_dialog(config):
    from FineVision_Notebook import FineVision_Notebook

    manager = FineVision_Notebook(
        task_name="EyeLinkNativeCalibration",
        default_params=_native_dialog_params(config),
        parameter_groups=NATIVE_PARAMETER_GROUPS,
        parameter_validator=lambda params: _validate_native_dialog_params(
            config, params
        ),
        parameter_summary_provider=lambda params: _native_parameter_summary(
            config, params
        ),
    )
    if not manager.prompt_for_parameters(
        title="EyeLink Native Calibration / 原生校准参数"
    ):
        return None
    return _config_from_dialog_params(config, manager.exp_params)


def _find_official_graphics_helper():
    """Locate SR Research's installed PsychoPy graphics helper.

    The helper is part of the EyeLink Developers Kit samples and its licence
    does not permit copying it into this repository, so it is loaded in place.
    """
    local_helper = SCRIPT_DIR / "EyeLinkCoreGraphicsPsychoPy.py"
    if local_helper.exists():
        return local_helper

    roots = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value) / "SR Research" / "EyeLink")

    relative = Path(
        "SampleExperiments/Python/examples/Psychopy_examples/Coder/"
        "saccade/EyeLinkCoreGraphicsPsychoPy.py"
    )
    for root in roots:
        exact_path = root / relative
        if exact_path.exists():
            return exact_path

    for root in roots:
        sample_root = root / "SampleExperiments" / "Python" / "examples"
        if not sample_root.exists():
            continue
        match = next(sample_root.rglob("EyeLinkCoreGraphicsPsychoPy.py"), None)
        if match is not None:
            return match

    raise RuntimeError(
        "Could not find EyeLinkCoreGraphicsPsychoPy.py. Install the EyeLink "
        "Developers Kit samples, or copy the official helper next to this task."
    )


def _load_official_graphics_class():
    helper_path = _find_official_graphics_helper()
    module_name = "_finevision_official_eyelink_psychopy_graphics"
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load EyeLink graphics helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.EyeLinkCoreGraphicsPsychoPy, helper_path


def _build_rewarding_graphics(
    base_class,
    pylink_module,
    *,
    auto_exit_after_success=False,
    auto_start_calibration=False,
):
    class RewardingEyeLinkGraphics(base_class):
        def __init__(self, tracker, win, arduino, reward_mode, reward_ms):
            # Disable the helper's WAV sounds. FineVision's Arduino controller
            # provides its own short audible reward cue when reward is enabled.
            super().__init__(tracker, win, True)
            self._tracker = tracker
            self._arduino = arduino
            self._reward_mode = reward_mode
            self._reward_ms = int(reward_ms)
            self._last_target = None
            self._target_visible = False
            self._target_index = 0
            self._phase = "SETUP"
            self._auto_exit_after_success = bool(auto_exit_after_success)
            self._auto_start_calibration = bool(auto_start_calibration)
            self._auto_start_sent = False
            self._return_to_task_requested = False
            self.reward_events = []
            self.edf_events = []

        def _send_edf_event(self, event_name, **fields):
            message_parts = [str(event_name)]
            for key, value in fields.items():
                clean_value = str(value).replace("\n", " ").replace("\r", " ")
                clean_value = clean_value.replace(" ", "_")
                message_parts.extend((str(key).upper(), clean_value))
            message = " ".join(message_parts)
            event_record = {
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "message": message,
            }
            self.edf_events.append(event_record)
            if self._tracker is not None:
                try:
                    self._tracker.sendMessage(message)
                except Exception as exc:
                    event_record["send_error"] = str(exc)
                    print(f"[Warning] Could not write EDF event: {message}")

        def _deliver_reward(self, reason):
            if self._arduino is None or self._reward_ms <= 0:
                return
            self._arduino.reward(duration_ms=self._reward_ms)
            event_record = {
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "reason": str(reason),
                "target": self._last_target,
                "duration_ms": self._reward_ms,
            }
            self.reward_events.append(event_record)
            target_x = None if self._last_target is None else self._last_target[0]
            target_y = None if self._last_target is None else self._last_target[1]
            self._send_edf_event(
                "NATIVE_REWARD",
                reason=reason,
                duration_ms=self._reward_ms,
                target_x=target_x,
                target_y=target_y,
            )
            print(
                f"[Reward] {reason}: {self._reward_ms} ms "
                f"at target {self._last_target}"
            )

        def draw_cal_target(self, x, y):
            new_target = (int(round(x)), int(round(y)))
            new_presentation = (
                not self._target_visible or new_target != self._last_target
            )
            if (
                self._reward_mode == "advance"
                and self._last_target is not None
                and new_target != self._last_target
            ):
                # EyeLink only advances to a different coordinate after it has
                # collected the previous target. Reward before drawing the new
                # target so water remains associated with the previous point.
                self._deliver_reward("target_advanced")
            self._last_target = new_target
            self._target_visible = True
            result = super().draw_cal_target(x, y)
            if new_presentation:
                self._target_index += 1
                self._send_edf_event(
                    "NATIVE_CAL_TARGET_ON",
                    phase=self._phase,
                    index=self._target_index,
                    x=new_target[0],
                    y=new_target[1],
                )
            return result

        def erase_cal_target(self):
            previous_target = self._last_target
            was_visible = self._target_visible
            self._target_visible = False
            result = super().erase_cal_target()
            if was_visible and previous_target is not None:
                self._send_edf_event(
                    "NATIVE_CAL_TARGET_OFF",
                    phase=self._phase,
                    index=self._target_index,
                    x=previous_target[0],
                    y=previous_target[1],
                )
            return result

        def get_input_key(self):
            keys = list(super().get_input_key() or [])
            if self._auto_start_calibration and not self._auto_start_sent:
                # A Host-side C command starts the Host's own target display.
                # Injecting C through the display-PC graphics handler starts
                # calibration on the PsychoPy subject window instead.
                keys.append(pylink_module.KeyInput(ord("c"), 0))
                self._auto_start_sent = True
                self._send_edf_event("NATIVE_CAL_AUTO_START_REQUESTED")
            for key_input in keys or []:
                key_code = getattr(key_input, "__key__", None)
                if key_code in (ord("c"), ord("C")):
                    self._phase = "CALIBRATION"
                    self._send_edf_event(
                        "NATIVE_CAL_PHASE_START", phase=self._phase
                    )
                elif key_code in (ord("v"), ord("V")):
                    self._phase = "VALIDATION"
                    self._send_edf_event(
                        "NATIVE_CAL_PHASE_START", phase=self._phase
                    )
            if self._reward_mode == "manual" and self._target_visible:
                if any(
                    getattr(key_input, "__key__", None) == ord(" ")
                    for key_input in (keys or [])
                ):
                    self._send_edf_event(
                        "NATIVE_CAL_MANUAL_ACCEPT",
                        phase=self._phase,
                        index=self._target_index,
                    )
                    self._deliver_reward("manual_space")
            if self._return_to_task_requested:
                keys = list(keys or [])
                keys.append(pylink_module.KeyInput(27, 0))
                self._return_to_task_requested = False
                self._send_edf_event("NATIVE_CAL_RETURN_TO_TASK")
            return keys

        def play_beep(self, beepid):
            if beepid == pylink_module.CAL_GOOD_BEEP:
                self._send_edf_event(
                    "NATIVE_CAL_RESULT",
                    phase=self._phase,
                    result="GOOD",
                )
                if self._reward_mode == "advance" and self._last_target is not None:
                    # The target-advance rule cannot reward the final point,
                    # because no next target follows it. CAL_GOOD_BEEP marks a
                    # successful end to calibration or validation.
                    self._deliver_reward("calibration_or_validation_complete")
                self._last_target = None
                self._target_visible = False
                self._phase = "SETUP"
                if self._auto_exit_after_success:
                    self._return_to_task_requested = True
            elif beepid == pylink_module.CAL_ERR_BEEP:
                self._send_edf_event(
                    "NATIVE_CAL_RESULT",
                    phase=self._phase,
                    result="ERROR",
                )
                self._last_target = None
                self._target_visible = False
                self._phase = "SETUP"
            elif beepid == getattr(pylink_module, "CAL_TARG_BEEP", None):
                self._send_edf_event(
                    "NATIVE_CAL_TARGET_BEEP",
                    phase=self._phase,
                    index=self._target_index,
                )
            return super().play_beep(beepid)

    return RewardingEyeLinkGraphics


def _write_session_log(
    config,
    status,
    helper_path,
    graphics,
    session_id=None,
    host_edf_name=None,
    local_edf_path=None,
    edf_downloaded=False,
    edf_transfer_error=None,
    calibration_area=None,
    target_size_px=None,
    error=None,
):
    log_dir = SCRIPT_DIR / "experiment_logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"eyelink_native_calibration_{timestamp}.json"
    payload = {
        "status": status,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "host_ip": config.host_ip,
        "screen": config.screen,
        "screen_size": [config.width, config.height],
        "calibration_type": config.calibration_type,
        "max_eccentricity_deg": config.max_eccentricity_deg,
        "calibration_area": calibration_area,
        "viewing_distance_cm": config.viewing_distance_cm,
        "monitor_size_cm": [
            config.monitor_width_cm,
            config.monitor_height_cm,
        ],
        "target_size_px": target_size_px,
        "fixation_point_radius_deg": config.fixation_point_radius_deg,
        "background_gray_level": config.background_gray_level,
        "background_rgb_255": list(config.background_rgb_255),
        "background_luminance_cd_m2": config.background_luminance_cd_m2,
        "task_params_path": config.task_params_path,
        "brightness_calibration_path": config.brightness_calibration_path,
        "reward_mode": config.reward_mode,
        "reward_ms": config.reward_ms,
        "automatic_pacing_ms": config.pacing_ms,
        "dummy": config.dummy,
        "session_id": session_id,
        "host_edf_name": host_edf_name,
        "local_edf_path": (
            None if local_edf_path is None else str(local_edf_path)
        ),
        "edf_downloaded": bool(edf_downloaded),
        "edf_transfer_error": (
            None if edf_transfer_error is None else str(edf_transfer_error)
        ),
        "graphics_helper": None if helper_path is None else str(helper_path),
        "reward_events": [] if graphics is None else graphics.reward_events,
        "edf_events": [] if graphics is None else graphics.edf_events,
        "error": None if error is None else str(error),
    }
    with log_path.open("w", encoding="utf-8") as log_file:
        json.dump(payload, log_file, indent=2, ensure_ascii=False)
    print(f"Session log: {log_path}")
    return log_path


def run_native_calibration(config):
    import pylink
    from psychopy import visual

    from FineVision_Util import ArduinoController

    tracker = None
    win = None
    arduino = None
    graphics = None
    helper_path = None
    calibration_area = None
    target_size_px = None
    session_started_at = datetime.now()
    session_id, host_edf_name, local_edf_path = _native_edf_paths(
        session_started_at
    )
    local_edf_path.parent.mkdir(exist_ok=True)
    data_file_open = False
    edf_downloaded = False
    edf_transfer_error = None
    status = "error"
    caught_error = None

    try:
        if config.reward_mode != "off":
            arduino = ArduinoController()
            if getattr(arduino, "conn", None) is None:
                print(
                    "[Warning] Arduino was not detected. Calibration will run, "
                    "but only the local reward sound will be available."
                )

        print(
            f"Opening calibration display {config.screen} at "
            f"{config.width}x{config.height} ..."
        )
        background_color = rgb255_to_psychopy(config.background_rgb_255)
        win = visual.Window(
            size=(config.width, config.height),
            screen=config.screen,
            fullscr=config.fullscreen,
            color=background_color,
            colorSpace="rgb",
            units="pix",
            allowGUI=False,
            waitBlanking=True,
            title="FineVision EyeLink Native Calibration",
        )
        actual_width, actual_height = (int(value) for value in win.size)
        config.width = actual_width
        config.height = actual_height
        calibration_area = _calibration_area(
            config, actual_width, actual_height
        )
        target_radius_px = _task_visual_angle_to_pixels(
            config.fixation_point_radius_deg,
            config.viewing_distance_cm,
            config.monitor_width_cm,
            actual_width,
        )
        target_size_px = max(2, int(round(2.0 * target_radius_px)))

        if config.dummy:
            print("Connecting to EyeLink mouse simulation ...")
            tracker = pylink.EyeLink(None)
        else:
            print(f"Connecting to EyeLink Host at {config.host_ip} ...")
            tracker = pylink.EyeLink(config.host_ip)
            if not tracker.isConnected():
                raise RuntimeError(f"EyeLink Host {config.host_ip} is not connected.")

        tracker.setOfflineMode()
        open_result = tracker.openDataFile(host_edf_name)
        if open_result not in (None, 0):
            raise RuntimeError(
                f"EyeLink could not create Host EDF {host_edf_name}: "
                f"status {open_result}"
            )
        data_file_open = True
        tracker.sendCommand(
            f"screen_pixel_coords = 0 0 {actual_width - 1} {actual_height - 1}"
        )
        tracker.sendMessage(
            f"DISPLAY_COORDS 0 0 {actual_width - 1} {actual_height - 1}"
        )
        tracker.sendCommand(
            "file_event_filter = LEFT,RIGHT,FIXATION,SACCADE,BLINK,"
            "MESSAGE,BUTTON,INPUT"
        )
        tracker.sendCommand(
            "file_sample_data = LEFT,RIGHT,GAZE,HREF,RAW,GAZERES,"
            "AREA,STATUS,INPUT"
        )
        tracker.sendCommand(f"calibration_type = {config.calibration_type}")
        x_proportion = calibration_area["x"]["proportion"]
        y_proportion = calibration_area["y"]["proportion"]
        tracker.sendCommand(
            "calibration_area_proportion "
            f"{x_proportion:.6f} {y_proportion:.6f}"
        )
        tracker.sendCommand(
            "validation_area_proportion "
            f"{x_proportion:.6f} {y_proportion:.6f}"
        )
        tracker.sendMessage(
            "NATIVE_CAL_SESSION_START "
            f"SESSION {session_id} TYPE {config.calibration_type} "
            f"GRAY_LEVEL {config.background_gray_level} "
            f"BACKGROUND_RGB {'_'.join(str(v) for v in config.background_rgb_255)}"
        )
        if config.reward_mode == "manual":
            tracker.sendCommand("enable_automatic_calibration = NO")
        else:
            tracker.sendCommand("enable_automatic_calibration = YES")
            tracker.sendCommand(
                f"automatic_calibration_pacing = {config.pacing_ms}"
            )

        official_graphics, helper_path = _load_official_graphics_class()
        rewarding_graphics = _build_rewarding_graphics(
            official_graphics, pylink
        )
        graphics = rewarding_graphics(
            tracker,
            win,
            arduino,
            config.reward_mode,
            config.reward_ms,
        )
        graphics.setCalibrationColors("white", background_color)
        graphics.setTargetType("circle")
        graphics.setTargetSize(target_size_px)
        mode_instruction = (
            "SPACE: accept target + reward\n"
            if config.reward_mode == "manual"
            else "Targets advance automatically\n"
        )
        graphics._calibInst.text = (
            "ENTER: show/hide camera image    C: calibration    V: validation\n"
            f"{mode_instruction}ESC: finish and return to FineVision"
        )
        pylink.openGraphicsEx(graphics)

        print("\nEyeLink native setup is ready.")
        print(f"Host EDF: {host_edf_name}")
        print(f"Local EDF after calibration: {local_edf_path}")
        print(
            "Background: calibrated Gray level "
            f"{config.background_gray_level}, RGB {config.background_rgb_255}, "
            f"{config.background_luminance_cd_m2:g} cd/m2."
        )
        print(
            "Five-point outer target positions: "
            f"horizontal +/-{calibration_area['x']['offset_px']} px "
            f"({calibration_area['x']['eccentricity_deg']:.3f} deg), "
            f"vertical +/-{calibration_area['y']['offset_px']} px "
            f"({calibration_area['y']['eccentricity_deg']:.3f} deg)."
        )
        print("C = calibration, V = validation, ESC = finish.")
        if config.reward_mode == "manual":
            print("Manual mode: press SPACE only while the monkey fixates the target.")
        elif config.reward_mode == "advance":
            print("Automatic mode: reward follows each accepted target transition.")

        tracker.doTrackerSetup()
        status = "completed"
        print("EyeLink native setup/calibration closed normally.")
    except BaseException as exc:
        caught_error = exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            status = "aborted"
        else:
            print(f"EyeLink native calibration failed: {exc}")
        raise
    finally:
        if tracker is not None:
            try:
                tracker.setOfflineMode()
            except Exception:
                pass
        if tracker is not None and data_file_open:
            try:
                tracker.sendMessage(
                    f"NATIVE_CAL_SESSION_END STATUS {status.upper()}"
                )
                try:
                    pylink.pumpDelay(100)
                except Exception:
                    pass
            except Exception:
                pass
        if tracker is not None and data_file_open:
            try:
                tracker.closeDataFile()
                data_file_open = False
                tracker.receiveDataFile(
                    host_edf_name,
                    str(local_edf_path),
                )
                edf_downloaded = True
                print(f"EyeLink calibration EDF saved to: {local_edf_path}")
            except Exception as exc:
                edf_transfer_error = exc
                if status == "completed":
                    status = "completed_edf_transfer_failed"
                print(f"[Warning] EyeLink EDF download failed: {exc}")
        # Keep the graphics adapter registered through receiveDataFile().
        # PyLink may poll get_input_key during transfer; closing it earlier can
        # leave a None adapter and raise AttributeError.
        try:
            pylink.closeGraphics()
        except Exception:
            pass
        if tracker is not None:
            try:
                tracker.close()
            except Exception:
                pass
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        if arduino is not None:
            try:
                arduino.close()
            except Exception:
                pass
        _write_session_log(
            config,
            status,
            helper_path,
            graphics,
            session_id=session_id,
            host_edf_name=host_edf_name,
            local_edf_path=local_edf_path,
            edf_downloaded=edf_downloaded,
            edf_transfer_error=edf_transfer_error,
            calibration_area=calibration_area,
            target_size_px=target_size_px,
            error=caught_error,
        )


def main(argv=None):
    args = _parse_args(argv)
    config = _config_from_args(args)
    if not args.no_dialog:
        config = _show_config_dialog(config)
        if config is None:
            print("Calibration cancelled.")
            return 0
    run_native_calibration(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
