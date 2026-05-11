# %%
import time
from multiprocessing import Process
import cv2
# 假设你之前的 SDK 封装保存在 QYTracker_util.py 中
from FV_QY_Eyetracker import QYTracker 

class EyetrackerServer(Process):
    """
    眼动仪后台服务进程。
    继承自 multiprocessing.Process，确保它运行在独立的 CPU 核心上。
    """
    def __init__(self, shared_data, dll_path, frame_rate=100):
        super().__init__()
        self.shared_data = shared_data
        self.dll_path = dll_path
        self.frame_rate = frame_rate
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
        
        last_timestamp = -1.0
        
        poll_interval = 1.0/250.0
        last_poll_time = time.perf_counter()

        try:
            while self.shared_data.is_running:
                # 3. 抓取数据 (调用 SDK 获取眼动数据接口 [cite: 14])
                current_time_perf = time.perf_counter()
                if current_time_perf - last_poll_time >= poll_interval:
                    gaze_raw = tracker.get_gaze()
                
                
                    if gaze_raw:
                        # 将 SDK 的格式映射到你的 SharedGazeData 字典格式
                        # 注意：根据 SDK，stEyeCtl_EyeDataEx 包含双眼和原始点数据 [cite: 47-60]
                        #current_frame_time = gaze_raw.get('time_frame',0.0)
                        
                        
                        formatted_data = {
                            'xl': gaze_raw.get('xl', 0.0),
                            'yl': gaze_raw.get('yl', 0.0),
                            'xr': gaze_raw.get('xr', 0.0),
                            'yr': gaze_raw.get('yr', 0.0),
                            #'timestamp': gaze_raw.get('time_frame', 0.0),
                            #'valid': gaze_raw.get('valid', True)
                        }
                        # 4. 写入共享内存 (极速操作)
                        self.shared_data.update(formatted_data)
                        #last_timestamp = current_frame_time
                    last_poll_time = current_time_perf
                else:
                    time.sleep(0)
                
                # --- 新增：4. 抓取并显示图像 ---
                #img = tracker.get_image()
                #if img is not None:
                #    # 显示图像
                #    cv2.imshow("EyeTracker Live Feed", img)
                
                # 必须加入 cv2.waitKey，否则 OpenCV 窗口会未响应死机。
                # 传入 1 意味着只阻塞 1 毫秒处理窗口事件。
                #cv2.waitKey(1)
                
                # 5. 控制采样循环频率
                # 稍微 sleep 一下，防止把 CPU 跑满，给系统留点呼吸空间
                # 0.002s = 500Hz，足以覆盖 100Hz 的眼动仪采样
                #time.sleep(0.002) 

        finally:
            # 6. 安全关闭
            #cv2.destroyAllWindows()
            tracker.stop_tracking()
            tracker.close()
            print("[Server] 后台服务已安全关闭。")


