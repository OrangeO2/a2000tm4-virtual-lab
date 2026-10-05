"""信号链与被控对象模型测试：ADC 编码、调理通道、钳位、悬空引脚行为。"""
import pytest

from a2000sim.plant import (VREF_MV, ADC_MAX, CURRENT_CHAIN, FLOATING_PE3,
                            FLOATING_PE2, FloatingPinModel, VOLTAGE_CHAIN,
                            adc_code, adc_mv)

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
    """[M-5 实测标定] 连续采样单调衰减、静置恢复（PE3 参数）。"""
    import math
    pin = FloatingPinModel(**FLOATING_PE3)
    samples = [pin.sample(dt_since_last_s=0.0) for _ in range(8)]  # 背靠背无恢复
    assert all(samples[i] >= samples[i + 1] - 1e-9 for i in range(7)), \
        f"连续采样应衰减: {samples}"
    assert samples[0] > samples[-1]
    # 静置恢复：600ms 空闲后应回到 ≥95% 静息电平（probe7 实测协议）
    pin._pin_mv += (pin.resting_mv - pin._pin_mv) * (1 - math.exp(-0.6 / pin.recovery_tau_s))
    assert pin.pin_mv == pytest.approx(pin.resting_mv, rel=0.05)


def test_floating_pe3_matches_probe7_bleed_sequence():
    """[M-5] 按 probe7 实测协议复现 PE3 采样序列：
    5 次静息测量（600ms 空闲→采样→放电）后紧接 8 次连续采样。"""
    from a2000sim.plant import adc_code
    pin = FloatingPinModel(**FLOATING_PE3)
    for _ in range(5):                     # probe7 的静息测量协议
        pin.sample(dt_since_last_s=0.6)
    measured = [1523, 1498, 1476, 1463, 1445, 1448, 1442, 1422]  # probe7 实测码
    modeled = [pin.pin_mv for _ in range(8)]  # 占位，下面逐次真实采样
    modeled = []
    for _ in range(8):
        modeled.append(adc_code(pin.sample(dt_since_last_s=0.0)))
    for k, (m, x) in enumerate(zip(modeled, measured)):
        tol = 8 if k < 7 else 16           # 实测自噪声 ±6 码 + 模型舍入
        assert abs(m - x) <= tol, f"第 {k} 次采样: 模型 {m} vs 实测 {x}（偏差 >{tol} 码）"


def test_floating_pe2_distinct_resting():
    """[M-5] PE2 与 PE3 静息电平不同（1170.8 vs 1263.1 mV），模型分参。"""
    pe3 = FloatingPinModel(**FLOATING_PE3)
    pe2 = FloatingPinModel(**FLOATING_PE2)
    assert pe3.resting_mv == pytest.approx(1263.1, abs=0.1)
    assert pe2.resting_mv == pytest.approx(1170.8, abs=0.1)
    assert pe2.resting_mv < pe3.resting_mv


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
    # 电压链（PE2/AIN1/CH1）：0.5 分压
    code_v = adc_code(plant.pin_voltage_mv())
    assert code_v == pytest.approx(adc_code(2500.0), abs=12)
    # 电流链（PE3/AIN0/CH0）：0.1Ω×10 增益
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


# ---------------- v0.4+：线调整率与过流保护（评分项仿真） ----------------

def test_buck_line_regulation_meets_course_criterion():
    """[评分表] 电压调整率：Vin 10→20V，ΔV <10mV 得 5 分（线调整率 50ppm/V）。"""
    from a2000sim.scoring import score_line_regulation
    p10 = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0,
                    load_res_ohm=5.1, vin_mv=10000.0, line_reg_ppm_per_v=50.0)
    p20 = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0,
                    load_res_ohm=5.1, vin_mv=20000.0, line_reg_ppm_per_v=50.0)
    for p in (p10, p20):
        p.advance(0.05)
    dv = abs(p20.vout_mv - p10.vout_mv)
    assert dv == pytest.approx(2.5, abs=0.2)     # 50ppm/V × 10V × 5000mV
    assert score_line_regulation(dv) == 5


def test_buck_overcurrent_protection_and_recovery():
    """[评分表] 过流保护和恢复：有效关断 5 分 + 自动恢复 5 分。

    场景：5.1Ω 正常 → 并联 2.5Ω（I=2A > 触发 1.5A）→ 关断（打嗝重试仍过流保持）
    → 负载回到 5.1Ω → 自动恢复 5V。
    """
    plant = BuckPlant(vout_nominal_mv=5000.0, soft_start_ms=30.0,
                      load_res_ohm=5.1, ocp_trip_a=1.5, ocp_hiccup_s=0.05)
    plant.advance(0.05)
    assert not plant.tripped
    assert plant.current_a == pytest.approx(0.98, rel=0.01)

    plant.set_load(2.5)                          # I = 2A > 1.5A
    plant.advance(0.01)                          # 打嗝周期内：输出快速衰减
    assert plant.tripped
    assert plant.vout_mv < 200                   # 有效关断（评分第一档）
    plant.advance(0.05)                          # 打嗝重试仍过流 → 保持关断
    assert plant.tripped and plant.vout_mv == 0

    plant.set_load(5.1)                          # 负载恢复正常
    plant.advance(0.01)
    assert not plant.tripped                     # 自动恢复
    plant.advance(0.05)
    assert plant.vout_mv == pytest.approx(5000.0, rel=0.01)
    from a2000sim.scoring import score_protection
    assert score_protection(tripped=True, recovered=True) == 10


def test_buck_overcurrent_trip_within_course_window():
    """[课程任务] 触发电流允许范围 1.1~1.9A：1.5A 触发值应在窗内；1.0A 不触发。"""
    p = BuckPlant(load_res_ohm=5.0, ocp_trip_a=1.5)
    p.advance(0.05)
    assert not p.tripped                          # 1.0A < 1.5A
    p.set_load(3.0)                               # I = 1.67A ∈ [1.1, 1.9]
    p.advance(0.01)
    assert p.tripped                              # 触发且在允许窗内
