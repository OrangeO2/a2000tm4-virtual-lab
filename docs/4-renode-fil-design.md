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
