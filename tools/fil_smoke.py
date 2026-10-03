#!/usr/bin/env python3
"""A2000TM4 固件在环（FIL）冒烟测试。

直接驱动 Renode 运行课程原始固件，并断言虚拟实验台的回读结果：

1. adc_demo：注入 CH0=CH1=1250mV → ADC 码 1551 → GRID1-8 显示 "1551"
2. demo   ：注入键 3 → key_code=3；键 7 → 7；释放 → 0
3. v0.3 被控对象闭环：BuckPlant（软启动→稳态→负载阶跃）分窗推进，
   逐窗同步注入 CH0/CH1 电压，固件显示逐窗跟随，按课程满分档断言

用法（需 Renode 可执行文件与 firmware/local/ 下的课程固件，见 NOTICE.md）：

    python tools/fil_smoke.py                     # 自动探测 Renode
    RENODE_EXE=/path/renode python tools/fil_smoke.py

固件缺失时打印 SKIP 并以退出码 0 结束（CI 友好）。
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from a2000sim.plant import BuckPlant, adc_code  # noqa: E402

def _which(name):
    from shutil import which
    return which(name)


RENODE_CANDIDATES = [
    os.environ.get("RENODE_EXE", ""),
    r"C:\Users\%s\tools\renode\renode_1.17.0-portable\renode.exe" % os.environ.get("USERNAME", ""),
    "/opt/renode/renode",
    _which("renode"),
]

FW_ADC = os.path.join(REPO, "firmware", "local", "adc_demo.axf")
FW_DEMO = os.path.join(REPO, "firmware", "local", "demo.axf")


def find_renode():
    for c in RENODE_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    return None


def run_renode(renode, commands):
    cmd_line = "; ".join(commands)
    out = subprocess.run([renode, "--console", "-e", cmd_line + "; quit"],
                         capture_output=True, text=True, timeout=300, cwd=REPO)
    return out.stdout + out.stderr


def readbacks(output):
    """按顺序提取 monitor Read* 命令打印的 0x... 值（剥离 ANSI 颜色码）。"""
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    return re.findall(r"^(0x[0-9A-Fa-f]+)$", clean, flags=re.M)


def main():
    renode = find_renode()
    if not renode:
        print("SKIP: 未找到 Renode 可执行文件（设置 RENODE_EXE）")
        return 0
    if not (os.path.isfile(FW_ADC) and os.path.isfile(FW_DEMO)):
        print("SKIP: firmware/local/ 缺少课程固件（adc_demo.axf / demo.axf）")
        return 0

    failures = []

    # ---- 测试 1：adc_demo 电压注入 → 显示 "1551" ----
    cmds = [
        "$bin=@%s" % FW_ADC,
        "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
        'emulation RunFor "00:00:02"',
    ]
    for i in range(8):
        cmds.append("sysbus ReadByte 0x%X" % (0x50000010 + i))
    out = run_renode(renode, cmds)
    vals = [int(v, 16) for v in readbacks(out)]
    digits = vals[:8]
    expect = [1, 5, 5, 1, 1, 5, 5, 1]           # CH0=CH1=码1551
    if digits == expect:
        print("PASS adc_demo 显示 = %s（码 1551）" % digits)
    else:
        failures.append("adc_demo 显示 = %s，期望 %s" % (digits, expect))

    # ---- 测试 2：demo 键注入 → key_code 跟随 ----
    kc_addr = "0x20000019"
    cmds = [
        "$bin=@%s" % FW_DEMO,
        "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
        'emulation RunFor "00:00:01"',
        "sysbus ReadByte %s" % kc_addr,
        "sysbus WriteDoubleWord 0x50000000 3",
        'emulation RunFor "00:00:00.3"',
        "sysbus ReadByte %s" % kc_addr,
        "sysbus WriteDoubleWord 0x50000000 7",
        'emulation RunFor "00:00:00.3"',
        "sysbus ReadByte %s" % kc_addr,
        "sysbus WriteDoubleWord 0x50000000 0",
        'emulation RunFor "00:00:00.3"',
        "sysbus ReadByte %s" % kc_addr,
    ]
    out = run_renode(renode, cmds)
    vals = [int(v, 16) for v in readbacks(out)]
    seq = vals[:4]
    expect_seq = [0, 3, 7, 0]
    if seq == expect_seq:
        print("PASS demo 键注入 key_code 序列 = %s" % seq)
    else:
        failures.append("demo key_code = %s，期望 %s" % (seq, expect_seq))

    # ---- 测试 3：v0.3 被控对象闭环（BuckPlant 分窗推进） ----
    # 时间线（全局虚拟时钟，含固件"追赶"裕量）：1s 引导（显示 300ms 后初始化）
    # → 软启动中点（soft_start=1.6s，t=0.5s 处 vout≈1562mV）→ 稳态 5V/5.1Ω
    # → 负载阶跃 10Ω（I=0.5A）。四个确定状态逐一断言（确定性模型，精确相等）。
    # 通道映射 [课程 PPT]：CH0(PE3)=电压（GRID5-8 左侧），CH1(PE2)=电流（GRID1-4 右侧）。
    # 注意：Python 外设处理较慢，固件在全局虚拟时间上"欠账"，故每步用 10 倍以上
    # RunFor 裕量让固件追平后再读回。
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=1600.0, load_res_ohm=5.1)
    cmds = [
        "$bin=@%s" % FW_ADC,
        "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
        "sysbus WriteDoubleWord 0x50000040 0",
        "sysbus WriteDoubleWord 0x50000044 0",
        'emulation RunFor "00:00:01"',              # 引导 + 显示初始化（激励 0V）
    ]
    states = []                                     # (名称, CH0电压码, CH1电流码)

    def step_to(name, dt_s, load=None):
        plant.advance(dt_s)
        if load:
            plant.set_load(load)
        v_pin, i_pin = plant.pin_voltage_mv(), plant.pin_current_mv()
        cmds.append("sysbus WriteDoubleWord 0x50000040 %d" % int(round(v_pin)))
        cmds.append("sysbus WriteDoubleWord 0x50000044 %d" % int(round(i_pin)))
        cmds.append('emulation RunFor "00:00:%04.2f"' % max(2.0, dt_s * 20))
        for i in range(8):
            cmds.append("sysbus ReadByte 0x%X" % (0x50000010 + i))
        states.append((name, adc_code(int(round(v_pin))), adc_code(int(round(i_pin)))))

    step_to("软启动中点(t=0.5s/1.6s)", 0.5)
    step_to("稳态(5V/5.1Ω)", 1.5)
    step_to("负载阶跃(10Ω, I=0.5A)", 0.5, load=10)
    step_to("阶跃后稳态", 0.5)

    out = run_renode(renode, cmds)
    vals = [int(v, 16) for v in readbacks(out)]
    if len(vals) < 4 * 8:
        failures.append("场景 3 回读数量不足：got %d" % len(vals))
    else:
        for k in range(4):
            name, want_v, want_i = states[k]
            d = vals[k * 8:(k + 1) * 8]
            ch1_disp = d[0] * 1000 + d[1] * 100 + d[2] * 10 + d[3]   # GRID1-4 电流
            ch0_disp = d[4] * 1000 + d[5] * 100 + d[6] * 10 + d[7]   # GRID5-8 电压
            if (ch0_disp, ch1_disp) == (want_v, want_i):
                print("PASS [%s]: 电压=%4d 电流=%4d" % (name, ch0_disp, ch1_disp))
            else:
                failures.append("[%s]: 电压=%d(期望%d) 电流=%d(期望%d)"
                                % (name, ch0_disp, want_v, ch1_disp, want_i))

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("FIL SMOKE: 3/3 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
