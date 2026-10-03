# Renode 固件在环（FIL）目录

## 文件

- `a2000tm4.repl` — 平台描述（v0.2：CPU/存储/UART 真模型 + **内嵌 IronPython
  虚拟实验台外设**：GPIO K/M 位级双向对接 TM1638、ADC0 真 FIFO/RIS 语义、
  实验台控制块 0x50000000）
- `a2000tm4.resc` — 机器脚本（预置实测/就绪值 + 位带别名就绪位 + 固件加载）

## 准备

1. 安装 Renode ≥1.17（https://renode.io 便携版）。
2. 课程固件放入 `firmware/local/`（版权边界见 NOTICE.md）。

## 交互运行

```bash
cd <仓库根>
renode --console renode/a2000tm4.resc
start                          # 或 emulation RunFor "00:00:02"
```

## 实验台控制块（0x50000000）

monitor / Robot / 任何总线主都可读写：

| 地址 | 语义 |
|---|---|
| 0x00 W/R | 键注入：写 1..9 按下、0 释放；读=当前键号 |
| 0x10+i R | GRID(i+1) 解码显示值（0..9/0x0A..0x0F/0xFF 熄灭/0xEE 未知） |
| 0x20+i R | GRID(i+1) 原始段码（bit7=DP） |
| 0x30+i R | LED(i+1) |
| 0x40/0x44 W/R | CH0(PE3)/CH1(PE2) 引脚电压 mV（ADC 激励） |
| 0x48/0x4C R | CH0/CH1 最近采样码 |

示例：注入 3V 到 CH1 并按下键 5：

```
sysbus WriteDoubleWord 0x50000044 3000
sysbus WriteDoubleWord 0x50000000 5
```

## 自动冒烟

```bash
python tools/fil_smoke.py
```

两项断言（课程原始固件、未重编译）：
1. adc_demo：CH0=CH1=1250mV → GRID1-8 显示 "1551"；
2. demo：键注入 3→7→0，固件 key_code 逐步跟随。
