import json
import unittest

from tests import fakes

fakes.install()

import readings  # noqa: E402
import wifi_connect  # noqa: E402,F401  (imports against the fake network module)


class PayloadTests(unittest.TestCase):
    def test_payload_has_humidity_when_present(self):
        body = readings.build_payload(24.3, 61.234, 1012.8, 34816)
        self.assertEqual(body["humidity"], 61.23)

    def test_payload_omits_humidity_when_none(self):
        body = readings.build_payload(24.3, None, 1012.8, 34816)
        self.assertNotIn("humidity", body)
        self.assertNotIn("humidity", json.dumps(body))
        self.assertEqual(body["temperature"], 24.3)
        self.assertEqual(body["light_level"], 34816)


class ConversionTests(unittest.TestCase):
    def test_none_humidity_passes_through(self):
        self.assertEqual(readings.convert_reading(2430, 25600 * 1000, None),
                         (24.3, None, 1000.0))

    def test_humidity_is_scaled(self):
        self.assertEqual(readings.convert_reading(0, 0, 1024 * 50)[1], 50.0)


class DisplayTests(unittest.TestCase):
    def test_display_and_log_lines_without_humidity(self):
        lines = readings.display_lines(24.3, None, 1012.8, 34816)
        self.assertEqual(lines[0], "T:24.3C H:--")
        self.assertEqual(lines[1], "P:1012.8hPa")
        self.assertEqual(
            readings.log_line(201, 24.3, None, 1012.8, 34816),
            "POST OK (201) - T:24.3C H:-- P:1012.8hPa L:34816")

    def test_display_line_with_humidity(self):
        self.assertEqual(readings.display_lines(24.3, 61.2, 1012.8, 1)[0],
                         "T:24.3C H:61.2%")

    def test_placeholder_when_absent(self):
        self.assertEqual(readings.format_humidity(None), "--")

    def test_value_when_present(self):
        self.assertEqual(readings.format_humidity(61.234), "61.2%")


if __name__ == "__main__":
    unittest.main()
