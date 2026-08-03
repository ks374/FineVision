import math
import os
from datetime import datetime
from psychopy import visual, core, event, gui
from multiprocessing import Process
from collections import deque
import traceback
import pandas as pd

# 确保这些自定义模块在你的同一目录下
from eyetracker import create_tracker_runtime
from Json_manager import update_json, read_json
from FineVision_Notebook import FineVision_Notebook
from GazeTrackerRenderer import GazeTrackerRenderer
from FineVision_Util import ArduinoController

# ==========================================
# 2. 核心任务类 (ManualMappingTask)
# ==========================================
class ManualMappingTask:
    def __init__(self, win_sub, win_ctl, shared_data, task_manager,is_simulating):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.task_manager = task_manager
        self.is_simulating = is_simulating

        self.arduino = ArduinoController()
        
        # 计算双屏缩放比例
        self.scale_x = win_ctl.size[0] / win_sub.size[0]
        self.scale_y = win_ctl.size[1] / win_sub.size[1]

        self.gaze_renderer = GazeTrackerRenderer(self.win_ctl,self.shared_data,self.scale_x,self.scale_y,self.is_simulating)

        # --- 视觉刺激初始化 ---
        # 猴子屏幕：中心注视点
        self.stim_fix_point = visual.Circle(win_sub, radius=15, fillColor='green', lineColor='green', pos=(0,0))
        
        # 控制台屏幕：包含注视点、实时眼动光标、隐形的“注视窗口”边界
        self.ctl_fix_point = visual.Circle(win_ctl, radius=15 * self.scale_x, fillColor='green', pos=(0,0))
        self.ctl_gaze_cursor = visual.Circle(win_ctl, radius=6, fillColor='yellow', opacity=0.8)
        self.ctl_fix_window = visual.Circle(win_ctl, radius=100, fillColor=None, lineColor='red', lineWidth=2, pos=(0,0))

        #self.tail_line = visual.ShapeStim(
        #    self.win_ctl,
        #    vertices=[(0,0),(0,0)],
        #    closeShape=False,
        #    lineWidth=2.0,
        #    lineColor='yellow',
        #    opacity=0.6
        #)
        
        self.mouse = event.Mouse(visible=True, win=self.win_ctl)
        self.sub_bar = visual.Rect(self.win_sub, fillColor='white', lineColor=None)
        self.ctl_bar = visual.Rect(self.win_ctl, fillColor='white', lineColor=None, opacity=0.7)
        self.bar_clock = core.Clock()
        
        self.trial_clock = core.Clock()
        self.behavior_log = []
        self.session_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    def update_params(self):
        """从参数管理器中拉取最新的参数并更新类的属性"""
        p = self.task_manager.exp_params
        
        self.wait_time = p.get('Wait Time (s)', 2.0)
        self.stim_duration = p.get('Stim Duration (s)', 1.0)
        self.reward_len = p.get('Reward Length (s)', 0.2)
        self.iti_time = p.get('ITI (s)', 1.0)
        self.timeout_time = p.get('Timeout (s)', 2.0)
        self.fix_radius = p.get('Fix Window Radius (pix)', 100)
        
        # 同步更新控制台的绿色判定圈大小
        self.ctl_fix_window.radius = self.fix_radius * self.scale_x
        
        # Mapping Bar 参数更新 ---
        self.bar_w = p.get('Bar Width (pix)', 10)
        self.bar_h = p.get('Bar Length (pix)', 150)
        self.bar_ang = p.get('Bar Angle (deg)', 0)
        self.bar_spd = p.get('Bar Speed (pix/s)', 400)
        self.bar_range = p.get('Bar Range (pix)', 400)
        
        # 更新猴子屏幕的 Bar 尺寸和角度
        self.sub_bar.width = self.bar_w
        self.sub_bar.height = self.bar_h
        self.sub_bar.ori = self.bar_ang
        
        # 更新控制台的 Bar 尺寸。使用统一的 scale_x 防止旋转时发生形变
        self.ctl_bar.width = self.bar_w * self.scale_x
        self.ctl_bar.height = self.bar_h * self.scale_x
        self.ctl_bar.ori = self.bar_ang

    def is_gaze_in_window(self, gaze_x, gaze_y):
        """判定视线是否在注视窗内 (计算距中心 0,0 的欧氏距离)"""
        dist = math.hypot(gaze_x - 0, gaze_y - 0)
        return dist <= self.fix_radius

    def run_task(self):
        """任务主循环：处理所有的 Trial 和状态机"""
        # 初始调用弹窗
        self.task_manager.prompt_for_parameters()
        self.update_params()
        
        print("\n=== Manual Mapping Task 开始执行 ===")
        print("按 'Esc' 退出，按 'N' 在 Trial 结束后修改参数。")
        
        trial_count = 1
        success_count = 0
        pause_requested = False

        while True:
            # ====================================================
            # 阶段 A：ITI 与 参数修改安全区
            # ====================================================
            if pause_requested:
                print("\n[实验暂停] 正在呼出参数修改面板...")
                # 视觉保护：给猴子黑屏
                self.win_sub.color = "black"
                self.win_sub.flip()
                
                # 阻塞呼出参数修改窗口
                self.task_manager.prompt_for_parameters()
                self.update_params()
                print(f"✅ 参数已更新！")
                
                # 极度重要：清空按键缓存！防止打字内容渗入下一循环
                event.clearEvents()
                
                self.win_sub.color = "black"
                self.win_sub.flip()
                pause_requested = False 
            else:
                # 正常 ITI 维持黑屏
                self.win_sub.color = 'black'
                self.win_ctl.color = 'black'
                self.win_sub.flip()
                self.win_ctl.flip()

            self.trial_clock.reset()
            while self.trial_clock.getTime() < self.iti_time:
                self.gaze_renderer.update_and_draw()

                self.win_sub.flip()
                self.win_ctl.flip()

                keys = event.getKeys()
                if 'escape' in keys: return
                if 'n' in keys:
                    pause_requested = True
                    break

            # ====================================================
            # 阶段 B：Wait for Fixation (等待猴子看过来)
            # ====================================================
            print(f"\n--- Trial {trial_count} 开始 ---")
            self.arduino.trial_start()
            if hasattr(self.shared_data, "send_event"):
                self.shared_data.send_event(f"TRIALID {trial_count}")
                self.win_sub.callOnFlip(
                    self.shared_data.send_event,
                    f"FIX_ON TRIAL {trial_count}",
                )
            
            self.ctl_fix_window.linColor = 'red'

            t_trial_start = core.getTime()
            t_draw_finish = None
            t_gaze_enter = None
            first_draw_done = False

            trial_status = "NoFix"
            self.trial_clock.reset()
            
            # 清理上一轮的杂乱按键，确保本轮按键检测干净
            event.clearEvents()
            
            gaze_acquired = False
            t_gaze_first_enter = None
            
            while self.trial_clock.getTime() < self.wait_time:
                self.stim_fix_point.draw()
                self.ctl_fix_point.draw()
                self.ctl_fix_window.draw()

                if not first_draw_done:
                    t_draw_finish = core.getTime()
                    first_draw_done = True
                
                gaze = self.gaze_renderer.update_and_draw()
                
                if gaze['valid'] and self.is_gaze_in_window(gaze['x'], gaze['y']):
                    if not gaze_acquired:
                        gaze_acquired = True
                        t_gaze_first_enter = core.getTime()
                    else:
                        current_time = core.getTime()
                        if (current_time - t_gaze_first_enter) * 1000 >= 150:
                            trial_status = "Acquired"
                            t_gaze_enter = t_gaze_first_enter
                            break
                else:
                    gaze_acquired = False
                    t_gaze_first_enter = None
                
                self.win_sub.flip()
                self.win_ctl.flip()
                
                # 在 Wait 期间允许检测按键
                keys = event.getKeys()
                if 'escape' in keys: return
                if 'n' in keys: pause_requested = True

            # ====================================================
            # 阶段 C：Hold (严格保持期，不允许眨眼或越界)
            # ====================================================
            if trial_status == "Acquired":
                self.trial_clock.reset()
                self.bar_clock.reset() # 猴子一旦注视，Bar的运动周期重置
                
                self.ctl_fix_window.lineColor = 'green'
                
                win_w, win_h = self.win_ctl.size
                
                while self.trial_clock.getTime() < self.stim_duration:
                    self.stim_fix_point.draw()
                    self.ctl_fix_point.draw()
                    self.ctl_fix_window.draw()
                    
                    # --- 新增：Mapping Bar 的渲染逻辑 ---
                    mouse_x, mouse_y = self.mouse.getPos()
                    if abs(mouse_x) <= win_w / 2 and abs(mouse_y) <= win_h / 2:
                        
                        # 2. 计算基于时间的偏移量 (dist)
                        # 使用 % 运算，让其扫过 self.bar_range 后瞬间回到负半轴继续
                        t = self.bar_clock.getTime()
                        dist = (t * self.bar_spd) % self.bar_range - (self.bar_range / 2)
                        
                        # 3. 修正：将角度转化为弧度 (加负号适配 PsychoPy 顺时针坐标系)
                        mov_rad = math.radians(-self.bar_ang) 
                        dx_sub = dist * math.cos(mov_rad)
                        dy_sub = dist * math.sin(mov_rad)
                        
                        # 4. 将控制台鼠标位置逆向映射到猴子的屏幕坐标系
                        mouse_x_sub = mouse_x / self.scale_x
                        mouse_y_sub = mouse_y / self.scale_y
                        
                        # 5. 更新并绘制猴子屏幕的 Bar
                        self.sub_bar.pos = (mouse_x_sub + dx_sub, mouse_y_sub + dy_sub)
                        self.sub_bar.draw()
                        
                        # 6. 更新并绘制控制台屏幕的 Bar (映射回控制台像素)
                        self.ctl_bar.pos = (mouse_x + dx_sub * self.scale_x, mouse_y + dy_sub * self.scale_y)
                        self.ctl_bar.draw()
                    
                    gaze = self.gaze_renderer.update_and_draw()
                    
                    # 严苛判定：无效(眨眼)或移出窗口直接 Break
                    if not gaze['valid'] or not self.is_gaze_in_window(gaze['x'], gaze['y']):
                        t_break = core.getTime()
                        fixation_duration_ms = (t_break - t_gaze_enter) * 1000
                        
                        if fixation_duration_ms <= 50:
                            trial_status = "NoFix"
                        else:
                            trial_status = "Break"
                        break

                    self.win_sub.flip()
                    self.win_ctl.flip()
                    
                    # 保持期间同样检测按键
                    keys = event.getKeys()
                    if 'escape' in keys: return
                    if 'n' in keys: pause_requested = True

                if trial_status == "Acquired":
                    trial_status = "Success"

            # ====================================================
            # 阶段 D：Outcome (结果与惩罚)
            # ====================================================
            if trial_status == "Success":
                success_count += 1
                print(f" -> Result: SUCCESS! (给水 {self.reward_len}s)")
                
                self.arduino.trial_success()
                reward_ms = int(self.reward_len * 1000)
                self.arduino.reward(reward_ms)
                
            elif trial_status == "Break":
                print(f" -> Result: BREAK! (执行 Timeout 惩罚 {self.timeout_time}s)")
                self.win_sub.color = 'black'
                self.win_ctl.color = 'black'
                self.win_sub.flip()
                self.win_ctl.flip()
                #self.win_sub.flip()
                #self.win_ctl.flip()
                self.arduino.trial_break()
                core.wait(self.timeout_time)
                
            elif trial_status == "NoFix":
                print(" -> Result: NO FIX (猴子未看屏幕)")
                self.win_sub.color = 'black'
                self.win_ctl.color = 'black'
                self.win_sub.flip()
                self.win_ctl.flip()
                self.arduino.trial_nofix()
            
            print(f"当前正确率: {success_count}/{trial_count}")
            

            if hasattr(self.shared_data, "send_event"):
                self.shared_data.send_event(
                    f"!V TRIAL_VAR Status {trial_status}"
                )
                self.shared_data.send_event(f"TRIAL_RESULT {trial_status}")
            self.behavior_log.append({
                "Trial":trial_count,
                "Status":trial_status,
                "Time_TrialStart":t_trial_start,
                "Time_DrawFinish":t_draw_finish,
                "Time_GazeEnter":t_gaze_enter,
                "Time_End":core.getTime()
            })

            trial_count += 1


# ==========================================
# 3. 主程序入口 (Main)
# ==========================================
if __name__ == '__main__':
    # 1. 启动眼动仪 Server 和共享内
    tracker_mode = globals().get("TRACKER_MODE_OVERRIDE", "qy")
    is_simulating = globals().get("IS_SIMULATING_OVERRIDE", 1)
    tracker_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tracker_runtime = create_tracker_runtime(
        tracker_mode,
        is_simulating=bool(is_simulating),
        session_id=f"ManualMap_{tracker_timestamp}",
        save_dir=os.path.dirname(os.path.abspath(__file__)),
        screen_size=(1920, 1080),
        qy_sample_rate=100,
    )
    shared_data = tracker_runtime.gaze_source
    
    # 2. 屏幕配置
    MONITOR_ID_SUBJECT = 1 
    MONITOR_ID_CONTROL = 0 

    # Log_prep
    timestamp = datetime.now().strftime("%Y%m%d")

    print("正在初始化双屏幕环境...")
    win_subject = visual.Window(
        screen=MONITOR_ID_SUBJECT,
        size=[1920, 1080], 
        fullscr=False,      # 实际电生理中如果需要高精时间，建议改为 True
        waitBlanking=True,
        color='black',
        units='pix',
        allowGUI=False
    )

    win_control = visual.Window(
        screen=MONITOR_ID_CONTROL,
        size=[800, 600],   
        fullscr=False,     
        waitBlanking=False,  #IMPORTANT: no V-Sync
        color='black',
        units='pix',
        title="Fixation Control View"
    )
    # 3. 设定专属默认参数
    mapping_defaults = {
        'Subject ID': 'Monkey_H18',
        'Wait Time (s)': 10.0,        
        'Stim Duration (s)': 10.0,    # 调长注视时间，方便你有时间挪动鼠标寻找感受野      
        'Fix Window Radius (pix)': 500, 
        'Reward Length (s)': 0.2,       
        'ITI (s)': 1.0,                  
        'Timeout (s)': 2.5,
        # --- 新增的 Mapping 参数 ---
        'Bar Width (pix)': 10,
        'Bar Length (pix)': 200,
        'Bar Angle (deg)': 0,
        'Bar Speed (pix/s)': 300,
        'Bar Range (pix)': 400
    }

    # 4. 实例化参数管理器
    print("加载参数配置...")
    task_manager = FineVision_Notebook(task_name="ManualMappingTask", default_params=mapping_defaults)

    # 5. 实例化并运行 Fixation 任务
    try:
        mapping_task = ManualMappingTask(win_subject, win_control, shared_data, task_manager, is_simulating)
        while True:
            mapping_task.run_task()
    except Exception as e:
        print(f"任务运行中发生错误: {e}")
        traceback.print_exc()
    finally:
        # 无论正常退出还是报错，必须安全回收资源
        if hasattr(mapping_task,'behavior_log') and len(mapping_task.behavior_log) > 0:
            csv_name = f"Mapping_task_log_{timestamp}.csv"
            pd.DataFrame(mapping_task.behavior_log).to_csv(csv_name,index=False)
            print(f"Log data saved.")
        
        print("正在关闭实验进程...")
        mapping_task.arduino.close()
        tracker_runtime.close()
        win_subject.close()
        win_control.close()
        core.quit()
