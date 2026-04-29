# %%
import serial
import serial.tools.list_ports as list_ports
import time
from trodesnetwork import socket # 假设你已安装 SpikeGadgets 的 Python API


# %%
class ArduinoController:
    """
    基于 CursorRocker 代码复用的 Arduino 控制类。
    负责：液体奖励 (Pump)、TTL 打标 (Marker)。
    """
    def __init__(self, baudrate=115200):
        self.conn = None
        self._connect(baudrate)

    def _connect(self, baudrate):
        ports = list_ports.comports()
        for port in ports:
            # 根据你的描述，通常设备名包含 Arduino
            if port.manufacturer and "Arduino" in port.manufacturer:
                try:
                    self.conn = serial.Serial(port.device, baudrate, timeout=1)
                    time.sleep(2) # 等待复位
                    print(f"[Hardware] Arduino connected on {port.device}")
                    return
                except Exception as e:
                    print(f"[Hardware] Failed to connect Arduino: {e}")
        print("[Hardware] Warning: No Arduino found. Running in simulation mode.")

    def send_event_code(self,code):
        if self.conn and 0 <= code <= 127:
            self.conn.write(bytes([code]))
        #Usage: 

    def trial_start(self):
        self.send_event_code(1)

    def trial_end(self):
        self.send_event_code(2)

    def trial_success(self):
        self.send_event_code(3)
    
    def trial_nofix(self):
        self.send_event_code(4)
    
    def trial_break(self):
        self.send_event_code(5)
    
    def reward(self,duration_ms):
        """
        给予水奖励
        传输协议：[指令头 128] + [高位字节] + [低位字节]
        """
        if self.conn:
            high_byte = (duration_ms >> 8) & 0xFF
            low_byte = duration_ms & 0xFF

            payload = bytes([128,high_byte,low_byte])
            self.conn.write(payload)
    
    def drain(self, duration_ms=32767):
        """排水 (指令头 129)"""
        if self.conn:
            high_byte = (duration_ms >> 8) & 0xFF
            low_byte = duration_ms & 0xFF
            self.conn.write(bytes([129, high_byte, low_byte]))
            
    def stop_all(self):
        """紧急停止所有水泵 (指令头 130)"""
        if self.conn:
            self.conn.write(bytes([130]))

    def close(self):
        if self.conn:
            self.conn.close()


# %%
class SpikeGadgetsBridge:
    """
    SpikeGadgets 通信接口。
    """
    def __init__(self, is_simulating = 0, connection_name='source.spikes'):
        self.is_simulating = is_simulating
        self.connected = False
        self.subscriber = None
        if is_simulating == 0:
            self.connect(connection_name)

    def connect(self, connection_name):
        try:
            self.subscriber = socket.SourceSubscriber(connection_name)
            self.connected = True
            print("[Hardware] SpikeGadgets connected.")
        except Exception as e:
            print(f"[Hardware] SpikeGadgets connection failed: {e}")

    def get_latest_spike(self):
        # 这里预留接口，用于以后的数据储存。
        pass


