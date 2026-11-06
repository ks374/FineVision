import tkinter as tk
from tkinter import messagebox
import json
import serial
import serial.tools.list_ports
import threading
import time

from FineVision_Util import play_reward_sound

class PumpControllerApp:
    MILLIKEY_USB_VID = 0x16C0
    MILLIKEY_USB_PID = 0x048A
    MILLIKEY_BAUDRATE = 128000
    EXTERNAL_BUTTON_DEBOUNCE_S = 0.75

    def __init__(self, root):
        self.root = root
        self.root.title("水泵快捷控制面板")
        self.root.geometry("350x440")
        self.root.resizable(False, False)
        
        self.serial_port = None
        self.default_speed = 255  # 默认全速 5V
        self._sound_lock = threading.Lock()
        self._external_button_last_reward_time = float("-inf")
        self._millikey_serial = None
        self._millikey_last_pressed = False
        self._millikey_reward_pending = False
        self._external_button_active = True
        self._millikey_stop_event = threading.Event()
        
        self._build_ui()
        self._refresh_ports()
        self._init_external_button_listener()
        
        self.root.after(300, self.auto_connect_com3)
        self.root.after(20, self._poll_serial)
        self.root.after(20, self._dispatch_millikey_reward)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def auto_connect_com3(self):
        """启动时自动连接 COM3"""
        try:
            port = "COM3"
            self.serial_port = serial.Serial(port, 115200, timeout=1)
            self.serial_port.reset_input_buffer()
            self.port_var.set(port)
            self.btn_connect.config(text="断开")
            self.lbl_status.config(text=f"状态: 已自动连接到 {port}", fg="green")
        except:
            self.lbl_status.config(text=f"状态: COM3 连接失败", fg="red")

    def _build_ui(self):
        # ================= 连接区域 =================
        frame_conn = tk.LabelFrame(self.root, text="串口连接", padx=10, pady=10)
        frame_conn.pack(fill="x", padx=10, pady=10)
        
        self.port_var = tk.StringVar()
        self.port_menu = tk.OptionMenu(frame_conn, self.port_var, "")
        self.port_menu.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.btn_refresh = tk.Button(frame_conn, text="刷新", command=self._refresh_ports)
        self.btn_refresh.pack(side="left", padx=(0, 5))
        
        self.btn_connect = tk.Button(frame_conn, text="连接", command=self._toggle_connection)
        self.btn_connect.pack(side="left")

        # ================= 控制按钮区域 =================
        frame_ctrl = tk.LabelFrame(self.root, text="快捷控制", padx=10, pady=10)
        frame_ctrl.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 1. 正转 2s
        btn_fwd_2s = tk.Button(frame_ctrl, text="💧 正转 2s (快速给水)", font=("Arial", 12),
                               command=lambda: self.send_pump_cmd(128, 2000), bg="#e0f7fa", height=2)
        btn_fwd_2s.pack(fill="x", pady=5)

        # 2. 正转 50s
        btn_fwd_10s = tk.Button(frame_ctrl, text="🌊 正转 50s (大量给水)", font=("Arial", 12),
                                command=lambda: self.send_pump_cmd(128, 50000), bg="#b2ebf2", height=2)
        btn_fwd_10s.pack(fill="x", pady=5)

        # 3. 反转 60s
        btn_rev_20s = tk.Button(frame_ctrl, text="🔄 反转 60s (排空管路)", font=("Arial", 12),
                                command=lambda: self.send_pump_cmd(129, 60000), bg="#fff9c4", height=2)
        btn_rev_20s.pack(fill="x", pady=5)

        # 4. 紧急停止
        btn_stop = tk.Button(frame_ctrl, text="🛑 紧急停止", font=("Arial", 12, "bold"), fg="white",
                             command=self.send_stop_cmd, bg="#ef5350", height=2)
        btn_stop.pack(fill="x", pady=(15, 5))

        btn_single_reward = tk.Button(
            frame_ctrl,
            text="💧 单次给水 0.5s + 声音",
            font=("Arial", 12, "bold"),
            command=self.trigger_single_reward,
            bg="#c8e6c9",
            height=2,
        )
        btn_single_reward.pack(fill="x", pady=(5, 0))

        self.external_button_enabled = tk.BooleanVar(value=True)
        chk_external_button = tk.Checkbutton(
            frame_ctrl,
            text="后台监听 MilliKey 第一个按钮（给水 0.5s + 声音）",
            variable=self.external_button_enabled,
            command=self._set_external_button_enabled,
            anchor="w",
        )
        chk_external_button.pack(fill="x", pady=(6, 0))

        # 状态栏
        self.lbl_status = tk.Label(self.root, text="状态: 未连接", fg="red")
        self.lbl_status.pack(side="bottom", pady=5)

    def _refresh_ports(self):
        """刷新可用串口列表"""
        ports = serial.tools.list_ports.comports()
        menu = self.port_menu["menu"]
        menu.delete(0, "end")
        
        port_list = [port.device for port in ports]
        if port_list:
            for p in port_list:
                menu.add_command(label=p, command=lambda value=p: self.port_var.set(value))
            self.port_var.set(port_list[0])
        else:
            self.port_var.set("未找到串口")

    def _toggle_connection(self):
        """连接或断开串口"""
        if self.serial_port and self.serial_port.is_open:
            # 执行断开
            self.serial_port.close()
            self.btn_connect.config(text="连接")
            self.lbl_status.config(text="状态: 已断开", fg="red")
        else:
            # 执行连接
            port = self.port_var.get()
            if not port or port == "未找到串口":
                messagebox.showwarning("警告", "请选择有效的 COM 端口！")
                return
            try:
                self.serial_port = serial.Serial(port, 115200, timeout=1)
                self.serial_port.reset_input_buffer()
                self.btn_connect.config(text="断开")
                self.lbl_status.config(text=f"状态: 已连接到 {port}", fg="green")
            except Exception as e:
                messagebox.showerror("连接失败", f"无法连接到 {port}:\n{e}")

    def _poll_serial(self):
        """监听 Arduino 的脚踏通知，并让电脑扬声器发出三声短音。"""
        try:
            if self.serial_port and self.serial_port.is_open:
                while self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode("utf-8", errors="ignore").strip()
                    if "Pressed" in line:
                        self.lbl_status.config(text="状态: 已收到脚踏信号，正在播放提示音", fg="green")
                        # self._start_pedal_sound()   #以关闭电脑端声音
        except (serial.SerialException, OSError) as error:
            self.lbl_status.config(text=f"状态: 串口读取失败: {error}", fg="red")
        finally:
            self.root.after(10, self._poll_serial)

    def _init_external_button_listener(self):
        """通过 MilliKey 自带串口读取按钮，不向 Windows 发送键盘输入。"""
        threading.Thread(
            target=self._poll_external_button,
            name="MilliKeyButtonMonitor",
            daemon=True,
        ).start()

    def _poll_external_button(self):
        """持续读取 MilliKey 第一个按钮的物理状态并识别按下边沿。"""
        while not self._millikey_stop_event.is_set():
            if not self._external_button_active:
                self._millikey_last_pressed = False
                time.sleep(0.1)
                continue

            try:
                if self._millikey_serial is None or not self._millikey_serial.is_open:
                    self._connect_millikey()
                pressed = self._read_millikey_button_1()
                if pressed and not self._millikey_last_pressed:
                    self._millikey_reward_pending = True
                self._millikey_last_pressed = pressed
            except (serial.SerialException, OSError, ValueError, KeyError, json.JSONDecodeError):
                self._close_millikey_serial()
                self._millikey_last_pressed = False
                time.sleep(1.0)

    def _set_external_button_enabled(self):
        self._external_button_active = self.external_button_enabled.get()

    def _dispatch_millikey_reward(self):
        """在 Tk 主线程执行串口给水和界面更新。"""
        if self._millikey_reward_pending:
            self._millikey_reward_pending = False
            self._handle_external_button_press()
        self.root.after(10, self._dispatch_millikey_reward)

    def _connect_millikey(self):
        """按硬件 ID 自动寻找并连接 MilliKey 的 USB 串口。"""
        port_name = next(
            (
                port.device
                for port in serial.tools.list_ports.comports()
                if port.vid == self.MILLIKEY_USB_VID
                and port.pid == self.MILLIKEY_USB_PID
            ),
            None,
        )
        if port_name is None:
            raise serial.SerialException("未找到 MilliKey")
        self._millikey_serial = serial.Serial(
            port_name,
            self.MILLIKEY_BAUDRATE,
            timeout=0.2,
        )
        self._millikey_serial.reset_input_buffer()

    def _read_millikey_button_1(self):
        """读取 MilliKey 配置响应中的第一个物理按钮状态。"""
        self._millikey_serial.write(b"GET CONFIG\n")
        response = self._millikey_serial.readline().decode(
            "utf-8", errors="replace"
        ).strip()
        if not response:
            raise serial.SerialException("MilliKey 无响应")
        config = json.loads(response)
        return bool(config["hardware"]["buttons"][0]["pressed"])

    def _close_millikey_serial(self):
        if self._millikey_serial is not None:
            try:
                self._millikey_serial.close()
            except (serial.SerialException, OSError):
                pass
            self._millikey_serial = None

    def _handle_external_button_press(self, now=None):
        """MilliKey 按钮每按一次给水一次，并过滤键盘连发。"""
        if now is None:
            now = time.monotonic()

        if now - self._external_button_last_reward_time < self.EXTERNAL_BUTTON_DEBOUNCE_S:
            return
        self._external_button_last_reward_time = now
        self.trigger_single_reward(source="MilliKey 按钮 1")

    def _on_close(self):
        self._millikey_stop_event.set()
        self._close_millikey_serial()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.root.destroy()

    def _start_pedal_sound(self):
        """在 Windows 当前默认音频设备上播放快速六声提示音。"""
        if not self._sound_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._play_pedal_beeps, daemon=True).start()

    def _play_pedal_beeps(self):
        """复用 Orientation/Saccade 任务的 0.5 秒快速给水提示音。"""
        try:
            play_reward_sound()
            self.root.after(
                0,
                lambda: self.lbl_status.config(text="状态: 提示音播放完成", fg="green"),
            )
        except RuntimeError as error:
            self.root.after(
                0,
                lambda: self.lbl_status.config(text=f"状态: 提示音播放失败: {error}", fg="red"),
            )
        finally:
            self._sound_lock.release()

    def trigger_single_reward(self, source="界面按钮"):
        """模拟踩下一次脚踏：给水 500 ms，并播放一次奖励提示音。"""
        if self.send_pump_cmd(128, 500):
            self.lbl_status.config(
                text=f"状态: {source}触发给水 0.5s，并播放提示音",
                fg="green",
            )
            # self._start_pedal_sound()    #以关闭电脑端声音

    def send_pump_cmd(self, cmd_type, duration_ms):
        """发送水泵时长控制指令"""
        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showwarning("未连接", "请先连接 Arduino 串口！")
            return False

        # 按照 Arduino 代码逻辑拆解为 High Byte 和 Low Byte
        high_byte = (duration_ms >> 8) & 0xFF
        low_byte = duration_ms & 0xFF
        speed = self.default_speed

        try:
            # 将 4 个字节打包发送
            payload = bytes([cmd_type, high_byte, low_byte, speed])
            self.serial_port.write(payload)
            
            action = "正转" if cmd_type == 128 else "反转"
            print(f"发送成功: {action} {duration_ms}ms, 速度 {speed}")
            return True
        except Exception as e:
            messagebox.showerror("发送错误", f"指令发送失败: {e}")
            return False

    def send_stop_cmd(self):
        """发送紧急停止指令"""
        if not self.serial_port or not self.serial_port.is_open:
            return
        try:
            self.serial_port.write(bytes([130]))
            print("发送成功: 紧急停止")
        except Exception as e:
            print(f"停止指令发送失败: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = PumpControllerApp(root)
    root.mainloop()
