"""课程算法与实测事实交叉验证测试。"""
import pytest

from a2000sim.fw_algorithms import (COURSE_CAL, SYSCLOCK_HZ, SlidingWindowAverage,
                                    HysteresisFilter, apply_linear, fit_linear,
                                    pll_sysclk, systick_reload)
from a2000sim.plant import ADC_MAX, CURRENT_CHAIN, VOLTAGE_CHAIN, adc_code, adc_mv


# ---------------- [M-2] 实测时钟事实 ----------------

def test_systick_reload_matches_measured():
    """实测 SysTick RVR = 399999（20ms @ 20MHz）——模型必须逐位复现。"""
    assert systick_reload(0.02, SYSCLOCK_HZ) == 399999


def test_pll_math_matches_measured():
    """实测 RSCLKCFG/PLLFREQ → 20.000MHz（PIOSC 路径）。"""
    r = pll_sysclk(ref_hz=16_000_000, mint=30, q=12, sysdiv=1)
    assert r["sysclk_hz"] == pytest.approx(20_000_000)
    assert r["vco_in_spec"] is True
    assert r["ref"] == "PIOSC"


def test_pll_mosc_path_is_out_of_spec():
    """25MHz 晶振路径 → 750MHz VCO，超出 320–480MHz 窗口（被物理排除）。"""
    r = pll_sysclk(ref_hz=25_000_000, mint=30, q=12, sysdiv=1)
    assert r["vco_hz"] == 750_000_000
    assert r["vco_in_spec"] is False


def test_pll_q_truncation_reproduces_dac_demo_anomaly():
    """课程 dac_demo 请求 1MHz → Q 域 5 位截断 → 实得 15MHz 的机理复现。"""
    # Q=240 截断为 5 位域的 15（240 & 0x1F），得 480/16/2 = 15MHz
    r = pll_sysclk(ref_hz=16_000_000, mint=30, q=240 & 0x1F, sysdiv=1)
    assert r["sysclk_hz"] == pytest.approx(15_000_000)


# ---------------- 课程算法 ----------------

def test_sliding_window_average():
    win = SlidingWindowAverage(window=4, fill=0)
    assert [win.add(x) for x in (8, 8, 8, 8)] == [2, 4, 6, 8]
    win2 = SlidingWindowAverage(window=4, fill=100)
    assert win2.add(100) == 100


def test_hysteresis():
    h = HysteresisFilter(deadband=2)
    assert h.feed(100) == 100
    assert h.feed(101) == 100          # 门限内保持
    assert h.feed(103) == 103          # 超门限跳变


def test_linear_fit_residual():
    pts = [(x, 2.0 * x + 1.0) for x in (0, 100, 500, 1000, 2000, 4095)]
    a, b = fit_linear(pts)
    assert apply_linear(1234, a, b) == pytest.approx(2.0 * 1234 + 1.0, abs=1e-6)


# ---------------- 课程指标预演（端到端：被控对象→ADC→标定→误差断言） ----------------

@pytest.mark.parametrize("vout_mv", [4850, 4950, 5000, 5050, 5150])
def test_voltage_measurement_meets_course_criterion(vout_mv):
    """课程指标：电压测量误差 ≤0.02V 满分 / ≤0.05V 合格。
    用理想链 + 重新拟合的标定（两个偏置点）做端到端预演。"""
    pins = [VOLTAGE_CHAIN.forward(v) for v in (4850, 5150)]
    codes = [adc_code(p) for p in pins]
    a, b = fit_linear(list(zip(codes, (4850, 5150))))
    displayed = apply_linear(adc_code(VOLTAGE_CHAIN.forward(vout_mv)), a, b)
    assert abs(displayed - vout_mv) <= 20  # ≤0.02V（满分档）


@pytest.mark.parametrize("current_a", [0.1, 0.3, 0.5, 0.8, 1.0])
def test_current_measurement_meets_course_criterion(current_a):
    """课程指标：电流测量误差 ≤0.01A 满分档（端到端预演，同上）。"""
    pins = [CURRENT_CHAIN.forward(v) for v in (0.1, 1.0)]
    codes = [adc_code(p) for p in pins]
    a, b = fit_linear(list(zip(codes, (0.1, 1.0))))
    displayed = apply_linear(adc_code(CURRENT_CHAIN.forward(current_a)), a, b)
    assert abs(displayed - current_a) <= 0.01


def test_course_calibration_constants_shape():
    """[PPT] 课程参考标定系数存在且为线性形式（数值依赖其调理板，不在此断言精度）。"""
    assert set(COURSE_CAL) == {"voltage", "current"}
    for a, b in COURSE_CAL.values():
        assert isinstance(a, float) and isinstance(b, float)


def test_overscale_reading_is_clamped():
    """Z3.3 钳位下故障高压不会击穿 ADC 读数域（钳到满码）。"""
    assert adc_code(VOLTAGE_CHAIN.forward(9000)) == ADC_MAX
    assert adc_mv(ADC_MAX) == pytest.approx(3300.0)
