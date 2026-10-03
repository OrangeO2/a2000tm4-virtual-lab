# 仿真用 TM4C1294NCPDT 寄存器地图（课程固件触达子集）

> 覆盖课程固件（demo/adc_demo/dac_demo 系列）实际会访问的寄存器区间，
> 以及 Renode 平台为"让原始固件跑通"而需要特殊处置的地址。
> 完整地图见 TivaWare `inc/hw_*.h`（本仓库不复制其内容）。

## 核心与存储

| 区间 | 内容 | Renode 处置 |
|---|---|---|
| 0x0000_0000–0x000F_FFFF | 1MB Flash（代码执行区） | MappedMemory，LoadELF 灌入 |
| 0x2000_0000–0x2003_FFFF | 256KB SRAM | MappedMemory |
| 0xE000_E000–0xE000_EFFF | NVIC/SysTick/SCB | Renode 内置 NVIC（systickFrequency=20MHz 实测值） |

## 系统控制（0x400FE000，实测课程固件会碰的寄存器）

| 地址 | 寄存器 | 固件行为 | Renode v0.1 处置 |
|---|---|---|---|
| 0x400FE000/004 | DID0/DID1 | （探针读） | 预置实测值 |
| 0x400FE060/070 | RCC/RCC2 | TM4C129 不使用（读得 0 为真值） | 存储即可 |
| 0x400FE0B0 | RSCLKCFG | SysCtlClockFreqSet 写 | 存储即可 |
| 0x400FE160/164 | PLLFREQ0/1 | 写 MINT/Q、置 PLLPWR | 存储即可 |
| **0x400FE168** | **PLLSTAT** | **忙等 LOCK 位（有限 32768 次）** | **预置 0x1（LOCK）** |
| 0x400FE608 | RCGCGPIO | SysCtlPeripheralEnable 写 | 存储 |
| 0x400FE638 | RCGCADC | 写 | 存储 |
| **0x400FEA08** | **PRGPIO** | **SysCtlPeripheralReady 忙等** | **预置 0x7FFF（全就绪）** |
| **0x400FEA38** | **PRADC** | 同上 | **预置 0x1** |
| 0x400FDFC0/C4 | FSIZE/SSIZE | （探针读） | 预置实测值 |

> 预置"就绪位"意味着仿真中外设时钟瞬间就绪——对课程固件的轮询式驱动完全等效，
> 这是刻意的简化（v0.1 限制，见 docs/4）。

## GPIO（每个端口 4KB 块，DATA 为掩码别名寻址）

| 端口 | 基址 | 课程用途 | 实测配置（暂停态） |
|---|---|---|---|
| E | 0x40024000 | PE2/PE3=ADC 输入、PE0/PE4 | DIR=0x11 DEN=0x11 |
| F | 0x40025000 | PF0=LED4、**PF3=M0PWM3 蜂鸣器** | AFSEL=0x08 PCTL nibble3=6 |
| J | 0x4003D000 | PJ0/PJ1 按键 | DEN=0x02 |
| K | 0x40061000 | **PK4=STB、PK5=DIO** | DEN=0x30 |
| L | 0x40062000 | **PL0=SDA、PL1=SCL**（软件 I2C→DAC6571） | 默认态 |
| M | 0x40063000 | **PM0=CLK**、PM2=有源蜂鸣器 | DIR=0x05 |
| N | 0x40064000 | PN0/PN1 核心 LED | DIR=0x03 |

**DATA 掩码别名**：地址 `base + (mask << 2)`，仅 mask 覆盖的位被写/读——
TM1638 位拍与软件 I2C 的每一位都经由它，是 FIL 层 GPIO 外设模型（v0.2）的核心语义。

## ADC0（0x40038000，adc_demo 实测序列）

| 地址 | 寄存器 | 固件行为 | Renode v0.1 处置 |
|---|---|---|---|
| 0x40038000 | ACTSS | 序列使能 | 存储 |
| **0x40038004** | **RIS** | **忙等序列完成位** | **预置 0x2（序列1 恒"完成"）** |
| 0x4003800C | ISC | 写清除 | 存储 |
| 0x40038014 | EMUX | 写 0（处理器触发） | 存储 |
| 0x40038028 | PSSI | 写触发 | 存储 |
| 0x40038060/064 | SSMUX1/SSCTL1 | 写通道/END 配置 | 存储（亦是"注入哪路"的解析依据） |
| **0x40038068** | **SSFIFO1** | **读 2 次 = CH0、CH1 采样值** | **预置 12 位注入码（v0.1 两路同值）** |
| 0x40038FC4 | PC | 写速率 | 存储（实测真值 0x7） |

## 其他被映射为 stub 的区间（防误访问）

Flash 控制器 0x400FD000、PWM0 0x40028000、EEPROM 0x400AF000、
WDT 0x40000000/1、I2C 0x40020000 起、SSI 0x40008000 起、TIMER 0x40030000 起。
课程固件对它们只有写或干脆不碰；v0.2+ 按需升级为真模型。
