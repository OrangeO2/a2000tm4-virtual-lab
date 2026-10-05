# Renode 固件在环（FIL）目录

## 文件

- `a2000tm4.repl` — 平台描述（v0.4：CPU/存储/UART 真模型 + **内嵌 IronPython
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
| 0x40/0x44 W/R | CH0(PE3/AIN0，电流链) / CH1(PE2/AIN1，电压链) 引脚 mV（ADC 激励） |
| 0x48/0x4C R | CH0/CH1 最近采样码 |
| 0x50 R | DAC6571 完整 10 位码（0..1023） |
| 0x54 R | DAC6571 输出电压 mV（按 3.3V 参考） |
| 0x58 R | 已解码有效 DAC 写帧数 |
| 0x5C..0x5E R | 最后一个有效 DAC 帧的地址/MSB/LSB |

示例：向电压链 CH1/PE2 注入 3V 并按下键 5：

```
sysbus WriteDoubleWord 0x50000044 3000
sysbus WriteDoubleWord 0x50000000 5
```

## 自动冒烟

```bash
python tools/fil_smoke.py
```

脚本按本地可用固件独立执行并明确报告 PASS/SKIP，不再把缺失固件计成“全通过”。当前场景：
1. adc_demo：CH0=CH1=1250mV → GRID1-8 显示 "1551"；
2. demo：键注入 3→7→0，固件 key_code 跟随；
3. BuckPlant：按 CH0=电流、CH1=电压的物理映射做分窗闭环；
4. dac_demo：验证完整 10 位 DAC 码与 I2C 帧；
5. [M-5] 无功率板连续采样尾点基线回放（CH0=1427 / CH1=1313）。
