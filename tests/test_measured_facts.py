"""实测档案中的可机械复核事实，防止文档转录与通道定义漂移。"""

from a2000sim.plant import (CURRENT_ADC_CHANNEL, CURRENT_ADC_PIN,
                            VOLTAGE_ADC_CHANNEL, VOLTAGE_ADC_PIN)


EEPROM_BLOCK0 = [
    0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF,
    0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF,
    0xFFFFFFFF, 0xFFFFFFFF, 0x1CD1FFAD, 0xFFFFFFFF,
    0x736F7865, 0x21657469, 0x66663037, 0xFFFFFFFF,
]


def test_eeprom_factory_pattern():
    """[M-6] 小端原始字应包含记录的 exosite!70ff 厂测残留。"""
    raw = b"".join(word.to_bytes(4, "little") for word in EEPROM_BLOCK0)
    assert b"exosite!70ff" in raw


def test_measured_channel_assignment():
    """[SCH/M-5] 电流=PE3/AIN0/CH0；电压=PE2/AIN1/CH1。"""
    assert (CURRENT_ADC_CHANNEL, CURRENT_ADC_PIN) == (0, "PE3/AIN0")
    assert (VOLTAGE_ADC_CHANNEL, VOLTAGE_ADC_PIN) == (1, "PE2/AIN1")
