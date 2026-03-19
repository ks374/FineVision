import math
import os
from datetime import datetime
from psychopy import visual, core, event, gui
from multiprocessing import Process
from collections import deque
import traceback

# 确保这些自定义模块在你的同一目录下
from Shared_Memory_Util import SharedGazeData
from QYEyetracker_Server import EyetrackerServer
from Json_manager import update_json, read_json
from FineVision_Notebook import FineVision_Notebook
from GazeTrackerRenderer import GazeTrackerRenderer
from FineVision_Util import ArduinoController

# ==========================================
# 2. 核心任务类 (FixationTask)
# ==========================================
class FixationTask:
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
        self.stim_fix_point = visual.Circle(win_sub, radius=5, fillColor='white', lineColor='white', pos=(0,0))
        
        # 控制台屏幕：包含注视点、实时眼动光标、隐形的“注视窗口”边界
        self.ctl_fix_point = visual.Circle(win_ctl, radius=5 * self.scale_x, fillColor='white', pos=(0,0))
        self.ctl_gaze_cursor = visual.Circle(win_ctl, radius=6, fillColor='yellow', opacity=0.8)
        self.ctl_fix_window = visual.Circle(win_ctl, radius=100, fillColor=None, lineColor='green', lineWidth=2, pos=(0,0))

        #self.tail_line = visual.ShapeStim(
        #    self.win_ctl,
        #    vertices=[(0,0),(0,0)],
        #    closeShape=False,
        #    lineWidth=2.0,
        #    lineColor='yellow',
        #    opacity=0.6
        #)
        self.trial_clock = core.Clock()

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

    def is_gaze_in_window(self, gaze_x, gaze_y):
        """判定视线是否在注视窗内 (计算距中心 0,0 的欧氏距离)"""
        dist = math.hypot(gaze_x - 0, gaze_y - 0)
        return dist <= self.fix_radius

    def run_task(self):
        """任务主循环：处理所有的 Trial 和状态机"""
        # 初始调用弹窗
        self.task_manager.prompt_for_parameters()
        self.update_params()
        
        print("\n=== Fixation Task 开始执行 ===")
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
                self.win_sub.color = "black"
                self.win_sub.flip()
                self.win_ctl.flip()

            core.wait(self.iti_time)

            # ====================================================
            # 阶段 B：Wait for Fixation (等待猴子看过来)
            # ====================================================
            print(f"\n--- Trial {trial_count} 开始 ---")
            self.arduino.trial_start()

            trial_status = "NoFix"
            self.trial_clock.reset()
            
            # 清理上一轮的杂乱按键，确保本轮按键检测干净
            event.clearEvents()
            
            while self.trial_clock.getTime() < self.wait_time:
                self.stim_fix_point.draw()
                self.ctl_fix_point.draw()
                self.ctl_fix_window.draw()
                
                gaze = self.gaze_renderer.update_and_draw()
                
                if gaze['valid'] and self.is_gaze_in_window(gaze['x'],gaze['y']):
                    trial_status = "Acquired"
                    break
                
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
                
                while self.trial_clock.getTime() < self.stim_duration:
                    self.stim_fix_point.draw()
                    self.ctl_fix_point.draw()
                    self.ctl_fix_window.draw()
                    
                    gaze = self.gaze_renderer.update_and_draw()
                    
                    # 严苛判定：无效(眨眼)或移出窗口直接 Break
                    if not gaze['valid'] or not self.is_gaze_in_window(gaze['x'], gaze['y']):
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
                
                self.arduino.trail_success()
                reward_ms = int(self.reward_len * 1000)
                self.arduino.reward(reward_ms)
                
            elif trial_status == "Break":
                print(f" -> Result: BREAK! (执行 Timeout 惩罚 {self.timeout_time}s)")
                self.arduino.trial_break()
                self.win_sub.color = "black"
                self.win_sub.flip()
                core.wait(self.timeout_time)
                
            elif trial_status == "NoFix":
                print(" -> Result: NO FIX (猴子未看屏幕)")
                self.arduino.trial_nofix()
            
            print(f"当前正确率: {success_count}/{trial_count}")
            trial_count += 1


# ==========================================
# 3. 主程序入口 (Main)
# ==========================================
if __name__ == '__main__':
    # 1. 启动眼动仪 Server 和共享内存
    is_simulating = 1
    shared_data = SharedGazeData()
    if is_simulating == 0:
        p_server = EyetrackerServer(shared_data, "EyeControl_SDK.dll", 100)
        p_server.start()
        print("EyeTracker Server Started.")
    else:
        print("Running simulation mode.")
    
    # 2. 屏幕配置
    MONITOR_ID_SUBJECT = 1 
    MONITOR_ID_CONTROL = 0 

    # 生成当前实验的追踪 JSON
    timestamp = datetime.now().strftime("%Y%m%d")
    task_json_path = f"task_data_fixation_{timestamp}.json"
    update_json(task_json_path, "Session_start_time", timestamp)

    print("正在初始化双屏幕环境...")
    win_subject = visual.Window(
        screen=MONITOR_ID_SUBJECT,
        size=[1920, 1080], 
        fullscr=True,      # 实际电生理中如果需要高精时间，建议改为 True
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

    # 3. 设定 Fixation Task 专属默认参数
    fixation_defaults = {
        'Subject ID': 'Monkey_H18',
        'Wait Time (s)': 10.0,        
        'Stim Duration (s)': 1.5,        
        'Fix Window Radius (pix)': 250, 
        'Reward Length (s)': 0.25,       
        'ITI (s)': 5.0,                  
        'Timeout (s)': 2.5               
    }

    # 4. 实例化参数管理器
    print("加载参数配置...")
    task_manager = FineVision_Notebook(task_name="FixationTask", default_params=fixation_defaults)

    # 5. 实例化并运行 Fixation 任务
    try:
        fix_task = FixationTask(win_subject, win_control, shared_data, task_manager,is_simulating)
        fix_task.run_task()
    except Exception as e:
        print(f"任务运行中发生错误: {e}")
        traceback.print_exc()
    finally:
        # 无论正常退出还是报错，必须安全回收资源
        print("正在关闭实验进程...")
        fix_task.arduino.close()
        shared_data.stop()
        p_server.join()
        win_subject.close()
        win_control.close()
        core.quit()