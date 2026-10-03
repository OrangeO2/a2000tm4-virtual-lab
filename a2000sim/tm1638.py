"""TM1638 位级协议参考模型（虚拟芯片 + 课程时序驱动器）。

出处标注：
- 段码表 [课程 tm1638.c / Titan Micro TM1638 通用共阴段码，事实数据]
- 键值解码表 [课程 tm1638.c TM1638_Readkeyboard()，A2000 实测有效]
- 时序 [课程 tm1638.c：STB 低→命令/数据（LSB 先行、CLK 上升沿锁存）→STB 高]
- 命令解码 [TM1638 datasheet]：0x40 写显示（自动地址）、0x44 写显示（固定地址）、
  0x42 读键扫数据、0x8x 显示控制、0xC0|n 地址命令
- 键数据位序说明见 TM1638.bit_order（A2000 二极管键矩阵接线下的经验约定）

两条使用路径：
1. TM1638 + TM1638Driver + DirectPinBus —— 纯模型闭环（本层测试）。
2. renode_access / 实板逻辑分析仪 —— 引脚事件流喂给 TM1638 解码。
"""

from __future__ import annotations

# 共阴 7 段段码（bit0=A ... bit6=G，bit7=DP）[课程 tm1638.c TM1638_DigiSegment]
SEGMENT_CODE = {
    "0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66,
    "5": 0x6D, "6": 0x7D, "7": 0x07, "8": 0x7F, "9": 0x6F,
    "A": 0x77, "b": 0x7C, "C": 0x39, "d": 0x5E, "E": 0x79,
    "F": 0x71, "G": 0x3D, "H": 0x76, "I": 0x06, "L": 0x38,
    "n": 0x37, "o": 0x5C, "P": 0x73, "q": 0x67, "r": 0x50,
    "S": 0x6D, "t": 0x78, "U": 0x3E, "Y": 0x6E,
    "-": 0x40, "_": 0x08, " ": 0x00,
}
# 反查表：数字后插入以覆盖同码字母（"1"/"I" 共用 0x06、"5"/"S" 共用 0x6D）
_SEG_TO_CHAR = {v: k for k, v in SEGMENT_CODE.items()}
_SEG_TO_CHAR.update({SEGMENT_CODE[d]: d for d in "0123456789"})

# 课程键值解码表 [课程 tm1638.c TM1638_Readkeyboard()，A2000 实测有效]
# 键号 → (字节索引, 课程侧字节值)
_COURSE_KEY_TABLE = {
    1: (0, 0x04), 2: (0, 0x02), 3: (0, 0x01),
    4: (0, 0x40), 5: (0, 0x20), 6: (0, 0x10),
    7: (1, 0x04), 8: (1, 0x02), 9: (1, 0x01),
}


def decode_course_keys(c0: int, c1: int) -> list[int]:
    """按课程解码表把键扫描字节映射为键号列表（多键同按返回全部命中）。"""
    keys = [k for k, (idx, val) in _COURSE_KEY_TABLE.items()
            if (c0 if idx == 0 else c1) == val]
    return sorted(keys)


class KeyMatrix:
    """A2000 的 3×3 键矩阵虚拟侧。

    press(n) / release(n) / release_all()；key_scan_bytes() 返回 TM1638
    在"读键扫数据"命令后应输出的 4 个原始字节。

    ⚠️ A2000 接线事实 [SCH]：键列经 D10–D12 二极管接 KS/SEG 复用线，
    "无键 = 读 0x00"的通用 TM1638 假设在此板上**未被验证**
    （实板调试口测得无键回读 0xFF，见 docs/2 M-5 注）。
    因此无键态输出参数化：默认 0x00（TM1638 数据手册理想行为），
    复刻 A2000 实测行为时用 no_key_pattern=(0xFF,)*4。
    """

    def __init__(self, no_key_pattern: tuple[int, int, int, int] = (0, 0, 0, 0)):
        self.no_key_pattern = no_key_pattern
        self.pressed: set[int] = set()

    def press(self, key: int) -> None:
        if key not in _COURSE_KEY_TABLE:
            raise ValueError(f"键号 {key} 不在 1..9")
        self.pressed.add(key)

    def release(self, key: int) -> None:
        self.pressed.discard(key)

    def release_all(self) -> None:
        self.pressed.clear()

    def key_scan_bytes(self) -> tuple[int, int, int, int]:
        if not self.pressed:
            return self.no_key_pattern
        c = [0, 0, 0, 0]
        for k in sorted(self.pressed):
            idx, val = _COURSE_KEY_TABLE[k]
            c[idx] |= val
        return (c[0], c[1], c[2], c[3])


class TM1638:
    """位级虚拟 TM1638。

    引脚级接口：
      stb(level) / clk(level) / dio(level)：驱动引脚（锁存边沿语义）
      get_dio()：读 DIO（读键扫描期间芯片驱动数据位，其余 Hi-Z → None）

    读键数据时序模型（与课程采样点自洽）：
      进入 key_read 时芯片不驱动（Hi-Z，_read_ptr=-1）；每个 CLK 下降沿推出
      下一位；课程驱动器在 CLK 上升沿后采样——第 1 次采样得到 bit0，共 32 位。

    显示 RAM：16 字节，偶字节=数码段码，奇字节=LED 字节 [课程 RefreshDIGIandLED]。
    """

    def __init__(self, keys: KeyMatrix | None = None):
        self.display_ram = bytearray(16)
        self.brightness = 0
        self.display_on = False
        self.address_pointer = 0
        self.auto_increment = True
        self.keys = keys or KeyMatrix()

        self._stb = 1
        self._clk = 1
        self._dio_out: int | None = None
        self._shift = 0
        self._bits = 0
        self._frame_bytes: list[int] = []
        self._mode = "idle"          # idle / command / data_write / key_read
        self._read_ptr = -1

    # ---------------- 引脚级接口 ----------------
    def stb(self, level: int) -> None:
        if level == 0 and self._stb == 1:          # 下降沿：帧开始
            self._shift = 0
            self._bits = 0
            self._frame_bytes = []
            self._mode = "command"
        elif level == 1 and self._stb == 0:        # 上升沿：帧结束（执行挂起的写）
            if self._mode == "data_write":
                self._flush_writes()
            self._mode = "idle"
        self._stb = level

    def clk(self, level: int) -> None:
        if self._stb != 0:
            self._clk = level
            return
        if level == 1 and self._clk == 0:          # 上升沿：锁存 DIO（命令/写数据）
            if self._mode in ("command", "data_write") and self._dio_out is not None:
                self._shift = (self._shift >> 1) | ((self._dio_out & 1) << 7)
                self._bits += 1
                if self._bits == 8:
                    self._on_byte(self._shift & 0xFF)
                    self._shift = 0
                    self._bits = 0
        elif level == 0 and self._clk == 1:        # 下降沿：读键模式下推出下一位
            if self._mode == "key_read":
                self._read_ptr += 1
        self._clk = level

    def dio(self, level: int) -> None:
        self._dio_out = level

    def get_dio(self) -> int | None:
        """读键模式下芯片驱动键数据位，其余 Hi-Z（None）。

        位序：LSB-first（w_i = byte bit i）——课程驱动器 `temp>>=1; temp|=0x80`
        的移位方向决定第一个采样位落在 temp bit0，故 LSB-first 上线才能让
        课程时序重构出 key_scan_bytes() 的原始值（与 TM1638 手册键数据 LSB 先行一致）。
        """
        if self._mode == "key_read" and self._stb == 0 and 0 <= self._read_ptr < 32:
            byte = self.keys.key_scan_bytes()[self._read_ptr // 8 % 4]
            return (byte >> (self._read_ptr % 8)) & 1
        return None

    # ---------------- 命令处理 ----------------
    def _on_byte(self, byte: int) -> None:
        if self._mode == "command":
            if byte & 0xC0 == 0x40:                # 数据命令
                if byte & 0x02:                    # 0x42：读键扫数据 [TM1638 DS]
                    self._mode = "key_read"
                    self._read_ptr = -1            # 首个下降沿推出 bit0
                else:
                    self.auto_increment = not bool(byte & 0x04)   # 0x04=固定地址
                    self._mode = "data_write"
            elif byte & 0xC0 == 0xC0:              # 地址命令
                self.address_pointer = byte & 0x0F
                self._mode = "data_write"
            elif byte & 0xC0 == 0x80:              # 显示控制
                self.display_on = bool(byte & 0x08)
                self.brightness = byte & 0x07
                self._mode = "idle"
            else:
                self._mode = "idle"
        elif self._mode == "data_write":
            self._frame_bytes.append(byte)

    def _flush_writes(self) -> None:
        addr = self.address_pointer
        for b in self._frame_bytes:
            if 0 <= addr < 16:
                self.display_ram[addr] = b
            addr = addr + 1 if self.auto_increment else addr

    # ---------------- 视图 ----------------
    def render(self) -> str:
        """板上从左到右的数码位 = GRID1..8 = display_ram[0,2,4..14]。"""
        out = []
        for i in range(8):
            seg = self.display_ram[i * 2]
            ch = _SEG_TO_CHAR.get(seg & 0x7F, "?")
            if seg & 0x80:
                ch += "."
            out.append(ch)
        return " ".join(out)

    def leds(self) -> list[int]:
        return [self.display_ram[i * 2 + 1] & 1 for i in range(8)]


class DirectPinBus:
    """把 TM1638Driver 的引脚操作直接接到虚拟芯片（纯模型闭环）。"""

    def __init__(self, chip: TM1638):
        self.chip = chip

    def write(self, stb: int, clk: int, dio: int | None) -> None:
        self.chip.stb(stb)
        self.chip.clk(clk)
        if dio is not None:
            self.chip.dio(dio)

    def read_dio(self) -> int:
        return self.chip.get_dio() or 0


class TM1638Driver:
    """逐行复刻课程 tm1638.c 的时序（对任何满足 PinBus 接口的总线可用）。

    PinBus 接口：write(stb, clk, dio)（dio=None 表示释放/输入）、read_dio()。
    """

    def __init__(self, bus):
        self.bus = bus
        self._stb = 1

    def _stb_low(self) -> None:
        self._stb = 0
        self.bus.write(0, 1, None)

    def _stb_high(self) -> None:
        self._stb = 1
        self.bus.write(1, 1, None)

    # 课程 TM1638_Serial_Input：LSB 先行，CLK 上升沿锁存
    def _serial_input(self, data: int) -> None:
        for _ in range(8):
            self.bus.write(self._stb, 0, data & 1)
            data >>= 1
            self.bus.write(self._stb, 1, None)

    # 课程 TM1638_Serial_Output：temp.bit(7-i) = 第 i 个上线位
    def _serial_output(self) -> int:
        temp = 0
        for _ in range(8):
            temp >>= 1
            self.bus.write(self._stb, 0, None)     # 下降沿：芯片推出下一位
            self.bus.write(self._stb, 1, None)     # 上升沿
            if self.bus.read_dio():                # 采样点（与课程一致）
                temp |= 0x80
            self.bus.write(self._stb, 0, None)
        return temp

    def read_keyboard(self) -> tuple[tuple[int, int, int, int], int]:
        """返回 (c[0..3], 课程键号)，复刻 TM1638_Readkeyboard。"""
        self._stb_low()
        self._serial_input(0x42)
        c = [self._serial_output() for _ in range(4)]
        self._stb_high()
        keys = decode_course_keys(c[0], c[1])
        return (c[0], c[1], c[2], c[3]), (keys[0] if keys else 0)

    def init(self, brightness: int = 2) -> None:
        """课程 TM1638_Init（0x8A = 开显示 + 档位 2），brightness: 0..7。"""
        self._stb_low()
        self._serial_input(0x88 | (brightness & 0x07))
        self._stb_high()

    def refresh(self, digit: list[int], pnt: int = 0, led: list[int] | None = None) -> None:
        """复刻 TM1638_RefreshDIGIandLED：digit 元素为字符或段码，pnt 小数点位掩码。"""
        led = led or [0] * 8
        buf: list[int] = []
        for i in range(8):
            d = digit[i]
            seg = SEGMENT_CODE.get(str(d), d) if isinstance(d, (str, int)) else 0
            if (pnt >> i) & 1:
                seg |= 0x80
            buf.append(seg & 0xFF)
            buf.append(led[i] & 1)
        self._stb_low()
        self._serial_input(0x40)
        self._stb_high()
        self._stb_low()
        self._serial_input(0xC0)
        for b in buf:
            self._serial_input(b)
        self._stb_high()
