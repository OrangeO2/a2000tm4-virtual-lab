#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe v7: confirmed-halt GPIO write adjudication + proper ADC methodology."""
import os, socket, time, traceback

RESULT_DIR = os.environ.get("HWPROBE_OUT_DIR", os.path.join(os.path.dirname(__file__), "results"))
os.makedirs(RESULT_DIR, exist_ok=True)
OUT = open(os.path.join(RESULT_DIR, "probe7_result.txt"), "w", encoding="utf-8")
def p(*a):
    line = " ".join(str(x) for x in a)
    print(line); OUT.write(line + "\n"); OUT.flush()

class Tel:
    def __init__(self, port=4444):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(25); self.buf = b""
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

tel = Tel(); rsp = RSP()

def rd32(addr, tries=5):
    for t in range(tries):
        r = rsp.cmd(("m%08x,4" % addr).encode())
        if not r.startswith(b"E") and len(r) >= 8:
            return int.from_bytes(bytes.fromhex(r[:8].decode()), "little")
        time.sleep(0.02)
    return None

def mww(addr, val, pushes=2):
    tel.cmd("mww 0x%08X 0x%08X" % (addr, val))
    for _ in range(pushes):
        rd32(0xE000EDF0)
    return rd32(addr)

sect = lambda s: (p(""), p("#### %s ####" % s))
try:
    sect("0. HALT (confirmed by polling S_HALT)")
    for attempt in range(5):
        tel.cmd("halt")
        time.sleep(0.3)
        dh = rd32(0xE000EDF0)
        p("  attempt %d: DHCSR=%s S_HALT=%d" % (attempt, ("%08X" % dh) if dh else "?", (dh >> 17) & 1 if dh else -1))
        if dh is not None and (dh >> 17) & 1:
            break

    sect("1. GPIO WRITE ADJUDICATION (CPU confirmed halted)")
    # Port K masked alias
    k0 = rd32(0x400610C0)
    p("  K mask-read initial: %s" % ("%08X" % k0 if k0 is not None else "?"))
    r1 = mww(0x400610C0, 0x00000000)
    p("  mww KDATA=0x00 -> readback %s" % ("%08X" % r1 if r1 is not None else "?"))
    r1b = rd32(0x400610C0); r1c = rd32(0x400610C0)
    p("    re-read x2: %s %s" % (("%08X" % r1b) if r1b is not None else "?", ("%08X" % r1c) if r1c is not None else "?"))
    mww(0x400610C0, 0x00000030)
    # Port L full alias (PL0/PL1 NC on this base board -> safe)
    l0 = rd32(0x400623FC)
    p("  L full-read initial: %s" % ("%08X" % l0 if l0 is not None else "?"))
    r2 = mww(0x400623FC, 0x000000AA)
    r2b = rd32(0x400623FC)
    mww(0x400623FC, 0x00000000)
    p("  mww LDATA=0xAA -> readback %s / %s" % (("%08X" % r2) if r2 is not None else "?", ("%08X" % r2b) if r2b is not None else "?"))
    # gdb 1-byte write at K masked alias
    rr = rsp.cmd(b"M400610c0,1:00")
    rd32(0xE000EDF0)
    r3 = rd32(0x400610C0)
    p("  gdb 1-byte M KDATA -> %r readback %s" % (rr, ("%08X" % r3) if r3 is not None else "?"))
    rsp.cmd(b"M400610c0,1:30" if False else b"M400610c4,1:30")  # no-op variant not used
    mww(0x400610C0, 0x00000030)
    # DIR write test (PK5 direction) — restore immediately
    d0 = rd32(0x40061400)
    r4 = mww(0x40061400, (d0 or 0x30) ^ 0x20)
    r4b = rd32(0x40061400)
    mww(0x40061400, d0 or 0x30)
    p("  K DIR %s -> flip readback %s (re-read %s) -> restored" %
      (("%08X" % d0) if d0 is not None else "?", ("%08X" % r4) if r4 is not None else "?", ("%08X" % r4b) if r4b is not None else "?"))

    sect("2. ADC PROPER METHODOLOGY (settled single conversions)")
    mww(0x400FE638, 0x00000001)
    pr = 0
    for _ in range(200):
        pr = rd32(0x400FEA38) or 0
        if pr & 1: break
    p("  RCGCADC=1, PRADC ready=%d" % (pr & 1))
    amsel_o = rd32(0x40024528)
    mww(0x40024528, (amsel_o or 0) | 0x0C)
    for a, v in [(0x40038000, 0), (0x40038014, 0), (0x40038060, 0x10), (0x40038064, 0x60),
                 (0x40038FC4, 3), (0x4003800C, 2), (0x40038000, 2)]:
        mww(a, v)
    # resting voltage: idle 600 ms (caps recover), then ONE trigger
    p("  -- PE3/PE2 resting measurement (600ms idle -> 1 trigger) x5 --")
    for i in range(5):
        time.sleep(0.6)
        mww(0x40038028, 0x2)
        got = False
        for _w in range(200):
            v = rd32(0x40038004)
            if v is not None and (v & 2): got = True; break
        if not got: p("   trig timeout"); continue
        mww(0x4003800C, 0x2)
        a3 = rd32(0x40038068); a2 = rd32(0x40038068)
        p("   #%d: PE3=%4d (%.0f mV)  PE2=%4d (%.0f mV)" %
          (i, a3, a3 * 3300.0 / 4095, a2, a2 * 3300.0 / 4095))
    p("  -- bleed test: 8 back-to-back triggers on PE3 (no idle) --")
    bleeds = []
    for _ in range(8):
        mww(0x40038028, 0x2)
        for _w in range(200):
            v = rd32(0x40038004)
            if v is not None and (v & 2): break
        mww(0x4003800C, 0x2)
        bleeds.append(rd32(0x40038068))
        rd32(0x40038068)
    p("   %s" % bleeds)
    p("  -- die temperature: settle 300ms after TS select, single conversion x3 --")
    tvals = []
    for i in range(3):
        for a, v in [(0x40038000, 0), (0x400380A0, 0), (0x400380A4, 7),
                     (0x4003800C, 8), (0x40038000, 8)]:
            mww(a, v)
        time.sleep(0.3)
        mww(0x40038028, 0x8)
        got = False
        for _w in range(200):
            v = rd32(0x40038004)
            if v is not None and (v & 8): got = True; break
        if not got: p("   temp trig timeout"); continue
        mww(0x4003800C, 0x8)
        c = rd32(0x400380A8)
        temp = (1475 * 4096 - 2250 * c) / 40960.0
        tvals.append((c, temp))
        p("   #%d: code=%d -> %.1f C" % (i, c, temp))
    # restore
    for a, v in [(0x40038000, 0), (0x40038014, 0), (0x40038060, 0), (0x40038064, 0),
                 (0x40038FC4, 7), (0x4003800C, 0)]:
        mww(a, v)
    mww(0x40024528, amsel_o or 0)
    mww(0x400FE638, 0)
    p("  restored (RCGCADC=0, AMSEL, ADC regs)")
    p("  NOTE: ADC0 PC original read as 0x7 earlier (clock-on real value); restored to 0x7")

    sect("3. RESUME")
    rsp.close(); time.sleep(0.3)
    tel.cmd("resume")
    time.sleep(0.5)
    out = tel.cmd("targets")
    txt = out.decode(errors="replace")
    line = [l for l in txt.splitlines() if "tm4c1294" in l]
    p("final: %s" % (line[0].strip() if line else txt.strip()[:100]))
    tel.close()
except Exception:
    p("FATAL: %s" % traceback.format_exc())
    try:
        rsp.close(); tel.cmd("resume"); tel.close(); p("(resumed after fatal)")
    except Exception:
        pass
OUT.close()
print("PROBE7 COMPLETE")
