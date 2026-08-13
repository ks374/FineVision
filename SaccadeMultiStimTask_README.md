# SaccadeMultiStimTask

这个任务复用 `SaccadeTask.py` 的完整时序与成功判定，只把单一椭圆替换为启动时生成的固定刺激条件表。

运行：

```powershell
python SaccadeMultiStimTask.py
```

## 参数界面

参数按类别显示在标签页中：

- `Session / 会话`
- `Fixation / 注视`
- `Timing / 时间`
- `Plan / 条件表`
- `Position / 位置`
- `Shape / 形状`
- `Display / 屏幕`
- `Reward / 奖励`

原来的 `SaccadeTask.py` 也使用相同的分类界面。

窗口底部会实时显示当前参数生成的 trial 数：

```text
Planned trials: 总数 = 正式刺激数 + control 数（组数 × control 位置数 × 2）
```

修改任一位置、形状、方向、颜色、强度、重复次数或 control 组数后，该行会
立即更新。输入尚未完成或范围无效时显示 `—`，不会弹出错误窗口。

角度、window 大小等声明为小数的字段始终允许输入小数；即使上次保存的是
整数（例如 `3`），下次打开时也仍可改为 `2.5`。

## 条件如何生成

下列数值均使用“最小值、最大值、步长”生成闭区间序列：

- 刺激 X 位置
- 刺激 Y 位置
- 椭圆长轴
- 椭圆短轴
- 椭圆方向
- 亮度等级

颜色使用 `Stim Colors (comma-separated)` 指定，例如：

```text
R,G,B,Gray
```

程序对位置、长短轴、颜色和亮度做笛卡尔积，再乘以
`Repeats Per Condition`，由此得到正式刺激条件；随后按照 `Control Groups`
生成位置 control，形成整个 session 的固定条件表。
最大值与最小值之差必须能被步长整除。

椭圆方向使用：

- `Stim Orientation Min (deg)`
- `Stim Orientation Max (deg)`
- `Stim Orientation Step (deg)`

有效范围为 `0 ≤ orientation < 180°`。因为椭圆的 180° 与 0° 在视觉上
相同，所以不再重复生成 180° 条件。例如 `0 / 150 / 30` 会生成
0、30、60、90、120 和 150°。

`Condition Order` 有两种选择：

- `Sequential`：按参数顺序呈现。
- `Randomized`：使用 `Random Seed` 将整张条件表一次性打乱。同样的参数和 seed 会得到同样的顺序。

## 亮度与颜色标定

0–20 级的实际 RGB 来自：

```text
屏幕RGB_0-20等亮度刺激标定.xlsx
```

运行时首先载入 `stim_calibration_0_20.json`，保证原有 0–20 级完全
不变。21 级以后使用 `stim_calibration_extension_to_255.json` 中的
两次测量平均曲线做分段线性反插值，亮度步长继续使用 1.175 cd/m²，
直到该颜色的输入值达到 255。

各颜色可用的最高等级为：

- R：36
- G：127
- B：20
- Gray：182

如果一个范围超过某个颜色的最高等级，该颜色只生成其标定范围内的
条件。例如设置 1–36 且选择全部颜色时，R/G/Gray 生成 1–36 级，
B 仍只生成 1–20 级。等级 0 不再作为正式刺激参数使用。

`Background Gray Level (0-182)` 控制整个任务的灰色背景，使用同一套 Gray
标定。默认第5级，对应 RGB=(40,40,40)，目标亮度约 5.875 cd/m²。该参数
只允许在 session 开始前修改，运行中按 `N` 时会显示为灰色锁定项。

## Position control

`Control Groups` 是非负整数。每一组 control 包含：

- 参数界面指定的中央 fixation 位置；
- 当前 stimulus 网格中的所有不重复位置。

如果中央位置本来就在 stimulus 网格中，则只生成一次。例如当前 stimulus
位置共有 49 个且包含中央点，`Control Groups = 1` 会生成 98 个 control（49 对）；
若不包含中央点，则会生成 100 个 control（50 对）。

Control trial：

- 从 trial 开始就在该 control 的位置显示 fixation 点；
- 使用正常的 fixation 获取时间和 fixation window；
- 要求持续注视随机的 `Fixation Duration Min/Max` 时间；
- 不进入 gap 和 stimulus 阶段；
- 成功状态记为 `Control_Success` 并给水；
- 获取失败或中途破坏注视时不奖励，并重复同一 control 位置。

`Sequential` 模式下成对 control 会均匀穿插在正式刺激之间；
`Randomized` 模式下则把每对 control 作为不可拆分的块，与正式刺激一起按 seed
打乱。

## 失败重试与 trial 数

正式刺激只有在该 trial 为 `Success` 时才会推进。任何失败状态都会原样
重试当前条件，位置、形状、颜色和亮度都不改变。Control 也只有成功完成
指定位置的注视后才推进。

因此启动时固定的是“计划成功条件数”，不是最终尝试次数：

```text
最终尝试次数 = 计划条件数 + 正式刺激和 control 的失败重试次数
```

## 运行中修改参数

按 `N` 后，当前 trial 会先正常结束，任务再在下一个 trial 前打开参数
窗口。窗口中灰色项目属于固定条件表，不能修改，包括：

- 刺激位置、形状、方向、颜色和强度；
- control 组数、重复次数、条件顺序和随机 seed；
- subject、fixation 位置以及显示器几何参数。

仍可修改的运行参数包括：

- fixation window 和 stimulus window 大小；
- fixation、gap、刺激显示、反应窗和目标保持时间；
- fixation 获取时间、ITI、timeout 和给水时间。

确认后只更新这些运行参数，不会重新生成条件表、改变当前条件顺序或重置
已经完成的进度。

## CMD 成功率

每次尝试结束后会显示：

- 从 session 开始至今的总体成功率；
- 最近40次尝试的成功率。

`Success` 和 `Control_Success` 都计为成功，失败重试计入总尝试
次数。

## 输出

每个 session 会保存：

- `SaccadeMultiStim_condition_plan_<timestamp>.csv`：本次实际使用的完整条件顺序。
- `SaccadeMultiStim_parameters_<timestamp>.json`：本次参数快照。
- `SaccadeMultiStim_task_log_<timestamp>.csv`：每次尝试的行为与条件信息。
- `SaccadeMultiStim_eye_log_<timestamp>.csv`：连续眼动数据。

行为日志中的 `Condition_Index` 在失败重试时保持不变，
`Attempt_For_Condition` 会增加；成功后才进入下一个 condition。

## 成对 control 与在线校准检查

每个 control 位置现在连续呈现两次；无论条件顺序是 `Sequential` 还是
`Randomized`，同一对的第 1、2 次都不会被正式 trial 分开。一次失败仍会原位
重试，成功后才进入同一对的下一次。

每次成功 control 使用注视结束前最后 100 ms 的有效 gaze 计算中心，并把中心、
XY 误差和二维误差写入任务 CSV 与 EyeLink EDF message。只有同一对 control 的
两次二维误差都超过 `Control Gaze Error Threshold (deg)` 时，任务才会在 trial
边界暂停并显示红色校准警告。阈值可在按 `N` 打开的运行中菜单里修改，而且必须
小于 fixation window 半径。

EyeLink 模式的运行中菜单有三个按钮：蓝色“确定”、蓝色“重新校准”和红色
“取消”。重新校准会隐藏原任务显示，在 screen 1 新建独立的全屏校准窗口，停止
采样记录并调用 EyeLink 原生 setup/calibration。校准成功后窗口自动退出并恢复
原任务；也可以在任务电脑按 `Esc` 放弃校准并返回。这个 `Esc` 会在恢复任务前被
清除并短暂屏蔽，不会再同时结束 Saccade session；回到任务一秒后重新按下的
`Esc` 仍会正常停止任务。Host 上原来的 EDF 始终保持打开，因此校准前后的任务
数据仍属于同一个 EDF。QY 模式没有 EyeLink 重新校准按钮。
