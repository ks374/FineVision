# Intan RHS 版本使用说明

## 眼跳任务刺激标记（2026-10-26）

`Saccade_Elec_stim_Eyelink_Intan.py` 的真实电刺激同时在 `DIGITAL-OUT-01`
输出 1 kHz 脉冲列：每 1 ms 一个脉冲，高电平 0.5 ms、低电平 0.5 ms，
共 164 个。数字输出与电极共用 F1 边沿触发，参数在同一次 ITI 停录中上传、读回核对；
不是 Python 每隔 1 ms 发送一次命令。脚本禁用 AnalogOut1ThresholdEnabled，
确保 DIG OUT 1 由数字序列器控制。该接口由任务专用。

当前电刺激最后一相结束于触发后 163.733333 ms；最后一个数字高电平为
163.0–163.5 ms，比电刺激结束早约 0.233333 ms，之后保持低电平，不再输出。
这与任务名义时长 166.666667 ms 不同。数字标记仅在真实电刺激触发时出现，
视觉对照和模拟模式不产生该硬件输出。暂停/视觉对照撤销软件触发许可；
硬件有限脉冲列会自行结束。不要在 RHX 手动按 F1；这会触发仍配置在硬件中的输出。
正常退出禁用电极及数字标记；通信故障时只能尽力停止，不能保证物理状态。

接线：刺激端 DIG OUT 1 → 记录端 DIG IN 2；光电二极管同步信号分别接两套系统的
DIG IN 1。记录端任务代码无需因此改动，但 RHX 必须启用并保存 DIG IN 1、2。
`session.json` 保存标记定义，`intan_acquisition.jsonl` 保存实际上传及核对的波形参数。
离线协议测试不验证真实电平、两端时钟或物理边沿；接线后需用实际记录/示波器检查
164 个上升沿、约 1 ms 周期、0.5 ms 高电平及其与电刺激的相对时序。
单次刺激 GUI 不启用此标记功能。

2026-10-21 修复：RunMode 切换命令单独发送，再独立查询状态。此前把 `set runmode record` 和 `get type` 放在同一批次，RHX 进入采集循环后可能不再执行本批次的后续查询，导致录制已恢复而脚本超时断开。初始化改为查询各端口 `NumberAmplifierChannels`，不再枚举不存在的全部 512 个通道；无扩展器时只检查两个模拟/数字输出。

生成日期：2026-10-20。原始两个 Trodes 脚本未修改。

## 文件

- `trodes_stim_once_gui_Intan.py`：单次刺激窗口、单次确认、1 秒光电方块预览、与脉冲列等长的方块预览、停止。连接时清理一次；每次刺激前，在同一次停录内禁用旧配置、上传新配置并恢复。刺激结束不再清除硬件配置或停录，1 秒后可准备下一次。触发许可在发出命令前已消耗，脚本不会自动重复触发。不要手动在 RHX 按 F1，硬件仍保留上一组参数。
- `Saccade_Elec_stim_Eyelink_Intan.py`：原眼跳任务的 Intan 版本。保留 EyeLink、Arduino 奖励、视觉模拟、鼠标演练、注视/眼跳判定、重试规则、N 键试次边界编辑、Space 暂停、Esc 结束及日志。
- `IntanStim.py`：两个脚本共用的 RHX TCP 通信和刺激配置模块，必须放在同一目录。还需要现有 `SaccadeElecLogic.py` 及 FineVision 原有依赖。
- `Saccade_Elec_plan_preview_Intan.json`：默认 32 通道计划预览。

## 不能与 Trodes 完全相同的部分

**官方 RHX 的 UploadStimParameters 必须在 Stop 状态执行。** 原任务逐试次切换通道和电流，因此此版本在 ITI 中停止采集、清除旧波形并上传新波形，然后恢复此前的 Run 或 Record 模式。试次本身在恢复成功后才开始。

眼跳任务每个电刺激试次的旧配置清理与新参数上传合并在一次 Stop/Record 中。刺激后不额外清理；视觉对照和暂停只撤销脚本触发许可，不停录清理硬件，下一次电刺激准备时统一替换旧配置。初始化和最终退出时仍有独立的硬件清理。不要在 RHX 手动按 F1，软件撤销许可不等于硬件禁用。

## 眼跳任务的记录保护（2026-10-21）

- 真实刺激的眼跳任务现在必须从 **Record** 启动，拒绝只显示不保存的 Run。
- 每次恢复记录并完成准备后至少等待 **1.1 秒**，然后核对 Intan 段内 `CurrentTimestamp` 已增长至少 **33000 个样本**（30 kHz），才进入下一试次、发出 TRIALID/注视点等试次事件。上传耗时超过原 ITI 时自动延长 ITI，绝不压缩这段基线。
- 每个试次结果、奖励预计结束及 Arduino 试次输出后，保留至少 **1.1 秒**。下一次停录前同时检查 PC 保护期限及段内采样计数。奖励结束包含在保护范围内。
- 正常最后一个试次退出时也执行尾部保护。Esc/程序异常中止试次时，先等待已经下发的脉冲列及预计奖励结束，再请求尾部保护，之后清理。该路径不读取可能已经出错的 EyeLink 队列。
- 保护使用每段自己的时间戳，不假定 Stop/Record 后时间戳跨段递增；计数不增长、意外复位或模式被外部切换时会报错，不能继续开始新试次。
- `PRETRIAL_RECORDING_GUARD_PASSED`、`RHX_TRIAL_TAIL_PROTECTED` 和 `recording_event_end_pc` 等记录用于核对边界。启动清理及退出清理可能生成不含试次的辅助记录段；不保证每个文件夹一定有一个 trial。含试次的记录段才适用上述前后保护。
- 这些约束在采集与通信正常的前提下执行。掉电、设备断连、磁盘写入失败、手动停录无法由脚本保证数据完整。物理文件首尾样本及同步仍需实机验证。

- **Record 才保存神经数据；Run 只显示、不保存。**
- Record 恢复时采用独立、唯一的文件基名，并启用 `CreateNewDirectory=True`，为每段建立独立子目录，防止按通道/信号保存的 `.dat` 文件被覆盖。数据位于 RHX 原先设置的目录下面。原基名后附 `_Intan_日期时间_微秒_seg编号`，RHX 还会追加自己的时间戳。
- ITI 中存在真正的神经数据缺口，不能将分段数据当作无缝连续采样。EyeLink/行为日志仍按原任务运行。
- `intan_acquisition.jsonl` 保存停止/恢复请求与确认的 PC 时间、记录文件基名、RHX 文件时间戳、段编号及刺激参数。PC 时间不是精确硬件采样时刻；跨设备对齐仍使用真实记录的光电/TTL 信号。
- 上传超出原 ITI 时会延长 ITI，原任务的 `ITI_EXTENDED_FOR_STIM_PREP` 事件保留。
- 电流步长必须在 RHX 启动时选择，TCP 不能动态更换。单次 GUI 可选择所有原有步长，但必须与 RHX 一致；眼跳任务要求 **1 µA/步**。
- RHX 对每相及相间间隔上限为 5000 µs、每列最多 256 个脉冲；超出会明确报错。

如果要求整个实验的神经记录严格连续，同时逐试次修改电流，当前官方 RHX TCP 路径不能实现；本版本不声称具备这一能力。

## 明天连接与启动

1. 使用 **Intan RHS 控制器、RHS 头级和相应接口线**。RHD 纯记录系统不适用。
2. 启动 RHX，选 **30 kHz**；眼跳任务选 **1 µA** 刺激步长。
3. 确认接线、参考、地、刺激回流连接和 RHX 原生通道名。选中的通道必须存在，且在 RHX 中启用记录。
4. 在 RHX 配好保存目录和文件名，然后开始 **Record**。仅单次刺激窗口做不保存的台架观察时可用 **Run**；眼跳任务真实刺激必须 Record。Stop 或 Trigger 模式会被脚本拒绝。
5. RHX 中打开 **Network → Remote TCP Control**，让命令端口在 `127.0.0.1:5000` 监听，显示 Pending。两个脚本不要同时占用该端口。
6. 使用原有 PsychoPy Python 启动其中一个脚本：

```powershell
& D:\Software\Psychopy\python.exe D:\Chenghang\FineVision\trodes_stim_once_gui_Intan.py
& D:\Software\Psychopy\python.exe D:\Chenghang\FineVision\Saccade_Elec_stim_Eyelink_Intan.py
```

单次窗口：先填写地址、通道范围和步长，再点击 **Connect to Intan RHX**。连接成功后这些连接参数锁定；波形和目标通道仍可编辑。

眼跳任务：默认仍为 `Simulate stimulation=True`。实际电刺激时改为 False。配置文件独立为 `params_Saccade_Elec_stim_Eyelink_Intan.json`，不会覆盖原 Trodes 任务的参数。

初始化会清除 RHX 中现有的刺激使能，包括其他端口、模拟输出及数字输出；任务使用 F1 触发。运行期间不要在 RHX 中手动按 F1、修改刺激参数或切换运行模式。退出时保留完保护尾段，再停止并保存当前记录、清除刺激配置，保持 Stop，不重新开启空白记录段。

## EyeLink RAW 校准（2026-10-21 修复）

眼跳任务读取现有 `eyelink_setting.json`，在会话配置中独立设置 `sample_source=raw`（全局为 gaze 也可启动）；全局非 RAW 时明确使用 `eyelink_raw_pupil_setting.json` 中当前右眼二维仿射校准。全局设置及原始校准文件不修改。会话目录保存 `eyelink_raw_settings.json` 和 `eyelink_raw_calibration_snapshot.json`，后者是本次在线计算实际加载的系数快照。

注视与目标窗口使用现有后端的 RAW 校准结果。眼跳时间仍由 EyeLink 原生 ENDSACC 事件提供，但空间起终点从事件边界附近（最多相差 2 ms）的右眼 RAW 样本计算：先完整二维仿射映射至屏幕像素，再换算视角，计算幅度与终点。RAW 模式不读取事件的 Host GAZE 起终点，不要求 Host GAZE 校准；这保留原生事件检测时序，不是另写一套从 RAW 速度识别眼跳的算法。

队列中的 RAW 样本和校准后屏幕位置另存 `raw_gaze_samples.jsonl`，眼跳结果保存在 `saccades.jsonl`。缺失边界样本、眨眼/瞳孔无效等情况标记无效，不用 Host GAZE 替代，不将瞳孔像素直接解释为视角。暂停时清空待判定 RAW 事件及短期缓存，避免跨暂停配对。

## 通道映射与计划

眼跳任务默认 128 通道：
`A-000:A-031,B-000:B-031,C-000:C-031,D-000:D-031`。
这是四个端口各连接 32 通道时的 RHX 原生名称；启动会逐一查询通道是否存在并启用，缺少通道就报错。列表顺序对应逻辑电极顺序，实际输出以 plan.json 的 intan_channel 为准；HW/nTrode 只是旧逻辑标签，不证明转接板或物理电极接点映射。

2026-10-22 眼跳任务改为每通道 8、14、20 µA 各一次，不做计划重复：
384 个电刺激条件 + 96 个插入 control + 10 个初始 precontrol = 490 个计划条件。
仍然每 4 个电刺激条件插入 1 个 control，control 位置均匀分布在 RF 内的 8×12 网格。
control 的亮度、大小、注视保持、奖励及失败重试规则沿用现有设置。
原失败重试仍保留，因此实际尝试次数可能超过 490，同一条件失败后也可能再次尝试。
共用 make_plan 默认仍为两次，眼跳任务显式指定 repeats=1，不改变其他调用者的旧协议。

### 同时连接两台 Intan

分别启动对应设备的 RHX 实例，并在设备选择窗口核对型号及序列号。
RHS 刺激/记录设备的 TCP 命令端口建议使用 5000；RHD 纯记录设备若启用 TCP，使用另一个端口，例如 5010。
眼跳任务的 Intan address 填 RHS 实例地址（默认 tcp://127.0.0.1:5000），实际端口不同时相应修改。

脚本按指定的 RHX 地址连接，不依赖 USB 插入顺序，不自动扫描或切换设备。
首先仅查询 get type，要求 ControllerStimRecord；误连 RHD 会关闭连接并报错，在此之前不会发设置、停录或刺激命令。
还会拒绝 synthetic/playback，并核对 128 个通道、30 kHz、1 µA 步长和 Record 模式。
连接日志 RHX_CONNECTED 记录地址、控制器类型和通道列表。
另一台设备的采集和保存由其 RHX 实例管理，本任务不会自动启动或同步它。

## 波形、极性和时序

眼跳任务保留 30 kHz 下每相 5 样本（166.6667 µs）、相间 2 样本（66.6667 µs）、周期 100 样本（3333.3333 µs，300 Hz）、每列 50 脉冲。方块标称持续时间仍为 166.6667 ms；最后一相结束为约 163.7333 ms。

Intan 显式设置 NegativeFirst、双相等幅等宽。单次 GUI 两个通道相同时，仅该通道负相优先输出，回流走硬件刺激地；两个通道不同时，分别配置负相优先和正相优先，并用同一个 F1 事件同步触发。它们是两个独立电流源，接线和实际电流波形需台架验证。

**此前 Trodes 实际输出的电流方向未得到物理确认，因此不能把 Intan 的 NegativeFirst 等同于已经测量证实的旧系统极性。**

本版本明确设置：EnableAmpSettle=True、MaintainAmpSettle=False、刺激前 settle=0、刺激后 settle=1000 µs、EnableChargeRecovery=False（双相波形自身等电荷）。这是明确的 Intan 配置，不宣称与未知的 Trodes 固件恢复策略相同。全局 UseFastSettle/HeadstageGlobalSettle、采集带宽及参考配置沿用 RHX 现有设置。

光电方块保持受试屏右下角 160×160 px、边缘 10 px。任务保留 `PD_ON`、`STIM_COMMAND` 等时刻。TCP 接受命令不能证明电流已经输出；`hardware_onset_verified=False` 会写入结果。丢失应答后禁止自动重发刺激。

## 离线检查

### Intan 眼跳响应窗口（2026-10-23）

取消 `Event arrival grace (ms)` 参数及额外接收等待。默认 `Response after stim (ms)` 为 300；control/precontrol 以 `stimoff_pc` 为基准，真实电刺激以 `stim_command_pc + 标称刺激时长` 为基准（并非硬件确认的结束时间）。眼跳自身起止时间仍需在事件窗口内，事件也必须在截止时间前收到并完成合格判定；截止后处理的事件不再改变该试次结果。control 仍需在截止前完成目标保持。

新 session 的日志版本为 4，记录 `response_timing_policy`；试次另记录 `response_deadline_reference`，首次选中合格眼跳时记录 `saccade_qualified_pc`。`saccade.received_pc` 仍为事件接收时间；`response_end_pc` 仍为逻辑结束时间；`response_finished_pc` 是循环实际退出时间，可能受一轮刷新/处理耗时影响略晚于截止，但不会获得额外判定宽限。原始眼跳日志可以继续记录截止后事件，用于离线分析。

已使用假 RHX TCP 服务检查：分包/粘包、错误反馈、参数读回、上传前停止、上传完成后恢复、文件名唯一、错误模式/采样率/步长/通道拒绝、未知触发结果不重发、单通道/双通道配置、32/128 通道计划。

原任务的眼跳、注视光电时序、运行中编辑、EyeLink 队列处理和暂停流程由复制后的行为测试检查。

这些是代码及模拟接口检查，尚未在真实 Intan、EyeLink、Arduino 和显示器上联调，也未测量物理电流和光电延迟。

依据：Intan 官方 [RHX TCP 文档与示例](https://intantech.com/files/RHX_TCP.zip)（包内文档标为 3.5.1）以及 [RHX 3.5.2 源码](https://github.com/Intan-Technologies/Intan-RHX)。下载的参考资料位于 `intan_reference`。

## 2026-10-22 参数编辑后的 EyeLink 链路恢复

普通 Space 暂停仍调用 frame()，持续处理眼动；旧版 N 参数窗口进入 Tk mainloop 后停止 frame()/drain()，这是长暂停后的已确认缺陷。
新版参数窗口使用同一 UI 线程约每 10 ms 消费暂停数据，不写入试次判定，EDF 仍由 EyeLink 持续记录。
窗口关闭及四点重校准结束后调用 SDK resetData()/dataSwitch() 重置链路接收，然后要求新队列样本不早于恢复起点，
且相对最新样本和 trackerTime 均不落后 50 ms，连续稳定 100 ms 后才允许继续。最多等 10 秒，失败则停止而不开始下一试次。
常规逐帧读队列若落后最新样本超过 500 ms，也会明确报错，避免用过期事件产生 nofix_2。
这些阈值是软件恢复检查，不代表眼跳物理延迟测量。离线测试通过；长暂停与 SDK 实际恢复仍需实机验证。
本次会话证明暂停后接收到旧事件，不能仅据此指定积压位于 DLL、操作系统或网络的哪一层。

## 2026-10-26 Control 成功条件

Intan 眼跳任务的 control 和 precontrol 不再要求 ENDSACC、眼跳幅度或眼跳终点条件。
仅根据实时有效右眼 gaze 判断：在原响应期限内进入目标窗口，并连续保持 Control hold (ms)。
目标与 fixation 重叠时，目标出现后已在窗口内也可以开始保持计时，不累计目标出现前的保持时间。
进入后未保持完成或中途离开仍按原 break_2 规则处理，未进入为 nofix_2；电刺激试次仍要求合格眼跳。
眼跳原始日志与链路完整性检查保留。试次增加 response_success_criterion 字段区分判定标准。
