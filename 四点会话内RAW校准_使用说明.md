# Intan saccade 会话内四点RAW校准

入口：Saccade_Elec_stim_Eyelink_Intan.py（今天使用的Intan版本）。N请求在当前试次结束后的安全边界暂停，参数窗口有“Recalibrate / 重新校准”。参数编辑保存后，选择该按钮进入四点校准。此时Intan刺激已解除，校准不触发电刺激。

固定顺序（屏幕中心角度，右上为正）：(-3,5)、(6,-6)、(-3,-6)、(6,5)，每点权重1。复用当前被试与工作窗口、EyeLink连接、已打开的EDF和奖励控制器；不启动独立脚本，不新增显示窗口或连接。

每个目标沿用当前任务的注视点半径、注视窗、等待时间、ITI和水奖励，保持时间固定500ms，末100ms采集RAW，至少20个唯一有效采样才接受。普通自动采集依赖旧映射判断持续在窗内；空格可手动触发100ms采集（沿用独立校准逻辑，操作者须确认在看目标）。没有增加眼速/离散度稳定检测。失败重试当前点，Esc取消本轮并保留旧映射。

四点均完成后，检查右眼RAW不共线，再加权最小二乘拟合二维仿射模型。一次性更新主目录eyelink_raw_pupil_setting.json、backend内存系数以及EyeEvents.raw_calibration缓存。新映射保存在本次任务raw_recalibration_<时间>/中；backend的calibration_file指向该次快照，启动时的旧快照不覆盖。激活失败回滚文件和两处内存，随后停止任务报错，不带不确定映射继续实验。

更新后自动恢复；同一待执行条件会重新准备并经过正常ITI/录制保护间隔，不需要按Space。清理校准阶段残余眼跳和RAW缓存、清空光标轨迹、重新同步时钟后才允许恢复。采集中Esc取消本轮时保留旧映射，完成清理后同样自动继续。参数窗口“取消”仍表示结束任务；与四点采集中的Esc取消本轮不同。校准运行异常或更新失败仍停止任务报错。

采集期间持续清理EyeLink链接队列；raw_gaze_samples.jsonl及saccades.jsonl中该阶段记为attempt=0，并由RAW_RECALIBRATION_START/END标记划定。每个行为trial和RAW采样带calibration_revision；校准时RAW采样使用旧版本，下一行为trial使用新版本。collection.json保存逐点RAW采样、时间、拟合结果和状态；mapping_before.json保留旧映射。新映射的训练误差不作为独立验证准确度。

此修改没有接入旧Trodes刺激任务，也没有改变独立Calibration/Validation的点列表。软件检查不能代替现场验证窗口切换、EyeLink队列/EDF、奖励和真实刺激解除。
