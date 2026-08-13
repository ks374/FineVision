import hashlib
import json
import os

from .base import SimulatedBackend
from .eyelink_backend import EyeLinkBackend
from .qy_backend import QYBackend


SUPPORTED_TRACKERS = {"qy", "eyelink", "mouse"}


def _load_eyelink_settings(path):
    with open(path, "r", encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    return settings


def _host_edf_name(session_id):
    # EyeLink Host base names are limited to eight characters.
    digest = hashlib.sha1(str(session_id).encode("utf-8")).hexdigest()[:7]
    return f"F{digest}.EDF".upper()


def create_tracker_runtime(
    tracker_mode,
    *,
    is_simulating=False,
    session_id="finevision",
    save_dir=".",
    session_t0=None,
    screen_size=(1920, 1080),
    qy_sample_rate=100,
    gaze_log_queue=None,
    dropped_samples=None,
    eyelink_settings_path="eyelink_setting.json",
):
    """Create the selected backend while keeping vendor imports out of tasks."""
    mode = "mouse" if is_simulating else str(tracker_mode).lower()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if mode not in SUPPORTED_TRACKERS:
        raise ValueError(
            f"Unknown tracker mode {tracker_mode!r}; expected one of "
            f"{sorted(SUPPORTED_TRACKERS)}."
        )

    if mode == "mouse":
        return SimulatedBackend(
            calibration_file=os.path.join(project_root, "default_setting.json")
        )
    if mode == "qy":
        return QYBackend(
            sample_rate=qy_sample_rate,
            calibration_file=os.path.join(project_root, "default_setting.json"),
            gaze_log_queue=gaze_log_queue,
            session_t0=session_t0,
            dropped_samples=dropped_samples,
        )

    settings_path = eyelink_settings_path
    if not os.path.isabs(settings_path):
        settings_path = os.path.join(project_root, settings_path)
    settings_path = os.path.abspath(settings_path)
    settings = _load_eyelink_settings(settings_path)
    calibration_file = settings.get(
        "calibration_file", "eyelink_default_setting.json"
    )
    active_eye = settings.get("active_eye", "right")
    if not os.path.isabs(calibration_file):
        calibration_file = os.path.join(
            os.path.dirname(settings_path), calibration_file
        )
    host_edf_name = _host_edf_name(session_id)
    local_edf_path = os.path.join(
        os.path.abspath(save_dir),
        f"{session_id}_eyelink.edf",
    )
    backend = EyeLinkBackend(
        host_ip=settings.get("host_ip", "100.1.1.1"),
        host_edf_name=host_edf_name,
        local_edf_path=local_edf_path,
        screen_size=screen_size,
        sample_rate=settings.get("sample_rate_hz", 1000),
        sample_source=settings.get("sample_source", "href"),
        calibration_file=calibration_file,
        active_eye=active_eye,
        session_t0=session_t0,
    )
    backend.send_event(
        f"FINEVISION_SESSION_ID {session_id} HOST_FILE {host_edf_name}"
    )
    return backend
