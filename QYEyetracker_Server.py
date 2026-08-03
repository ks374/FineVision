# %%
import time
from multiprocessing import Process
from queue import Full
import cv2
# 假设你之前的 SDK 封装保存在 QYTracker_util.py 中
from FV_QY_Eyetracker import QYTracker 

class EyetrackerServer(Process):
    """
    眼动仪后台服务进程。
    继承自 multiprocessing.Process，确保它运行在独立的 CPU 核心上。
    """
    def __init__(
        self,
        shared_data,
        dll_path,
        frame_rate=100,
        gaze_log_queue=None,
        session_t0=None,
        dropped_samples=None,
    ):
        super().__init__()
        self.shared_data = shared_data
        self.dll_path = dll_path
        self.frame_rate = frame_rate
        self.gaze_log_queue = gaze_log_queue
        # time.perf_counter() is system-wide on Windows. Passing the parent's
        # origin makes eye samples and PsychoPy task events directly comparable.
        self.session_t0 = (
            float(session_t0) if session_t0 is not None else time.perf_counter()
        )
        self.dropped_samples = dropped_samples
        self.daemon = True  # 随主进程一起退出


    def run(self):
        """
        子进程的入口点。
        注意：DLL 的实例化必须在这里（子进程内）进行。
        """
        # 1. 初始化 SDK (调用 SDK API [cite: 10])
        print(f"[Server] 正在尝试连接眼动仪 (频率: {self.frame_rate}Hz)...",flush=True)
        tracker = QYTracker(self.dll_path)
        
        
        if not tracker.connect(self.frame_rate):
            print("[Server] 错误：无法连接到硬件，请检查连接或驱动。",flush=True)
            return

        # 2. 开启算法引擎
        tracker.start_tracking()
        print("[Server] 追踪引擎已启动，正在写入数据...")
        
        poll_interval = 1.0/250.0
        last_poll_time = time.perf_counter()

        is_eye_detected = False

        try:
            while self.shared_data.is_running:
                # 3. 抓取数据 (调用 SDK 获取眼动数据接口 [cite: 14])
                current_time_perf = time.perf_counter()
                if current_time_perf - last_poll_time >= poll_interval:
                    gaze_raw = tracker.get_gaze()
                
                
                    if gaze_raw:
                        sample_time = time.perf_counter() - self.session_t0
                        # 将 SDK 的格式映射到你的 SharedGazeData 字典格式
                        # 注意：根据 SDK，stEyeCtl_EyeDataEx 包含双眼和原始点数据 [cite: 47-60]
                        current_xl = gaze_raw.get('xl', -999.0)
                        current_yl = gaze_raw.get('yl', -999.0)
                        current_xr = gaze_raw.get('xr', -999.0)
                        current_yr = gaze_raw.get('yr', -999.0)
                        left_valid = current_xl != -999 and current_yl != -999
                        right_valid = current_xr != -999 and current_yr != -999
                        
                        formatted_data = {
                            'xl': current_xl,
                            'yl': current_yl,
                            'xr': current_xr,
                            'yr': current_yr,
                            'left_valid': left_valid,
                            'right_valid': right_valid,
                            'valid': left_valid or right_valid,
                            'timestamp': sample_time,
                        }
                        # 4. 写入共享内存 (极速操作)
                        self.shared_data.update(formatted_data)
                        gaze_cal = self.shared_data.get_latest_cal()
                        is_eye_detected = bool(gaze_cal["valid"])

                        # 仅把轻量级数值放入队列；CSV 磁盘写入由另一个进程批量完成。
                        if self.gaze_log_queue is not None:
                            gaze_x = gaze_cal["x"] if is_eye_detected else -999.0
                            gaze_y = gaze_cal["y"] if is_eye_detected else -999.0
                            try:
                                self.gaze_log_queue.put_nowait(
                                    (sample_time, gaze_x, gaze_y)
                                )
                            except Full:
                                # 绝不让磁盘异常反向阻塞眼动采集或任务显示。
                                if self.dropped_samples is not None:
                                    with self.dropped_samples.get_lock():
                                        self.dropped_samples.value += 1
                    last_poll_time = current_time_perf
                else:
                    time.sleep(0)
                
                # --- 新增：4. 抓取并显示图像 ---
                img = tracker.get_image()
                if img is not None:
                    if len(img.shape) == 2 or (len(img.shape) == 3 and img.shape[2] == 1):
                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                        
                    dot_color = (0, 255, 0) if is_eye_detected else (0, 0, 255)
                    h, w = img.shape[:2]
                    center_coordinates = (w - 70, 70)
                    radius = 30      # 圆点大小
                    thickness = -1    # -1 代表填充实心圆

                    cv2.circle(img, center_coordinates, radius, dot_color, thickness)

                    # 显示图像
                    cv2.imshow("EyeTracker Live Feed", img)
                
                # 必须加入 cv2.waitKey，否则 OpenCV 窗口会未响应死机。
                # 传入 1 意味着只阻塞 1 毫秒处理窗口事件。
                cv2.waitKey(1)
                
                # 5. 控制采样循环频率
                # 稍微 sleep 一下，防止把 CPU 跑满，给系统留点呼吸空间
                # 0.002s = 500Hz，足以覆盖 100Hz 的眼动仪采样
                #time.sleep(0.002) 

        finally:
            # 6. 安全关闭
            cv2.destroyAllWindows()
            tracker.stop_tracking()
            tracker.close()
            print("[Server] 后台服务已安全关闭。")


