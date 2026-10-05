# hwprobe — 真板硬件探针（调试口实证工具集）

本目录收录对真实 A2000TM4/EK-TM4C1294XL 板卡做调试口实证的 Python 探针脚本。
`a2000sim/` 中标为 `[M-x]` 的实测常数来自这些探针与 `docs/2-measured-board-facts.md`；
数据手册、原理图理论值和现象学参数则分别标记，不再笼统声称所有模型参数都是实测。

## 工作原理

经 TI ICDI 调试口（WinUSB 驱动，无需换驱动）连接 OpenOCD，
用 GDB 远程协议/monitor 命令直读、直写芯片寄存器：

```bash
# 终端 1：启动 OpenOCD（gdb 3333 + telnet 4444）
xpack-openocd/bin/openocd.exe -s scripts -f board/ti_ek-tm4c1294xl.cfg \
    -c "gdb_port 3333" -c "telnet_port 4444" -c "tcl_port disabled"

# 终端 2：运行探针
python probe8.py
```

| 脚本 | 功能 |
|---|---|
| `probe4.py` | 分层写路径诊断 + 身份寄存器 + SysTick/NVIC 快照 |
| `probe5.py` | EEPROM 读取（容量/块 0 数据，含出厂 qs_iot 痕迹） |
| `probe7.py` | ADC 实测（PE2/PE3 静息电压、连续采样衰减、片上温度） |
| `probe8.py` | 全片 1MB Flash 备份（默认 `results/probe8_flash.bin`，可用 `HWPROBE_SKIP_FLASH=1` 跳过）+ TM1638 显示写 + 键扫描回读 |

探针文本输出默认写入 `tools/hwprobe/results/`；可用 `HWPROBE_OUT_DIR` 改目录。Flash 路径可用 `HWPROBE_FLASH_OUT` 覆盖。

## 实测结论速览（详见 docs/2-measured-board-facts.md）

- 芯片：TM4C1294NCPDT（CPUID 0x410FC241，1MB Flash / 256KB SRAM / 6KB EEPROM）
- 时钟：20.000 MHz = PIOSC 16M × MINT30 ÷ 12 ÷ 2（晶振路径未使用）
- 系统时钟函数返回值 20000000 与 SysTick 重装值 399999 逐位自洽
- 悬空 ADC 引脚 ~1.2V：静置恢复、连续采样单调衰减
- EEPROM 残留出厂 qs_iot 数据（"exosite!70ff"）

## 行为注意事项（踩坑实录）

1. gdb 客户端连接时 OpenOCD 自动暂停目标，断开默认恢复运行；
2. posted-write：写后立即读同址得旧值，需隔一次事务再校验；
3. 会话老化后 halt 超时 → 重启 OpenOCD；
4. 读未开时钟的外设寄存器 → DAP 停顿（返回零）；
5. 探针原则上只读；写操作仅限时钟门控/ADC 配置等并在结束前恢复。

## 复用到其他板卡

1. OpenOCD 启动后先跑 `probe4.py` 确认身份寄存器；
2. 若烧录报错，检查 Keil 工程 uvoptx 里的 ICDI 序列号是否为当前板
   （Debug → Settings → Stellaris ICDI 重选）；
3. 更换实验内容时优先复用 probe7 的 ADC 方法论（静置→单次转换）。
