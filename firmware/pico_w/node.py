# firmware/pico_w/node.py
# the logic of the node with no hardware import: the fault table, the boot
# counter, the back-off, the body builder and the loop's single pass. The
# hardware sits behind the object passed to Node, so all of this runs on a
# desktop Python as well.

import readings

# firmware version reported in the `fw` health field
FW_VERSION = "1.1.0"

# the backend refuses a sequence number above this
MAX_SEQ = 4294967295

# ---- the fault table -----------------------------------------------------
# sensor key (the backend's name, from backend/app/services/sensor_map.py)
# -> reading field -> plausible range. A value outside its range means the
# sensor cannot be trusted, so the whole sensor is reported as out_of_range
# and its fields are left out of the post.
SENSOR_RANGES = {
    "bme280": {
        "temperature": (-40.0, 85.0),
        "humidity": (0.0, 100.0),
        "pressure": (300.0, 1100.0),
    },
    "ldr": {
        "light_level": (0, 65535),
    },
}

# state reported when a read raises. The driver raises when the chip does not
# answer on the bus, which is what `missing` means.
READ_FAILED_STATE = "missing"


def apply_faults(values, errors):
    """Return (clean_values, faults).

    values is a dict of reading field to number or None, errors a dict of
    sensor key to fault state for each sensor whose read raised. A fault drops
    every field of that sensor from the result, because the backend does not
    trust them and a NaN would also break the JSON.
    """
    clean = {}
    faults = {}
    for sensor, fields in SENSOR_RANGES.items():
        if sensor in errors:
            faults[sensor] = errors[sensor]
            continue
        bad = False
        for field, (low, high) in fields.items():
            value = values.get(field)
            # written so a NaN fails the test: every comparison with NaN is false
            if value is not None and not (low <= value <= high):
                bad = True
        if bad:
            faults[sensor] = "out_of_range"
            continue
        for field in fields:
            if values.get(field) is not None:
                clean[field] = values[field]
    return clean, faults


# ---- the boot counter ---------------------------------------------------
# the server refuses a post whose (boot, seq) is not newer than the last it
# accepted. It drops a boot above this limit
MAX_BOOT = 2147483647


def next_boot(read_file, write_file):
    """Return (boot, persisted) from the counter file. It returns (None, False) when
    the file cannot be used.

    read_file() returns the stored text or raises OSError when there is no
    file (the first boot of a new node, which starts at 1). write_file(text)
    stores the new value or raises. The new value is written before it is used.
    When the file is corrupt, out of range or cannot be written there is no
    safe small number to use: a number taken from the file could repeat one
    already sent. The caller then takes boot from the clock (see clock_boot)."""
    previous = 0
    try:
        text = read_file()
    except OSError:
        text = None
    if text is not None:
        try:
            previous = int(text.strip())
        except ValueError:
            return None, False
        if previous < 0 or previous >= MAX_BOOT:
            return None, False
    boot = previous + 1
    try:
        write_file(str(boot))
    except Exception:
        return None, False
    return boot, True


def clock_boot(unix_seconds):
    """A boot number from the synced clock: Unix seconds, capped at the
    server's limit. It only rises from one boot to the next. It is always
    far above any small counter, so moving from a counter to the clock is a
    rise. Once the counter file can be written again the clock value is stored
    in it, so the counter carries on from there and never falls back below a
    number already sent. A boot that was not stored, followed by one where the
    file reads again with an older value, would send a smaller number: that is
    refused (409) until an admin accepts a new counter. The README says so.
    The cap is reached in 2038 (the server's own limit)."""
    return min(int(unix_seconds), MAX_BOOT)


# ---- the reset counter ---------------------------------------------------
# a post that hangs ends in a watchdog reset. The pacer's wait is lost with
# it. The number of watchdog resets in a row is kept in a small file so a node
# that resets on every attempt does not hammer the server. The file is written
# only at boot after a watchdog reset (the count goes up) and once after the
# first good post (it is cleared), never once per attempt. A node in a reset
# loop waits at least 5 s then doubling to 300 s between boots, so it writes at
# most about 290 times a day. A healthy node writes nothing.

def next_reset_count(read_file, write_file, was_watchdog):
    """Return the number of watchdog resets in a row, including this boot."""
    try:
        previous = int(read_file().strip())
    except (OSError, ValueError):
        previous = 0
    if previous < 0 or previous > 100:
        previous = 100
    if not was_watchdog:
        if previous != 0:
            try:
                write_file("0")
            except Exception:
                pass
        return 0
    count = previous + 1
    try:
        write_file(str(count))
    except Exception:
        pass  # a count that cannot be kept still holds for this boot
    return count


# ---- the address ----------------------------------------------------------

def base_address(url):
    """The base address with any trailing slashes removed. The server answers 404 for a path with a
    trailing slash and never redirects it, so a double slash in a request would end every post."""
    return url.rstrip("/")


def address_problem(url):
    """A plain message when the address is not a bare base address (None when it is). A full ingest address
    (https://host/api/v1/telemetry, with or without a slash on the end) is refused: the node adds the
    path itself."""
    import http_post
    try:
        scheme, host, port, path = http_post.parse_url(base_address(url))
    except ValueError:
        return None  # the other check names what is wrong with it
    if path != "/":
        return ("API_BASE_URL must be the base address only, for example https://api.example.org. "
                "Remove the path {} (the node adds /api/v1/telemetry itself)".format(path))
    return None


# ---- back-off ------------------------------------------------------------

def backoff_delay(failures, base_s, cap_s):
    """Seconds to wait after `failures` failed posts in a row: base, 2x base and
    so on, never more than cap_s."""
    steps = min(max(failures, 1) - 1, 20)
    return min(cap_s, base_s << steps)


def parse_retry_after(value, default_s, max_s):
    """Seconds from a Retry-After header. Only the whole-seconds form is read:
    the date form is rare and needs a clock, so it gets the default."""
    try:
        seconds = int(str(value).strip())
    except (ValueError, TypeError):
        return default_s
    if seconds < 1:
        return default_s
    return min(seconds, max_s)


class Pacer:
    """Decides how long to wait after each post."""

    def __init__(self, interval_s, cap_s, auth_start_s, auth_cap_s, retry_after_max_s):
        self.interval_s = interval_s
        self.cap_s = cap_s
        self.auth_start_s = auth_start_s
        self.auth_cap_s = auth_cap_s
        self.retry_after_max_s = retry_after_max_s
        self.failures = 0
        self.auth_failures = 0

    def on_result(self, status, retry_after=None):
        """Return the seconds to wait before the next post.

        status is the HTTP status or -1 when the post never completed."""
        if 200 <= status < 300:
            self.failures = 0
            self.auth_failures = 0
            return self.interval_s
        if status in (401, 403, 404, 409):
            # a 404 on a post is a wrong address, which will not fix itself either. A wrong key will not
            # fix itself. A counter the server calls
            # old stays old until an admin accepts a new one, so wait hard
            self.auth_failures += 1
            return backoff_delay(self.auth_failures, self.auth_start_s, self.auth_cap_s)
        if status == 429:
            # the server asked us to slow down: obey it, never go faster than normal
            wait = parse_retry_after(retry_after, 60, self.retry_after_max_s)
            return max(wait, self.interval_s)
        self.auth_failures = 0
        self.failures += 1
        return backoff_delay(self.failures, self.interval_s, self.cap_s)

    def on_local_failure(self):
        """A failure before any post (no Wi-Fi, no clock): same doubling."""
        self.failures += 1
        return backoff_delay(self.failures, self.interval_s, self.cap_s)


def status_text(status):
    """Short text for the OLED status line."""
    if 200 <= status < 300:
        return "POST OK"
    if status in (401, 403):
        return "KEY REFUSED"
    if status == 404:
        return "BAD ADDRESS"
    if status == 409:
        return "COUNTER OLD"
    if status == 429:
        return "RATE LIMITED"
    if status == -1:
        return "NO REPLY"
    return "ERR {}".format(status)


# ---- the body ------------------------------------------------------------

def build_body(device_id, values, faults, seq, boot, up_s, unix_ts=None,
               reset_reason=None, heap_free=None, plain_http=False):
    """Build the telemetry body: the readings plus the health fields.

    values is the dict returned by apply_faults. `ts` is only sent once the
    clock is set. `faults` is left out when empty, as the API allows."""
    body = readings.build_payload(
        values.get("temperature"), values.get("humidity"),
        values.get("pressure"), values.get("light_level"), device_id)
    body["seq"] = seq
    body["boot"] = boot
    body["up"] = up_s
    body["fw"] = FW_VERSION
    if faults:
        body["faults"] = dict(faults)
    if unix_ts is not None:
        body["ts"] = unix_ts
    if reset_reason:
        body["reset_reason"] = reset_reason
    if heap_free is not None:
        body["heap_free"] = heap_free
    if plain_http:
        # bench mode is visible to the server as well as on the serial output
        body["plain_http"] = True
    return body


# ---- start-up checks -----------------------------------------------------

def is_placeholder(value, marker="CHANGE_ME"):
    return (not isinstance(value, str)) or value.strip() == "" or marker in value


def pem_to_ders(text, limit=4):
    """Return the DER bytes of every certificate in a PEM text (at most
    `limit`). Raises ValueError when there is none. A file may hold two
    roots, so a chain that moves from one to the other still verifies. The TLS
    call is given plain DER."""
    import binascii
    begin = "-----BEGIN CERTIFICATE-----"
    end = "-----END CERTIFICATE-----"
    found = []
    position = 0
    while len(found) < limit:
        start = text.find(begin, position)
        if start < 0:
            break
        stop = text.find(end, start)
        if stop < 0:
            raise ValueError("certificate block is not closed")
        try:
            der = binascii.a2b_base64(text[start + len(begin):stop])
        except Exception:
            raise ValueError("certificate text is not valid base64")
        # a certificate is a DER SEQUENCE: tag 0x30 then a long-form length
        if len(der) < 4 or der[0] != 0x30 or der[1] != 0x82:
            raise ValueError("not a DER certificate")
        if len(der) != 4 + ((der[2] << 8) | der[3]):
            raise ValueError("certificate length does not match its header")
        found.append(bytes(der))
        position = stop + len(end)
    if not found:
        raise ValueError("no certificate block found")
    return found


def clock_plausible(unix_seconds, floor, ceiling):
    """True when a time from NTP lies between the build-date floor and the
    ceiling. A wrong answer (the epoch, a far-future date) is refused."""
    return floor <= unix_seconds <= ceiling


def startup_problems(cfg, read_file):
    """Return a list of plain-words problems that stop the node starting.

    cfg is the config module (or any object with the same names). read_file(path)
    returns the text of a file or raises OSError."""
    problems = []
    for name in ("WIFI_SSID", "WIFI_PASS", "API_BASE_URL", "DEVICE_ID", "API_KEY"):
        if is_placeholder(getattr(cfg, name, None)):
            problems.append("{} is missing or still a placeholder: set it in secrets.py".format(name))
    import http_post
    for name in ("API_KEY", "DEVICE_ID"):
        value = getattr(cfg, name, None)
        if not is_placeholder(value) and not http_post.header_safe(value):
            problems.append("{} holds a space or a control character".format(name))
    url = getattr(cfg, "API_BASE_URL", "")
    if isinstance(url, str) and not is_placeholder(url):
        try:
            http_post.parse_url(base_address(url))
        except ValueError as e:
            problems.append("API_BASE_URL is not usable: {}".format(e))
        problem = address_problem(url)
        if problem:
            problems.append(problem)
        if url.startswith("https://"):
            try:
                pem_to_ders(read_file(cfg.ROOT_CA_FILE))
            except OSError:
                problems.append("{} is missing: copy the root certificate to the node".format(cfg.ROOT_CA_FILE))
            except ValueError as e:
                problems.append("{} is not a real certificate yet ({}): see the README".format(cfg.ROOT_CA_FILE, e))
        elif url.startswith("http://"):
            if not getattr(cfg, "ALLOW_PLAIN_HTTP", False):
                problems.append("API_BASE_URL is http:// but ALLOW_PLAIN_HTTP is not set: use https:// or set it for bench use only")
        else:
            problems.append("API_BASE_URL must start with https://")
    return problems


# ---- the loop ------------------------------------------------------------

class Node:
    """One pass of the main loop per call to step().

    hw is the hardware seam. It provides: ticks_ms, ticks_diff, feed,
    read_bme, read_ldr, show, wifi_connected, wifi_connect, sync_clock,
    unix_time, reset_reason, heap_free, save_boot, clear_reset_marker, post
    and reset. main.py supplies the real one and the tests a fake.

    boot is the counter from the file. It is None when the file could not be used:
    the node then takes boot from the synced clock before its first post. It
    never posts without a boot."""

    def __init__(self, hw, cfg, boot, boot_persisted=True, reset_count=0):
        self.hw = hw
        self.cfg = cfg
        self.boot = boot
        self.boot_persisted = boot_persisted
        self.reset_count = reset_count
        self.tls = cfg.API_BASE_URL.startswith("https://")
        self.pacer = Pacer(cfg.TELEMETRY_INTERVAL, cfg.BACKOFF_CAP_S,
                           cfg.AUTH_BACKOFF_START_S, cfg.AUTH_BACKOFF_CAP_S,
                           cfg.RETRY_AFTER_MAX_S)
        self.seq = 0
        self.now_ms = 0
        self._last_ticks = None
        # after watchdog resets in a row the first post waits as the pacer would
        self.next_post_ms = 0
        if reset_count > 0:
            self.next_post_ms = backoff_delay(reset_count, cfg.TELEMETRY_INTERVAL, cfg.BACKOFF_CAP_S) * 1000
        self.clock_ok = False
        self._clock_tried = False
        self._next_resync_ms = 0
        self._net_failures = 0
        self.status_line = "STARTING"
        self._reported_404 = False
        self._last_fault_text = ""
        self._why = {}

    def announce(self):
        print("PHAEMOS Pico node {} boot {}".format(FW_VERSION, self.boot if self.boot is not None else "(from clock)"))
        if self.boot is None:
            print("WARNING: boot counter file could not be used: boot will come from the clock")
        if self.reset_count:
            print("WARNING: {} watchdog reset(s) in a row: the first post is delayed".format(self.reset_count))
        if not self.tls:
            print("WARNING: PLAIN HTTP (bench only): the key and the readings are NOT encrypted")

    @property
    def up_s(self):
        return self.now_ms // 1000

    def _tick(self):
        now = self.hw.ticks_ms()
        if self._last_ticks is not None:
            self.now_ms += self.hw.ticks_diff(now, self._last_ticks)
        self._last_ticks = now

    def _read(self):
        """Read every sensor. A read that raises is a fault, never a stop."""
        values = {}
        errors = {}
        self._why = {}
        try:
            t, h, p = self.hw.read_bme()
            values["temperature"] = t
            values["humidity"] = h
            values["pressure"] = p
        except Exception as e:
            errors["bme280"] = READ_FAILED_STATE
            self._why["bme280"] = type(e).__name__
        try:
            values["light_level"] = self.hw.read_ldr()
        except Exception as e:
            errors["ldr"] = READ_FAILED_STATE
            self._why["ldr"] = type(e).__name__
        return apply_faults(values, errors)

    def step(self):
        """Run one pass: read, show and post when due. Never raises for a
        sensor, display or network failure."""
        self.hw.feed()
        self._tick()
        clean, faults = self._read()
        text = ",".join(sorted(faults))
        if text != self._last_fault_text:
            # printed only when the set changes, so a dead sensor does not
            # fill the serial output once a second
            print("faults:", text or "none", self._why if self._why else "")
            self._last_fault_text = text
        try:
            lines = readings.display_lines(
                clean.get("temperature"), clean.get("humidity"),
                clean.get("pressure"), clean.get("light_level")) + (self.status_line,)
            if not self.tls:
                lines = lines + ("PLAIN HTTP!",)
            self.hw.show(lines)
        except Exception as e:
            print("display failed:", e)

        if self.now_ms < self.next_post_ms:
            return
        delay = self._post(clean, faults)
        self._tick()
        self.next_post_ms = self.now_ms + delay * 1000

    def _clock_needed(self):
        # HTTPS needs the clock for the certificate. So does a boot number
        # taken from the clock. Plain HTTP otherwise makes one try for `ts`.
        return self.tls or self.boot is None

    def _sync(self):
        if self.hw.sync_clock():
            self.clock_ok = True
            self._net_failures = 0
            self._next_resync_ms = self.now_ms + self.cfg.RESYNC_INTERVAL_S * 1000
            return True
        return False

    def _post(self, clean, faults):
        hw = self.hw
        if not hw.wifi_connected():
            self.status_line = "NO WIFI"
            if not hw.wifi_connect():
                print("Wi-Fi not connected, will retry")
                return self.pacer.on_local_failure()
        if not self.clock_ok and (self._clock_needed() or not self._clock_tried):
            self._clock_tried = True
            if not self._sync():
                if self._clock_needed():
                    self.status_line = "NO CLOCK"
                    print("clock not set, will retry")
                    return self.pacer.on_local_failure()
        elif self.clock_ok and self.now_ms >= self._next_resync_ms:
            # a daily re-sync. A failure keeps the old time and tries again soon
            if not self._sync():
                self._next_resync_ms = self.now_ms + 3600 * 1000

        if self.boot is None:
            now = hw.unix_time()
            if now is None:
                # never post without a usable boot
                self.clock_ok = False
                self.status_line = "NO CLOCK"
                return self.pacer.on_local_failure()
            self.boot = clock_boot(now)
            self.boot_persisted = hw.save_boot(self.boot)
            print("boot {} taken from the clock{}".format(
                self.boot, "" if self.boot_persisted else " (not stored)"))

        if self.seq > MAX_SEQ:
            # restart rather than wrap, because the counter must never repeat
            hw.reset()
        seq = self.seq
        # the number is used up when the body is built, sent or not, so a post
        # that reached the server but lost its answer is never repeated
        self.seq += 1
        body = build_body(self.cfg.DEVICE_ID, clean, faults, seq, self.boot, self.up_s,
                          hw.unix_time() if self.clock_ok else None,
                          hw.reset_reason(), hw.heap_free(), not self.tls)
        try:
            status, retry_after = hw.post(body)
        except Exception as e:
            print("post error:", e)
            status, retry_after = -1, None
        self.status_line = status_text(status)
        delay = self.pacer.on_result(status, retry_after)

        if status == -1:
            # a post that never completed may be a wrong clock failing the
            # certificate check. After three in a row the clock is forgotten
            # and set again before the next post
            self._net_failures += 1
            if self._net_failures >= self.cfg.CLOCK_FAIL_LIMIT and self.tls:
                self.clock_ok = False
                self._net_failures = 0
                print("three posts in a row failed: the clock will be set again")
        else:
            self._net_failures = 0

        mode = "" if self.tls else " [PLAIN HTTP]"
        if 200 <= status < 300:
            print("POST OK ({}) seq {}{}".format(status, seq, mode))
            if self.reset_count:
                self.reset_count = 0
                hw.clear_reset_marker()
            if not self.boot_persisted:
                # the counter file could not be written earlier: try again
                self.boot_persisted = hw.save_boot(self.boot)
        else:
            print("POST failed (status={}) seq {}, next try in {}s{}".format(status, seq, delay, mode))
            if status in (401, 403):
                print("the API refused the key: check API_KEY in secrets.py")
            elif status == 404:
                if not self._reported_404:
                    self._reported_404 = True
                    print("the API answered 404 for the telemetry route: API_BASE_URL is wrong. It must be the base "
                          "address only, with no path and no trailing slash. Checking again in {}s".format(delay))
            elif status == 409:
                print("the API refused boot {} seq {} as older than the last it accepted. "
                      "If this node's flash was wiped an admin must accept a new counter "
                      "for it. Waiting {}s".format(self.boot, seq, delay))
        return delay
