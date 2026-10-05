"""被控对象与信号链模型（稳压源 → TLV2372 调理 → ADC）。

出处标注：
- ADC 参考电压/位数 [DS] TM4C1294NCPDT：12 位 SAR，VREFP=VDDA=3.3V
- 分压比 ≈0.5、差分增益 10–20、+7V 运放供电、Z3.3 钳位 [SCH][课程实验2指导书]
- 固件标定系数 ×2.005/−1.141、×1.002/−36.12 [PPT《如何提高ADC采样精度和稳定度》]
- 悬空引脚行为 [M-5 实测]：静息 ~1.2V、连续采样单调衰减、静置恢复
"""

from __future__ import annotations

from dataclasses import dataclass

VREF_MV = 3300.0    # [DS] ADC 参考电压（VDDA）
ADC_MAX = 4095      # [DS] 12 位
R_SENSE_OHM = 0.1   # [SCH] 稳压源板电流采样电阻 R3
DIFF_GAIN = 10.0    # [课程实验2] 差分放大建议增益（10–20 取下限）


def adc_code(v_mv: float) -> int:
    """引脚电压(mV) → 12 位 ADC 码。"""
    code = int(round(v_mv / VREF_MV * ADC_MAX))
    return max(0, min(ADC_MAX, code))


def adc_mv(code: int) -> float:
    """12 位 ADC 码 → 引脚电压(mV)。"""
    return code * VREF_MV / ADC_MAX


@dataclass
class ConditioningChannel:
    """调理通道：真实量 → 引脚电压（含 Z3.3 钳位）。

    voltage 链：pin = Vout × 分压比(0.5)，跟随器缓冲
    current 链：pin = I × R_SENSE × DIFF_GAIN
    clamp：R40/R42(10Ω) + Z3.3 稳压管 → 引脚电压不超过 ~3.3V
    """

    scale: float            # 量 → 引脚 mV 的增益
    clamp_mv: float = 3300.0

    def forward(self, value: float) -> float:
        """value: 电压 mV 或电流 A（由子类/工厂决定 scale 的量纲）。"""
        return min(value * self.scale, self.clamp_mv)


VOLTAGE_CHAIN = ConditioningChannel(scale=0.5)            # Vout(mV) → pin(mV)
CURRENT_CHAIN = ConditioningChannel(scale=R_SENSE_OHM * DIFF_GAIN * 1000.0)  # I(A) → pin(mV)


# [M-5 实测标定] probe7（2026-10-03，docs/2）实测的悬空引脚参数：
#   PE3(AIN0/CH0)：静息 1567.6 码 = 1263.1 mV（5 次独立测量 1559–1578）；
#                  连续采样尾点 1422–1448 码（中点 1428 码 = 1150.5 mV）；
#                  逐样本衰减系数 ~0.32；600ms 空闲恢复 ≥98%（tau ≈ 0.15s）
#   PE2(AIN1/CH1)：静息 1454 码 = 1170.8 mV（1446–1460）；
#                  尾点未直接测量，按与 PE3 相同的绝对跌落估计 1314 码 = 1058.2 mV
FLOATING_PE3 = dict(resting_mv=1263.1, plateau_mv=1150.5,
                    bleed_per_sample=0.32, recovery_tau_s=0.15)
FLOATING_PE2 = dict(resting_mv=1170.8, plateau_mv=1058.2,
                    bleed_per_sample=0.32, recovery_tau_s=0.15)


class FloatingPinModel:
    """悬空 ADC 引脚的现象学模型（参数标定自 M-5 实测，probe7 回填）。

    行为：静息电平 resting_mv；每被采样一次向 plateau_mv 衰减 bleed_per_sample；
    空闲时以 recovery_tau（秒）指数恢复。这不是电路仿真，是把实测曲线参数化，
    用于生成"类真实"的 ADC 输入激励与验证采样策略（滑动平均/迟滞）。

    默认参数 = PE3 实测标定（FLOATING_PE3）；PE2 用 FLOATING_PE2。
    实测序列（PE3 连续 8 次采样，码）：1523→1498→1476→1463→1445→1448→1442→1422，
    模型复现见 tests/test_plant.py::test_floating_pe3_matches_probe7_bleed。
    """

    def __init__(self, resting_mv: float = 1263.1, plateau_mv: float = 1156.0,
                 bleed_per_sample: float = 0.32, recovery_tau_s: float = 0.15):
        self.resting_mv = resting_mv
        self.plateau_mv = plateau_mv
        self.bleed_per_sample = bleed_per_sample
        self.recovery_tau_s = recovery_tau_s
        self._pin_mv = resting_mv

    def sample(self, dt_since_last_s: float = 0.04) -> float:
        """返回本次采样时引脚电压(mV)，并施加采样放电。"""
        import math
        self._pin_mv += (self.resting_mv - self._pin_mv) * (1 - math.exp(-dt_since_last_s / self.recovery_tau_s))
        v = self._pin_mv
        self._pin_mv -= (self._pin_mv - self.plateau_mv) * self.bleed_per_sample
        return v

    @property
    def pin_mv(self) -> float:
        return self._pin_mv


class BuckPlant:
    """TPS40200 降压稳压源的被控对象模型（v0.3，现象学）。

    忠实复现的行为（全部可在 FIL 中被课程固件"看到"）：
    - 软启动：输出从 0 线性爬升到额定值，时长 soft_start_ms
      [课程实验1：C8=2.2µF → 软启动 ≥30ms 的选型结论]
    - 稳态：输出 = 额定值（电压调整率/负载调整率按理想调节处理）
    - 负载阶跃：负载电流变化瞬间输出跌落 dip_mv（与 ΔI 成正比），
      随后以 tau_recovery 一阶恢复到新稳态 [现象学参数，非电路仿真]
    - 电流：I_R3 = Vout/R_load（评分口径；底板 R23 200Ω 假负载的影响
      通过 min_load_a 参数可选计入，默认 0 以对齐评分表换算）

    信号链输出：
      pin_voltage_mv() = VOLTAGE_CHAIN.forward(vout)   （0.5 分压 → PE2 侧）
      pin_current_mv() = CURRENT_CHAIN.forward(i)      （0.1Ω×10 → PE3 侧）

    时间推进：advance(dt_s) 由 FIL 测试分窗调用（与 Renode RunFor 同步）。
    """

    def __init__(self, vout_nominal_mv: float = 5000.0,
                 soft_start_ms: float = 30.0,
                 load_res_ohm: float = 5.1,
                 dip_mv_per_a: float = 120.0,
                 tau_recovery_s: float = 0.002,
                 min_load_a: float = 0.0,
                 vin_mv: float = 10000.0,
                 line_reg_ppm_per_v: float = 0.0,
                 ocp_trip_a: float = 1.5,
                 ocp_hiccup_s: float = 0.1,
                 ocp_enabled: bool = True):
        self.vout_nominal_mv = vout_nominal_mv
        self.soft_start_ms = soft_start_ms
        self.load_res_ohm = load_res_ohm
        self.dip_mv_per_a = dip_mv_per_a
        self.tau_recovery_s = tau_recovery_s
        self.min_load_a = min_load_a
        # 线调整率 [现象学]：Vin 偏离 15V 中点每 1V 输出漂移 ppm×1e-6（0=理想调节）
        self.vin_mv = vin_mv
        self.line_reg_ppm_per_v = line_reg_ppm_per_v
        # 过流保护 [课程任务：触发允许范围 1.1~1.9A；评分：关断 5 分+恢复 5 分]
        self.ocp_trip_a = ocp_trip_a
        self.ocp_hiccup_s = ocp_hiccup_s
        self.ocp_enabled = ocp_enabled
        self._tripped = False
        self._trip_t = -1e9
        self.t_s = 0.0
        self._vout_mv = 0.0
        self._dip_mv = 0.0
        self._last_load = load_res_ohm

    @property
    def vout_mv(self) -> float:
        return self._vout_mv

    def _nominal_mv(self) -> float:
        """额定输出（含线调整率：Vin 偏离 15V 中点每伏漂移 ppm×1e-6）。"""
        factor = 1.0 + self.line_reg_ppm_per_v * 1e-6 * (self.vin_mv - 15000.0) / 1000.0
        return self.vout_nominal_mv * factor

    @property
    def current_a(self) -> float:
        """R3 采样电流 [评分口径]：I = Vout/R_load（+ 可选最小负载）。"""
        if self.load_res_ohm <= 0:
            return self.min_load_a
        return self._vout_mv / 1000.0 / self.load_res_ohm + self.min_load_a

    def set_load(self, res_ohm: float) -> None:
        """负载阶跃：按 ΔI 施加输出跌落，随后 advance 中一阶恢复。"""
        old_i = self.current_a
        self.load_res_ohm = res_ohm
        delta_i = abs(self.current_a - old_i)
        self._dip_mv += self.dip_mv_per_a * delta_i

    def advance(self, dt_s: float) -> None:
        """推进 dt_s 的虚拟时间（软启动 + 负载阶跃恢复 + 过流保护打嗝）。"""
        import math
        self.t_s += dt_s
        nominal = self._nominal_mv()

        # 过流保护判定（以额定输出下的负载电流为准）[课程任务 1.1~1.9A]
        i_nom = (nominal / 1000.0) / self.load_res_ohm if self.load_res_ohm > 0 else self.min_load_a
        if self.ocp_enabled and not self._tripped and i_nom > self.ocp_trip_a:
            self._tripped = True
            self._trip_t = self.t_s
        if self._tripped and self.t_s - self._trip_t >= self.ocp_hiccup_s and i_nom <= self.ocp_trip_a:
            self._tripped = False                       # 负载已回到安全范围 → 自动恢复

        if self._tripped:
            # 关断：输出快速衰减到 0（打嗝间隔后按上文条件重试）
            self._vout_mv = max(0.0, self._vout_mv - 2.0e6 * dt_s)   # ≈ I/C：2A 进 940µF
            self._dip_mv = 0.0
            return

        alpha = 1.0 - math.exp(-dt_s / self.tau_recovery_s) if self.tau_recovery_s > 0 else 1.0
        if self.t_s * 1000.0 < self.soft_start_ms:
            # 软启动：输出直接跟随线性爬升（一阶滞后只作用于阶跃恢复）
            self._vout_mv = max(0.0, nominal * (self.t_s * 1000.0 / self.soft_start_ms) - self._dip_mv)
        else:
            self._vout_mv = self._vout_mv + (nominal - self._vout_mv) * alpha
            self._vout_mv = max(0.0, self._vout_mv - self._dip_mv)
        self._dip_mv *= max(0.0, 1.0 - alpha)   # 跌落随同一时间常数恢复

    @property
    def tripped(self) -> bool:
        return self._tripped

    def pin_voltage_mv(self) -> float:
        """电压调理输出（→ PE2 侧，adc_demo 的 CH1/AIN1）。"""
        return VOLTAGE_CHAIN.forward(self._vout_mv)

    def pin_current_mv(self) -> float:
        """电流调理输出（→ PE3 侧，adc_demo 的 CH0/AIN0）。"""
        return CURRENT_CHAIN.forward(self.current_a)
