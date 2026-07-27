import tkinter as tk
from tkinter import messagebox
import serial
import serial.tools.list_ports
import threading
import time
import winsound

class PumpControllerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("水泵快捷控制面板")
        self.root.geometry("350x400")
        self.root.resizable(False, False)
        
        self.serial_port = None
        self.default_speed = 255  # 默认全速 5V
        
        self._build_ui()
        self._refresh_ports()
        
        self.root.after(300, self.auto_connect_com3)
        self.root.after(20, self._poll_serial)
    
    def auto_connect_com3(self):
        """启动时自动连接 COM3"""
        try:
            port = "COM3"
            self.serial_port = serial.Serial(port, 115200, timeout=1)
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
                        threading.Thread(target=self._play_pedal_beeps, daemon=True).start()
        except (serial.SerialException, OSError):
            pass
        finally:
            self.root.after(10, self._poll_serial)

    @staticmethod
    def _play_pedal_beeps():
        """约 0.2 秒内播放“嘀嘀嘀”，不阻塞界面。"""
        for index in range(3):
            winsound.Beep(1800, 50)
            if index < 2:
                time.sleep(0.025)

    def send_pump_cmd(self, cmd_type, duration_ms):
        """发送水泵时长控制指令"""
        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showwarning("未连接", "请先连接 Arduino 串口！")
            return

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
        except Exception as e:
            messagebox.showerror("发送错误", f"指令发送失败: {e}")

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
