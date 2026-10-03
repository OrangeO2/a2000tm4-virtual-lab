"""DAC6571 软件 I2C 参考模型。

出处标注：
- 协议常量 [DS] TI DAC6571 datasheet (Rev.B)：10 位、I2C、写地址
  1001 100 + A0 + W —— A0=GND 时 8 位写地址 0x98（7 位地址 0x4C）。
  数据两字节：[PD1 PD0 D9..D6][D5..D0 00]，PD=00 正常工作。
- 输出 [DS]：Vout = VDD × code / 1024，缓冲轨到轨输出（0 ~ VDD）。
- 位时序发射器复刻课程 DAC6571.c 的 GPIO 位拍（MSB 先行、
  SCL 上升沿锁存、第 9 脉冲 ACK、START/STOP 语义）。
"""

from __future__ import annotations

DAC6571_ADDR7 = 0x4C
DAC6571_ADDR8_WRITE = 0x98
DAC6571_CODE_MAX = 1024  # 10 位


def dac6571_voltage(code: int, vdd: float = 3.3) -> float:
    """[DS] Vout = VDD × code/1024（code 超范围按 10 位截断的语义报错）。"""
    if not 0 <= code < DAC6571_CODE_MAX:
        raise ValueError(f"DAC6571 编码须在 0..1023，得到 {code}")
    return vdd * code / DAC6571_CODE_MAX


class DAC6571:
    """虚拟 DAC6571：接受解码后的写帧，维护输出电压。"""

    def __init__(self, vdd: float = 3.3):
        self.vdd = vdd
        self.code = 0
        self.power_down = (0, 0)
        self.frames: list[tuple[int, int]] = []

    def on_write_frame(self, addr8: int, data: list[int]) -> None:
        if len(data) < 2:
            raise ValueError("DAC6571 写帧需要 2 数据字节（Fast Mode）")
        if addr8 != DAC6571_ADDR8_WRITE:
            raise ValueError(f"地址不匹配: 收到 {addr8:#04x}，期望 {DAC6571_ADDR8_WRITE:#04x}")
        raw = (data[0] << 8) | data[1]
        self.power_down = ((raw >> 14) & 0b11, 0)
        self.code = (raw >> 2) & 0x3FF   # 数据左对齐 2 位填充：code=raw>>2 [DS]
        self.frames.append((addr8, self.code))

    @property
    def voltage(self) -> float:
        return dac6571_voltage(self.code, self.vdd)


class SoftI2CMaster:
    """复刻课程 DAC6571.c 的 GPIO 位拍发射器（回调式，便于接解码器/事件记录）。

    时序（与课程 DAC6571_Fastmode_Operation 一致）：
      START：SCL=1 期间 SDA 1→0，随后 SCL=0
      数据：SCL=0 时置 SDA（MSB 先行），SCL 1→0 完成一位
      ACK：第 9 脉冲（课程不检查 ACK 电平，模型照实标注）
      STOP：SCL=1 期间 SDA 0→1
    """

    def __init__(self, on_pin: callable):
        self.on_pin = on_pin  # on_pin(scl: int, sda: int | None)

    def _bit(self, scl: int, sda: int | None) -> None:
        self.on_pin(scl, sda)

    def start(self) -> None:
        self._bit(1, 1)
        self._bit(1, 0)
        self._bit(0, 0)

    def stop(self) -> None:
        self._bit(0, 0)
        self._bit(1, 0)
        self._bit(1, 1)

    def write_byte(self, byte: int) -> None:
        for i in range(7, -1, -1):
            self._bit(0, (byte >> i) & 1)
            self._bit(1, (byte >> i) & 1)
            self._bit(0, (byte >> i) & 1)

    def ack_slot(self) -> None:
        """第 9 个时钟；课程实现把 SDA 切输入且不检查电平，模型发释放态。"""
        self._bit(0, None)
        self._bit(1, None)
        self._bit(0, None)

    def fastmode_operation(self, code: int, addr8: int = DAC6571_ADDR8_WRITE) -> None:
        """一次完整 DAC 转换（复刻课程函数语义，3 字节写帧）。"""
        if not 0 <= code < DAC6571_CODE_MAX:
            raise ValueError(f"DAC 编码须在 0..1023，得到 {code}")
        code1 = code << 2                       # 左移 2 位，PD1PD0=00
        msb = (code1 >> 8) & 0xFF
        lsb = code1 & 0xFF
        self.start()
        self.write_byte(addr8)
        self.ack_slot()
        self.write_byte(msb)
        self.ack_slot()
        self.write_byte(lsb)
        self.ack_slot()
        self.stop()


class I2CBusDecoder:
    """从 SCL/SDA 事件流解码 I2C 写帧（供 Renode 访问日志 / 实板逻辑分析仪共用）。

    feed(scl, sda, prev_sda) 逐边沿喂入；完整写帧通过 on_frame(addr8, data) 回调。
    数据位在 SCL 低电平建立、上升沿锁存（与课程软件 I2C 一致）。
    """

    def __init__(self, on_frame: callable):
        self.on_frame = on_frame
        self._scl = 1
        self._sda = 1
        self._in_frame = False
        self._bits: list[int] = []
        self._bytes: list[int] = []
        self._addr: int = -1
        self._skip_ack = False

    def feed(self, scl: int, sda: int | None, prev_sda: int | None = None) -> None:
        """喂入一次引脚变化。sda=None 表示释放（Hi-Z，按上拉视为 1）。

        prev_sda：调用方若不给，则用上一次的 sda（None 视为 1）。
        """
        level = 1 if sda is None else sda
        prev = self._sda if prev_sda is None else prev_sda

        if scl == 1 and self._scl == 1:
            if level == 0 and prev == 1:            # START
                self._in_frame = True
                self._bits, self._bytes, self._addr = [], [], -1
                self._skip_ack = False
            elif level == 1 and prev == 0 and self._in_frame:
                self._finish_frame()                # STOP
                self._in_frame = False
        elif scl == 1 and self._scl == 0 and self._in_frame:
            if self._skip_ack:                      # 第 9 脉冲 = ACK 槽，跳过
                self._skip_ack = False
            else:
                self._bits.append(level)            # SCL 上升沿锁存
                if len(self._bits) == 8:
                    self._bytes.append(self._pack(self._bits))
                    self._bits = []
                    self._skip_ack = True           # 下一上升沿是 ACK
        self._scl, self._sda = scl, level

    def _pack(self, bits: list[int]) -> int:
        v = 0
        for b in bits:
            v = (v << 1) | b
        return v

    def _finish_frame(self) -> None:
        if self._bytes:
            addr = self._bytes[0]
            data = self._bytes[1:]
            if data:
                self.on_frame(addr, data)
        self._bytes = []
