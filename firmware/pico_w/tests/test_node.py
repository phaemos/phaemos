import base64
import json
import types
import unittest

from tests import fakes

fakes.install()

import node  # noqa: E402
import readings  # noqa: E402


def make_cert_pem(length=300):
    # a DER SEQUENCE header with a long-form length, then filler. It only has
    # to look like a certificate to the shape check.
    der = bytes([0x30, 0x82, length >> 8, length & 0xFF]) + bytes(length)
    return "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n-----END CERTIFICATE-----\n"


class FaultTests(unittest.TestCase):
    def test_all_good_has_no_faults(self):
        clean, faults = node.apply_faults(
            {"temperature": 20.0, "humidity": 40.0, "pressure": 1000.0, "light_level": 500}, {})
        self.assertEqual(faults, {})
        self.assertEqual(len(clean), 4)

    def test_failed_read_faults_sensor_and_drops_its_fields(self):
        clean, faults = node.apply_faults({"light_level": 5}, {"bme280": "missing"})
        self.assertEqual(faults, {"bme280": "missing"})
        self.assertEqual(clean, {"light_level": 5})

    def test_out_of_range_drops_the_whole_sensor(self):
        clean, faults = node.apply_faults(
            {"temperature": 120.0, "humidity": 40.0, "pressure": 1000.0, "light_level": 5}, {})
        self.assertEqual(faults, {"bme280": "out_of_range"})
        self.assertNotIn("humidity", clean)

    def test_nan_is_out_of_range(self):
        _, faults = node.apply_faults({"temperature": float("nan"), "pressure": 1000.0}, {})
        self.assertEqual(faults, {"bme280": "out_of_range"})

    def test_bmp280_missing_humidity_is_not_a_fault(self):
        clean, faults = node.apply_faults(
            {"temperature": 20.0, "humidity": None, "pressure": 1000.0, "light_level": 1}, {})
        self.assertEqual(faults, {})
        self.assertNotIn("humidity", clean)

    def test_fault_keys_exist_in_the_backend_sensor_map(self):
        import os
        import re
        path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "app",
                            "services", "sensor_map.py")
        if not os.path.exists(path):
            self.skipTest("backend not in this checkout")
        text = open(path).read()
        for key in node.SENSOR_RANGES:
            self.assertTrue(re.search(r'^\s*"%s":' % key, text, re.M), key)


class BootCounterTests(unittest.TestCase):
    def run_boot(self, stored, write_ok=True):
        written = []

        def read():
            if stored is None:
                raise OSError(2)
            return stored

        def write(text):
            if not write_ok:
                raise OSError(5)
            written.append(text)

        return node.next_boot(read, write), written

    def test_first_boot_is_one(self):
        self.assertEqual(self.run_boot(None), ((1, True), ["1"]))

    def test_counts_up_from_the_file(self):
        self.assertEqual(self.run_boot("41\n"), ((42, True), ["42"]))

    def test_unusable_file_gives_no_boot(self):
        for stored in ("garbage", "-3", str(node.MAX_BOOT), "99999999999"):
            self.assertEqual(self.run_boot(stored)[0], (None, False), stored)

    def test_unwritable_file_gives_no_boot_and_never_a_repeat(self):
        self.assertEqual(self.run_boot("41", write_ok=False)[0], (None, False))

    def test_clock_boot_rises_and_is_capped(self):
        self.assertEqual(node.clock_boot(1793491200), 1793491200)
        self.assertGreater(node.clock_boot(1793491201), node.clock_boot(1793491200))
        self.assertEqual(node.clock_boot(5_000_000_000), node.MAX_BOOT)
        # a clock boot is above any small counter, so the move to it is a rise
        self.assertGreater(node.clock_boot(1793491200), 1_000_000)

    def test_clock_boot_never_exceeds_the_servers_limit(self):
        for t in (0, 2 ** 31 - 1, 2 ** 31, 2 ** 40):
            self.assertLessEqual(node.clock_boot(t), 2147483647)

    def test_boot_sequence_is_strictly_newer_through_a_failure_and_recovery(self):
        # counter 1, 2, 3, then the file breaks (clock boots), then it is
        # rewritten from the last clock boot and carries on above it
        sent = []
        store = {"v": None, "ok": True}

        def read():
            if store["v"] is None:
                raise OSError(2)
            return store["v"]

        def write(text):
            if not store["ok"]:
                raise OSError(5)
            store["v"] = text

        for _ in range(3):
            sent.append(node.next_boot(read, write)[0])
        store["ok"] = False
        for clock in (1793500000, 1793500100):
            self.assertIsNone(node.next_boot(read, write)[0])
            sent.append(node.clock_boot(clock))
        store["ok"] = True
        store["v"] = str(sent[-1])  # the node persisted its clock boot once writes worked
        sent.append(node.next_boot(read, write)[0])
        self.assertEqual(sent, sorted(set(sent)))


class ResetCountTests(unittest.TestCase):
    def run_count(self, stored, was_watchdog):
        writes = []

        def read():
            if stored is None:
                raise OSError(2)
            return stored

        return node.next_reset_count(read, writes.append, was_watchdog), writes

    def test_power_on_with_no_file_writes_nothing(self):
        self.assertEqual(self.run_count(None, False), (0, []))

    def test_watchdog_resets_count_up(self):
        self.assertEqual(self.run_count(None, True), (1, ["1"]))
        self.assertEqual(self.run_count("2", True), (3, ["3"]))

    def test_other_reset_clears_a_count(self):
        self.assertEqual(self.run_count("4", False), (0, ["0"]))

    def test_unwritable_marker_does_not_stop_the_node(self):
        def write(_):
            raise OSError(5)
        self.assertEqual(node.next_reset_count(lambda: "1", write, True), 2)

    def test_count_is_capped_and_garbage_is_zero(self):
        self.assertEqual(self.run_count("1000", True)[0], 101)
        self.assertEqual(self.run_count("x", True)[0], 1)

    def test_writes_per_day_stay_small_in_a_reset_loop(self):
        # each boot waits backoff_delay(count) before its first post. The
        # post then hangs for the watchdog period (8 s): one write per cycle
        t, writes, count = 0, 0, 0
        while t < 86400:
            count += 1
            writes += 1
            t += node.backoff_delay(count, 5, 300) + 8
        self.assertLess(writes, 300)


class BackoffTests(unittest.TestCase):
    def test_doubles_then_caps(self):
        self.assertEqual([node.backoff_delay(n, 5, 300) for n in range(1, 9)],
                         [5, 10, 20, 40, 80, 160, 300, 300])

    def test_huge_failure_count_is_safe(self):
        self.assertEqual(node.backoff_delay(10 ** 9, 5, 300), 300)

    def pacer(self):
        return node.Pacer(5, 300, 300, 3600, 3600)

    def test_success_resets(self):
        p = self.pacer()
        p.on_result(500)
        p.on_result(500)
        self.assertEqual(p.on_result(201), 5)
        self.assertEqual(p.on_result(500), 5)

    def test_401_backs_off_hard_and_grows(self):
        p = self.pacer()
        self.assertEqual([p.on_result(401) for _ in range(6)], [300, 600, 1200, 2400, 3600, 3600])

    def test_429_honours_retry_after_and_clamps_it(self):
        p = self.pacer()
        self.assertEqual(p.on_result(429, "120"), 120)
        self.assertEqual(p.on_result(429, "99999"), 3600)
        self.assertEqual(p.on_result(429, "1"), 5)
        self.assertEqual(p.on_result(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 60)
        self.assertEqual(p.on_result(429, None), 60)

    def test_429_does_not_count_as_a_failure(self):
        p = self.pacer()
        p.on_result(429, "30")
        self.assertEqual(p.on_result(500), 5)

    def test_transport_failure_doubles(self):
        p = self.pacer()
        self.assertEqual([p.on_result(-1) for _ in range(3)], [5, 10, 20])


class BodyTests(unittest.TestCase):
    def test_health_fields_and_json(self):
        body = node.build_body("dev-1", {"temperature": 21.5, "pressure": 1001.0, "light_level": 9},
                               {"bme280": "missing"}, 3, 7, 120, 1790000000, "watchdog", 90000)
        self.assertEqual((body["seq"], body["boot"], body["up"], body["fw"]), (3, 7, 120, node.FW_VERSION))
        self.assertEqual(body["faults"], {"bme280": "missing"})
        self.assertEqual(body["ts"], 1790000000)
        self.assertEqual(body["reset_reason"], "watchdog")
        json.dumps(body)

    def test_no_faults_key_when_empty_and_no_ts_before_clock(self):
        body = node.build_body("d", {"light_level": 1}, {}, 0, 1, 0)
        self.assertNotIn("faults", body)
        self.assertNotIn("ts", body)
        self.assertEqual(body["device_id"], "d")


class StartupTests(unittest.TestCase):
    def cfg(self, **kw):
        base = dict(WIFI_SSID="net", WIFI_PASS="pw", API_BASE_URL="https://api.example.org",
                    DEVICE_ID="d1", API_KEY="k", ALLOW_PLAIN_HTTP=False, ROOT_CA_FILE="root_ca.pem")
        base.update(kw)
        return types.SimpleNamespace(**base)

    def reader(self, text):
        def read(path):
            if text is None:
                raise OSError(2)
            return text
        return read

    def test_good_config_has_no_problems(self):
        self.assertEqual(node.startup_problems(self.cfg(), self.reader(make_cert_pem())), [])

    def test_placeholders_are_named(self):
        problems = node.startup_problems(
            self.cfg(WIFI_PASS="CHANGE_ME", API_KEY="", DEVICE_ID="CHANGE_ME"), self.reader(make_cert_pem()))
        text = " ".join(problems)
        for name in ("WIFI_PASS", "API_KEY", "DEVICE_ID"):
            self.assertIn(name, text)
        self.assertNotIn("WIFI_SSID", text)

    def test_default_config_module_is_all_placeholders(self):
        import config
        problems = node.startup_problems(config, self.reader(make_cert_pem()))
        self.assertEqual(len(problems), 5)

    def test_placeholder_certificate_blocks_https(self):
        placeholder = open(fakes.PICO_DIR + "/root_ca.pem").read()
        problems = node.startup_problems(self.cfg(), self.reader(placeholder))
        self.assertEqual(len(problems), 1)
        self.assertIn("root_ca.pem", problems[0])

    def test_missing_certificate_file_blocks_https(self):
        self.assertEqual(len(node.startup_problems(self.cfg(), self.reader(None))), 1)

    def test_plain_http_needs_the_flag(self):
        cfg = self.cfg(API_BASE_URL="http://192.168.1.5:8000")
        self.assertEqual(len(node.startup_problems(cfg, self.reader(None))), 1)
        cfg = self.cfg(API_BASE_URL="http://192.168.1.5:8000", ALLOW_PLAIN_HTTP=True)
        self.assertEqual(node.startup_problems(cfg, self.reader(None)), [])

    def test_other_schemes_are_refused(self):
        problems = node.startup_problems(self.cfg(API_BASE_URL="ftp://x"), self.reader(None))
        self.assertTrue(problems)

    def test_crlf_or_space_in_settings_is_refused(self):
        for name in ("API_KEY", "DEVICE_ID"):
            for bad in ("k\r\nX-Evil: 1", "a b", "k\x7f", "caf\u00e9"):
                problems = node.startup_problems(self.cfg(**{name: bad}), self.reader(make_cert_pem()))
                self.assertTrue(any(name in p for p in problems), (name, bad))

    def test_bad_host_in_the_address_is_refused(self):
        for url in ("https://api.example.org\r\nX-Evil: 1", "https://a b.example", "https://h:80x/"):
            self.assertTrue(node.startup_problems(self.cfg(API_BASE_URL=url), self.reader(make_cert_pem())), url)

    def test_pem_to_ders_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            node.pem_to_ders("nothing here")
        with self.assertRaises(ValueError):
            node.pem_to_ders("-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----")
        with self.assertRaises(ValueError):
            node.pem_to_ders("-----BEGIN CERTIFICATE-----\nAAAA")
        self.assertEqual([len(d) for d in node.pem_to_ders(make_cert_pem(300))], [304])

    def test_a_file_with_two_roots_gives_both(self):
        ders = node.pem_to_ders(make_cert_pem(300) + "\n" + make_cert_pem(400))
        self.assertEqual([len(d) for d in ders], [304, 404])

    def test_one_bad_certificate_in_a_file_spoils_it(self):
        bad = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"
        with self.assertRaises(ValueError):
            node.pem_to_ders(make_cert_pem(300) + bad)

    def test_clock_plausible(self):
        self.assertFalse(node.clock_plausible(0, 1793491200, 4102444800))
        self.assertFalse(node.clock_plausible(1793491199, 1793491200, 4102444800))
        self.assertTrue(node.clock_plausible(1795000000, 1793491200, 4102444800))
        self.assertFalse(node.clock_plausible(4102444801, 1793491200, 4102444800))


class FakeHardware:
    def __init__(self):
        self.t = 0
        self.bme = (21.0, 40.0, 1000.0)
        self.ldr = 100
        self.wifi = True
        self.wifi_can_connect = True
        self.clock = True
        self.replies = []
        self.posts = []
        self.feed_times = []
        self.shown = []
        self.resets = 0
        self.saved_boot = []
        self.save_ok = True
        self.marker_cleared = 0
        self.syncs = 0

    def ticks_ms(self):
        return self.t & 0x3FFFFFFF  # MicroPython's tick counter wraps

    def ticks_diff(self, a, b):
        return ((a - b + (1 << 29)) & 0x3FFFFFFF) - (1 << 29)

    def feed(self):
        self.feed_times.append(self.t)

    def read_bme(self):
        if isinstance(self.bme, Exception):
            raise self.bme
        return self.bme

    def read_ldr(self):
        if isinstance(self.ldr, Exception):
            raise self.ldr
        return self.ldr

    def show(self, lines):
        self.shown.append(lines)

    def wifi_connected(self):
        return self.wifi

    def wifi_connect(self):
        self.wifi = self.wifi_can_connect
        return self.wifi

    def sync_clock(self):
        self.syncs += 1
        return self.clock

    def unix_time(self):
        return 1795000000 + self.t // 1000 if self.clock else None

    def reset_reason(self):
        return "poweron"

    def heap_free(self):
        return 1000

    def save_boot(self, boot):
        if self.save_ok:
            self.saved_boot.append(boot)
        return self.save_ok

    def clear_reset_marker(self):
        self.marker_cleared += 1

    def post(self, body):
        self.posts.append(body)
        # a post is a few steps and the real one feeds between them
        self.feed()
        self.t += 1500
        self.feed()
        reply = self.replies.pop(0) if self.replies else (201, None)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def reset(self):
        self.resets += 1


def make_cfg(url="https://api.example.org", key="SECRET-KEY-VALUE"):
    return types.SimpleNamespace(
        API_BASE_URL=url, DEVICE_ID="d1", API_KEY=key, TELEMETRY_INTERVAL=5, BACKOFF_CAP_S=300,
        AUTH_BACKOFF_START_S=300, AUTH_BACKOFF_CAP_S=3600, RETRY_AFTER_MAX_S=3600,
        RESYNC_INTERVAL_S=86400, CLOCK_FAIL_LIMIT=3)


def make_node(hw, url="https://api.example.org", boot=4, reset_count=0):
    return node.Node(hw, make_cfg(url), boot, True, reset_count)


def run(n, secs):
    # advance simulated time one second per pass, as the real loop does
    for _ in range(secs):
        n.step()
        n.hw.t += 1000


class AddressTests(unittest.TestCase):
    def test_trailing_slashes_are_stripped_and_no_request_has_a_double_slash(self):
        import http_post
        for url in ("https://api.example.org", "https://api.example.org/", "https://api.example.org///"):
            full = node.base_address(url) + "/api/v1/telemetry"
            self.assertEqual(http_post.parse_url(full), ("https", "api.example.org", 443, "/api/v1/telemetry"))
            self.assertNotIn("//", full[len("https://"):])

    def test_a_full_ingest_address_is_refused_with_a_plain_message(self):
        for url in ("https://h/api/v1/telemetry", "https://h/api/v1/telemetry/", "https://h/api/v1/", "http://10.0.0.2:8000/x"):
            message = node.address_problem(url)
            self.assertIn("base address only", message, url)
            self.assertIn("Remove the path", message)
        for url in ("https://h", "https://h/", "http://10.0.0.2:8000/", "https://h:8443//"):
            self.assertIsNone(node.address_problem(url), url)

    def test_startup_refuses_the_full_address_and_accepts_a_trailing_slash(self):
        cfg = types.SimpleNamespace(WIFI_SSID="n", WIFI_PASS="p", API_BASE_URL="https://h/api/v1/telemetry/", DEVICE_ID="d",
                                    API_KEY="k", ALLOW_PLAIN_HTTP=False, ROOT_CA_FILE="root_ca.pem")
        pem = make_cert_pem()
        problems = node.startup_problems(cfg, lambda path: pem)
        self.assertEqual(len(problems), 1)
        self.assertIn("base address only", problems[0])
        cfg.API_BASE_URL = "https://h/"
        self.assertEqual(node.startup_problems(cfg, lambda path: pem), [])


class NotFoundTests(unittest.TestCase):
    def test_a_404_backs_off_like_a_refused_key(self):
        p = node.Pacer(5, 300, 300, 3600, 3600)
        self.assertEqual([p.on_result(404) for _ in range(4)], [300, 600, 1200, 2400])
        self.assertEqual(p.on_result(201), 5)

    def test_a_404_is_reported_once_and_not_retried_every_few_seconds(self):
        import contextlib
        import io
        hw = FakeHardware()
        hw.replies = [(404, None)] * 3
        n = make_node(hw)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run(n, 299)
            self.assertEqual(len(hw.posts), 1)
            run(n, 4)
            self.assertEqual(len(hw.posts), 2)
        self.assertEqual(out.getvalue().count("API_BASE_URL is wrong"), 1)
        self.assertEqual(n.status_line, "BAD ADDRESS")


class LoopTests(unittest.TestCase):
    def test_posts_on_interval_with_increasing_seq(self):
        hw = FakeHardware()
        n = make_node(hw)
        run(n, 16)
        self.assertEqual([b["seq"] for b in hw.posts], [0, 1, 2, 3])
        self.assertTrue(all(b["boot"] == 4 for b in hw.posts))
        self.assertTrue(hw.posts[-1]["up"] >= 15)

    def test_sensor_read_that_raises_does_not_stop_the_loop(self):
        hw = FakeHardware()
        hw.bme = OSError(5)
        hw.ldr = RuntimeError("adc")
        n = make_node(hw)
        run(n, 6)
        self.assertEqual(hw.posts[0]["faults"], {"bme280": "missing", "ldr": "missing"})
        self.assertNotIn("temperature", hw.posts[0])

    def test_display_failure_does_not_stop_the_loop(self):
        hw = FakeHardware()
        hw.show = lambda lines: (_ for _ in ()).throw(OSError(5))
        n = make_node(hw)
        run(n, 6)
        self.assertGreaterEqual(len(hw.posts), 1)

    def test_failed_posts_back_off_then_recover(self):
        hw = FakeHardware()
        hw.replies = [(500, None), (500, None), (500, None)]
        n = make_node(hw)
        run(n, 60)
        self.assertEqual([b["seq"] for b in hw.posts][:5], [0, 1, 2, 3, 4])
        self.assertEqual(n.pacer.failures, 0)

    def test_seq_is_not_reused_after_a_failed_post(self):
        hw = FakeHardware()
        hw.replies = [OSError("boom"), (201, None)]
        n = make_node(hw)
        run(n, 20)
        self.assertEqual([b["seq"] for b in hw.posts][:2], [0, 1])

    def test_401_waits_five_minutes_then_doubles(self):
        hw = FakeHardware()
        hw.replies = [(401, None), (401, None)]
        n = make_node(hw)
        run(n, 299)
        self.assertEqual(len(hw.posts), 1)
        run(n, 4)
        self.assertEqual(len(hw.posts), 2)
        run(n, 590)
        self.assertEqual(len(hw.posts), 2)
        run(n, 8)
        self.assertEqual(len(hw.posts), 3)

    def test_409_backs_off_like_a_401_and_says_what_it_means(self):
        import io
        import contextlib
        hw = FakeHardware()
        hw.replies = [(409, None), (409, None)]
        n = make_node(hw)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run(n, 299)
            self.assertEqual(len(hw.posts), 1)
            run(n, 4)
            self.assertEqual(len(hw.posts), 2)
        self.assertIn("older than the last it accepted", out.getvalue())
        self.assertIn("admin must accept a new counter", out.getvalue())
        self.assertEqual(n.status_line, "COUNTER OLD")

    def test_duplicate_200_is_delivered(self):
        hw = FakeHardware()
        hw.replies = [(200, None)]
        n = make_node(hw)
        run(n, 4)
        self.assertEqual(n.pacer.failures, 0)
        self.assertEqual(n.status_line, "POST OK")

    def test_429_waits_for_retry_after(self):
        hw = FakeHardware()
        hw.replies = [(429, "40")]
        n = make_node(hw)
        run(n, 39)
        self.assertEqual(len(hw.posts), 1)
        run(n, 3)
        self.assertEqual(len(hw.posts), 2)

    def test_wifi_reconnect_then_post(self):
        hw = FakeHardware()
        hw.wifi = False
        hw.wifi_can_connect = False
        n = make_node(hw)
        run(n, 3)
        self.assertEqual(hw.posts, [])
        hw.wifi_can_connect = True
        run(n, 15)
        self.assertGreaterEqual(len(hw.posts), 1)

    def test_https_waits_for_the_clock(self):
        hw = FakeHardware()
        hw.clock = False
        n = make_node(hw)
        run(n, 8)
        self.assertEqual(hw.posts, [])
        hw.clock = True
        run(n, 20)
        self.assertGreaterEqual(len(hw.posts), 1)
        self.assertIn("ts", hw.posts[0])

    def test_plain_http_posts_without_the_clock_announces_and_marks_the_body(self):
        import io
        import contextlib
        hw = FakeHardware()
        hw.clock = False
        n = make_node(hw, url="http://10.0.0.2:8000")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n.announce()
            run(n, 6)
        self.assertIn("PLAIN HTTP", out.getvalue())
        self.assertGreaterEqual(len(hw.posts), 1)
        self.assertNotIn("ts", hw.posts[0])
        self.assertIs(hw.posts[0]["plain_http"], True)
        self.assertEqual(hw.shown[-1][-1], "PLAIN HTTP!")

    def test_https_mode_has_no_plain_marker(self):
        hw = FakeHardware()
        n = make_node(hw)
        run(n, 6)
        self.assertNotIn("plain_http", hw.posts[0])
        self.assertNotIn("PLAIN HTTP!", hw.shown[-1])

    def test_uptime_survives_tick_wrap(self):
        hw = FakeHardware()
        hw.t = (1 << 30) - 3000
        n = make_node(hw)
        run(n, 10)
        self.assertGreaterEqual(n.up_s, 9)

    def test_no_gap_between_feeds_is_longer_than_the_slowest_step(self):
        hw = FakeHardware()
        n = make_node(hw)
        run(n, 30)
        gaps = [b - a for a, b in zip(hw.feed_times, hw.feed_times[1:])]
        # a pass is 1000 ms of sleep (fed in slices by the real hardware)
        # around a post of two 1500 ms steps
        self.assertLessEqual(max(gaps), 1500 + 1000)

    def test_key_value_never_appears_in_output_or_body(self):
        import io
        import contextlib
        hw = FakeHardware()
        hw.replies = [(401, None), OSError("boom"), (409, None)]
        n = make_node(hw)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n.announce()
            run(n, 700)
        self.assertNotIn("SECRET-KEY-VALUE", out.getvalue())
        self.assertNotIn("SECRET-KEY-VALUE", json.dumps(hw.posts))

    # ---- boot from the clock ----
    def test_unusable_boot_file_takes_boot_from_the_clock_and_waits_for_it(self):
        hw = FakeHardware()
        hw.clock = False
        n = node.Node(hw, make_cfg(), None, False)
        run(n, 12)
        self.assertEqual(hw.posts, [])  # never posts without a usable boot
        hw.clock = True
        run(n, 12)
        self.assertGreaterEqual(len(hw.posts), 1)
        boot = hw.posts[0]["boot"]
        self.assertTrue(1793491200 <= boot <= node.MAX_BOOT)
        self.assertEqual(hw.saved_boot[0], boot)
        self.assertTrue(all(b["boot"] == boot for b in hw.posts))

    def test_unusable_boot_file_in_plain_mode_still_waits_for_the_clock(self):
        hw = FakeHardware()
        hw.clock = False
        n = node.Node(hw, make_cfg("http://10.0.0.2:8000"), None, False)
        run(n, 12)
        self.assertEqual(hw.posts, [])

    def test_clock_boot_is_stored_again_after_a_good_post_when_writes_failed(self):
        hw = FakeHardware()
        hw.save_ok = False
        n = node.Node(hw, make_cfg(), None, False)
        run(n, 6)
        self.assertEqual(hw.saved_boot, [])
        hw.save_ok = True
        run(n, 12)
        self.assertEqual(hw.saved_boot, [n.boot])

    # ---- the clock ----
    def test_three_posts_in_a_row_that_never_completed_clear_the_clock(self):
        hw = FakeHardware()
        hw.replies = [OSError("tls"), OSError("tls"), OSError("tls")]
        n = make_node(hw)
        run(n, 120)
        self.assertGreaterEqual(hw.syncs, 2)  # the first and the one after the third failure

    def test_a_server_error_does_not_clear_the_clock(self):
        hw = FakeHardware()
        hw.replies = [(500, None)] * 5
        n = make_node(hw)
        run(n, 600)
        self.assertEqual(hw.syncs, 1)

    def test_clock_is_set_again_daily(self):
        hw = FakeHardware()
        n = make_node(hw)
        run(n, 3)
        before = hw.syncs
        n.next_post_ms = 0
        hw.t += 86400 * 1000
        run(n, 6)
        self.assertGreater(hw.syncs, before)

    def test_failed_daily_resync_keeps_posting(self):
        hw = FakeHardware()
        n = make_node(hw)
        run(n, 3)
        hw.clock = False
        hw.t += 86400 * 1000
        n.next_post_ms = 0
        before = len(hw.posts)
        run(n, 8)
        self.assertGreater(len(hw.posts), before)

    # ---- reset marker ----
    def test_watchdog_resets_in_a_row_delay_the_first_post(self):
        hw = FakeHardware()
        n = make_node(hw, reset_count=4)  # 5, 10, 20, 40 -> 40 s
        run(n, 39)
        self.assertEqual(hw.posts, [])
        run(n, 4)
        self.assertEqual(len(hw.posts), 1)

    def test_first_good_post_clears_the_marker_once(self):
        hw = FakeHardware()
        n = make_node(hw, reset_count=1)
        run(n, 30)
        self.assertEqual(hw.marker_cleared, 1)

    def test_no_marker_write_for_a_healthy_node(self):
        hw = FakeHardware()
        n = make_node(hw)
        run(n, 30)
        self.assertEqual(hw.marker_cleared, 0)


if __name__ == "__main__":
    unittest.main()
