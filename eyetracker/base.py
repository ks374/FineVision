from abc import ABC, abstractmethod


class TrackerBackend(ABC):
    """Minimal contract shared by QY, EyeLink, and simulated tasks."""

    mode = "unknown"

    @property
    @abstractmethod
    def gaze_source(self):
        """Return an object exposing get_latest/get_latest_cal."""

    def send_event(self, message):
        """Record a task event on the tracker clock when supported."""

    def send_event_on_flip(self, window, message):
        """Queue a tracker event immediately after the next subject flip."""
        window.callOnFlip(self.send_event, message)

    @property
    def supports_recalibration(self):
        """Return whether the backend can reopen its native setup screen."""
        return False

    def recalibrate(self, window, **kwargs):
        """Run native calibration without closing the current data file."""
        raise RuntimeError(
            f"{type(self).__name__} does not support in-session calibration."
        )

    @abstractmethod
    def close(self):
        """Stop acquisition and release tracker resources."""


class SimulatedBackend(TrackerBackend):
    mode = "mouse"

    def __init__(self, calibration_file="default_setting.json"):
        from Shared_Memory_Util import SharedGazeData

        self._gaze_source = SharedGazeData(
            calibration_file=calibration_file
        )
        self._gaze_source.mode = self.mode

    @property
    def gaze_source(self):
        return self._gaze_source

    def close(self):
        self._gaze_source.stop()
