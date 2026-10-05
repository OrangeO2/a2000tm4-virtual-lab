"""课程评分规则函数（仿真验收预演用）。

出处：上海交通大学《工程实践与科技创新[3A]测试方法和评分规则》（2025-11-25 版）
表 2（第一阶段测试细则）/ 相关条款。所有阈值逐字对齐评分表：

- 输出电压绝对精度：每条件下 4.85~5.15V 得 5 分（两条件共 10 分）
- 负载调整率：变化 <0.01V 得 5 分；≥0.01V 且 ≤0.02V 得 2 分；其他 0 分
- 电压调整率：变化 <0.01V 得 5 分；≥0.01V 且 ≤0.025V 得 2 分；其他 0 分
- 单片机监测电压：误差 ≤0.02V 得 5 分；≤0.05V 且 >0.02V 得 2 分；其他 0 分
- 单片机监测电流：误差 ≤0.01A 得 5 分；≤0.05A 且 >0.01A 得 2 分；其他 0 分
- 过流保护：有效关断 5 分 + 自动恢复 5 分
- 输出纹波：≤30mV 得 20 分；30~100mV 线性折算；>100mV 0 分（仿真不可验，仅保留函数）

仿真范围说明：纹波与效率依赖实机开关行为与功耗测量，准静态模型不可验；
预演脚本对这些项输出 N/A 而不给分。
"""

from __future__ import annotations

VOUT_NOMINAL_MV = 5000.0


def score_abs_voltage(vout_mv: float) -> int:
    """输出电压绝对精度（每条件 5 分）：4.85~5.15V。"""
    return 5 if 4850 <= vout_mv <= 5150 else 0


def score_load_regulation(dv_mv: float) -> int:
    """负载调整率（5 分）：|ΔV| <10mV → 5；≤20mV → 2；其他 0。"""
    dv = abs(dv_mv)
    if dv < 10:
        return 5
    if dv <= 20:
        return 2
    return 0


def score_line_regulation(dv_mv: float) -> int:
    """电压调整率（5 分）：|ΔV| <10mV → 5；≤25mV → 2；其他 0。"""
    dv = abs(dv_mv)
    if dv < 10:
        return 5
    if dv <= 25:
        return 2
    return 0


def score_monitor_voltage(err_mv: float) -> int:
    """单片机监测电压（5 分）：误差 ≤20mV → 5；≤50mV → 2；其他 0。"""
    err = abs(err_mv)
    if err <= 20:
        return 5
    if err <= 50:
        return 2
    return 0


def score_monitor_current(err_a: float) -> int:
    """单片机监测电流（5 分）：误差 ≤10mA → 5；≤50mA → 2；其他 0。"""
    err = abs(err_a)
    if err <= 0.010:
        return 5
    if err <= 0.050:
        return 2
    return 0


def score_protection(tripped: bool, recovered: bool) -> int:
    """过流保护和恢复（10 分）：有效关断 5 分 + 在关断基础上自动恢复 5 分。"""
    if tripped and recovered:
        return 10
    if tripped:
        return 5
    return 0


def score_ripple(upp_mv: float) -> int:
    """输出纹波（20 分）：≤30mV → 20；30~100mV 线性折算；>100mV → 0。

    注意：准静态仿真不可验——本函数供实机数据回填后使用。
    """
    if upp_mv <= 30:
        return 20
    if upp_mv <= 100:
        return round(8 + (100 - upp_mv) / 70 * 12)
    return 0
