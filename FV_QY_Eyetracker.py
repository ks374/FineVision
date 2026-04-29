# %%
import ctypes
from ctypes import wintypes
import time
import os
import cv2
import numpy as np

# %%
class StEyeCtlEyeDataEx(ctypes.Structure):
    _fields_ = [
        ("xm", ctypes.c_double),                # 原始眼动点X [cite: 49]
        ("ym", ctypes.c_double),                # 原始眼动点Y [cite: 50]
        ("xl", ctypes.c_double),                # 原始左眼动点X [cite: 51]
        ("yl", ctypes.c_double),                # 原始左眼动点Y [cite: 52]
        ("xr", ctypes.c_double),                # 原始右眼动点X [cite: 53]
        ("yr", ctypes.c_double),                # 原始右眼动点Y [cite: 54]
        ("l_area", ctypes.c_double),            # 左眼瞳孔面积 [cite: 55]
        ("r_area", ctypes.c_double),            # 右眼瞳孔面积 [cite: 56]
        ("i32LeftEyePosX", ctypes.c_int),       # 左眼相对显示器的位置X [cite: 57]
        ("i32LeftEyePosY", ctypes.c_int),       # 左眼相对显示器的位置Y [cite: 58]
        ("i32RightEyePosX", ctypes.c_int),      # 右眼相对显示器的位置X [cite: 59]
        ("i32RightEyePosY", ctypes.c_int),      # 右眼相对显示器的位置Y [cite: 60]
        ("nCalibrationStatus", ctypes.c_int),   # 校准状态 [cite: 61]
        ("returnValue", ctypes.c_int),          # 返回值 [cite: 62]
        ("frame_time", ctypes.c_double),        # 帧时间 [cite: 63]
    ]

# %%
class QYTracker:
    '''
    Example: tk = QYTracker(dll_path="C:\my\lib\position\EyeControl_SDK.dll")
    '''
    def __init__(self, dll_filename="EyeControl_SDK.dll",sdk_folder = "QYSDK"):
        # 加载 DLL 
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.sdk_dir_abs = os.path.join(current_dir, sdk_folder)
            self.sdk_dir_abs = os.path.join(current_dir, sdk_folder)
            self.dll_path_abs = os.path.join(self.sdk_dir_abs, dll_filename)
            print(f"[QYTracker] SDK 位置: {self.dll_path_abs}", flush=True)


            self.sdk = ctypes.WinDLL(self.dll_path_abs)
            #print(self.sdk.EyeControl_Init,flush=True)
            self._setup_prototypes()
            self.is_tracking = False
            print("Successfully loaded QY EyeTracker SDK.")
            
            self.part_width = 640
            self.part_height = 400
            self.part_size = self.part_width * self.part_height
            
            self._part_array = (ctypes.c_ubyte * self.part_size)()
            self._full_array = (ctypes.c_ubyte * (1920 * 1200))()
            self._left_array = (ctypes.c_ubyte * (360 * 180))()
            self._right_array = (ctypes.c_ubyte * (360 * 180))()
            
        except Exception as e:
            print(f"Failed to load SDK: {e}")

    def _setup_prototypes(self):
        # 设置函数输入输出类型
        self.sdk.EyeControl_Init.restype = wintypes.BOOL
        self.sdk.EyeControl_Init.argtypes = [ctypes.c_int]

        self.sdk.EyeControl_GetEyeDataEx.restype = ctypes.c_int
        self.sdk.EyeControl_GetEyeDataEx.argtypes = [ctypes.POINTER(StEyeCtlEyeDataEx)]

        self.sdk.EyeControl_StartRecognition.restype = None
        self.sdk.EyeControl_StopRecognition.restype = None
        self.sdk.EyeControl_Close.restype = None
        
        PBYTE = ctypes.POINTER(ctypes.c_ubyte)
        PINT = ctypes.POINTER(ctypes.c_int)

        self.sdk.EyeControl_GetImageBuffer.restype = wintypes.BOOL
        self.sdk.EyeControl_GetImageBuffer.argtypes = [
            ctypes.POINTER(PBYTE),  # pBuf
            ctypes.POINTER(PBYTE),  # partBuf
            PINT,                   # nBufWidth
            PINT,                   # nBufHeight
            ctypes.POINTER(PBYTE),  # leftBuf
            ctypes.POINTER(PBYTE),  # rightBuf
            PINT,                   # eyeBufWidth
            PINT                    # eyeBufHeight
        ]
        
    def get_image(self):
        """
        拉取最新一帧眼动仪画面，将其转换为 OpenCV 可用的 numpy 数组。
        为保证性能，这里只返回 640x400 的缩略图。
        """
        PBYTE = ctypes.POINTER(ctypes.c_ubyte)
        
        # 将我们预分配的内存转为指针
        pBuf = ctypes.cast(self._full_array, PBYTE)
        partBuf = ctypes.cast(self._part_array, PBYTE)
        leftBuf = ctypes.cast(self._left_array, PBYTE)
        rightBuf = ctypes.cast(self._right_array, PBYTE)

        nBufWidth = ctypes.c_int(0)
        nBufHeight = ctypes.c_int(0)
        eyeBufWidth = ctypes.c_int(0)
        eyeBufHeight = ctypes.c_int(0)

        # 调用底层接口
        ret = self.sdk.EyeControl_GetImageBuffer(
            ctypes.byref(pBuf), ctypes.byref(partBuf),
            ctypes.byref(nBufWidth), ctypes.byref(nBufHeight),
            ctypes.byref(leftBuf), ctypes.byref(rightBuf),
            ctypes.byref(eyeBufWidth), ctypes.byref(eyeBufHeight)
        )

        if ret:
            # 使用 numpy 的 ctypeslib 将 C 内存直接映射为 Python 数组，做到零拷贝(Zero-copy)，速度极快
            img_array = np.ctypeslib.as_array(partBuf, shape=(self.part_size,))
            
            # 将 1D 数组重塑为 2D 图像矩阵 (高度, 宽度)
            img_reshaped = img_array.reshape((self.part_height, self.part_width))
            
            # 如果是红外相机，这通常是 8-bit 单通道灰度图。可以直接用 cv2 显示。
            return img_reshaped
            
        return None

    def connect(self, frame_rate=100):
        # 初始化并开始识别
        
        if self.sdk.EyeControl_Init(frame_rate):
            print("Call Eyetracker StartRecg Function",flush=True)
            self.sdk.EyeControl_StartRecognition()
            print("Finish Eyetracker StartRecg Function",flush=True)
            self.is_tracking = True
            print("EyeTracker connected and recognition started.")
            return True
        return False
    
    def start_tracking(self):
        """
        开始识别：通常会触发一次全图搜索和参数自适应。
        建议在猴子坐好、每个Block开始前、或跟丢后调用。
        """
        self.sdk.EyeControl_StartRecognition()
        self.is_tracking = True
        # 给算法一点时间来稳定曝光和锁定瞳孔（比如 200-500ms）
        time.sleep(0.2) 
        print("Tracking Algorithm Started.")

    def stop_tracking(self):
        """
        停止识别：释放 CPU 资源，重置算法状态。
        """
        self.sdk.EyeControl_StopRecognition() # [cite: 32]
        self.is_tracking = False
        print("Tracking Algorithm Stopped.")

    def get_gaze(self):
        # 获取最新眼动数据 
        data = StEyeCtlEyeDataEx()
        result = self.sdk.EyeControl_GetEyeDataEx(ctypes.byref(data))
        
        if result == 1: # 成功获取 [cite: 17]
            return {
                "xl": data.xl,
                "yl": data.yl,
                "xr": data.xr,
                "yr": data.yr,
                "timestamp": data.frame_time
            }
        return None

    def close(self):
        # 停止并关闭 [cite: 33, 41]
        self.sdk.EyeControl_StopRecognition()
        self.sdk.EyeControl_Close()
        print("EyeTracker closed.")



# %%
