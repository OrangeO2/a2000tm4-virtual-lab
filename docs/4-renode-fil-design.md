# Renode 固件在环（FIL）平台：设计、v0.1 限制与路线图

## 设计原则

1. **运行课程原始 .axf，不改一行固件**——仿真的价值在于测试"将要上板的那个二进制"。
2. 每个非平凡常数都要能追溯到 `docs/2-measured-board-facts.md`。
3. v0.1 用"**预置寄存器 + 访问观测**"而不是自定义外设模型，
   把工程量集中在正确性可验证的地方；v0.2 起再升级为真正的外设模型。

## v0.1 平台构成（renode/a2000tm4.repl）

```
CPU.CortexM (cortex-m4f) + NVIC (systickFrequency=20_000_000，实测 M-2)
Flash 1MB @0x0 + SRAM 256KB @0x20000000（LoadELF 直灌）
UART0 (PL011) @0x400C000 → showAnalyzer（串口输出可捕获）
SYSCTL/GPIO/ADC0/PWM/EEPROM/I2C/... → MappedMemory 存储型 stub
监视器预置：PLLSTAT.LOCK=1、PRGPIO=0x7FFF、PRADC=0x1、ADC0.RIS=0x2、
           ADC0.SSFIFO1=注入的 12 位电压码
```

固件在环已验证/预期通过的行为：

- `SysCtlClockFreqSet(...)`：写 PLLFREQ/RSCLKCFG，读 PLLSTAT 立即"锁定"，正常走 PLL 分支；
- `SysCtlPeripheralEnable/Ready`：RCGC 写入 + PR 预置 → 立即就绪；
- `adc_demo`：GPIO 位拍 TM1638 → 写入 GPIO K/M stub（可用监视器读回），
  ADC 读 FIFO 得到注入码 → 数码管显示注入电压对应的十进制值；
- `dac_demo`：软件 I2C 位流写入 GPIO L stub → 可从访问日志解码 DAC 码值。

## v0.1 已知限制（刻意的）

| 限制 | 原因 | v0.2 方案 |
|---|---|---|
| ADC 两通道读数相同 | SSFIFO 无弹出语义（存储型 stub） | ADC0 升级为 Python/C# 外设：PSSI 触发→从附着激励采样→RIS 置位→FIFO 真弹出 |
| 按键无法注入 | GPIO DATA 读返回的是存储的锁存值 | GPIO 端口外设化：DIR/DEN/DATA 别名语义 + 虚拟 TM1638 芯片在 DIO 上驱动键值 |
| 外设时钟瞬时就绪 | PR 位为静态预置 | SYSCTL 外设化：RCGC→PR 联动（对课程固件等效） |
| 无时序仿真 | 无位时序概念 | 层面不同：位时序由 `models/a2000sim/tm1638.py` 在事件流上建模（与真实板逻辑分析仪共用解码器） |

## 实测验证记录（2026-10-03，Renode 1.17.0）

课程原始 `adc_demo.axf`（未重编译）在平台上完整通过 2s 虚拟时间运行：

```
[INFO] cpu: Setting initial values: PC = 0x2C9, SP = 0x20000290.
[INFO] a2000tm4: Machine started.
（RunFor 2s 后读取 RAM）
0x20000018 = 0x01312D00   ← ui32SysClock = 20,000,000（SysCtlClockFreqSet 返回值与实板逐位一致）
digit[0..3] = 01 05 05 02 ← 注入 ADC 码 1552 被固件采样并显示为十进制 "1552"
```

过程中发现并解决的两个**平台级**问题（对任何 TM4C1294 Renode 适配都适用）：

1. **位带别名（bit-band alias）**：TivaWare 的 `HWREGBITW`（SysCtlPeripheralEnable/
   Ready 的实现）写的是位带别名地址 `0x42000000 + ((reg-0x40000000)<<5) + bit*4`。
   例如 RCGCGPIO Port K 就绪位落在 `0x43FD4124`。Renode 1.17 无内建位带，
   v0.1 用 `sysctl_bitband` 存储块 + 预置 PR 就绪位解决。
2. **MOSC 起振等待**：`SysCtlClockFreqSet` 对 OSC_MAIN 会轮询
   `RIS.MOSCPUPRIS`（0x400FE050 bit8）524288 次，仿真中恒 0 → 返回 0 →
   SysTick 完全失速。预置该位后时钟函数正常返回 20000000。

## v0.2（已实现）：虚拟实验台外设

`renode/a2000tm4.repl` 内嵌 IronPython 外设（单实例多地址注册，经
`request.Absolute` 路由）替代了 GPIO K/M 与 ADC0 的存储 stub：

| 挂载点 | 语义 |
|---|---|
| 0x40061000 (GPIO K) | DATA 掩码别名读写（掩码=addr[9:2]）、DIR/DEN、锁存器；PK4/PK5 电平变化喂给 TM1638 状态机 |
| 0x40063000 (GPIO M) | 同上；PM0 边沿驱动 TM1638 时钟 |
| 0x40038000 (ADC0) | PSSI 触发→按 SSMUX1 通道序采样激励→FIFO 压栈→RIS 置位；SSFIFO 读=弹出；ISC 清除 |
| 0x50000000 (控制块) | 0x00 键注入（1..9/0 释放）；0x10+i GRID 解码值；0x20+i 段码；0x30+i LED；0x40/0x44 CH0/CH1 毫伏注入；0x48/0x4C 最近采样码 |

实测（Renode 1.17.0）：

- adc_demo：注入 CH0=CH1=1250mV → 码 1551 → GRID1-8 解码显示 "1551"×2；
- demo：键注入 3→7→0，固件 `key_code`（0x20000019）逐步跟随；
- 悬空引脚行为不再出现（ADC 输入由激励显式给定），存储 stub 时代的两路同值限制解除。

IronPython 注意事项（踩坑实录）：
1. 脚本体每次总线访问重新执行、作用域持久——状态初始化必须在 `request.IsInit` 下；
2. 模块级 `global` 声明会报 "assigned to before global declaration"，直接删除；
3. `filename:` 属性按进程 CWD 的 `File.Exists` 解析（便携版会改 CWD）→ 用内嵌
   `script: '''...'''` 形式规避；三引号内不能出现 `'''`；
4. 多地址注册经 `request.Absolute` 区分（`Offset` 每个注册点独立归零）。

## v0.3（已实现）：被控对象闭环

`a2000sim/plant.py::BuckPlant`（现象学模型）：软启动线性爬升（C8 选型 30ms 量级，
FIL 场景拉长到 1.6s 以便观察）、负载阶跃跌落（ΔI 成比例）与一阶恢复、
评分口径电流 I=Vout/R_load。信号链经 VOLTAGE_CHAIN/CURRENT_CHAIN 映射到
CH0(PE3, 电压)/CH1(PE2, 电流)。

`tools/fil_smoke.py` 场景 3 实现了**分窗协同仿真**：主机侧 BuckPlant 与
Renode 固件按全局虚拟时间分窗同步——每窗把 plant(t) 的调理后引脚电压写入
控制块 0x40/0x44，RunFor 推进后回读 GRID 解码显示。四状态精确断言全过：
软启动中点（969/380）、稳态（3102/1216）、负载阶跃（3102/620）、
阶跃后含跌落恢复（3066/613，现象学跌落被固件如实采样）。

**时序发现（重要）**：Renode 全局虚拟时钟与 CPU 本地时间存在**滞后**
（Python 外设处理耗时使固件在全局时间上"欠账"，跨 RunFor 累计），
实测固件显示滞后激励约 2-3 倍窗口。因此 FIL 断言必须在"充裕追赶"之后
读取终态，不能做逐窗精确对时；pytest 侧的模型级时序测试不受影响。

## v0.4（已实现，验证部分通过）：GPIO L 软件 I2C + 虚拟 DAC6571

实验台外设新增 GPIO L（PL0=SDA/PL1=SCL）注册与 I2C 解码器：START/STOP 边沿、
SCL 上升沿位锁存、第 9 脉冲 ACK 跳过、地址 0x98 过滤、DAC 码 = raw>>2。
控制块新增 0x50（DAC 码）/0x54（输出 mV）/0x58（帧数）/0x5C-5E（最后帧字节）。

课程 dac_demo 需本地重编译（源码含已知的 1MHz 时钟请求异常——课程注释本意
20MHz，见 docs/2；仿真中 1MHz 请求导致 SysTick 1kHz 中断风暴）。

**已验证**：I2C 位流解码工作（帧计数随固件写递增）、控制块回读 DAC 码/电压。
**已知问题（观察项，未计入失败）**：dac_demo 以 ~50Hz 风暴写 PORT L（帧计数
≈ 虚拟秒数 × 50）且显示刷新被撕裂——疑似 SysTick 处理器在虚拟时间滞后补偿下
风暴式触发，与 Python 外设墙钟开销耦合。需专门排查（候选：提高脚本执行效率、
改用 C# 外设、或 Renode 时间域配置）。设 FIL_SMOKE_STRICT=1 可使其计入失败。

**IronPython/Renode 踩坑补充**：外设脚本体按**函数局部作用域**执行——模块级
（顶层）赋值是局部变量，与函数内 `global` 声明的模块全局**脱节**；可变状态
必须统一放状态字典（本仓库用 `S[...]`），在 IsInit 时重建；函数内 `global`
声明的名字不得在顶层同作用域先赋值（编译错）。

## 实板数据回填（probe7 → 仿真对齐）

bench 默认激励已从占位值（1250/1250mV）改为 [M-5] 实测的"无功率板连续采样
尾点"（PE3=1150mV→码1427；PE2=1058mV→码1313，PE2 尾点为估计值）；
`fil_smoke` 场景 5 断言固件显示与实板基线一致。悬空引脚动态模型
（FloatingPinModel）参数同步精调（衰减 0.32/样本、恢复 tau 0.15s），
pytest 含实测序列校验（±8 码）。待功率板实件接入后，将以同协议回填
VOLTAGE_CHAIN/CURRENT_CHAIN 的实测增益（当前为原理图理论值）。

## v1.0 验收预演（tools/acceptance_rehearsal.py）

按评分规则表 2 逐项预演，输出记分卡（2026-10-05 首跑 50/50）：

| 项 | 满分 | 仿真方式 | 首跑结果 |
|---|---|---|---|
| 单片机监测电压 | 5 | FIL：固件显示码 ×标定链反演 vs plant 真值 | 误差 0.8mV → 5 |
| 单片机监测电流 | 5 | 同上（0.98A 与 0.8A 两条件） | 误差 ≤0.4mA → 5 |
| 输出电压绝对精度 | 10 | BuckPlant 稳态（5.1Ω/空载） | 4999/5000mV → 10 |
| 负载调整率 | 5 | 模型 5.1Ω vs 10Ω | ΔV=0 → 5 |
| 电压调整率 | 5 | 模型 Vin 10→20V（线调整率 50ppm/V 设计值） | ΔV=2.5mV → 5 |
| 过流保护和恢复 | 10 | BuckPlant 打嗝现象学（2.5Ω 触发/5.1Ω 恢复） | 10 |
| 输出纹波 | 20 | **N/A 需实机**（准静态模型无开关纹波） | — |
| 电源转换效率 | 40 | **N/A 需实机**（模型无损耗） | — |

BuckPlant 同步新增：vin_mv/line_reg_ppm_per_v（线调整率现象学）、
ocp_trip_a/ocp_hiccup_s/ocp_enabled（过流打嗝：触发→输出快速衰减（≈I/C 物理速率
2A/940µF≈2128V/s）→重试间隔后负载安全则自动恢复）。评分边界函数见
a2000sim/scoring.py（阈值逐字对齐评分表，pytest 边界用例覆盖）。

## 测试策略

- **模型层（CI 必测）**：`pytest tests/` —— 协议、被控对象、算法、实测交叉验证。
- **FIL 层（本地/CI 可选）**：`renode/tests/*.robot`（renode-test）：
  1. 平台语法冒烟：加载 .repl 不报错；
  2. FIL 冒烟：加载用户本地固件 → 跑 N 条指令 → 读 digit[] 缓冲 → 断言显示值；
  3. 指标断言：注入电压 → 固件显示 → 换算误差 ≤ 0.02V（课程满分档）。

  符号地址（digit/led 缓冲）由 `tools/extract_symbols.py` 从课程工程的 .map 文件提取，
  放入 `firmware/local/symbols.json`（不入库）。

## 与实板工具的关系

`tools/hwprobe/` 的探针脚本同样读取这些寄存器——**仿真平台和实板探针共享同一张
寄存器地图（docs/3）与同一套协议模型（models/）**。任何一边发现事实变化，
两边同步修订，这就是"复刻"的含义。
