import math
import os
import random
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
# 2. 核心任务类 (AutoMappingTask)
# ==========================================
class AutoMappingTask:
    def __init__(self, win_sub, win_ctl, shared_data, task_manager, is_simulating):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.task_manager = task_manager
        self.is_simulating = is_simulating

        self.arduino = ArduinoController()
        
        # 计算双屏缩放比例
        self.scale_x = win_ctl.size[0] / win_sub.size[0]
        self.scale_y = win_ctl.size[1] / win_sub.size[1]

        self.gaze_renderer = GazeTrackerRenderer(self.win_ctl, self.shared_data, self.scale_x, self.scale_y, self.is_simulating)

        # --- 视觉刺激初始化 ---
        self.stim_fix_point = visual.Circle(win_sub, radius=15, fillColor='green', lineColor='green', pos=(0,0))
        self.ctl_fix_point = visual.Circle(win_ctl, radius=15 * self.scale_x, fillColor='green', pos=(0,0))
        self.ctl_gaze_cursor = visual.Circle(win_ctl, radius=6, fillColor='yellow', opacity=0.8)
        self.ctl_fix_window = visual.Circle(win_ctl, radius=100, fillColor=None, lineColor='red', lineWidth=2, pos=(0,0))

        # --- Mapping Bar 初始化 ---
        self.sub_bar = visual.Rect(self.win_sub, fillColor='white', lineColor=None)
        self.ctl_bar = visual.Rect(self.win_ctl, fillColor='white', lineColor=None, opacity=0.7)
        
        # --- 光电二极管 (PD) 触发块 ---
        # 放置在猴子屏幕的右下角，尺寸 100x100 像素
        # 1920x1080 的屏幕，中心点为 (0,0)，右下角边缘为 (960, -540)
        self.pd_block = visual.Rect(self.win_sub, width=100, height=100, pos=(910, -490), fillColor='white', lineColor=None)

        self.trial_clock = core.Clock()
        self.behavior_log = []
        self.session_time = datetime.now().strftime("%Y%m%d_%H%M%S")

        # --- Trial 队列管理 ---
        # 0: 向右, 1: 向下, 2: 向左, 3: 向上
        # 同样的 4 个 trial 重复 8 次
        base_blocks = [0, 1, 2, 3] * 8
        self.trial_queue = deque(base_blocks)

    def update_params(self):
        """从参数管理器中拉取最新的参数并更新类的属性"""
        p = self.task_manager.exp_params
        
        self.wait_time = p.get('Wait Time (s)', 2.0)
        # 固定扫描时间为 1 秒
        self.stim_duration = 1.0 
        self.reward_len = p.get('Reward Length (s)', 0.2)
        self.iti_time = p.get('ITI (s)', 1.0)
        self.timeout_time = p.get('Timeout (s)', 2.0)
        self.fix_radius = p.get('Fix Window Radius (pix)', 100)
        
        self.ctl_fix_window.radius = self.fix_radius * self.scale_x

        # --- Auto Mapping 参数 ---
        self.rf_x = p.get('RF Center X (pix)', 0)
        self.rf_y = p.get('RF Center Y (pix)', 0)
        self.bar_spd = p.get('Bar Speed (pix/s)', 400)
        self.bar_l = p.get('Bar Length (pix)', 200)
        self.bar_w = p.get('Bar Width (pix)', 10)

    def is_gaze_in_window(self, gaze_x, gaze_y):
        """判定视线是否在注视窗内 (计算距中心 0,0 的欧氏距离)"""
        dist = math.hypot(gaze_x - 0, gaze_y - 0)
        return dist <= self.fix_radius

    def run_task(self):
        """任务主循环：处理所有的 Trial 和状态机"""
        self.task_manager.prompt_for_parameters()
        self.update_params()
        
        print("\n=== Auto Mapping Task 开始执行 ===")
        print("按 'Esc' 退出，按 'N' 在 Trial 结束后修改参数。")
        
        trial_count = 1
        success_count = 0
        pause_requested = False

        # 只要队列里还有任务，就一直执行
        while len(self.trial_queue) > 0:
            
            # 取出当前要执行的 Trial 条件
            current_cond = self.trial_queue.popleft()
            
            # ====================================================
            # 阶段 A：ITI 与 参数修改安全区
            # ====================================================
            if pause_requested:
                print("\n[实验暂停] 正在呼出参数修改面板...")
                self.win_sub.color = "black"
                self.win_sub.flip()
                
                self.task_manager.prompt_for_parameters()
                self.update_params()
                print(f"✅ 参数已更新！")
                
                event.clearEvents()
                self.win_sub.color = "black"
                self.win_sub.flip()
                pause_requested = False 
            else:
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
            dir_names = {0: "Right", 1: "Down", 2: "Left", 3: "Up"}
            print(f"\n--- Trial {trial_count} 开始 | 队列剩余: {len(self.trial_queue)} | 方向: {dir_names[current_cond]} ---")
            self.arduino.trial_start()
            if hasattr(self.shared_data, "send_event"):
                self.shared_data.send_event(f"TRIALID {trial_count}")
                self.win_sub.callOnFlip(
                    self.shared_data.send_event,
                    f"FIX_ON TRIAL {trial_count}",
                )
            
            self.ctl_fix_window.lineColor = 'red'

            t_trial_start = core.getTime()
            t_draw_finish = None
            t_gaze_enter = None
            first_draw_done = False
            trial_status = "NoFix"
            self.trial_clock.reset()
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
                
                keys = event.getKeys()
                if 'escape' in keys: return
                if 'n' in keys: pause_requested = True

            # ====================================================
            # 阶段 C：Hold (严格保持期，1秒固定动画)
            # ====================================================
            if trial_status == "Acquired":
                self.trial_clock.reset()
                self.ctl_fix_window.lineColor = 'green'
                
                while self.trial_clock.getTime() < self.stim_duration:
                    t = self.trial_clock.getTime() # t 从 0 走到 1.0
                    
                    # --- 核心：计算 Bar 在这一帧的位置 ---
                    # 距离公式：当前位置 = 起点 + (速度 * 时间)
                    # 扫描总范围 = 速度 * 1秒 = self.bar_spd
                    
                    if current_cond == 0: # 0: 向右移动 (竖条)
                        self.sub_bar.width, self.sub_bar.height = self.bar_w, self.bar_l
                        curr_x = self.rf_x - (self.bar_spd / 2) + (self.bar_spd * t)
                        curr_y = self.rf_y
                        
                    elif current_cond == 1: # 1: 向下移动 (横条)
                        self.sub_bar.width, self.sub_bar.height = self.bar_l, self.bar_w
                        curr_x = self.rf_x
                        curr_y = self.rf_y + (self.bar_spd / 2) - (self.bar_spd * t)
                        
                    elif current_cond == 2: # 2: 向左移动 (竖条)
                        self.sub_bar.width, self.sub_bar.height = self.bar_w, self.bar_l
                        curr_x = self.rf_x + (self.bar_spd / 2) - (self.bar_spd * t)
                        curr_y = self.rf_y
                        
                    elif current_cond == 3: # 3: 向上移动 (横条)
                        self.sub_bar.width, self.sub_bar.height = self.bar_l, self.bar_w
                        curr_x = self.rf_x
                        curr_y = self.rf_y - (self.bar_spd / 2) + (self.bar_spd * t)

                    # 更新猴子屏幕 Bar
                    self.sub_bar.pos = (curr_x, curr_y)
                    
                    # 更新控制台屏幕 Bar
                    self.ctl_bar.width = self.sub_bar.width * self.scale_x
                    self.ctl_bar.height = self.sub_bar.height * self.scale_x
                    self.ctl_bar.pos = (curr_x * self.scale_x, curr_y * self.scale_y)

                    # 绘制所有元素
                    self.stim_fix_point.draw()
                    self.ctl_fix_point.draw()
                    self.ctl_fix_window.draw()
                    self.sub_bar.draw()
                    self.ctl_bar.draw()
                    
                    # --- 新增：绘制 PD 白块 ---
                    # 它只会在这个 1 秒的扫描循环内被绘制，意味着 Bar 出现的瞬间白块出现，Bar 消失瞬间白块消失
                    self.pd_block.draw()
                    
                    gaze = self.gaze_renderer.update_and_draw()
                    
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
                
            else:
                # 核心机制：如果失败，将当前任务插回队列最前面（等待重做）
                self.trial_queue.appendleft(current_cond)
                
                if trial_status == "Break":
                    print(f" -> Result: BREAK! (任务重新入队，执行 Timeout 惩罚 {self.timeout_time}s)")
                    self.win_sub.color = 'black'
                    self.win_ctl.color = 'black'
                    self.win_sub.flip()
                    self.win_ctl.flip()
                    self.arduino.trial_break()
                    core.wait(self.timeout_time)
                elif trial_status == "NoFix":
                    print(" -> Result: NO FIX (猴子未看屏幕，任务重新入队)")
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
                self.shared_data.send_event(
                    f"!V TRIAL_VAR Condition {dir_names[current_cond]}"
                )
                self.shared_data.send_event(f"TRIAL_RESULT {trial_status}")
            self.behavior_log.append({
                "Trial": trial_count,
                "Condition": dir_names[current_cond],
                "Status": trial_status,
                "Time_TrialStart": t_trial_start,
                "Time_DrawFinish": t_draw_finish,
                "Time_GazeEnter": t_gaze_enter,
                "Time_End": core.getTime()
            })

            trial_count += 1
            
        # 跳出 while 循环意味着队列已清空
        print("\n🎉 全部扫描任务已顺利完成！")


# ==========================================
# 3. 主程序入口 (Main)
# ==========================================
if __name__ == '__main__':
    tracker_mode = globals().get("TRACKER_MODE_OVERRIDE", "qy")
    is_simulating = globals().get("IS_SIMULATING_OVERRIDE", 1)
    tracker_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tracker_runtime = create_tracker_runtime(
        tracker_mode,
        is_simulating=bool(is_simulating),
        session_id=f"RFMap_{tracker_timestamp}",
        save_dir=os.path.dirname(os.path.abspath(__file__)),
        screen_size=(1920, 1080),
        qy_sample_rate=100,
    )
    shared_data = tracker_runtime.gaze_source
    
    MONITOR_ID_SUBJECT = 1 
    MONITOR_ID_CONTROL = 0 

    timestamp = datetime.now().strftime("%Y%m%d")

    print("正在初始化双屏幕环境...")
    win_subject = visual.Window(
        screen=MONITOR_ID_SUBJECT,
        size=[1920, 1080], 
        fullscr=False,
        waitBlanking=True,
        color='black',
        units='pix',
        allowGUI=False
    )

    win_control = visual.Window(
        screen=MONITOR_ID_CONTROL,
        size=[800, 450],
        fullscr=False,     
        waitBlanking=False, 
        color='black',
        units='pix',
        title="Auto Mapping Control View"
    )

    # 3. 设定 Auto Mapping 专属默认参数
    auto_mapping_defaults = {
        'Subject ID': 'Monkey_H18',
        'Wait Time (s)': 10.0,        
        'Fix Window Radius (pix)': 100, 
        'Reward Length (s)': 0.2,       
        'ITI (s)': 3.0,                  
        'Timeout (s)': 2.5,
        # --- 新增：自动扫描专属参数 ---
        'RF Center X (pix)': 200,
        'RF Center Y (pix)': -200,
        'Bar Speed (pix/s)': 400,
        'Bar Length (pix)': 420,
        'Bar Width (pix)': 10
    }

    print("加载参数配置...")
    task_manager = FineVision_Notebook(task_name="AutoMappingTask", default_params=auto_mapping_defaults)

    try:
        auto_task = AutoMappingTask(win_subject, win_control, shared_data, task_manager, is_simulating)
        auto_task.run_task()
    except Exception as e:
        print(f"任务运行中发生错误: {e}")
        traceback.print_exc()
    finally:
        if hasattr(auto_task,'behavior_log') and len(auto_task.behavior_log) > 0:
            csv_name = f"AutoMapping_task_log_{timestamp}.csv"
            pd.DataFrame(auto_task.behavior_log).to_csv(csv_name,index=False)
            print(f"Log data saved.")
        
        print("正在关闭实验进程...")
        auto_task.arduino.close()
        tracker_runtime.close()
        win_subject.close()
        win_control.close()
        core.quit()
