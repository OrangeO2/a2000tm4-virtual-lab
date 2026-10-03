#!/usr/bin/env python3
"""A2000TM4 固件在环（FIL）冒烟测试。

直接驱动 Renode 运行课程原始固件，并断言虚拟实验台的回读结果：

1. adc_demo：注入 CH0=CH1=1250mV → ADC 码 1551 → GRID1-8 显示 "1551"
2. demo   ：注入键 3 → key_code=3；键 7 → 7；释放 → 0

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

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("FIL SMOKE: 2/2 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
