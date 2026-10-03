# 实测数据档案（模型常数的出处）

> 本文档是仿真模型的"标定证书"。所有条目均标注测量条件与工具版本，
> 复测方法见 `tools/hwprobe/`。**修改 `models/` 中的常数前，先来这里登记新实测。**

测量环境（2026-10-03）：

- 板卡：A2000TM4 底板 + EK-TM4C1294XL 核心板，ICDI 序列号 `0F00CD37`，ICDI 固件 1224
- 探针：xpack OpenOCD 0.12.0-7 经 TI WinUSB 驱动直连（TI ICDI 驱动 2.2.1.0）
- 方法：GDB-RSP（读）+ Renode monitor mww（写）混合，CPU 暂停态逐寄存器读取
- 原始探针脚本：`tools/hwprobe/probe*.py`，原始输出 `probe*_result.txt`

## M-1 芯片身份

| 事实 | 值 | 探针 |
|---|---|---|
| CPUID | `0x410FC241`（Cortex-M4 r0p1） | probe4 §D |
| DID0 / DID1 | `0x100A0002` / `0x101FC06E`（双读稳定） | probe2/4/8 |
| Flash | FSIZE=`0x1FF` → 1MB | probe3/8 |
| SRAM | SSIZE=`0x3FF` → 256KB | probe3 |
| EEPROM | EESIZE=`0x00600600` → 6KB, 96 块 | probe5 |
| EEDONE（时钟开启后） | 0（模块空闲） | probe5 |

## M-2 时钟树（运行态实测）

| 事实 | 值 | 说明 |
|---|---|---|
| RSCLKCFG | `0x10000001` | USEPLL=1, PLLSRC=PIOSC, PSYSDIV=1 |
| PLLFREQ0 / 1 | `0x0080001E` / `0x00000B00` | MINT=30, Q+1=12 |
| 系统时钟 | **20.000000 MHz** | 16M×30÷12÷2；MOSC 路径(750MHz VCO)超规格排除 |
| SysTick RVR | `399999` | = 20ms@20MHz，与固件源码逐位吻合 |
| SysTick CSR | `0x00010007` | ENABLE=1, TICKINT=1, CLKSOURCE=1 |
| NVIC ISER0 | `0x00000000` | 无外设中断，纯轮询 |

**模型引用**：`models/a2000sim/fw_algorithms.py::SYSCLOCK_HZ`、Renode 平台 `systickFrequency`。

## M-3 运行态时钟门控（驻留固件的行为画像）

| RCGC 寄存器 | 实测值 | 含义 |
|---|---|---|
| RCGCGPIO (0x400FE608) | `0x00007FFF` | 全部 15 个 GPIO 端口时钟开启 |
| RCGCHIB (0x400FE614) | `0x00000001` | 休眠模块时钟开启 |
| RCGCPWM (0x400FE640) | `0x00000001` | PWM0 时钟开启 |
| RCGCADC / RCGCUART / RCGCSSI | 0 | ADC/UART/SSI 未启用（与 COM3 静默一致） |

PF3 PCTL=6 → **M0PWM3**（无源蜂鸣器复用已配置，PWMENABLE=0 未使能输出）。

## M-4 GPIO 实况（暂停态快照，确认暂停后读取）

| 端口 | DIR | DEN | 数据/备注 |
|---|---|---|---|
| K | 0x10/0x30（随固件相位变化） | 0x30 | STB=PK4 常输出；DIO=PK5 在读键帧内为输入 |
| M | 0x05 | 0x05 | PM0=CLK、PM2=有源蜂鸣器，均输出 |
| E | 0x11 | 0x11 | PE0/PE4 输出，AMSEL=0（未配模拟） |
| F | 0x00 / AFSEL=0x08 | 0x08 | PF3=M0PWM3 |
| J | 0x00 | 0x02 | PJ1 数字使能（浮空输入） |
| N | 0x03 | 0x03 | PN0/PN1 核心 LED，观测到翻转（固件在跑） |
| L | 0x00 | 0x00 | 全未配置（软件 I2C 未启用） |

## M-5 ADC0 现场实测（调试器驱动 ADC 完成真实转换）

| 事实 | 值 | 探针 |
|---|---|---|
| PE3(AIN0) 静息码 | ~1559–1578 → **~1260 mV**，5 次独立测量稳定 | probe7 |
| PE2(AIN1) 静息码 | ~1446–1460 → **~1170 mV** | probe7 |
| 连续 8 次触发 | 1725→1469 单调衰减（高阻节点被采样电容放电） | probe6/7 |
| 静置 600ms 后 | 恢复至 ~1260mV 稳定 | probe7 |
| 片上温度 | 码 1888 → **43.8°C**（后续 48/50°C，TS 通道建立时间效应） | probe7 |
| ADC0 PC（时钟开启后真值） | `0x7` | probe6 |

**模型引用**：`models/a2000sim/plant.py::FloatingPinModel` 复现"静置恢复/连续采样衰减"行为。

## M-6 EEPROM 块 0 原始数据（16 字）

```text
FFFFFFFF FFFFFFFF FFFFFFFF FFFFFFFF FFFFFFFF FFFFFFFF FFFFFFFF FFFFFFFF
FFFFFFFF FFFFFFFF 1CD1FFAD FFFFFFFF 736F7865 21657469 66663037 FFFFFFFF
```

小端解码 0x736F7865→"exos"、0x21657469→"ite!"、0x66663037→"70ff"：
**"exosite!70ff"** —— EK-TM4C1294XL 出厂 qs_iot（Exosite 云连接演示）写入的
设备标识残留。EEPROM 不随固件擦除消失，故此数据跨固件存活。

**模型引用**：`tests/test_measured_facts.py::test_eeprom_factory_pattern`。

## M-7 驻留固件考古

| 事实 | 值 |
|---|---|
| 驻留程序大小 | ~33 KB（有效内容至 0x81D4） |
| 向量表 | SP=`0x200002D0`，Reset=`0x2C9`，SysTick=`0xB55` |
| 特征串 | `AT+FREQ=0876<12`（@0x4E6D，射频模块 AT 指令） |
| 与磁盘 12 个候选 .axf/bin 比对 | 全不匹配（磁盘为重编译版本） |
| 全片 Flash 备份 | `tools/hwprobe/` 产物，1MB，0 坏块，39.9s |

## M-8 调试链路行为（影响探针与 FIL 设计）

1. TI ICDI 驱动即 WinUSB 类，OpenOCD 0.12 直连无需换驱动；
2. gdb 连接 → OpenOCD 自动暂停目标，断开默认恢复运行；
3. posted-write：写后立即读同址得旧值，隔一次事务后可见（探针必须推读）；
4. 会话老化后 halt 超时、块读偶发全零 → 重启 OpenOCD 痊愈；
5. 读未开时钟的外设 → DAP 停顿（error 0x7，返回零）；
6. cfg 脚本中 mdw 输出丢失：用 `-c` 参数、gdb-RSP 或 telnet mww 替代。
