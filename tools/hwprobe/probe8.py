#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe v8 (final): fresh-session reset-halt -> TM1638 real bus drive -> reset run."""
import hashlib, os, socket, time, traceback

RESULT_DIR = os.environ.get("HWPROBE_OUT_DIR", os.path.join(os.path.dirname(__file__), "results"))
os.makedirs(RESULT_DIR, exist_ok=True)
OUT = open(os.path.join(RESULT_DIR, "probe8_result.txt"), "w", encoding="utf-8")
def p(*a):
    line = " ".join(str(x) for x in a)
    print(line); OUT.write(line + "\n"); OUT.flush()

class Tel:
    def __init__(self, port=4444):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(40); self.buf = b""
        self.read_until("> ")
    def _recv(self):
        d = self.s.recv(65536)
        if not d: raise IOError("telnet closed")
        self.buf += d
    def read_until(self, pat, timeout=40):
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
    def close(self):
        try: self.s.close()
        except Exception: pass

class RSP:
    def __init__(self, port=3333):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(30); self.buf = b""
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
            if time.time() - t0 > 30: raise TimeoutError("no ack")
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

def rdbytes(addr, nbytes, tries=5):
    for _ in range(tries):
        r = rsp.cmd(("m%08x,%x" % (addr, nbytes)).encode())
        if not r.startswith(b"E") and len(r) >= nbytes * 2:
            return bytes.fromhex(r[:nbytes * 2].decode())
        time.sleep(0.02)
    return None

def mww(addr, val, pushes=2):
    tel.cmd("mww 0x%08X 0x%08X" % (addr, val))
    for _ in range(pushes):
        rd32(0xE000EDF0)
    return rd32(addr)

sect = lambda s: (p(""), p("#### %s ####" % s))
try:
    sect("0. RESET HALT (sysresetreq) + verify")
    tel.cmd("cortex_m reset_config sysresetreq")
    out = tel.cmd("reset halt")
    p("reset halt: %s" % out.decode(errors="replace").strip().replace("\r", " ")[:150])
    dh = rd32(0xE000EDF0)
    p("DHCSR=0x%08X S_HALT=%d S_RESET_ST=%d C_DEBUGEN=%d" %
      (dh, (dh >> 17) & 1, (dh >> 24) & 1, dh & 1))
    halted = bool(dh is not None and (dh >> 17) & 1)
    if not halted:
        raise IOError("target not halted after reset halt")

    sect("1. POST-RESET IDENTITY RE-CHECK + PP SINGLES")
    p("DID0=%08X DID1=%08X" % (rd32(0x400FE000), rd32(0x400FE004)))
    p("FSIZE=%08X SSIZE=%08X  (post-reset)" % (rd32(0x400FDFC0), rd32(0x400FDFC4)))

    sect("1A. FULL FLASH BACKUP (1 MiB)")
    flash_path = os.environ.get("HWPROBE_FLASH_OUT",
                                os.path.join(RESULT_DIR, "probe8_flash.bin"))
    if os.environ.get("HWPROBE_SKIP_FLASH") == "1":
        p("  SKIP: HWPROBE_SKIP_FLASH=1")
    else:
        tmp_path = flash_path + ".tmp"
        h = hashlib.sha256()
        total = 0x100000
        with open(tmp_path, "wb") as fp:
            for off in range(0, total, 0x400):
                chunk = rdbytes(off, min(0x400, total - off))
                if chunk is None:
                    raise IOError("flash read failed at 0x%08X" % off)
                fp.write(chunk)
                h.update(chunk)
        os.replace(tmp_path, flash_path)
        p("  wrote %d bytes -> %s" % (total, flash_path))
        p("  sha256=%s" % h.hexdigest())

    ppnames = {0x300: "WD", 0x304: "TIMER", 0x308: "GPIO", 0x30C: "DMA", 0x310: "EPI",
               0x314: "HIB", 0x318: "UART", 0x31C: "SSI", 0x320: "I2C", 0x328: "USB",
               0x330: "EPHY", 0x334: "CAN", 0x338: "ADC", 0x33C: "ACMP", 0x340: "PWM",
               0x344: "QEI", 0x348: "LPC", 0x350: "PECI", 0x354: "FAN", 0x358: "EEPROM",
               0x35C: "WTIMER", 0x370: "RTS", 0x374: "CCM", 0x390: "LCD", 0x398: "1WIRE",
               0x39C: "EMAC", 0x3A4: "HIM"}
    for off, nm in ppnames.items():
        v = rd32(0x400FE000 + off)
        p("  PP %-8s = %s (%d present)" % (nm, ("%08X" % v) if v is not None else "??",
                                            bin(v).count("1") if v else 0))

    sect("2. GPIO CLOCK/DEN/DIR SETUP (debugger configures TM1638 pins)")
    rcg = rd32(0x400FE608)
    mww(0x400FE608, (rcg or 0) | 0xA00)      # ports K(9), M(11)
    pr = 0
    for _ in range(200):
        pr = rd32(0x400FEA08) or 0
        if pr & 0xA00: break
    p("  RCGCGPIO=%08X PRGPIO=%08X (K,M ready=%d)" % (rd32(0x400FE608), pr, bool(pr & 0xA00)))
    denk = rd32(0x4006151C); mww(0x4006151C, (denk or 0) | 0x30)
    dirk = rd32(0x40061400); mww(0x40061400, (dirk or 0) | 0x30)
    denm = rd32(0x4006351C); mww(0x4006351C, (denm or 0) | 0x01)
    dirm = rd32(0x40063400); mww(0x40063400, (dirm or 0) | 0x01)
    p("  K: DEN=%08X DIR=%08X   M: DEN=%08X DIR=%08X" %
      (rd32(0x4006151C), rd32(0x40061400), rd32(0x4006351C), rd32(0x40063400)))

    sect("3. TM1638 REAL BUS DRIVE (display + key readback)")
    KDATA, KFULL = 0x400610C0, 0x400613FC
    KCLK, MCLKFULL = 0x40063004, 0x400633FC
    DIRK = 0x40061400
    def stb(v):  mww(KDATA, (0x10 if v else 0x00) | 0x20)
    def clk(v):  mww(KCLK, 0x01 if v else 0x00)
    def dio(v):  mww(KDATA, 0x10 | (0x20 if v else 0x00))
    def rd_dio(): return ((rd32(KDATA) or 0) >> 5) & 1
    def send_byte(b):
        for i in range(8):
            clk(0); dio((b >> i) & 1); clk(1)
    stb(True)
    stb(False); send_byte(0x40); stb(True)
    stb(False); send_byte(0xC0)
    for _ in range(8):
        send_byte(0xFF); send_byte(0x01)
    stb(True)
    stb(False); send_byte(0x8F); stb(True)
    p("  wrote display RAM: 8 digits '8.' + 8 LEDs ON, brightness 0x8F")
    p("  >>> LOOK AT THE BOARD: all 8 digits show 8. and all 8 LEDs should be lit <<<")
    dirk = rd32(DIRK)
    reads = []
    for trial in range(3):
        stb(True); stb(False)
        send_byte(0x42)                         # read-key command, DIO as OUTPUT
        mww(DIRK, (dirk or 0x30) & ~0x20)       # DIO -> input
        cb = []
        for _b in range(4):
            t = 0
            for _bit in range(8):
                t >>= 1
                clk(False)
                if rd_dio(): t |= 0x80
                clk(True)
            cb.append(t)
        mww(DIRK, dirk or 0x30)                 # DIO -> output
        stb(True)
        reads.append(cb)
        time.sleep(0.05)
    for c in reads:
        if all(x == 0 for x in c):
            p("  key scan (%02X %02X %02X %02X): TM1638 DRIVES 0x00 -> chip ALIVE, no key" % tuple(c))
        elif all(x == 0xFF for x in c):
            p("  key scan (%02X %02X %02X %02X): all-FF -> no response" % tuple(c))
        else:
            keys = [k for m, k in {0x04: 1, 0x02: 2, 0x01: 3, 0x40: 4, 0x20: 5, 0x10: 6}.items() if c[0] & m]
            keys += [k for m, k in {0x04: 7, 0x02: 8, 0x01: 9}.items() if c[1] & m]
            p("  key scan (%02X %02X %02X %02X): PRESSED KEY(S) = %s" % (tuple(c) + (keys,)))
    p("  (leave display pattern; firmware restart next will repaint it)")

    sect("4. RESET RUN (clean firmware restart)")
    rsp.close(); time.sleep(0.3)
    tel.cmd("reset run")
    time.sleep(1.0)
    out = tel.cmd("targets")
    txt = out.decode(errors="replace")
    line = [l for l in txt.splitlines() if "tm4c1294" in l]
    p("final: %s" % (line[0].strip() if line else txt.strip()[:100]))
    tel.close()
except Exception:
    p("FATAL: %s" % traceback.format_exc())
    try:
        rsp.close(); tel.cmd("reset run"); tel.close(); p("(reset-run after fatal)")
    except Exception:
        pass
OUT.close()
print("PROBE8 COMPLETE")
