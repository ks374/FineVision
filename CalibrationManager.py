# %%
import numpy as np
from psychopy import visual, core, event
from Shared_Memory_Util import SharedGazeData
#from QYEyetracker_Server import EyetrackerServer
from datetime import datetime
from collections import deque
from FineVision_Util import ArduinoController


class CalibrationManager:
    def __init__(self, subject_win, control_win, shared_data,setting_file_path, arduino_controller=None):
        self.win_sub = subject_win
        self.win_ctl = control_win
        self.shared_data = shared_data
        self.setting_file_path = setting_file_path
        self.arduino = arduino_controller


        #This file lives in the drive forever. It will save the default calibration parameteres
        #Updated everytime you do a calibration. 
        self.default_json_path = f"default_setting.json"

        # 获取分辨率比率 (用于把猴子的大坐标缩放到你的小窗口上)
        self.scale_x = control_win.size[0] / subject_win.size[0]
        self.scale_y = control_win.size[1] / subject_win.size[1]

        # 定义 9 点坐标 (假设屏幕分辨率 1920x1080，使用像素单位)
        # 覆盖中心、四角及各边中点
        w, h = subject_win.size[0]//3, subject_win.size[1]//3
        self.targets = [
            (0, 0), (-w, h), (0, h), (w, h),
            (-w, 0), (w, 0), (-w, -h), (0, -h), (w, -h)
        ]
        self.stim_target = visual.Circle(self.win_sub, radius=15, fillColor='white', lineColor='red')
        self.ctl_target = visual.Circle(self.win_ctl, radius=15, fillColor='white', lineColor='red')
        self.ctl_gaze = visual.Circle(self.win_ctl, radius=5, fillColor='yellow', opacity=0.8)
        self.tail_line = visual.ShapeStim(
            self.win_ctl,
            vertices=[(0,0),(0,0)],
            closeShape=False,
            lineWidth=2.0,
            lineColor='yellow',
            opacity=0.6
        )

    def run_calibration(self,default_left_cal,default_right_cal):
        """执行 9 点校准流程"""
        collected_data = [] # 存储结构: (target_x, target_y, raw_xl, raw_yl, raw_xr, raw_yr)

        # 重置共享内存中的校准参数为默认值 (Gain=1, Offset=0)
        self.shared_data.set_calibration_left(default_left_cal['ox'], default_left_cal['oy'], default_left_cal['gx'], default_left_cal['gy'])
        self.shared_data.set_calibration_right(default_right_cal['ox'], default_right_cal['oy'], default_right_cal['gx'], default_right_cal['gy'])

        print("开始校准：请注视屏幕上的红点，按下空格键采集当前点。")

        for i, (tx, ty) in enumerate(self.targets):
            self.stim_target.pos = (tx, ty)
            self.ctl_target.pos = (tx * self.scale_x, ty * self.scale_y)
            
            # --- 关键修改：进入实时渲染循环，而不是死等按键 ---
            # 这一步让你能看到猴子到底在看哪
            event.clearEvents() # 清除旧按键

            #Define the tail for the gaze position
            gaze_trail = deque(maxlen=60)
            smooth_buffer = deque(maxlen=5) # 新增：用于存储最近5个点来计算滑动平均
            
            last_print_time = core.getTime()
            print_interval = 0.5  # 打印间隔，单位：秒（这里设置为0.5秒输出一次）

            while True:
                # 1. 获取最新视线 (此时拿到的是经过 gain=1, offset=0 计算后的“伪原始”数据)
                # 注意：这里我们只画左眼或者双眼中心作为参考
                gaze = self.shared_data.get_latest_cal()

                self.stim_target.draw()
                self.win_sub.flip()

                self.ctl_target.draw()
                
                if gaze['valid']:
                    # 这里直接用 shared_data 算出来的坐标 (因为我们刚刚重置了参数，所以它约等于 raw data)
                    # 如果眼动仪原始坐标和屏幕坐标差异巨大（比如原点在左上角 vs 中心），
                    # 你可能需要在这里手动减去屏幕分辨率的一半来让它出现在视野里
                    # 假设 raw data 也是以屏幕中心为 0 (或者在 Server 端做过基础去中心化)
                    gx_scaled = gaze['x'] * self.scale_x
                    gy_scaled = gaze['y'] * self.scale_y
                    
                    # 将当前坐标加入平滑缓冲区
                    smooth_buffer.append((gx_scaled, gy_scaled))

                    # 计算最近 N (最多5个) 点的平均值
                    # 使用纯 Python 计算，避免每帧调用 numpy 带来额外开销，保证 PsychoPy 渲染帧率
                    gx_scaled = sum(p[0] for p in smooth_buffer) / len(smooth_buffer)
                    gy_scaled = sum(p[1] for p in smooth_buffer) / len(smooth_buffer)

                    #current_time = core.getTime()
                    #if current_time - last_print_time >= print_interval:
                    #    print(f"[点 {i+1}/9] 实时视线 -> 原始 X:{gaze['x']:.1f}, Y:{gaze['y']:.1f} | 缩放后 X:{gx_scaled:.1f}, Y:{gy_scaled:.1f}")
                    #    last_print_time = current_time

                    gaze_trail.append((gx_scaled,gy_scaled))

                    if len(gaze_trail) >= 2:
                        self.tail_line.vertices = list(gaze_trail)
                        self.tail_line.draw()

                    self.ctl_gaze.pos = (gx_scaled,gy_scaled)
                    self.ctl_gaze.draw()
                
                # 2. 绘制目标
                self.win_ctl.flip()

                # 3. 检测按键退出循环
                keys = event.getKeys()
                if 'space' in keys:
                    if self.arduino is not None:
                        # 给予 100 毫秒的水滴奖励（你可以把这个时长做成类属性或函数参数方便调节）
                        self.arduino.reward(duration_ms=100) 
                        print(f" -> 触发液体奖励 (100ms)")
                    break # 跳出 while，进入采集阶段
                elif 'escape' in keys:
                    print("校准中止")
                    return False

            # --- Step B: 采集阶段 ---
            print(f"正在采集点 {i+1}/9...")
            samples = []
            # 采集 10 个样本
            for _ in range(10): 
                # 这里我们特意取 buffer 里最后 1 个点，自己手动存 list
                # 这样比直接取 last_n=20 更稳，因为我们可以控制 core.wait
                gaze = self.shared_data.get_latest()
                
                # 注意：snapshot 返回的是 numpy array，取 [0] 拿到数值
                samples.append([gaze['xl'], gaze['yl'], gaze['xr'], gaze['yr']])
                core.wait(0.01) 
            
            avg_raw = np.mean(samples, axis=0)
            collected_data.append((tx, ty, avg_raw[0], avg_raw[1], avg_raw[2], avg_raw[3]))
            print(f" -> Raw: (xl: {avg_raw[0]:.1f}, yl:{avg_raw[1]:.1f},xr:{avg_raw[2]:.1f},yr:{avg_raw[3]:.1f})")

        # Step C: 计算并应用
        (left_cal,right_cal) = self._calculate_and_apply(np.array(collected_data))
        return (left_cal,right_cal)
    
    def run_quick_calib(self, default_left_cal, default_right_cal, num_points=3):
        """
        确定的3点快速校准，适用于猴子不熟悉任务时快速确定 calibration 参数。
        选取中心、左上、右下三个点，以确保 X 和 Y 轴都有足够的坐标变化来计算 Gain。
        """
        collected_data = []  # (tx, ty, raw_xl, raw_yl, raw_xr, raw_yr)

        # 重置校准参数为默认
        self.shared_data.set_calibration_left(default_left_cal['ox'], default_left_cal['oy'],
                                            default_left_cal['gx'], default_left_cal['gy'])
        self.shared_data.set_calibration_right(default_right_cal['ox'], default_right_cal['oy'],
                                            default_right_cal['gx'], default_right_cal['gy'])

        print("开始快速校准 (3点)：请注视屏幕上的红点，按下空格键采集。")

        # 定义专用的3点坐标：(0,0)中心, (-w, h)左上, (w, -h)右下
        w, h = self.win_sub.size[0]//3, self.win_sub.size[1]//3
        targets_3pt = [(0, 0), (-w, h), (w, -h)]

        for i, (tx, ty) in enumerate(targets_3pt):
            self.stim_target.pos = (tx, ty)
            self.ctl_target.pos = (tx * self.scale_x, ty * self.scale_y)

            event.clearEvents()
            gaze_trail = deque(maxlen=60)
            smooth_buffer = deque(maxlen=5) # 新增：用于存储最近5个点来计算滑动平均

            # 实时渲染循环，直到按下空格
            while True:
                gaze = self.shared_data.get_latest_cal()

                self.stim_target.draw()
                self.win_sub.flip()

                self.ctl_target.draw()

                if gaze['valid']:
                    gx_scaled = gaze['x'] * self.scale_x
                    gy_scaled = gaze['y'] * self.scale_y

                    # 将当前坐标加入平滑缓冲区
                    smooth_buffer.append((gx_scaled, gy_scaled))

                    gaze_trail.append((gx_scaled, gy_scaled))
                    if len(gaze_trail) >= 2:
                        self.tail_line.vertices = list(gaze_trail)
                        self.tail_line.draw()

                    self.ctl_gaze.pos = (gx_scaled, gy_scaled)
                    self.ctl_gaze.draw()

                self.win_ctl.flip()

                keys = event.getKeys()
                if 'space' in keys:
                    break
                elif 'escape' in keys:
                    print("快速校准中止")
                    return (default_left_cal, default_right_cal)

            # 采集阶段
            print(f"正在采集点 {i+1}/3...")
            samples = []
            for _ in range(10):
                gaze = self.shared_data.get_latest()
                samples.append([gaze['xl'], gaze['yl'], gaze['xr'], gaze['yr']])
                core.wait(0.01)

            avg_raw = np.mean(samples, axis=0)
            collected_data.append((tx, ty, avg_raw[0], avg_raw[1], avg_raw[2], avg_raw[3]))
            print(f" -> Raw: (xl:{avg_raw[0]:.1f}, yl:{avg_raw[1]:.1f}, xr:{avg_raw[2]:.1f}, yr:{avg_raw[3]:.1f})")

        # 调用专属的3点计算函数
        if len(collected_data) == 3:
            left_cal, right_cal = self._calculate_and_apply_3pt(np.array(collected_data))
            return (left_cal, right_cal)
        else:
            return (default_left_cal, default_right_cal)
    
    def _calculate_and_apply_3pt(self, data):
        """专门用于3点校准的计算与应用函数"""
        # data 列: 0:tx, 1:ty, 2:xl, 3:yl, 4:xr, 5:yr
        tx, ty = data[:, 0], data[:, 1]
        xl, yl = data[:, 2], data[:, 3]
        xr, yr = data[:, 4], data[:, 5]

        # 对于3个点，使用1阶多项式拟合(最小二乘法)依然是计算独立X/Y轴 Gain 和 Offset 的最佳方式。
        # 如果你未来想引入特定的3点算法（例如仿射变换矩阵），可以直接在这里修改，而不影响9点校准逻辑。
        gxl, oxl = np.polyfit(xl, tx, 1)
        gyl, oyl = np.polyfit(yl, ty, 1)

        gxr, oxr = np.polyfit(xr, tx, 1)
        gyr, oyr = np.polyfit(yr, ty, 1)

        # 推送到共享内存
        self.shared_data.set_calibration_left(oxl, oyl, gxl, gyl)
        self.shared_data.set_calibration_right(oxr, oyr, gxr, gyr)

        left_cal = {'ox': oxl, 'oy': oyl, 'gx': gxl, 'gy': gyl}
        right_cal = {'ox': oxr, 'oy': oyr, 'gx': gxr, 'gy': gyr}

        print("\n--- 3点快速校准完成 ---")
        print(f"左眼参数: Gain (X:{gxl:.3f}, Y:{gyl:.3f}), Offset (X:{oxl:.1f}, Y:{oyl:.1f})")
        print(f"右眼参数: Gain (X:{gxr:.3f}, Y:{gyr:.3f}), Offset (X:{oxr:.1f}, Y:{oyr:.1f})")

        return (left_cal, right_cal)

    def _calculate_and_apply(self, data):
        """利用线性回归计算 Gain 和 Offset 并更新共享内存"""
        # data 列: 0:tx, 1:ty, 2:xl, 3:yl, 4:xr, 5:yr
        tx, ty = data[:, 0], data[:, 1]
        xl, yl = data[:, 2], data[:, 3]
        xr, yr = data[:, 4], data[:, 5]

        # 左眼拟合 (Target = Raw * Gain + Offset)
        # 使用 np.polyfit(x, y, 1) 返回 [Gain, Offset]
        gxl, oxl = np.polyfit(xl, tx, 1)
        gyl, oyl = np.polyfit(yl, ty, 1)

        # 右眼拟合
        gxr, oxr = np.polyfit(xr, tx, 1)
        gyr, oyr = np.polyfit(yr, ty, 1)

        # 推送到共享内存，让后台 Server 立即应用 
        self.shared_data.set_calibration_left(oxl, oyl, gxl, gyl)
        self.shared_data.set_calibration_right(oxr, oyr, gxr, gyr)

        left_cal = {'ox':oxl,'oy':oyl,'gx':gxl,'gy':gyl}
        right_cal = {'ox':oxr,'oy':oyr,'gx':gxr,'gy':gyr}

        print("\n校准完成！参数已同步至后台进程。")
        print(f"左眼参数: Gain xl and yl:({gxl:.3f}, {gyl:.3f}), Offset xl and yl: ({oxl:.1f}, {oyl:.1f})")
        print(f"右眼参数: Gain xl and yl:({gxr:.3f}, {gyr:.3f}), Offset xl and yl: ({oxr:.1f}, {oyr:.1f})")

        return (left_cal,right_cal)


