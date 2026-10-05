"""a2000sim — A2000TM4 课程开发板无实物仿真实验台的参考模型层。

所有常数的出处标注约定：
- [M-x]  → docs/2-measured-board-facts.md 的实测条目
- [DS]   → TI/Titan Micro 数据手册事实
- [PPT]  → 课程讲义《如何提高ADC采样精度和稳定度》
- [SCH]  → A2000TM4 电原理图 v3
"""

from .tm1638 import (  # noqa: F401
    SEGMENT_CODE,
    KeyMatrix,
    TM1638,
    TM1638Driver,
    DirectPinBus,
)
from .dac6571 import (  # noqa: F401
    DAC6571_ADDR7,
    DAC6571_ADDR8_WRITE,
    DAC6571,
    SoftI2CMaster,
    I2CBusDecoder,
)
from .plant import (  # noqa: F401
    BuckPlant,
    FLOATING_PE3,
    FLOATING_PE2,
    VREF_MV,
    ADC_MAX,
    R_SENSE_OHM,
    CURRENT_ADC_CHANNEL,
    CURRENT_ADC_PIN,
    VOLTAGE_ADC_CHANNEL,
    VOLTAGE_ADC_PIN,
    ConditioningChannel,
    VOLTAGE_CHAIN,
    CURRENT_CHAIN,
    FloatingPinModel,
    adc_code,
    adc_mv,
)
from .fw_algorithms import (  # noqa: F401
    SYSCLOCK_HZ,
    systick_reload,
    pll_sysclk,
    SlidingWindowAverage,
    HysteresisFilter,
    fit_linear,
    apply_linear,
    COURSE_CAL,
)
