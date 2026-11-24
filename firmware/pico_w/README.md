# Raspberry Pi Pico 2W - Ambient Node

This node reads a BME280 or BMP280 (temperature and pressure, plus humidity on the BME280), an LDR (light),
displays readings on an SSD1306 OLED and POSTs telemetry to the Phaemos API
over Wi-Fi every 5 seconds. It posts over HTTPS and checks the server's certificate.
A BMP280 has no humidity element so we leave humidity out of the POST body and the display shows `H:--`.

---

## Installing MicroPython on the Pico 2W

1. Download the Pico 2W MicroPython UF2 from:
   https://micropython.org/download/RPI_PICO2_W/

   > Use the **Pico 2W** build, not the original Pico W build - the RP2350
   > chip requires its own firmware image.

2. Hold the **BOOTSEL** button on the Pico 2W, then connect it to your
   computer via USB while holding the button.

3. The Pico appears as a USB mass storage device named **RPI-RP2**.

4. Drag the downloaded `.uf2` file onto the **RPI-RP2** drive.

5. The Pico automatically reboots into MicroPython.  The RPI-RP2 drive
   disappears - this is normal.

---

## Not run on real hardware

None of this firmware has run on a Pico yet. The logic (health fields, back-off, boot counter, start-up checks,
the loop) is tested on a desktop Python with fakes standing in for the board. The calls that only exist in
MicroPython (watchdog, TLS, NTP, sockets) are written from the MicroPython documentation as we understand it
and are listed under "What depends on MicroPython" below. Treat the first run on a board as a test.

---

## Settings and secrets

`config.py` holds defaults and placeholders only and is safe to commit. Real values go in `secrets.py`, which
is not committed:

1. Copy `secrets.example.py` to `secrets.py`.
2. Replace every `CHANGE_ME` with the real Wi-Fi name, Wi-Fi password, API address (`https://...`), device id and
   device key.
3. Copy `secrets.py` to the node with the other files.

The node refuses to run while any of those still says `CHANGE_ME` or is empty. It prints which setting is
missing on the serial output and stops.

What this does not protect: `secrets.py` sits in the Pico's flash as plain text. Anyone who holds the node can
read it over USB in seconds. Keep a node that holds a key somewhere only trusted people can reach, give each
node its own key and rotate the key if a node is lost.

The repository's `.gitignore` must list `firmware/pico_w/secrets.py`.

---

## Trust root (HTTPS)

The node checks the API's certificate against one root certificate that you put in `root_ca.pem`. The file in
this folder is a placeholder. In HTTPS mode the node refuses to start until it holds a real certificate.

The documented deployment uses Let's Encrypt, whose chain ends at the ISRG Root X1 root. To fill in the file:

1. Download the root from Let's Encrypt's own certificates page, https://letsencrypt.org/certificates/ (choose
   ISRG Root X1, the PEM link).
2. Check it before trusting it. Print its fingerprint and compare it with the SHA-256 fingerprint shown for that
   root on the same page:

   ```bash
   openssl x509 -in root_ca.pem -noout -subject -enddate -fingerprint -sha256
   ```

3. Check that the API really ends at that root:

   ```bash
   openssl s_client -connect api.phaemos.com:443 -servername api.phaemos.com -showcerts </dev/null
   ```

   The last certificate it sends is signed by the root you downloaded. If Let's Encrypt moves the site to another
   root, change the file to match.
4. Copy `root_ca.pem` to the node. It is public, so it is fine to commit once checked.

The file may hold more than one root (up to four, one after another). Put both Let's Encrypt roots in it so a
chain that moves from one to the other does not silence the node. The node reads PEM, converts each certificate to
DER and gives the `ssl` module one `load_verify_locations(cadata=...)` call per root. Whether repeated calls add
to the trusted set or replace it has not been checked on a board. If they replace it only the last root in the
file is trusted, so after the first flash try a node against each root in turn. A block in the file that is not a
real certificate stops the node starting. A root has an expiry date, so note it (`-enddate` above) and replace
the file before then.

### The clock

The clock is set by NTP before the first HTTPS post, because a certificate cannot be checked against a wrong
date. Until the clock is set the node does not post and tries again with the usual back-off.

- A time below `CLOCK_FLOOR_UNIX` in `config.py` (or above 1 January 2100) is refused as a wrong answer. The
  floor is the build date of the firmware. MicroPython has no build date, so **keep it current**: when you flash
  a node set it to a date on or just before that day (Unix seconds, for example from
  `python3 -c "import calendar;print(calendar.timegm((2026,11,1,0,0,0)))"`).
- Three posts in a row that never completed make the node forget the clock and set it again before the next
  post. A wrong clock makes every certificate check fail. This is how a node recovers from one wrong NTP
  answer without a power cycle. A reply with a status (even an error) does not count.
- The clock is set again every 24 hours. If that fails the node keeps its old time and tries again an hour
  later.

### Plain HTTP (bench only)

To test against a server with no TLS, set `ALLOW_PLAIN_HTTP = True` in `secrets.py` and use an `http://`
address. The node then prints a warning at start, marks every post line `[PLAIN HTTP]`, shows `PLAIN HTTP!` on
the display and sends `"plain_http": true` in every body. The key and the
readings cross the network unencrypted, so never use it on a node that leaves the bench. Without the flag an
`http://` address stops the node starting.

---

## How the node keeps running

| Part | Behaviour |
|---|---|
| Watchdog | `machine.WDT` set to 8000 ms and fed on every pass and between each step of a post. The RP2040 limit is about 8.3 s (8388 ms in MicroPython), so 8000 ms is the largest round value. A node that hangs resets itself |
| Time-outs | Every socket operation gives up after 2 s. The reply is read at most 64 bytes at a time, with a feed before each piece, a cap of 1024 bytes in all (enforced while reading) and a total deadline of 12 s measured in ticks. A server that drips one byte at a time is cut off at the deadline with the watchdog fed throughout |
| Longest legitimate pass | The loop runs once a second. A normal pass is a sensor read, a display refresh and a one second sleep taken in 250 ms slices. A post adds the lookup, the connect, the handshake, the send and the reply pieces, each at most 2 s and each with a feed before it. No normal step runs past about 2.5 s without a feed |
| Wi-Fi | Checked before every post. A lost connection is rejoined. A join polls every half second with a feed each time and gives up after 20 s |
| Failed post | The wait before the next try doubles from 5 s up to 300 s and goes back to 5 s after a good post |
| 429 | The `Retry-After` seconds are obeyed, up to one hour |
| 401, 403 or 409 | A wrong key will not fix itself and a counter the server calls old stays old until an admin accepts a new one. The node waits 5 minutes and doubles up to one hour. For a 409 it says on the serial output what it means. A 200 with `"status": "duplicate"` counts as delivered |
| Sensor read that fails | The sensor is reported in `faults` and the loop carries on. The sensor and the display are set up again after each failure, so a loose wire is recovered |

Two things cannot be bounded from MicroPython code: a host name lookup (the API's or the NTP server's) has no
time-out of its own. The TLS handshake runs inside one `wrap_socket` call that may loop for longer than the
watchdog period if a server trickles its bytes. Either ends in a watchdog reset. That is a safe failure. The
next boot shows `reset_reason` of `watchdog`. We could not verify the handshake behaviour here, so it is stated
as a risk and not a finding.

### Resets and the retry rate

A watchdog reset loses the back-off held in memory. To stop a node in a reset loop hammering the server, the
node keeps a count of watchdog resets in a row in `reset_count.txt`:

- At boot after a watchdog reset the count goes up by one and is written. After any other reset a count that is
  not zero is cleared.
- The first post of a boot waits as the back-off would for that count (5 s, 10 s, 20 s and so on up to 300 s).
- The first good post after such a boot clears the count.
- Nothing is written once per attempt. A node in a reset loop writes once per boot. Each boot waits at least
  as long as the one before up to 300 s, so the writes are bounded at about 290 a day (checked in the tests). A
  healthy node writes nothing. If the file cannot be written the node carries on and the count only holds for
  that boot.

### What the node reports

Each post carries the readings plus `seq`, `boot`, `up`, `fw`, `ts` (once the clock is set), `reset_reason`,
`heap_free`, `plain_http` (bench mode only) and `faults`. The server refuses a post whose (`boot`, `seq`) is not
newer than the last it accepted for the machine (409). A machine that has sent the pair must always send it.

- `seq` goes up by one for every post made, sent or not. It starts again from 0 at each boot.
- `boot` comes from `boot_count.txt`, a small counter written once per boot (to a temporary file that is then
  renamed). The new value is written before it is used.
- If that file is missing it is the first boot and the count starts at 1. If it is corrupt, out of range or
  cannot be written there is no safe small number: a number read from it could repeat one already sent. The node
  then takes `boot` from the synced clock (Unix seconds, capped at 2147483647 which is the server's limit),
  waits for the clock before its first post and never posts without a usable `boot`. It tries to store that
  value in the counter file after each good post until a write works. From then on the counter carries on from
  the clock value.
- Moving from a small counter to a clock value is a rise, because a clock value is always far above a small
  count. Moving back never happens by itself: once the clock value is stored the counter continues above it. One
  case is not covered. If writes fail for some boots (so clock values are sent and not stored) and the file then
  reads again with its old small value, the next boot sends a number below the last accepted and is refused (409)
  until an admin accepts a new counter. The node says so on the serial output.
- A node whose flash was wiped starts again at 1, which can be below an earlier boot. The same 409 and the same
  admin step apply.
- The clock value reaches the server's limit in January 2038. After that `boot` stops rising and the server
  must raise its limit.
- `up` is accumulated from the tick counter, which wraps, so it does not jump.

Sensor keys in `faults` are `bme280` and `ldr`, as in the API's sensor map. A read that raises is `missing`.
A temperature outside -40 to 85, a humidity outside 0 to 100 or a pressure outside 300 to 1100 hPa makes the
whole `bme280` entry `out_of_range` and its values are left out of the post.

### The address

`API_BASE_URL` is the base address only (for example `https://api.example.org`). Trailing slashes are stripped, because the server answers 404 for a path with a trailing slash and never redirects it. A full ingest address such as `https://api.example.org/api/v1/telemetry/` is refused at start with a plain message, because the node adds the path itself. A 404 on a post is a wrong address and will not fix itself: the node says so once on the serial output and then waits as it does for a refused key (5 minutes, doubling to an hour) and does not retry every few seconds.

### What the node checks in its settings

The host in `API_BASE_URL` may hold only letters, digits, dots and hyphens and the port only digits, so a host such
as `api.example.org\r\nX-Evil: 1` is refused. The key, the device id and the path must hold no space and no
byte at or below 0x20, at 0x7F or above. Each is checked at start (the node names the setting) and again when the
request is built. IPv6 addresses in brackets are not supported.

---

## Copying Files to the Pico

### Using Thonny (recommended for beginners)

1. Open Thonny IDE (https://thonny.org/).
2. Go to **Tools > Options > Interpreter**, select **MicroPython (Raspberry Pi Pico)**.
3. Connect the Pico via USB.
4. In the Files panel (View > Files), navigate to this folder on your PC.
5. Right-click each `.py` file and choose **Upload to /**.
6. Copy in this order: `config.py`, `secrets.py`, `root_ca.pem`, `bme280.py`, `ssd1306.py`,
   `wifi_connect.py`, `http_post.py`, `readings.py`, `node.py`, `main.py`.

### Using rshell (command line)

```bash
pip install rshell
rshell --port /dev/ttyACM0   # adjust port for your OS

# Inside rshell:
cp firmware/pico_w/config.py       /pyboard/
cp firmware/pico_w/secrets.py      /pyboard/
cp firmware/pico_w/root_ca.pem     /pyboard/
cp firmware/pico_w/bme280.py       /pyboard/
cp firmware/pico_w/ssd1306.py      /pyboard/
cp firmware/pico_w/wifi_connect.py /pyboard/
cp firmware/pico_w/http_post.py    /pyboard/
cp firmware/pico_w/readings.py     /pyboard/
cp firmware/pico_w/node.py         /pyboard/
cp firmware/pico_w/main.py         /pyboard/
```

### Using mpremote (official MicroPython tool)

```bash
pip install mpremote
mpremote cp firmware/pico_w/config.py       :config.py
mpremote cp firmware/pico_w/secrets.py      :secrets.py
mpremote cp firmware/pico_w/root_ca.pem     :root_ca.pem
mpremote cp firmware/pico_w/bme280.py       :bme280.py
mpremote cp firmware/pico_w/ssd1306.py      :ssd1306.py
mpremote cp firmware/pico_w/wifi_connect.py :wifi_connect.py
mpremote cp firmware/pico_w/http_post.py    :http_post.py
mpremote cp firmware/pico_w/readings.py     :readings.py
mpremote cp firmware/pico_w/node.py         :node.py
mpremote cp firmware/pico_w/main.py         :main.py
```

---

## Wiring

All devices share the I2C bus on GP4 (SDA) and GP5 (SCL).

### BME280 or BMP280 Temperature/Pressure (and Humidity on the BME280)

| Breakout Pin | Pico 2W Pin | Notes                             |
|------------|-------------|-----------------------------------|
| VCC        | 3.3V (Pin 36) | 3.3V only - do NOT use VBUS (5V) |
| GND        | GND (Pin 38)  |                                 |
| SCL        | GP5 (Pin 7)   | I2C0 SCL                        |
| SDA        | GP4 (Pin 6)   | I2C0 SDA                        |
| SDO        | GND           | Sets I2C address to 0x76        |
| CSB        | 3.3V          | Selects I2C mode (not SPI)      |

### SSD1306 OLED Display

| SSD1306 Pin | Pico 2W Pin   | Notes                         |
|-------------|---------------|-------------------------------|
| VCC         | 3.3V (Pin 36) | Shares power rail with BME280 |
| GND         | GND (Pin 38)  |                               |
| SCL         | GP5 (Pin 7)   | Shared I2C bus with BME280    |
| SDA         | GP4 (Pin 6)   | Shared I2C bus with BME280    |

> The BME280 or BMP280 (0x76) and SSD1306 (0x3C) have different I2C addresses so they
> coexist on the same bus without conflict.

### LDR Light Sensor

Wire the LDR as a voltage divider with a 10 kohm resistor. The top of the LDR goes to the ADC
reference (ADC_VREF) and the 10 kohm resistor goes to analogue ground:

```
ADC_VREF ---[LDR]--- ADC pin ---[10k]--- AGND
```

Higher light = lower LDR resistance = higher voltage = higher ADC reading.

The ADC pin depends on the board. It is the single value `LDR_PIN` in `config.py`:

| Board                        | ADC pin | `LDR_PIN` |
|------------------------------|---------|-----------|
| Raspberry Pi Pico 2 W        | GP26 (Pin 31) | 26  |
| Waveshare RP2350B-Plus-W     | GPIO40  | 40        |

The UF2 above is the Raspberry Pi Pico 2 W build, on which pin 40 is invalid. The Waveshare RP2350B-Plus-W
needs a MicroPython build made for that board and we have not verified one. Pin 40 applies only with such a build.

---

## Verifying Output in Thonny

1. Open Thonny and connect to the Pico.
2. Click the **Shell** tab at the bottom.
3. Press **Ctrl+D** to soft-reset and run `main.py`.
4. You should see:

```
PHAEMOS Pico node 1.1.0 boot 3
Wi-Fi connected. IP: 192.168.1.42
POST OK (201) seq 0
POST OK (201) seq 1
```

With a BMP280 the humidity shows as `H:--` on the display and the POST body has no humidity.

5. If you see `POST failed (status=-1)`, check that the Phaemos API server
   is running, `API_BASE_URL` in `secrets.py` is correct and (for HTTPS) that `root_ca.pem` is the right root.
   A failed certificate check shows as a status of -1 with an error name above it.

6. If you see `Wi-Fi failed`, verify the SSID and password in `secrets.py` and
   that the Pico 2W is within range of the access point.

7. If you see `PHAEMOS node will not start`, the lines under it name the setting to fix.

8. `the API refused the key` means a 401: the key in `secrets.py` is wrong or was rotated.

---

## Testing

The tests run on a desktop Python 3 with the standard library only and need no hardware and no network. Small
fakes stand in for the `machine` and `network` modules, the I2C bus and the whole board. From this folder run:

```bash
python3 -m unittest discover
python3 -m py_compile *.py tests/*.py
```

The logic lives in `node.py` (fault table, boot counter, back-off, body builder, start-up checks and the
loop's single pass) and `readings.py` (unit conversion and display text). `http_post.py` holds the URL,
request and reply handling as plain functions. `main.py` is the only file that touches the board and is not
imported by the tests.

## What depends on MicroPython

The tests cannot prove any of these. Check each on a board:

- `machine.WDT(timeout=8000)` and `feed()`, with the 8388 ms limit holding on the RP2350 as well as the RP2040
- `machine.reset()`, `machine.reset_cause()` and the names `PWRON_RESET` and `WDT_RESET`, which the reset counter relies on
- `time.ticks_ms`, `ticks_diff`, `sleep_ms`, `time.gmtime` and the epoch of 2000 (the node adds 946684800 to
  send a Unix `ts`)
- `ntptime.settime()` and its `timeout` setting, with whether its name lookup can outlast the watchdog
- `read(n)` on a TLS stream returning what is available (up to n bytes) and not waiting for n bytes, with a read that
  times out raising or returning nothing. Both are handled as a failed post
- `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` refusing TLS 1.0 and 1.1 with no setting (the `minimum_version` line is skipped
  when the board's ssl has none), `verify_mode = ssl.CERT_REQUIRED`, `load_verify_locations(cadata=)`
  with DER bytes (once per root, adding to the trusted set) and `wrap_socket(sock, server_hostname=...)` checking the host name. These are in
  `http_post.make_tls_context` and `http_post.open_socket`, the only two functions to change if the
  installed MicroPython differs. We assume MicroPython 1.24 or later, the first release with a Pico 2 W
  build. We could not check the `ssl` documentation for that release from this machine
- `socket.getaddrinfo`, `settimeout`, `write` and `readline` on a TLS stream
- `network.WLAN` (`active`, `connect`, `isconnected`, `ifconfig`)
- `os.urandom`, `os.rename` and `binascii.a2b_base64`
- `gc.mem_free` and `bytes.decode()`
- `I2C`, `ADC.read_u16` and the display driver, unchanged from before
