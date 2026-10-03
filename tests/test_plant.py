"""信号链与被控对象模型测试：ADC 编码、调理通道、钳位、悬空引脚行为。"""
import pytest

from a2000sim.plant import (VREF_MV, ADC_MAX, CURRENT_CHAIN, FloatingPinModel,
                            VOLTAGE_CHAIN, adc_code, adc_mv)


def test_adc_encoding():
    assert adc_code(0) == 0
    assert adc_code(3300) == ADC_MAX
    assert adc_mv(ADC_MAX) == pytest.approx(VREF_MV)
    assert adc_code(1650) == pytest.approx(ADC_MAX / 2, abs=1)
    with pytest.raises(AssertionError):
        assert adc_code(99999) > ADC_MAX  # 超范围被钳到满码


def test_voltage_chain_scale():
    """分压比 0.5 [SCH]：5V 输出 → 2.5V 引脚。"""
    assert VOLTAGE_CHAIN.forward(5000) == pytest.approx(2500)


def test_current_chain_scale():
    """0.1Ω × 增益10 [SCH/实验2]：0.8A → 800mV。"""
    assert CURRENT_CHAIN.forward(0.8) == pytest.approx(800.0)


def test_zener_clamp():
    """Z3.3 + 10Ω 钳位 [SCH]：引脚电压不超过 ~3.3V。"""
    assert VOLTAGE_CHAIN.forward(9000) == 3300.0
    assert CURRENT_CHAIN.forward(5.0) == 3300.0


def test_floating_pin_bleed_and_recovery():
    """[M-5 实测] 连续采样单调衰减、静置恢复。"""
    pin = FloatingPinModel(resting_mv=1260.0, plateau_mv=1165.0,
                           bleed_per_sample=0.045, recovery_tau_s=2.0)
    samples = [pin.sample(dt_since_last_s=0.04) for _ in range(8)]
    assert all(samples[i] >= samples[i + 1] - 1e-9 for i in range(7)), \
        f"连续采样应衰减: {samples}"
    assert samples[0] > samples[-1]
    # 静置恢复（模拟 5s 无采样）
    import math
    pin._pin_mv += (pin.resting_mv - pin._pin_mv) * (1 - math.exp(-5 / 2.0))
    assert pin.pin_mv == pytest.approx(pin.resting_mv, rel=0.05)
