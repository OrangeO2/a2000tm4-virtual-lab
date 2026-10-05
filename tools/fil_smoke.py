#!/usr/bin/env python3
"""A2000TM4 固件在环（FIL）冒烟测试。

直接驱动 Renode 运行课程原始固件，并断言虚拟实验台的回读结果：

1. adc_demo：注入 CH0=CH1=1250mV → ADC 码 1551 → GRID1-8 显示 "1551"
2. demo   ：注入键 3 → key_code=3；键 7 → 7；释放 → 0
3. v0.3 被控对象闭环：按物理映射 CH0=电流、CH1=电压分窗注入
4. v0.4 DAC6571：验证完整 10 位 DAC 码，不再只检查低 8 位
5. [M-5] 无功率板连续采样尾点基线回放（CH0=1427 / CH1=1313）

用法（需 Renode 可执行文件与 firmware/local/ 下的课程固件，见 NOTICE.md）：

    python tools/fil_smoke.py                     # 自动探测 Renode
    RENODE_EXE=/path/renode python tools/fil_smoke.py

各场景按所需固件独立执行；缺失项明确计为 SKIP，不再把跳过场景报告成“5/5 通过”。
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
    """按顺序提取 monitor Read* 命令打印的 0x... 值（整数列表）。

    Renode 的日志行可能与回读值同行拼接（无换行），故对每行做前缀匹配：
    以 0x 开头的行，其前导十六进制 token 即为回读值。"""
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    vals = []
    for line in clean.split("\n"):
        m = re.match(r"^(0x[0-9A-Fa-f]+)", line)
        if m:
            vals.append(int(m.group(1), 16))
    return vals


def main():
    renode = find_renode()
    if not renode:
        print("SKIP: 未找到 Renode 可执行文件（设置 RENODE_EXE）")
        return 0

    failures = []
    skipped = []
    executed = 0
    passed = 0

    # ---- 测试 1：adc_demo 电压注入 → 显示 "1551" ----
    if not os.path.isfile(FW_ADC):
        skipped.append("测试1 adc_demo：缺少 firmware/local/adc_demo.axf")
    else:
        executed += 1
        cmds = [
            "$bin=@%s" % FW_ADC,
            "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
            "sysbus WriteDoubleWord 0x50000040 1250",
            "sysbus WriteDoubleWord 0x50000044 1250",
            'emulation RunFor "00:00:02"',
        ]
        for i in range(8):
            cmds.append("sysbus ReadByte 0x%X" % (0x50000010 + i))
        vals = readbacks(run_renode(renode, cmds))
        digits = vals[:8]
        expect = [1, 5, 5, 1, 1, 5, 5, 1]
        if digits == expect:
            passed += 1
            print("PASS [1] adc_demo 显示 = %s（CH0=CH1=1250mV → 码1551）" % digits)
        else:
            failures.append("[1] adc_demo 显示 = %s，期望 %s" % (digits, expect))

    # ---- 测试 2：demo 键注入 → key_code 跟随 ----
    if not os.path.isfile(FW_DEMO):
        skipped.append("测试2 demo：缺少 firmware/local/demo.axf")
    else:
        executed += 1
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
        seq = readbacks(run_renode(renode, cmds))[:4]
        expect_seq = [0, 3, 7, 0]
        if seq == expect_seq:
            passed += 1
            print("PASS [2] demo 键注入 key_code 序列 = %s" % seq)
        else:
            failures.append("[2] demo key_code = %s，期望 %s" % (seq, expect_seq))

    # ---- 测试 3：v0.3 被控对象闭环（BuckPlant 分窗推进） ----
    # 物理映射统一为：CH0=PE3/AIN0=电流；CH1=PE2/AIN1=电压。
    # 固件显示：GRID1-4=CH1（电压），GRID5-8=CH0（电流）。
    if not os.path.isfile(FW_ADC):
        skipped.append("测试3 BuckPlant FIL：缺少 firmware/local/adc_demo.axf")
    else:
        executed += 1
        plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=1600.0, load_res_ohm=5.1)
        cmds = [
            "$bin=@%s" % FW_ADC,
            "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
            "sysbus WriteDoubleWord 0x50000040 0",  # CH0/PE3 = current
            "sysbus WriteDoubleWord 0x50000044 0",  # CH1/PE2 = voltage
            'emulation RunFor "00:00:01"',
        ]
        states = []  # (name, voltage_code_on_CH1, current_code_on_CH0)

        def step_to(name, dt_s, load=None):
            plant.advance(dt_s)
            if load is not None:
                plant.set_load(load)
            v_pin = plant.pin_voltage_mv()
            i_pin = plant.pin_current_mv()
            cmds.append("sysbus WriteDoubleWord 0x50000040 %d" % int(round(i_pin)))
            cmds.append("sysbus WriteDoubleWord 0x50000044 %d" % int(round(v_pin)))
            cmds.append('emulation RunFor "00:00:%04.2f"' % max(2.0, dt_s * 20))
            for i in range(8):
                cmds.append("sysbus ReadByte 0x%X" % (0x50000010 + i))
            states.append((name, adc_code(int(round(v_pin))), adc_code(int(round(i_pin)))))

        step_to("软启动中点(t=0.5s/1.6s)", 0.5)
        step_to("稳态(5V/5.1Ω)", 1.5)
        step_to("负载阶跃(10Ω, I=0.5A)", 0.5, load=10)
        step_to("阶跃后稳态", 0.5)

        vals = readbacks(run_renode(renode, cmds))
        ok = len(vals) >= 4 * 8
        if not ok:
            failures.append("[3] 场景回读数量不足：got %d" % len(vals))
        else:
            local_failures = []
            for k, (name, want_v, want_i) in enumerate(states):
                d = vals[k * 8:(k + 1) * 8]
                voltage_disp = d[0] * 1000 + d[1] * 100 + d[2] * 10 + d[3]
                current_disp = d[4] * 1000 + d[5] * 100 + d[6] * 10 + d[7]
                if (voltage_disp, current_disp) == (want_v, want_i):
                    print("PASS [3:%s]: 电压=%4d 电流=%4d" % (name, voltage_disp, current_disp))
                else:
                    local_failures.append(
                        "[3:%s]: 电压=%d(期望%d) 电流=%d(期望%d)"
                        % (name, voltage_disp, want_v, current_disp, want_i)
                    )
            if local_failures:
                failures.extend(local_failures)
            else:
                passed += 1

    # ---- 测试 4：v0.4 DAC6571 I2C 闭环（完整 10 位 DAC 码） ----
    FW_DAC = os.path.join(REPO, "firmware", "local", "dac_demo.axf")
    if not os.path.isfile(FW_DAC):
        skipped.append("测试4 DAC6571：缺少 firmware/local/dac_demo.axf")
    else:
        executed += 1
        cmds = [
            "$bin=@%s" % FW_DAC,
            "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
            'emulation RunFor "00:00:02"',
            "sysbus ReadDoubleWord 0x50000050",
            "sysbus ReadDoubleWord 0x50000058",
            "sysbus ReadByte 0x50000010",
            "sysbus ReadByte 0x50000011",
            "sysbus ReadByte 0x50000012",
            "sysbus ReadByte 0x50000013",
            "sysbus WriteDoubleWord 0x50000000 4",
            'emulation RunFor "00:00:00.5"',
            "sysbus WriteDoubleWord 0x50000000 0",
            'emulation RunFor "00:00:00.5"',
            "sysbus ReadDoubleWord 0x50000050",
            "sysbus ReadByte 0x50000010",
            "sysbus ReadByte 0x50000011",
            "sysbus ReadByte 0x50000012",
            "sysbus ReadByte 0x50000013",
            "sysbus WriteDoubleWord 0x50000000 1",
            'emulation RunFor "00:00:00.5"',
            "sysbus WriteDoubleWord 0x50000000 0",
            'emulation RunFor "00:00:00.5"',
            "sysbus ReadDoubleWord 0x50000050",
            "sysbus ReadDoubleWord 0x50000058",
        ]
        vals = readbacks(run_renode(renode, cmds))
        if len(vals) < 13:
            failures.append("[4] DAC 闭环回读数量不足：got %d" % len(vals))
        else:
            dac0, frames0 = vals[0], vals[1]
            grid0 = vals[2:6]
            dac1, grid1 = vals[6], vals[7:11]
            dac2, frames2 = vals[11], vals[12]
            ok_boot = dac0 == 1023 and grid0 == [1, 0, 2, 3]
            ok_dec = dac1 == 923 and grid1 == [0, 9, 2, 3]
            ok_back = dac2 == 1023 and frames2 >= 3 and frames2 >= frames0
            if ok_boot and ok_dec and ok_back:
                passed += 1
                print("PASS [4] DAC闭环：1023 → 923 → 1023，I2C 帧=%d" % frames2)
            else:
                failures.append(
                    "[4] DAC闭环: boot=%s/%s dec=%s/%s back=%s frames=%s/%s"
                    % (dac0, grid0, dac1, grid1, dac2, frames0, frames2)
                )

    # ---- 测试 5：M-5 无功率板连续采样尾点基线 ----
    # bench 默认 CH0/PE3=1150mV、CH1/PE2=1058mV，对应 1427/1313 码。
    if not os.path.isfile(FW_ADC):
        skipped.append("测试5 实板基线回放：缺少 firmware/local/adc_demo.axf")
    else:
        executed += 1
        cmds = [
            "$bin=@%s" % FW_ADC,
            "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
            'emulation RunFor "00:00:02"',
        ]
        for i in range(8):
            cmds.append("sysbus ReadByte 0x%X" % (0x50000010 + i))
        digits = readbacks(run_renode(renode, cmds))[:8]
        expect = [1, 3, 1, 3, 1, 4, 2, 7]  # GRID1-4=CH1=1313; GRID5-8=CH0=1427
        if digits == expect:
            passed += 1
            print("PASS [5] M-5 基线回放：CH1=1313 / CH0=1427")
        else:
            failures.append("[5] 基线显示=%s，期望=%s" % (digits, expect))

    for item in skipped:
        print("SKIP:", item)
    if failures:
        for item in failures:
            print("FAIL:", item)
        print("FIL SMOKE: %d/%d 已执行场景通过；%d 跳过；%d 失败" %
              (passed, executed, len(skipped), len(failures)))
        return 1

    print("FIL SMOKE: %d/%d 已执行场景通过；%d 跳过" %
          (passed, executed, len(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
