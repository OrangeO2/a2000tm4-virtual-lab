#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe v4: layered write-path diagnosis + stable readbacks. Target always resumed."""
import socket, time, traceback

OUT = open(r"C:\Users\42400\tools\tm4c_probe\probe4_result.txt", "w", encoding="utf-8")
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
    def read_until(self, pat, timeout=25):
        if isinstance(pat, str): pat = pat.encode()
        t0 = time.time()
        while pat not in self.buf:
            if time.time() - t0 > timeout: raise TimeoutError("want %r tail=%r" % (pat, self.buf[-150:]))
            self._recv()
        i = self.buf.index(pat) + len(pat)
        out, self.buf = self.buf[:i], self.buf[i:]
        return out
    def cmd(self, c, marker="> "):
        self.s.sendall((c + "\r\n").encode())
        return self.read_until(marker)

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

def words(b):
    return [int.from_bytes(b[i:i+4], "little") for i in range(0, len(b) - len(b) % 4, 4)]

tel = Tel()
rsp = RSP()

def g_rd32(addr, tries=4):
    r = b""
    for t in range(tries):
        r = rsp.cmd(("m%08x,4" % addr).encode())
        if not r.startswith(b"E") and len(r) >= 8:
            return int.from_bytes(bytes.fromhex(r[:8].decode()), "little")
        time.sleep(0.02)
    return None

def g_rdN(addr, nbytes, tries=4):
    r = b""
    for t in range(tries):
        r = rsp.cmd(("m%08x,%x" % (addr, nbytes)).encode())
        if not r.startswith(b"E") and len(r) >= nbytes * 2:
            return bytes.fromhex(r[:nbytes * 2].decode())
        time.sleep(0.02)
    return None

def g_wr32(addr, val):
    return rsp.cmd(("M%08x,4:%08x" % (addr, val)).encode())

tel.cmd("halt")

sect = lambda s: (p(""), p("#### %s ####" % s))

# ---- A. RAM write via TELNET mww -------------------------------------------
sect("A. TELNET mww/mdd RAM write test @0x20000040")
ram_ok_telnet = False
try:
    out = tel.cmd("mdw 0x20000040 2")
    p("before: %s" % out.decode(errors="replace").strip().replace("\r", " ")[:120])
    tel.cmd("mww 0x20000040 0xA5A55A5A")
    out = tel.cmd("mdw 0x20000040 1")
    p("after : %s" % out.decode(errors="replace").strip().replace("\r", " ")[:120])
    ram_ok_telnet = "a5a55a5a" in out.decode(errors="replace").lower()
    tel.cmd("mww 0x20000040 0xDEADBEEF")
    out = tel.cmd("mdw 0x20000040 1")
    p("second: %s" % out.decode(errors="replace").strip().replace("\r", " ")[:120])
    p("=> telnet mww RAM write: %s" % ("WORKS" if ram_ok_telnet else "NO EFFECT"))
except Exception:
    p("telnet ram test failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])

# ---- B. RAM write via GDB M ------------------------------------------------
sect("B. GDB M packet RAM write test @0x20000044")
try:
    b0 = g_rd32(0x20000044)
    r = g_wr32(0x20000044, 0x5A5AA5A5)
    b1 = g_rd32(0x20000044)
    g_wr32(0x20000044, b0 if b0 is not None else 0)
    p("before=%s resp=%r after=%s -> gdb M RAM write: %s" %
      (("%08X" % b0) if b0 is not None else "None", r,
       ("%08X" % b1) if b1 is not None else "None",
       "WORKS" if (b1 == 0x5A5AA5A5) else "NO EFFECT"))
except Exception:
    p("gdb ram test failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])

# ---- C. GPIO DATA write via telnet ------------------------------------------
sect("C. TELNET mww GPIO K DATA (STB line) flip test")
gpio_ok_telnet = False
try:
    out = tel.cmd("mdw 0x400610c0 1")
    p("K DATA(mask 0x30) before: %s" % out.decode(errors="replace").strip()[:80])
    tel.cmd("mww 0x400610c0 0x00")   # STB low, DIO low
    out = tel.cmd("mdw 0x400610c0 1")
    p("after writing 0x00     : %s" % out.decode(errors="replace").strip()[:80])
    gpio_ok_telnet = "00000000" in out.decode(errors="replace").lower()
    tel.cmd("mww 0x400610c0 0x00000030")  # STB high, DIO high
    out = tel.cmd("mdw 0x400610c0 1")
    p("restored 0x30          : %s" % out.decode(errors="replace").strip()[:80])
    p("=> telnet mww GPIO write: %s" % ("WORKS" if gpio_ok_telnet else "NO EFFECT"))
except Exception:
    p("gpio test failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])

# ---- D. stable identity + core regs -----------------------------------------
sect("D. IDENTITY (gdb reads, stable)")
try:
    cpuid = g_rd32(0xE000ED00)
    p("CPUID=0x%08X -> implementer=0x%02X partno=0x%03X variant=r%dp%d arch=0x%X" %
      (cpuid, (cpuid >> 24) & 0xFF, (cpuid >> 4) & 0xFFF, (cpuid >> 20) & 0xF,
       cpuid & 0xF, (cpuid >> 16) & 0xF))
    p("  partno 0xC24 = ARM Cortex-M4" if ((cpuid >> 4) & 0xFFF) == 0xC24 else "  partno unexpected!")
    d0 = g_rd32(0x400FE000); d1 = g_rd32(0x400FE004)
    d0b = g_rd32(0x400FE000); d1b = g_rd32(0x400FE004)
    p("DID0=0x%08X/%08X  DID1=0x%08X/%08X" % (d0, d0b, d1, d1b))
    syst_csr = g_rd32(0xE000E010); syst_rvr = g_rd32(0xE000E014); syst_cvr = g_rd32(0xE000E018)
    p("SysTick: CSR=0x%08X (ENABLE=%d TICKINT=%d CLKSOURCE=%d) RVR=%d CVR=%d" %
      (syst_csr, syst_csr & 1, (syst_csr >> 1) & 1, (syst_csr >> 2) & 1, syst_rvr, syst_cvr))
    p("  -> SysTick reload for 20ms @ 20MHz would be RVR=399999 (observed %d)" % syst_rvr)
    iser0 = g_rd32(0xE000E100)
    p("NVIC ISER0=0x%08X (enabled IRQs bitmask)" % iser0)
except Exception:
    p("identity failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])

# ---- E. PP block chunked stable reads ---------------------------------------
sect("E. PP INVENTORY (44B chunks x2, stability-retried)")
try:
    ppvals = []
    for chunk in range(4):
        base = 0x400FE300 + chunk * 0x2C  # 44 bytes per chunk
        last = None
        for t in range(6):
            data = g_rdN(base, 0x2C)
            if data is None: continue
            if last is not None and data == last: break
            last = data
        ppvals.extend(words(last if last is not None else b""))
    names = {0x300: "WD0/1", 0x304: "TIMER0-7", 0x308: "GPIO", 0x30C: "DMA", 0x310: "EPI",
             0x314: "HIB", 0x318: "UART0-7", 0x31C: "SSI0-3", 0x320: "I2C0-9", 0x324: "-",
             0x328: "USB", 0x32C: "-", 0x330: "EPHY", 0x334: "CAN", 0x338: "ADC",
             0x33C: "ACMP", 0x340: "PWM", 0x344: "QEI", 0x348: "LPC", 0x350: "PECI",
             0x354: "FAN", 0x358: "EEPROM", 0x35C: "WTIMER", 0x370: "RTS", 0x374: "CCM",
             0x390: "LCD", 0x398: "1WIRE", 0x39C: "EMAC", 0x3A4: "HIM"}
    for i, v in enumerate(ppvals):
        a = 0x400FE300 + i * 4
        if a in names and names[a] != "-":
            p("  %-9s @0x%08X = 0x%08X (%d present)" % (names[a], a, v, bin(v).count("1")))
except Exception:
    p("PP failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])

# ---- F. resume ---------------------------------------------------------------
sect("F. RESUME")
try:
    rsp.close(); time.sleep(0.3)
    tel.cmd("resume")
    out = tel.cmd("targets")
    txt = out.decode(errors="replace")
    p("target state: %s" % ("RUNNING" if "running" in txt else txt.strip()[:120]))
    tel.close()
except Exception:
    p("resume failed: %s" % traceback.format_exc(limit=1).strip().splitlines()[-1])
OUT.close()
print("PROBE4 COMPLETE")
