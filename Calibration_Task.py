# %%
from multiprocessing import Process
from psychopy import visual,core,event
from Shared_Memory_Util import SharedGazeData
from QYEyetracker_Server import EyetrackerServer
from CalibrationManager import CalibrationManager
from Json_manager import update_json,read_json
from datetime import datetime
import json
import os
from FineVision_Util import ArduinoController

# %%
if __name__ == '__main__':

    is_simulating = 0
    
    shared_data = SharedGazeData()
    if is_simulating == 0:
        p_server = EyetrackerServer(shared_data, "EyeControl_SDK.dll", 100)
        p_server.start()
        print("EyeTracker Server Started.")
    else:
        print("Running simulation mode.")
    # 1. 自动检测屏幕数量
#    你的电脑可能是 Screen 0 (主屏), 猴子显示器是 Screen 1
#   可以在 Windows "显示设置" 里确认编号
    MONITOR_ID_SUBJECT = 1 
    MONITOR_ID_CONTROL = 0

    # 1.1 生成当前任务的json文件，后缀为cal
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_json_path = f"task_data_{timestamp}.json"
    
    update_json(task_json_path,"Session_start_time",timestamp)
    print(f"Json file created and timestamp saved to: {task_json_path}")

    # 2. 初始化猴子窗口 (Full Screen)
    win_subject = visual.Window(
        screen=MONITOR_ID_SUBJECT,
        size=[1920, 1080], 
        fullscr=False,      # 必须全屏以保证时间精度
        waitBlanking=True,
        color='black',
        units='pix',
        allowGUI=False
    )

    # 3. 初始化控制窗口 (Windowed, Small)
    # 这个窗口给你看，不用太大，800x600 足够看清布局了
    win_control = visual.Window(
        screen=MONITOR_ID_CONTROL,
        size=[800, 600],   # 保持和猴子屏幕大致的长宽比 (4:3 或 16:9)
        fullscr=False,     # 窗口模式
        waitBlanking=False,
        color='black',
        units='pix',
        title="Experiment Control View"
    )
    
    my_arduino = None
    try:
        print("正在连接 Arduino 水泵...")
        my_arduino = ArduinoController() # 请根据你的实际类定义修改参数
        print("✅ Arduino 连接成功！")
    except Exception as e:
        print(f"❌ Arduino 连接失败: {e}。本次校准将没有液体奖励。")

    # 4. 传入 Manager
    calib_manager = CalibrationManager(
        subject_win=win_subject, 
        control_win=win_control, 
        shared_data=shared_data,
        setting_file_path = task_json_path,
        arduino_controller = my_arduino,
        is_simulating=is_simulating
    )

    default_json_path = f"default_setting.json"
    fallback_left = {'ox': -865.6, 'oy': -301.0, 'gx': 2023.224, 'gy': 1287.796}
    fallback_right = {'ox': -1008.7, 'oy': 70.4, 'gx': 2203.769, 'gy': 1439.845}
    if not os.path.exists(default_json_path):
        default_left_cal = fallback_left
        default_right_cal = fallback_right
        default_settings = {
            "default_left_cal":default_left_cal,
            "default_right_cal":default_right_cal
        }
        with open(default_json_path,'w',encoding='utf-8') as f:
            json.dump(default_settings,f,indent=4)
        
    else:
        with open(default_json_path,'r',encoding='utf-8') as f:
            settings = json.load(f)
            default_left_cal = settings.get("default_left_cal",fallback_left)
            default_right_cal = settings.get("default_right_cal",fallback_right)
        print(f"Fetch default cali parameters as default.")

    (left_cal,right_cal) = calib_manager.run_calibration(default_left_cal,default_right_cal)

    #Need to update default and task json files. 
    update_json(default_json_path,"default_left_cal",left_cal)
    update_json(default_json_path,"default_right_cal",right_cal)
    update_json(task_json_path,"left_cal",left_cal)
    update_json(task_json_path,"right_cal",right_cal)

    #(left_cal,right_cal) = calib_manager.run_calibration(left_cal,right_cal)

    

    shared_data.stop()
    if is_simulating != 1:
        p_server.join()
    win_subject.close()
    win_control.close()
    core.quit()


