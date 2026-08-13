# %%
from multiprocessing import Value, Lock, Array
import ctypes
import numpy as np  # 消费者读取 buffer 时通常需要转成 numpy 处理
import os
from Json_manager import read_json


def normalize_calibration(calibration=None):
    """Return a backward-compatible 2-D affine calibration dictionary.

    screen_x = ox + gx * raw_x + gxy * raw_y
    screen_y = oy + gyx * raw_x + gy * raw_y

    Legacy four-value calibrations remain valid because both cross-axis
    coefficients default to zero.
    """
    calibration = calibration or {}
    return {
        "model": str(calibration.get("model", "affine_2d")),
        "ox": float(calibration.get("ox", 0.0)),
        "oy": float(calibration.get("oy", 0.0)),
        "gx": float(calibration.get("gx", 1.0)),
        "gy": float(calibration.get("gy", 1.0)),
        "gxy": float(calibration.get("gxy", 0.0)),
        "gyx": float(calibration.get("gyx", 0.0)),
    }


class SharedGazeData:
    """Hardware-neutral, process-safe storage for the latest gaze sample."""

    def __init__(self, buffer_size=1000, calibration_file="default_setting.json"):
        self._size = buffer_size
        self._lock = Lock()
        self.calibration_file = calibration_file
        
        # --- 0. Calibration parameter --- 
        self._offset_xl = Value('d',0.0) ; self._offset_yl = Value('d',0.0)
        self._gain_xl = Value('d',1.0) ; self._gain_yl = Value('d',1.0)
        self._gain_x_from_yl = Value('d', 0.0)
        self._gain_y_from_xl = Value('d', 0.0)
        self._offset_xr = Value('d',0.0) ; self._offset_yr = Value('d',0.0)
        self._gain_xr = Value('d',1.0) ; self._gain_yr = Value('d',1.0)
        self._gain_x_from_yr = Value('d', 0.0)
        self._gain_y_from_xr = Value('d', 0.0)

        # --- 1. 最新数据 (用于实时反馈，如画光标) ---
        # 双眼 X, Y
        self._xl = Value('d', 0.0)
        self._yl = Value('d', 0.0)
        self._xr = Value('d', 0.0)
        self._yr = Value('d', 0.0)
        # 与任务日志共用同一会话原点的单调时间（秒）。
        self._timestamp = Value('d', 0.0)
        self._valid = Value('i', 0)
        self._left_valid = Value('i', 0)
        self._right_valid = Value('i', 0)

        # --- 2. Buffer 历史数据 (用于不丢包记录) ---
        # 使用 Array 开辟共享数组
        self._buf_xl = Array('d', buffer_size)
        self._buf_yl = Array('d', buffer_size)
        self._buf_xr = Array('d', buffer_size)
        self._buf_yr = Array('d', buffer_size)
        self._buf_ts = Array('d', buffer_size)
        
        # 这是一个指针，指向 buffer 中最新写入的位置 (0 ~ 999)
        self._head_ptr = Value('i', -1) 
        
        # 控制位
        self._running = Value('b', True)

        self._load_default_calibration()
    
    def _load_default_calibration(self):
        fallback_left = {'ox': 0.0, 'oy': 0.0, 'gx': 1.0, 'gy': 1.0}
        fallback_right = {'ox': 0.0, 'oy': 0.0, 'gx': 1.0, 'gy': 1.0}
        
        # 2. 使用你的 Json_manager 一键读取
        settings = read_json(self.calibration_file)
        
        # 安全兜底：如果 read_json 失败返回了 None，给它一个空字典防止后续 .get() 报错
        if not settings:
            settings = {}

        # 3. 提取数据（如果 settings 里没找到对应的 key，就用 fallback）
        left_cal = settings.get("default_left_cal", fallback_left)
        right_cal = settings.get("default_right_cal", fallback_right)

        print("[SharedGazeData] 初始化完成，已通过 Json_manager 加载校准参数。")

        # 4. 将读取到的参数写入共享内存
        # 再次使用 .get() 防范 json 内部字典缺斤少两
        self.set_calibration_left_dict(left_cal)
        self.set_calibration_right_dict(right_cal)

    def update(self, data):
        """
        生产者调用：写入数据 (双眼)
        data 格式: {'xl':..., 'yl':..., 'xr':..., 'yr':..., 'l_area':..., 'r_area':..., 'timestamp':...}
        """
        with self._lock:
            # A. 更新单点数据 (给实时逻辑用)
            self._xl.value = data.get('xl', 0.0)
            self._yl.value = data.get('yl', 0.0)
            self._xr.value = data.get('xr', 0.0)
            self._yr.value = data.get('yr', 0.0)
            self._timestamp.value = data.get('timestamp', 0.0)
            inferred_left_valid = not (
                self._xl.value == -999 or self._yl.value == -999
            )
            inferred_right_valid = not (
                self._xr.value == -999 or self._yr.value == -999
            )
            self._left_valid.value = int(
                bool(data.get('left_valid', inferred_left_valid))
            )
            self._right_valid.value = int(
                bool(data.get('right_valid', inferred_right_valid))
            )
            self._valid.value = int(
                bool(data.get(
                    'valid',
                    self._left_valid.value or self._right_valid.value,
                ))
            )

            # B. 更新 Buffer (给数据保存用)
            # 计算下一个写入位置：(当前位置 + 1) % 总长度
            # 比如 999 的下一个是 0，实现“环形”覆盖
            next_idx = (self._head_ptr.value + 1) % self._size
            
            self._buf_xl[next_idx] = self._xl.value
            self._buf_yl[next_idx] = self._yl.value
            self._buf_xr[next_idx] = self._xr.value
            self._buf_yr[next_idx] = self._yr.value
            self._buf_ts[next_idx] = self._timestamp.value
            
            # 更新指针
            self._head_ptr.value = next_idx

    def get_latest(self):
        """
        消费者调用：只拿最新的一个点 (画光标用)
        """
        with self._lock:
            return {
                'xl': self._xl.value, 'yl': self._yl.value,
                'xr': self._xr.value, 'yr': self._yr.value,
                'timestamp': self._timestamp.value,
                'valid': bool(self._valid.value),
                'left_valid': bool(self._left_valid.value),
                'right_valid': bool(self._right_valid.value),
            }
    
    def get_latest_cal(self):
        data = self.get_latest()
        left_valid = bool(data['left_valid'])
        right_valid = bool(data['right_valid'])
        if left_valid:
            xl = (
                self._offset_xl.value
                + data['xl'] * self._gain_xl.value
                + data['yl'] * self._gain_x_from_yl.value
            )
            yl = (
                self._offset_yl.value
                + data['xl'] * self._gain_y_from_xl.value
                + data['yl'] * self._gain_yl.value
            )
        else:
            xl = yl = -999.0
        if right_valid:
            xr = (
                self._offset_xr.value
                + data['xr'] * self._gain_xr.value
                + data['yr'] * self._gain_x_from_yr.value
            )
            yr = (
                self._offset_yr.value
                + data['xr'] * self._gain_y_from_xr.value
                + data['yr'] * self._gain_yr.value
            )
        else:
            xr = yr = -999.0
        # 双眼平均。原实现误写成 (xl + xl) / 2，导致右眼 X 完全未参与。
        valid_points = []
        if left_valid:
            valid_points.append((xl, yl))
        if right_valid:
            valid_points.append((xr, yr))
        if valid_points:
            x = sum(point[0] for point in valid_points) / len(valid_points)
            y = sum(point[1] for point in valid_points) / len(valid_points)
        else:
            x = y = -999.0
        return {
            'x': x,
            'y': y,
            'xl': xl ,
            'yl': yl ,
            'xr': xr ,
            'yr': yr ,
            'timestamp': data['timestamp'],
            'valid': bool(valid_points),
            'left_valid': left_valid,
            'right_valid': right_valid,
        }

    def get_buffer_snapshot(self, last_n=None):
        """
        消费者调用：拿到 Buffer 数据 (数据分析/保存用)
        参数: last_n (int) -> 获取最后 n 个点。如果不填，获取整个 buffer。
        返回: Numpy Array 格式的数据
        """
        with self._lock:
            # 这是一个极快的内存拷贝操作
            head = self._head_ptr.value
            
            # 获取所有原生数组的拷贝 (防止在转换时被写入覆盖)
            # 注意：这里为了线程安全，必须拷贝。虽然有一点开销，但在 1000 长度下可忽略。
            # 这里使用了切片操作 [:] 来复制整个 list
            xl = np.array(self._buf_xl[:])
            yl = np.array(self._buf_yl[:])
            xr = np.array(self._buf_xr[:])
            yr = np.array(self._buf_yr[:])
            ts = np.array(self._buf_ts[:])
            
        # --- 处理环形逻辑 ---
        # 如果 buffer 是环形的，最新的数据可能在中间。
        # np.roll 可以把数组“转”回来，让最新的数据排在最后
        # shift = -(head + 1) 表示把 head 指针后面的那个（也就是最老的）转到索引 0
        shift_amount = -(head + 1)
        
        xl = np.roll(xl, shift_amount)
        yl = np.roll(yl, shift_amount)
        xr = np.roll(xr, shift_amount)
        yr = np.roll(yr, shift_amount)
        ts = np.roll(ts, shift_amount)

        if last_n is not None and last_n < self._size:
            # 只取最后 N 个
            return xl[-last_n:], yl[-last_n:], xr[-last_n:], yr[-last_n:], ts[-last_n:]
        
        return xl, yl, xr, yr, ts

    def set_calibration_left(self, ox, oy, gx, gy, gxy=0.0, gyx=0.0):
        """更新左眼参数"""
        with self._lock:
            self._offset_xl.value, self._offset_yl.value = ox, oy
            self._gain_xl.value, self._gain_yl.value = gx, gy
            self._gain_x_from_yl.value = gxy
            self._gain_y_from_xl.value = gyx

    def set_calibration_right(self, ox, oy, gx, gy, gxy=0.0, gyx=0.0):
        """更新右眼参数"""
        with self._lock:
            self._offset_xr.value, self._offset_yr.value = ox, oy
            self._gain_xr.value, self._gain_yr.value = gx, gy
            self._gain_x_from_yr.value = gxy
            self._gain_y_from_xr.value = gyx

    def set_calibration_left_dict(self, calibration):
        calibration = normalize_calibration(calibration)
        self.set_calibration_left(
            calibration['ox'], calibration['oy'],
            calibration['gx'], calibration['gy'],
            calibration['gxy'], calibration['gyx'],
        )

    def set_calibration_right_dict(self, calibration):
        calibration = normalize_calibration(calibration)
        self.set_calibration_right(
            calibration['ox'], calibration['oy'],
            calibration['gx'], calibration['gy'],
            calibration['gxy'], calibration['gyx'],
        )
    
    def get_calibration_left(self):
        with self._lock:
            return {
                'model': 'affine_2d',
                'ox': self._offset_xl.value, 'oy': self._offset_yl.value,
                'gx': self._gain_xl.value, 'gy': self._gain_yl.value,
                'gxy': self._gain_x_from_yl.value,
                'gyx': self._gain_y_from_xl.value,
            }
    def get_calibration_right(self):
        with self._lock:
            return {
                'model': 'affine_2d',
                'ox': self._offset_xr.value, 'oy': self._offset_yr.value,
                'gx': self._gain_xr.value, 'gy': self._gain_yr.value,
                'gxy': self._gain_x_from_yr.value,
                'gyx': self._gain_y_from_xr.value,
            }


    @property
    def is_running(self):
        return self._running.value
    
    def stop(self):
        self._running.value = False


