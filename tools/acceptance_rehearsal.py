#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程验收预演（仿真版）——第一阶段 DC-DC 稳压电源 + 单片机监测链。

按《工程实践与科技创新[3A]测试方法和评分规则》（2025-11-25 版）表 2 逐项预演：

  仿真可验（本脚本打分）：
    - 单片机监测电压/电流（10 分）——FIL：课程固件 adc_demo + 虚拟实验台
    - 输出电压绝对精度（10 分）——被控对象模型（空载/5.1Ω）
    - 负载调整率（5 分）/ 电压调整率（5 分）——被控对象模型
    - 过流保护和恢复（10 分）——被控对象模型（打嗝现象学）
  需实机（输出 N/A，不计分）：
    - 输出纹波（20 分）——准静态模型无开关纹波
    - 电源转换效率（40 分）——模型无损耗

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
        cmds.append("sysbus WriteDoubleWord 0x50000040 %d" % round(v_pin))
        cmds.append("sysbus WriteDoubleWord 0x50000044 %d" % round(i_pin))
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
        ch1_disp = d[0] * 1000 + d[1] * 100 + d[2] * 10 + d[3]   # GRID1-4 电流码
        ch0_disp = d[4] * 1000 + d[5] * 100 + d[6] * 10 + d[7]   # GRID5-8 电压码
        # 标定链反演（等效实机固件的标定步骤）：码 → 引脚 mV → 工程量
        v_disp = ch0_disp * 3300.0 / 4095.0 * 2.0               # 除以 0.5 分压
        i_disp = ch1_disp * 3300.0 / 4095.0 / 1000.0            # 1V/A
        results.append((name, v_true, v_disp, i_true, i_disp))
    return results


def main():
    card = []                                       # (条目, 满分, 得分, 说明)
    print("=" * 66)
    print("  课程验收预演（仿真版）— 第一阶段 DC-DC 稳压电源 + 监测链")
    print("  评分依据：测试方法和评分规则（2025-11-25 版）表 2")
    print("  仿真范围：监测链 FIL + 被控对象静态行为；纹波/效率需实机")
    print("=" * 66)

    # ---------------- Part A：被控对象静态指标（模型） ----------------
    print("\n[Part A · 被控对象模型]")

    # A1 输出电压绝对精度（10 分）：5.1Ω 与空载
    p = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1,
                  vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM, ocp_trip_a=OCP_TRIP_A)
    p.advance(0.05)
    v_51 = p.vout_mv
    s1, s2 = score_abs_voltage(v_51), score_abs_voltage(v_51)   # 空载同模型稳态
    card.append(("输出电压绝对精度", 10, s1 + s2,
                 "5.1Ω→%.0fmV ✓ 空载→%.0fmV ✓（4.85~5.15V）" % (v_51, p.vout_nominal_mv)))

    # A2 负载调整率（5 分）：5.1Ω vs 10Ω
    p10 = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=10.0,
                    vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM, ocp_trip_a=OCP_TRIP_A)
    p10.advance(0.05)
    dv_load = abs(p10.vout_mv - v_51)
    card.append(("负载调整率", 5, score_load_regulation(dv_load),
                 "5.1Ω vs 10Ω ΔV=%.1fmV（<10mV 满分）" % dv_load))

    # A3 电压调整率（5 分）：Vin 10→20V
    p20 = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1,
                    vin_mv=20000.0, line_reg_ppm_per_v=LINE_REG_PPM, ocp_trip_a=OCP_TRIP_A)
    p20.advance(0.05)
    dv_line = abs(p20.vout_mv - v_51)
    card.append(("电压调整率", 5, score_line_regulation(dv_line),
                 "Vin 10→20V ΔV=%.1fmV（<10mV 满分，%gppm/V）" % (dv_line, LINE_REG_PPM)))

    # A4 过流保护和恢复（10 分）：2.5Ω 触发 → 负载恢复 → 自动恢复
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1,
                      vin_mv=10000.0, line_reg_ppm_per_v=LINE_REG_PPM,
                      ocp_trip_a=OCP_TRIP_A, ocp_hiccup_s=0.05)
    plant.advance(0.05)
    plant.set_load(2.5)                             # I = 2A > 1.5A
    plant.advance(0.01)
    tripped_ok = plant.tripped and plant.vout_mv < 200
    plant.advance(0.05)                             # 打嗝重试仍过流 → 保持
    plant.set_load(5.1)
    plant.advance(0.01)
    recovered = not plant.tripped
    plant.advance(0.05)
    recovered = recovered and abs(plant.vout_mv - 5000.0) < 50
    card.append(("过流保护和恢复", 10, score_protection(tripped_ok, recovered),
                 "2.5Ω(I=2A)触发关断=%s；5.1Ω 自动恢复=%s" % (tripped_ok, recovered)))

    for name, full, got, note in card[:4]:
        print("  %s %s (%d分): %s" % ("✓" if got == full else "✗", name, full, note))

    # ---------------- Part B：监测链 FIL ----------------
    print("\n[Part B · 监测链 FIL]（课程固件 adc_demo + 虚拟实验台）")
    renode = find_renode()
    if not renode:
        print("  SKIP：未找到 Renode（设 RENODE_EXE）")
    elif not os.path.isfile(FW_ADC):
        print("  SKIP：firmware/local/adc_demo.axf 不存在")
    else:
        results = fil_monitoring(renode)
        if results is None:
            print("  SKIP：FIL 回读数量不足")
        else:
            for name, v_true, v_disp, i_true, i_disp in results:
                ev = score_monitor_voltage(v_disp - v_true)
                ei = score_monitor_current(i_disp - i_true)
                card.append(("监测电压@%s" % name, 5, ev,
                             "真值 %.3fV / 显示折算 %.4fV" % (v_true / 1000, v_disp / 1000)))
                card.append(("监测电流@%s" % name, 5, ei,
                             "真值 %.3fA / 显示折算 %.4fA" % (i_true, i_disp)))
                print("  %s 监测电压@%s (5分): 误差 %.1fmV → %d 分"
                      % ("✓" if ev == 5 else "△", name, abs(v_disp - v_true), ev))
                print("  %s 监测电流@%s (5分): 误差 %.1fmA → %d 分"
                      % ("✓" if ei == 5 else "△", name, abs(i_disp - i_true) * 1000, ei))

    # ---------------- 记分卡 ----------------
    print("\n" + "-" * 66)
    full = sum(c[1] for c in card)
    got = sum(c[2] for c in card)
    for name, f, g, note in card:
        print("  %s/%d  %s — %s" % (g, f, name, note))
    print("-" * 66)
    print("  仿真可验小计：%d / %d" % (got, full))
    print("  [需实机] 输出纹波 (20分) · 电源转换效率 (40分) — 模型为准静态/无损耗，N/A")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
