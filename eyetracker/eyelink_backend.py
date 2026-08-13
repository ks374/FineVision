import math
import os
import time

from .base import TrackerBackend


INVALID_GAZE = -999.0


class EyeLinkBackend(TrackerBackend):
    """Direct PyLink backend with EDF recording and custom calibration input.

    The active FineVision configuration reads right-eye HREF coordinates and
    maps them into task-screen pixels with FineVision's custom calibration.
    EyeLink GAZE screen coordinates remain available as an optional source,
    but are not used by the default EyeLink task configuration.
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
        active_eye="right",
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
        self.active_eye = str(active_eye).lower()
        if self.active_eye != "right":
            raise ValueError("EyeLink active_eye must be 'right'.")

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
        self._graphics_open = False
        self._calibration_graphics = None
        try:
            self._connect_and_record()
        except Exception:
            self._close_after_startup_error()
            raise

    @property
    def gaze_source(self):
        return self

    @property
    def supports_recalibration(self):
        return True

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
            self._close_calibration_graphics()
            try:
                self._tracker.close()
            except Exception:
                pass

    def _close_calibration_graphics(self):
        """Close PyLink graphics only after all Host transfers are done."""
        if not self._graphics_open or self._pylink is None:
            return
        try:
            self._pylink.closeGraphics()
        except Exception:
            pass
        finally:
            self._graphics_open = False
            self._calibration_graphics = None

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
        if self.sample_source == "gaze":
            # EyeLink GAZE is already calibrated by the Host and _eye_pair()
            # has already converted it from top-left screen pixels to
            # FineVision's centered coordinate system.  Applying the custom
            # HREF affine calibration here would calibrate the sample twice.
            gaze = self._gaze_source.get_latest()
        else:
            gaze = self._gaze_source.get_latest_cal()

        # The EyeLink calibration export supplied for this task contains only
        # right-eye coefficients.  Online task decisions must therefore use
        # that calibrated eye exclusively, rather than averaging it with the
        # uncalibrated left eye or falling back to left-eye samples.
        if not gaze["right_valid"]:
            gaze.update({"x": INVALID_GAZE, "y": INVALID_GAZE, "valid": False})
            return gaze
        gaze.update({"x": gaze["xr"], "y": gaze["yr"], "valid": True})
        return gaze

    def get_buffer_snapshot(self, last_n=None):
        self._poll()
        return self._gaze_source.get_buffer_snapshot(last_n)

    def set_calibration_left(self, ox, oy, gx, gy, gxy=0.0, gyx=0.0):
        self._gaze_source.set_calibration_left(ox, oy, gx, gy, gxy, gyx)

    def set_calibration_right(self, ox, oy, gx, gy, gxy=0.0, gyx=0.0):
        self._gaze_source.set_calibration_right(ox, oy, gx, gy, gxy, gyx)

    def set_calibration_left_dict(self, calibration):
        self._gaze_source.set_calibration_left_dict(calibration)

    def set_calibration_right_dict(self, calibration):
        self._gaze_source.set_calibration_right_dict(calibration)

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

    def recalibrate(
        self,
        window,
        *,
        calibration_type="HV5",
        max_eccentricity_deg=12.0,
        viewing_distance_cm=60.0,
        monitor_width_cm=54.0,
        monitor_height_cm=30.0,
        fixation_point_radius_deg=0.2,
        background_color=(0.0, 0.0, 0.0),
        arduino=None,
        reward_mode="advance",
        reward_ms=300,
        pacing_ms=1200,
    ):
        """Run EyeLink setup/calibration and resume the same open EDF.

        Recording is stopped before ``doTrackerSetup`` and restarted after it
        returns.  The Host data file remains open throughout, so samples from
        before and after recalibration stay in one EDF.
        """
        if self._closed or self._tracker is None:
            raise RuntimeError("EyeLink is not available for recalibration.")
        calibration_type = str(calibration_type).upper()
        if calibration_type not in {"HV5", "HV9"}:
            raise ValueError("EyeLink calibration_type must be HV5 or HV9.")

        from EyeLink_Native_Calibration import (
            _axis_calibration_extent,
            _build_rewarding_graphics,
            _load_official_graphics_class,
            _task_visual_angle_to_pixels,
        )

        was_recording = self._recording
        setup_error = None
        self.send_event(
            "FINEVISION_RECALIBRATION_REQUESTED "
            f"TYPE {calibration_type}"
        )
        try:
            if was_recording:
                self._tracker.stopRecording()
                self._recording = False
                self._pylink.pumpDelay(100)
            self._tracker.setOfflineMode()

            x_area = _axis_calibration_extent(
                max_eccentricity_deg,
                viewing_distance_cm,
                monitor_width_cm,
                self.screen_width,
            )
            y_area = _axis_calibration_extent(
                max_eccentricity_deg,
                viewing_distance_cm,
                monitor_height_cm,
                self.screen_height,
            )
            target_radius_px = _task_visual_angle_to_pixels(
                fixation_point_radius_deg,
                viewing_distance_cm,
                monitor_width_cm,
                self.screen_width,
            )
            target_size_px = max(2, int(round(2.0 * target_radius_px)))

            self._tracker.sendCommand(
                f"calibration_type = {calibration_type}"
            )
            self._tracker.sendCommand(
                "calibration_area_proportion "
                f"{x_area['proportion']:.6f} {y_area['proportion']:.6f}"
            )
            self._tracker.sendCommand(
                "validation_area_proportion "
                f"{x_area['proportion']:.6f} {y_area['proportion']:.6f}"
            )
            if reward_mode == "manual":
                self._tracker.sendCommand("enable_automatic_calibration = NO")
            else:
                self._tracker.sendCommand("enable_automatic_calibration = YES")
                self._tracker.sendCommand(
                    f"automatic_calibration_pacing = {int(pacing_ms)}"
                )

            official_graphics, _ = _load_official_graphics_class()
            rewarding_graphics = _build_rewarding_graphics(
                official_graphics,
                self._pylink,
                auto_exit_after_success=True,
                auto_start_calibration=True,
            )
            graphics = rewarding_graphics(
                self._tracker,
                window,
                arduino,
                str(reward_mode),
                int(reward_ms),
            )
            graphics.setCalibrationColors("white", background_color)
            graphics.setTargetType("circle")
            graphics.setTargetSize(target_size_px)
            graphics._calibInst.text = (
                "Calibration starts automatically on the subject screen\n"
                "C: restart calibration    V: validation\n"
                "Successful calibration returns automatically\n"
                "ESC: return without completing calibration"
            )
            self._pylink.openGraphicsEx(graphics)
            # Keep a strong reference and leave the PyLink callbacks
            # registered until EDF transfer has finished. receiveDataFile()
            # may still poll get_input_key(); closing graphics here replaces
            # its adapter with None and can abort task shutdown.
            self._calibration_graphics = graphics
            self._graphics_open = True
            self._tracker.sendMessage(
                "FINEVISION_RECALIBRATION_START "
                f"TYPE {calibration_type} "
                f"MAX_ECC_DEG {float(max_eccentricity_deg):.3f}"
            )
            self._tracker.doTrackerSetup()
            calibration_message = ""
            try:
                calibration_message = self._tracker.getCalibrationMessage()
            except Exception:
                pass
            safe_result = "_".join(str(calibration_message).split())
            self._tracker.sendMessage(
                "FINEVISION_RECALIBRATION_SETUP_END "
                f"RESULT {safe_result or 'UNKNOWN'}"
            )
        except BaseException as exc:
            setup_error = exc
        finally:
            try:
                self._tracker.setOfflineMode()
                if was_recording:
                    result = self._tracker.startRecording(1, 1, 1, 1)
                    if result not in (None, 0):
                        raise RuntimeError(
                            f"EyeLink startRecording failed after calibration: "
                            f"{result}"
                        )
                    self._recording = True
                    self._pylink.pumpDelay(100)
                    self._tracker.sendMessage(
                        "FINEVISION_RECALIBRATION_RECORDING_RESUMED"
                    )
                    self._last_sample_time = None
            except BaseException as resume_error:
                if setup_error is None:
                    setup_error = resume_error

        if setup_error is not None:
            raise setup_error
        return True

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
            self._close_calibration_graphics()
            self._gaze_source.stop()
            if self._tracker is not None:
                self._tracker.close()
        if transfer_error is not None:
            raise RuntimeError(
                "EyeLink EDF remained on the Host but could not be copied to "
                f"{self.local_edf_path}: {transfer_error}"
            ) from transfer_error
        print(f"EyeLink EDF saved to: {self.local_edf_path}")
