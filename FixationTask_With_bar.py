import math
import os
import glob
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from psychopy import visual, core, event, gui, sound
from multiprocessing import Process
from collections import deque
import traceback
import pandas as pd
import json  # 新增：用于JSON保存

from eyetracker import create_tracker_runtime
from Json_manager import update_json, read_json
from FineVision_Notebook import FineVision_Notebook
from GazeTrackerRenderer import GazeTrackerRenderer
from FineVision_Util import ArduinoController


# ==========================================
# 0. 文件保存工具函数
# ==========================================
def get_unique_filename(base_name, extension=".csv", sub_dir=None):
    """
    生成不重复的文件名：如果文件已存在，自动添加编号
    时间戳精确到秒，确保每次实验文件名唯一
    例如：Fixation_task_log_20250608_163052.csv
          Fixation_task_log_20250608_163052_001.csv（如果冲突）
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 如果指定了子目录，创建它
    if sub_dir is not None:
        os.makedirs(sub_dir, exist_ok=True)
        base_path = os.path.join(sub_dir, f"{base_name}_{timestamp}")
    else:
        base_path = f"{base_name}_{timestamp}"

    candidate = f"{base_path}{extension}"

    # 如果同一秒内多次保存（极罕见），添加编号
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{base_path}_{counter:03d}{extension}"
        counter += 1

    return candidate


# ==========================================
# 1. Bar 刺激类 (BarStimulus)
# ==========================================
class BarStimulus:
    """
    支持：
      - 单一位置 / 序列位置（8 个外围点循环）
      - RGB 颜色
      - 对称闪烁（沿水平中线镜像）
      - 自定义闪烁周期
    """

    # 3×3 网格的 8 个外围位置（1920×1080，中心原点，单位：像素）
    SEQUENCE_POSITIONS = [
        (-640, 360),   # 0: 左上
        (0, 360),      # 1: 中上
        (640, 360),    # 2: 右上
        (-640, 0),     # 3: 左中
        (640, 0),      # 4: 右中
        (-640, -360),  # 5: 左下
        (0, -360),     # 6: 中下
        (640, -360),   # 7: 右下
    ]

    def __init__(self, win_sub, win_ctl, scale_x, scale_y):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.scale_x = scale_x
        self.scale_y = scale_y

        # ---------- 默认参数 ----------
        self.enabled        = True
        self.color_r        = 255
        self.color_g        = 0
        self.color_b        = 0
        self.width          = 120
        self.height         = 40
        self.shape          = 'Rectangle'
        self.pos_x          = 300
        self.pos_y          = 0

        self.flicker_on     = False
        self.flicker_interval = 0.5
        self.flicker_duration = 0.3

        self.rotation       = 0.0   # 旋转角度（度，顺时针）

        self.mode           = 'single'      # 'single' | 'sequence'
        self.symmetric_flicker = False
        self.sequence_start_idx = 0
        self.sequence_dwell_time = 1.0
        self.sequence_interval   = 0.5

        # 内部状态
        self._flicker_clock   = core.Clock()
        self._flicker_visible = True
        self._paused          = False

        self._sequence_clock  = core.Clock()
        self._sequence_idx    = 0
        self._sequence_showing = True

        self._build_stimuli()

    # ------------------------------------------------------------------
    def _create_stim_pair(self, color, pos=(0, 0)):
        """创建一对 (sub, ctl) 刺激，位置随后动态更新"""
        w_s = self.width
        h_s = self.height
        w_c = self.width * self.scale_x
        h_c = self.height * self.scale_y

        if self.shape == 'Ellipse':
            # 用多边形近似椭圆，避免 visual.Circle 的 radius 覆盖 size 导致充满窗口
            import math as _math
            n_pts = 64
            verts_s = [(_math.cos(2 * _math.pi * i / n_pts) * w_s / 2,
                        _math.sin(2 * _math.pi * i / n_pts) * h_s / 2)
                       for i in range(n_pts)]
            verts_c = [(_math.cos(2 * _math.pi * i / n_pts) * w_c / 2,
                        _math.sin(2 * _math.pi * i / n_pts) * h_c / 2)
                       for i in range(n_pts)]
            s_sub = visual.ShapeStim(
                self.win_sub, vertices=verts_s,
                fillColor=color, lineColor=color, pos=pos, closeShape=True,
                ori=self.rotation)
            s_ctl = visual.ShapeStim(
                self.win_ctl, vertices=verts_c,
                fillColor=color, lineColor=color, pos=pos, closeShape=True,
                ori=self.rotation)
        elif self.shape == 'Triangle':
            verts_s = [(0, h_s / 2), (-w_s / 2, -h_s / 2), (w_s / 2, -h_s / 2)]
            verts_c = [(0, h_c / 2), (-w_c / 2, -h_c / 2), (w_c / 2, -h_c / 2)]
            s_sub = visual.ShapeStim(
                self.win_sub, vertices=verts_s,
                fillColor=color, lineColor=color, pos=pos, closeShape=True,
                ori=self.rotation)
            s_ctl = visual.ShapeStim(
                self.win_ctl, vertices=verts_c,
                fillColor=color, lineColor=color, pos=pos, closeShape=True,
                ori=self.rotation)
        else:  # Rectangle
            s_sub = visual.Rect(
                self.win_sub, width=w_s, height=h_s,
                fillColor=color, lineColor=color, pos=pos,
                ori=self.rotation)
            s_ctl = visual.Rect(
                self.win_ctl, width=w_c, height=h_c,
                fillColor=color, lineColor=color, pos=pos,
                ori=self.rotation)
        return s_sub, s_ctl

    def _build_stimuli(self):
        # PsychoPy 默认 colorSpace='rgb'，范围 [-1, 1]；需将 0-255 映射到 -1~1
        c = [self.color_r / 127.5 - 1.0,
             self.color_g / 127.5 - 1.0,
             self.color_b / 127.5 - 1.0]
        self.stim_sub, self.stim_ctl = self._create_stim_pair(c)
        if self.symmetric_flicker:
            self.stim_sub_sym, self.stim_ctl_sym = self._create_stim_pair(c)
        else:
            self.stim_sub_sym = None
            self.stim_ctl_sym = None

    # ------------------------------------------------------------------
    def apply_params(self, params: dict):
        self.enabled           = params.get('bar_enabled',          self.enabled)
        self.color_r           = params.get('bar_color_r',        self.color_r)
        self.color_g           = params.get('bar_color_g',        self.color_g)
        self.color_b           = params.get('bar_color_b',        self.color_b)
        self.width             = params.get('bar_width',          self.width)
        self.height            = params.get('bar_height',         self.height)
        self.shape             = params.get('bar_shape',          self.shape)
        self.pos_x             = params.get('bar_pos_x',          self.pos_x)
        self.pos_y             = params.get('bar_pos_y',          self.pos_y)

        self.flicker_on        = params.get('bar_flicker_on',     self.flicker_on)
        self.flicker_interval  = params.get('bar_flicker_interval', self.flicker_interval)
        self.flicker_duration  = params.get('bar_flicker_duration', self.flicker_duration)

        self.rotation          = params.get('bar_rotation',       self.rotation)

        self.mode              = params.get('bar_mode',           self.mode)
        self.symmetric_flicker = params.get('bar_symmetric_flicker', self.symmetric_flicker)
        self.sequence_start_idx    = params.get('bar_sequence_start_idx',    self.sequence_start_idx)
        self.sequence_dwell_time   = params.get('bar_sequence_dwell_time',   self.sequence_dwell_time)
        self.sequence_interval     = params.get('bar_sequence_interval',     self.sequence_interval)

        self._build_stimuli()
        self._flicker_clock.reset()
        self._flicker_visible = True
        self._sequence_clock.reset()
        self._sequence_idx    = self.sequence_start_idx
        self._sequence_showing = True

    # ------------------------------------------------------------------
    def pause(self):
        self._paused = True
        self._flicker_visible = False

    def resume(self):
        self._paused = False
        self._flicker_clock.reset()
        self._sequence_clock.reset()
        self._sequence_idx    = self.sequence_start_idx
        self._sequence_showing = True
        self._flicker_visible = True

    # ------------------------------------------------------------------
    def draw_frame(self):
        """在 win.flip() 之前调用，自动处理 sequence / flicker / symmetric 逻辑"""
        if not self.enabled or self._paused:
            return

        # ---- 闪烁逻辑 ----
        if self.flicker_on:
            t = self._flicker_clock.getTime() % self.flicker_interval
            self._flicker_visible = (t < self.flicker_duration)
        else:
            self._flicker_visible = True

        if not self._flicker_visible:
            return

        # ---- 位置逻辑 ----
        if self.mode == 'sequence':
            cycle = self.sequence_dwell_time + self.sequence_interval
            t_seq = self._sequence_clock.getTime() % cycle
            self._sequence_showing = (t_seq < self.sequence_dwell_time)

            period = int(self._sequence_clock.getTime() // cycle)
            self._sequence_idx = (self.sequence_start_idx + period) % 8
            x, y = self.SEQUENCE_POSITIONS[self._sequence_idx]
        else:
            x, y = self.pos_x, self.pos_y
            self._sequence_showing = True

        if not self._sequence_showing:
            return

        # ---- 绘制主 Bar ----
        self.stim_sub.pos = (x, y)
        self.stim_ctl.pos = (x * self.scale_x, y * self.scale_y)
        self.stim_sub.draw()
        self.stim_ctl.draw()

        # ---- 绘制对称 Bar（水平轴镜像） ----
        if self.symmetric_flicker:
            x_sym, y_sym = x, -y
            self.stim_sub_sym.pos = (x_sym, y_sym)
            self.stim_ctl_sym.pos = (x_sym * self.scale_x, y_sym * self.scale_y)
            self.stim_sub_sym.draw()
            self.stim_ctl_sym.draw()


# ==========================================
# 2. 统一参数面板 (UnifiedParamDialog)
#    上方 Fixation 可编辑（数字输入模式） + 下方 Bar 可编辑（含实时示意图）
#    右侧带竖向滚动条
# ==========================================
class UnifiedParamDialog:
    SCREEN_W = 1920
    SCREEN_H = 1080
    CANVAS_W = 400
    CANVAS_H = 225

    def __init__(self, current_fix_params: dict, current_bar_params: dict):
        self.fix_params = current_fix_params.copy()
        self.bar_params = current_bar_params.copy()
        self.result = None
        self.cancelled = False
        self._dragging = False

    # ------------------------------------------------------------------
    def show(self):
        root = tk.Tk()
        root.title("FineVision Experiment — 统一参数配置")
        root.resizable(False, False)
        self.root = root

        FONT_HEADER = ('Helvetica', 11, 'bold')
        FONT_LABEL  = ('Helvetica', 10)

        # ── 滚动容器 ──
        main_canvas = tk.Canvas(root, width=880, height=700)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=main_canvas.yview)
        scrollable_frame = tk.Frame(main_canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )

        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)

        # 鼠标滚轮支持
        def _on_mousewheel(event):
            main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        main_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ── 顶部标题 ──
        tk.Label(scrollable_frame, text="FineVision Experiment Notebook",
                 font=('Helvetica', 13, 'bold')).pack(pady=(10, 2))
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', padx=8)

        # ═══════════════════════════════════════════════════════════
        # 上区：Fixation 参数（数字输入模式，保持原风格）
        # ═══════════════════════════════════════════════════════════
        fix_frame = tk.LabelFrame(scrollable_frame, text=" ▶ Fixation Task Parameters",
                                  font=FONT_HEADER, fg='#2060a0', padx=8, pady=6)
        fix_frame.pack(fill='x', padx=12, pady=6)

        self.fix_vars = {}

        def make_fix_entry(row, label, key, width=10):
            tk.Label(fix_frame, text=label + ':', font=FONT_LABEL,
                     anchor='w', width=26).grid(row=row, column=0, sticky='w', pady=3)
            val = self.fix_params.get(key, '')
            var = tk.StringVar(value=str(val))
            self.fix_vars[key] = var
            tk.Entry(fix_frame, textvariable=var, width=width,
                     font=FONT_LABEL).grid(row=row, column=1, sticky='w', padx=4)

        make_fix_entry(0, 'Subject ID',             'Subject ID',             20)
        make_fix_entry(1, 'Wait Time (s)',           'Wait Time (s)')
        make_fix_entry(2, 'Stim Duration (s)',       'Stim Duration (s)')
        make_fix_entry(3, 'Fix Window Radius (pix)', 'Fix Window Radius (pix)')
        make_fix_entry(4, 'Reward Length (s)',       'Reward Length (s)')
        make_fix_entry(5, 'ITI (s)',                 'ITI (s)')
        make_fix_entry(6, 'Timeout (s)',             'Timeout (s)')

        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', padx=8, pady=4)

        # ═══════════════════════════════════════════════════════════
        # 下区：Bar 参数（可编辑 + 示意图）
        # ═══════════════════════════════════════════════════════════
        bar_frame = tk.LabelFrame(scrollable_frame, text=" ▶ Bar Stimulus Parameters",
                                  font=FONT_HEADER, fg='#a04020', padx=8, pady=6)
        bar_frame.pack(fill='both', expand=True, padx=12, pady=6)

        # ── 左侧：Canvas 示意图 ──
        left_frame = tk.Frame(bar_frame)
        left_frame.grid(row=0, column=0, rowspan=30, padx=5, pady=5, sticky='n')

        self.canvas = tk.Canvas(left_frame, width=self.CANVAS_W, height=self.CANVAS_H,
                                bg='black', highlightthickness=2, highlightbackground='#555')
        self.canvas.pack()
        tk.Label(left_frame, text='提示：可直接拖动示意图中的 Bar 调整位置',
                 font=('Helvetica', 8), fg='gray').pack(pady=(2, 0))

        self.canvas.bind('<Button-1>',       self._on_canvas_click)
        self.canvas.bind('<B1-Motion>',       self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)

        # ── 右侧：控制面板 ──
        right_frame = tk.Frame(bar_frame)
        right_frame.grid(row=0, column=1, sticky='n', padx=8)

        # 1) 启用 Bar
        self.enabled_var = tk.BooleanVar(value=self.bar_params.get('bar_enabled', True))
        tk.Label(right_frame, text='Enable Bar:', font=FONT_LABEL,
                 anchor='w', width=18).grid(row=0, column=0, sticky='w')
        tk.Checkbutton(right_frame, variable=self.enabled_var,
                       command=self._update_preview).grid(row=0, column=1, sticky='w')

        # 2) RGB 颜色
        color_frame = tk.LabelFrame(right_frame, text="Color (RGB 0-255)",
                                    font=FONT_LABEL, padx=4, pady=4)
        color_frame.grid(row=1, column=0, columnspan=3, sticky='ew', pady=4)

        self.r_var = tk.IntVar(value=self.bar_params.get('bar_color_r', 255))
        self.g_var = tk.IntVar(value=self.bar_params.get('bar_color_g', 0))
        self.b_var = tk.IntVar(value=self.bar_params.get('bar_color_b', 0))

        for i, (label, var) in enumerate([('R', self.r_var), ('G', self.g_var), ('B', self.b_var)]):
            tk.Label(color_frame, text=label, font=FONT_LABEL, width=3).grid(row=i, column=0)
            sc = tk.Scale(color_frame, from_=0, to=255, variable=var,
                          orient='horizontal', length=140)
            sc.grid(row=i, column=1, sticky='ew')
            sp = tk.Spinbox(color_frame, from_=0, to=255, textvariable=var,
                            width=5, command=lambda: root.after_idle(self._update_preview))
            sp.grid(row=i, column=2, padx=2)
            sp.bind('<Return>',   lambda e: root.after_idle(self._update_preview))
            sp.bind('<FocusOut>', lambda e: root.after_idle(self._update_preview))

        # 颜色变量变化时实时刷新预览（after_idle 确保 IntVar 已更新）
        for _var in (self.r_var, self.g_var, self.b_var):
            _var.trace_add('write', lambda *a: root.after_idle(self._update_preview))

        # 3) 形状 & 尺寸
        tk.Label(right_frame, text='Shape:', font=FONT_LABEL,
                 anchor='w', width=18).grid(row=2, column=0, sticky='w')
        self.shape_var = tk.StringVar(value=self.bar_params.get('bar_shape', 'Rectangle'))
        ttk.Combobox(right_frame, textvariable=self.shape_var,
                     values=['Rectangle', 'Ellipse', 'Triangle'],
                     state='readonly', width=12).grid(row=2, column=1, sticky='w')
        self.shape_var.trace('w', lambda *args: self._update_preview())

        self.width_var  = tk.IntVar(value=self.bar_params.get('bar_width', 120))
        self.height_var = tk.IntVar(value=self.bar_params.get('bar_height', 40))

        tk.Label(right_frame, text='Width (pix):', font=FONT_LABEL,
                 anchor='w', width=18).grid(row=3, column=0, sticky='w')
        tk.Scale(right_frame, from_=10, to=600, variable=self.width_var,
                 orient='horizontal', length=140,
                 command=lambda v: self._update_preview()).grid(row=3, column=1, sticky='ew')
        tk.Spinbox(right_frame, from_=10, to=600, textvariable=self.width_var,
                   width=5, command=lambda: self._update_preview()).grid(row=3, column=2)

        tk.Label(right_frame, text='Height (pix):', font=FONT_LABEL,
                 anchor='w', width=18).grid(row=4, column=0, sticky='w')
        tk.Scale(right_frame, from_=10, to=400, variable=self.height_var,
                 orient='horizontal', length=140,
                 command=lambda v: self._update_preview()).grid(row=4, column=1, sticky='ew')
        tk.Spinbox(right_frame, from_=10, to=400, textvariable=self.height_var,
                   width=5, command=lambda: self._update_preview()).grid(row=4, column=2)

        # 4) 位置 X / Y（与 Canvas 联动）
        pos_frame = tk.LabelFrame(right_frame, text="Position (center origin, pix)",
                                  font=FONT_LABEL, padx=4, pady=4)
        pos_frame.grid(row=5, column=0, columnspan=3, sticky='ew', pady=4)

        self.pos_x_var = tk.IntVar(value=self.bar_params.get('bar_pos_x', 300))
        self.pos_y_var = tk.IntVar(value=self.bar_params.get('bar_pos_y', 0))

        tk.Label(pos_frame, text='X:', font=FONT_LABEL).grid(row=0, column=0)
        tk.Scale(pos_frame, from_=-960, to=960, variable=self.pos_x_var,
                 orient='horizontal', length=120,
                 command=lambda v: self._update_preview()).grid(row=0, column=1, sticky='ew')
        tk.Spinbox(pos_frame, from_=-960, to=960, textvariable=self.pos_x_var,
                   width=6, command=lambda: self._update_preview()).grid(row=0, column=2, padx=2)

        tk.Label(pos_frame, text='Y:', font=FONT_LABEL).grid(row=1, column=0)
        tk.Scale(pos_frame, from_=540, to=-540, variable=self.pos_y_var,
                 orient='horizontal', length=120,
                 command=lambda v: self._update_preview()).grid(row=1, column=1, sticky='ew')
        tk.Spinbox(pos_frame, from_=-540, to=540, textvariable=self.pos_y_var,
                   width=6, command=lambda: self._update_preview()).grid(row=1, column=2, padx=2)

        self.pos_x_var.trace('w', lambda *args: self._update_preview())
        self.pos_y_var.trace('w', lambda *args: self._update_preview())

        # 5) 模式选择
        mode_frame = tk.LabelFrame(right_frame, text="Display Mode",
                                   font=FONT_LABEL, padx=4, pady=4)
        mode_frame.grid(row=6, column=0, columnspan=3, sticky='ew', pady=4)

        self.mode_var = tk.StringVar(value=self.bar_params.get('bar_mode', 'single'))
        tk.Radiobutton(mode_frame, text='A. Single Position (Repeat)',
                       variable=self.mode_var, value='single',
                       command=self._on_mode_change).grid(row=0, column=0, sticky='w')
        tk.Radiobutton(mode_frame, text='B. Sequence (8 positions cycle)',
                       variable=self.mode_var, value='sequence',
                       command=self._on_mode_change).grid(row=1, column=0, sticky='w')

        # Single 选项
        self.single_opts = tk.Frame(mode_frame)
        self.single_opts.grid(row=0, column=1, rowspan=2, sticky='w', padx=10)
        self.symm_var = tk.BooleanVar(value=self.bar_params.get('bar_symmetric_flicker', False))
        tk.Checkbutton(self.single_opts, text='Symmetric Flicker (mirror on X-axis)',
                       variable=self.symm_var,
                       command=self._update_preview).pack(anchor='w')

        # Sequence 选项
        self.seq_opts = tk.LabelFrame(right_frame, text="Sequence Settings",
                                      font=FONT_LABEL, padx=4, pady=4)
        self.seq_opts.grid(row=7, column=0, columnspan=3, sticky='ew', pady=4)

        tk.Label(self.seq_opts, text='Start Position:', font=FONT_LABEL).grid(
            row=0, column=0, sticky='w', columnspan=3)

        self.seq_start_var = tk.IntVar(value=self.bar_params.get('bar_sequence_start_idx', 0))
        self.seq_buttons = []
        pos_names = ['左上', '中上', '右上', '左中', '右中', '左下', '中下', '右下']
        pos_grid  = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1), (2, 2)]
        for idx, (r, c) in enumerate(pos_grid):
            btn = tk.Button(self.seq_opts, text=pos_names[idx], width=6,
                            command=lambda i=idx: self._set_seq_start(i))
            btn.grid(row=r + 1, column=c, padx=1, pady=1)
            self.seq_buttons.append(btn)
        tk.Label(self.seq_opts, text='●', font=('Helvetica', 10), fg='green').grid(row=2, column=1)

        tk.Label(self.seq_opts, text='Dwell Time (s):', font=FONT_LABEL).grid(
            row=4, column=0, sticky='w', columnspan=2)
        self.seq_dwell_var = tk.DoubleVar(value=self.bar_params.get('bar_sequence_dwell_time', 1.0))
        tk.Scale(self.seq_opts, from_=0.1, to=5.0, variable=self.seq_dwell_var,
                 orient='horizontal', length=140, resolution=0.1).grid(row=4, column=2, sticky='ew')

        tk.Label(self.seq_opts, text='Interval (s):', font=FONT_LABEL).grid(
            row=5, column=0, sticky='w', columnspan=2)
        self.seq_interval_var = tk.DoubleVar(value=self.bar_params.get('bar_sequence_interval', 0.5))
        tk.Scale(self.seq_opts, from_=0.0, to=3.0, variable=self.seq_interval_var,
                 orient='horizontal', length=140, resolution=0.1).grid(row=5, column=2, sticky='ew')

        # 6) 闪烁参数
        flicker_frame = tk.LabelFrame(right_frame, text="Flicker",
                                      font=FONT_LABEL, padx=4, pady=4)
        flicker_frame.grid(row=8, column=0, columnspan=3, sticky='ew', pady=4)

        self.flicker_var = tk.BooleanVar(value=self.bar_params.get('bar_flicker_on', False))
        tk.Checkbutton(flicker_frame, text='Enable Flicker', variable=self.flicker_var).grid(
            row=0, column=0, sticky='w')

        tk.Label(flicker_frame, text='Cycle (s):', font=FONT_LABEL).grid(row=1, column=0, sticky='w')
        self.flicker_interval_var = tk.DoubleVar(value=self.bar_params.get('bar_flicker_interval', 0.5))
        tk.Scale(flicker_frame, from_=0.05, to=3.0, variable=self.flicker_interval_var,
                 orient='horizontal', length=120, resolution=0.05).grid(row=1, column=1, sticky='ew')

        tk.Label(flicker_frame, text='ON duration (s):', font=FONT_LABEL).grid(row=2, column=0, sticky='w')
        self.flicker_duration_var = tk.DoubleVar(value=self.bar_params.get('bar_flicker_duration', 0.3))
        tk.Scale(flicker_frame, from_=0.02, to=3.0, variable=self.flicker_duration_var,
                 orient='horizontal', length=120, resolution=0.02).grid(row=2, column=1, sticky='ew')

        # 7) 旋转角度
        rotation_frame = tk.LabelFrame(right_frame, text="Rotation (degrees)",
                                       font=FONT_LABEL, padx=4, pady=4)
        rotation_frame.grid(row=9, column=0, columnspan=3, sticky='ew', pady=4)

        self.rotation_var = tk.DoubleVar(value=self.bar_params.get('bar_rotation', 0.0))
        tk.Label(rotation_frame, text='Angle (°):', font=FONT_LABEL).grid(row=0, column=0, sticky='w')
        rot_scale = tk.Scale(rotation_frame, from_=0, to=360, variable=self.rotation_var,
                             orient='horizontal', length=140, resolution=1.0)
        rot_scale.grid(row=0, column=1, sticky='ew')
        tk.Spinbox(rotation_frame, from_=0, to=360, textvariable=self.rotation_var,
                   width=6, command=lambda: root.after_idle(self._update_preview)).grid(
                       row=0, column=2, padx=2)
        self.rotation_var.trace_add('write', lambda *a: root.after_idle(self._update_preview))

        # 初始化
        self._set_seq_start(self.seq_start_var.get())
        self._on_mode_change()

        # 确认 / 取消 按钮
        btn_frame = tk.Frame(scrollable_frame)
        btn_frame.pack(pady=(4, 10))
        tk.Button(btn_frame, text=' ✔ Confirm & Apply ',
                  font=('Helvetica', 11, 'bold'),
                  bg='#2060a0', fg='white',
                  command=self._on_confirm).pack(side='left', padx=8)
        tk.Button(btn_frame, text=' ✖ Cancel ',
                  font=('Helvetica', 11, 'bold'),
                  bg='#c0392b', fg='white',
                  command=self._on_cancel).pack(side='left', padx=8)

        self._update_preview()
        root.mainloop()

        if self.result is None:
            # 窗口被直接关闭（等同 cancel）
            self.cancelled = True
            self.result = (self.fix_params, self.bar_params)

        return self.cancelled, self.result[0], self.result[1]

    # ------------------------------------------------------------------
    def _set_seq_start(self, idx):
        self.seq_start_var.set(idx)
        for i, btn in enumerate(self.seq_buttons):
            if i == idx:
                btn.config(relief='sunken', bg='#a0d0ff')
            else:
                btn.config(relief='raised', bg='#f0f0f0')
        self._update_preview()

    def _on_mode_change(self):
        if self.mode_var.get() == 'single':
            self.single_opts.grid()
            self.seq_opts.grid_remove()
        else:
            self.single_opts.grid_remove()
            self.seq_opts.grid()
        self._update_preview()

    def _on_confirm(self):
        new_fix = {}
        for k, v in self.fix_vars.items():
            new_fix[k] = v.get() if hasattr(v, 'get') else v

        # 类型修正
        for k in ['Wait Time (s)', 'Stim Duration (s)', 'Reward Length (s)',
                  'ITI (s)', 'Timeout (s)']:
            try:
                new_fix[k] = float(new_fix[k])
            except ValueError:
                new_fix[k] = self.fix_params.get(k, 0.0)
        try:
            new_fix['Fix Window Radius (pix)'] = int(new_fix['Fix Window Radius (pix)'])
        except ValueError:
            new_fix['Fix Window Radius (pix)'] = self.fix_params.get('Fix Window Radius (pix)', 100)

        new_bar = {
            'bar_enabled':          self.enabled_var.get(),
            'bar_color_r':          self.r_var.get(),
            'bar_color_g':          self.g_var.get(),
            'bar_color_b':          self.b_var.get(),
            'bar_shape':            self.shape_var.get(),
            'bar_width':            self.width_var.get(),
            'bar_height':           self.height_var.get(),
            'bar_pos_x':            self.pos_x_var.get(),
            'bar_pos_y':            self.pos_y_var.get(),
            'bar_mode':             self.mode_var.get(),
            'bar_symmetric_flicker': self.symm_var.get(),
            'bar_sequence_start_idx':    self.seq_start_var.get(),
            'bar_sequence_dwell_time':   round(self.seq_dwell_var.get(), 2),
            'bar_sequence_interval':     round(self.seq_interval_var.get(), 2),
            'bar_flicker_on':       self.flicker_var.get(),
            'bar_flicker_interval': round(self.flicker_interval_var.get(), 3),
            'bar_flicker_duration': round(self.flicker_duration_var.get(), 3),
            'bar_rotation':         round(self.rotation_var.get(), 1),
        }
        self.result = (new_fix, new_bar)
        self.root.destroy()

    def _on_cancel(self):
        """取消：标记 cancelled，保存参数到JSON，关闭面板，调用方检测后退出任务"""
        self.cancelled = True

        # ========== 修改：Cancel时保存参数到JSON（使用唯一文件名） ==========
        # 收集当前Fixation参数
        cancel_fix = {}
        for k, v in self.fix_vars.items():
            cancel_fix[k] = v.get() if hasattr(v, 'get') else v

        # 类型修正（与confirm一致）
        for k in ['Wait Time (s)', 'Stim Duration (s)', 'Reward Length (s)',
                  'ITI (s)', 'Timeout (s)']:
            try:
                cancel_fix[k] = float(cancel_fix[k])
            except ValueError:
                cancel_fix[k] = self.fix_params.get(k, 0.0)
        try:
            cancel_fix['Fix Window Radius (pix)'] = int(cancel_fix['Fix Window Radius (pix)'])
        except ValueError:
            cancel_fix['Fix Window Radius (pix)'] = self.fix_params.get('Fix Window Radius (pix)', 100)

        # 收集当前Bar参数
        cancel_bar = {
            'bar_enabled':          self.enabled_var.get(),
            'bar_color_r':          self.r_var.get(),
            'bar_color_g':          self.g_var.get(),
            'bar_color_b':          self.b_var.get(),
            'bar_shape':            self.shape_var.get(),
            'bar_width':            self.width_var.get(),
            'bar_height':           self.height_var.get(),
            'bar_pos_x':            self.pos_x_var.get(),
            'bar_pos_y':            self.pos_y_var.get(),
            'bar_mode':             self.mode_var.get(),
            'bar_symmetric_flicker': self.symm_var.get(),
            'bar_sequence_start_idx':    self.seq_start_var.get(),
            'bar_sequence_dwell_time':   round(self.seq_dwell_var.get(), 2),
            'bar_sequence_interval':     round(self.seq_interval_var.get(), 2),
            'bar_flicker_on':       self.flicker_var.get(),
            'bar_flicker_interval': round(self.flicker_interval_var.get(), 3),
            'bar_flicker_duration': round(self.flicker_duration_var.get(), 3),
            'bar_rotation':         round(self.rotation_var.get(), 1),
        }

        # 合并为统一字典
        cancel_params = {
            'fixation_params': cancel_fix,
            'bar_params': cancel_bar,
            'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'status': 'cancelled'
        }

        # 保存到同一文件夹（与脚本同目录），使用唯一文件名
        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_filename = get_unique_filename("cancelled_params", ".json", sub_dir=script_dir)

        try:
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(cancel_params, f, ensure_ascii=False, indent=2)
            print(f"\n[Cancel] 参数已保存到: {json_filename}")
        except Exception as e:
            print(f"\n[Warning] 保存取消参数失败: {e}")
        # ========== 修改结束 ==========

        self.result = (self.fix_params, self.bar_params)
        self.root.destroy()

    # ------------------------------------------------------------------
    def _psycho_to_canvas(self, px, py):
        s = min(self.CANVAS_W / self.SCREEN_W, self.CANVAS_H / self.SCREEN_H)
        cx = self.CANVAS_W / 2 + px * s
        cy = self.CANVAS_H / 2 - py * s
        return cx, cy, s

    def _canvas_to_psycho(self, cx, cy):
        s = min(self.CANVAS_W / self.SCREEN_W, self.CANVAS_H / self.SCREEN_H)
        px = (cx - self.CANVAS_W / 2) / s
        py = (self.CANVAS_H / 2 - cy) / s
        return px, py

    def _on_canvas_click(self, event):
        items = self.canvas.find_overlapping(event.x - 5, event.y - 5,
                                            event.x + 5, event.y + 5)
        for item in items:
            if 'bar' in self.canvas.gettags(item):
                self._dragging = True
                break

    def _on_canvas_drag(self, event):
        if not self._dragging:
            return
        px, py = self._canvas_to_psycho(event.x, event.y)
        px = max(-960, min(960, int(px)))
        py = max(-540, min(540, int(py)))
        self.pos_x_var.set(px)
        self.pos_y_var.set(py)

    def _on_canvas_release(self, event):
        self._dragging = False

    # ------------------------------------------------------------------
    def _draw_bar_on_canvas(self, cx, cy, bw, bh, shape, color, tag):
        import math as _math
        _, _, s = self._psycho_to_canvas(0, 0)
        w = bw * s
        h = bh * s
        angle_deg = self.rotation_var.get() if hasattr(self, 'rotation_var') else 0.0
        angle_rad = _math.radians(-angle_deg)  # tkinter Y轴向下，取反

        def _rotate(pts):
            result = []
            for dx, dy in pts:
                rx = dx * _math.cos(angle_rad) - dy * _math.sin(angle_rad)
                ry = dx * _math.sin(angle_rad) + dy * _math.cos(angle_rad)
                result.extend([cx + rx, cy + ry])
            return result

        if shape == 'Rectangle':
            corners = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            pts = _rotate(corners)
            self.canvas.create_polygon(pts, fill=color, outline=color, tags=tag)
        elif shape == 'Ellipse':
            n = 48
            pts = _rotate([(_math.cos(2*_math.pi*i/n)*w/2,
                             _math.sin(2*_math.pi*i/n)*h/2) for i in range(n)])
            self.canvas.create_polygon(pts, fill=color, outline=color, tags=tag)
        else:  # Triangle
            corners = [(0, -h/2), (-w/2, h/2), (w/2, h/2)]
            pts = _rotate(corners)
            self.canvas.create_polygon(pts, fill=color, outline=color, tags=tag)

    def _update_preview(self):
        self.canvas.delete('all')

        # 屏幕外框
        s = min(self.CANVAS_W / self.SCREEN_W, self.CANVAS_H / self.SCREEN_H)
        w = self.SCREEN_W * s
        h = self.SCREEN_H * s
        ox = (self.CANVAS_W - w) / 2
        oy = (self.CANVAS_H - h) / 2
        self.canvas.create_rectangle(ox, oy, ox + w, oy + h,
                                     outline='#333', width=1)

        # Fixation 中心点（绿色）
        cx, cy, _ = self._psycho_to_canvas(0, 0)
        r_fix = max(3, int(15 * s))
        self.canvas.create_oval(cx - r_fix, cy - r_fix,
                                cx + r_fix, cy + r_fix,
                                fill='green', outline='green', tags='fix')

        if not self.enabled_var.get():
            return

        # 颜色 / 尺寸 / 形状
        color = f'#{self.r_var.get():02x}{self.g_var.get():02x}{self.b_var.get():02x}'
        shape = self.shape_var.get()
        bw = self.width_var.get()
        bh = self.height_var.get()

        if self.mode_var.get() == 'sequence':
            # 显示 8 个位置小标记，高亮起始位置并绘制实际 Bar
            for idx, (px, py) in enumerate(BarStimulus.SEQUENCE_POSITIONS):
                x, y, _ = self._psycho_to_canvas(px, py)
                is_start = (idx == self.seq_start_var.get())
                size = 8 if is_start else 4
                c = color if is_start else '#555'
                self.canvas.create_rectangle(x - size, y - size,
                                             x + size, y + size,
                                             fill=c, tags='seq_mark')
                if is_start:
                    self._draw_bar_on_canvas(x, y, bw, bh, shape, color, 'bar')
        else:
            # Single 模式：当前 XY
            px, py = self.pos_x_var.get(), self.pos_y_var.get()
            x, y, _ = self._psycho_to_canvas(px, py)
            self._draw_bar_on_canvas(x, y, bw, bh, shape, color, 'bar')

            # 对称闪烁预览
            if self.symm_var.get():
                x_sym, y_sym, _ = self._psycho_to_canvas(px, -py)
                self._draw_bar_on_canvas(x_sym, y_sym, bw, bh, shape, color, 'bar_sym')
                self.canvas.create_line(x, y + bh * s / 2,
                                        x_sym, y_sym - bh * s / 2,
                                        dash=(4, 2), fill='#888')


# ==========================================
# 3. 核心任务类 (FixationTask)
# ==========================================
class FixationTask:
    def __init__(self, win_sub, win_ctl, shared_data, task_manager, is_simulating):
        self.win_sub = win_sub
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.task_manager = task_manager
        self.is_simulating = is_simulating

        self.arduino = ArduinoController()

        self.scale_x = win_ctl.size[0] / win_sub.size[0]
        self.scale_y = win_ctl.size[1] / win_sub.size[1]

        # ========== 鼠标模拟模式：用鼠标替代眼动仪 ==========
        self.use_mouse_gaze = bool(self.is_simulating)  # 设为 True 启用鼠标模拟gaze
        if self.use_mouse_gaze:
            from psychopy import event as pyevent
            self.mouse = pyevent.Mouse(win=self.win_sub)
            print("[MouseGaze] 鼠标模拟gaze模式已启用，鼠标位置将作为gaze点。")
        else:
            self.gaze_renderer = GazeTrackerRenderer(
                self.win_ctl, self.shared_data,
                self.scale_x, self.scale_y, self.is_simulating)
            self.mouse = None
        # ========== 鼠标模拟模式结束 ==========

        # --- 视觉刺激 ---
        self.stim_fix_point = visual.Circle(
            win_sub, radius=15, fillColor='green', lineColor='green', pos=(0, 0))

        self.ctl_fix_point = visual.Circle(
            win_ctl, radius=15 * self.scale_x, fillColor='green', pos=(0, 0))
        self.ctl_gaze_cursor = visual.Circle(
            win_ctl, radius=6, fillColor='yellow', opacity=0.8)
        self.ctl_fix_window = visual.Circle(
            win_ctl, radius=100, fillColor=None,
            lineColor='red', lineWidth=2, pos=(0, 0))

        self.trial_clock = core.Clock()
        self.behavior_log = []

        # ========== 修改：使用精确到秒的时间戳作为session标识 ==========
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"Fixation_{self.session_timestamp}"

        # 创建本次实验的专用日志文件夹
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.save_dir = os.path.join(script_dir, "experiment_logs", self.session_id)
        os.makedirs(self.save_dir, exist_ok=True)
        print(f"[Session] 本次实验日志目录: {self.save_dir}")
        # ========== 修改结束 ==========

        # ---------- Bar 刺激 ----------
        self._bar_params = {
            'bar_enabled':          True,
            'bar_color_r':          255,
            'bar_color_g':          0,
            'bar_color_b':          0,
            'bar_shape':            'Rectangle',
            'bar_width':            120,
            'bar_height':           40,
            'bar_pos_x':            300,
            'bar_pos_y':            0,
            'bar_mode':             'single',
            'bar_symmetric_flicker': False,
            'bar_sequence_start_idx':    0,
            'bar_sequence_dwell_time':   1.0,
            'bar_sequence_interval':     0.5,
            'bar_flicker_on':       False,
            'bar_flicker_interval': 0.5,
            'bar_flicker_duration': 0.3,
            'bar_rotation':         0.0,
        }
        self.bar = BarStimulus(win_sub, win_ctl, self.scale_x, self.scale_y)
        self.bar.apply_params(self._bar_params)

        # ---------- 成功提示音 ----------
        # 使用 PsychoPy 合成一个短促的高频纯音（800 Hz，0.15s）
        try:
            self.success_sound = sound.Sound(value=800, secs=0.15, volume=0.8)
        except Exception as e:
            print(f"[Warning] 无法初始化成功提示音: {e}")
            self.success_sound = None

    # ------------------------------------------------------------------
    def _update_gaze_and_draw(self):
        """
        统一获取gaze数据并绘制到控制窗口。
        鼠标模式：鼠标在subject窗口的位置作为gaze点。
        眼动仪模式：使用GazeTrackerRenderer。
        返回格式：{'valid': bool, 'x': float, 'y': float}
        """
        if self.use_mouse_gaze:
            # 获取鼠标在subject窗口中的位置（pix单位，中心原点）
            mouse_pos = self.mouse.getPos()
            mx, my = mouse_pos[0], mouse_pos[1]

            # 判断鼠标是否在subject窗口内
            win_size = self.win_sub.size  # [width, height]
            half_w, half_h = win_size[0] / 2, win_size[1] / 2
            valid = (-half_w <= mx <= half_w and -half_h <= my <= half_h)

            # 在控制窗口绘制鼠标位置（黄色光标）
            ctl_mx = mx * self.scale_x
            ctl_my = my * self.scale_y
            self.ctl_gaze_cursor.pos = (ctl_mx, ctl_my)
            self.ctl_gaze_cursor.draw()

            return {'valid': valid, 'x': mx, 'y': my}
        else:
            return self.gaze_renderer.update_and_draw()

    # ------------------------------------------------------------------
    def update_params(self):
        p = self.task_manager.exp_params
        self.wait_time     = p.get('Wait Time (s)',           2.0)
        self.stim_duration = p.get('Stim Duration (s)',      1.0)
        self.reward_len    = p.get('Reward Length (s)',       0.2)
        self.iti_time      = p.get('ITI (s)',                 1.0)
        self.timeout_time  = p.get('Timeout (s)',             2.0)
        self.fix_radius    = p.get('Fix Window Radius (pix)', 100)
        self.ctl_fix_window.radius = self.fix_radius * self.scale_x

    def _prompt_all_params(self):
        """统一弹窗：Fixation + Bar 同时编辑；Cancel 时关闭任务界面并退出"""
        dlg = UnifiedParamDialog(self.task_manager.exp_params, self._bar_params)
        cancelled, new_fix, new_bar = dlg.show()

        if cancelled:
            print("\n[Cancel] 用户取消，正在关闭所有任务界面...")
            try:
                self.win_sub.close()
            except Exception:
                pass
            try:
                self.win_ctl.close()
            except Exception:
                pass
            raise SystemExit("User cancelled experiment")

        # 更新 Fixation 参数
        self.task_manager.exp_params.update(new_fix)
        self.update_params()

        # 更新 Bar 参数
        self._bar_params = new_bar
        self.bar.apply_params(self._bar_params)
        print("  参数已更新 — Fixation + Bar")

    # ========== 新增：每次Trial结束后立即保存（防止崩溃丢失数据） ==========
    def _save_trial_data(self, trial_data):
        """每次 trial 结束后立即保存单个 trial 数据"""
        try:
            trial_file = os.path.join(
                self.save_dir,
                f"trial_{trial_data['Trial']:04d}_{self.session_timestamp}.csv"
            )
            pd.DataFrame([trial_data]).to_csv(trial_file, index=False)
        except Exception as e:
            print(f"[Warning] Trial {trial_data['Trial']} 保存失败: {e}")
    # ========== 新增结束 ==========

    # ------------------------------------------------------------------
    def is_gaze_in_window(self, gaze_x, gaze_y):
        dist = math.hypot(gaze_x, gaze_y)
        return dist <= self.fix_radius

    # ------------------------------------------------------------------
    def run_task(self):
        """任务主循环"""
        self._prompt_all_params()

        print("\n=== Fixation Task 开始执行 ===")
        print("按 'Esc' 退出，按 'N' 在 Trial 结束后修改参数。")

        trial_count     = 1
        success_count   = 0
        pause_requested = False

        while True:
            # ==========================================================
            # 阶段 A：ITI 与参数修改安全区
            # ==========================================================
            if pause_requested:
                print("\n[实验暂停] 正在呼出参数修改面板...")
                self.win_sub.color = "black"
                self.win_sub.flip()

                self.bar.pause()
                self._prompt_all_params()
                print("✅ 参数已更新！")

                event.clearEvents()
                self.win_sub.color = "black"
                self.win_sub.flip()
                pause_requested = False
                self.bar.resume()
            else:
                self.win_sub.color = 'black'
                self.win_ctl.color = 'black'
                self.win_sub.flip()
                self.win_ctl.flip()

            self.trial_clock.reset()
            while self.trial_clock.getTime() < self.iti_time:
                self._update_gaze_and_draw()
                self.win_sub.flip()
                self.win_ctl.flip()

                keys = event.getKeys()
                if 'escape' in keys:
                    return
                if 'n' in keys:
                    pause_requested = True
                    break

            # ==========================================================
            # 阶段 B：Wait for Fixation
            # ==========================================================
            print(f"\n--- Trial {trial_count} 开始 ---")
            self.arduino.trial_start()
            if hasattr(self.shared_data, "send_event"):
                self.shared_data.send_event(f"TRIALID {trial_count}")
                self.win_sub.callOnFlip(
                    self.shared_data.send_event,
                    f"FIX_ON TRIAL {trial_count}",
                )

            t_trial_start   = core.getTime()
            t_draw_finish   = None
            t_gaze_enter    = None
            first_draw_done = False

            trial_status    = "NoFix"
            self.trial_clock.reset()
            event.clearEvents()

            gaze_acquired       = False
            t_gaze_first_enter  = None

            # ========== 修复1：Bar延迟计时器与显示标志 ==========
            # Bar延迟改为100ms（必须小于Acquired的150ms，确保Bar有机会显示）
            BAR_DELAY = 0.1  # 100ms延迟
            bar_delay_clock = core.Clock()
            bar_show_ready = False  # bar是否可以显示
            t_gaze_entered = None   # gaze首次进入fixation窗口的时间
            # ========== 修复1结束 ==========

            while self.trial_clock.getTime() < self.wait_time:
                # 1. 始终绘制Fixation点
                self.stim_fix_point.draw()
                self.ctl_fix_point.draw()
                self.ctl_fix_window.draw()

                # 2. 检查gaze状态并管理bar延迟计时
                gaze = self._update_gaze_and_draw()

                if gaze['valid'] and self.is_gaze_in_window(gaze['x'], gaze['y']):
                    if not gaze_acquired:
                        # gaze首次进入fixation窗口
                        gaze_acquired = True
                        t_gaze_first_enter = core.getTime()
                        t_gaze_entered = core.getTime()
                        bar_delay_clock.reset()  # 启动bar延迟计时
                    else:
                        # gaze持续在fixation窗口内
                        # ========== 修复2：Bar延迟条件判断 ==========
                        # 检查是否已满足BAR_DELAY延迟，可以显示bar
                        if not bar_show_ready and bar_delay_clock.getTime() >= BAR_DELAY:
                            bar_show_ready = True
                        # ========== 修复2结束 ==========

                        # 检查是否满足150ms保持要求（acquired条件）
                        if (core.getTime() - t_gaze_first_enter) * 1000 >= 150:
                            trial_status = "Acquired"
                            t_gaze_enter = t_gaze_first_enter
                            break
                else:
                    # gaze离开fixation窗口，重置所有状态
                    gaze_acquired = False
                    t_gaze_first_enter = None
                    t_gaze_entered = None
                    bar_show_ready = False

                # 3. 绘制Bar（仅在gaze进入fixation窗口且延迟BAR_DELAY后）
                # ========== 修复3：确保Bar在条件满足时绘制 ==========
                if bar_show_ready:
                    self.bar.draw_frame()
                # ========== 修复3结束 ==========

                # 记录fixation点实际出现时间（第一次绘制）
                if not first_draw_done:
                    t_draw_finish = core.getTime()
                    first_draw_done = True

                self.win_sub.flip()
                self.win_ctl.flip()

                keys = event.getKeys()
                if 'escape' in keys:
                    return
                if 'n' in keys:
                    pause_requested = True

            # ==========================================================
            # 阶段 C：Hold（严格保持期）
            # ==========================================================
            if trial_status == "Acquired":
                self.trial_clock.reset()
                self.ctl_fix_window.lineColor = 'green'

                while self.trial_clock.getTime() < self.stim_duration:
                    # ========== 修复4：Hold阶段Bar持续显示 ==========
                    # Hold阶段：bar继续显示（一旦在Wait阶段满足条件显示后，Hold阶段持续显示）
                    if bar_show_ready:
                        self.bar.draw_frame()
                    # ========== 修复4结束 ==========

                    self.stim_fix_point.draw()
                    self.ctl_fix_point.draw()
                    self.ctl_fix_window.draw()

                    gaze = self._update_gaze_and_draw()

                    if not gaze['valid'] or not self.is_gaze_in_window(gaze['x'], gaze['y']):
                        t_break = core.getTime()
                        fixation_duration_ms = (t_break - t_gaze_enter) * 1000
                        trial_status = "NoFix" if fixation_duration_ms <= 50 else "Break"
                        break

                    self.win_sub.flip()
                    self.win_ctl.flip()

                    keys = event.getKeys()
                    if 'escape' in keys:
                        return
                    if 'n' in keys:
                        pause_requested = True

                if trial_status == "Acquired":
                    trial_status = "Success"

            # ==========================================================
            # 阶段 D：Outcome（结果与惩罚）
            # ==========================================================
            if trial_status == "Success":
                success_count += 1
                print(f" -> Result: SUCCESS! (给水 {self.reward_len}s) [{success_count}/{trial_count}]")
                # 播放成功提示音
                if self.success_sound is not None:
                    try:
                        self.success_sound.play()
                    except Exception as e:
                        print(f"[Warning] 提示音播放失败: {e}")
                self.arduino.trial_success()
                self.arduino.reward(int(self.reward_len * 1000))

            elif trial_status == "Break":
                print(f" -> Result: BREAK! (Timeout {self.timeout_time}s)")
                self.win_sub.color = 'black'
                self.win_ctl.color = 'black'
                self.win_sub.flip()
                self.win_ctl.flip()
                self.win_sub.flip()
                self.win_ctl.flip()
                self.arduino.trial_break()
                core.wait(self.timeout_time)

            elif trial_status == "NoFix":
                print(" -> Result: NO FIX")
                self.win_sub.color = 'black'
                self.win_ctl.color = 'black'
                self.win_sub.flip()
                self.win_ctl.flip()
                self.arduino.trial_nofix()

            print(f"当前正确率: {success_count}/{trial_count}")

            trial_data = {
                "Trial":           trial_count,
                "Status":          trial_status,
                "Time_TrialStart": t_trial_start,
                "Time_DrawFinish": t_draw_finish,
                "Time_GazeEnter":  t_gaze_enter,
                "Time_End":        core.getTime(),
                "Bar_Enabled":     self._bar_params['bar_enabled'],
                "Bar_Color_R":     self._bar_params['bar_color_r'],
                "Bar_Color_G":     self._bar_params['bar_color_g'],
                "Bar_Color_B":     self._bar_params['bar_color_b'],
                "Bar_Shape":       self._bar_params['bar_shape'],
                "Bar_Mode":        self._bar_params['bar_mode'],
                "Bar_Pos_X":       self._bar_params['bar_pos_x'],
                "Bar_Pos_Y":       self._bar_params['bar_pos_y'],
                "Bar_Width":       self._bar_params['bar_width'],
                "Bar_Height":      self._bar_params['bar_height'],
                "Bar_Flicker":     self._bar_params['bar_flicker_on'],
                "Bar_Rotation":    self._bar_params.get('bar_rotation', 0.0),
            }

            if hasattr(self.shared_data, "send_event"):
                self.shared_data.send_event(
                    f"!V TRIAL_VAR Status {trial_status}"
                )
                self.shared_data.send_event(f"TRIAL_RESULT {trial_status}")
            self.behavior_log.append(trial_data)

            # ========== 修改：每次Trial结束立即保存 ==========
            self._save_trial_data(trial_data)
            # ========== 修改结束 ==========

            trial_count += 1


# ==========================================
# 4. 主程序入口 (Main)
# ==========================================
if __name__ == '__main__':
    tracker_mode = globals().get("TRACKER_MODE_OVERRIDE", "qy")
    is_simulating = globals().get("IS_SIMULATING_OVERRIDE", 0)
    tracker_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tracker_runtime = create_tracker_runtime(
        tracker_mode,
        is_simulating=bool(is_simulating),
        session_id=f"FixBar_{tracker_timestamp}",
        save_dir=os.path.dirname(os.path.abspath(__file__)),
        screen_size=(1920, 1080),
        qy_sample_rate=100,
    )
    shared_data = tracker_runtime.gaze_source

    MONITOR_ID_SUBJECT = 1
    MONITOR_ID_CONTROL = 0

    print("正在初始化双屏幕环境...")
    win_subject = visual.Window(
        screen=MONITOR_ID_SUBJECT,
        size=[1920, 1080],
        fullscr=False,
        waitBlanking=True,
        color='black',
        units='pix',
        allowGUI=False
    )

    win_control = visual.Window(
        screen=MONITOR_ID_CONTROL,
        size=[800, 450],
        fullscr=False,
        waitBlanking=False,
        color='black',
        units='pix',
        title="Fixation Control View"
    )

    fixation_defaults = {
        'Subject ID':             'Monkey_H18',
        'Wait Time (s)':          10.0,
        'Stim Duration (s)':      1.5,
        'Fix Window Radius (pix)': 500,
        'Reward Length (s)':      0.2,
        'ITI (s)':                5.0,
        'Timeout (s)':            2.5,
    }

    print("加载参数配置...")
    task_manager = FineVision_Notebook(
        task_name="FixationTask", default_params=fixation_defaults)

    try:
        fix_task = FixationTask(win_subject, win_control,
                                shared_data, task_manager, is_simulating)
        while True:
            fix_task.run_task()

    except SystemExit as e:
        print(f"实验已退出: {e}")

    except Exception as e:
        print(f"任务运行中发生错误: {e}")
        traceback.print_exc()

    finally:
        # ========== 修改：使用唯一文件名保存汇总数据，不覆盖 ==========
        if hasattr(fix_task, 'behavior_log') and len(fix_task.behavior_log) > 0:
            try:
                # 使用 get_unique_filename 确保不覆盖
                csv_name = get_unique_filename(
                    "Fixation_task_log", ".csv", 
                    sub_dir=fix_task.save_dir
                )
                pd.DataFrame(fix_task.behavior_log).to_csv(csv_name, index=False)
                print(f"[Save] 汇总数据已保存: {csv_name}")
                print(f"[Save] 本次实验所有数据位于: {fix_task.save_dir}")
            except Exception as e:
                print(f"[Warning] 保存汇总数据失败: {e}")
        # ========== 修改结束 ==========

        print("正在关闭实验进程...")
        try:
            fix_task.arduino.close()
        except Exception:
            pass
        tracker_runtime.close()
        try:
            win_subject.close()
        except Exception:
            pass
        try:
            win_control.close()
        except Exception:
            pass
        core.quit()
