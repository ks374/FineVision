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

    def send_cmd(self, cmd):
        if self.conn:
            self.conn.write((cmd + "\n").encode())
            # 如果需要读取返回，可以在这里 readline，但在高频循环中可能会阻塞
            # return self.conn.readline().decode().strip()

    def reward(self, duration_ms):
        """给予水奖励"""
        self.send_cmd(f"PUMP:,{duration_ms}")

    def send_marker(self, code, duration=50):
        """发送 TTL Marker (1=Start, 2=End, etc.)"""
        self.send_cmd(f"MARKER:{code},{duration}")
    
    def pump(self,duration=14000):
        self.send_cmd(f"PUMP:,{duration}")
    
    def drain(self,duration=32767):
        self.send_cmd(f"DRAIN:,{duration}")

    def stop_all(self):
        self.send_cmd("STOP")
    
    #Note: No read_analog function for now. 

    def close(self):
        if self.conn:
            self.conn.close()


# %%
class SpikeGadgetsBridge:
    """
    SpikeGadgets 通信接口。
    """
    def __init__(self, connection_name='source.spikes', connect=True):
        self.connected = False
        self.subscriber = None
        if connect:
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


