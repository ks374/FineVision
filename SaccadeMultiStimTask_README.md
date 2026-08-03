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
Planned trials: 总数 = 正式刺激数 + control 数（实际 control 比例）
```

修改任一位置、形状、方向、颜色、强度、重复次数或 control 比例后，该行会
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
`Repeats Per Condition`，由此得到正式刺激条件；随后按照
`Control Trial Proportion (0-1)` 插入空白 control，形成整个 session
的固定条件表。
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

## Blank control

`Control Trial Proportion (0-1)` 表示 control 占整张计划条件表的目标
比例，例如 `0.1` 表示约 10%。因为 trial 数必须为整数，界面在开始前会
同时显示实际比例。

Control trial：

- 不画椭圆刺激，也不画刺激窗；
- 无论猴子是否完成注视或眼跳，均给水；
- 日志状态记为 `Control_Reward`；
- 给水后直接推进到下一个条件，不会重试。

`Sequential` 模式下 control 会均匀穿插在正式刺激之间；
`Randomized` 模式下则与正式刺激一起按 seed 打乱。

## 失败重试与 trial 数

正式刺激只有在该 trial 为 `Success` 时才会推进。任何失败状态都会原样
重试当前条件，位置、形状、颜色和亮度都不改变。Control 始终给水并推进。

因此启动时固定的是“计划成功条件数”，不是最终尝试次数：

```text
最终尝试次数 = 计划条件数 + 正式刺激的失败重试次数
```

## 运行中修改参数

按 `N` 后，当前 trial 会先正常结束，任务再在下一个 trial 前打开参数
窗口。窗口中灰色项目属于固定条件表，不能修改，包括：

- 刺激位置、形状、方向、颜色和强度；
- control 比例、重复次数、条件顺序和随机 seed；
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

`Success` 和必定给水的 `Control_Reward` 都计为成功，失败重试计入总尝试
次数。

## 输出

每个 session 会保存：

- `SaccadeMultiStim_condition_plan_<timestamp>.csv`：本次实际使用的完整条件顺序。
- `SaccadeMultiStim_parameters_<timestamp>.json`：本次参数快照。
- `SaccadeMultiStim_task_log_<timestamp>.csv`：每次尝试的行为与条件信息。
- `SaccadeMultiStim_eye_log_<timestamp>.csv`：连续眼动数据。

行为日志中的 `Condition_Index` 在失败重试时保持不变，
`Attempt_For_Condition` 会增加；成功后才进入下一个 condition。
