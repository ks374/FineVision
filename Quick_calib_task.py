# %%
from multiprocessing import Process
from psychopy import visual, core, event
from Shared_Memory_Util import SharedGazeData
from QYEyetracker_Server import EyetrackerServer
from CalibrationManager import CalibrationManager
from Json_manager import update_json, read_json
from datetime import datetime
import json
import os
from FineVision_Util import ArduinoController

# %%
if __name__ == '__main__':

    # 初始化共享内存与眼动仪服务器
    shared_data = SharedGazeData()
    p_server = EyetrackerServer(shared_data, "EyeControl_SDK.dll", 100)
    p_server.start()
    print("EyeTracker Server Started.")

    # 1. 设置屏幕显示器 ID
    MONITOR_ID_SUBJECT = 1 
    MONITOR_ID_CONTROL = 0

    # 1.1 生成当前任务的 JSON 文件，记录元数据
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_json_path = f"quick_calib_data_{timestamp}.json"
    
    update_json(task_json_path, "Session_start_time", timestamp)
    print(f"Json file created and timestamp saved to: {task_json_path}")

    # 2. 初始化被试窗口 (猴子屏幕，全屏保证渲染时序严格)
    win_subject = visual.Window(
        screen=MONITOR_ID_SUBJECT,
        size=[1920, 1080], 
        fullscr=False,      # 生产环境中建议改为 True 以保证同步精度
        waitBlanking=True,
        color='black',
        units='pix',
        allowGUI=False
    )

    # 3. 初始化主试控制窗口 (监控视窗，窗口模式)
    win_control = visual.Window(
        screen=MONITOR_ID_CONTROL,
        size=[800, 600],   
        fullscr=False,     
        waitBlanking=False,
        color='black',
        units='pix',
        title="Quick Calibration Control View"
    )
    
    my_arduino = None
    try:
        print("正在连接 Arduino 水泵...")
        my_arduino = ArduinoController() # 请根据你的实际类定义修改参数
        print("✅ Arduino 连接成功！")
    except Exception as e:
        print(f"❌ Arduino 连接失败: {e}。本次校准将没有液体奖励。")

    # 4. 实例化 CalibrationManager
    calib_manager = CalibrationManager(
        subject_win=win_subject, 
        control_win=win_control, 
        shared_data=shared_data,
        setting_file_path=task_json_path
    )

    # 5. 加载默认校准参数 (Fallback)
    default_json_path = f"default_setting.json"
    fallback_left = {'ox': -865.6, 'oy': -301.0, 'gx': 2023.224, 'gy': 1287.796}
    fallback_right = {'ox': -1008.7, 'oy': 70.4, 'gx': 2203.769, 'gy': 1439.845}
    
    if not os.path.exists(default_json_path):
        default_left_cal = fallback_left
        default_right_cal = fallback_right
        default_settings = {
            "default_left_cal": default_left_cal,
            "default_right_cal": default_right_cal
        }
        with open(default_json_path, 'w', encoding='utf-8') as f:
            json.dump(default_settings, f, indent=4)
        print("Created new default_setting.json with fallback parameters.")
    else:
        with open(default_json_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            default_left_cal = settings.get("default_left_cal", fallback_left)
            default_right_cal = settings.get("default_right_cal", fallback_right)
        print("Fetched existing calibration parameters as default.")

    # 6. 执行 3 点快速校准
    # 注意：这里调用的是 run_quick_calib
    (left_cal, right_cal) = calib_manager.run_quick_calib(default_left_cal, default_right_cal)

    # 7. 更新 JSON 文件记录新计算的校准矩阵
    update_json(default_json_path, "default_left_cal", left_cal)
    update_json(default_json_path, "default_right_cal", right_cal)
    update_json(task_json_path, "left_cal", left_cal)
    update_json(task_json_path, "right_cal", right_cal)

    print("Quick Calibration completed and parameters saved.")

    # 8. 安全关闭所有进程与窗口
    shared_data.stop()
    p_server.join()
    win_subject.close()
    win_control.close()
    core.quit()