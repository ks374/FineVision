from collections import deque
from psychopy import visual

class GazeTrackerRenderer:
    def __init__(self, win_ctl, shared_data, scale_x, scale_y):
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.scale_x = scale_x
        self.scale_y = scale_y
        
        # 把所有的视觉元素初始化都收纳在这里
        self.cursor = visual.Circle(win_ctl, radius=6, fillColor='yellow', opacity=0.8)
        self.tail_line = visual.ShapeStim(
            win_ctl, vertices=[(0,0),(0,0)], closeShape=False,
            lineWidth=2.0, lineColor='yellow', opacity=0.6
        )
        self.trail = deque(maxlen=60)

    def reset_trail(self):
        """每个 Trial 开始时调用，清空尾巴"""
        self.trail.clear()

    def update_and_draw(self):
        """在每一帧渲染前调用，自动获取数据并画上去"""
        gaze = self.shared_data.get_latest_cal()
        
        if gaze['valid']:
            # 计算缩放后的屏幕坐标
            gx = gaze['x'] * self.scale_x
            gy = gaze['y'] * self.scale_y
            
            # 更新尾巴
            self.trail.append((gx, gy))
            if len(self.trail) >= 2:
                self.tail_line.vertices = list(self.trail)
                self.tail_line.draw()
                
            # 画圆点头
            self.cursor.pos = (gx, gy)
            self.cursor.draw()
            
        return gaze # 顺便把这帧的数据返回给主程序做逻辑判定