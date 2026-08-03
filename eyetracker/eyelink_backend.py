import math
import os
import time

from .base import TrackerBackend


INVALID_GAZE = -999.0


class EyeLinkBackend(TrackerBackend):
    """Direct PyLink backend with EDF recording and custom calibration input.

    FineVision intentionally does not call EyeLink's display calibration here.
    With ``sample_source='href'``, the user's CalibrationManager maps the HREF
    coordinates into FineVision screen coordinates.  Camera setup and tracking
    quality still need to be checked on the EyeLink Host before the task.
    """

    mode = "eyelink"

    def __init__(
        self,
        host_ip,
        host_edf_name,
        local_edf_path,
        screen_size=(1920, 1080),
        sample_rate=1000,
        sample_source="href",
        calibration_file="eyelink_default_setting.json",
        session_t0=None,
    ):
        from Shared_Memory_Util import SharedGazeData

        self.host_ip = str(host_ip)
        self.host_edf_name = str(host_edf_name)
        self.local_edf_path = os.path.abspath(local_edf_path)
        self.screen_width = int(screen_size[0])
        self.screen_height = int(screen_size[1])
        self.sample_rate = int(sample_rate)
        self.sample_source = str(sample_source).lower()
        if self.sample_source not in {"href", "gaze"}:
            raise ValueError("EyeLink sample_source must be 'href' or 'gaze'.")

        self.session_t0 = (
            float(session_t0) if session_t0 is not None else time.perf_counter()
        )
        self._gaze_source = SharedGazeData(
            calibration_file=calibration_file
        )
        self._pylink = None
        self._tracker = None
        self._recording = False
        self._data_file_open = False
        self._closed = False
        self._last_sample_time = None
        try:
            self._connect_and_record()
        except Exception:
            self._close_after_startup_error()
            raise

    @property
    def gaze_source(self):
        return self

    def _connect_and_record(self):
        try:
            import pylink
        except ImportError as exc:
            raise RuntimeError(
                "PyLink is not installed. Install the EyeLink Developers Kit "
                "and the PyLink build matching FineVision's Python version."
            ) from exc

        self._pylink = pylink
        print(f"Connecting to EyeLink Host at {self.host_ip} ...")
        self._tracker = pylink.EyeLink(self.host_ip)
        if not self._tracker.isConnected():
            raise RuntimeError(f"EyeLink Host {self.host_ip} is not connected.")

        self._tracker.setOfflineMode()
        self._tracker.openDataFile(self.host_edf_name)
        self._data_file_open = True
        self._configure_tracker()
        result = self._tracker.startRecording(1, 1, 1, 1)
        if result not in (None, 0):
            raise RuntimeError(f"EyeLink startRecording failed: {result}")
        self._recording = True
        pylink.pumpDelay(100)
        self.send_event("FINEVISION_SESSION_START")
        print(
            f"EyeLink recording started; Host EDF: {self.host_edf_name}"
        )

    def _close_after_startup_error(self):
        if self._tracker is None:
            return
        try:
            if self._recording:
                self._tracker.stopRecording()
                self._recording = False
            self._tracker.setOfflineMode()
            if self._data_file_open:
                self._tracker.closeDataFile()
                self._data_file_open = False
        except Exception:
            pass
        finally:
            try:
                self._tracker.close()
            except Exception:
                pass

    def _configure_tracker(self):
        right = self.screen_width - 1
        bottom = self.screen_height - 1
        self._tracker.sendCommand(
            f"screen_pixel_coords = 0 0 {right} {bottom}"
        )
        self._tracker.sendMessage(f"DISPLAY_COORDS 0 0 {right} {bottom}")
        self._tracker.sendCommand(f"sample_rate = {self.sample_rate}")
        self._tracker.sendCommand(
            "file_event_filter = LEFT,RIGHT,FIXATION,SACCADE,BLINK,"
            "MESSAGE,BUTTON,INPUT"
        )
        self._tracker.sendCommand(
            "file_sample_data = LEFT,RIGHT,GAZE,HREF,RAW,GAZERES,"
            "AREA,STATUS,INPUT"
        )
        self._tracker.sendCommand(
            "link_event_filter = LEFT,RIGHT,FIXATION,SACCADE,BLINK,"
            "BUTTON"
        )
        self._tracker.sendCommand(
            "link_sample_data = LEFT,RIGHT,GAZE,HREF,RAW,AREA,STATUS"
        )

    def _is_valid_pair(self, pair):
        if pair is None or len(pair) < 2:
            return False
        missing = getattr(self._pylink, "MISSING_DATA", 32768.0)
        return all(
            value is not None
            and math.isfinite(float(value))
            and float(value) != float(missing)
            for value in pair[:2]
        )

    def _eye_pair(self, eye_data):
        if eye_data is None:
            return None
        if self.sample_source == "href":
            return eye_data.getHREF()
        pair = eye_data.getGaze()
        if not self._is_valid_pair(pair):
            return pair
        # EyeLink GAZE uses top-left origin; FineVision uses centered pixels.
        return (
            float(pair[0]) - self.screen_width / 2.0,
            self.screen_height / 2.0 - float(pair[1]),
        )

    def _poll(self):
        if self._closed or self._tracker is None:
            return
        if not self._tracker.isConnected():
            self._gaze_source.update({
                "xl": INVALID_GAZE,
                "yl": INVALID_GAZE,
                "xr": INVALID_GAZE,
                "yr": INVALID_GAZE,
                "left_valid": False,
                "right_valid": False,
                "timestamp": time.perf_counter() - self.session_t0,
            })
            return

        sample = self._tracker.getNewestSample()
        if sample is None:
            return
        sample_time = float(sample.getTime()) / 1000.0
        if sample_time == self._last_sample_time:
            return
        self._last_sample_time = sample_time

        left_eye = None
        right_eye = None
        if sample.isBinocular():
            left_eye = sample.getLeftEye()
            right_eye = sample.getRightEye()
        elif sample.isLeftSample():
            left_eye = sample.getLeftEye()
        elif sample.isRightSample():
            right_eye = sample.getRightEye()

        left_pair = self._eye_pair(left_eye)
        right_pair = self._eye_pair(right_eye)
        left_valid = self._is_valid_pair(left_pair)
        right_valid = self._is_valid_pair(right_pair)
        self._gaze_source.update({
            "xl": float(left_pair[0]) if left_valid else INVALID_GAZE,
            "yl": float(left_pair[1]) if left_valid else INVALID_GAZE,
            "xr": float(right_pair[0]) if right_valid else INVALID_GAZE,
            "yr": float(right_pair[1]) if right_valid else INVALID_GAZE,
            "left_valid": left_valid,
            "right_valid": right_valid,
            "valid": left_valid or right_valid,
            "timestamp": sample_time,
        })

    def get_latest(self):
        self._poll()
        return self._gaze_source.get_latest()

    def get_latest_cal(self):
        self._poll()
        return self._gaze_source.get_latest_cal()

    def get_buffer_snapshot(self, last_n=None):
        self._poll()
        return self._gaze_source.get_buffer_snapshot(last_n)

    def set_calibration_left(self, ox, oy, gx, gy):
        self._gaze_source.set_calibration_left(ox, oy, gx, gy)

    def set_calibration_right(self, ox, oy, gx, gy):
        self._gaze_source.set_calibration_right(ox, oy, gx, gy)

    def get_calibration_left(self):
        return self._gaze_source.get_calibration_left()

    def get_calibration_right(self):
        return self._gaze_source.get_calibration_right()

    @property
    def is_running(self):
        return not self._closed

    def stop(self):
        self.close()

    def send_event(self, message):
        if self._tracker is None or self._closed:
            return
        safe_message = " ".join(str(message).replace("\n", " ").split())
        self._tracker.sendMessage(safe_message)

    def close(self):
        if self._closed:
            return
        self._closed = True
        transfer_error = None
        try:
            if self._tracker is not None:
                try:
                    self._tracker.sendMessage("FINEVISION_SESSION_END")
                except Exception:
                    pass
                if self._recording:
                    self._tracker.stopRecording()
                    self._recording = False
                    self._pylink.pumpDelay(100)
                self._tracker.setOfflineMode()
                self._pylink.msecDelay(500)
                if self._data_file_open:
                    self._tracker.closeDataFile()
                    self._data_file_open = False
                    os.makedirs(
                        os.path.dirname(self.local_edf_path), exist_ok=True
                    )
                    try:
                        self._tracker.receiveDataFile(
                            self.host_edf_name,
                            self.local_edf_path,
                        )
                    except Exception as exc:
                        transfer_error = exc
        finally:
            self._gaze_source.stop()
            if self._tracker is not None:
                self._tracker.close()
        if transfer_error is not None:
            raise RuntimeError(
                "EyeLink EDF remained on the Host but could not be copied to "
                f"{self.local_edf_path}: {transfer_error}"
            ) from transfer_error
        print(f"EyeLink EDF saved to: {self.local_edf_path}")
