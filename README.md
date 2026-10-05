# A2000TM4 Virtual Lab — 课程开发板（TM4C1294NCPDT + TM1638）无实物仿真实验台

> 把上海交大《工程实践与科技创新 III-A》使用的 **A2000TM4 实验底板 + EK-TM4C1294XL 核心板**
> 完整复刻为可仿真、可自动实测的虚拟实验台：在没有真实板卡的情况下，
> 直接运行课程原始固件、注入虚拟电压、捕获虚拟显示、断言课程验收指标。

---

## 这个仓库提供什么

| 层 | 内容 | 状态 |
|---|---|---|
| **硬件档案（docs/）** | 基于调试口实测的板卡拆解：芯片身份、时钟树、寄存器实况、EEPROM、ADC 现象，以及尚待完成的功率板调理标定 | ✅ 核心数字板事实已实测；功率级/调理链仍明确区分理论值、现象学参数与待回填实测值 |
| **参考模型层（a2000sim/ + tests/）** | TM1638 位级协议模型、DAC6571 软件 I2C 模型、稳压源+信号调理"被控对象"模型、课程算法（滑动窗口平均/迟滞门限/线性标定）——附带与**实测数据**交叉验证的测试 | ✅ `pytest` 全绿（CI 强制） |
| **固件在环层（renode/）** | Renode 平台 + 虚拟实验台外设（内嵌 IronPython）：TM1638 位级双向对接（**键注入** + 显示捕获）、ADC0 双通道动态电压注入（真 FIFO/RIS 语义）、实验台控制块 0x50000000 | ✅ 已验证：课程 adc_demo.axf 与 demo.axf 均实测通过（电压→显示 "1551"；键 3/7/0 注入→key_code 跟随） |
| **实板工具（tools/hwprobe/）** | 本项目配套的真板探针：经 ICDI 调试口直读寄存器、实测 ADC/EEPROM、全片 Flash 备份——仿真模型的每个常数都来自它们 | ✅ 可直接复用于任何一块板 |

## 为什么不是"再写一个模拟器"

项目里的非平凡常数都应有**来源类型**：真板实测 `[M-x]`、数据手册 `[DS]`、原理图/课程资料，或明确标注为理论/现象学假设。`docs/2-measured-board-facts.md` 只承载真板实测，不把设计值冒充测量值：

- 系统时钟 **20.000 MHz** 是实测的：PIOSC 16M × MINT30 ÷ 12 ÷ 2（25 MHz 晶振路径被 VCO 规格物理排除），
  且与固件 SysTick 重装值 `399999` 逐位自洽；
- ADC 悬空引脚 ~1.2 V 漂移、静置恢复、连续采样衰减——真实板实测曲线，直接成为仿真模型的行为规范；
- EEPROM 里 `"exosite!70ff"` 的出厂痕迹、TM1638 的二极管键矩阵接法——全部进入模型假设。

**被控对象（Plant）模型**直接编码课程验收指标，因此仿真测试断言的就是评分规则：

```text
电压监测误差 ≤ 0.02 V（满分档） / ≤ 0.05 V（合格档）   ← 测试用例自动判定
电流监测误差 ≤ 0.01 A（满分档） / ≤ 0.05 A（合格档）
```

## 快速开始

### 1. 跑通参考模型测试（无任何依赖）

```bash
pip install -e ".[test]"
pytest tests/ -v
```

### 2. 用 TM1638 协议模型做一次"虚拟显示"

```python
from a2000sim.tm1638 import TM1638, TM1638Driver

chip = TM1638()                      # 虚拟芯片
driver = TM1638Driver(chip)          # 位级驱动（复刻课程 tm1638.c 时序）
driver.init()
driver.refresh(digit=[1,2,3,4,5,6,7,8], pnt=0x04, led=[1]*8)
print(chip.render())                 # '    1234.5678' 之类的人类可读画面
print(hex(chip.display_ram[0]))      # 0x06 → 数字 1 的段码
```

### 3. 固件在环（需要 Renode + 课程固件）

课程固件（demo.axf / adc_demo.axf 等）属课程方版权，不入库——放到
`firmware/local/`（已 gitignore）后：

```bash
renode --console renode/a2000tm4.resc     # 交互式
# 或：按本地已有课程固件独立执行各 FIL 场景，并明确报告 PASS/SKIP
python tools/fil_smoke.py
```

平台细节、v0.1 已知限制与路线图见 `docs/4-renode-fil-design.md`。

## 仓库结构

```
├── docs/                     # 实证硬件档案（先读这个）
│   ├── 1-hardware-a2000tm4.md       # A2000TM4 硬件拆解（调试口实测版）
│   ├── 2-measured-board-facts.md    # 实测数据档案（模型常数的出处）
│   ├── 3-tm4c1294-register-map.md   # 仿真用寄存器地图
│   └── 4-renode-fil-design.md       # 固件在环平台设计/限制/路线图
├── a2000sim/          # Python 参考模型（纯逻辑，可独立使用）
│   ├── tm1638.py             # TM1638 位级协议 + 虚拟芯片 + 段码表
│   ├── dac6571.py            # 软件 I2C 解码 + DAC 输出模型
│   ├── plant.py              # 稳压源 + TLV2372 信号调理 + ADC 编码链
│   ├── fw_algorithms.py      # 课程算法：滑动窗口平均/迟滞/线性标定
├── tests/                    # pytest（含实测数据交叉验证）
├── renode/                   # Renode 平台（.repl/.resc；FIL 回归由 tools/fil_smoke.py 驱动）
├── tools/hwprobe/            # 真板探针（ICDI 直读/Flash 备份/ADC 实测）
└── .github/workflows/ci.yml  # pytest + Renode 平台语法检查
```

## 版权与边界

- 本仓库**只包含原创代码与实测事实**；课程固件源码/二进制（© 上海交大教学组）
  不入库，由使用者按课程授权在本地放入 `firmware/local/`。见 `NOTICE.md`。
- 段码表、寄存器地址、指令码等属于 TI 公开数据手册 / 课程公开讲义中的事实性数据。

## 路线图

- [x] v0.1 文档 + 参考模型 + Renode 基础平台（固件可跑通、ADC 静态注入、显示捕获）
- [x] v0.2 GPIO/ADC 升级为 Renode Python 外设：TM1638 总线级双向对接（键注入 ✓）+ ADC0 真 FIFO/RIS 语义（双通道动态电压注入 ✓）
- [x] v0.3 被控对象闭环：BuckPlant（软启动/负载阶跃/调理链）分窗协同仿真，固件显示四状态精确断言（含课程满分档误差口径）
- [x] v0.4 GPIO L 软件 I2C 解码器 + 虚拟 DAC6571 外设模型（dac_demo 全链路闭环验证：键注入→码调整→I2C 帧解码）
- [ ] v1.0 一键回归：`pytest` + `renode-test` 全绿即视为通过一次"课程验收预演"

## 致谢

- [Renode](https://renode.io)（Antmicro，MIT）— 固件在环仿真框架
- [tm4c-gcc-renode-template](https://github.com/kasattejaswi/tm4c-gcc-renode-template) — TM4C123 平台写法参考
- TI TivaWare / TM4C1294 / TM1638（Titan Micro）公开数据手册 — 事实性数据来源
- 上海交大《工程实践与科技创新》课程资料 — 板卡拓扑与课程指标的依据

## License

MIT — 见 [LICENSE](LICENSE)。课程相关材料的版权边界见 [NOTICE.md](NOTICE.md)。
