# %%
from multiprocessing import Process
from psychopy import visual,core,event
from Shared_Memory_Util import SharedGazeData
from QYEyetracker_Server import EyetrackerServer
from CalibrationManager import CalibrationManager

# %%
if __name__ == '__main__':

    shared_data = SharedGazeData()
    p_server = EyetrackerServer(shared_data, "EyeControl_SDK.dll", 100)
    p_server.start()
    print("EyeTracker Server Started.")
    # 1. 自动检测屏幕数量
#    你的电脑可能是 Screen 0 (主屏), 猴子显示器是 Screen 1
#   可以在 Windows "显示设置" 里确认编号
    MONITOR_ID_SUBJECT = 1 
    MONITOR_ID_CONTROL = 0 

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

    # 4. 传入 Manager
    calib_manager = CalibrationManager(
        subject_win=win_subject, 
        control_win=win_control, 
        shared_data=shared_data
    )

    (left_cal,right_cal) = calib_manager.run_calibration()

    (left_cal,right_cal) = calib_manager.run_calibration(left_cal,right_cal)

    shared_data.stop()
    p_server.join()
    win_subject.close()
    win_control.close()
    core.quit()


