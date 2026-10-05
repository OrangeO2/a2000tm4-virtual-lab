#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 renode/a2000tm4.repl 的内嵌外设脚本块（v0.4 状态字典版）并写回。

用法：python tools/gen_bench_script.py
（修改下方 SCRIPT 内容后重新运行即可更新 .repl）
"""

import io

REPL = "renode/a2000tm4.repl"

SCRIPT = r'''
# ---- A2000TM4 虚拟实验台外设 v0.4（IronPython，状态字典版） ----
# 说明：Renode 的 Python 外设脚本体按函数局部作用域执行——普通赋值是"局部变量"，
# 与函数内 `global` 声明的模块全局脱节。因此所有可变状态统一放在字典 S 中，
# 彻底规避作用域问题；S 在 request.IsInit 时重建。
# 常量每次访问重建（代价可忽略）。

GPIO_K_BASE = 0x40061000; GPIO_K_END = 0x40062000
GPIO_L_BASE = 0x40062000; GPIO_L_END = 0x40063000
GPIO_M_BASE = 0x40063000; GPIO_M_END = 0x40064000
ADC0_BASE = 0x40038000; ADC0_END = 0x40039000
BENCH_BASE = 0x50000000; BENCH_END = 0x50001000

SEGS = {
    "0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66,
    "5": 0x6D, "6": 0x7D, "7": 0x07, "8": 0x7F, "9": 0x6F,
    "A": 0x77, "b": 0x7C, "C": 0x39, "d": 0x5E, "E": 0x79, "F": 0x71,
}
KEY_TABLE = {
    1: (0, 0x04), 2: (0, 0x02), 3: (0, 0x01),
    4: (0, 0x40), 5: (0, 0x20), 6: (0, 0x10),
    7: (1, 0x04), 8: (1, 0x02), 9: (1, 0x01),
}
REV_DIGIT = {}
for _c in "0123456789":
    REV_DIGIT[SEGS[_c]] = int(_c)
for _i, _c in enumerate("AbCdEF"):
    REV_DIGIT[SEGS[_c]] = 10 + _i


def key_scan_bytes():
    c = [0, 0, 0, 0]
    if S["key"] in KEY_TABLE:
        idx, val = KEY_TABLE[S["key"]]
        c[idx] = val
    return c


def tm_dio_out():
    if S["tmmode"] == "key_read" and S["pstb"] == 0 and 0 <= S["rptr"] < 32:
        byte = key_scan_bytes()[(S["rptr"] // 8) % 4]
        S["kdbg"] = (S.get("kdbg", 0) + 1) if S["rptr"] % 8 == 0 and S["rptr"] < 8 else S.get("kdbg", 0)
        if S["rptr"] % 8 == 0:
            S["klast"] = byte
        return (byte >> (S["rptr"] % 8)) & 1
    return 1


def decode_seg(seg):
    if seg & 0x7F == 0:
        return 0xFF
    return REV_DIGIT.get(seg & 0x7F, 0xEE)


def tm_stb_edge(level):
    if level == 0:
        S["tmmode"] = "command"; S["shift"] = 0; S["nbits"] = 0
        S["frame"] = []; S["rptr"] = -1
    else:
        if S["tmmode"] == "data_write":
            addr = S["taddr"]
            for b in S["frame"]:
                if 0 <= addr < 16:
                    S["disp"][addr] = b
                if S["autoinc"]:
                    addr += 1
            S["taddr"] = addr
        S["tmmode"] = "idle"; S["rptr"] = -1


def tm_clk_edge(level):
    if S["pstb"] != 0:
        return
    if level == 1:
        if S["tmmode"] in ("command", "data_write"):
            bit = (S["klatch"] >> 5) & 1
            S["shift"] = (S["shift"] >> 1) | (bit << 7)
            S["nbits"] += 1
            if S["nbits"] == 8:
                byte = S["shift"] & 0xFF
                S["shift"] = 0; S["nbits"] = 0
                if S["tmmode"] == "command":
                    if byte & 0xC0 == 0x40:
                        if byte & 0x02:
                            S["tmmode"] = "key_read"; S["rptr"] = -1
                        else:
                            S["autoinc"] = not bool(byte & 0x04)
                            S["tmmode"] = "data_write"
                    elif byte & 0xC0 == 0xC0:
                        S["taddr"] = byte & 0x0F
                        S["tmmode"] = "data_write"
                    elif byte & 0xC0 == 0x80:
                        S["on"] = 1 if byte & 0x08 else 0
                        S["bright"] = byte & 0x07
                        S["tmmode"] = "idle"
                    else:
                        S["tmmode"] = "idle"
                elif S["tmmode"] == "data_write":
                    S["frame"].append(byte)
    else:
        if S["tmmode"] == "key_read":
            S["rptr"] += 1


def gpio_write(port, off, value):
    if off < 0x400:
        mask = (off >> 2) & 0xFF
        lk = "klatch" if port == "K" else "mlatch"
        new_latch = (S[lk] & (0xFF ^ mask)) | (value & mask)
        S[lk] = new_latch
        if port == "K":
            new_stb = (new_latch >> 4) & 1
            if new_stb != S["pstb"]:
                S["pstb"] = new_stb
                tm_stb_edge(new_stb)
        else:
            new_clk = new_latch & 1
            if new_clk != S["pclk"]:
                S["pclk"] = new_clk
                tm_clk_edge(new_clk)
    elif off == 0x400:
        S["kdir" if port == "K" else "mdir"] = value
    elif off == 0x51C:
        S["kden" if port == "K" else "mden"] = value
    else:
        S["gmisc"][(port, off)] = value


def gpio_read(port, off):
    if off < 0x400:
        mask = (off >> 2) & 0xFF
        out = 0
        for bit in range(8):
            m = 1 << bit
            if mask & m == 0:
                continue
            if port == "K" and bit == 5 and (S["kdir"] & m) == 0:
                if tm_dio_out():
                    out |= m
                continue
            latch = S["klatch"] if port == "K" else S["mlatch"]
            if latch & m:
                out |= m
        return out
    if off == 0x400:
        return S["kdir"] if port == "K" else S["mdir"]
    if off == 0x51C:
        return S["kden"] if port == "K" else S["mden"]
    return S["gmisc"].get((port, off), 0)


def i2c_feed(scl, sda, pscl, psda):
    if scl == 1 and pscl == 1:
        if sda == 0 and psda == 1:                    # START
            S["istarts"] = S.get("istarts", 0) + 1
            S["ifrm"] = 1; S["ibits"] = []; S["ibytes"] = []; S["iack"] = 0
        elif sda == 1 and psda == 0 and S["ifrm"]:     # STOP
            if len(S["ibytes"]) >= 3 and S["ibytes"][0] == 0x98:
                raw = (S["ibytes"][1] << 8) | S["ibytes"][2]
                S["dacc"] = (raw >> 2) & 0x3FF
                S["dfrms"] += 1
                S["lfr"] = [S["ibytes"][0], S["ibytes"][1], S["ibytes"][2]]
            S["ifrm"] = 0
    elif scl == 1 and pscl == 0 and S["ifrm"]:
        if S["iack"]:
            S["iack"] = 0                              # 第 9 脉冲 = ACK 槽
        else:
            S["ibits"].append(sda)
            if len(S["ibits"]) == 8:
                v = 0
                for b in S["ibits"]:
                    v = (v << 1) | b
                S["ibytes"].append(v)
                S["ibits"] = []
                S["iack"] = 1


def gpio_l_write(off, value):
    if off < 0x400:
        mask = (off >> 2) & 0xFF
        new_latch = (S["llatch"] & (0xFF ^ mask)) | (value & mask)
        S["llatch"] = new_latch
        scl = (new_latch >> 1) & 1                    # PL1=SCL（bit1）
        sda = new_latch & 1                           # PL0=SDA（bit0）
        if (S["ldir"] & 1) == 0:
            sda = 1                                   # SDA 释放 → 上拉
        if (S["ldir"] & 2) == 0:
            scl = 1
        if scl != S["pscl"] or sda != S["psda"]:
            i2c_feed(scl, sda, S["pscl"], S["psda"])
            S["pscl"] = scl
            S["psda"] = sda
    elif off == 0x400:
        S["ldir"] = value
    elif off == 0x51C:
        S["lden"] = value
    else:
        S["lmisc"][off] = value


def gpio_l_read(off):
    if off < 0x400:
        mask = (off >> 2) & 0xFF
        out = 0
        for bit in range(8):
            m = 1 << bit
            if mask & m == 0:
                continue
            if bit in (0, 1) and (S["ldir"] & m) == 0:
                out |= m                              # 输入态 → 上拉 1
            elif S["llatch"] & m:
                out |= m
        return out
    if off == 0x400:
        return S["ldir"]
    if off == 0x51C:
        return S["lden"]
    return S["lmisc"].get(off, 0)


def adc_trigger(seq):
    if seq != 1:
        return
    S["fifo"] = []
    for step in range(2):
        ch = (S["ssmux"] >> (4 * step)) & 0xF
        mv = S["chmv"][ch] if ch < 2 else 0
        code = int(round(mv * 4095.0 / 3300.0))
        if code > 4095:
            code = 4095
        S["fifo"].append(code)
        if ch < 2:
            S["alast"][ch] = code
    S["aris"] |= 0x2


def adc_write(off, value):
    if off == 0x00:
        S["actss"] = value & 0xF
    elif off == 0x0C:
        S["aris"] = S["aris"] & (0xF ^ (value & 0xF))
    elif off == 0x14:
        S["emux"] = value
    elif off == 0x28:
        for seq in range(4):
            if value & (1 << seq):
                adc_trigger(seq)
    elif off == 0x60:
        S["ssmux"] = value & 0xFFFF
    elif off == 0x64:
        S["ssctl"] = value & 0xFFFF
    elif off == 0xFC4:
        S["apc"] = value


def adc_read(off):
    if off == 0x00:
        return S["actss"]
    if off == 0x04:
        return S["aris"]
    if off == 0x0C:
        return S["aris"]
    if off == 0x68:
        if S["fifo"]:
            return S["fifo"].pop(0)
        return S["alast"][0]
    if off == 0x60:
        return S["ssmux"]
    if off == 0x64:
        return S["ssctl"]
    if off == 0xFC4:
        return S["apc"]
    return 0


def bench_write(off, value):
    if off == 0x00:
        key = value & 0xF
        S["key"] = key if 0 <= key <= 9 else 0
    elif off == 0x40:
        S["chmv"][0] = value & 0xFFFF
    elif off == 0x44:
        S["chmv"][1] = value & 0xFFFF


def bench_read(off):
    if off == 0x00 or off == 0x04:
        return S["key"]
    if 0x10 <= off < 0x18:
        return decode_seg(S["disp"][(off - 0x10) * 2])
    if 0x20 <= off < 0x28:
        return S["disp"][(off - 0x20) * 2]
    if 0x30 <= off < 0x38:
        return S["disp"][(off - 0x30) * 2 + 1]
    if off == 0x40:
        return S["chmv"][0]
    if off == 0x44:
        return S["chmv"][1]
    if off == 0x48:
        return S["alast"][0]
    if off == 0x4C:
        return S["alast"][1]
    if off == 0x50:
        return S["dacc"]
    if off == 0x54:
        return int(3300.0 * S["dacc"] / 1024)
    if off == 0x58:
        return S["dfrms"]
    if 0x5C <= off < 0x5F:
        return S["lfr"][off - 0x5C]
    if off == 0x60:
        return S.get("istarts", 0)
    if off == 0x61:
        return S.get("kdbg", 0)
    if off == 0x62:
        return S.get("klast", 0)
    return 0


def dispatch_write(request):
    a = request.Absolute
    v = request.Value & 0xFFFFFFFF
    if GPIO_K_BASE <= a < GPIO_K_END:
        gpio_write("K", a - GPIO_K_BASE, v)
    elif GPIO_L_BASE <= a < GPIO_L_END:
        gpio_l_write(a - GPIO_L_BASE, v)
    elif GPIO_M_BASE <= a < GPIO_M_END:
        gpio_write("M", a - GPIO_M_BASE, v)
    elif ADC0_BASE <= a < ADC0_END:
        adc_write(a - ADC0_BASE, v)
    elif BENCH_BASE <= a < BENCH_END:
        bench_write(a - BENCH_BASE, v)


def dispatch_read(request):
    a = request.Absolute
    v = 0
    if GPIO_K_BASE <= a < GPIO_K_END:
        v = gpio_read("K", a - GPIO_K_BASE)
    elif GPIO_L_BASE <= a < GPIO_L_END:
        v = gpio_l_read(a - GPIO_L_BASE)
    elif GPIO_M_BASE <= a < GPIO_M_END:
        v = gpio_read("M", a - GPIO_M_BASE)
    elif ADC0_BASE <= a < ADC0_END:
        v = adc_read(a - ADC0_BASE)
    elif BENCH_BASE <= a < BENCH_END:
        v = bench_read(a - BENCH_BASE)
    request.Value = v & 0xFFFFFFFF


if request.IsInit:
    S = {}
    S["tmmode"] = "idle"; S["shift"] = 0; S["nbits"] = 0; S["frame"] = []; S["taddr"] = 0
    S["autoinc"] = True; S["rptr"] = -1; S["disp"] = [0] * 16; S["bright"] = 0; S["on"] = 0
    S["key"] = 0
    S["kdir"] = 0; S["kden"] = 0; S["klatch"] = 0
    S["mdir"] = 0; S["mden"] = 0; S["mlatch"] = 0
    S["ldir"] = 0; S["lden"] = 0; S["llatch"] = 0
    S["pstb"] = 1; S["pclk"] = 1; S["pscl"] = 1; S["psda"] = 1
    S["gmisc"] = {}; S["lmisc"] = {}
    S["actss"] = 0; S["aris"] = 0; S["emux"] = 0; S["ssmux"] = 0; S["ssctl"] = 0; S["apc"] = 7
    S["fifo"] = []; S["chmv"] = [1150, 1058]; S["alast"] = [0, 0]  # [M-5] CH0=PE3/AIN0(电流链), CH1=PE2/AIN1(电压链)；此处为无功率板尾点
    S["dacc"] = 0; S["dfrms"] = 0; S["lfr"] = [0x98, 0x00, 0x00]
    S["istarts"] = 0; S["kdbg"] = 0; S["klast"] = 0
elif request.IsWrite:
    dispatch_write(request)
elif request.IsRead:
    dispatch_read(request)
'''

repl = io.open(REPL, encoding="utf-8").read()
start = repl.index("    script: '''")
end = repl.index("'''", start + 15) + 3
new_block = "    script: '''" + SCRIPT + "'''"
s = repl[:start] + new_block + repl[end:]
io.open(REPL, "w", encoding="utf-8", newline="").write(s)
print("REPL 已更新：%d 字符" % len(s))
