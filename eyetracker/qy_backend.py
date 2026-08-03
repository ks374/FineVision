from .base import TrackerBackend


class QYBackend(TrackerBackend):
    """Adapter around the existing QY worker-process implementation."""

    mode = "qy"

    def __init__(
        self,
        dll_path="EyeControl_SDK.dll",
        sample_rate=100,
        calibration_file="default_setting.json",
        gaze_log_queue=None,
        session_t0=None,
        dropped_samples=None,
    ):
        from QYEyetracker_Server import EyetrackerServer
        from Shared_Memory_Util import SharedGazeData

        self._gaze_source = SharedGazeData(
            calibration_file=calibration_file
        )
        self._gaze_source.mode = self.mode
        self._server = EyetrackerServer(
            self._gaze_source,
            dll_path,
            sample_rate,
            gaze_log_queue=gaze_log_queue,
            session_t0=session_t0,
            dropped_samples=dropped_samples,
        )
        self._server.start()
        print("QY eye-tracker server started.")

    @property
    def gaze_source(self):
        return self._gaze_source

    def close(self):
        self._gaze_source.stop()
        self._server.join(timeout=10)
        if self._server.is_alive():
            self._server.terminate()
            self._server.join(timeout=2)
