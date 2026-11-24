import contextlib
import io
import unittest

from tests import fakes

fakes.install()

import http_post  # noqa: E402


class Clock:
    """A fake tick counter that advances when a fake stream is read."""

    def __init__(self):
        self.now = 0
        self.feeds = []

    def ticks_ms(self):
        return self.now

    def ticks_diff(self, a, b):
        return a - b

    def feed(self):
        self.feeds.append(self.now)

    def max_gap(self):
        gaps = [b - a for a, b in zip(self.feeds, self.feeds[1:])]
        return max(gaps) if gaps else 0


class FakeConn:
    """A stream with read(n). `drip` is a (bytes per read, ms per read) pair and
    `endless` makes the stream never end."""

    def __init__(self, reply, clock=None, per_read=(None, 0), endless=None, fail_on_write=None, fail_on_read=None):
        self.data = reply
        self.pos = 0
        self.clock = clock
        self.per_read = per_read
        self.endless = endless
        self.written = b""
        self.closed = False
        self.fail_on_write = fail_on_write
        self.fail_on_read = fail_on_read
        self.taken = 0
        self.reads = 0

    def write(self, data):
        if self.fail_on_write:
            raise self.fail_on_write
        self.written += data

    def read(self, n):
        self.reads += 1
        if self.fail_on_read:
            raise self.fail_on_read
        limit, cost = self.per_read
        if self.clock is not None:
            self.clock.now += cost
        if limit is not None:
            n = min(n, limit)
        if self.endless is not None:
            self.taken += n
            return self.endless * n
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        self.taken += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class UrlTests(unittest.TestCase):
    def test_https_default_port(self):
        self.assertEqual(http_post.parse_url("https://api.example.org/api/v1/telemetry"),
                         ("https", "api.example.org", 443, "/api/v1/telemetry"))

    def test_http_with_port_and_no_path(self):
        self.assertEqual(http_post.parse_url("http://10.0.0.2:8000"), ("http", "10.0.0.2", 8000, "/"))

    def test_bad_addresses(self):
        bad = ("ftp://x", "https://", "https://user:pw@host/", "http://h:99999/", "http://h:abc/", "host",
               "http://h:/", "http://h:80x/", "http://h:+80/", "http://h: 80/", "http://h:80:81/")
        for url in bad:
            with self.assertRaises(ValueError, msg=url):
                http_post.parse_url(url)

    def test_host_with_crlf_space_or_odd_characters_is_refused(self):
        for host in ("api.example.org\r\nX-Evil: 1", "api example.org", "api.example.org\t", "ex_ample.org",
                     "api.example.org\x00", "[::1]", "caf\u00e9.example", "a?b"):
            with self.assertRaises(ValueError, msg=repr(host)):
                http_post.parse_url("https://" + host + "/x")

    def test_path_with_a_control_character_or_space_is_refused(self):
        for path in ("/a b", "/a\r\nX: 1", "/a\x7f", "/a\u00e9"):
            with self.assertRaises(ValueError, msg=repr(path)):
                http_post.parse_url("https://h" + path)


class RequestTests(unittest.TestCase):
    def test_request_shape(self):
        req = http_post.build_request("api.example.org", 443, "https", "/t", '{"a":1}', "KEY")
        head, _, body = req.partition(b"\r\n\r\n")
        self.assertEqual(body, b'{"a":1}')
        lines = head.decode().split("\r\n")
        self.assertEqual(lines[0], "POST /t HTTP/1.0")
        self.assertIn("Host: api.example.org", lines)
        self.assertIn("X-API-Key: KEY", lines)
        self.assertIn("Content-Length: 7", lines)

    def test_host_header_keeps_a_non_default_port(self):
        req = http_post.build_request("h", 8000, "http", "/", "{}", "k")
        self.assertIn(b"Host: h:8000\r\n", req)

    def test_a_key_that_could_add_a_header_is_refused(self):
        for key in ("k\r\nX-Evil: 1", "k\nX", "a b", "", "k\x00", "k\x7f", "k\u00e9"):
            with self.assertRaises(ValueError, msg=repr(key)):
                http_post.build_request("h", 443, "https", "/", "{}", key)

    def test_a_request_never_holds_a_second_header_block(self):
        req = http_post.build_request("h", 443, "https", "/", "{}", "abc")
        self.assertEqual(req.count(b"\r\n\r\n"), 1)


class StatusTests(unittest.TestCase):
    def test_good_lines(self):
        self.assertEqual(http_post.parse_status_line("HTTP/1.1 201 Created"), 201)
        self.assertEqual(http_post.parse_status_line("HTTP/1.0 429"), 429)

    def test_cut_or_garbled_lines_are_refused(self):
        for line in ("HTTP/1.1 2000 OK", "HTTP/1.1 20", "HTTP/1.1 2x0", "HTTP/1.1 099", "HTTP/1.1 600",
                     "HTTP/2 200", "hello", "", "HTTP/1.1  200", "HTTP/1.1 +20"):
            with self.assertRaises(ValueError, msg=line):
                http_post.parse_status_line(line)


class ReadTests(unittest.TestCase):
    def head(self, conn, clock, limit_ms=12000):
        deadline = http_post.Deadline(clock.ticks_ms, clock.ticks_diff, limit_ms)
        return http_post.read_reply_head(conn, deadline, clock.feed)

    def test_status_and_retry_after(self):
        clock = Clock()
        conn = FakeConn(b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: x\r\nretry-after: 30\r\n\r\nbody")
        self.assertEqual(self.head(conn, clock), (429, "30"))

    def test_status_without_retry_after(self):
        clock = Clock()
        self.assertEqual(self.head(FakeConn(b"HTTP/1.0 201 Created\r\n\r\n"), clock), (201, None))

    def test_garbage_and_empty_raise(self):
        for data in (b"hello\r\n\r\n", b"", b"HTTP/1.1 200"):
            with self.assertRaises(ValueError, msg=data):
                self.head(FakeConn(data), Clock())

    def test_an_endless_reply_stops_at_the_cap_while_reading(self):
        clock = Clock()
        conn = FakeConn(b"", endless=b"x")
        with self.assertRaises(ValueError):
            self.head(conn, clock)
        self.assertLessEqual(conn.taken, http_post.MAX_HEAD_BYTES)

    def test_the_cap_holds_for_the_last_piece_when_it_is_not_a_multiple_of_the_piece(self):
        original = http_post.MAX_HEAD_BYTES
        http_post.MAX_HEAD_BYTES = 1000  # not a multiple of the 64 byte piece
        try:
            conn = FakeConn(b"", endless=b"x")
            with self.assertRaises(ValueError):
                self.head(conn, Clock())
            self.assertEqual(conn.taken, 1000)
        finally:
            http_post.MAX_HEAD_BYTES = original

    def test_a_long_status_line_is_never_read_as_a_status(self):
        # "HTTP/1.1 200" followed by a flood: the cut line must not pass as 200
        clock = Clock()
        conn = FakeConn(b"HTTP/1.1 200" + b"0" * 5000)
        with self.assertRaises(ValueError):
            self.head(conn, clock)
        self.assertLessEqual(conn.taken, http_post.MAX_HEAD_BYTES)

    def test_a_drip_ends_at_the_deadline_with_the_watchdog_fed_throughout(self):
        clock = Clock()
        # one byte every 1.5 s, forever
        conn = FakeConn(b"", clock, per_read=(1, 1500), endless=b"H")
        with self.assertRaises(OSError):
            self.head(conn, clock, limit_ms=12000)
        self.assertLessEqual(clock.now, 12000 + 1500)
        # the watchdog period is 8000 ms: no gap between feeds may reach it
        self.assertLess(clock.max_gap(), 8000)
        self.assertLessEqual(clock.max_gap(), 1500)

    def test_a_drip_that_finishes_inside_the_deadline_is_read(self):
        clock = Clock()
        conn = FakeConn(b"HTTP/1.1 201 Created\r\n\r\n", clock, per_read=(1, 100))
        self.assertEqual(self.head(conn, clock), (201, None))


class PostTests(unittest.TestCase):
    def post(self, conn, url="https://h/p", tls=object(), connect_error=None, clock=None, **kw):
        clock = clock or Clock()

        def connect(host, port, ctx, timeout, feed):
            if connect_error:
                raise connect_error
            self.seen = (host, port, ctx is not None, timeout)
            return conn

        result = http_post.post_json(url, "{}", "SECRETKEY", tls, 2, clock.feed, connect,
                                     (clock.ticks_ms, clock.ticks_diff), **kw)
        return result, clock

    def test_success_closes_and_feeds(self):
        conn = FakeConn(b"HTTP/1.1 201 Created\r\n\r\n")
        result, clock = self.post(conn)
        self.assertEqual(result, (201, None))
        self.assertTrue(conn.closed)
        self.assertEqual(self.seen, ("h", 443, True, 2))
        self.assertGreaterEqual(len(clock.feeds), 4)

    def test_timeout_and_errors_give_minus_one(self):
        self.assertEqual(self.post(None, connect_error=OSError(110))[0], (-1, None))
        conn = FakeConn(b"", fail_on_write=OSError(104))
        self.assertEqual(self.post(conn)[0], (-1, None))
        self.assertTrue(conn.closed)

    def test_https_without_a_context_is_refused(self):
        self.assertEqual(self.post(FakeConn(b"HTTP/1.1 200 OK\r\n\r\n"), tls=None)[0], (-1, None))

    def test_plain_http_passes_no_tls_context(self):
        self.post(FakeConn(b"HTTP/1.1 200 OK\r\n\r\n"), url="http://h:8000/p")
        self.assertEqual(self.seen, ("h", 8000, False, 2))

    def test_a_dripping_server_ends_the_post_and_closes_the_socket(self):
        clock = Clock()
        conn = FakeConn(b"", clock, per_read=(1, 1500), endless=b"H")
        result, _ = self.post(conn, clock=clock, deadline_ms=6000)
        self.assertEqual(result, (-1, None))
        self.assertTrue(conn.closed)
        self.assertLessEqual(clock.now, 6000 + 1500)

    def test_a_bad_host_or_key_sends_nothing(self):
        conn = FakeConn(b"HTTP/1.1 200 OK\r\n\r\n")
        for url in ("https://h\r\nX-Evil: 1/p", "https://h /p"):
            result, _ = self.post(conn, url=url)
            self.assertEqual(result, (-1, None))
        self.assertEqual(conn.written, b"")

    def test_key_never_printed_on_any_error_path(self):
        paths = {
            "connect": dict(conn=None, connect_error=OSError("boom")),
            "write": dict(conn=FakeConn(b"", fail_on_write=OSError("write failed"))),
            "read": dict(conn=FakeConn(b"", fail_on_read=OSError("read failed"))),
            "garbled": dict(conn=FakeConn(b"not http\r\n\r\n")),
            "empty": dict(conn=FakeConn(b"")),
            "endless": dict(conn=FakeConn(b"", endless=b"x")),
            "no tls": dict(conn=FakeConn(b""), tls=None),
            "bad url": dict(conn=FakeConn(b""), url="ftp://h"),
        }
        for name, kwargs in paths.items():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                result, _ = self.post(**kwargs)
            self.assertEqual(result, (-1, None), name)
            self.assertNotIn("SECRETKEY", out.getvalue(), name)
            self.assertTrue(out.getvalue(), name)  # the error was reported

    def test_key_never_in_output_on_a_good_post(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.post(FakeConn(b"HTTP/1.1 201 Created\r\n\r\n"))
        self.assertNotIn("SECRETKEY", out.getvalue())


if __name__ == "__main__":
    unittest.main()
