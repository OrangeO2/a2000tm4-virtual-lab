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


class FloatingPinModel:
    """悬空 ADC 引脚的现象学模型（参数标定自 M-5 实测）。

    行为：静息电平 resting_mv；每被采样一次向 plateau_mv 衰减 bleed_per_sample；
    空闲时以 recovery_tau（秒）指数恢复。这不是电路仿真，是把实测曲线参数化，
    用于生成"类真实"的 ADC 输入激励与验证采样策略（滑动平均/迟滞）。
    """

    def __init__(self, resting_mv: float = 1260.0, plateau_mv: float = 1165.0,
                 bleed_per_sample: float = 0.045, recovery_tau_s: float = 2.0):
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
