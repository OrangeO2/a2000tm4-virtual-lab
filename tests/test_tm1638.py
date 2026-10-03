"""TM1638 协议模型测试：段码、写显示闭环、键值闭环、课程键值表。"""
import pytest

from a2000sim.tm1638 import (KeyMatrix, TM1638, TM1638Driver, DirectPinBus,
                             decode_course_keys, SEGMENT_CODE)


@pytest.fixture()
def chip_and_driver():
    chip = TM1638()
    driver = TM1638Driver(DirectPinBus(chip))
    return chip, driver


def test_segment_table_facts():
    """段码表与课程 tm1638.c 逐位一致（事实数据抽查）。"""
    assert SEGMENT_CODE["0"] == 0x3F
    assert SEGMENT_CODE["8"] == 0x7F
    assert SEGMENT_CODE["1"] == 0x06
    assert SEGMENT_CODE["-"] == 0x40
    assert SEGMENT_CODE[" "] == 0x00


def test_display_write_roundtrip(chip_and_driver):
    chip, driver = chip_and_driver
    driver.init(brightness=2)
    driver.refresh(digit=[1, 2, 3, 4, 5, 6, 7, 8], pnt=0x04, led=[1] * 8)
    # 显示 RAM：偶字节=段码，奇字节=LED；digit[i] → display_ram[i*2]
    assert chip.display_ram[0] == SEGMENT_CODE["1"]
    assert chip.display_ram[4] == SEGMENT_CODE["3"] | 0x80   # pnt bit2 → digit[2]="3" → RAM[4]
    assert chip.display_ram[14] == SEGMENT_CODE["8"]
    assert chip.leds() == [1] * 8
    assert chip.display_on and chip.brightness == 2
    assert "1" in chip.render() and "8." not in chip.render().split()[0]


def test_digit_index_mapping(chip_and_driver):
    """digit[i] 应落在 display_ram 的第 i 对字节（板上左→右 = digit[4][5][6][7][0..3]
    的映射属于固件层，模型层保持 GRID1..8 = digit[0..7] 的物理顺序）。"""
    chip, driver = chip_and_driver
    driver.refresh(digit=[9, 0, 0, 0, 0, 0, 0, 0])
    assert chip.display_ram[0] == SEGMENT_CODE["9"]


def test_key_roundtrip(chip_and_driver):
    chip, driver = chip_and_driver
    keys = KeyMatrix()
    chip.keys = keys
    for key in range(1, 10):
        keys.release_all()
        keys.press(key)
        c, code = driver.read_keyboard()
        assert code == key, f"键 {key} 解码失败: c={c}"
        assert c in (keys.key_scan_bytes(),) or decode_course_keys(c[0], c[1]) == [key]


def test_no_key_returns_zero(chip_and_driver):
    chip, driver = chip_and_driver
    c, code = driver.read_keyboard()
    assert c == (0, 0, 0, 0)
    assert code == 0


def test_a2000_no_key_pattern_is_ff():
    """A2000 接线下无键回读 0xFF（实测 M-5 注）也必须安全解码为“无键”。"""
    chip = TM1638(keys=KeyMatrix(no_key_pattern=(0xFF, 0xFF, 0xFF, 0xFF)))
    driver = TM1638Driver(DirectPinBus(chip))
    c, code = driver.read_keyboard()
    assert c == (0xFF, 0xFF, 0xFF, 0xFF)
    assert code == 0  # 课程精确匹配解码下 FF 不命中任何键号


def test_course_key_decode_table():
    assert decode_course_keys(0x04, 0x00) == [1]
    assert decode_course_keys(0x02, 0x00) == [2]
    assert decode_course_keys(0x01, 0x00) == [3]
    assert decode_course_keys(0x40, 0x00) == [4]
    assert decode_course_keys(0x20, 0x00) == [5]
    assert decode_course_keys(0x10, 0x00) == [6]
    assert decode_course_keys(0x00, 0x04) == [7]
    assert decode_course_keys(0x00, 0x02) == [8]
    assert decode_course_keys(0x00, 0x01) == [9]
    assert decode_course_keys(0x00, 0x00) == []
    assert decode_course_keys(0xFF, 0xFF) == []  # 精确匹配下多键/FF 不命中
