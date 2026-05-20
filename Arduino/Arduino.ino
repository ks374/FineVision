// 定义你的水泵控制引脚
const int pumpVoltagePin = 5;  // PWM (调节速度，尚未实装，感觉用不到)
const int pumpEnablePin = 6;   // 开关引脚 (假设 LOW 打开，HIGH 关闭)
const int pumpDirPin = 7;      // 方向引脚
const int pumptap = 12;        // 脚踏开关输入引脚



// 非阻塞计时器变量
unsigned long pumpEndTime = 0;
bool isPumping = false;

// 🌟 新增：脚踏边沿检测变量
bool lastTapState = LOW;

void setup() {
  Serial.begin(115200);
  
  // 初始化水泵引脚
  pinMode(pumpVoltagePin, OUTPUT);
  pinMode(pumpEnablePin, OUTPUT);
  pinMode(pumpDirPin, OUTPUT);
  pinMode(pumptap, INPUT);      // 脚踏开关：输入模式

  
  // 默认关闭水泵 (假设 HIGH 为关)
  digitalWrite(pumpEnablePin, HIGH);
  analogWrite(pumpVoltagePin, 128); // 设置转速满
  digitalWrite(pumpDirPin, LOW);    // 正向
  
  // 🌟 核心：把 Arduino Uno 的 8, 9, 10, 11 引脚设为输出模式
  // 它们对应底层寄存器 PORTB 的最低 4 位。
  // 这几根线用来连到 SpikeGadgets 的 Digital IN！
  DDRB = DDRB | B00001111; 
  PORTB = PORTB & B11110000; // 初始电平全部拉低
}

void loop() {
  // 1. 极速读取串口数据
  if (Serial.available() > 0) {
    byte cmd = Serial.read();

    // =====================================
    // 极速通道 (TTL Markers)
    // =====================================
    if (cmd >= 0 && cmd <= 127) {
      // 一行代码，直接把这个数字投射到 8, 9, 10, 11 四根引脚上！
      // 耗时：62 纳秒！
      //Note: Will only use 1-7 as task event encoder. Value between 8 and 127 will be invalid. 
      PORTB = (PORTB & B11110000) | (cmd & B00000111);
      delayMicroseconds(1);
      PORTB |= B00001000;    //Note: Pin 11 for strobe control switch, 1 ms. 
      delayMicroseconds(1000);
      PORTB &= B11110111;
    }
    
    // =====================================
    // 参数通道 (Pump Control)
    // =====================================
    else if (cmd == 128) { // 128: Reward 正常给水
      // 等待后面跟着的 2 个字节的参数 (持续时间)
      while (Serial.available() < 3) { /* 死等几微秒 */ }
      byte highByte = Serial.read();
      byte lowByte = Serial.read();
      byte speed = Serial.read(); // 新增：读取转速 (0=0V, 255=5V)
      
      // 拼凑出我们要的毫秒数
      unsigned int duration = (highByte << 8) | lowByte;
      
      // 开启水泵 (非阻塞！)
      //analogWrite(pumpVoltagePin, speed); // 1. 设置转速 (0-5V)
      digitalWrite(pumpDirPin, LOW);      // 2. 顺时针 (正向)
      digitalWrite(pumpEnablePin, LOW);   // 3. 开启水泵
      pumpEndTime = millis() + duration;
      isPumping = true;
    }
    
    else if (cmd == 129) { // 129: Drain 排水
      while (Serial.available() < 3) {}
      byte high = Serial.read();
      byte low = Serial.read();
      byte speed = Serial.read(); // 读取转速
      unsigned int duration = (high << 8) | low;
      
      // 反向水泵
      //analogWrite(pumpVoltagePin, speed); // 1. 设置转速 (0-5V)
      digitalWrite(pumpDirPin, HIGH);     // 2. 逆时针 (反向)
      digitalWrite(pumpEnablePin, LOW);   // 3. 开启水泵
      pumpEndTime = millis() + duration;
      isPumping = true;
    }
    
    else if (cmd == 130) { // 130: 紧急停止
      digitalWrite(pumpEnablePin, HIGH);  // 关闭使能
      //analogWrite(pumpVoltagePin, 0);     // 建议停机时把电压也降到 0
      isPumping = false;
    }
  }

  // 2. 🌟 非阻塞检查：水泵是否到时间该关了？
  // 因为没有用 delay()，所以在这个检查期间，Arduino 可以随时回去接收 TTL 信号！
  if (isPumping && millis() >= pumpEndTime) {
    digitalWrite(pumpEnablePin, HIGH); // 关水泵
    //analogWrite(pumpVoltagePin, 0);    // 转速归零 (可选，更安全)
    digitalWrite(pumpDirPin, LOW);     // 恢复正向
    isPumping = false;
  }

  // 3. 🌟 脚踏开关：上升沿触发，单次出水 0.5s
  bool currentTapState = digitalRead(pumptap);
  if (currentTapState == HIGH && lastTapState == LOW) {
    if (!isPumping) {
      digitalWrite(pumpDirPin, LOW);
      digitalWrite(pumpEnablePin, LOW);
      //analogWrite(pumpVoltagePin, 255); // 全速
      pumpEndTime = millis() + 500;
      Serial.print("Pressed");
      isPumping = true;
    }
  }
  lastTapState = currentTapState;
} 

