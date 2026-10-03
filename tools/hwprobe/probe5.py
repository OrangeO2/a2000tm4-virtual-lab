#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe v5: telnet mww for writes (posted-write aware), gdb for reads.
TM1638 real bus drive + ADC live + EEPROM. Always resumes target."""
import socket, time, traceback

OUT = open(r"C:\Users\42400\tools\tm4c_probe\probe5_result.txt", "w", encoding="utf-8")
def p(*a):
    line = " ".join(str(x) for x in a)
    print(line); OUT.write(line + "\n"); OUT.flush()

class Tel:
    def __init__(self, port=4444):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(20); self.buf = b""
        self.read_until("> ")
    def _recv(self):
        d = self.s.recv(65536)
        if not d: raise IOError("telnet closed")
        self.buf += d
    def read_until(self, pat, timeout=30):
        if isinstance(pat, str): pat = pat.encode()
        t0 = time.time()
        while pat not in self.buf:
            if time.time() - t0 > timeout: raise TimeoutError("want %r tail=%r" % (pat, self.buf[-120:]))
            self._recv()
        i = self.buf.index(pat) + len(pat)
        out, self.buf = self.buf[:i], self.buf[i:]
        return out
    def cmd(self, c, marker="> "):
        self.s.sendall((c + "\r\n").encode())
        return self.read_until(marker)
    def close(self):
        try: self.s.close()
        except Exception: pass

class RSP:
    def __init__(self, port=3333):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(25); self.buf = b""
        self.cmd(b"?")
    def _recv(self):
        d = self.s.recv(65536)
        if not d: raise IOError("gdb closed")
        self.buf += d
    def _send(self, data):
        cs = sum(data) & 0xFF
        self.s.sendall(b"$" + data + b"#" + format(cs, "02x").encode())
        t0 = time.time()
        while True:
            if time.time() - t0 > 25: raise TimeoutError("no ack")
            if not self.buf: self._recv()
            c, self.buf = self.buf[:1], self.buf[1:]
            if c == b"+": return
            if c == b"-": raise IOError("NACK")
    def _read(self):
        while True:
            while b"$" not in self.buf: self._recv()
            i = self.buf.index(b"$"); self.buf = self.buf[i:]
            j = self.buf.find(b"#")
            while j == -1: self._recv(); j = self.buf.find(b"#")
            payload = self.buf[1:j]
            while len(self.buf) < j + 3: self._recv()
            self.buf = self.buf[j + 3:]
            self.s.sendall(b"+")
            return payload
    def cmd(self, data):
        self._send(data); return self._read()
    def close(self):
        try: self.s.close()
        except Exception: pass

tel = Tel()
rsp = RSP()

def rd32(addr, tries=5):
    for t in range(tries):
        r = rsp.cmd(("m%08x,4" % addr).encode())
        if not r.startswith(b"E") and len(r) >= 8:
            return int.from_bytes(bytes.fromhex(r[:8].decode()), "little")
        time.sleep(0.02)
    return None

def rdwords(addr, nbytes, tries=5):
    """read nbytes, retry until two consecutive reads agree (or nonzero-stable)"""
    last = None
    for t in range(tries + 3):
        r = rsp.cmd(("m%08x,%x" % (addr, nbytes)).encode())
        if r.startswith(b"E") or len(r) < nbytes * 2:
            time.sleep(0.02); continue
        b = bytes.fromhex(r[:nbytes * 2].decode())
        if last is not None and b == last:
            return b
        if any(x != 0 for x in b) and last is None:
            last = b; continue
        if last is not None and b != last:
            last = b; continue
        last = b
    return last

def wr32(addr, val):
    """telnet mww word write + one push read + verify read"""
    tel.cmd("mww 0x%08X 0x%08X" % (addr, val))
    rd32(0x400FE000)               # push (flush posted write)
    return rd32(addr)

KDATA, KCLK = 0x400610C0, 0x40063004   # masked DATA addrs: K bits4/5, M bit0
DIRK = 0x40061000 + 0x400

def stb(v):  wr32(KDATA, (0x10 if v else 0x00) | 0x20)
def clk(v):  wr32(KCLK, 0x01 if v else 0x00)
def dio(v):  wr32(KDATA, 0x10 | (0x20 if v else 0x00))
def rd_dio(): return (rd32(0x40061080) >> 5) & 1
def send_byte(b):
    for i in range(8):
        clk(0); dio((b >> i) & 1); clk(1)

try:
    sect = lambda s: (p(""), p("#### %s ####" % s))

    # ---------- 0. state + halt ----------
    sect("0. STATE & HALT")
    out = tel.cmd("targets")
    p("state: %s" % ("RUNNING" if "running" in out.decode(errors="replace") else out.decode(errors='replace')[:80]))
    tel.cmd("halt")
    dh = rd32(0xE000EDF0)
    p("DHCSR=0x%08X S_HALT=%d" % (dh, (dh >> 17) & 1))

    # ---------- 1. write-path canary ----------
    sect("1. WRITE CANARY (telnet mww -> push -> verify)")
    cur = rd32(KDATA)
    wr32(KDATA, cur ^ 0x10)
    rb = rd32(KDATA)
    wr32(KDATA, cur)
    rb2 = rd32(KDATA)
    p("cur=%08X -> flipped readback=%08X -> restored=%08X : writes %s" %
      (cur, rb, rb2, "WORK" if (rb & 0x30) == ((cur ^ 0x10) & 0x30) else "STILL BROKEN"))

    if (rb & 0x30) == ((cur ^ 0x10) & 0x30):
        # ---------- 2. TM1638 ----------
        sect("2. TM1638 REAL BUS DRIVE")
        stb(1)
        stb(0); send_byte(0x40); stb(1)
        stb(0); send_byte(0xC0)
        for _ in range(8):
            send_byte(0xFF); send_byte(0x01)
        stb(1)
        stb(0); send_byte(0x8F); stb(1)
        p("  display RAM = all segments + all 8 LEDs, brightness max (0x8F)")
        dirk = rd32(DIRK)
        p("  PK DIR=%08X" % dirk)
        reads = []
        for trial in range(3):
            stb(1); stb(0)
            send_byte(0x42)                    # DIO = OUTPUT during command (fixed)
            wr32(DIRK, (dirk or 0x30) & ~0x20) # DIO -> input
            cb = []
            for _b in range(4):
                t = 0
                for _bit in range(8):
                    t >>= 1; clk(0)
                    if rd_dio(): t |= 0x80
                    clk(1)
                cb.append(t)
            wr32(DIRK, dirk or 0x30)           # DIO -> output
            stb(1)
            reads.append(cb)
        for c in reads:
            if all(x == 0 for x in c):
                p("  key read (%02X %02X %02X %02X): TM1638 DRIVING 0x00 -> ALIVE, no key" % tuple(c))
            elif all(x == 0xFF for x in c):
                p("  key read (%02X %02X %02X %02X): all-FF -> no TM1638 response" % tuple(c))
            else:
                keys = [k for m, k in {0x04: 1, 0x02: 2, 0x01: 3, 0x40: 4, 0x20: 5, 0x10: 6}.items() if c[0] & m]
                keys += [k for m, k in {0x04: 7, 0x02: 8, 0x01: 9}.items() if c[1] & m]
                p("  key read (%02X %02X %02X %02X): keys=%s" % (tuple(c) + (keys,)))
        wr32(DIRK, dirk or 0x30); wr32(KDATA, 0x30); wr32(KCLK, 0)
        p("  PK/PM restored")

        # ---------- 3. ADC live ----------
        sect("3. ADC0 LIVE (PE3/PE2 + die temperature)")
        rcadc = wr32(0x400FE638, 0x00000001)
        p("  RCGCADC now = %s" % ("0x%08X" % rcadc if rcadc is not None else "unreadable"))
        pr = None
        for _ in range(200):
            pr = rd32(0x400FEA38)
            if pr is not None and (pr & 1): break
        p("  PRADC=%s (bit0 ready=%d)" % (("%08X" % pr) if pr is not None else "?", (pr or 0) & 1))
        adc_o = {}
        for a in (0x40038000, 0x40038004, 0x4003800C, 0x40038014, 0x40038060, 0x40038064, 0x40038FC4):
            adc_o[a] = rd32(a)
        p("  ADC0 before: " + " ".join("%X=%s" % (k & 0xFFF, ("%08X" % v) if v is not None else "??") for k, v in adc_o.items()))
        amsel_o = rd32(0x40024528)
        wr32(0x40024528, (amsel_o or 0) | 0x0C)
        for a, v in [(0x40038000, 0x00000000), (0x40038014, 0x00000000),
                     (0x40038060, 0x00000010), (0x40038064, 0x00000060),
                     (0x40038FC4, 0x00000003), (0x4003800C, 0x00000002),
                     (0x40038000, 0x00000002)]:
            wr32(a, v)
        pe3, pe2, ok = [], [], True
        for _ in range(8):
            wr32(0x40038028, 0x02)
            got = False
            for _w in range(200):
                v = rd32(0x40038004)
                if v is not None and (v & 0x02): got = True; break
            if not got: ok = False; p("  !! seq1 RIS timeout"); break
            wr32(0x4003800C, 0x02)
            pe3.append(rd32(0x40038068)); pe2.append(rd32(0x40038068))
        if ok and pe3:
            p("  PE3(AIN0) codes: %s" % pe3)
            p("  PE2(AIN1) codes: %s" % pe2)
            p("  PE3 = %.1f mV ; PE2 = %.1f mV (avg of %d)" %
              (sum(x * 3300.0 / 4095 for x in pe3) / len(pe3),
               sum(x * 3300.0 / 4095 for x in pe2) / len(pe2), len(pe3)))
        for a, v in [(0x40038000, 0x00000000), (0x400380A0, 0x00000000),
                     (0x400380A4, 0x00000007), (0x4003800C, 0x00000008),
                     (0x40038000, 0x00000008)]:
            wr32(a, v)
        tc = []
        for _ in range(8):
            wr32(0x40038028, 0x08)
            got = False
            for _w in range(200):
                v = rd32(0x40038004)
                if v is not None and (v & 0x08): got = True; break
            if not got: p("  !! temp RIS timeout"); break
            wr32(0x4003800C, 0x08)
            tc.append(rd32(0x400380A8))
        if tc:
            temps = [(1475 * 4096 - 2250 * c) / 40960.0 for c in tc]
            p("  die-temp codes: %s -> %.1f C" % (tc, sum(temps) / len(temps)))
        for a, v in adc_o.items():
            if v is not None: wr32(a, v)
        wr32(0x40024528, amsel_o or 0)
        wr32(0x400FE638, 0x00000000)
        p("  ADC0/AMSEL/RCGCADC restored")
    else:
        p("  (skipping TM1638/ADC — write path still broken)")

    # ---------- 4. EEPROM ----------
    sect("4. EEPROM")
    try:
        rce = wr32(0x400FE658, 0x00000001)
        p("  RCGCEEPROM=%s" % ("0x%08X" % rce if rce is not None else "?"))
        done = None
        for _ in range(200):
            done = rd32(0x400AF018)
            if done is not None and (done & 1) == 0: break
        p("  EEDONE=%s" % (("%08X" % done) if done is not None else "?"))
        eesize = rd32(0x400AF000)
        if eesize:
            p("  EESIZE=0x%08X -> %d words (%d bytes), %d blocks" %
              (eesize, eesize & 0xFFFF, (eesize & 0xFFFF) * 4, (eesize >> 16) & 0x7FF))
            wr32(0x400AF004, 0); wr32(0x400AF008, 0)
            ee = []
            for _ in range(16):
                v = rd32(0x400AF014)
                if v is None: break
                ee.append(v)
            p("  EEPROM block0: " + (" ".join("%08X" % x for x in ee) if ee else "(unreadable)"))
            wr32(0x400AF004, 0); wr32(0x400AF008, 0)
    except Exception:
        p("EEPROM failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])
    wr32(0x400FE658, 0x00000000)

    # ---------- 5. resume ----------
    sect("5. RESUME")
    rsp.close(); time.sleep(0.3)
    tel.cmd("resume")
    out = tel.cmd("targets")
    txt = out.decode(errors="replace")
    p("final state: %s" % ("RUNNING ✓" if "running" in txt else txt.strip()[:150]))
    tel.close()
except Exception:
    p("FATAL: %s" % traceback.format_exc())
    try:
        rsp.close()
    except Exception:
        pass
    try:
        tel.cmd("resume")
        tel.close()
        p("(target resumed after fatal)")
    except Exception:
        pass
OUT.close()
print("PROBE5 COMPLETE")
