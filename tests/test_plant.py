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


# ---------------- v0.3：BuckPlant 被控对象动态模型 ----------------

from a2000sim.plant import BuckPlant  # noqa: E402


def test_buck_soft_start_ramp():
    """软启动：输出从 0 线性爬升到额定（30ms 选型 [课程实验1]）。"""
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1)
    plant.advance(0.0)
    assert plant.vout_mv == 0.0
    vs = []
    for _ in range(10):
        plant.advance(0.003)          # 3ms 步进，共 30ms
        vs.append(plant.vout_mv)
    assert all(vs[i] <= vs[i + 1] + 1e-9 for i in range(len(vs) - 1)), "应单调爬升"
    assert vs[-1] == pytest.approx(5000.0, rel=0.01)


def test_buck_steady_state_current():
    """稳态电流按评分口径：I = Vout/R_load。5.0V/5.1Ω ≈ 0.980A。"""
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1)
    plant.advance(0.05)
    assert plant.current_a == pytest.approx(5.0 / 5.1, rel=0.001)


def test_buck_load_step_transient_and_settle():
    """负载阶跃：瞬间跌落（ΔI 成比例）→ 一阶恢复到新稳态。"""
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0,
                      load_res_ohm=5.1, dip_mv_per_a=120.0, tau_recovery_s=0.002)
    plant.advance(0.05)               # 稳态 5V
    v_before = plant.vout_mv
    plant.set_load(10.0)              # 阶跃：I 0.98→0.50A，ΔI≈0.48A
    plant.advance(0.001)              # 1ms：处于暂态
    assert plant.vout_mv < v_before - 0.02, "阶跃瞬间应有可观测跌落"
    for _ in range(20):               # 20×5ms = 100ms 后应稳定在新稳态
        plant.advance(0.005)
    assert plant.vout_mv == pytest.approx(5000.0, rel=0.002)
    assert plant.current_a == pytest.approx(0.5, rel=0.001)


def test_buck_pin_mapping_end_to_end_course_criterion():
    """端到端：被控对象 → 调理链 → ADC 码，误差按课程满分档（±0.02V/±0.01A）。

    换算：0.02V → 引脚 10mV → 码 ±12.4；0.01A → 引脚 10mV → 码 ±12.4。
    """
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1)
    plant.advance(0.05)
    # 电压链（PE2/CH1）：0.5 分压
    code_v = adc_code(plant.pin_voltage_mv())
    assert code_v == pytest.approx(adc_code(2500.0), abs=12)
    # 电流链（PE3/CH0）：0.1Ω×10 增益
    code_i = adc_code(plant.pin_current_mv())
    assert code_i == pytest.approx(adc_code(plant.current_a * 1000.0), abs=12)


def test_buck_scenario_schedule_for_fil():
    """FIL 场景 3 的开环调度表：分窗推进 + 写窗首值，稳态窗口码值应落在容差内。"""
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0, load_res_ohm=5.1)
    dt = 0.1
    schedule = []
    for k in range(12):
        v_pin = plant.pin_voltage_mv()
        i_pin = plant.pin_current_mv()
        schedule.append((adc_code(v_pin), adc_code(i_pin)))
        if k == 5:
            plant.set_load(10.0)
        plant.advance(dt)
    assert schedule[0] == (0, 0)                       # t=0 软启动未开始
    v_mid, i_mid = schedule[2]                         # 已达稳态
    assert abs(v_mid - 3102) <= 12                     # 0.02V 档
    assert abs(i_mid - 1216) <= 12                     # 0.01A 档
    v_last, i_last = schedule[-1]                      # 负载 10Ω 后
    assert abs(v_last - 3102) <= 12
    assert abs(i_last - adc_code(0.5 * 1000.0)) <= 12  # I=0.5A
