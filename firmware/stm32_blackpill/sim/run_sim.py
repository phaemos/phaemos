#!/usr/bin/env python3
"""
run_sim.py - emulation test for the Black Pill vibration node firmware

starts Renode (headless) once per scenario with the real firmware ELF on the board description in
blackpill.repl, drives the scripted MPU6050 (mpu6050_sim.cs) through the Renode monitor, captures what the
firmware sends on USART1 over a socket and checks it with its own CRC and line parser.  python 3 standard
library only.  see README.md for what each scenario proves and what the emulation cannot show.

exit status is non-zero when any scenario FAILs or could not run (NOT RUN, unless named with --optional).
FINDING and SKIPPED do not fail the run.
"""

import argparse
import concurrent.futures as cf
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.dirname(HERE)
DEFAULT_ELF = os.path.join(FW_DIR, ".pio", "build", "blackpill_f411ce", "firmware.elf")
DEFAULT_RENODE = os.path.expanduser("~/Applications/Renode.app/Contents/MacOS/macos_run.command")
BUILD = os.path.join(HERE, "build")

WINDOW_S = 1.28
ST_MISSING, ST_STUCK, ST_CLIP, ST_ID, ST_WDOG, ST_DROP, ST_BOR, ST_NO_DATA = 1, 2, 4, 8, 16, 32, 64, 128

# ---------------------------------------------------------------------------------------------------
# the harness's own CRC-16/CCITT-FALSE (bit by bit) and line parser.  nothing here is shared with the
# firmware sources.
# ---------------------------------------------------------------------------------------------------


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


assert crc16(b"123456789") == 0x29B1

LINE_RE = re.compile(
    r"^VIB:(-?\d+\.\d\d),(-?\d+\.\d\d),(-?\d+\.\d\d),MAG:(\d+\.\d\d),FFT_PEAK:(\d+\.\d)Hz,"
    r"RMS:(\d+\.\d{3}),(\d+\.\d{3}),(\d+\.\d{3}),PK:(\d+\.\d{3}),"
    r"ST:(\d+),SEQ:(\d+),UP:(\d+),MT:(\d+),RF:(\d+),BR:(\d+)\*([0-9A-F]{4})$")
PONG_RE = re.compile(r"^PONG:(\d+)\*([0-9A-F]{4})$")


class Line:
    def __init__(self, t, raw):
        self.t = t                      # simulated time at the end of the step it arrived in
        self.raw = raw
        self.kind = "garbage"
        self.crc_ok = False
        self.len = len(raw) + 2
        body, star, tail = raw.rpartition("*")
        if star and len(tail) == 4:
            self.crc_ok = ("%04X" % crc16(body.encode("latin-1"))) == tail
        m = LINE_RE.match(raw)
        if m:
            g = m.groups()
            self.kind = "data"
            self.vib = tuple(float(x) for x in g[0:3])
            self.mag = float(g[3])
            self.fft = float(g[4])
            self.rms = tuple(float(x) for x in g[5:8])
            self.pk = float(g[8])
            self.st, self.seq, self.up, self.mt, self.rf, self.br = (int(x) for x in g[9:15])
            return
        m = PONG_RE.match(raw)
        if m:
            self.kind = "pong"
            self.n = int(m.group(1))

    @property
    def zero(self):
        return self.kind == "data" and not any(self.vib) and self.mag == 0 and not any(self.rms) and self.pk == 0


# ---------------------------------------------------------------------------------------------------
# one Renode process
# ---------------------------------------------------------------------------------------------------


class Sim:
    def __init__(self, name, elf, renode, mips, ports, loglevel=3, step=0.05):
        self.name, self.elf, self.renode, self.mips = name, elf, renode, mips
        self.mon_port, self.uart_port = ports
        self.loglevel = loglevel
        self.step = step
        self.vt = 0.0
        self.lines = []
        self.rxbuf = b""
        self.log = []
        self.track_led = False
        self.led = []                   # (simulated time, level of PC13) once per step
        self.proc = None
        self.mon = None
        self.uart = None

    # -- start up and shut down --
    def start(self, unplug=False, wdflag=False, nohse=False):
        """start Renode.  it very occasionally stalls while loading the script, so a start that is not ready
        after 120 s is killed and tried again, up to three times"""
        last = None
        for attempt in range(3):
            try:
                self._start_once(unplug, wdflag, nohse, attempt)
                return
            except RuntimeError as e:
                last = e
                self.stop()
        raise last

    def _start_once(self, unplug, wdflag, nohse, attempt):
        self.log = []
        self.mon_port += 100 * attempt
        self.uart_port += 100 * attempt
        resc = os.path.join(BUILD, "%s.resc" % self.name)
        with open(resc, "w") as f:
            f.write('$repl=@%s\n$elf=@%s\ninclude @%s\n' % (os.path.join(HERE, "blackpill.repl"), self.elf,
                                                            os.path.join(HERE, "blackpill.resc")))
            f.write("sysbus.cpu PerformanceInMips %d\n" % self.mips)
            f.write('emulation CreateServerSocketTerminal %d "term" false\n' % self.uart_port)
            f.write("connector Connect sysbus.usart1 term\n")
            if unplug:
                f.write("sysbus.mpuctl Unplug\n")
            if wdflag:
                # the model leaves RCC_CSR at its power-on value after a watchdog reset.  silicon would set
                # IWDGRSTF and clear the power-on flags, so on every reset from now on the harness does that
                # for reads of RCC_CSR.  it is not active during the first boot.
                f.write('macro reset\n"""\n    sysbus LoadELF $elf\n    sysbus SetHookAfterPeripheralRead sysbus.rcc '
                        '"value = (value & ~0x0E000000) | 0x20000000" <0x74 +4>\n"""\n')
            if nohse:
                # hold HSERDY (bit 17 of RCC_CR) low, so the crystal never reports ready.  the hook is set again in
                # the reset macro because a reset reloads the ELF through it
                hook = 'sysbus SetHookAfterPeripheralRead sysbus.rcc "value = value & ~0x20000" <0x0 +4>'
                f.write(hook + '\n')
                f.write('macro reset\n"""\n    sysbus LoadELF $elf\n    ' + hook + '\n"""\n')
            f.write('logLevel 1\nlog "READY-FOR-HARNESS"\nlogLevel %d\n' % self.loglevel)
        self.proc = subprocess.Popen([self.renode, "--disable-xwt", "-P", str(self.mon_port), "--plain", resc],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     start_new_session=True)
        threading.Thread(target=self._reader, daemon=True).start()
        t0 = time.time()
        while not any("READY-FOR-HARNESS" in l for l in self.log):
            if time.time() - t0 > 120 or self.proc.poll() is not None:
                raise RuntimeError("Renode did not start: " + "".join(self.log[-8:]))
            time.sleep(0.2)
        errs = [l for l in self.log if "There was an error" in l or "Error E" in l]
        if errs:
            raise RuntimeError("Renode script error: " + "".join(errs[:3]))
        self.mon = socket.create_connection(("127.0.0.1", self.mon_port), timeout=5)
        self.mon.settimeout(0.5)
        self.uart = socket.create_connection(("127.0.0.1", self.uart_port), timeout=5)
        self.uart.settimeout(0.001)
        self.cmd("mach set 0")

    def _reader(self):
        for l in self.proc.stdout:
            self.log.append(l)

    def stop(self):
        for s in (self.mon, self.uart):
            try:
                s.close()
            except Exception:
                pass
        if self.proc:
            try:
                os.killpg(self.proc.pid, 9)
            except Exception:
                pass

    # -- monitor --
    def cmd(self, c, timeout=120):
        self.mon.sendall((c + "\r\n").encode())
        buf = b""
        t = time.time()
        while time.time() - t < timeout:
            try:
                d = self.mon.recv(65536)
            except socket.timeout:
                d = b""
            buf += d
            clean = re.sub(rb"\xff[\xfb-\xfe].", b"", buf)
            if clean.rstrip().endswith(b"(blackpill)") and c.encode()[:20] in clean:
                break
        else:
            raise RuntimeError("Renode monitor did not answer %r within %d s" % (c[:40], timeout))
        text = re.sub(rb"\xff[\xfb-\xfe].", b"", buf).decode(errors="replace")
        return text

    def value(self, c):
        out = self.cmd(c)
        m = re.findall(r"0x[0-9A-Fa-f]+", out.split("\n", 1)[-1] if c in out.split("\n")[0] else out)
        # the answer is the last 0x... token before the next prompt
        toks = re.findall(r"^(0x[0-9A-Fa-f]+)\s*$", out, re.M)
        return int(toks[-1], 16) if toks else (int(m[-1], 16) if m else None)

    def mpu(self, call):
        return self.cmd("sysbus.mpuctl " + call)

    # -- time and uart --
    def _drain(self):
        try:
            while True:
                d = self.uart.recv(4096)
                if not d:
                    break
                self.rxbuf += d
        except (socket.timeout, BlockingIOError):
            pass
        while b"\n" in self.rxbuf:
            raw, self.rxbuf = self.rxbuf.split(b"\n", 1)
            self.lines.append(Line(self.vt, raw.rstrip(b"\r").decode("latin-1")))

    def run(self, seconds, step=None):
        step = step or self.step
        end = self.vt + seconds
        while self.vt < end - 1e-9:
            s = min(step, end - self.vt)
            self.cmd("emulation RunFor '%.4f'" % s)
            self.vt += s
            self._drain()
            if self.track_led:
                v = self.value("sysbus ReadDoubleWord 0x40020814")      # GPIOC_ODR
                if v is not None:
                    self.led.append((self.vt, (v >> 13) & 1))

    def run_until(self, pred, limit, step=None):
        end = self.vt + limit
        while self.vt < end and not pred():
            self.run(step or self.step, step)
        return pred()

    def send(self, data):
        self.uart.sendall(data)

    def data(self, since=0):
        return [l for l in self.lines if l.kind == "data" and l.t >= since]

    def pongs(self):
        return [l for l in self.lines if l.kind == "pong"]

    def garbage(self):
        return [l for l in self.lines if l.kind == "garbage"]


# ---------------------------------------------------------------------------------------------------
# scenario plumbing
# ---------------------------------------------------------------------------------------------------


class Result:
    def __init__(self, num, name):
        self.num, self.name = num, name
        self.status = "PASS"
        self.notes = []
        self.checks = []
        self.findings = []
        self.secs = 0.0

    def check(self, ok, msg):
        self.checks.append((bool(ok), msg))
        if not ok:
            self.status = "FAIL"
        return ok

    def finding(self, msg):
        self.findings.append(msg)

    def finish(self):
        if self.status == "PASS" and self.findings:
            self.status = "FINDING"


def sine_signal(sim, freq, amp_z, off_z=16384):
    sim.mpu("SetSignal %g 0 0 %g 0 0 %g" % (freq, amp_z, off_z))


def basic_line_checks(r, sim, lines, allow_seq_restart=False):
    """CRC good, shape good, length, no garbage, SEQ without gaps, UP not going backwards"""
    r.check(not sim.garbage(), "no malformed output (%d garbage line(s))" % len(sim.garbage()))
    r.check(all(l.crc_ok for l in lines), "CRC good on all %d data lines" % len(lines))
    r.check(all(l.len <= 160 for l in lines), "every line within 160 bytes (longest %d)" % max([l.len for l in lines] or [0]))
    if lines and not allow_seq_restart:
        seqs = [l.seq for l in lines]
        r.check(seqs == list(range(seqs[0], seqs[0] + len(seqs))), "SEQ without gaps: %s" % seqs)
        r.check(seqs[0] == 0, "first line has SEQ 0")
    ups = [l.up for l in lines]
    r.check(all(b >= a for a, b in zip(ups, ups[1:])), "UP never goes backwards: %s" % ups)


def led_toggles(sim, t_from=0.0, t_to=1e9):
    """times at which PC13 changed level, from the once-per-step samples"""
    out = []
    prev = None
    for t, v in sim.led:
        if prev is not None and v != prev and t_from <= t <= t_to:
            out.append(t)
        prev = v
    return out


def intervals(ts):
    return [round(b - a, 2) for a, b in zip(ts, ts[1:])]


def gaps(lines):
    return [round(b.t - a.t, 2) for a, b in zip(lines, lines[1:])]


# ---------------------------------------------------------------------------------------------------
# scenarios.  each takes (sim, result) and drives the run.
# ---------------------------------------------------------------------------------------------------

AMP = 5000.0                       # raw counts, 0.305 g
AMP_G = AMP / 16384.0


def sc_boot(sim, r):
    sine_signal(sim, 10, AMP)
    sim.run(2.0)
    d = sim.data()
    r.check(len(d) >= 1, "firmware got through clock set-up and HAL init and sent a line (%d line)" % len(d))
    rd = sim.value
    # registers the firmware wrote.  the emulation does not run the PLL, so this proves what the firmware
    # asked for and nothing about whether a real PLL would lock
    pll = rd("sysbus ReadDoubleWord 0x40023804")
    cfg = rd("sysbus ReadDoubleWord 0x40023808")
    exp_pll = 25 | (192 << 6) | (0 << 16) | (1 << 22) | (4 << 24)
    # bits 31:28 of PLLCFGR are reserved and keep their reset value, so only the defined fields are compared
    r.check(pll is not None and (pll & 0x0F437FFF) == exp_pll, "RCC_PLLCFGR M=25 N=192 P=2 Q=4 source HSE (0x%08X, expected 0x%08X in the defined bits)" % (pll or 0, exp_pll))
    r.check(cfg is not None and (cfg & 3) == 2 and ((cfg >> 10) & 7) == 4 and ((cfg >> 13) & 7) == 0 and ((cfg >> 4) & 15) == 0,
            "RCC_CFGR system clock PLL, AHB /1, APB1 /2, APB2 /1 (0x%08X)" % (cfg or 0))
    psc = rd("sysbus ReadDoubleWord 0x40000028")
    arr = rd("sysbus ReadDoubleWord 0x4000002C")
    r.check(psc == 9599 and arr == 99, "TIM2 PSC 9599 ARR 99 (PSC %s ARR %s)" % (psc, arr))
    pr = rd("sysbus ReadDoubleWord 0x40003004")
    rl = rd("sysbus ReadDoubleWord 0x40003008")
    r.check(rl == 2000, "IWDG reload 2000 (got %s) and prescaler register %s (4 is divide by 64)" % (rl, pr))
    brr = rd("sysbus ReadDoubleWord 0x40011008")
    r.check(brr == 0x341, "USART1 BRR 0x341 for 115200 baud at 96 MHz (got 0x%X)" % (brr or 0))
    acc = rd("sysbus ReadDoubleWord 0x40023C00")
    r.notes.append("FLASH_ACR read back as %s (the flash controller model may not keep the latency field)" % (hex(acc) if acc is not None else None))
    r.check(sim.mpu("AccelRange").count("0x00000000") >= 1, "ACCEL_CONFIG written as 0x00 (+/-2 g)")
    # the unhandled register accesses seen during boot (log level raised for this scenario)
    un = sorted(set(re.sub(r"^\[[^\]]*\] ", "", l.strip()) for l in sim.log if "nhandled" in l or "non existing" in l))
    un = sorted(set(re.sub(r"value 0x[0-9A-Fa-f]+", "value ...", u) for u in un))
    r.notes.append("unhandled register accesses logged: %d distinct" % len(un))
    for u in un[:12]:
        r.notes.append("  " + u[:150])


def sc_healthy(sim, r):
    sim.track_led = True
    sine_signal(sim, 10, AMP)
    sim.run(7.0)
    hb = intervals(led_toggles(sim))
    r.check(len(hb) >= 3 and all(abs(x - WINDOW_S) <= 0.15 for x in hb), "LED heartbeat: one toggle per window, never the slow blink: %s" % hb)
    d = sim.data()
    r.check(len(d) == 5, "5 lines in 7.0 s of simulated time (got %d)" % len(d))
    basic_line_checks(r, sim, d)
    g = gaps(d)
    r.check(all(abs(x - WINDOW_S) <= 0.11 for x in g), "gap between lines 1.28 s +/- 0.11 s (measured %s)" % g)
    r.check(d and abs(d[0].t - WINDOW_S) <= 0.2, "first line at %.2f s (expected about 1.28 s)" % (d[0].t if d else -1))
    r.check(all(l.st == 0 for l in d), "ST 0 on every line (%s)" % [l.st for l in d])
    r.check(all(abs(l.up - int(l.t - 0.05)) <= 1 for l in d), "UP tracks simulated time: %s at %s" % ([l.up for l in d], [l.t for l in d]))
    r.check(all(abs(l.fft - 10.0) <= 100.0 / 128 for l in d), "FFT_PEAK within one bin of 10 Hz: %s" % [l.fft for l in d])
    want = AMP_G / math.sqrt(2)
    r.check(all(abs(l.rms[2] - want) <= 0.02 * want + 0.001 for l in d), "RMS z near amplitude over root two (%.4f g): %s" % (want, [l.rms[2] for l in d]))
    r.check(all(l.rms[0] == 0 and l.rms[1] == 0 for l in d), "RMS x and y zero (no signal there)")
    r.check(all(abs(l.vib[2] - 1.0) <= 0.01 for l in d), "VIB z about 1.00 g (gravity offset)")
    r.check(all(abs(l.mag - 1.0) <= 0.01 for l in d), "MAG about 1.00 g")
    r.check(all(abs(l.pk - AMP_G) <= 0.02 for l in d), "PK near the amplitude %.3f g: %s" % (AMP_G, [l.pk for l in d]))
    r.check(all(l.mt == 0 and l.rf == 0 and l.br == 0 for l in d), "MT RF BR all zero")
    r.notes.append("gaps %s s, UP %s" % (g, [l.up for l in d]))


def sc_absent_boot(sim, r):
    sim.run(4.2)
    z = sim.data()
    r.check(len(z) >= 3, "zero lines keep coming with no sensor (%d lines in 4.2 s)" % len(z))
    r.check(all(l.zero for l in z), "readings are all zero")
    r.check(all(l.st & ST_MISSING for l in z), "SENSOR_MISSING on every one (ST %s)" % [l.st for l in z])
    r.check(all(l.crc_ok for l in z), "CRC good on all")
    g = gaps(z)
    r.check(z and abs(z[0].t - WINDOW_S) <= 0.25, "first line at %.2f s" % (z[0].t if z else -1))
    r.check(all(abs(x - WINDOW_S) <= 0.11 for x in g), "normal rhythm 1.28 s +/- 0.11 s (measured %s)" % g)
    sine_signal(sim, 10, AMP)
    sim.mpu("Plug")
    sine_signal(sim, 10, AMP)
    n0 = len(sim.data())
    ok = sim.run_until(lambda: any(l.st & ST_MISSING == 0 for l in sim.data()[n0:]), 9.0)
    r.check(ok, "sensor appears and a good line follows")
    d = sim.data()
    good = [l for l in d[n0:] if not (l.st & ST_MISSING)]
    if good:
        r.check(good[0].st & ~ST_DROP == 0, "first good line has no fault bit (ST %d)" % good[0].st)
        r.check(abs(good[0].rms[2] - AMP_G / math.sqrt(2)) <= 0.02, "its RMS z %.3f matches the signal" % good[0].rms[2])
        r.notes.append("first good line %.2f s after the sensor appeared" % (good[0].t - (d[n0].t if len(d) > n0 else 0)))
        sim.run(WINDOW_S * 2 + 0.2)
        last = sim.data()[-2:]
        r.check(all(l.st == 0 for l in last), "later lines are clean (ST %s)" % [l.st for l in last])
    basic_line_checks(r, sim, sim.data())
    r.notes.append("counters at the end: RF %d BR %d MT %d (a failed read costs a 20 ms timeout in this I2C model, which also costs ticks)" %
                   (sim.data()[-1].rf, sim.data()[-1].br, sim.data()[-1].mt))


def sc_lost_midrun(sim, r):
    sim.track_led = True
    sine_signal(sim, 10, AMP)
    sim.run(3.2)
    before = list(sim.data())
    r.check(len(before) == 2 and all(l.st == 0 for l in before), "two good lines before the loss")
    r.check(len(led_toggles(sim)) >= 2, "heartbeat: the LED on PC13 toggles once per window (%s)" % intervals(led_toggles(sim)))
    sim.mpu("Unplug")
    t_lost = sim.vt
    sim.run(5.2)
    mid = [l for l in sim.data() if l.t > t_lost]
    z = [l for l in mid if l.zero]
    r.check(len(z) >= 3, "zero lines on the rhythm while lost (%d lines in 5.2 s)" % len(z))
    r.check(all(l.st & ST_MISSING for l in z), "SENSOR_MISSING on each (ST %s)" % [l.st for l in mid])
    r.check(all(abs(x - WINDOW_S) <= 0.15 for x in gaps(mid)), "rhythm 1.28 s +/- 0.15 s: %s" % gaps(mid))
    blink = intervals(led_toggles(sim, t_lost + 1.5))
    r.check(len(blink) >= 3 and all(0.4 <= x <= 0.7 for x in blink), "while lost the LED blinks slowly, a toggle every 0.5 s: %s" % blink)
    sim.mpu("Plug")
    sine_signal(sim, 10, AMP)
    n0 = len(sim.data())
    ok = sim.run_until(lambda: any(not (l.st & ST_MISSING) for l in sim.data()[n0:]), 9.0)
    r.check(ok, "the sensor returns and a good line follows")
    sim.run(WINDOW_S * 2 + 0.1)
    d = sim.data()
    good = [l for l in d[n0:] if not (l.st & ST_MISSING)]
    r.check(good and good[0].st & ~ST_DROP == 0, "SENSOR_MISSING clears on the first complete window (ST %s)" % ([l.st for l in good[:2]]))
    r.check(all(l.st == 0 for l in good[1:]), "and the lines after are clean")
    r.check(good and abs(good[0].rms[2] - AMP_G / math.sqrt(2)) <= 0.02, "readings are the injected signal again")
    t_back = good[0].t if good else sim.vt
    after = intervals(led_toggles(sim, t_back + 0.1))
    r.check(len(after) >= 1 and all(x >= 1.0 for x in after),
            "once the first window completes the slow blink stops and the heartbeat is back, a toggle per window: %s" % after)
    basic_line_checks(r, sim, d)


def sc_one_failed(sim, r):
    sine_signal(sim, 10, AMP)
    sim.run(1.9)
    n0 = len(sim.data())
    r.check(n0 == 1, "one line so far (the window is about half full at 1.9 s)")
    # two all-zero triples in a row: the firmware counts each as a failed read and the retry within the tick
    # fails too, so this is one failed tick.  (one all-zero triple alone is rescued by the retry, see scenario 13)
    sim.mpu("ZeroNext 2")
    t_fail = sim.vt
    sim.run(5.0)
    d = sim.data()
    after = [l for l in d if l.t > t_fail]
    r.check(not any(l.zero for l in d), "no zero line at all")
    r.check(not any(l.st & ST_MISSING for l in d), "SENSOR_MISSING never set (ST %s)" % [l.st for l in d])
    r.check(len(after) >= 2 and after[0].st & ST_DROP, "WINDOW_DROPPED on the next line (ST %s)" % [l.st for l in after])
    r.check(len(after) >= 2 and after[1].st == 0, "and gone on the one after")
    r.check(after and after[0].t - t_fail > 0.9, "that line arrives a full window after the failure (%.2f s)" % (after[0].t - t_fail if after else -1))
    r.check(after and after[-1].rf == 2, "RF counted the two failed attempts (RF %s)" % [l.rf for l in after])
    basic_line_checks(r, sim, d)
    r.notes.append("no line at the 2.56 s mark: lines at %s" % [l.t for l in d])


def sc_stuck(sim, r):
    sim.mpu("SetSignal 10 0 0 0 100 -200 16384")        # constant on all three axes
    sim.run(4.0)
    d = sim.data()
    r.check(len(d) >= 3 and all(l.st & ST_STUCK for l in d), "SENSOR_STUCK on every line (ST %s)" % [l.st for l in d])
    r.check(all(l.st == ST_STUCK for l in d), "and nothing else is set")
    r.check(all(l.rms == (0, 0, 0) and l.pk == 0 and l.fft == 0 for l in d), "RMS 0, PK 0, FFT_PEAK 0.0 for a constant window")
    r.check(all(abs(l.vib[2] - 1.0) <= 0.01 for l in d), "the readings are still sent (VIB z 1.00)")
    n0 = len(sim.data())
    sine_signal(sim, 10, AMP)
    sim.run(WINDOW_S * 3)
    later = sim.data()[n0:]
    r.check(later and all(l.st == 0 for l in later[-2:]), "clears when the data moves again (ST %s)" % [l.st for l in later])
    basic_line_checks(r, sim, sim.data())


def sc_clip(sim, r):
    sim.mpu("SetSignal 10 0 0 20000 0 0 16384")         # peaks at 36384 counts, past +full scale
    sim.run(4.0)
    d = sim.data()
    r.check(len(d) >= 3 and all(l.st == ST_CLIP for l in d), "CLIPPING and nothing else on every line (ST %s)" % [l.st for l in d])
    sim.mpu("SetSignal 10 0 0 15000 0 0 16000")         # peaks at 31000, below full scale
    n0 = len(sim.data())
    sim.run(WINDOW_S * 3)
    later = sim.data()[n0:]
    r.check(later and later[-1].st == 0, "no CLIPPING at a 31000 count peak, under full scale (ST %s)" % [l.st for l in later])
    sim.mpu("SetSignal 10 0 0 0 0 0 32767")             # constant at exactly +full scale
    n0 = len(sim.data())
    sim.run(WINDOW_S * 3)
    later = sim.data()[n0:]
    r.check(later and later[-1].st & ST_CLIP, "CLIPPING at exactly 32767 (ST %s)" % [l.st for l in later])
    basic_line_checks(r, sim, sim.data())


def sc_id(sim, r):
    sim.mpu("SetWhoAmI 112")                              # 0x70
    sine_signal(sim, 10, AMP)
    sim.run(4.0)
    d = sim.data()
    r.check(len(d) >= 3 and all(l.st & ST_ID for l in d), "ID_MISMATCH on every line (ST %s)" % [l.st for l in d])
    r.check(all(l.st == ST_ID for l in d), "and nothing else is set: the node keeps sampling")
    r.check(all(abs(l.rms[2] - AMP_G / math.sqrt(2)) <= 0.02 for l in d), "readings still sent")
    basic_line_checks(r, sim, d)
    r.notes.append("the periodic re-check (every 100 windows, 128 s) is not exercised here, see scenario 19")


def sc_sleep(sim, r):
    sine_signal(sim, 10, AMP)
    sim.run(2.0)
    r.check(sim.value("sysbus.mpuctl Pwr") == 0, "part awake after init (PWR_MGMT_1 0x00)")
    w0 = sim.value("sysbus.mpuctl Writes")
    sim.mpu("ForceSleep")
    r.check(sim.value("sysbus.mpuctl Pwr") == 0x40, "sleep bit set by the harness")
    t0 = sim.vt
    sim.run(5.2)
    d = sim.data()
    after = [l for l in d if l.t > t0]
    stuck = [l for l in after if l.st & ST_STUCK]
    r.check(len(stuck) >= 1, "a stuck window is reported (ST %s)" % [l.st for l in after])
    r.check(sim.value("sysbus.mpuctl Pwr") == 0, "the firmware found the sleep bit and woke the part (PWR_MGMT_1 0x%02X)" % (sim.value("sysbus.mpuctl Pwr") or 0))
    w1 = sim.value("sysbus.mpuctl Writes")
    r.check(w1 > w0, "it re-wrote the sensor configuration (%d I2C writes before, %d after)" % (w0, w1))
    r.check(after and after[-1].st == 0 and abs(after[-1].rms[2] - AMP_G / math.sqrt(2)) <= 0.02,
            "the last line is clean with the signal back (ST %d RMS z %.3f)" % (after[-1].st, after[-1].rms[2]))
    basic_line_checks(r, sim, d)


def sc_ping(sim, r):
    sine_signal(sim, 10, AMP)
    sim.run(1.5)
    data_before = sim.data()
    seq_before = data_before[-1].seq if data_before else None
    # garbage first: nothing may come back
    for junk in (b"hello\n", b"PING:\n", b"PING:65536\n", b"\xff\xfe\x00\x80\n", b"PONG:5\n", b"xPING:3\n", b"ping:4\n"):
        sim.send(junk)
    sim.run(0.6, 0.02)
    r.check(not sim.pongs(), "garbage and malformed pings get no reply (%d pongs)" % len(sim.pongs()))
    # a long line then a good one
    sim.send(b"A" * 200 + b"\n")
    sim.run(0.1, 0.02)
    t_send = sim.vt
    sim.send(b"PING:42\n")
    ok = sim.run_until(lambda: len(sim.pongs()) >= 1, 0.7, 0.01)
    p = sim.pongs()
    r.check(ok and p[0].n == 42 and p[0].crc_ok, "PING:42 answered with a good PONG:42*CCCC (%s)" % (p[0].raw if p else None))
    if p:
        r.check(p[0].t - t_send <= 0.5, "pong within 500 ms of simulated time (%.2f s, step 0.01 s)" % (p[0].t - t_send))
        r.notes.append("pong latency %.2f s" % (p[0].t - t_send))
    # the ends of the number range and a CR LF ending
    sim.send(b"PING:0\r\n")
    sim.run(0.15, 0.01)
    sim.send(b"PING:65535\n")
    sim.run(0.15, 0.01)
    pn = [x.n for x in sim.pongs()]
    r.check(pn == [42, 0, 65535], "PING:0 (CR LF) and PING:65535 answered too: %s" % pn)
    # a ping split in two writes
    sim.send(b"PI")
    sim.run(0.05, 0.01)
    sim.send(b"NG:7\n")
    sim.run(0.2, 0.01)
    r.check([x.n for x in sim.pongs()][-1:] == [7], "a ping split across two writes is answered")
    sim.run(4.0)
    d = sim.data()
    basic_line_checks(r, sim, d)
    r.check(all(l.st == 0 for l in d), "data lines unaffected (ST %s)" % [l.st for l in d])
    seqs = [l.seq for l in d]
    r.check(seqs == list(range(len(seqs))), "a pong does not move SEQ: %s over %d pongs" % (seqs, len(sim.pongs())))
    r.check(all(l.crc_ok for l in sim.pongs()), "every pong has a good CRC")
    garb = [l.raw for l in sim.garbage()]
    r.check(not garb, "no stray output (%s)" % garb[:3])


def watchdog_run(sim, r, inject):
    sine_signal(sim, 10, AMP)
    sim.run(2.0)
    r.check(len(sim.data()) == 1, "running normally before the fault")
    # harness-forced hang: stop TIM2 so ticks stop.  the firmware's own rule is to stop refreshing the
    # watchdog when no tick has arrived for a second
    sim.cmd("sysbus WriteDoubleWord 0x40000000 0")
    t_hang = sim.vt
    sim.run_until(lambda: any(l.kind == "data" and l.seq == 0 and l.t > t_hang for l in sim.lines), 12.0, 0.1)
    again = [l for l in sim.data() if l.t > t_hang and l.seq == 0]
    # the watchdog must bite within a stated window: about 1 s of tick staleness plus the 4.0 s timeout, then
    # one window to the first line of the new boot.  8 s leaves room for the step size and the boot
    r.check(bool(again) and again[0].t - t_hang <= 8.0,
            "the IWDG reset the machine within 8 s of the hang (new boot's first line %s)" %
            ("%.1f s after TIM2 stopped" % (again[0].t - t_hang) if again else "never seen in 12 s"))
    if not again:
        return None
    r.check(True, "SEQ restarted at 0 on the new boot")
    r.check(0.1 <= again[0].t - t_hang - WINDOW_S <= 6.5,
            "reset after about 1 s of tick staleness plus the 4 s timeout (new line %.1f s after the hang, which includes one 1.28 s window)" % (again[0].t - t_hang))
    r.check(again[0].up <= 2, "UP restarted (UP %d)" % again[0].up)
    return again[0]


def sc_watchdog(sim, r):
    first = watchdog_run(sim, r, False)
    if first:
        r.notes.append("RESET_WATCHDOG is NOT checked here: the RCC model leaves IWDGRSTF clear (ST %d on the new line), see scenario 12" % first.st)


def sc_watchdog_flag(sim, r):
    first = watchdog_run(sim, r, True)
    if first:
        r.check(first.st & ST_WDOG, "the first line of the new boot carries RESET_WATCHDOG (ST %d)" % first.st)
        r.check(not first.st & ST_BOR, "and no RESET_BROWNOUT")
        sim.run(WINDOW_S + 0.2)
        r.check(sim.data()[-1].st & ST_WDOG, "it is held on the next line (ST %d)" % sim.data()[-1].st)
        r.notes.append("the flag was injected by the harness, so this proves the firmware reads, reports and holds it, not that the silicon sets it")


def sc_retry(sim, r):
    """one read in ten fails.  a failed read that returns quickly is retried within the tick, so the window carries on"""
    sine_signal(sim, 10, AMP)
    sim.run(1.5)
    sim.mpu("ZeroEvery 10")
    t0 = sim.vt
    sim.run(8.0)
    after = [l for l in sim.data() if l.t > t0]
    r.check(len(after) >= 5, "windows keep completing while a tenth of the reads fail: %d lines in 8 s" % len(after))
    r.check(not any(l.zero for l in sim.data()), "no zero line at all")
    r.check(not any(l.st & (ST_NO_DATA | ST_MISSING) for l in sim.data()), "no NO_DATA and no SENSOR_MISSING (ST %s)" % [l.st for l in sim.data()])
    r.check(not any(l.st & ST_DROP for l in after), "no window was dropped: the retry kept every one (ST %s)" % [l.st for l in after])
    r.check(all(abs(x - WINDOW_S) <= 0.15 for x in gaps(sim.data())), "lines stay on the 1.28 s rhythm: %s" % gaps(sim.data()))
    r.check(after and all(abs(l.rms[2] - AMP_G / math.sqrt(2)) <= 0.03 for l in after), "readings are still the signal (RMS z %s)" % [l.rms[2] for l in after])
    r.check(after and after[-1].rf >= 40, "RF still counts the failed reads so the hub sees the flaky bus (RF %s)" % [l.rf for l in after])
    basic_line_checks(r, sim, sim.data())
    r.notes.append("in the first version of this scenario (no retry) the same fault left the node sending no line at all")


def sc_flaky(sim, r):
    sine_signal(sim, 10, AMP)
    sim.mpu("ZeroPercent 2 7")                     # each read attempt fails at random with probability 2 per cent
    sim.run(60.0, 0.1)
    d = sim.data()
    nd = [l for l in d if l.st & ST_NO_DATA]
    good = [l for l in d if not l.st & ST_NO_DATA]
    gp = gaps(d)
    periods = 60.0 / WINDOW_S
    # a tick fails only when both attempts fail (0.02 squared).  a window of 128 ticks is good with probability
    # (1 - 0.0004) ^ 128, about 95 per cent.  a failure restarts the window, so the line rate is a little lower
    expect = 0.9995
    r.check(len(good) >= 0.80 * periods, "most windows complete: %d data lines in 60 s (%.0f periods, expected about 95 per cent of them)" % (len(good), periods))
    r.check(len(nd) <= 0.2 * len(d), "NO_DATA is rare: %d of %d lines" % (len(nd), len(d)))
    r.check(max(gp or [0]) <= 2 * WINDOW_S + 0.2, "never silent for more than two periods (longest gap %.2f s)" % max(gp or [0]))
    r.check(not any(l.st & ST_MISSING for l in d), "SENSOR_MISSING never set")
    r.check(d and 60 <= d[-1].rf <= 220, "RF shows the 2 per cent failure rate (RF %d for about 6000 reads, expected near 120 plus the second failures)" % (d[-1].rf if d else -1))
    r.check(all(l.crc_ok for l in d) and not sim.garbage(), "CRC good, no malformed output")
    seqs = [l.seq for l in d]
    r.check(seqs == list(range(len(seqs))), "SEQ without gaps")
    r.check(all(abs(l.fft - 10.0) <= 100.0 / 128 for l in good), "the data lines still show the 10 Hz peak (a retry does not distort the window)")
    r.notes.append("60 s at 2 per cent random read failures: %d lines, %d data and %d NO_DATA, RF %d, longest gap %.2f s" %
                   (len(d), len(good), len(nd), d[-1].rf if d else 0, max(gp or [0])))


def sc_nodata(sim, r):
    """failures that the single retry cannot rescue: two reads in a row fail, once in every ten reads"""
    sine_signal(sim, 10, AMP)
    sim.run(1.5)
    r.check(len(sim.data()) == 1, "one good line before the fault")
    last_good = sim.data()[-1]
    sim.mpu("ZeroRun 10 2")
    t0 = sim.vt
    sim.run(12.0)
    after = [l for l in sim.data() if l.t > t0]
    r.check(len(after) >= 7, "a line keeps coming while one tick in nine fails both attempts (%d lines in 12 s)" % len(after))
    if after:
        r.check(after[0].t - last_good.t <= 2 * WINDOW_S + 0.15,
                "first NO_DATA line %.2f s after the last good line (limit two periods, 2.56 s)" % (after[0].t - last_good.t))
        r.check(all(l.st & ST_NO_DATA for l in after), "every one has NO_DATA (ST %s)" % [l.st for l in after])
        r.check(all(l.zero for l in after), "readings are all zero")
        r.check(not any(l.st & ST_MISSING for l in after), "SENSOR_MISSING never set (the sensor is not lost)")
        r.check(all(l.st & ST_DROP for l in after), "WINDOW_DROPPED set as well")
        g = gaps(after)
        r.check(all(abs(x - WINDOW_S) <= 0.15 for x in g), "then one line per window period: %s" % g)
        r.check(after[-1].rf > after[0].rf, "RF keeps counting so the hub can see the failure rate (RF %d to %d)" % (after[0].rf, after[-1].rf))
    ok_before = len(sim.data())
    sim.mpu("ZeroRun 0 0")                         # the fault clears
    ok = sim.run_until(lambda: len([l for l in sim.data()[ok_before:] if l.st & ST_NO_DATA == 0]) >= 1, 6.0)
    r.check(ok, "when the reads recover a complete window arrives")
    good = [l for l in sim.data()[ok_before:] if not l.st & ST_NO_DATA]
    r.check(good and not good[0].zero and good[0].st & ST_NO_DATA == 0, "its line clears NO_DATA and has readings (ST %s)" % [l.st for l in good[:1]])
    sim.run(WINDOW_S + 0.2)
    r.check(sim.data()[-1].st == 0, "and the line after is clean (ST %d)" % sim.data()[-1].st)
    basic_line_checks(r, sim, sim.data())


def sc_timing(sim, r):
    """the sample reads stay 10 ms apart, including the read after each line is sent"""
    sine_signal(sim, 10, AMP)
    sim.run(1.0)
    sim.mpu("ResetGaps")
    sim.run(7.0)
    n = sim.value("sysbus.mpuctl GapCount")
    mx = sim.value("sysbus.mpuctl MaxGapUs")
    mn = sim.value("sysbus.mpuctl MinGapUs")
    over = sim.value("sysbus.mpuctl GapsOver11ms")
    under = sim.value("sysbus.mpuctl GapsUnder9ms")
    d = sim.data()
    r.check(n is not None and n >= 690, "the sensor model timed %s read-to-read gaps in 7 s (about 700 expected)" % n)
    r.check(over == 0, "no gap over 11 ms: no tick was lost around the %d lines sent (%s over)" % (len(d), over))
    r.check(under == 0, "no gap under 9 ms (%s under)" % under)
    r.check(mx is not None and mx <= 10500, "longest gap %s us, shortest %s us (the tick is 10000 us)" % (mx, mn))
    r.check(len(d) >= 4 and all(l.mt == 0 for l in d), "MT is 0 on every line (%s)" % [l.mt for l in d])
    r.notes.append("the model's UART sends instantly and the CPU runs at 8 MIPS, so this shows the loop does not wait on the line, not the 14 ms on a real wire")


def sc_crystal(sim, r):
    """the crystal never starts: the watchdog (started before the clock set-up) must reset the chip again and again"""
    sim.run(14.0)
    resets = [l for l in sim.log if "Watchdog reset triggered" in l]
    r.check(len(resets) >= 2, "the watchdog reset the chip %d times in 14 s of simulated time with no crystal (about every 4 s)" % len(resets))
    r.check(not sim.data(), "no line is sent while the crystal is missing (%d lines)" % len(sim.data()))
    # the crystal comes back: the next boot must run normally
    sim.cmd('macro reset "sysbus LoadELF $elf"')
    sim.cmd("sysbus ClearHookAfterPeripheralRead sysbus.rcc")
    sine_signal(sim, 10, AMP)
    ok = sim.run_until(lambda: len(sim.data()) >= 1, 12.0)
    r.check(ok, "when the crystal starts the node boots and sends lines again")
    if sim.data():
        r.check(sim.data()[0].crc_ok and sim.data()[0].st == 0, "first line is good (ST %d)" % sim.data()[0].st)
    r.notes.append("the crystal is refused by a read hook that holds HSERDY low in RCC_CR.  the node does not fall back to the internal oscillator: a node with no crystal is reported to the hub as a silent link")


def sc_pings(sim, r):
    """two pings 0.5 ms apart, a burst of pings and pings while a line is going out.  every pong that comes back
    must be whole, in order and no data line may be damaged"""
    sine_signal(sim, 10, AMP)
    sim.run(1.5)
    sim.send(b"PING:1\n")
    sim.run(0.0005, 0.0005)
    sim.send(b"PING:2\n")
    sim.run(0.4, 0.02)
    p = sim.pongs()
    r.check([x.n for x in p] == [1, 2] and all(x.crc_ok for x in p), "two pings 0.5 ms apart: both answered, both whole: %s" % [x.raw for x in p])
    n0 = len(p)
    for n in range(10, 16):                              # a burst of six, 0.5 ms apart
        sim.send(("PING:%d\n" % n).encode())
        sim.run(0.0005, 0.0005)
    sim.run(0.4, 0.02)
    p = sim.pongs()[n0:]
    r.check(len(p) >= 2 and all(x.crc_ok for x in p), "a burst of six pings: %d pongs came back, every one whole (the model's UART sends at once, so the node can answer them all; the queue limit is in the host test)" % len(p))
    r.check([x.n for x in p] == sorted(x.n for x in p), "and in order: %s" % [x.n for x in p])
    # pings while a line is on the wire: the next line is due 1.28 s after the last one
    d = sim.data()
    t_next = d[-1].t + WINDOW_S
    sim.run_until(lambda: sim.vt >= t_next - 0.02, 3.0, 0.01)
    n1 = len(sim.pongs())
    for k in range(40):
        sim.send(("PING:%d\n" % (100 + k)).encode())
        sim.run(0.001, 0.001)
    sim.run(0.5, 0.02)
    q = sim.pongs()[n1:]
    r.check(len(q) >= 3 and all(x.crc_ok for x in q), "forty pings around a line: %d pongs, every one whole" % len(q))
    r.check([x.n for x in q] == sorted(x.n for x in q) and len(set(x.n for x in q)) == len(q), "in order and none twice")
    sim.run(WINDOW_S * 2)
    dd = sim.data()
    basic_line_checks(r, sim, dd)
    r.check(all(l.st == 0 for l in dd), "the data lines are untouched (ST %s)" % [l.st for l in dd])
    r.check(not sim.garbage(), "no malformed output (%d)" % len(sim.garbage()))


def sc_long_id(sim, r):
    sim.mpu("SetWhoAmI 112")
    sine_signal(sim, 10, AMP)
    sim.run(3.0)
    r.check(sim.data() and sim.data()[-1].st & ST_ID, "ID_MISMATCH set at start")
    sim.mpu("SetWhoAmI 104")                              # the part is right again
    sim.run(135.0, 5.0)
    d = sim.data()
    r.check(d[-1].st & ST_ID == 0, "the periodic check (every 100 windows) clears ID_MISMATCH (last ST %d, %d lines)" % (d[-1].st, len(d)))
    r.check(any(l.st & ST_ID for l in d[:50]), "it stays set until that check (set on the first 50 lines)")


SCENARIOS = [
    (1, "Boot, clock and register read-back", sc_boot, dict(loglevel=2)),
    (2, "Healthy sensor, 10 Hz sine on Z", sc_healthy, {}),
    (3, "Sensor absent at boot, then appears", sc_absent_boot, dict(unplug=True)),
    (4, "Sensor lost mid-run, then returns", sc_lost_midrun, {}),
    (5, "One failed tick (both attempts)", sc_one_failed, {}),
    (6, "Frozen data (SENSOR_STUCK)", sc_stuck, {}),
    (7, "Full-scale data (CLIPPING)", sc_clip, {}),
    (8, "WHO_AM_I wrong (ID_MISMATCH)", sc_id, {}),
    (9, "Sleep bit set mid-run", sc_sleep, {}),
    (10, "Ping and pong", sc_ping, {}),
    (11, "Watchdog resets a hung node", sc_watchdog, {}),
    (12, "RESET_WATCHDOG after the reset (flag injected)", sc_watchdog_flag, dict(wdflag=True)),
    (13, "One read in ten fails: retried", sc_retry, {}),
    (14, "2 per cent of reads fail at random", sc_flaky, {}),
    (15, "Both attempts fail, one tick in nine: NO_DATA", sc_nodata, {}),
]
SCENARIOS += [
    (16, "No tick lost around a line", sc_timing, {}),
    (17, "Crystal never starts: watchdog resets", sc_crystal, dict(nohse=True, loglevel=2)),
    (18, "Pings close together and during a line", sc_pings, {}),
]
LONG_SCENARIOS = [
    (19, "Periodic WHO_AM_I check (128 s)", sc_long_id, {}),
]


def run_one(num, name, fn, opts, args, elf, port_base, idx):
    """run one scenario.  a Renode or harness problem (not a failed check) is retried once, because Renode
    occasionally stalls.  a scenario that still aborts is reported as aborted and counts as a failure of the
    run and the negative control does not count it as a caught mutant"""
    for attempt in range(2):
        r = Result(num, name)
        r.aborted = False
        t0 = time.time()
        sim = Sim("s%d_%d_%d" % (num, idx, attempt), elf, args.renode, args.mips,
                  (port_base + 2 * idx + 400 * attempt, port_base + 2 * idx + 1 + 400 * attempt),
                  loglevel=opts.get("loglevel", 3), step=args.step)
        # a scenario that takes far longer than any should is a stalled Renode: kill it so the call below fails
        limit = 900 if num == 19 else 420
        timer = threading.Timer(limit, sim.stop)
        timer.start()
        try:
            sim.start(unplug=opts.get("unplug", False), wdflag=opts.get("wdflag", False), nohse=opts.get("nohse", False))
            fn(sim, r)
        except Exception as e:                   # a harness or Renode problem is a failure, never a pass
            r.status = "FAIL"
            r.aborted = True
            r.checks.append((False, "scenario aborted: %r" % (e,)))
        finally:
            timer.cancel()
            sim.stop()
        r.finish()
        r.secs = time.time() - t0
        r.sim = sim
        if not r.aborted:
            break
    return r


def build_mutant(label, edits, workdir):
    """copy the firmware sources outside the repository, apply the edits and build with pio"""
    dst = os.path.join(workdir, label)
    shutil.copytree(FW_DIR, dst, ignore=shutil.ignore_patterns(".pio", "sim"))
    for rel, old, new in edits:
        p = os.path.join(dst, rel)
        s = open(p).read()
        if old not in s:
            raise RuntimeError("mutation target not found: %s in %s" % (old, rel))
        open(p, "w").write(s.replace(old, new, 1))
    out = subprocess.run(["pio", "run"], cwd=dst, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("mutant build failed: " + out.stdout[-500:] + out.stderr[-500:])
    return os.path.join(dst, ".pio", "build", "blackpill_f411ce", "firmware.elf")


# every scenario has at least one mutant that must make it fail.  each entry is (label, edits, scenarios that
# must FAIL), an edit being (file, old text, new text)
MUTANTS = [
    ("pll_wrong_n", [("Core/Src/main.c", "osc.PLL.PLLN       = 192U;", "osc.PLL.PLLN       = 191U;")], [1]),
    ("crc_init", [("Core/Src/crc16.c", "uint16_t crc = 0xFFFFU;", "uint16_t crc = 0x0000U;")], [2]),
    ("rms_keeps_mean", [("Core/Src/window_stats.c", "int64_t var_n2 = (int64_t)N_SAMPLES * sumsq - (int64_t)sum * (int64_t)sum;", "int64_t var_n2 = (int64_t)N_SAMPLES * sumsq;")], [2]),
    ("no_zero_line_when_lost", [("Core/Src/sensor_state.c", "return ZERO_LINE_MISSING;", "return ZERO_LINE_NONE;")], [3, 4]),
    ("lost_never_clears", [("Core/Src/node_core.c", "SensorState_OnWindowComplete(&n->sensor);", "")], [4]),
    ("lost_on_first_failure", [("Core/Inc/sensor_state.h", "#define MAX_CONSECUTIVE_FAILURES    5U", "#define MAX_CONSECUTIVE_FAILURES    1U")], [5]),
    ("stuck_never_found", [("Core/Src/window_stats.c", "out->stuck = all_equal(w->x) && all_equal(w->y) && all_equal(w->z);", "out->stuck = false;")], [6]),
    ("no_clipping", [("Core/Inc/imu_config.h", "#define IMU_RAW_FULL_SCALE_MAX  32767", "#define IMU_RAW_FULL_SCALE_MAX  40000")], [7]),
    ("id_never_mismatch", [("Core/Src/main.c", "Status_SetIdMismatch(&s_core.status, !IMU_IdIsExpected(id));", "Status_SetIdMismatch(&s_core.status, false);")], [8]),
    ("sleep_not_checked_on_stuck", [("Core/Src/main.c", "bin. */\n        Sensor_CheckAwake();", "bin. */\n        ;")], [9]),
    ("pong_wrong_number", [("Core/Src/main.c", "Line_BuildPong(pong, sizeof(pong), n);", "Line_BuildPong(pong, sizeof(pong), (uint16_t)(n + 1U));")], [10, 18]),
    ("watchdog_refreshed_for_ever", [("Core/Src/main.c", "if ((now - last_tick_ms) < TICK_STALE_MS)", "if (1)")], [11, 12]),
    ("reset_flag_ignored", [("Core/Src/status.c", "if (iwdg || wwdg)", "if (0)")], [12]),
    ("no_retry", [("Core/Src/sensor_state.c", "return (!first_ok) && (first_elapsed_ms <= QUICK_FAIL_MAX_MS);", "return false;")], [13, 14]),
    ("no_data_never", [("Core/Src/sensor_state.c", "if (s->ticks_since_window >= NO_DATA_TICKS)", "if (0)")], [15]),
    ("blocking_send", [("Core/Src/main.c", "(void)UART_QueueLine(s_line, len);", "(void)HAL_UART_Transmit(&huart1, (uint8_t *)s_line, (uint16_t)len, 100U); HAL_Delay(14U);")], [16]),
    ("pong_overwrites_in_flight", [("Core/Src/tx_queue.c", "&q->slot[(uint8_t)((q->head + q->count) % TX_SLOTS)];", "&q->slot[(uint8_t)((q->head + q->count + TX_SLOTS - 1U) % TX_SLOTS)];")], ["test_uart.c"]),
    ("line_skipped_while_pong_on_wire", [("Core/Src/tx_queue.c", "return q->count < TX_SLOTS;", "return (q->count < TX_SLOTS) && !q->in_flight;")], ["test_uart.c"]),
    ("overrun_not_restarted", [("Core/Src/uart_output.c", "    g_rx_errors++;\n    if (huart->RxState == HAL_UART_STATE_READY)", "    g_rx_errors++;\n    if (0)")], ["test_uart.c"]),
    ("watchdog_started_late", [("Core/Src/main.c", "    MX_IWDG_Init();\n\n    SystemClock_Config();", "    SystemClock_Config();"),
                               ("Core/Src/main.c", "(void)HAL_IWDG_Refresh(&hiwdg);\n\n    uint32_t missed_seen", "MX_IWDG_Init();\n\n    uint32_t missed_seen")], [17]),
    ("id_check_never_repeated", [("Core/Src/main.c", "#define IDENTITY_CHECK_WINDOWS      100U", "#define IDENTITY_CHECK_WINDOWS      100000U")], [19]),
]


def summary(results):
    print()
    print("%-3s %-42s %-8s %6s  %s" % ("#", "Scenario", "Result", "Wall s", "Checks"))
    print("-" * 90)
    for r in results:
        ok = sum(1 for c in r.checks if c[0])
        print("%-3s %-42s %-8s %6.0f  %d/%d" % (r.num, r.name, r.status, r.secs, ok, len(r.checks)))
    print("-" * 90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=DEFAULT_ELF)
    ap.add_argument("--renode", default=DEFAULT_RENODE)
    ap.add_argument("--only", type=int, action="append", help="scenario number, may be repeated")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--mips", type=int, default=8, help="simulated CPU speed (see README)")
    ap.add_argument("--step", type=float, default=0.05, help="simulated seconds per UART poll")
    ap.add_argument("--optional", type=int, action="append", default=[], help="scenario number that may be NOT RUN without failing the run")
    ap.add_argument("--long", action="store_true", help="also run the 128 s scenario")
    ap.add_argument("--negative-control", action="store_true", help="build mutated firmware outside the repository and require that the harness fails")
    ap.add_argument("--only-mutant", action="append", default=[], help="negative control: only this mutant, may be repeated")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.renode):
        print("Renode not found at %s (use --renode)" % args.renode)
        return 2
    os.makedirs(BUILD, exist_ok=True)
    port_base = 21000 + (os.getpid() % 400) * 40

    if args.negative_control:
        return negative_control(args, port_base)

    if not os.path.exists(args.elf):
        print("firmware ELF not found: %s (run pio run first)" % args.elf)
        return 2
    todo = [s for s in SCENARIOS + (LONG_SCENARIOS if args.long or (args.only and 19 in args.only) else []) if not args.only or s[0] in args.only]
    results = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(run_one, n, name, fn, o, args, args.elf, port_base, i) for i, (n, name, fn, o) in enumerate(todo)]
        for f in futs:
            r = f.result()
            results.append(r)
            print("[%s] %d %s (%.0f s)" % (r.status, r.num, r.name, r.secs), flush=True)
            for ok, msg in r.checks:
                if args.verbose or not ok:
                    print("    %s %s" % ("ok  " if ok else "FAIL", msg))
            for n in r.notes:
                print("    note: %s" % n)
            for fnd in r.findings:
                print("    FINDING: %s" % fnd)
    if not any(r.num == 19 for r in results) and not args.only:
        results.append(not_run(19, "Periodic WHO_AM_I check (128 s)", "slow: about 128 s of simulated time. run with --long"))
    summary(results)
    # a scenario that could not run is a failure of the run, unless it was named with --optional
    failed = [r for r in results if r.status == "FAIL" or (r.status == "NOT RUN" and r.num not in args.optional)]
    print("%d scenario(s): %d PASS, %d FAIL, %d FINDING, %d NOT RUN, %d SKIPPED" % (
        len(results), sum(r.status == "PASS" for r in results), sum(r.status == "FAIL" for r in results),
        sum(r.status == "FINDING" for r in results), sum(r.status == "NOT RUN" for r in results),
        sum(r.status == "SKIPPED" for r in results)))
    for r in failed:
        if r.status == "NOT RUN":
            print("NOT RUN counts as a failure: scenario %d (use --optional %d to allow it)" % (r.num, r.num))
    return 1 if failed else 0


def not_run(num, name, why):
    """a scenario left out by the command line: shown, but not a failure"""
    r = Result(num, name)
    r.status = "SKIPPED"
    r.notes.append(why)
    return r


def run_host_test(elf_path, test_file):
    """run the plain build line from the header of a host test inside a mutated copy of the sources.  elf_path is
    the firmware ELF path of that copy, which locates the copy"""
    copy = elf_path.split("/.pio/")[0]
    tdir = os.path.join(copy, "test_host")
    line = None
    for ln in open(os.path.join(tdir, test_file)):
        if ln.startswith(" *   cc "):
            line = ln[len(" *   "):].strip()
            break
    env = dict(os.environ, TMPDIR=tempfile.mkdtemp(prefix="hostmut_"))
    out = subprocess.run(["sh", "-c", line], cwd=tdir, capture_output=True, text=True, env=env)
    return out.returncode, out.stdout + out.stderr


def negative_control(args, port_base):
    work = tempfile.mkdtemp(prefix="blackpill_mutants_")
    print("building mutated firmware under %s (outside the repository)" % work)
    bad = 0
    table = {x[0]: x for x in SCENARIOS + LONG_SCENARIOS}
    built = {}
    for label, edits, must_fail in MUTANTS:
        if args.only_mutant and label not in args.only_mutant:
            continue
        try:
            built[label] = build_mutant(label, edits, work)
        except Exception as e:
            print("mutant %s: could not build: %s" % (label, e))
            bad += 1
    # host-test mutants: the named test, built from the mutated sources, must fail
    for label, edits, must_fail in MUTANTS:
        for n in must_fail:
            if isinstance(n, str) and label in built:
                rc, out = run_host_test(built[label], n)
                caught = rc != 0 and "FAILED" in out
                print("mutant %-28s host test %-18s -> %s" % (label, n, "FAILED as it must" if caught else "DID NOT CATCH IT"), flush=True)
                for ln in [x for x in out.splitlines() if x.startswith("FAIL")][:3]:
                    print("      %s" % ln[:150])
                if not caught:
                    bad += 1
    jobs = [(label, n) for label, edits, must_fail in MUTANTS if label in built for n in must_fail if not isinstance(n, str)]
    try:
        with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futs = [(label, n, ex.submit(run_one, n, table[n][1], table[n][2], table[n][3], args, built[label], port_base, i))
                    for i, (label, n) in enumerate(jobs)]
            for label, n, f in futs:
                r = f.result()
                caught = r.status == "FAIL" and not r.aborted
                print("mutant %-28s scenario %-2d %s -> harness %s" % (label, n, table[n][1], "FAILED as it must" if caught else "DID NOT CATCH IT (%s%s)" % (r.status, ", aborted" if r.aborted else "")), flush=True)
                for ok, msg in r.checks:
                    if not ok:
                        print("      %s" % msg[:160])
                if not caught:
                    bad += 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    covered = sorted({n for _, _, mf in MUTANTS for n in mf if not isinstance(n, str)})
    uncovered = [n for n in table if n not in covered]
    print("scenarios with a mutant: %s" % covered)
    print("host tests with a mutant: %s" % sorted({n for _, _, mf in MUTANTS for n in mf if isinstance(n, str)}))
    if uncovered:
        print("scenarios WITHOUT a mutant: %s" % uncovered)
        bad += 1
    print("negative control: %s" % ("every mutant was caught" if not bad else "%d problem(s)" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
