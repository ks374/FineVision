# -*- coding: utf-8 -*-
# =============================================================================
# File Name: CursorRocker_1_0_20250621.py
# Author: Guangyuan Chen
# Created: 2025-06-21
# Description:
#     本程序用于实验猴CursorRocker范式离线神经数据与行为数据采集，SpikeTime根据Spike最新数据实时更新
#     功能包括：
#         - 可选是否连接SpikeGadgets
#         - 基于SpikeGadgets进行Spike实施数据传输
#         - 基于 Psychopy 与 Arduino 进行范式实现；
#         - 自动保存每次trial的行为数据、Firingrate数据、Spike数据、Trial信息、终端日志与配置文件。
#     注意：
#         - 请根据实验猴编号修改参数部分；
#         - 运行前调整好SpikeGadgets的Spike；
#         - 在实验前确认串口与设备连接状态。
# =============================================================================

# change screen settings
#xrandr --output HDMI-0  --primary --auto        --output HDMI-2-2 --auto --left-of HDMI-0        --output DP-0 --auto --same-as HDMI-2-2
#xinput map-to-output 12 HDMI-2-2

import os
import numpy as np
import sounddevice as sd
import shutil
from datetime import datetime
import sys
from contextlib import contextmanager
import serial
import serial.tools.list_ports as list_ports
import pandas as pd
import time
from collections import deque
import copy
import re
from trodesnetwork import socket
from threading import Thread
from queue import Queue
from psychopy import visual, event, core
import warnings
warnings.filterwarnings("ignore")


# Arduino控制类
class Arduino:
    """
    Pin口说明:
        功能	            Arduino引脚	        连接设备	                说明
        TrialStart	    D2	                采集系统Digital-IN-1	    用于发送试验开始标记
        TrialEnd	    D3	                采集系统Digital-IN-1	    用于发送试验结束标记
        PumpVoltage	    D5(PWM)	            水泵	                    数字输出控制水泵转速(0~5V)
        PumpEnable	    D6	                水泵	                    数字输出控制水泵开关(低电平开)
        PumpDirection   D7                  水泵                        数字输出控制水泵旋转方向(低电平为正向)

    """

    def __init__(self, baudrate=115200):
        """
        初始化类,设置串口连接。
        :param port: Arduino 所连接的端口号
        :param baudrate: 串口波特率,默认115200
        """
        if_connect = False
        ports = list_ports.comports()
        for port in ports:
            if port.manufacturer is not None and "Arduino" in port.manufacturer:
                self.serial_conn = serial.Serial(port.device, baudrate, timeout=1)
                time.sleep(2)  # 给Arduino时间进行初始化
                print("Connect Arduino Success!")
                if_connect = True
                break
        if not if_connect:
            raise IOError("No Arduino device found!")

    def send_command(self, command):
        """
        发送指令到Arduino,并等待返回值。
        :param command: 指令字符串
        :return: Arduino返回的信息
        """
        self.serial_conn.write((command + "\n").encode())
        response = self.serial_conn.readline().decode().strip()
        return response

    def trial_start(self, duration=50):
        """
        发送TrialStart Marker。
        :param duration: 高电平持续时间（毫秒）,默认50ms
        """
        response = self.send_command(f"MARKER:1,{duration}")
        return response

    def trial_end(self, duration=50):
        """
        发送TrialEnd Marker。
        :param duration: 高电平持续时间（毫秒）,默认50ms
        """
        response = self.send_command(f"MARKER:2,{duration}")
        return response

    def marker_3(self, duration=50):
        """
        发送TrialEnd Marker。
        :param duration: 高电平持续时间（毫秒）,默认50ms
        """
        response = self.send_command(f"MARKER:3,{duration}")
        return response
    
    def marker_4(self, duration=50):
        """
        发送TrialEnd Marker。
        :param duration: 高电平持续时间（毫秒）,默认50ms
        """
        response = self.send_command(f"MARKER:4,{duration}")
        return response

    def pump(self, duration=14000):
        """
        控制水泵运行。
        
        :param duration: 水泵运行时间（毫秒）
        """
        response = self.send_command(f"PUMP:,{duration}")
        return response

    def drain(self, duration=32767):  # int 最大值 32.767s
        """
        控制水泵排水。
        
        :param duration: 水泵运行时间（毫秒）
        """
        response = self.send_command(f"DRAIN:,{duration}")
        return response

    def stop_all(self):
        """
        停止所有操作。
        """
        response = self.send_command("STOP")
        return response
    
    def read_analog(self):
        response = list(map(float, re.findall(r"A\d: ([\d.]+)", self.send_command("READ"))))
        return np.array(response[1:]) - np.array(analog_bias)
    

    def close(self):
        """
        关闭串口连接。
        """
        self.serial_conn.close()


## Part 0:手动参数设置
#          方位图
#            1/8
#       2/8      0/8
# 3/8                   7/8
#       4/8      6/8
#            5/8
f = 0
path_com = '/home/zhaolab/桌面/Code_CoBCI/CursorRocker/online_command.py'
path_data = r'/media/zhaolab/data/E18/BehaviorData'  # 数据保存位置
path_file = os.path.basename(__file__)
path_abs_file = os.path.abspath(__file__)  # 获取当前 Python 文件的绝对路径
subject_name = input('\nInput subject name: ')

mode = "withoutSG"  # "withoutSG"
 
# 参数设置
if subject_name == "E18":
    class Config:
        speed_ratio = 6  # 光标移动速度系数
        water_time = 200  # 单次给水时间(All)
        timeout_limit = 50  # timeout时间(All)
        radius_target_circle = 350  # 目标所在圆的半径(All)
        radius_cursor = 120  # 光标半径(CursorCatch、CursorDrag)
        radius_target = 120  # 目标半径(All)
        frame_interval = 0.04  # 每20ms传输一帧数据
        drift_speed = 0  # 光标漂移速度~1.5 (Point、CursorDrag)
        target_direct_all =  [i * 1 / 8 for i in range(1, 9)]  # 目标点出现的方向（1:右下）(All)
        time_trial_interval = 2  # Trial之间的间隔(All)
        margins = 0  # 光标与屏幕最边缘的距离限制(All)
        deltaY = 100  # Y坐标调整的像素值
        deltaX = 0  # X坐标调整的像素值
else:
    print("猴号错误，请检查猴号！")

spike_data_queue = Queue()
spike_server = []
activity_container = deque(maxlen=20)
SGtime_now = 0
SGtime_last = 0
unit_all = []
analog_bias = [0, 0]

# 队列用于存储 SpikeGadgets 的数据
def spike_data_receiver():
    """
    后台线程：实时接收 SpikeGadgets 的 spike 数据。
    """
    global spike_server, SGtime_now
    while True:
        spike_data = spike_server.receive()
        if spike_data["cluster"] > 0:  # TODO: Cluster选择
            spike_data_queue.put(spike_data)  # 将数据存入队列
            SGtime_now = max(SGtime_now, spike_data["localTimestamp"])
            time.sleep(0)  # 每隔 0.1ms 接收一次数据


def calculate_valid_units():
    global unit_all
    time_wait = 10
    print(f"Please wait {time_wait}s to calculate valid channels!")
    core.wait(time_wait)
    spike_base = []
    while not spike_data_queue.empty():
        spike_base.append(spike_data_queue.get())

    df_spike_frame = pd.DataFrame(spike_base)
    unit_all = list(np.unique(df_spike_frame['nTrodeId'].map(str).str.zfill(3) + "-" + df_spike_frame['cluster'].map(str)))
    unit_all.sort()


def calculate_neural_activity():
    """
    收取当前frame累积的spike数据
    计算当前frame的activity
    :return:
    """

    global path_spike, unit_all, activity_container, SGtime_last
     
    SGtime_now_copy = copy.deepcopy(SGtime_now)
    # 获取数据帧的所有spike数据并保存
    spike_frame = []
    while not spike_data_queue.empty():
        spike_frame.append(spike_data_queue.get())

    if not len(spike_frame):
        spike_frame = [{
            'nTrodeId': None,
            'cluster': None,
            'localTimestamp': None,
            'systemTimestamp': None
        }]
    df_spike_frame = pd.DataFrame(spike_frame).sort_values(by="localTimestamp")
    df_spike_frame["unit"] = df_spike_frame['nTrodeId'].map(str).str.zfill(3) + "-" + df_spike_frame['cluster'].map(str)
    df_spike_frame = df_spike_frame.rename(columns={"localTimestamp": "SGTimestamp"})
    df_spike_frame[["unit", 'SGTimestamp']].to_csv(path_spike, mode="a", header=not os.path.exists(path_spike), index=False)
    

    firing_counts = np.array(df_spike_frame['unit'].value_counts().reindex(unit_all, fill_value=0))
    firing_rate = firing_counts / (SGtime_now_copy - SGtime_last) * 3e4
    SGtime_last = copy.deepcopy(SGtime_now_copy)
    df_fr_frame = pd.DataFrame([firing_rate], columns=unit_all)

    activity_container.append(firing_rate)
    return df_fr_frame



def initialize_experiment():
    global Config
    global diary_name, path_trial, path_location, path_spike, path_fr
    global frames_handout_limit, center_screen_x, center_screen_y, target_pos_all, drift
    global win, mouse, arduino, Beep_hit, target, cursor, spike_server, analog_bias
    # 文件夹初始化
    log_time = datetime.now().strftime('%Y%m%d')
    while True:
        session_num = input('Session number: ')
        path_session = os.path.join(path_data, log_time, session_num)
        try:
            os.makedirs(path_session)
            break
        except FileExistsError:
            print("该文件夹已经创建,请考虑创建一个新的文件夹！")
    # 更改工作目录       
    os.chdir(path_session)

    # 保存程序文件
    shutil.copy(path_abs_file, os.path.join(path_session, os.path.basename(path_file)))

    file_name = f'{subject_name}_{log_time}_{session_num}'
    diary_name = f'{file_name}_diary.txt'
    path_trial = f"{file_name}_trial.csv"
    path_location = f"{file_name}_location.csv"
    path_spike = f"{file_name}_spike.csv"
    path_fr = f"{file_name}_firingrate.csv"
    # 日志文件初始化
    with open(diary_name, 'w') as diary_file:  # 写入日志文件
        diary_file.write(f'日志开始时间: {datetime.now().strftime("%Y%m%dT%H%M%S")}\n')

    if mode == "withSG":
        # 初始化spike server并统计unit
        spike_server = socket.SourceSubscriber('source.spikes')
        spike_data_thread = Thread(target=spike_data_receiver, daemon=True)
        spike_data_thread.start()
        calculate_valid_units()


    ## 屏幕信息与触屏信息的获取
    win = visual.Window([1920, 1080], color="black", fullscr=True, units='pix', screen=1)
    screenXpixels, screenYpixels = win.size

    # 初始化Arduino
    arduino = Arduino()
    analog_bias_tmp = []
    for i in range(50):
        analog_bias_tmp.append(arduino.read_analog())
        core.wait(0.04)
    analog_bias = np.mean(analog_bias_tmp, axis=0).tolist()
    print("analog_bias: ", analog_bias)

    # 音频制作
    def make_beep(frequency, duration, fs=44100):
        # 生成一个 beep 信号,使用指定的采样率
        t = np.linspace(0, duration, int(fs * duration), endpoint=False)  # 时间序列
        beep_signal = np.sin(2 * np.pi * frequency * t)  # 生成正弦波
        return beep_signal
    Beep_hit = np.concatenate([make_beep(800, 0.1), make_beep(1300, 0.1), make_beep(2000, 0.1)])

    # 光标与目标的参数初始化
    target = {
        "Xpos": 0,  # 初始水平坐标
        "Ypos": 0,  # 初始垂直坐标
        "aim_distance": Config.radius_target + Config.radius_cursor,  # 内缘相接
        "radius": Config.radius_target,
        "timeout_limit": Config.timeout_limit,
        "region": {
            "xmin": -screenXpixels / 2 + Config.radius_target + Config.margins,
            "xmax": screenXpixels / 2 - Config.radius_target - Config.margins,
            "ymin": -screenYpixels / 2 + Config.radius_target + Config.margins,
            "ymax": screenYpixels / 2 - Config.radius_target - Config.margins
        }
    }

    cursor = {
        "Xpos": 0,  # 初始水平坐标
        "Ypos": 0,  # 初始垂直坐标
        "radius": Config.radius_cursor,
        "region": {
            "xmin": -screenXpixels / 2 + Config.radius_cursor + Config.margins,
            "xmax": screenXpixels / 2 - Config.radius_cursor - Config.margins,
            "ymin": -screenYpixels / 2 + Config.radius_cursor + Config.margins,
            "ymax": screenYpixels / 2 - Config.radius_cursor - Config.margins
        }
    }

    # 光标漂移初始化
    drift = np.random.rand(2) - 0.5  # 生成随机漂移值
    drift = Config.drift_speed * drift / np.linalg.norm(drift)  # 根据漂移速度进行归一化（此处为 0）


# 绘图
def func_draw(circle_1=None, color_1=None, circle_2=None, color_2=None):
    elements = []
    if circle_1 and color_1:
        elements.append(visual.Circle(win, radius=circle_1['radius'], pos=(circle_1['Xpos'], circle_1['Ypos']),
                                      fillColor=[c / 255.0 for c in color_1]))
    if circle_2 and color_2:
        elements.append(visual.Circle(win, radius=circle_2['radius'], pos=(circle_2['Xpos'], circle_2['Ypos']),
                                      fillColor=[c / 255.0 for c in color_2]))
    for element in elements:
        element.draw()
    win.flip()


def change_status(info_trial, status, Time_Psy, Time_Unix, Time_SG):
    global status_end_all
    if status in status_end_all:
        info_trial.update({
            "status": status,
            f"TimePsy_TrialEnd": Time_Psy,
            f"TimeUnix_TrialEnd": Time_Unix,
            f"TimeSG_TrialEnd": Time_SG,
        })
    else:
        info_trial.update({
            "status": status,
            f"TimePsy_{status}": Time_Psy,
            f"TimeUnix_{status}": Time_Unix,
            f"TimeSG_{status}": Time_SG,
        })


## Part 3: 状态与屏幕定时更新函数
def process_frame():
    global cursor, target, info_trial, touch_series
    color_blue = [-255, -255, 255]
    color_red = [255, -255, -255]
    color_green = [-255, 255, -255]

    # 时间记录
    time_trial = trial_clock.getTime()  # 获取当前时间戳
    Time_Psy = core.getTime()
    Time_Unix = int(time.time_ns() / 1000)
    Time_SG = copy.deepcopy(SGtime_now)
    if mode == "withSG": df_fr_frame = calculate_neural_activity()  # 计算当前frame的神经活动

    analog_x, analog_y = arduino.read_analog()
    analog_x = -analog_x
    cursor["Xpos"] += Config.speed_ratio * analog_x
    cursor["Ypos"] += Config.speed_ratio * analog_y


    if time_trial >= target["timeout_limit"]:
        change_status(info_trial, "timeout", Time_Psy, Time_Unix, Time_SG)

    condition = info_trial['status']
    if condition == "initial":
        func_draw(target, color_blue, cursor, color_red)
        change_status(info_trial, "runtrial", Time_Psy, Time_Unix, Time_SG)

    elif condition == "runtrial":
        # 计算新的光标位置
        cursor["Xpos"] = max(min(cursor["Xpos"], cursor["region"]["xmax"]), cursor["region"]["xmin"])
        cursor["Ypos"] = max(min(cursor["Ypos"], cursor["region"]["ymax"]), cursor["region"]["ymin"])
        func_draw(target, color_blue, cursor, color_green)
        # 若cursor与target接触
        if np.linalg.norm(np.array([cursor["Xpos"], cursor["Ypos"]]) - np.array([target["Xpos"], target["Ypos"]])) <= target["aim_distance"]:
            change_status(info_trial, "success", Time_Psy, Time_Unix, Time_SG)

    # 保存frame数据
    pd.DataFrame([{
        "TimePsy": Time_Psy,
        "TimeUnix": Time_Unix,
        "Time_SG": Time_SG,
        "CursorX": cursor["Xpos"],
        "CursorY": cursor["Ypos"],
        "TargetX": target["Xpos"],
        "TargetY": target["Ypos"],
        "AnalogX_real": analog_x,
        "AnalogY_real": analog_y,
    }]).to_csv(path_location, mode="a", header=not os.path.exists(path_location), index=False)
    if mode == "withSG": df_fr_frame.to_csv(path_fr, mode="a", header=not os.path.exists(path_fr), index=False)

    # try:
    #     exec(open(path_com).read())
    # except:
    #     print("Command Error!")

## Part 2: 运行主体
def mainfuction():
    global touch_series, trial_clock, info_trial, status_end_all
    global target, cursor

    arduino.pump(duration=17000)  # trial 开始放水充满水管
    core.wait(20)
    print(f"Main program starts at {datetime.now().strftime('%Y%m%dT%H%M%S')}")

    status_all = ["initial", "waittouch", "touchhold", "waitcatch", "success", "handout", "timeout", "rangeout", "clickout"]
    status_end_all = ["success", "handout", "timeout", "rangeout", "clickout"]
    status_keyboard = "normal"  # 运行状态 "normal", "skip", "stop"
    info_all = []
    info_all_save = []
    result_all = []  # 保存每一个trial的结果矩阵
    index_block = 0
    water_all = 0  # 总给水量

    while True:  # 每次循环一个block

        # 生成所有角度目标的位置信息
        target_pos_all = np.zeros((len(Config.target_direct_all), 2))
        for direct_index in range(len(Config.target_direct_all)):
            target_pos_x_tmp = round(Config.deltaX + Config.radius_target_circle * np.cos(2 * np.pi * Config.target_direct_all[direct_index]))
            target_pos_y_tmp = round(Config.deltaY + Config.radius_target_circle * np.sin(2 * np.pi * Config.target_direct_all[direct_index]))
            target_pos_all[direct_index, 0] = np.clip(target_pos_x_tmp + drift[0], target["region"]["xmin"], target["region"]["xmax"])
            target_pos_all[direct_index, 1] = np.clip(target_pos_y_tmp + drift[1], target["region"]["ymin"], target["region"]["ymax"])


        index_block += 1
        index_target_series = np.random.permutation(len(Config.target_direct_all))  # 乱序执行
        # index_target_series = 1：(len(target_direct_all))  # 顺序执行

        print(f"\nBlock {index_block} #####################")
        print(f"Target index series: {index_target_series}\n")

        info_trial = {}  # 当前trial的信息
        index_trial = 0
        index_target_series_index = 0

        while index_target_series_index < len(index_target_series):  # 做满8个方向为一循环

            if info_trial.get("status", "initial") in ["rangeout", "timeout", "handout", "clickout"]:
                index_target_series_index -= 1
            index_target = index_target_series[index_target_series_index]

            index_trial += 1
            index_target_series_index += 1
            print(f"\nTrial {index_trial}, Target-{index_target}: ", end="")

            # 光标信息
            cursor["Xpos"] = Config.deltaX
            cursor["Ypos"] = Config.deltaY
            # target信息
            target_direct_trial = Config.target_direct_all[index_target]  # 当前trial target方向
            target_posi_trial = target_pos_all[index_target, :]  # 当前trial target位置
            target["Direct_ini"] = target_direct_trial
            target["Xpos"] = max(min(target_posi_trial[0], target["region"]["xmax"]), target["region"]["xmin"])
            target["Ypos"] = max(min(target_posi_trial[1], target["region"]["ymax"]), target["region"]["ymin"])

            # 当前trial信息
            info_trial = {
                "index_block": index_block,
                "index_trial": index_trial,
                "status": "initial",
                "targetX": target["Xpos"],
                "targetY": target["Ypos"],
                "targetRadius": target["radius"],
                "cursorX": cursor["Xpos"],
                "cursorY": cursor["Ypos"],
                "cursorRadius": cursor["radius"],
                "dist_target": np.linalg.norm(np.array([target["Xpos"], target["Ypos"]]) - np.array([cursor["Xpos"], cursor["Ypos"]])),
                "TimePsy_TrialStart": core.getTime(),
                "TimeUnix_TrialStart": int(time.time_ns() / 1000),
                "TimeSG_TrialStart": SGtime_now,
            }
            arduino.trial_start()  # Marker-Trial开始，等待拖动

            # 循环获取位置并更新
            touch_series = []
            trial_clock, frame_clock = core.Clock(), core.Clock()  # 在这里开始计时,每20ms执行一次 process_frame
            while True:  # 循环检测trial结束
                frame_clock.reset()
                process_frame()

                if info_trial["status"] in status_end_all:  # trial结束
                    break

                # 判断当前按键状态
                status_keyboard = "normal"
                keys = event.getKeys()
                if "escape" in keys:
                    status_keyboard = "stop"
                    break
                if "space" in keys:
                    status_keyboard = "skip"
                    break


                # 等待帧间隔
                remaining_time = Config.frame_interval - frame_clock.getTime()
                if remaining_time > 0: core.wait(remaining_time)

            # Trial结束处理
            func_draw()  # 黑屏
            arduino.trial_end()  # Marker-结束trial
            if info_trial["status"] == "success":  # 成功奖励
                sd.play(Beep_hit, 48000, device=0)  # 声音提示
                arduino.pump(Config.water_time)
                water_all=water_all + Config.water_time;  # 总给水时间
            
            # trial结束，保存当前trial数据
            info_all_save.append(info_trial.copy())
            pd.DataFrame(info_all_save).to_csv(path_trial, mode="w", header=True, index=False)  # 保存精简数据
            info_trial["cursor"] = cursor
            info_trial["target"] = target
            info_all.append(info_trial)
            pd.DataFrame(info_all).to_csv(path_trial.replace(".csv", "_detail.csv"), mode="w", header=True, index=False)  # 保存全部数据
            result_all.append(info_trial["status"])
            print(info_trial["status"])
            print(f"Success: {result_all.count('success')}, Handout: {result_all.count('handout')}, Timeout: {result_all.count('timeout')}, Rangeout: {result_all.count('rangeout')}, Clickout: {result_all.count('clickout')}")

            core.wait(Config.time_trial_interval)  # 间隔

            # 判断trial手动控制状态
            if (status_keyboard == "stop") | (status_keyboard == "skip"):
                break
        # 判断block运行状态
        if status_keyboard == "stop":
            break

    arduino.drain(duration=30000)  # 排空水管，方便记录给水
    print(f"\nTotal Water: {water_all / 1e3} s")
    print(f"Total block number is {index_block}")
    win.close()
    arduino.close()


# 记录日志
@contextmanager
def dual_output(filename):
    class DualOutput:
        def __init__(self, filename):
            self.file = open(filename, 'a')
            self.stdout = sys.stdout

        def write(self, message):
            self.stdout.write(message)
            self.file.write(message)

        def flush(self):
            self.stdout.flush()
            self.file.flush()

    dual = DualOutput(filename)
    sys.stdout = dual
    try:
        yield
    finally:
        sys.stdout = dual.stdout
        dual.file.close()


# 使用示例
if __name__ == "__main__":

    initialize_experiment()

    with dual_output(diary_name):
        # 你的程序代码
        mainfuction()
