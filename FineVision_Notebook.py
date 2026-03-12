from psychopy import gui, core
from Json_manager import read_json, update_json
import os

class FineVision_Notebook:
    def __init__(self,task_name="FinVision",default_params=None):
        """
        :param task_name: 任务名称，用于生成独立的 JSON 参数文件
        :param default_params: 外部传入的字典。如果不传，则使用内置默认值。
        """
        self.task_name = task_name
        self.param_file = f"params_{self.task_name}.json"

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
                    self.exp_params[key] = saved_value
            else:
                # 如果 JSON 里有，但当前默认字典里没有的新增参数，也一起合并进来
                self.exp_params[key] = saved_value

    def prompt_for_parameters(self):
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
