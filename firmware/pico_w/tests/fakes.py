# small stand-ins for the MicroPython-only modules so the firmware imports on
# a desktop Python.  install() must run before importing the firmware modules.

import os
import sys
import types

PICO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakePin:
    def __init__(self, pin, *args, **kwargs):
        self.pin = pin


class FakeADC:
    def __init__(self, pin):
        self.pin = pin

    def read_u16(self):
        return 0


class FakeI2C:
    def __init__(self, *args, **kwargs):
        pass


class FakeWLAN:
    def __init__(self, interface):
        self.interface = interface

    def active(self, state=None):
        return True

    def isconnected(self):
        return True


def install():
    machine = types.ModuleType("machine")
    machine.Pin = FakePin
    machine.ADC = FakeADC
    machine.I2C = FakeI2C
    sys.modules["machine"] = machine

    network = types.ModuleType("network")
    network.STA_IF = 0
    network.WLAN = FakeWLAN
    sys.modules["network"] = network

    if PICO_DIR not in sys.path:
        sys.path.insert(0, PICO_DIR)


class FakeBus:
    """I2C bus stand-in that serves register reads from a dict of bytes."""

    def __init__(self, chip_id):
        self.regs = {}
        self.writes = []
        self.reads = []
        self.regs[0xD0] = chip_id
        # Bosch datasheet example calibration data (BMP280 section 3.12)
        calib = [0x70, 0x6B, 0x43, 0x67, 0x18, 0xFC, 0x7D, 0x8E, 0x43, 0xD6,
                 0xD0, 0x0B, 0x27, 0x0B, 0x8C, 0x00, 0xF9, 0xFF, 0x8C, 0x3C,
                 0xF8, 0xC6, 0x70, 0x17]
        for i, b in enumerate(calib):
            self.regs[0x88 + i] = b
        # raw sample from the same example: pressure then temperature
        for i, b in enumerate([0x65, 0x5A, 0xC0, 0x7E, 0xED, 0x00]):
            self.regs[0xF7 + i] = b
        # a BMP280 has no humidity calibration or humidity data, so those
        # registers only exist on the fake when it stands in for a BME280.
        if chip_id == 0x60:
            self.regs[0xA1] = 0x4B
            for i, b in enumerate([0x6B, 0x01, 0x00, 0x13, 0x2A, 0x03, 0x1E]):
                self.regs[0xE1 + i] = b
            self.regs[0xFD] = 0x6E
            self.regs[0xFE] = 0x40

    def readfrom_mem(self, addr, reg, count):
        self.reads.append((reg, count))
        return bytes(self.regs.get(reg + i, 0) for i in range(count))

    def writeto_mem(self, addr, reg, data):
        self.writes.append((reg, bytes(data)))
