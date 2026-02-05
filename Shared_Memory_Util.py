# %%
from multiprocessing import Value, Lock, Array
import ctypes
import numpy as np  # 消费者读取 buffer 时通常需要转成 numpy 处理

class SharedGazeData:
    def __init__(self, buffer_size=1000):
        self._size = buffer_size
        self._lock = Lock()
        
        # --- 0. Calibration parameter --- 
        self._offset_xl = Value('d',0.0) ; self._offset_yl = Value('d',0.0)
        self._gain_xl = Value('d',1.0) ; self._gain_yl = Value('d',1.0)
        self._offset_xr = Value('d',0.0) ; self._offset_yr = Value('d',0.0)
        self._gain_xr = Value('d',1.0) ; self._gain_yr = Value('d',1.0)

        # --- 1. 最新数据 (用于实时反馈，如画光标) ---
        # 双眼 X, Y
        self._xl = Value('d', 0.0)
        self._yl = Value('d', 0.0)
        self._xr = Value('d', 0.0)
        self._yr = Value('d', 0.0)
        self._timestamp = Value('d', 0.0)
        self._valid = Value('i', 0)

        # --- 2. Buffer 历史数据 (用于不丢包记录) ---
        # 使用 Array 开辟共享数组
        self._buf_xl = Array('d', buffer_size)
        self._buf_yl = Array('d', buffer_size)
        self._buf_xr = Array('d', buffer_size)
        self._buf_yr = Array('d', buffer_size)
        self._buf_ts = Array('d', buffer_size) # 时间戳 buffer
        
        # 这是一个指针，指向 buffer 中最新写入的位置 (0 ~ 999)
        self._head_ptr = Value('i', -1) 
        
        # 控制位
        self._running = Value('b', True)

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
            self._valid.value = 1 if data.get('valid', True) else 0

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
                'valid': bool(self._valid.value)
            }
    
    def get_latest_cal(self):
        data = self.get_latest()
        xl = data['xl'] * self._gain_xl.value + self._offset_xl.value
        yl = data['yl'] * self._gain_yl.value + self._offset_yl.value
        xr = data['xr'] * self._gain_xr.value + self._offset_xr.value
        yr = data['yr'] * self._gain_yr.value + self._offset_yr.value
        x = (xl+xl)/2
        y = (yl+yr)/2
        return {
            'x': x,
            'y': y,
            'xl': xl ,
            'yl': yl ,
            'xr': xr ,
            'yr': yr ,
            'timestamp': data['timestamp'],
            'valid': bool(data['valid'])
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

    def set_calibration_left(self, ox, oy, gx, gy):
        """更新左眼参数"""
        with self._lock:
            self._offset_xl.value, self._offset_yl.value = ox, oy
            self._gain_xl.value, self._gain_yl.value = gx, gy

    def set_calibration_right(self, ox, oy, gx, gy):
        """更新右眼参数"""
        with self._lock:
            self._offset_xr.value, self._offset_yr.value = ox, oy
            self._gain_xr.value, self._gain_yr.value = gx, gy
    
    def get_calibration_left(self):
        with self._lock:
            return {
                'ox': self._offset_xl.value, 'oy': self._offset_yl.value,
                'gx': self._gain_xl.value, 'gy': self._gain_yl.value
            }
    def get_calibration_right(self):
        with self._lock:
            return {
                'ox': self._offset_xr.value, 'oy': self._offset_yr.value,
                'gx': self._gain_xr.value, 'gy': self._gain_yr.value
            }


    @property
    def is_running(self):
        return self._running.value
    
    def stop(self):
        self._running.value = False


