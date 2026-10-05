#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调理链（PE2/PE3）状态测量探针——标定工作流的标准测量工具。

用途（docs/2 M-5 / M-5c）：
1. 无功率板：测悬空引脚静息基线（FloatingPinModel 标定）
2. 功率板连接未上电：测连接-未激活平衡点
3. 功率板上电：测调理输出（电压/电流通道），配合万用表 VOUT+ 读数
   与负载阻值标定 vdiv_ratio / i_gain（回填 BuckPlant 构造参数）

协议：halt → 自配 ADC0 序列1（CH0=PE3/AIN0，CH1=PE2/AIN1）→
      静置协议（600ms 空闲 → 单次转换）× N → 连续采样（可选）→ 恢复 → resume

前置：OpenOCD 已启动（gdb 3333 + telnet 4444）：
    openocd -f board/ti_ek-tm4c1294xl.cfg -c "gdb_port 3333" -c "telnet_port 4444"

用法：python probe_conditioning.py [静置次数，默认 6]
"""

import socket
import statistics
import sys
import time


class Tel:
    def __init__(self, port=4444):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(20)
        self.buf = b""
        self.ru("> ")

    def _recv(self):
        d = self.s.recv(65536)
        if not d:
            raise IOError("closed")
        self.buf += d

    def ru(self, pat, timeout=30):
        if isinstance(pat, str):
            pat = pat.encode()
        t0 = time.time()
        while pat not in self.buf:
            if time.time() - t0 > timeout:
                raise TimeoutError(pat)
            self._recv()
        i = self.buf.index(pat) + len(pat)
        out, self.buf = self.buf[:i], self.buf[i:]
        return out

    def cmd(self, c, marker="> "):
        self.s.sendall((c + "\r\n").encode())
        return self.ru(marker)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


class RSP:
    def __init__(self, port=3333):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(25)
        self.buf = b""
        self.cmd(b"?")

    def _recv(self):
        d = self.s.recv(65536)
        if not d:
            raise IOError("closed")
        self.buf += d

    def _send(self, data):
        cs = sum(data) & 0xFF
        self.s.sendall(b"$" + data + b"#" + format(cs, "02x").encode())
        t0 = time.time()
        while True:
            if time.time() - t0 > 25:
                raise TimeoutError("ack")
            if not self.buf:
                self._recv()
            c, self.buf = self.buf[:1], self.buf[1:]
            if c == b"+":
                return
            if c == b"-":
                raise IOError("NACK")

    def _read(self):
        while True:
            while b"$" not in self.buf:
                self._recv()
            i = self.buf.index(b"$")
            self.buf = self.buf[i:]
            j = self.buf.find(b"#")
            while j == -1:
                self._recv()
                j = self.buf.find(b"#")
            pl = self.buf[1:j]
            while len(self.buf) < j + 3:
                self._recv()
            self.buf = self.buf[j + 3:]
            self.s.sendall(b"+")
            return pl

    def cmd(self, data):
        self._send(data)
        return self._read()

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


tel = Tel()
rsp = RSP()


def rd32(a, tries=4):
    for t in range(tries):
        r = rsp.cmd(("m%08x,4" % a).encode())
        if not r.startswith(b"E") and len(r) >= 8:
            return int.from_bytes(bytes.fromhex(r[:8].decode()), "little")
        time.sleep(0.02)
    return None


def mww(a, v, pushes=2):
    tel.cmd("mww 0x%08X 0x%08X" % (a, v))
    for _ in range(pushes):
        rd32(0xE000EDF0)
    return rd32(a)


def main():
    n_rest = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    tel.cmd("halt")
    dh = rd32(0xE000EDF0)
    print("S_HALT=%d" % ((dh >> 17) & 1))

    # ADC0 时钟（若固件未开则补开，结束后恢复）
    rc = rd32(0x400FE638)
    if rc is not None and (rc & 1) == 0:
        mww(0x400FE638, rc | 0x01)
    pr = 0
    for _ in range(300):
        v = rd32(0x400FEA38)
        if v is not None and (v & 1):
            pr = 1
            break
    print("PRADC ready=%d" % pr)
    am = rd32(0x40024528)
    adc_saved = {a: rd32(a) for a in
                 (0x40038000, 0x40038014, 0x40038060, 0x40038064, 0x40038FC4)}
    mww(0x40024528, (am or 0) | 0x0C)          # PE2/PE3 模拟模式
    for a, v in [(0x40038000, 0), (0x40038014, 0), (0x40038060, 0x10),
                 (0x40038064, 0x60), (0x40038FC4, 3), (0x4003800C, 2),
                 (0x40038000, 2)]:
        mww(a, v)

    # 静置协议：idle → 单次转换（CH0=PE3 先出，CH1=PE2 后出）
    print("-- PE3(AIN0)/PE2(AIN1) 静置测量（600ms 间隔）x%d --" % n_rest)
    res = []
    for i in range(n_rest):
        time.sleep(0.6)
        mww(0x40038028, 0x2)
        got = False
        for _w in range(300):
            v = rd32(0x40038004)
            if v is not None and (v & 2):
                got = True
                break
        if not got:
            print("  trig timeout")
            continue
        mww(0x4003800C, 0x2)
        a3 = rd32(0x40038068)
        a2 = rd32(0x40038068)
        res.append((a3, a2))
        print("  #%d: PE3=%4d (%7.1f mV)   PE2=%4d (%7.1f mV)"
              % (i, a3, a3 * 3300 / 4095, a2, a2 * 3300 / 4095))

    if len(res) >= 3:
        e3 = statistics.mean(x[0] for x in res)
        e2 = statistics.mean(x[1] for x in res)
        s3 = statistics.pstdev(x[0] for x in res)
        s2 = statistics.pstdev(x[1] for x in res)
        print("  PE3 均值 %.0f 码 (σ=%.1f) = %.1f mV" % (e3, s3, e3 * 3300 / 4095))
        print("  PE2 均值 %.0f 码 (σ=%.1f) = %.1f mV" % (e2, s2, e2 * 3300 / 4095))
        print("  稳定性: PE3 %s / PE2 %s（σ<3 → 被驱动；σ>8 → 浮空/衰减）"
              % ("被驱动(稳)" if s3 < 3 else "浮空/衰减",
                 "被驱动(稳)" if s2 < 3 else "浮空/衰减"))
        print("  理论链反推（CH1/PE2=电压0.5分压；CH0/PE3=电流1V/A）: Vout=%.0f mV, I=%.3f A"
              % (e2 * 3300 / 4095 * 2, e3 * 3300 / 4095 / 1000))
        print("  标定提示：配合万用表 VOUT+ 读数 V 与负载 R，"
              "vdiv_ratio = PE2_mV/V，i_gain = PE3_mV/(V/R)")

    # 恢复捕获到的 ADC/GPIO 配置并 resume。ISC/RIS 属 W1C/运行态状态，无法无损复原。
    mww(0x40038000, 0)
    for a in (0x40038014, 0x40038060, 0x40038064, 0x40038FC4):
        if adc_saved.get(a) is not None:
            mww(a, adc_saved[a])
    if adc_saved.get(0x40038000) is not None:
        mww(0x40038000, adc_saved[0x40038000])
    mww(0x40024528, am or 0)
    if rc is not None:
        mww(0x400FE638, rc)
    tel.cmd("resume")
    time.sleep(0.3)
    out = tel.cmd("targets")
    print("target:", [l.strip() for l in out.decode(errors="replace").splitlines()
                      if "tm4c" in l])
    rsp.close()
    tel.close()
    print("DONE - resumed")


if __name__ == "__main__":
    sys.exit(main())
