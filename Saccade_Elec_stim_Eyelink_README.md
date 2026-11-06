# Saccade_Elec_stim_Eyelink

在 FineVision 目录，用现有 PsychoPy Python 启动：

```powershell
& 'D:\Software\Psychopy\python.exe' .\Saccade_Elec_stim_Eyelink.py
```

默认使用真实 EyeLink、绿色点模拟电刺激。`Simulate stimulation=True` 时完全不创建 Trodes 连接。
白色 control 点使用 SaccadeMultiStimTask 相同校准表，默认校准档位 150（当前表 RGB=225/225/225，目标亮度 176.25 cd/m²）。

纯鼠标演练（控制窗口内移动鼠标模拟 gaze，无 EyeLink、电刺激或水奖励）：

```powershell
& 'D:\Software\Psychopy\python.exe' .\Saccade_Elec_stim_Eyelink.py --mouse
```

鼠标演练仅用位置变化模拟 ENDSACC，不用于验证眼跳检测性能。默认参数表、EyeLink 参数表均沿用 FineVision 的加载方式。
只导出默认 970 个计划试次、不连接设备：

```powershell
& 'D:\Software\Psychopy\python.exe' .\Saccade_Elec_stim_Eyelink.py --preview
```

## 试次与参数

- HW bank start 选 0 或 128；nTrode ID=HW+1，每个 nTrode 内通道位置为 1。
- 先完成 10 个 precontrol，再执行 768 个刺激条件（128 通道×8/14/20 µA×2 次），每 4 个刺激条件后完成一次 control，共 192 次。
- 全部条件随机打乱，种子写入 session.json，计划写入 plan.json。
- 192 个 control 在 RF 矩形内分成 16×12 格，每格随机一点，再打乱顺序。RF 坐标是相对注视点的水平/垂直视角。
- RF 矩形可以包含中央注视点并与注视窗重叠；目标仍必须在屏幕内。control 须先出现合格眼跳并落入目标窗，随后才开始目标保持计时，因此 cue 出现时 gaze 已在目标窗内不构成成功。
- control 失败一直重复同一个位置；刺激前 nofix/break_1 重试同一条件，未消耗一次刺激。刺激已发出后，无论 success/nofix_2 都进入下一计划项。
- N 请求在当前尝试结束后的试次间暂停并打开参数窗口；确认后应用参数并继续，取消则结束并保存。Space 暂停期间也可以按 N 编辑；Space 仍用于普通暂停/继续，Esc 停止并保存。
- 运行中可以修改注视、反应、奖励、目标尺寸和 control 亮度等未锁定参数；受试者、真实/模拟模式、HW bank、随机种子、RF范围、屏幕几何和 Trodes 地址锁定，以保持计划及硬件连接一致。修改记录在 events.jsonl 的 PARAMETERS_UPDATED 事件中，每条 trial 标注 parameter_revision（初始为0）。
- 暂停时清空已准备的刺激槽；恢复后重新执行 ITI 并准备同一个待执行条件，不重置计划或重放已刺激条件。
- 参数窗口期间 EyeLink EDF 持续记录；关闭窗口后丢弃暂停期间积压的 link 队列数据并重新同步时钟，记录 PAUSE_LINK_QUEUE_CLEARED（含丢弃条数及丢失标记数）。这些暂停事件不参与下一试次判定；正常试次期间遇到 link 丢失仍报错停止。

## 判定与同步

光电标记沿用 Fixation_movingbar 的几何设置：160×160像素、右下角、距右/下边缘各10像素，按被试窗口实际尺寸定位。注视点首次出现（FIXPOINT_ON）不点亮；检测到进入注视窗（FIXON）后，在下一次被试屏幕刷新开始10帧光电脉冲。刺激/视觉目标开始（STIMON）另有一段覆盖刺激显示时长的光电信号；该显示信号不等于已验证的实际电流起始时间。

进入中央圈即 FIXON，无 150 ms 资格期；仍须完成随机的中央保持时间及 FIXON 后的 10 帧光电信号，哪一项更晚完成便以哪一项为准。若显示刷新率较低，实际中央保持时间可能长于参数指定的最短时间；计划和实际时间分别写入 trials 日志。中央点消失后 gap 期间也必须留在中央窗。刺激开始后立即允许眼跳。

每帧读取所有当前待处理队列项，只用右眼 ENDSACC 判定。幅度使用 EyeLink 起止 GAZE 经屏幕几何换算后的欧氏视角距离，默认严格 >0.75°（可在参数窗口调整）。眼跳起始时间必须处于刺激开始到刺激结束后 300 ms；默认额外等待 150 ms 接收延迟到达的完整事件，不扩大允许的起始时间窗口。

电刺激/绿色模拟试次：满足上述条件即 success。记录第一条被接受事件的终点、起止位置和时间、幅度，并保存相对注视点的终点坐标。control 还要求该眼跳终点进入白点目标窗，且 gaze 连续保持默认 50 ms。进入后未保持足够时间即离开，最终记 break_2（本次尝试不再恢复成功）。

状态：nofix、break_1、break_2、nofix_2、success；操作停止或设备错误另记 aborted。control 仅 success 奖励。刺激试次默认 nofix_2 也奖励，可用 Reward electrical nofix_2 关闭。奖励时刻在响应窗口及事件接收宽限期结束、黑屏翻转之后。

EyeLink 必须使用已经校准好的 Host GAZE：eyelink_setting.json 中 sample_source=gaze、active_eye=right。任务启用标准解析器配置 0；事件检测仍受该解析器门槛影响，0.75°只是对 ENDSACC 再筛选的默认幅度门槛。任务不会自动做原生标定。

光电方块位于被试屏幕右下角（160×160像素，距边缘10像素）。检测入窗的本次循环即准备开启，亮10次被试窗口绘制迭代；这不是10次物理刷新。注视中断会结束信号，因此中断试次可能不足10次。fixation保持和gap按perf_counter实际时间控制，不从刷新率推算迭代数。若10次循环跨过FIXOFF，光电保持到gap中完成，再翻黑；必要时延长gap以避免两次光电脉冲连在一起，记录实际时长。

刺激/白色cue以及对应光电显示按166.667 ms实际时间截止，截止后的首次翻屏关闭。启动测得的刷新率只作诊断，不用于确定循环次数。实际显示时长仍会有循环与翻屏量化延迟，保存stimoff_deadline_pc、stimoff_pc和stimulus_display_actual_s；物理时序以光电实测为准。

FIXON 表示任务检测到 gaze 入圈；FIXPOINT_ON 表示注视点出现，FIXOFF 表示注视点消失。STIMON/STIMOFF 是显示/光电翻转标记，各写一次，不是每帧反复发送。EDF 另含 PD_ON/PD_OFF、STIM_COMMAND、RESPONSE_END、TARGET_ENTER、REWARD、TRIAL_RESULT。每条标记含电脑时间和映射后的 EyeLink 时间；结构化元数据写在后续 META 分段消息中。

每次尝试测量电脑与 EyeLink 时钟偏移，并记录查询耗时。屏幕标记不代表硬件已经输出电流；真实模式响应窗口参考实际调用 Trodes 启动函数的电脑时间及标称 train 时长。物理电流起止与屏幕光电信号之间的偏差须由硬件记录确认。

从STIMON开始持续接收ENDSACC。真实电刺激响应截止为stim_command_pc+标称刺激串时长+Response after stim；视觉/模拟条件为实际stimoff_pc+Response after stim，不再提前写入预计显示结束对应的截止。首次合格眼跳可提前结束响应（control仍需落点保持），但不提前截断刺激显示，也不早于硬件标称串结束；未成功则等到截止及事件到达宽限期。眼跳开始和结束均须落在允许窗口内。response_deadline_pc保存预定截止；response_end_pc保存提前结束或截止；response_finished_pc保存等待/处理完成时刻，response_end_reason说明原因。

日志schema版本2：所有电脑时间戳以_pc结尾，单位秒；原生EyeLink时间戳以_eyelink结尾，单位毫秒；换算值以_eyelink_est结尾。持续时间仍使用_s或_ms。events.jsonl中的pc改为event_pc，tracker_ms_est改为event_eyelink_est，另有recorded_pc区分事件时刻与程序写入时刻；frames.jsonl使用flip_pc和gaze_sample_eyelink。眼跳start_ms/end_ms改为start_eyelink/end_eyelink，CSV展开为saccade_start_eyelink/saccade_end_eyelink。鼠标模拟事件仅保存start_pc/end_pc，不伪装原生EyeLink时间。

入窗保存fixation_enter_sample_eyelink（触发判断的采样）、fixation_detected_pc及fixon_pc（程序判定）、fixation_pd_on_pc（首次白块翻屏回调）。另外保存fixation_pd_off_pc、fixation_pd_actual_s和fixation_pd_cycles_completed。翻屏回调不是物理光子起始测量。既有日志文件不回写；分析脚本需依据schema区分新旧字段。

## 真实电刺激

将 Simulate stimulation 设为 False；运行环境需安装兼容的 trodesnetwork，Trodes 网络服务开启，工作区正确映射 HW/nTrode，并启用通道刺激能力。Trodes 串流及文件写入仍由实验者手动开启。

任务独占刺激配置：初始化会清除硬件上全部 0–255 刺激槽，并等待 2 秒让命令队列处理完毕，随后复用 group=2、slot=1。不得同时运行其他刺激控制程序。默认 ITI 为 3 秒；上一个 trial 判定结束约 1 秒后，在 ITI 中清除 slot 1，并预写下一次刺激的通道和电流。固定点出现及刺激光电信号翻转后不再发送清空命令，刺激开始时只触发已预写的 group。若清理和准备超过预定 ITI，会延长 ITI 并记录事件。通信在独立线程处理，避免阻塞显示循环；通信报错/超时后中止，不自动重发不确定是否已执行的刺激。

在 30 kHz 下，170 µs 与 60 µs 不能精确表示。实际配置为阴极先行、每相 5 samples=166.667 µs、相间 2 samples=66.667 µs、周期 100 samples=300 Hz、50 个双相脉冲；step1uA 对应幅度码 8/14/20。50 周期标称 166.667 ms，按这些参数从第一相开始到最后一相结束为 163.733 ms。这两个时长都保存在 waveform 元数据。

Esc 不保证立即中断硬件上已经启动的有限 50 脉冲串；任务不依赖未验证的硬件 stop API。成功响应、Trodes 返回 success、EDF 标记均不能替代真实输出验证。

## 数据及离线处理

每次会话位于 experiment_logs/Saccade_Elec_<subject>_<time>/：

- session.json：全部参数、实际波形、完整亮度校准表、模式。
- plan.json：970 个计划条件；plan_id 固定，attempt 是实际尝试编号。
- trials.jsonl：每次尝试即时落盘，包含状态、重复次数、是否已经刺激、奖励及选中的 ENDSACC。
- trials.csv：结束时生成的尝试汇总，单列展开眼跳终点 x/y（度）、起止时间和幅度。
- saccades.jsonl：所有读到的 ENDSACC，包括未通过筛选的事件；鼠标模式不产生真实 ENDSACC。
- events.jsonl：完整任务状态消息和时间。
- frames.jsonl：逐帧显示、光电方块状态和在线 gaze。此文件的 gaze 为逐帧抽样，不能替代高采样率 EDF。
- EyeLink EDF：后端持续录制原始高采样率眼动、EyeLink 自身事件、任务消息；关闭时从 Host 下载。

离线可用 SR Research 的 EDF2ASC 转换 EDF，按 MSG 内的 ATTEMPT 与 trials.csv 合并，然后按 FIXON/STIMON/STIM_COMMAND 对齐 SAMPLES 和 ESACC。必须保存 EDF 原件；检测器参数改变后可重新分析原始采样。电脑秒、EyeLink 毫秒及相对 session 秒不可直接混用，时钟映射参数见每次尝试记录。

## 软件检查

```powershell
& 'D:\Software\Psychopy\python.exe' -m unittest discover -s tests -p test_saccade_elec.py -v
```

测试覆盖计划数量、每条件重复、空间分层、事件队列、历史事件/时间边界、晚到 ENDSACC、control 目标保持和失败重试。尚未进行真实 EyeLink、显示光电或电刺激硬件联机验证。
