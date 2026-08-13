# %%
import numpy as np
import math
from psychopy import visual, core, event
from Shared_Memory_Util import SharedGazeData, normalize_calibration
#from QYEyetracker_Server import EyetrackerServer
from datetime import datetime
from collections import deque
from FineVision_Util import ArduinoController
from GazeTrackerRenderer import GazeTrackerRenderer


CALIBRATION_FIXATION_DURATION_S = 0.5
CALIBRATION_TAIL_SAMPLE_DURATION_S = 0.1
CALIBRATION_SAMPLE_POLL_INTERVAL_S = 0.001
MIN_CALIBRATION_TAIL_SAMPLES = 3


class CalibrationManager:
    def __init__(
        self,
        subject_win,
        control_win,
        shared_data,
        setting_file_path,
        arduino_controller=None,
        is_simulating=0,
        tracker_backend=None,
        add_quadrant_points=False,
        random_seed=None,
        target_specs=None,
        fixation_point_radius_px=15.0,
        fixation_window_radius_px=200.0,
        background_color="black",
        fixation_duration_s=CALIBRATION_FIXATION_DURATION_S,
        max_wait_time_s=5.0,
        iti_s=3.0,
        reward_ms=300,
    ):
        self.win_sub = subject_win
        self.win_ctl = control_win
        self.shared_data = shared_data
        self.setting_file_path = setting_file_path
        self.arduino = arduino_controller
        self.is_simulating = is_simulating
        self.tracker_backend = tracker_backend
        self.add_quadrant_points = bool(add_quadrant_points)
        self.fixation_point_radius_px = float(fixation_point_radius_px)
        self.fixation_window_radius_px = float(fixation_window_radius_px)
        if self.fixation_point_radius_px <= 0:
            raise ValueError("Fixation point radius must be positive.")
        if self.fixation_window_radius_px <= 0:
            raise ValueError("Fixation window radius must be positive.")
        self.background_color = background_color
        self.fixation_duration_s = float(fixation_duration_s)
        self.max_wait_time_s = float(max_wait_time_s)
        self.iti_s = float(iti_s)
        self.reward_ms = int(reward_ms)
        if self.fixation_duration_s < CALIBRATION_TAIL_SAMPLE_DURATION_S:
            raise ValueError(
                "Fixation duration must be at least the 100-ms sampling tail."
            )
        if self.max_wait_time_s <= 0 or self.iti_s < 0:
            raise ValueError(
                "Maximum wait must be positive and ITI non-negative."
            )
        if self.reward_ms < 0:
            raise ValueError("Reward duration cannot be negative.")
        if random_seed is None:
            random_seed = int(np.random.SeedSequence().entropy) % (2 ** 32)
        self.random_seed = int(random_seed) % (2 ** 32)
        self._last_collection_details = None
        self.calibration_report = {
            "status": "initialized",
            "model": "affine_2d",
            "formula": {
                "x": "ox + gx*raw_x + gxy*raw_y",
                "y": "oy + gyx*raw_x + gy*raw_y",
            },
            "random_seed": self.random_seed,
            "points": [],
        }


        #This file lives in the drive forever. It will save the default calibration parameteres
        #Updated everytime you do a calibration. 
        self.default_json_path = f"default_setting.json"

        # 获取分辨率比率 (用于把猴子的大坐标缩放到你的小窗口上)
        self.scale_x = control_win.size[0] / subject_win.size[0]
        self.scale_y = control_win.size[1] / subject_win.size[1]
        self.win_sub.color = self.background_color
        self.win_ctl.color = self.background_color

        self.gaze_renderer = GazeTrackerRenderer(self.win_ctl,self.shared_data,self.scale_x,self.scale_y,self.is_simulating)

        # 定义 9 点坐标 (假设屏幕分辨率 1920x1080，使用像素单位)
        # 覆盖中心、四角及各边中点
        if target_specs is None:
            w, h = subject_win.size[0]//6, subject_win.size[1]//6
            base_targets = [
                (0, 0), (-w, h), (0, h), (w, h),
                (-w, 0), (w, 0), (-w, -h), (0, -h), (w, -h)
            ]
            self.target_specs = [
                {"target": target, "region": "base_9"}
                for target in base_targets
            ]
            if self.add_quadrant_points:
                self.target_specs.extend(
                    {"target": target, "region": "quadrant_4_extra"}
                    for target in self._generate_quadrant_targets(
                        subject_win.size, self.random_seed
                    )
                )
        else:
            self.target_specs = []
            for spec in target_specs:
                normalized = dict(spec)
                normalized["target"] = tuple(
                    float(value) for value in spec["target"]
                )
                normalized["region"] = str(
                    spec.get("region", "base_9")
                )
                if "target_deg" in spec:
                    normalized["target_deg"] = [
                        float(value) for value in spec["target_deg"]
                    ]
                self.target_specs.append(normalized)
        self.targets = [spec["target"] for spec in self.target_specs]
        if len(self.targets) < 3:
            raise ValueError("Calibration requires at least three targets.")
        if len(self.targets) >= 5:
            self.quick_targets = [
                self.targets[0], self.targets[4], self.targets[2]
            ]
        else:
            self.quick_targets = self.targets[:3]
        self.calibration_report["targets"] = [
            {
                "index": index,
                "target_px": [float(target[0]), float(target[1])],
                "target_deg": spec.get("target_deg"),
                "region": spec["region"],
            }
            for index, (target, spec) in enumerate(
                zip(self.targets, self.target_specs), start=1
            )
        ]
        self.stim_target = visual.Circle(
            self.win_sub,
            radius=self.fixation_point_radius_px,
            fillColor='green',
            lineColor='green',
        )
        self.ctl_target = visual.Circle(
            self.win_ctl,
            radius=self.fixation_point_radius_px * self.scale_x,
            fillColor='green',
            lineColor='green',
        )
        #self.ctl_gaze = visual.Circle(self.win_ctl, radius=5, fillColor='yellow', opacity=0.8)
        self.tail_line = visual.ShapeStim(
            self.win_ctl,
            vertices=[(0,0),(0,0)],
            closeShape=False,
            lineWidth=2.0,
            lineColor='yellow',
            opacity=0.6
        )

    @staticmethod
    def _generate_quadrant_targets(screen_size, random_seed):
        """Generate four reproducible, stratified targets in quadrant IV.

        The ranges cover the current 0..9 deg horizontal and -9..0 deg
        saccade workspace while retaining a margin from the display edges.
        Stratification prevents four random draws from clustering together.
        """
        half_width = float(screen_size[0]) / 2.0
        half_height = float(screen_size[1]) / 2.0
        x_edges = (0.06 * half_width, 0.21 * half_width, 0.36 * half_width)
        y_edges = (0.06 * half_height, 0.34 * half_height, 0.62 * half_height)
        rng = np.random.default_rng(int(random_seed))
        targets = []
        for y_bin in range(2):
            for x_bin in range(2):
                x = rng.uniform(x_edges[x_bin], x_edges[x_bin + 1])
                y_magnitude = rng.uniform(
                    y_edges[y_bin], y_edges[y_bin + 1]
                )
                targets.append((int(round(x)), -int(round(y_magnitude))))
        rng.shuffle(targets)
        return targets

    def _send_tracker_event(self, message):
        if getattr(self, "tracker_backend", None) is not None:
            self.tracker_backend.send_event(message)

    def _send_tracker_event_on_flip(self, message):
        if getattr(self, "tracker_backend", None) is not None:
            self.tracker_backend.send_event_on_flip(self.win_sub, message)

    def _set_calibration_dict(self, side, calibration):
        dictionary_setter = getattr(
            self.shared_data, f"set_calibration_{side}_dict", None
        )
        if dictionary_setter is not None:
            dictionary_setter(calibration)
            return
        calibration = normalize_calibration(calibration)
        setter = getattr(self.shared_data, f"set_calibration_{side}")
        try:
            setter(
                calibration["ox"], calibration["oy"],
                calibration["gx"], calibration["gy"],
                calibration["gxy"], calibration["gyx"],
            )
        except TypeError:
            # Compatibility with simple test doubles and legacy stores.
            setter(
                calibration["ox"], calibration["oy"],
                calibration["gx"], calibration["gy"],
            )

    @staticmethod
    def _eye_is_valid(gaze, side):
        """Return whether one eye has a usable x/y pair."""
        validity_key = f"{side}_valid"
        if validity_key in gaze:
            return bool(gaze[validity_key])
        x_key = "xl" if side == "left" else "xr"
        y_key = "yl" if side == "left" else "yr"
        try:
            x_value = float(gaze[x_key])
            y_value = float(gaze[y_key])
        except (KeyError, TypeError, ValueError):
            return False
        return (
            np.isfinite(x_value)
            and np.isfinite(y_value)
            and x_value != -999.0
            and y_value != -999.0
        )

    @classmethod
    def _calibration_sample(cls, gaze):
        """Keep a valid monocular sample and mark the missing eye as NaN."""
        left_valid = cls._eye_is_valid(gaze, "left")
        right_valid = cls._eye_is_valid(gaze, "right")
        if not (left_valid or right_valid):
            return None
        return [
            float(gaze["xl"]) if left_valid else np.nan,
            float(gaze["yl"]) if left_valid else np.nan,
            float(gaze["xr"]) if right_valid else np.nan,
            float(gaze["yr"]) if right_valid else np.nan,
        ]

    @staticmethod
    def _average_calibration_samples(samples):
        sample_array = np.asarray(samples, dtype=float)
        averages = []
        for column in sample_array.T:
            finite = column[np.isfinite(column)]
            averages.append(float(np.mean(finite)) if finite.size else np.nan)
        return np.asarray(averages, dtype=float)

    def _collect_fixation_tail(
        self,
        target_x,
        target_y,
        fixation_radius,
        *,
        require_in_window=True,
        point_index=None,
        point_total=None,
        attempt=None,
    ):
        """Collect unique raw samples over the final 100 ms of fixation."""
        samples = []
        sample_records = []
        last_timestamp = None
        self._last_collection_details = None
        sampling_clock = core.Clock()
        point_label = int(point_index or 0)
        attempt_label = int(attempt or 0)
        self._send_tracker_event(
            f"CAL_SAMPLE_START POINT {point_label} ATTEMPT {attempt_label} "
            f"TARGET {float(target_x):.1f} {float(target_y):.1f}"
        )

        def abort_collection(reason):
            self._send_tracker_event(
                f"CAL_SAMPLE_ABORT POINT {point_label} "
                f"ATTEMPT {attempt_label} REASON {reason}"
            )
            self._last_collection_details = {
                "status": "aborted",
                "reason": reason,
                "samples": sample_records,
            }
            return None

        while sampling_clock.getTime() < CALIBRATION_TAIL_SAMPLE_DURATION_S:
            calibrated_gaze = self.shared_data.get_latest_cal()
            if not calibrated_gaze["valid"]:
                return abort_collection("INVALID_GAZE")
            if require_in_window:
                distance = math.hypot(
                    calibrated_gaze["x"] - target_x,
                    calibrated_gaze["y"] - target_y,
                )
                if distance > fixation_radius:
                    return abort_collection("OUTSIDE_WINDOW")

            raw_gaze = self.shared_data.get_latest()
            sample = self._calibration_sample(raw_gaze)
            if sample is None:
                return abort_collection("INVALID_RAW")

            timestamp = raw_gaze.get("timestamp")
            if timestamp is None or timestamp != last_timestamp:
                samples.append(sample)
                sample_records.append({
                    "tracker_timestamp_s": (
                        float(timestamp) if timestamp is not None else None
                    ),
                    "xl": None if not np.isfinite(sample[0]) else sample[0],
                    "yl": None if not np.isfinite(sample[1]) else sample[1],
                    "xr": None if not np.isfinite(sample[2]) else sample[2],
                    "yr": None if not np.isfinite(sample[3]) else sample[3],
                })
                last_timestamp = timestamp

            remaining = (
                CALIBRATION_TAIL_SAMPLE_DURATION_S
                - sampling_clock.getTime()
            )
            if remaining > 0:
                core.wait(min(CALIBRATION_SAMPLE_POLL_INTERVAL_S, remaining))

        if len(samples) < MIN_CALIBRATION_TAIL_SAMPLES:
            return abort_collection("TOO_FEW_SAMPLES")
        first_timestamp = sample_records[0]["tracker_timestamp_s"]
        last_timestamp = sample_records[-1]["tracker_timestamp_s"]
        self._last_collection_details = {
            "status": "accepted",
            "sample_count": len(samples),
            "tracker_timestamp_start_s": first_timestamp,
            "tracker_timestamp_end_s": last_timestamp,
            "duration_requested_s": CALIBRATION_TAIL_SAMPLE_DURATION_S,
            "samples": sample_records,
        }
        self._send_tracker_event(
            f"CAL_SAMPLE_END POINT {point_label} ATTEMPT {attempt_label} "
            f"N {len(samples)} TS_START {first_timestamp} TS_END {last_timestamp}"
        )
        return samples

    @staticmethod
    def _fit_axis(raw_values, targets, fallback_gain, fallback_offset):
        mask = np.isfinite(raw_values) & np.isfinite(targets)
        usable_raw = raw_values[mask]
        usable_targets = targets[mask]
        if usable_raw.size < 2 or np.unique(usable_raw).size < 2:
            return float(fallback_gain), float(fallback_offset)
        gain, offset = np.polyfit(usable_raw, usable_targets, 1)
        return float(gain), float(offset)

    @staticmethod
    def _fit_affine(raw_x, raw_y, target_x, target_y, fallback):
        """Fit one complete 2-D affine mapping for a single eye."""
        fallback = normalize_calibration(fallback)
        raw_x = np.asarray(raw_x, dtype=float)
        raw_y = np.asarray(raw_y, dtype=float)
        target_x = np.asarray(target_x, dtype=float)
        target_y = np.asarray(target_y, dtype=float)
        mask = (
            np.isfinite(raw_x)
            & np.isfinite(raw_y)
            & np.isfinite(target_x)
            & np.isfinite(target_y)
        )
        design = np.column_stack((
            np.ones(np.count_nonzero(mask)), raw_x[mask], raw_y[mask]
        ))
        if design.shape[0] < 3 or np.linalg.matrix_rank(design) < 3:
            return fallback
        coefficients_x = np.linalg.lstsq(
            design, target_x[mask], rcond=None
        )[0]
        coefficients_y = np.linalg.lstsq(
            design, target_y[mask], rcond=None
        )[0]
        return {
            "model": "affine_2d",
            "ox": float(coefficients_x[0]),
            "oy": float(coefficients_y[0]),
            "gx": float(coefficients_x[1]),
            "gy": float(coefficients_y[2]),
            "gxy": float(coefficients_x[2]),
            "gyx": float(coefficients_y[1]),
        }

    @staticmethod
    def _predict_affine(calibration, raw_x, raw_y):
        calibration = normalize_calibration(calibration)
        raw_x = np.asarray(raw_x, dtype=float)
        raw_y = np.asarray(raw_y, dtype=float)
        return np.column_stack((
            calibration["ox"]
            + calibration["gx"] * raw_x
            + calibration["gxy"] * raw_y,
            calibration["oy"]
            + calibration["gyx"] * raw_x
            + calibration["gy"] * raw_y,
        ))

    @staticmethod
    def _error_metrics(predicted, targets):
        predicted = np.asarray(predicted, dtype=float)
        targets = np.asarray(targets, dtype=float)
        finite = np.all(np.isfinite(predicted), axis=1)
        finite &= np.all(np.isfinite(targets), axis=1)
        if not np.any(finite):
            return None
        residual = predicted[finite] - targets[finite]
        distance = np.linalg.norm(residual, axis=1)
        return {
            "point_count": int(distance.size),
            "rmse_2d_px": float(np.sqrt(np.mean(distance ** 2))),
            "mean_error_2d_px": float(np.mean(distance)),
            "max_error_2d_px": float(np.max(distance)),
        }

    def run_calibration(self,default_left_cal,default_right_cal):
        """执行 9 点校准流程"""
        collected_data = [] # 存储结构: (target_x, target_y, raw_xl, raw_yl, raw_xr, raw_yr)
        self.calibration_report["status"] = "running"
        self.calibration_report["points"] = []

        # 重置共享内存中的校准参数为默认值 (Gain=1, Offset=0)
        self._set_calibration_dict("left", default_left_cal)
        self._set_calibration_dict("right", default_right_cal)

        print("开始校准：请注视屏幕上的红点，按下空格键采集当前点。")

        auto_fix_radius = self.fixation_window_radius_px
        auto_fix_time = self.fixation_duration_s
        max_wait_time = self.max_wait_time_s
        iti_time = self.iti_s
        
        fix_windows_9pt = []
        for (vx, vy) in self.targets:
            circle = visual.Circle(
                self.win_ctl,
                radius=auto_fix_radius * self.scale_x,
                pos=(vx * self.scale_x, vy * self.scale_y),
                lineColor='grey',
                lineWidth=1,
                fillColor=None,
                opacity=0.3  # 非活动状态设为较透明
            )
            fix_windows_9pt.append(circle)

        point_total = len(self.targets)
        for i, (tx, ty) in enumerate(self.targets):
            target_spec = self.target_specs[i]
            self.stim_target.pos = (tx, ty)
            self.ctl_target.pos = (tx * self.scale_x, ty * self.scale_y)

            point_acquired = False
            attempt = 0

            while not point_acquired:
                attempt += 1
                event.clearEvents() # 清除旧按键
                
                core.wait(iti_time)

                trial_clock = core.Clock()
                fix_clock = core.Clock()
                is_fixating = False
                status = "running"
                samples = None
                target_onset_pending = True
                
                fix_windows_9pt[i].lineColor = 'red'
            
                while True:
                    self.stim_target.draw()
                    if target_onset_pending:
                        self._send_tracker_event_on_flip(
                            f"CAL_POINT_ONSET POINT {i + 1} TOTAL {point_total} "
                            f"ATTEMPT {attempt} TARGET {float(tx):.1f} "
                            f"{float(ty):.1f} REGION {target_spec['region']}"
                        )
                        target_onset_pending = False
                    self.win_sub.flip()

                    self.ctl_target.draw()
                    
                    if not is_fixating and trial_clock.getTime() > max_wait_time:
                        status = "nofix"
                        break

                    gaze = self.gaze_renderer.update_and_draw()
                
                    for j, fw in enumerate(fix_windows_9pt):
                        if j==i:
                            fw.draw()

                    self.win_ctl.flip()
                
                    if gaze['valid']:
                        dist = math.hypot(gaze['x'] - tx, gaze['y'] - ty)

                        if dist <= auto_fix_radius:
                            if not is_fixating:
                                is_fixating = True
                                fix_clock.reset()
                                fix_windows_9pt[i].lineColor = 'green'
                            elif fix_clock.getTime() >= (
                                auto_fix_time
                                - CALIBRATION_TAIL_SAMPLE_DURATION_S
                            ):
                                samples = self._collect_fixation_tail(
                                    tx,
                                    ty,
                                    auto_fix_radius,
                                    point_index=i + 1,
                                    point_total=point_total,
                                    attempt=attempt,
                                )
                                if samples is None:
                                    status = "break"
                                    is_fixating = False
                                else:
                                    print(
                                        " -> 自动判定成功 "
                                        f"(持续注视 {auto_fix_time:.1f}s；"
                                        "末尾100ms用于采样)"
                                    )
                                    status = "success"
                                break
                        else:
                            if is_fixating:
                                status = "break"
                                is_fixating = False
                                break
                    elif is_fixating:
                        status = "break"
                        is_fixating = False
                        break

                    
                

                # 3. 检测按键退出循环
                    keys = event.getKeys()
                    if 'space' in keys:
                        samples = self._collect_fixation_tail(
                            tx,
                            ty,
                            auto_fix_radius,
                            require_in_window=False,
                            point_index=i + 1,
                            point_total=point_total,
                            attempt=attempt,
                        )
                        status = "success" if samples is not None else "break"
                        break
                    elif 'escape' in keys:
                        self.calibration_report["status"] = "aborted"
                        self._send_tracker_event(
                            f"CAL_POINT_ABORT POINT {i + 1} ATTEMPT {attempt}"
                        )
                        print("Calibration aborted")
                        return None
                
                # 4. 任务状态判定
                if status == "success":
                    point_acquired = True
                    print(f" -> Calibration point {i + 1}/{point_total} accepted.")
                    print(
                        f" -> Final 100 ms contained {len(samples)} "
                        "unique tracker samples."
                    )
                    if self.arduino is not None:
                        # 给予 100 毫秒的水滴奖励（你可以把这个时长做成类属性或函数参数方便调节）
                        self.arduino.reward(duration_ms=self.reward_ms)
                        print(f" -> 触发液体奖励 (500ms)")
                    else:
                        print(" -> [警告] arduino 对象为 None，水泵触发被跳过！请检查主程序中的 CalibrationManager 实例化。")

                    avg_raw = self._average_calibration_samples(samples)
                    collected_data.append((tx, ty, avg_raw[0], avg_raw[1], avg_raw[2], avg_raw[3]))
                    raw_mean = {
                        "xl": None if not np.isfinite(avg_raw[0]) else float(avg_raw[0]),
                        "yl": None if not np.isfinite(avg_raw[1]) else float(avg_raw[1]),
                        "xr": None if not np.isfinite(avg_raw[2]) else float(avg_raw[2]),
                        "yr": None if not np.isfinite(avg_raw[3]) else float(avg_raw[3]),
                    }
                    self.calibration_report["points"].append({
                        "index": i + 1,
                        "target_px": [float(tx), float(ty)],
                        "target_deg": target_spec.get("target_deg"),
                        "region": target_spec["region"],
                        "accepted_attempt": attempt,
                        "raw_mean": raw_mean,
                        "collection": self._last_collection_details,
                    })
                    self._send_tracker_event(
                        f"CAL_POINT_ACCEPTED POINT {i + 1} ATTEMPT {attempt} "
                        f"RAW_R {raw_mean['xr']} {raw_mean['yr']}"
                    )
                    print(f" -> Raw: (xl: {avg_raw[0]:.1f}, yl:{avg_raw[1]:.1f},xr:{avg_raw[2]:.1f},yr:{avg_raw[3]:.1f})")
                    self._send_tracker_event_on_flip(
                        f"CAL_POINT_OFF POINT {i + 1} ATTEMPT {attempt} "
                        "RESULT ACCEPTED"
                    )
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    
                    core.wait(0.8)
                elif status in ["nofix", "break"]:
                    self._send_tracker_event(
                        f"CAL_POINT_RETRY POINT {i + 1} ATTEMPT {attempt} "
                        f"REASON {status.upper()}"
                    )
                    reason = "未看屏幕 (NoFix)" if status == "nofix" else "注视中断 (Break)"
                    print(f" -> {reason}，执行 ITI ({iti_time}s) 后重试该点...")
                    
                    # 黑屏惩罚 ITI
                    self.win_sub.color = self.background_color
                    self.win_ctl.color = self.background_color
                    self._send_tracker_event_on_flip(
                        f"CAL_POINT_OFF POINT {i + 1} ATTEMPT {attempt} "
                        "RESULT RETRY"
                    )
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    #core.wait(iti_time)
                    # 惩罚结束后，while 循环继续，重试当前的第 i 个点

        # Step C: 计算并应用
        (left_cal,right_cal) = self._calculate_and_apply(np.array(collected_data))
        self.calibration_report["status"] = "complete"
        return (left_cal,right_cal)
    
    def run_quick_calib(self, default_left_cal, default_right_cal, num_points=3):
        """
        确定的3点快速校准，包含失败重试、ITI机制、数据有效性校验，以及【实时手动调参】功能。
        """
        collected_data = []  # (tx, ty, raw_xl, raw_yl, raw_xr, raw_yr)

        # 重置校准参数为默认
        self._set_calibration_dict("left", default_left_cal)
        self._set_calibration_dict("right", default_right_cal)

        print("\n=== 开始快速校准 (3点) ===")
        print("请注视屏幕红点。如果猴子只是一瞥，您可以使用以下快捷键实时挪动视线光标：")
        print(" [方向键 ↑ ↓ ← →] : 微调 X/Y 轴的 Offset (平移光标)")
        print(" [W / S]          : 微调 Y 轴的 Gain (纵向拉伸)")
        print(" [A / D]          : 微调 X 轴的 Gain (横向拉伸)")
        print(" [空格键]         : 强制判定成功并进入采集\n")

        auto_fix_radius = self.fixation_window_radius_px
        auto_fix_time = self.fixation_duration_s
        max_wait_time = self.max_wait_time_s
        iti_time = self.iti_s
        
        # 定义专用的3点坐标：(0,0)中心, (-w, h)左上, (w, -h)右下
        targets_3pt = self.quick_targets
        
        fix_windows_3pt = []
        for (vx, vy) in targets_3pt:
            circle = visual.Circle(
                self.win_ctl,
                radius=auto_fix_radius * self.scale_x,
                pos=(vx * self.scale_x, vy * self.scale_y),
                lineColor='grey',
                lineWidth=1,
                fillColor=None,
                opacity=0.3
            )
            fix_windows_3pt.append(circle)
            
            
        for i, (tx, ty) in enumerate(targets_3pt):
            self.stim_target.pos = (tx, ty)
            self.ctl_target.pos = (tx * self.scale_x, ty * self.scale_y)

            point_acquired = False

            while not point_acquired:
                event.clearEvents()
                
                core.wait(iti_time)

                trial_clock = core.Clock()
                fix_clock = core.Clock()
                is_fixating = False
                status = "running"
                samples = None
                
                fix_windows_3pt[i].lineColor = 'red'

                while True:
                    self.stim_target.draw()
                    self.win_sub.flip()
                    self.ctl_target.draw()
                    
                    if not is_fixating and trial_clock.getTime() > max_wait_time:
                        status = "nofix"
                        break

                    gaze = self.gaze_renderer.update_and_draw()
                    
                    
                    for j, fw in enumerate(fix_windows_3pt):
                        if j == i: fw.draw()

                    self.win_ctl.flip()

                    if gaze['valid']:
                        dist = math.hypot(gaze['x'] - tx, gaze['y'] - ty)

                        if dist <= auto_fix_radius:
                            if not is_fixating:
                                is_fixating = True
                                fix_clock.reset()
                                fix_windows_3pt[i].lineColor = 'green'
                            elif fix_clock.getTime() >= (
                                auto_fix_time
                                - CALIBRATION_TAIL_SAMPLE_DURATION_S
                            ):
                                samples = self._collect_fixation_tail(
                                    tx,
                                    ty,
                                    auto_fix_radius,
                                )
                                status = (
                                    "success" if samples is not None else "break"
                                )
                                break
                        else:
                            if is_fixating:
                                status = "break"
                                is_fixating = False
                                break
                    elif is_fixating:
                        status = "break"
                        is_fixating = False
                        break

                    

                    keys = event.getKeys()
                    if keys:
                        trial_clock.reset()
                        l_cal = self.shared_data.get_calibration_left()
                        r_cal = self.shared_data.get_calibration_right()

                        changed = False
                        offset_step = 5.0
                        gain_step = 2.0

                        # 键盘事件判断
                        if 'up' in keys:
                            l_cal['oy'] -= offset_step; r_cal['oy'] -= offset_step; changed = True
                        elif 'down' in keys:
                            l_cal['oy'] += offset_step; r_cal['oy'] += offset_step; changed = True
                        elif 'left' in keys:
                            l_cal['ox'] -= offset_step; r_cal['ox'] -= offset_step; changed = True
                        elif 'right' in keys:
                            l_cal['ox'] += offset_step; r_cal['ox'] += offset_step; changed = True
                        elif 'w' in keys:
                            l_cal['gy'] += gain_step; r_cal['gy'] += gain_step; changed = True
                        elif 's' in keys:
                            l_cal['gy'] -= gain_step; r_cal['gy'] -= gain_step; changed = True
                        elif 'd' in keys:
                            l_cal['gx'] += gain_step; r_cal['gx'] += gain_step; changed = True
                        elif 'a' in keys:
                            l_cal['gx'] -= gain_step; r_cal['gx'] -= gain_step; changed = True
                        # 如果修改了参数，立刻推送到后台 Server
                        if changed:
                            self._set_calibration_dict("left", l_cal)
                            self._set_calibration_dict("right", r_cal)
                            print(f"[调参] Offset(X:{l_cal['ox']:.1f}, Y:{l_cal['oy']:.1f}) | Gain(X:{l_cal['gx']:.2f}, Y:{l_cal['gy']:.2f})")

                        if 'space' in keys:
                            samples = self._collect_fixation_tail(
                                tx,
                                ty,
                                auto_fix_radius,
                                require_in_window=False,
                            )
                            status = (
                                "success" if samples is not None else "break"
                            )
                            break
                        elif 'escape' in keys:
                            print("快速校准中止")
                            return None
                if status == "success":
                    print(f" -> 点 {i+1}/3 成功锁定，准备采集数据...")
                elif status in ["nofix", "break"]:
                    reason = "未看屏幕 (NoFix)" if status == "nofix" else "注视中断 (Break)"
                    print(f" -> {reason}，执行 ITI ({iti_time}s) 后重试该点...")
                    self.win_sub.color = self.background_color
                    self.win_ctl.color = self.background_color
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    #core.wait(iti_time)
                    continue

                point_acquired = True
                print(
                    f" -> 点 {i+1}/3 的末尾100ms共采集 "
                    f"{len(samples)} 个唯一时间戳样本。"
                )

                if self.arduino is not None:
                    # 给予 100 毫秒的水滴奖励（你可以把这个时长做成类属性或函数参数方便调节）
                    self.arduino.reward(duration_ms=self.reward_ms)
                    print(f" -> 触发液体奖励 (500ms)")
                else:
                    print(" -> [警告] arduino 对象为 None，水泵触发被跳过！请检查主程序中的 CalibrationManager 实例化。")
                    
                avg_raw = self._average_calibration_samples(samples)
                collected_data.append((tx, ty, avg_raw[0], avg_raw[1], avg_raw[2], avg_raw[3]))
                print(f" -> Raw: (xl:{avg_raw[0]:.1f}, yl:{avg_raw[1]:.1f}, xr:{avg_raw[2]:.1f}, yr:{avg_raw[3]:.1f})")
                
                self.win_sub.flip()
                self.win_ctl.flip()
                
                core.wait(0.8)  

        # 调用专属的3点计算函数
        if len(collected_data) == 3:
            left_cal, right_cal = self._calculate_and_apply_3pt(np.array(collected_data))
            return (left_cal, right_cal)
        else:
            return (default_left_cal, default_right_cal)

    def _build_eye_quality(
        self, data, raw_x_column, raw_y_column, full_model, fallback
    ):
        """Quantify full fit and held-out quadrant-IV improvement."""
        target = data[:, :2]
        raw_x = data[:, raw_x_column]
        raw_y = data[:, raw_y_column]
        full_prediction = self._predict_affine(full_model, raw_x, raw_y)
        result = {
            "all_points_training": self._error_metrics(
                full_prediction, target
            ),
            "comparison_note": (
                "baseline_9_on_extra_q4 predicts the four added points "
                "without fitting them; affine_all_leave_one_out_q4 predicts "
                "each added point after excluding that point."
            ),
        }
        q4_indices = [
            index for index, spec in enumerate(self.target_specs)
            if spec["region"] == "quadrant_4_extra"
        ]
        if not q4_indices:
            return result

        base_count = min(9, len(data))
        baseline_model = self._fit_affine(
            raw_x[:base_count], raw_y[:base_count],
            target[:base_count, 0], target[:base_count, 1], fallback,
        )
        baseline_prediction = self._predict_affine(
            baseline_model, raw_x[q4_indices], raw_y[q4_indices]
        )
        baseline_metrics = self._error_metrics(
            baseline_prediction, target[q4_indices]
        )

        leave_one_out_prediction = []
        leave_one_out_target = []
        for held_out in q4_indices:
            keep = np.ones(len(data), dtype=bool)
            keep[held_out] = False
            loo_model = self._fit_affine(
                raw_x[keep], raw_y[keep],
                target[keep, 0], target[keep, 1], fallback,
            )
            prediction = self._predict_affine(
                loo_model, [raw_x[held_out]], [raw_y[held_out]]
            )[0]
            leave_one_out_prediction.append(prediction)
            leave_one_out_target.append(target[held_out])
        loo_metrics = self._error_metrics(
            leave_one_out_prediction, leave_one_out_target
        )
        q4_training_metrics = self._error_metrics(
            full_prediction[q4_indices], target[q4_indices]
        )
        improvement = None
        if (
            baseline_metrics is not None
            and loo_metrics is not None
            and baseline_metrics["rmse_2d_px"] > 0
        ):
            improvement = 100.0 * (
                baseline_metrics["rmse_2d_px"]
                - loo_metrics["rmse_2d_px"]
            ) / baseline_metrics["rmse_2d_px"]
        result.update({
            "baseline_9_model": baseline_model,
            "baseline_9_on_extra_q4": baseline_metrics,
            "affine_all_training_on_extra_q4": q4_training_metrics,
            "affine_all_leave_one_out_q4": loo_metrics,
            "estimated_q4_rmse_improvement_percent": improvement,
        })
        return result

    def _attach_point_residuals(self, data, left_cal, right_cal):
        target = data[:, :2]
        for side, raw_columns, calibration in (
            ("left", (2, 3), left_cal),
            ("right", (4, 5), right_cal),
        ):
            prediction = self._predict_affine(
                calibration, data[:, raw_columns[0]], data[:, raw_columns[1]]
            )
            for index, point_record in enumerate(
                self.calibration_report["points"]
            ):
                if not np.all(np.isfinite(prediction[index])):
                    point_record[f"{side}_fit"] = None
                    continue
                residual = prediction[index] - target[index]
                point_record[f"{side}_fit"] = {
                    "predicted_px": [
                        float(prediction[index, 0]),
                        float(prediction[index, 1]),
                    ],
                    "residual_px": [
                        float(residual[0]), float(residual[1])
                    ],
                    "error_2d_px": float(np.linalg.norm(residual)),
                }
    
    def _calculate_and_apply_3pt(self, data):
        """Fit the same affine model from three non-collinear quick points."""
        tx, ty = data[:, 0], data[:, 1]
        xl, yl = data[:, 2], data[:, 3]
        xr, yr = data[:, 4], data[:, 5]
        left_fallback = self.shared_data.get_calibration_left()
        right_fallback = self.shared_data.get_calibration_right()

        left_cal = self._fit_affine(
            xl, yl, tx, ty, left_fallback
        )
        right_cal = self._fit_affine(
            xr, yr, tx, ty, right_fallback
        )
        self._set_calibration_dict("left", left_cal)
        self._set_calibration_dict("right", right_cal)

        print("\n--- 3点快速校准完成 ---")
        print(f"Left affine calibration: {left_cal}")
        print(f"Right affine calibration: {right_cal}")

        return (left_cal, right_cal)

    def _calculate_and_apply(self, data):
        """Fit and apply a complete 2-D affine model for each eye."""
        tx, ty = data[:, 0], data[:, 1]
        xl, yl = data[:, 2], data[:, 3]
        xr, yr = data[:, 4], data[:, 5]
        left_fallback = self.shared_data.get_calibration_left()
        right_fallback = self.shared_data.get_calibration_right()

        left_cal = self._fit_affine(
            xl, yl, tx, ty, left_fallback
        )
        right_cal = self._fit_affine(
            xr, yr, tx, ty, right_fallback
        )
        self._set_calibration_dict("left", left_cal)
        self._set_calibration_dict("right", right_cal)

        if hasattr(self, "calibration_report"):
            self.calibration_report["calibration"] = {
                "left": left_cal,
                "right": right_cal,
            }
            self.calibration_report["quality"] = {
                "left": self._build_eye_quality(
                    data, 2, 3, left_cal, left_fallback
                ),
                "right": self._build_eye_quality(
                    data, 4, 5, right_cal, right_fallback
                ),
            }
            self._attach_point_residuals(data, left_cal, right_cal)

        print("\n校准完成！参数已同步至后台进程。")
        print(f"Left affine calibration: {left_cal}")
        print(f"Right affine calibration: {right_cal}")
        self._send_tracker_event(
            "CAL_MODEL RIGHT AFFINE_2D "
            f"OX {right_cal['ox']:.8g} OY {right_cal['oy']:.8g} "
            f"GX {right_cal['gx']:.8g} GY {right_cal['gy']:.8g} "
            f"GXY {right_cal['gxy']:.8g} GYX {right_cal['gyx']:.8g}"
        )

        return (left_cal,right_cal)


