from psychopy import core, gui
from Json_manager import read_json, update_json
import os
import tkinter as tk
from tkinter import messagebox, ttk


def _coerce_saved_value(default_value, saved_value):
    """Keep the parameter's declared UI type when restoring JSON values."""
    if isinstance(default_value, bool):
        return bool(saved_value)
    if isinstance(default_value, float) and isinstance(
        saved_value,
        (int, float),
    ):
        return float(saved_value)
    if (
        isinstance(default_value, int)
        and isinstance(saved_value, (int, float))
        and float(saved_value).is_integer()
    ):
        return int(saved_value)
    return saved_value


class _ScrollableParameterDialog:
    """Modal parameter editor with categorized, scrollable tabs."""

    def __init__(
        self,
        parameters,
        title,
        parameter_groups=None,
        parameter_validator=None,
        disabled_parameters=None,
        parameter_summary_provider=None,
        runtime_actions=False,
        allow_recalibration=False,
        notice=None,
    ):
        self.parameters = parameters
        self.parameter_validator = parameter_validator
        self.disabled_parameters = set(disabled_parameters or ())
        self.parameter_summary_provider = parameter_summary_provider
        self.runtime_actions = bool(runtime_actions)
        self.allow_recalibration = bool(allow_recalibration)
        self.notice = None if notice is None else str(notice)
        self.result = None
        self.action = "cancel"
        self.variables = {}
        self.widgets = {}
        self.widget_locations = {}
        self.forms = []
        self.tab_canvases = {}

        self.root = tk.Tk()
        self.root.title(title)
        self.root.minsize(620, 420)
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

        container = ttk.Frame(self.root, padding=(12, 12, 12, 8))
        container.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        for group_name, parameter_names in self._normalize_groups(
            parameter_groups
        ):
            self._add_parameter_tab(group_name, parameter_names)

        footer_row = 1
        if self.notice:
            notice_frame = ttk.Frame(container, padding=(0, 8, 0, 0))
            notice_frame.grid(row=footer_row, column=0, sticky="ew")
            tk.Label(
                notice_frame,
                text=self.notice,
                anchor="w",
                justify="left",
                fg="#c62828",
                font=("TkDefaultFont", 10, "bold"),
                wraplength=760,
            ).pack(fill="x")
            footer_row += 1
        self.summary_variable = None
        if self.parameter_summary_provider is not None:
            status_frame = ttk.Frame(container, padding=(0, 8, 0, 0))
            status_frame.grid(row=footer_row, column=0, sticky="ew")
            ttk.Separator(
                status_frame,
                orient="horizontal",
            ).pack(fill="x", pady=(0, 7))
            self.summary_variable = tk.StringVar(value="Planned trials: —")
            ttk.Label(
                status_frame,
                textvariable=self.summary_variable,
                anchor="w",
            ).pack(fill="x")
            footer_row += 1

        footer = ttk.Frame(container, padding=(0, 10, 0, 0))
        footer.grid(row=footer_row, column=0, sticky="e")
        if self.runtime_actions:
            button_style = {
                "width": 16,
                "fg": "white",
                "activeforeground": "white",
                "relief": "raised",
                "borderwidth": 1,
            }
            tk.Button(
                footer,
                text="Cancel / 取消",
                command=self._cancel,
                bg="#c62828",
                activebackground="#b71c1c",
                **button_style,
            ).pack(side="right", padx=(8, 0))
            if self.allow_recalibration:
                tk.Button(
                    footer,
                    text="Recalibrate / 重新校准",
                    command=lambda: self._accept("recalibrate"),
                    bg="#1565c0",
                    activebackground="#0d47a1",
                    **button_style,
                ).pack(side="right", padx=(8, 0))
            tk.Button(
                footer,
                text="Confirm / 确定",
                command=lambda: self._accept("confirm"),
                bg="#1565c0",
                activebackground="#0d47a1",
                **button_style,
            ).pack(side="right")
        else:
            ttk.Button(
                footer,
                text="Cancel",
                command=self._cancel,
                width=12,
            ).pack(side="right", padx=(8, 0))
            ttk.Button(
                footer,
                text="OK",
                command=self._accept,
                width=12,
            ).pack(side="right")

        self.root.bind("<Return>", lambda event: self._accept())
        self.root.bind("<Escape>", lambda event: self._cancel())
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Button-4>", self._on_mousewheel)
        self.root.bind_all("<Button-5>", self._on_mousewheel)

        if self.parameter_summary_provider is not None:
            for variable in self.variables.values():
                variable.trace_add("write", self._update_summary)
            self._update_summary()

        self._set_initial_geometry()

    def _normalize_groups(self, parameter_groups):
        if not parameter_groups:
            return [("Parameters", list(self.parameters))]

        groups = []
        assigned = set()
        items = (
            parameter_groups.items()
            if hasattr(parameter_groups, "items")
            else parameter_groups
        )
        for group_name, requested_names in items:
            names = [
                name
                for name in requested_names
                if name in self.parameters and name not in assigned
            ]
            if names:
                groups.append((str(group_name), names))
                assigned.update(names)

        remaining = [
            name for name in self.parameters if name not in assigned
        ]
        if remaining:
            groups.append(("Other / 其他", remaining))
        return groups

    def _add_parameter_tab(self, group_name, parameter_names):
        tab = ttk.Frame(self.notebook, padding=(6, 6, 6, 4))
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.notebook.add(tab, text=group_name)

        canvas = tk.Canvas(tab, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            tab,
            orient="vertical",
            command=canvas.yview,
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        form = ttk.Frame(canvas, padding=(8, 6, 12, 10))
        form.columnconfigure(1, weight=1)
        canvas_window = canvas.create_window(
            (0, 0),
            window=form,
            anchor="nw",
        )
        form.bind(
            "<Configure>",
            lambda _event, current_canvas=canvas: current_canvas.configure(
                scrollregion=current_canvas.bbox("all")
            ),
        )
        canvas.bind(
            "<Configure>",
            lambda event, current_canvas=canvas, window_id=canvas_window: (
                current_canvas.itemconfigure(window_id, width=event.width)
            ),
        )

        tab_id = str(tab)
        self.tab_canvases[tab_id] = canvas
        self.forms.append(form)

        for row, name in enumerate(parameter_names):
            value = self.parameters[name]
            label = ttk.Label(form, text=name, anchor="w")
            label.grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 22),
                pady=7,
            )

            if isinstance(value, list):
                choices = list(value)
                variable = tk.StringVar(
                    value=str(choices[0]) if choices else ""
                )
                widget = ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=[str(choice) for choice in choices],
                    state="readonly",
                    width=28,
                )
            elif isinstance(value, bool):
                variable = tk.BooleanVar(value=value)
                widget = ttk.Checkbutton(form, variable=variable)
            else:
                variable = tk.StringVar(value=str(value))
                widget = ttk.Entry(
                    form,
                    textvariable=variable,
                    width=32,
                )

            widget.grid(row=row, column=1, sticky="ew", pady=7)
            if name in self.disabled_parameters:
                label.state(["disabled"])
                widget.state(["disabled"])
            self.variables[name] = variable
            self.widgets[name] = widget
            self.widget_locations[name] = (tab_id, canvas, form)

    def _set_initial_geometry(self):
        self.root.update_idletasks()
        requested_width = max(
            (form.winfo_reqwidth() for form in self.forms),
            default=560,
        ) + 80
        requested_height = max(
            (form.winfo_reqheight() for form in self.forms),
            default=340,
        ) + 135
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(max(requested_width, 680), int(screen_width * 0.85))
        height = min(max(requested_height, 480), int(screen_height * 0.82))
        x_pos = max(0, (screen_width - width) // 2)
        y_pos = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            steps = -1
        elif getattr(event, "num", None) == 5:
            steps = 1
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return
            steps = -int(delta / 120)
            if steps == 0:
                steps = -1 if delta > 0 else 1
        selected_tab = self.notebook.select()
        canvas = self.tab_canvases.get(selected_tab)
        if canvas is not None:
            canvas.yview_scroll(steps, "units")

    @staticmethod
    def _convert_value(raw_value, original_value):
        if isinstance(original_value, list):
            for choice in original_value:
                if str(choice) == raw_value:
                    return choice
            return raw_value
        if isinstance(original_value, bool):
            return bool(raw_value)
        if isinstance(original_value, int):
            return int(raw_value.strip())
        if isinstance(original_value, float):
            return float(raw_value.strip())
        if isinstance(original_value, str):
            return raw_value
        return type(original_value)(raw_value)

    def _update_summary(self, *_args):
        if self.parameter_summary_provider is None:
            return

        updated = {}
        try:
            for name, original_value in self.parameters.items():
                updated[name] = self._convert_value(
                    self.variables[name].get(),
                    original_value,
                )
            summary = self.parameter_summary_provider(updated)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            summary = "Planned trials: — (enter a complete valid range)"
        self.summary_variable.set(str(summary))

    def _accept(self, action="confirm"):
        updated = {}
        for name, original_value in self.parameters.items():
            raw_value = self.variables[name].get()
            try:
                updated[name] = self._convert_value(
                    raw_value,
                    original_value,
                )
            except (TypeError, ValueError):
                widget = self.widgets[name]
                tab_id, canvas, form = self.widget_locations[name]
                self.notebook.select(tab_id)
                widget.focus_set()
                self.root.update_idletasks()
                form_height = max(1, form.winfo_height())
                canvas.yview_moveto(
                    max(0.0, widget.winfo_y() / form_height - 0.15)
                )
                messagebox.showerror(
                    "Invalid parameter",
                    f"Please enter a valid value for:\n{name}",
                    parent=self.root,
                )
                return

        if self.parameter_validator is not None:
            try:
                validation_message = self.parameter_validator(updated)
            except ValueError as error:
                messagebox.showerror(
                    "Invalid parameter combination",
                    str(error),
                    parent=self.root,
                )
                return
            if validation_message and not messagebox.askokcancel(
                "Confirm parameter plan",
                str(validation_message),
                parent=self.root,
            ):
                return

        self.result = updated
        self.action = str(action)
        self._close()

    def _cancel(self):
        self.result = None
        self.action = "cancel"
        self._close()

    def _close(self):
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")
        self.root.destroy()

    def show(self):
        self.root.lift()
        self.root.focus_force()
        first_widget = next(
            (
                widget
                for name, widget in self.widgets.items()
                if name not in self.disabled_parameters
            ),
            None,
        )
        if first_widget is not None:
            first_widget.focus_set()
        self.root.mainloop()
        return self.result

class FineVision_Notebook:
    def __init__(
        self,
        task_name="FinVision",
        default_params=None,
        parameter_groups=None,
        parameter_validator=None,
        parameter_summary_provider=None,
    ):
        """
        :param task_name: 任务名称，用于生成独立的 JSON 参数文件
        :param default_params: 外部传入的字典。如果不传，则使用内置默认值。
        """
        self.task_name = task_name
        self.param_file = f"params_{self.task_name}.json"
        self.parameter_groups = parameter_groups
        self.parameter_validator = parameter_validator
        self.parameter_summary_provider = parameter_summary_provider

        if default_params is None:
            default_params = {
                'Subject ID': 'Monkey_H18',
                'Reward Length (s)': 0.2,
                'Condition': ['Training', 'Testing', 'Probe'] # 这是一个下拉菜单
            }
        
        file_data = read_json(self.param_file)
        last_saved_params = file_data.get("parameters",{})

        self.exp_params = default_params.copy()

        for key, saved_value in last_saved_params.items():
            if key in self.exp_params:
                # 如果代码里定义的是列表（下拉菜单），但 JSON 里存的是上次选的字符串
                if isinstance(self.exp_params[key], list) and not isinstance(saved_value, list):
                    if saved_value in self.exp_params[key]:
                        # 把上次选中的项移到列表第一位，这样 GUI 打开时默认就是它
                        self.exp_params[key].remove(saved_value)
                        self.exp_params[key].insert(0, saved_value)
                else:
                    # 普通的数字或字符串，直接用上次保存的值覆盖
                    self.exp_params[key] = _coerce_saved_value(
                        self.exp_params[key],
                        saved_value,
                    )
            else:
                print(f"[Parameters] Ignoring obsolete saved field: {key}")
                continue
                # 如果 JSON 里有，但当前默认字典里没有的新增参数，也一起合并进来
                self.exp_params[key] = saved_value

    def _prompt_for_parameters_legacy(self):
        """弹出一个 UI 窗口让研究人员修改参数"""
        
        print(f"等待输入 {self.task_name} 任务的参数...")
        
        # 4. 调用内置 GUI
        dlg = gui.DlgFromDict(
            dictionary=self.exp_params, 
            title=f"实验参数设置 ({self.task_name})", # 标题栏加上任务名称
            sortKeys=False                  # 保持你定义的顺序
        )
        
        # 5. 检查研究人员是点了 "OK" 还是 "Cancel"
        if not dlg.OK:
            print("研究人员点击了取消，实验中止。")
            core.quit() # 安全退出 PsychoPy 程序
            return False

        # 6. 🌟 核心更新：点击 OK 后，将最新的参数字典存回 JSON 文件 🌟
        update_json(self.param_file, "parameters", self.exp_params)

        print("\n=== 新的实验参数已确认并保存 ===")
        #for key, value in self.exp_params.items():
        #    print(f"{key}: {value}")
            
        return True

    def prompt_for_parameters(
        self,
        disabled_parameters=None,
        parameter_validator=None,
        title=None,
    ):
        """Show a scrollable editor and save the confirmed parameters."""
        print(f"Waiting for {self.task_name} task parameters...")

        dialog = _ScrollableParameterDialog(
            parameters=self.exp_params,
            title=title or f"Experiment Parameters ({self.task_name})",
            parameter_groups=self.parameter_groups,
            parameter_validator=(
                parameter_validator
                if parameter_validator is not None
                else self.parameter_validator
            ),
            disabled_parameters=disabled_parameters,
            parameter_summary_provider=self.parameter_summary_provider,
        )
        updated_params = dialog.show()

        if updated_params is None:
            print("Parameter editing cancelled; stopping the experiment.")
            core.quit()
            return False

        self.exp_params.clear()
        self.exp_params.update(updated_params)
        update_json(self.param_file, "parameters", self.exp_params)
        print("\n=== Experiment parameters confirmed and saved ===")
        return True

    def prompt_for_runtime_parameters(
        self,
        disabled_parameters=None,
        parameter_validator=None,
        title=None,
        allow_recalibration=False,
        notice=None,
    ):
        """Edit live parameters and return confirm/recalibrate/cancel.

        Unlike the startup dialog, cancelling this menu does not call
        ``core.quit``.  The running task decides how to end its session.
        """
        print(f"Waiting for {self.task_name} runtime parameters...")
        dialog = _ScrollableParameterDialog(
            parameters=self.exp_params,
            title=title or f"Runtime Parameters ({self.task_name})",
            parameter_groups=self.parameter_groups,
            parameter_validator=(
                parameter_validator
                if parameter_validator is not None
                else self.parameter_validator
            ),
            disabled_parameters=disabled_parameters,
            parameter_summary_provider=self.parameter_summary_provider,
            runtime_actions=True,
            allow_recalibration=bool(allow_recalibration),
            notice=notice,
        )
        updated_params = dialog.show()
        if updated_params is None:
            print("Runtime parameter editing cancelled.")
            return "cancel"

        self.exp_params.clear()
        self.exp_params.update(updated_params)
        update_json(self.param_file, "parameters", self.exp_params)
        print("\n=== Runtime parameters confirmed and saved ===")
        return dialog.action

'''
    # ===== 外部调用的例子 =====
    # 假设你今天要跑一个 Memory Task
    while True:
        if pause_requested:
            print("\n[实验暂停] 正在呼出参数修改面板...")
            
            # 视觉保护：给猴子一个灰屏，避免它在暂停期间一直盯着之前的刺激
            win_sub.color = "gray"
            win_sub.flip()
            
            # 呼出参数修改窗口 (此时程序会阻塞，等待你输入)
            task_instance.prompt_for_parameters()
            
            # 重新提取更新后的参数
            current_reward = task_instance.exp_params['Reward Length (s)']
            current_condition = task_instance.exp_params['Condition']
            print(f"✅ 参数已更新！新奖励: {current_reward}s，新条件: {current_condition}")
            
            # 🌟 极度重要：清空按键缓存！
            # 因为你在输入框里打字（比如输入 '0.5' 然后按 'Enter'）时，这些按键会被 PsychoPy 记录。
            # 这里必须清空，否则弹窗一关，这些按键就会跑进你的任务逻辑里！
            event.clearEvents()
            pause_requested = False 

        # ====================================================
        # 阶段 B：执行核心 Trial 逻辑 (安全区，不会被打断)
        # ====================================================


        # ====================================================
        # 阶段 C：Trial 结束 (ITI 期间) -> 检测按键请求
        # ====================================================
        # 获取在这个 Trial 期间（或者 ITI 期间）研究人员按下的所有键盘按键
        keys = event.getKeys()
        
        if 'escape' in keys:
            print("按下 Esc，实验安全退出。")
            break
            
        # 如果检测到了 N 键，我们只改变状态标记，不立刻弹窗！
        if 'n' in keys:
            print(">> 接收到 'N' 键指令！将在下一个 Trial 开始前暂停。")
            pause_requested = True
            
        trial_count += 1
        
        # 模拟 ITI (Inter-Trial Interval) 间隔时间
        core.wait(1.0)
'''
