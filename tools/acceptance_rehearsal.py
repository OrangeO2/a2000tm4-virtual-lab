#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程验收预演（仿真版）——第一阶段 DC-DC 稳压电源 + 单片机监测链。

按《工程实践与科技创新[3A]测试方法和评分规则》（2025-11-25 版）表 2 做两类检查：

  A. 模型一致性检查（不计真实验收分）：
    - 输出电压、负载/电压调整率、过流关断/恢复
    - 这些结果由 BuckPlant 的设定参数决定，只能证明模型与评分函数自洽
  B. FIL 合成激励检查（可按评分阈值评价固件链路，但不代表实板得分）：
    - 课程固件 adc_demo + 虚拟实验台，验证 ADC→固件→显示处理链

  真实硬件验收仍需实机测量；纹波、效率以及功率级静态指标均不由本脚本宣称通过。

用法：
    python tools/acceptance_rehearsal.py
    RENODE_EXE=/path/renode python tools/acceptance_rehearsal.py

固件缺失时 Part B 跳过（Part A 模型部分照常）。
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from a2000sim.plant import BuckPlant, adc_code                     # noqa: E402
from a2000sim.scoring import (score_abs_voltage, score_line_regulation,  # noqa: E402
                              score_load_regulation, score_monitor_current,
                              score_monitor_voltage, score_protection)
from fil_smoke import FW_ADC, find_renode, readbacks, run_renode   # noqa: E402

LINE_REG_PPM = 50.0     # 线调整率设计值（0.005%/V → 10V 摆幅 ΔV≈2.5mV）
OCP_TRIP_A = 1.5        # 过流触发电流（课程允许窗 1.1~1.9A 的中点）


def fil_monitoring(renode):
    """Part B：监测链 FIL——两个评分条件，返回 (条目名, 真值, 折算值) 列表。"""
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0,
                      load_res_ohm=5.1, vin_mv=10000.0,
                      line_reg_ppm_per_v=LINE_REG_PPM, ocp_trip_a=OCP_TRIP_A)
    cmds = [
        "$bin=@%s" % FW_ADC,
        "include @%s" % os.path.join(REPO, "renode", "a2000tm4.resc"),
        'emulation RunFor "00:00:01"',              # 固件引导
    ]
    phases = []                                     # (名, 真值电压 mV, 真值电流 A)
    plan = [("稳态 5.0V/5.1Ω", 0.15, None),         # I ≈ 0.98A
            ("0.8A 档 (R=6.25Ω)", 1.5, 6.25)]       # 评分官任选条件示例
    for name, dur, load in plan:
        plant.advance(dur)
        if load:
            plant.set_load(load)
        v_pin, i_pin = plant.pin_voltage_mv(), plant.pin_current_mv()
        # 物理映射：CH0/PE3=A​IN0=电流；CH1/PE2=A​IN1=电压。
        cmds.append("sysbus WriteDoubleWord 0x50000040 %d" % round(i_pin))
        cmds.append("sysbus WriteDoubleWord 0x50000044 %d" % round(v_pin))
        cmds.append('emulation RunFor "00:00:%04.2f"' % max(2.0, dur * 10))
        for i in range(8):
            cmds.append("sysbus ReadByte 0x%X" % (0x50000010 + i))
        phases.append((name, plant.vout_mv, plant.current_a))

    out = run_renode(renode, cmds)
    vals = readbacks(out)
    if len(vals) < 16:
        return None
    results = []
    for k, (name, v_true, i_true) in enumerate(phases):
        d = vals[k * 8:(k + 1) * 8]
        ch1_disp = d[0] * 1000 + d[1] * 100 + d[2] * 10 + d[3]   # GRID1-4 = CH1/PE2 电压码
        ch0_disp = d[4] * 1000 + d[5] * 100 + d[6] * 10 + d[7]   # GRID5-8 = CH0/PE3 电流码
        # 标定链反演（合成理想链）：码 → 引脚 mV → 工程量
        v_disp = ch1_disp * 3300.0 / 4095.0 * 2.0               # 电压链 0.5 分压
        i_disp = ch0_disp * 3300.0 / 4095.0 / 1000.0            # 电流链 1V/A
        results.append((name, v_true, v_disp, i_true, i_disp))
    return results


def main():
    model_checks = []
    fil_card = []
    print("=" * 72)
    print("  课程验收预演（证据分级版）— 第一阶段 DC-DC 稳压电源 + 监测链")
    print("  A=模型一致性检查（不计真实验收分）；B=FIL 合成激励（仅验证固件链路）")
    print("=" * 72)

    # ---------------- Part A：模型一致性，不冒充硬件验收 ----------------
    print("\n[Part A · BuckPlant 模型一致性，不计真实验收分]")

    p_load = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1,
                       vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM,
                       ocp_trip_a=OCP_TRIP_A)
    p_open = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=1e9,
                       vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM,
                       ocp_trip_a=OCP_TRIP_A)
    p10 = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=10.0,
                    vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM,
                    ocp_trip_a=OCP_TRIP_A)
    p20 = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1,
                    vin_mv=20000.0, line_reg_ppm_per_v=LINE_REG_PPM,
                    ocp_trip_a=OCP_TRIP_A)
    for p in (p_load, p_open, p10, p20):
        p.advance(0.05)

    abs_ok = score_abs_voltage(p_load.vout_mv) == 5 and score_abs_voltage(p_open.vout_mv) == 5
    load_dv = abs(p10.vout_mv - p_load.vout_mv)
    line_dv = abs(p20.vout_mv - p_load.vout_mv)
    load_ok = score_load_regulation(load_dv) == 5
    line_ok = score_line_regulation(line_dv) == 5
    model_checks.extend([
        ("输出电压模型", abs_ok, "5.1Ω=%.1fmV，近似空载=%.1fmV" %
         (p_load.vout_mv, p_open.vout_mv)),
        ("负载调整率模型", load_ok, "5.1Ω vs 10Ω ΔV=%.2fmV" % load_dv),
        ("电压调整率模型", line_ok,
         "Vin 10→20V ΔV=%.2fmV；注意 %gppm/V 是模型设定值，不是测量值" %
         (line_dv, LINE_REG_PPM)),
    ])

    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1,
                      vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM,
                      ocp_trip_a=OCP_TRIP_A, ocp_hiccup_s=0.05)
    plant.advance(0.05)
    plant.set_load(2.5)
    plant.advance(0.01)
    tripped_ok = plant.tripped and plant.vout_mv < 200
    plant.advance(0.05)
    plant.set_load(5.1)
    plant.advance(0.01)
    recovered = not plant.tripped
    plant.advance(0.05)
    recovered = recovered and abs(plant.vout_mv - 5000.0) < 50
    protection_ok = score_protection(tripped_ok, recovered) == 10
    model_checks.append((
        "过流关断/安全负载恢复模型", protection_ok,
        "2.5Ω 触发=%s；回到5.1Ω恢复=%s（当前模型不声称复现周期 hiccup 波形）" %
        (tripped_ok, recovered),
    ))

    for name, ok, note in model_checks:
        print("  %s %s — %s" % ("PASS" if ok else "FAIL", name, note))

    # ---------------- Part B：FIL 合成激励 ----------------
    print("\n[Part B · FIL 合成激励；可检查固件链路，不代表实板硬件得分]")
    renode = find_renode()
    if not renode:
        print("  SKIP：未找到 Renode（设 RENODE_EXE）")
    elif not os.path.isfile(FW_ADC):
        print("  SKIP：firmware/local/adc_demo.axf 不存在")
    else:
        results = fil_monitoring(renode)
        if results is None:
            print("  FAIL：FIL 回读数量不足")
        else:
            for name, v_true, v_disp, i_true, i_disp in results:
                ev = score_monitor_voltage(v_disp - v_true)
                ei = score_monitor_current(i_disp - i_true)
                fil_card.append(("监测电压@%s" % name, 5, ev,
                                 "合成真值 %.3fV / 固件显示折算 %.4fV" %
                                 (v_true / 1000, v_disp / 1000)))
                fil_card.append(("监测电流@%s" % name, 5, ei,
                                 "合成真值 %.3fA / 固件显示折算 %.4fA" %
                                 (i_true, i_disp)))
                print("  %s 电压@%s: 误差 %.1fmV → 阈值分 %d/5" %
                      ("PASS" if ev == 5 else "CHECK", name, abs(v_disp - v_true), ev))
                print("  %s 电流@%s: 误差 %.1fmA → 阈值分 %d/5" %
                      ("PASS" if ei == 5 else "CHECK", name, abs(i_disp - i_true) * 1000, ei))

    print("\n" + "-" * 72)
    if fil_card:
        full = sum(c[1] for c in fil_card)
        got = sum(c[2] for c in fil_card)
        print("  FIL 合成激励阈值小计：%d / %d（仅固件处理链，不是实板验收分）" % (got, full))
    else:
        print("  FIL 合成激励：N/A")
    print("  真实硬件验收分：N/A — 输出精度/调整率/保护/纹波/效率都需独立实测证据")
    print("  模型检查通过：%d/%d；它们是回归检查，不计验收得分" %
          (sum(1 for _, ok, _ in model_checks if ok), len(model_checks)))
    print("-" * 72)
    return 0 if all(ok for _, ok, _ in model_checks) else 1


if __name__ == "__main__":
    sys.exit(main())
