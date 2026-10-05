"""课程评分规则函数边界测试（阈值逐字对齐评分表）。"""
import pytest

from a2000sim.scoring import (score_abs_voltage, score_line_regulation,
                              score_load_regulation, score_monitor_current,
                              score_monitor_voltage, score_protection,
                              score_ripple)


def test_score_abs_voltage():
    """每条件下 4.85~5.15V 得 5 分（含边界）。"""
    assert score_abs_voltage(4850) == 5
    assert score_abs_voltage(5000) == 5
    assert score_abs_voltage(5150) == 5
    assert score_abs_voltage(4849.9) == 0
    assert score_abs_voltage(5150.1) == 0


def test_score_load_regulation_boundaries():
    """变化 <0.01V 得 5；≥0.01V 且 ≤0.02V 得 2；其他 0。"""
    assert score_load_regulation(9.9) == 5
    assert score_load_regulation(10.0) == 2      # 0.01V 落入 2 分档
    assert score_load_regulation(20.0) == 2
    assert score_load_regulation(20.1) == 0
    assert score_load_regulation(-15) == 2       # 绝对值


def test_score_line_regulation_boundaries():
    """变化 <0.01V 得 5；≥0.01V 且 ≤0.025V 得 2；其他 0。"""
    assert score_line_regulation(9.9) == 5
    assert score_line_regulation(10.0) == 2
    assert score_line_regulation(25.0) == 2
    assert score_line_regulation(25.1) == 0


def test_score_monitor_voltage_boundaries():
    """误差 ≤0.02V 得 5；≤0.05V 且 >0.02V 得 2；其他 0。"""
    assert score_monitor_voltage(20) == 5
    assert score_monitor_voltage(20.1) == 2
    assert score_monitor_voltage(50) == 2
    assert score_monitor_voltage(50.1) == 0
    assert score_monitor_voltage(-18) == 5       # 绝对值


def test_score_monitor_current_boundaries():
    """误差 ≤0.01A 得 5；≤0.05A 且 >0.01A 得 2；其他 0。"""
    assert score_monitor_current(0.010) == 5
    assert score_monitor_current(0.0101) == 2
    assert score_monitor_current(0.050) == 2
    assert score_monitor_current(0.0501) == 0


def test_score_protection():
    assert score_protection(True, True) == 10
    assert score_protection(True, False) == 5
    assert score_protection(False, True) == 0
    assert score_protection(False, False) == 0


def test_score_ripple_formula():
    """≤30mV→20；30~100 线性折算 s=8+(100-Upp)/70×12；>100→0。"""
    assert score_ripple(30) == 20
    assert score_ripple(65) == 14                # 8+35/70×12 = 14
    assert score_ripple(100) == 8
    assert score_ripple(100.1) == 0
