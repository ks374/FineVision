# RAW 校准与验证

运行 Calibration_Task_EyeLink.py 做校准；运行 validation_task_Eyelink.py 做独立验证。两者独立使用 RAW，不修改 eyelink_setting.json，因此现有任务仍使用原有 GAZE 配置。

启动参数窗口可调整：个体、被试/操作屏编号、分辨率、全屏、注视点大小、注视窗、保持时间、等待超时、ITI、奖励、屏幕尺寸、视距、背景亮度、采样率、采样时段和最少样本数。

随后打开点列表窗口。校准和验证首次均默认3点：(0°,0°)、(-4°,0°)、(0°,3°)，权重均为1。坐标相对屏幕中心，右为正X、上为正Y。点击“+”增加一行，直接编辑X、Y和权重；每行可删除，但至少保留3个不共线点。点数不设固定上限，长列表可滚动；超出屏幕、非有限坐标和非正权重会拒绝开始。旧版水平/垂直范围及额外四点设置不用于这个自定义列表。校准和验证共用params_CalibrationTask.json中的通用参数及params_CalibrationTask_points.json中的点坐标和权重；任一入口确认保存后，另一入口下次运行也会使用这些值。旧的params_ValidationTask.json和params_ValidationTask_points.json不再读取，保留文件作为历史记录；取消点列表不会连接硬件。两者继续共用eyelink_raw_pupil_setting.json校准映射。

拟合使用每点采集末段的RAW均值，按 sum(weight * squared_pixel_error) 拟合二维仿射模型；实现中乘sqrt(weight)，因此权重2不是平方误差权重4。恰好3个有效不共线点可完全确定仿射模型，权重通常不改变其解；更多点时权重决定折中。验证误差不加权。默认3点只覆盖中央区域，外围任务需要自行添加覆盖范围内的点。

自动方式使用当前映射判断是否进入注视窗，并在保持末段采集RAW。空格立即开始指定时长的RAW采集，不要求当前映射判断在窗内，但仍要求有效眼动样本；操作者需要确认猴子在看目标。首次RAW系数为单位映射，通常需要空格采集建立初始映射。Escape中止；中止不更新活动映射。

采集期间EyeLink处于recording，EDF记录眼动样本和事件。这不等于保存眼部摄像机视频。采样结束关闭录制并将EDF下载到experiment_logs下带个体和时间的会话子目录。

校准成功写入主目录eyelink_raw_pupil_setting.json；会话子目录保存同名映射快照、mapping_before.json、tracker_settings.json、session.json和EDF。session.json中保留每点RAW样本、时间戳和模型信息。EDF传输失败会记录错误；文件仍可能留在Host端。

验证使用原有映射采集并计算右眼误差，绘图前不重新拟合。图中(0,0)代表各点的目标，编号对应点列表顺序。保存validation_before_update.png和validation_offsets.json，然后显示“更新/不更新”按钮；关闭图窗等价于不更新。独立验证需要重新采集样本，即使采用相同目标坐标也不能复用校准样本。

点击不更新：主目录活动映射保持原样。点击更新：用本次RAW、目标位置和逐点权重重新拟合完整二维仿射模型，覆盖主目录活动映射及本次会话子目录同名快照。旧映射保留在mapping_before.json。图始终是更新前的独立验证结果；新映射必须再运行一轮validation才能评估，不能用本次拟合误差宣称准确度。

现有刺激/行为任务入口未修改。Saccade_Elec_stim_Eyelink.py仍要求GAZE；本次RAW校准不会自动使它使用RAW。请勿单独改全局JSON后直接运行该刺激任务。

软件测试覆盖更新/不更新保存路径、旧映射验证、病态采样拒绝和图像保存。真实EyeLink录制、EDF下载、水奖励、屏幕呈现、鼠标按钮交互需现场验证。
