# %%
import numpy as np
import math
from psychopy import visual, core, event
from Shared_Memory_Util import SharedGazeData
#from QYEyetracker_Server import EyetrackerServer
from datetime import datetime
from collections import deque
from FineVision_Util import ArduinoController
from GazeTrackerRenderer import GazeTrackerRenderer


class CalibrationManager:
    def __init__(self, subject_win, control_win, shared_data,setting_file_path, arduino_controller=None, is_simulating = 0):
        self.win_sub = subject_win
        self.win_ctl = control_win
        self.shared_data = shared_data
        self.setting_file_path = setting_file_path
        self.arduino = arduino_controller
        self.is_simulating = is_simulating


        #This file lives in the drive forever. It will save the default calibration parameteres
        #Updated everytime you do a calibration. 
        self.default_json_path = f"default_setting.json"

        # 获取分辨率比率 (用于把猴子的大坐标缩放到你的小窗口上)
        self.scale_x = control_win.size[0] / subject_win.size[0]
        self.scale_y = control_win.size[1] / subject_win.size[1]

        self.gaze_renderer = GazeTrackerRenderer(self.win_ctl,self.shared_data,self.scale_x,self.scale_y,self.is_simulating)

        # 定义 9 点坐标 (假设屏幕分辨率 1920x1080，使用像素单位)
        # 覆盖中心、四角及各边中点
        w, h = subject_win.size[0]//6, subject_win.size[1]//6
        self.targets = [
            (0, 0), (-w, h), (0, h), (w, h),
            (-w, 0), (w, 0), (-w, -h), (0, -h), (w, -h)
        ]
        self.stim_target = visual.Circle(self.win_sub, radius=30, fillColor='red', lineColor='green')
        self.ctl_target = visual.Circle(self.win_ctl, radius=30*self.scale_x, fillColor='red', lineColor='green')
        #self.ctl_gaze = visual.Circle(self.win_ctl, radius=5, fillColor='yellow', opacity=0.8)
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

        auto_fix_radius = 200
        auto_fix_time = 0.15
        max_wait_time = 5
        iti_time = 3
        
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

        for i, (tx, ty) in enumerate(self.targets):
            self.stim_target.pos = (tx, ty)
            self.ctl_target.pos = (tx * self.scale_x, ty * self.scale_y)

            point_acquired = False

            while not point_acquired:
                
                event.clearEvents() # 清除旧按键
                
                core.wait(iti_time)

                trial_clock = core.Clock()
                fix_clock = core.Clock()
                is_fixating = False
                status = "running"
            
                while True:
                    self.stim_target.draw()
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
                            elif fix_clock.getTime() >= auto_fix_time:
                                print(f" -> 自动判定成功 (持续注视 {auto_fix_time}s)")
                                status = "success"
                                break
                        else:
                            if is_fixating:
                                status = "break"
                                is_fixating = False
                                break

                    
                

                # 3. 检测按键退出循环
                    keys = event.getKeys()
                    if 'space' in keys:
                        status = "success"
                        break # 跳出 while，进入采集阶段
                    elif 'escape' in keys:
                        print("校准中止")
                        return (default_left_cal, default_right_cal)
                
                # 4. 任务状态判定
                if status == "success":
                    point_acquired = True
                    print(f" -> 点 {i+1}/9 成功锁定。")
                    print(f"正在采集点 {i+1}/9...")
                    samples = []
                    collection_failed = False
                    # 采集 3 个样本
                    for _ in range(3): 
                        # 这里我们特意取 buffer 里最后 1 个点，自己手动存 list
                        # 这样比直接取 last_n=20 更稳，因为我们可以控制 core.wait
                        gaze = self.shared_data.get_latest()
                        if gaze['xl'] == -999.0 or gaze['xl'] == -999:
                            collection_failed = True
                            break
                        
                        # 注意：snapshot 返回的是 numpy array，取 [0] 拿到数值
                        samples.append([gaze['xl'], gaze['yl'], gaze['xr'], gaze['yr']])
                        core.wait(0.01) 
                    if collection_failed:
                        print(" -> [采集失败] 采样瞬间丢失眼睛(眨眼或移开视线)。执行 ITI 后重试该点...")
                        point_acquired = False
                        self.win_sub.color = 'black'
                        self.win_ctl.color = 'black'
                        self.win_sub.flip()
                        self.win_ctl.flip()
                        #core.wait(iti_time)
                        continue # 回到 while not point_acquired 的开头，重试该点
                    if self.arduino is not None:
                        # 给予 100 毫秒的水滴奖励（你可以把这个时长做成类属性或函数参数方便调节）
                        self.arduino.reward(duration_ms=500) 
                        print(f" -> 触发液体奖励 (500ms)")
                    else:
                        print(" -> [警告] arduino 对象为 None，水泵触发被跳过！请检查主程序中的 CalibrationManager 实例化。")

                    avg_raw = np.mean(samples, axis=0)
                    collected_data.append((tx, ty, avg_raw[0], avg_raw[1], avg_raw[2], avg_raw[3]))
                    print(f" -> Raw: (xl: {avg_raw[0]:.1f}, yl:{avg_raw[1]:.1f},xr:{avg_raw[2]:.1f},yr:{avg_raw[3]:.1f})")
                    
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    
                    core.wait(0.8)
                elif status in ["nofix", "break"]:
                    reason = "未看屏幕 (NoFix)" if status == "nofix" else "注视中断 (Break)"
                    print(f" -> {reason}，执行 ITI ({iti_time}s) 后重试该点...")
                    
                    # 黑屏惩罚 ITI
                    self.win_sub.color = 'black'
                    self.win_ctl.color = 'black'
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    #core.wait(iti_time)
                    # 惩罚结束后，while 循环继续，重试当前的第 i 个点

        # Step C: 计算并应用
        (left_cal,right_cal) = self._calculate_and_apply(np.array(collected_data))
        return (left_cal,right_cal)
    
    def run_quick_calib(self, default_left_cal, default_right_cal, num_points=3):
        """
        确定的3点快速校准，包含失败重试、ITI机制、数据有效性校验，以及【实时手动调参】功能。
        """
        collected_data = []  # (tx, ty, raw_xl, raw_yl, raw_xr, raw_yr)

        # 重置校准参数为默认
        self.shared_data.set_calibration_left(default_left_cal['ox'], default_left_cal['oy'],
                                            default_left_cal['gx'], default_left_cal['gy'])
        self.shared_data.set_calibration_right(default_right_cal['ox'], default_right_cal['oy'],
                                            default_right_cal['gx'], default_right_cal['gy'])

        print("\n=== 开始快速校准 (3点) ===")
        print("请注视屏幕红点。如果猴子只是一瞥，您可以使用以下快捷键实时挪动视线光标：")
        print(" [方向键 ↑ ↓ ← →] : 微调 X/Y 轴的 Offset (平移光标)")
        print(" [W / S]          : 微调 Y 轴的 Gain (纵向拉伸)")
        print(" [A / D]          : 微调 X 轴的 Gain (横向拉伸)")
        print(" [空格键]         : 强制判定成功并进入采集\n")

        auto_fix_radius = 200
        auto_fix_time = 0.2
        max_wait_time = 5.0  # 给长一点的时间方便手动调参
        iti_time = 3.0
        
        # 定义专用的3点坐标：(0,0)中心, (-w, h)左上, (w, -h)右下
        w, h = self.win_sub.size[0]//3, self.win_sub.size[1]//3
        targets_3pt = [(0, 0), (-w, 0), (0, h)]
        
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
                            elif fix_clock.getTime() >= auto_fix_time:
                                status = "success"
                                break
                        else:
                            if is_fixating:
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
                            self.shared_data.set_calibration_left(l_cal['ox'], l_cal['oy'], l_cal['gx'], l_cal['gy'])
                            self.shared_data.set_calibration_right(r_cal['ox'], r_cal['oy'], r_cal['gx'], r_cal['gy'])
                            print(f"[调参] Offset(X:{l_cal['ox']:.1f}, Y:{l_cal['oy']:.1f}) | Gain(X:{l_cal['gx']:.2f}, Y:{l_cal['gy']:.2f})")

                        if 'space' in keys:
                            status = "success"
                            break
                        elif 'escape' in keys:
                            print("快速校准中止")
                            return (default_left_cal, default_right_cal)
                if status == "success":
                    print(f" -> 点 {i+1}/3 成功锁定，准备采集数据...")
                elif status in ["nofix", "break"]:
                    reason = "未看屏幕 (NoFix)" if status == "nofix" else "注视中断 (Break)"
                    print(f" -> {reason}，执行 ITI ({iti_time}s) 后重试该点...")
                    self.win_sub.color = 'black'
                    self.win_ctl.color = 'black'
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    #core.wait(iti_time)
                    continue

                # 采集阶段
                print(f"正在采集点 {i+1}/3...")
                samples = []
                collection_failed = False
                for _ in range(3):
                    gaze = self.shared_data.get_latest()
                    if gaze['xl'] == -999.0 or gaze['xl'] == -999:
                        collection_failed = True
                        break 
                    samples.append([gaze['xl'], gaze['yl'], gaze['xr'], gaze['yr']])
                    core.wait(0.01)
                if collection_failed:
                    print(" -> [采集失败] 采样瞬间丢失眼睛(眨眼或移开视线)。执行 ITI 后重试该点...")
                    self.win_sub.color = 'black'
                    self.win_ctl.color = 'black'
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    #core.wait(iti_time)
                    continue

                point_acquired = True

                if self.arduino is not None:
                    # 给予 100 毫秒的水滴奖励（你可以把这个时长做成类属性或函数参数方便调节）
                    self.arduino.reward(duration_ms=500) 
                    print(f" -> 触发液体奖励 (500ms)")
                else:
                    print(" -> [警告] arduino 对象为 None，水泵触发被跳过！请检查主程序中的 CalibrationManager 实例化。")
                    
                avg_raw = np.mean(samples, axis=0)
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


