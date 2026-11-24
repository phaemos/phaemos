import unittest

from tests import fakes

fakes.install()

import bme280  # noqa: E402


class ChipIdTests(unittest.TestCase):
    def test_bme280_id_gives_humidity(self):
        sensor = bme280.BME280(fakes.FakeBus(0x60))
        temp, pres, hum = sensor.read_compensated_data()
        self.assertIsInstance(hum, int)
        self.assertTrue(0 <= hum / 1024.0 <= 100)
        self.assertEqual(temp, 2508)
        self.assertAlmostEqual(pres / 256.0, 100653, delta=1)

    def test_bmp280_id_gives_none(self):
        sensor = bme280.BME280(fakes.FakeBus(0x58))
        temp, pres, hum = sensor.read_compensated_data()
        self.assertIsNone(hum)
        self.assertEqual(temp, 2508)
        self.assertAlmostEqual(pres / 256.0, 100653, delta=1)

    def test_bmp280_reads_six_data_bytes_and_no_humidity_registers(self):
        bus = fakes.FakeBus(0x58)
        bme280.BME280(bus).read_compensated_data()
        self.assertIn((0xF7, 6), bus.reads)
        self.assertNotIn((0xF7, 8), bus.reads)
        read_regs = [reg for reg, _ in bus.reads]
        self.assertNotIn(0xA1, read_regs)
        self.assertNotIn(0xE1, read_regs)

    def test_bmp280_skips_humidity_register(self):
        bus = fakes.FakeBus(0x58)
        bme280.BME280(bus)
        self.assertNotIn(0xF2, [reg for reg, _ in bus.writes])

    def test_bme280_writes_humidity_register(self):
        bus = fakes.FakeBus(0x60)
        bme280.BME280(bus)
        self.assertIn(0xF2, [reg for reg, _ in bus.writes])

    def test_unknown_id_raises_clean_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            bme280.BME280(fakes.FakeBus(0x00))
        self.assertIn("0x00", str(ctx.exception))

    def test_temperature_and_pressure_match_across_chips(self):
        bme = bme280.BME280(fakes.FakeBus(0x60)).read_compensated_data()
        bmp = bme280.BME280(fakes.FakeBus(0x58)).read_compensated_data()
        self.assertEqual(bme[:2], bmp[:2])


if __name__ == "__main__":
    unittest.main()
