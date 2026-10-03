# Renode 固件在环（FIL）目录

## 文件

- `a2000tm4.repl` — 平台描述（v0.1：CPU/存储/UART 真模型 + 外设寄存器存储 stub）
- `a2000tm4.resc` — 机器脚本（预置实测/就绪值 + ADC 电压注入 + 加载固件）
- `tests/fil_adc_demo.robot` — 自动实测示例（renode-test）

## 准备

1. 安装 Renode ≥1.15（https://renode.io 下载便携版）。
2. 课程固件放入 `firmware/local/`（版权边界见根目录 NOTICE.md）：
   ```
   firmware/local/adc_demo.axf     # 来自课程 ADC_DEMO 工程 Objects/
   ```
3. 运行：
   ```bash
   cd <仓库根>
   renode --console renode/a2000tm4.resc
   ```
   正常现象：`LoadELF` 成功、`start` 后固件以 20MHz 运行、
   SysTick 每 20ms 驱动 TM1638 位拍（写入 gpiok/gpiom stub）。
4. 注入其他电压：改 `a2000tm4.resc` 中 `$adc_code`（12 位码，3300mV=4095）。

## 自动实测

```bash
renode-test renode/tests/fil_adc_demo.robot
```

测试内容：加载 adc_demo → 注入码 → 运行 → 从 RAM 符号 `digit[]` 读取
显示缓冲 → 断言十进制显示值与注入值一致（课程“单片机监测电压”指标的仿真预演）。
符号地址由 `tools/extract_symbols.py` 从课程工程的 .map 提取为
`firmware/local/symbols.json`。

## v0.1 已知限制

见 `docs/4-renode-fil-design.md`：两 ADC 通道同值、按键不可注入、
外设时钟瞬时就绪、无位时序概念——均已列入 v0.2/v0.3 路线图。
