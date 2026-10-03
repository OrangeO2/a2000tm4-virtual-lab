"""DAC6571 模型测试：协议常量、发射↔解码闭环、输出电压。"""
import pytest

from a2000sim.dac6571 import (DAC6571, DAC6571_ADDR7, DAC6571_ADDR8_WRITE,
                              I2CBusDecoder, SoftI2CMaster, dac6571_voltage)


def test_protocol_constants():
    """[DS] A0=GND：7 位地址 0x4C，8 位写地址 0x98。"""
    assert DAC6571_ADDR7 == 0x4C
    assert DAC6571_ADDR8_WRITE == 0x98


def test_voltage():
    assert dac6571_voltage(0) == 0.0
    assert dac6571_voltage(1023, 3.3) == pytest.approx(3.3 * 1023 / 1024)  # 满码差 1 LSB 到 VDD
    assert dac6571_voltage(512, 3.3) == pytest.approx(3.3 * 512 / 1024)
    with pytest.raises(ValueError):
        dac6571_voltage(1024)


@pytest.mark.parametrize("code", [0, 1, 512, 1000, 1023])
def test_master_decoder_roundtrip(code):
    """课程位拍发射器 → I2C 解码器 → 虚拟芯片，全链路还原编码值。"""
    dac = DAC6571(vdd=3.3)
    master = SoftI2CMaster(on_pin=lambda scl, sda: None)

    events: list[tuple[int, int | None]] = []

    def on_pin(scl, sda):
        events.append((scl, sda))
        decoder.feed(scl, sda)

    decoder = I2CBusDecoder(on_frame=dac.on_write_frame)
    master = SoftI2CMaster(on_pin=on_pin)
    master.fastmode_operation(code)

    assert dac.frames, "解码器未还原出写帧"
    addr8, got_code = dac.frames[-1]
    assert addr8 == DAC6571_ADDR8_WRITE
    assert got_code == code
    assert dac.voltage == pytest.approx(dac6571_voltage(code, 3.3))


def test_pd_bits_are_zero_in_fastmode():
    """课程 Fastmode 左移 2 位 → PD1PD0=00（正常工作模式）。"""
    dac = DAC6571()
    events: list[tuple[int, int | None]] = []
    decoder = I2CBusDecoder(on_frame=dac.on_write_frame)

    def on_pin(scl, sda):
        decoder.feed(scl, sda)

    SoftI2CMaster(on_pin=on_pin).fastmode_operation(1023)
    assert dac.power_down[0] == 0


def test_wrong_address_rejected():
    dac = DAC6571()
    with pytest.raises(ValueError):
        dac.on_write_frame(0x9A, [0xFF, 0xFC])
