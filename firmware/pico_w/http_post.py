# firmware/pico_w/http_post.py
# a small HTTP/1.0 client for the telemetry post, written on sockets so every
# network call has a time-out and TLS is always verified. urequests is not used
# because its time-out and TLS options differ between MicroPython releases.
#
# the parts that need no hardware (URL, request and reply handling) are plain
# functions. The two calls that touch MicroPython-only APIs are open_socket and
# make_tls_context, kept small so they are the only places to check on a board.

# the most bytes read from a reply: the status line and headers fit in this
# with room to spare. The cap is applied while reading, so no single call can
# take more than this from a hostile server.
MAX_HEAD_BYTES = 1024
# the most bytes asked of the stream in one read, so the deadline and the
# watchdog feed are checked often even when the server sends a byte at a time
READ_PIECE = 64

HOST_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"


def header_safe(text):
    """True when text is non-empty and holds only printable ASCII (no byte at
    or under 0x20 and none at 0x7F or above). A space, CR or LF in the path, key
    or device id could add a header or split the request."""
    if not isinstance(text, str) or text == "":
        return False
    for ch in text:
        code = ord(ch)
        if code <= 0x20 or code >= 0x7F:
            return False
    return True


def parse_url(url):
    """Return (scheme, host, port, path). Raises ValueError for anything else
    than an http:// or https:// address with a plain host name or IPv4 address."""
    if url.startswith("https://"):
        scheme, rest, port = "https", url[8:], 443
    elif url.startswith("http://"):
        scheme, rest, port = "http", url[7:], 80
    else:
        raise ValueError("address must start with https:// or http://")
    slash = rest.find("/")
    hostport = rest if slash < 0 else rest[:slash]
    path = "/" if slash < 0 else rest[slash:]
    host = hostport
    colon = hostport.find(":")
    if colon >= 0:
        host = hostport[:colon]
        digits = hostport[colon + 1:]
        if digits == "" or len(digits) > 5:
            raise ValueError("port is not a number")
        for ch in digits:
            if ch < "0" or ch > "9":
                raise ValueError("port is not a number")
        port = int(digits)
    if host == "" or len(host) > 253:
        raise ValueError("address has no host")
    for ch in host:
        if ch not in HOST_CHARS:
            raise ValueError("host may only hold letters, digits, dots and hyphens")
    if not (0 < port < 65536):
        raise ValueError("bad port")
    if not header_safe(path):
        raise ValueError("path holds a space or a control character")
    return scheme, host, port, path


def build_request(host, port, scheme, path, body, api_key):
    """Return the request as bytes. body is a str of JSON. Raises ValueError
    when the host, path or key could change the shape of the request."""
    if not header_safe(api_key):
        raise ValueError("the key holds a space or a control character")
    if not header_safe(path) or host == "" or any(c not in HOST_CHARS for c in host):
        raise ValueError("host or path is not safe to send")
    data = body.encode("utf-8")
    default = 443 if scheme == "https" else 80
    host_header = host if port == default else "{}:{}".format(host, port)
    head = (
        "POST {} HTTP/1.0\r\n"
        "Host: {}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "X-API-Key: {}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(path, host_header, len(data), api_key)
    return head.encode("utf-8") + data


def parse_status_line(line):
    """Return the status code from 'HTTP/1.1 201 Created' or raise ValueError.
    The code must be exactly three digits, so a cut or garbled line is refused
    and not read as some other status."""
    parts = line.split(" ", 2)
    if len(parts) < 2 or parts[0] not in ("HTTP/1.0", "HTTP/1.1"):
        raise ValueError("not an HTTP reply")
    code = parts[1]
    if len(code) != 3 or any(c < "0" or c > "9" for c in code):
        raise ValueError("bad status code")
    value = int(code)
    if value < 100 or value > 599:
        raise ValueError("bad status code")
    return value


def parse_reply_head(head):
    """Return (status, retry_after) from the bytes read so far (the status
    line and as many headers as arrived). retry_after is the header text or
    None."""
    lines = head.decode().split("\r\n")
    status = parse_status_line(lines[0])
    retry_after = None
    for line in lines[1:]:
        if line == "":
            break
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "retry-after":
            retry_after = value.strip()
    return status, retry_after


class Deadline:
    """A total time limit measured in ticks (wrap-safe on MicroPython)."""

    def __init__(self, ticks_ms, ticks_diff, limit_ms):
        self._ticks_ms = ticks_ms
        self._ticks_diff = ticks_diff
        self._start = ticks_ms()
        self.limit_ms = limit_ms

    def elapsed_ms(self):
        return self._ticks_diff(self._ticks_ms(), self._start)

    def expired(self):
        return self.elapsed_ms() >= self.limit_ms


def read_reply_head(conn, deadline, feed):
    """Read the status line and headers from conn, a few bytes at a time.

    conn needs read(n). The watchdog is fed before every piece, the deadline
    is checked before every piece and at most MAX_HEAD_BYTES are taken from the
    stream in all. Returns (status, retry_after). Raises on a time-out, an
    empty or unfinished status line or a garbled reply."""
    head = b""
    while len(head) < MAX_HEAD_BYTES:
        if deadline.expired():
            raise OSError("reply took too long")
        feed()
        want = MAX_HEAD_BYTES - len(head)
        piece = conn.read(READ_PIECE if want > READ_PIECE else want)
        if not piece:
            break  # the server closed the connection (or a read timed out)
        head += piece
        if b"\r\n\r\n" in head:
            break
    if b"\r\n" not in head:
        raise ValueError("no complete status line")
    return parse_reply_head(head)


def post_json(url, body, api_key, tls_context, timeout_s, feed, connect=None,
              ticks=None, deadline_ms=12000):
    """POST a JSON string and return (status, retry_after).

    Returns (-1, None) on any failure, such as a time-out, a refused
    connection, a failed certificate check or a garbled reply. The key is never
    printed. feed() is called between steps so the watchdog stays fed.
    deadline_ms is the total for the reply, measured in ticks. ticks is a pair
    (ticks_ms, ticks_diff) and defaults to the time module's."""
    if connect is None:
        connect = open_socket
    if ticks is None:
        import time
        ticks = (time.ticks_ms, time.ticks_diff)
    conn = None
    try:
        scheme, host, port, path = parse_url(url)
        if scheme == "https" and tls_context is None:
            raise ValueError("https needs a TLS context")
        request = build_request(host, port, scheme, path, body, api_key)
        deadline = Deadline(ticks[0], ticks[1], deadline_ms)
        conn = connect(host, port, tls_context if scheme == "https" else None, timeout_s, feed)
        feed()
        conn.write(request)
        feed()
        return read_reply_head(conn, deadline, feed)
    except Exception as e:
        # the message can name the host but never holds the key or the body
        print("http_post error:", type(e).__name__, e)
        return -1, None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        feed()


# ---- MicroPython-only calls (check these on a board) ---------------------

def open_socket(host, port, tls_context, timeout_s, feed):
    """Return a connected stream with a time-out on every operation.

    MicroPython only. The watchdog is fed before each step: the name lookup,
    the socket, the connect and the TLS handshake. Two things cannot be
    bounded from here. socket.getaddrinfo has no time-out of its own. The
    handshake runs inside one wrap_socket call that may loop for longer than
    the watchdog period if a server sends its bytes slowly. Either ends in a
    watchdog reset. The reset counter in node.py then holds the retry rate
    down."""
    import socket
    feed()
    address = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    feed()
    sock = socket.socket()
    try:
        sock.settimeout(timeout_s)
        feed()
        sock.connect(address)
        feed()
        if tls_context is not None:
            # server_hostname sets SNI and, with CERT_REQUIRED, is what the
            # certificate's name is checked against
            return tls_context.wrap_socket(sock, server_hostname=host)
        return sock
    except Exception:
        sock.close()
        raise


def make_tls_context(der_certificates):
    """Return a TLS context that verifies the server against the given roots
    (a list of DER bytes, one per root).

    MicroPython only. SSLContext, verify_mode and load_verify_locations(cadata=)
    follow the MicroPython ssl documentation as understood for release 1.24 and
    later. The roots are loaded with one call each. Whether repeated calls add
    to the trusted set (as understood) or replace it is not verified on a board:
    if they replace it only the last root is trusted. Nothing here has been run
    on a board. The context never uses CERT_NONE."""
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # TLS 1.0 and 1.1 are refused. The mbedTLS that MicroPython is built with
    # speaks TLS 1.2 and later only, so its ssl has no such setting and the
    # floor is already there. An ssl that has the setting is held to it
    try:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        pass
    context.verify_mode = ssl.CERT_REQUIRED
    for der in der_certificates:
        context.load_verify_locations(cadata=der)
    return context
