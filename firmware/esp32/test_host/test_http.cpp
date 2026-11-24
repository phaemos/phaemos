// test_http.cpp - host test for the pure parts of the hub's own HTTP post: the address, the
// request header, the status line and the wall-clock arithmetic that keeps a slow server from
// holding a post past its limit.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_http.cpp ../comms/http_parse.cpp -o "${TMPDIR:-/tmp}/test_http" && "${TMPDIR:-/tmp}/test_http"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_http.cpp ../comms/http_parse.cpp -o "${TMPDIR:-/tmp}/test_http_san" && "${TMPDIR:-/tmp}/test_http_san"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "../comms/http_parse.h"
#include "../config.h"

static int g_checks = 0;
static int g_failed = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        g_checks++;                                                          \
        if (!(cond)) {                                                       \
            g_failed++;                                                      \
            std::printf("FAIL line %d: %s\n", __LINE__, #cond);              \
        }                                                                    \
    } while (0)

static bool g_tls = false;

static void testUrl() {
    char host[64], path[96];
    uint16_t port = 0;
    CHECK(httpParseUrl("http://your-backend-url/api/v1/telemetry", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(std::strcmp(host, "your-backend-url") == 0 && port == 80 && std::strcmp(path, "/api/v1/telemetry") == 0);
    CHECK(httpParseUrl("http://192.168.1.20:8000/api/v1/telemetry", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(std::strcmp(host, "192.168.1.20") == 0 && port == 8000 && httpHostIsIp(host));
    CHECK(httpParseUrl("http://host", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(std::strcmp(path, "/") == 0 && port == 80);
    // http and https. nothing malformed
    CHECK(httpParseUrl("https://host/x", host, sizeof host, &port, path, sizeof path, &g_tls) && g_tls && port == 443);
    CHECK(!httpParseUrl("host/x", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http:///x", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://host:/x", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://host:0/x", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://host:70000/x", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://host:80a/x", host, sizeof host, &port, path, sizeof path, &g_tls));
    // too long for the buffers
    std::string longHost = "http://" + std::string(100, 'a') + "/x";
    CHECK(!httpParseUrl(longHost.c_str(), host, sizeof host, &port, path, sizeof path, &g_tls));
    std::string longPath = "http://h/" + std::string(200, 'p');
    CHECK(!httpParseUrl(longPath.c_str(), host, sizeof host, &port, path, sizeof path, &g_tls));
    // dotted addresses need no lookup
    CHECK(httpHostIsIp("10.0.0.1") && httpHostIsIp("255.255.255.255"));
    CHECK(!httpHostIsIp("example.com") && !httpHostIsIp("1.2.3") && !httpHostIsIp("1.2.3.4.5"));
    CHECK(!httpHostIsIp("1..2.3") && !httpHostIsIp("1234.1.1.1") && !httpHostIsIp(""));
}

static void testHeader() {
    char h[320];
    size_t n = httpBuildHeader(h, sizeof h, "api.example.org", 80, false, "/api/v1/telemetry", "key123", "PHAEMOS-hub/test", 1234);
    CHECK(n > 0 && n == std::strlen(h));
    CHECK(std::strncmp(h, "POST /api/v1/telemetry HTTP/1.1\r\n", 33) == 0);
    CHECK(std::strstr(h, "Host: api.example.org\r\n") != nullptr);
    CHECK(std::strstr(h, "X-API-Key: key123\r\n") != nullptr);
    CHECK(std::strstr(h, "User-Agent: PHAEMOS-hub/test\r\n") != nullptr);
    CHECK(std::strstr(h, "Content-Length: 1234\r\n") != nullptr);
    CHECK(std::strstr(h, "Content-Type: application/json\r\n") != nullptr);
    CHECK(std::strstr(h, "Connection: close\r\n") != nullptr);
    CHECK(n >= 4 && std::strcmp(h + n - 4, "\r\n\r\n") == 0);
    // a port other than 80 goes in the Host header
    httpBuildHeader(h, sizeof h, "10.0.0.1", 8000, false, "/x", "k", "ua", 5);
    CHECK(std::strstr(h, "Host: 10.0.0.1:8000\r\n") != nullptr);
    // too small a buffer is refused and never overrun
    char tiny[20];
    CHECK(httpBuildHeader(tiny, sizeof tiny, "a", 80, false, "/x", "k", "ua", 5) == 0);
}

static void testStatusLine() {
    CHECK(httpParseStatusLine("HTTP/1.1 200 OK") == 200);
    CHECK(httpParseStatusLine("HTTP/1.1 201 Created") == 201);
    CHECK(httpParseStatusLine("HTTP/1.0 422 Unprocessable Entity") == 422);
    CHECK(httpParseStatusLine("HTTP/1.1 500") == 500);
    CHECK(httpParseStatusLine("HTTP/1.1 2000 OK") == -1);
    CHECK(httpParseStatusLine("HTTP/1.1 20 OK") == -1);
    CHECK(httpParseStatusLine("HTTP/2 200") == -1);
    CHECK(httpParseStatusLine("HTTP/1.1200 OK") == -1);
    CHECK(httpParseStatusLine("hello") == -1);
    CHECK(httpParseStatusLine("") == -1);
    CHECK(httpParseStatusLine("HTTP/1.1 2x0 OK") == -1);
}

static void testLineReader() {
    HttpLine l;
    httpLineInit(&l);
    const char* in = "HTTP/1.1 200 OK\r\nServer: x\r\n";
    bool done = false;
    for (const char* c = in; *c && !done; c++) done = httpLineFeed(&l, *c);
    CHECK(done && std::strcmp(l.buf, "HTTP/1.1 200 OK") == 0);
    // a line longer than the buffer is cut and never overruns it
    httpLineInit(&l);
    for (int i = 0; i < 5000; i++) CHECK(!httpLineFeed(&l, 'x'));
    CHECK(l.len < sizeof l.buf);
    CHECK(httpLineFeed(&l, '\n'));
    // a header dripped one byte at a time never completes without a line end
    httpLineInit(&l);
    for (int i = 0; i < 100; i++) CHECK(!httpLineFeed(&l, 'H'));
}

static void testDeadline() {
    // the post has POST_WALL_CLOCK_MS in all, whatever the server does between bytes
    CHECK(httpRemainingMs(1000, 1000, POST_WALL_CLOCK_MS) == POST_WALL_CLOCK_MS);
    CHECK(httpRemainingMs(1000, 1000 + 5000, POST_WALL_CLOCK_MS) == POST_WALL_CLOCK_MS - 5000);
    CHECK(httpRemainingMs(1000, 1000 + POST_WALL_CLOCK_MS - 1, POST_WALL_CLOCK_MS) == 1);
    CHECK(httpRemainingMs(1000, 1000 + POST_WALL_CLOCK_MS, POST_WALL_CLOCK_MS) == 0);
    CHECK(httpRemainingMs(1000, 1000 + 10 * POST_WALL_CLOCK_MS, POST_WALL_CLOCK_MS) == 0);
    // across a millis() wrap
    uint32_t start = 0xFFFFFF00u;
    CHECK(httpRemainingMs(start, start + 1000, POST_WALL_CLOCK_MS) == POST_WALL_CLOCK_MS - 1000);
    CHECK(httpRemainingMs(start, start + POST_WALL_CLOCK_MS, POST_WALL_CLOCK_MS) == 0);

    // the longest a post can be busy: the wall clock. at most one more blocking step. that
    // stays under the main loop's busy limit
    CHECK(POST_WALL_CLOCK_MS + HTTP_CONNECT_TIMEOUT_MS < POST_BUSY_LIMIT_MS);
    CHECK(POST_WALL_CLOCK_MS == 20000);
}


static bool feedAll(HttpReader* r, const char* s) {
    for (; *s; s++) if (httpReaderFeed(r, *s)) return true;
    return false;
}

static void testReader() {
    HttpReader r;
    // a plain status line
    httpReaderInit(&r);
    CHECK(feedAll(&r, "HTTP/1.1 200 OK\r\n") && r.code == 200);
    // a leading blank line is tolerated
    httpReaderInit(&r);
    CHECK(feedAll(&r, "\r\nHTTP/1.1 201 Created\r\n") && r.code == 201);
    httpReaderInit(&r);
    CHECK(feedAll(&r, "\n\r\n\nHTTP/1.1 204 No Content\r\n") && r.code == 204);
    // a 100 Continue and its header block are not final. the real status follows
    httpReaderInit(&r);
    CHECK(!feedAll(&r, "HTTP/1.1 100 Continue\r\n\r\n"));
    CHECK(feedAll(&r, "HTTP/1.1 200 OK\r\n") && r.code == 200);
    // a 1xx with headers
    httpReaderInit(&r);
    CHECK(!feedAll(&r, "HTTP/1.1 103 Early Hints\r\nLink: </a>\r\n\r\n"));
    CHECK(feedAll(&r, "HTTP/1.1 422 Unprocessable\r\n") && r.code == 422);
    // a redirect is a final status: this client does not follow it
    httpReaderInit(&r);
    CHECK(feedAll(&r, "HTTP/1.1 301 Moved\r\nLocation: https://x/\r\n") && r.code == 301);
    // junk is final and not a status
    httpReaderInit(&r);
    CHECK(feedAll(&r, "garbage\r\n") && r.code == -1);
    CHECK(httpIsInformational(100) && httpIsInformational(199) && !httpIsInformational(200) && !httpIsInformational(99));
}

static void testControlCharacters() {
    char host[64], path[128];
    uint16_t port;
    CHECK(httpParseUrl("http://h.example/api", host, sizeof host, &port, path, sizeof path, &g_tls));
    // CR, LF, space, tab, NUL-adjacent control characters and DEL in the path would split the request
    CHECK(!httpParseUrl("http://h.example/a\r\nX-Evil: 1", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://h.example/a\nb", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://h.example/a\rb", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://h.example/a b", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://h.example/a\tb", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://h.example/a\x7f", host, sizeof host, &port, path, sizeof path, &g_tls));
    CHECK(!httpParseUrl("http://h\r\n.example/", host, sizeof host, &port, path, sizeof path, &g_tls));
    // and no https
    CHECK(httpParseUrl("https://h.example/api", host, sizeof host, &port, path, sizeof path, &g_tls) && g_tls);
    // every control character in the path is refused
    for (int c = 1; c <= 0x20; c++) {
        char u[64];
        std::snprintf(u, sizeof u, "http://h.example/a%cb", c);
        CHECK(!httpParseUrl(u, host, sizeof host, &port, path, sizeof path, &g_tls));
    }
}

static void testTlsRules() {
    char host[64], path[96];
    uint16_t port = 0;
    bool tls = false;
    // scheme and default port
    CHECK(httpParseUrl("https://api.example.org/api/v1/telemetry", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(tls && port == 443 && std::strcmp(host, "api.example.org") == 0);
    CHECK(httpParseUrl("https://api.example.org:8443/x", host, sizeof host, &port, path, sizeof path, &tls) && tls && port == 8443);
    CHECK(httpParseUrl("http://api.example.org/x", host, sizeof host, &port, path, sizeof path, &tls) && !tls && port == 80);
    // schemes that are neither
    CHECK(!httpParseUrl("ftp://h/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("HTTPS://h/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("https:/h/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("https://", host, sizeof host, &port, path, sizeof path, &tls));
    // user info, brackets and other characters never belong in a host
    CHECK(!httpParseUrl("https://user@host/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("https://user:pw@host/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("https://[::1]/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("https://ho st/x", host, sizeof host, &port, path, sizeof path, &tls));
    CHECK(!httpParseUrl("https://h%41/x", host, sizeof host, &port, path, sizeof path, &tls));
    // the policy: plain only with the bench flag. TLS only to a name
    CHECK(httpUrlPolicy(true, false, "api.example.org") == URL_OK);
    CHECK(httpUrlPolicy(true, true, "api.example.org") == URL_OK);
    CHECK(httpUrlPolicy(false, false, "api.example.org") == URL_REFUSED_PLAIN);
    CHECK(httpUrlPolicy(false, true, "api.example.org") == URL_OK);
    CHECK(httpUrlPolicy(false, false, "10.0.0.1") == URL_REFUSED_PLAIN);
    CHECK(httpUrlPolicy(true, false, "10.0.0.1") == URL_REFUSED_TLS_IP);
    CHECK(httpUrlPolicy(true, true, "192.168.1.20") == URL_REFUSED_TLS_IP);
    // the Host header omits the default port for the scheme only
    char h[360];
    httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "k", "ua", 5);
    CHECK(std::strstr(h, "Host: a.example\r\n") != nullptr);
    httpBuildHeader(h, sizeof h, "a.example", 80, true, "/x", "k", "ua", 5);
    CHECK(std::strstr(h, "Host: a.example:80\r\n") != nullptr);
    httpBuildHeader(h, sizeof h, "a.example", 443, false, "/x", "k", "ua", 5);
    CHECK(std::strstr(h, "Host: a.example:443\r\n") != nullptr);
    // a key or an agent with a control character, a space or a DEL is never sent
    CHECK(httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "k\r\nX-Evil: 1", "ua", 5) == 0);
    CHECK(httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "k\n", "ua", 5) == 0);
    CHECK(httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "a b", "ua", 5) == 0);
    CHECK(httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "k", "u\ra", 5) == 0);
    CHECK(httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "k\x7f", "ua", 5) == 0);
    CHECK(httpBuildHeader(h, sizeof h, "a.example", 443, true, "/x", "good-key_1.2", "ua", 5) > 0);
}

static void testTlsBudget() {
    uint32_t c = 0, hs = 0;
    const uint32_t CONNECT = HTTP_CONNECT_TIMEOUT_MS, HANDSHAKE = HTTP_TLS_HANDSHAKE_MS, RESERVE = HTTP_TLS_RESERVE_MS;
    const uint32_t MINC = HTTP_TLS_MIN_CONNECT_MS, MINH = HTTP_TLS_MIN_HANDSHAKE_MS;
    // the minimums are the decision: a handshake is documented at one to three seconds, so it is never
    // started with less than three and a connect never with less than one
    CHECK(MINH == 3000 && MINC == 1000);
    // a full budget leaves the caps
    CHECK(httpTlsPlan(POST_WALL_CLOCK_MS, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs));
    CHECK(c == CONNECT && hs == HANDSHAKE);
    // the plan never promises more than the budget has, never less than the minimums and refuses
    // exactly when the minimums do not fit
    uint32_t firstOk = 0;
    for (uint32_t left = 0; left <= POST_WALL_CLOCK_MS + 5000; left += 10) {
        bool ok = httpTlsPlan(left, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs);
        if (ok) {
            if (firstOk == 0) firstOk = left;
            CHECK(c >= MINC && hs >= MINH);
            CHECK(c <= CONNECT && hs <= HANDSHAKE);
            CHECK(c + hs + RESERVE <= left);
        } else {
            // refused exactly when the minimums cannot both be met out of what remains after the reserve
            uint32_t avail = left > RESERVE ? left - RESERVE : 0;
            uint32_t conn = avail / 3 > CONNECT ? CONNECT : avail / 3;
            uint32_t hand = avail - conn > HANDSHAKE ? HANDSHAKE : avail - conn;
            CHECK(left <= RESERVE || conn < MINC || hand < MINH);
        }
    }
    // the least time that starts a handshake: after the 3 s reserve a connect gets a third of what
    // remains and the handshake the rest and the handshake needs its 3 s. that is 4,499 ms after the
    // reserve, so 7,499 ms in all. 5 s left is refused and so is 7,498 ms
    CHECK(!httpTlsPlan(5000, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs));
    CHECK(!httpTlsPlan(7498, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs));
    CHECK(httpTlsPlan(7499, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs) && hs == MINH && c == 1499);
    CHECK(firstOk >= 7499 && firstOk <= 7510);
    // a lookup that used 15 s of the 20 s leaves 5 s: no handshake is started
    CHECK(!httpTlsPlan(POST_WALL_CLOCK_MS - 15000, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs));
    // 10 s left after a slow lookup: a shorter handshake that still gets its minimum and fits
    CHECK(httpTlsPlan(10000, CONNECT, HANDSHAKE, RESERVE, MINC, MINH, &c, &hs));
    CHECK(hs >= MINH && c + hs + RESERVE <= 10000);
    // with no lookup time spent every phase at its cap plus the reserve fits the wall clock
    CHECK(CONNECT + HANDSHAKE + RESERVE <= POST_WALL_CLOCK_MS);
    // the wall clock helper still agrees across the millis() wrap
    CHECK(httpRemainingMs(0xFFFFFF00u, 0xFFFFFF00u + 1000u, POST_WALL_CLOCK_MS) == POST_WALL_CLOCK_MS - 1000);
    CHECK(httpRemainingMs(0xFFFFFF00u, (uint32_t)(0xFFFFFF00u + POST_WALL_CLOCK_MS), POST_WALL_CLOCK_MS) == 0);
}

// a scripted stream with a virtual clock. bytes arrive at scripted times. nothing sleeps for real
struct ScriptedStream : HttpStream {
    struct Item { uint32_t atMs; char c; };
    std::vector<Item> items;
    size_t   next = 0;
    uint32_t now = 0;
    bool     closeAfterScript = false;
    bool     closes = false;
    uint32_t closedAtMs = 0;
    uint32_t reads = 0, pauses = 0, maxNow = 0;
    int available() override {
        return (next < items.size() && items[next].atMs <= now) ? 1 : 0;
    }
    int read() override {
        if (next < items.size() && items[next].atMs <= now) { reads++; return (unsigned char)items[next++].c; }
        return -1;
    }
    bool connected() override { return !(closes && (uint32_t)(now - closedAtMs) < 0x80000000u); }
    void pause(uint32_t ms) override { pauses++; now += ms; if (now > maxNow) maxNow = now; }
    uint32_t nowMs() override { if (now > maxNow) maxNow = now; return now; }
    void at(uint32_t t, const char* text) { for (; *text; text++) items.push_back({ t, *text }); }
};

static void testReadResponse() {
    const uint32_t LIMIT = POST_WALL_CLOCK_MS;
    // a plain answer
    {
        ScriptedStream s; s.now = 1000;
        s.at(1000, "HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n");
        HttpResponse r = httpReadResponse(s, 1000, LIMIT);
        CHECK(r.code == 200 && r.retryAfterSec == 0);
        CHECK(s.next < s.items.size());                       // it stopped at the status line and read no more
    }
    // a 429 with Retry-After and other headers
    {
        ScriptedStream s; s.now = 0;
        s.at(0, "HTTP/1.1 429 Too Many Requests\r\nServer: x\r\nRetry-After: 45\r\nContent-Length: 0\r\n\r\nbody");
        HttpResponse r = httpReadResponse(s, 0, LIMIT);
        CHECK(r.code == 429 && r.retryAfterSec == 45);
        CHECK(s.next == s.items.size() - 4);                  // it stopped at the blank line
    }
    // a 100 Continue, then the real answer
    {
        ScriptedStream s;
        s.at(0, "HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 401 Unauthorized\r\n");
        CHECK(httpReadResponse(s, 0, LIMIT).code == 401);
    }
    // a server that drips one byte every 1.9 s: the read ends at the wall clock and not before
    // the server stops. the status line is long enough that a patient server would keep it going
    // for minutes
    {
        ScriptedStream s;
        std::string line = "HTTP/1.1 200 OK\r\n";
        for (size_t i = 0; i < line.size(); i++) s.items.push_back({ (uint32_t)(i * 1900), line[i] });
        HttpResponse r = httpReadResponse(s, 0, LIMIT);
        CHECK(r.code == -1);
        CHECK(s.maxNow >= LIMIT && s.maxNow < LIMIT + 2000);  // ended at the budget, within one wait
        CHECK(s.reads <= LIMIT / 1900 + 2);
    }
    // header lines every 1.9 s on a 429: the budget ends it and the status is kept
    {
        ScriptedStream s;
        std::string head = "HTTP/1.1 429 Too Many Requests\r\n";
        s.at(0, head.c_str());
        uint32_t t = 1900;
        for (int i = 0; i < 40; i++, t += 1900) s.at(t, "X-Pad: 1\r\n");
        HttpResponse r = httpReadResponse(s, 0, LIMIT);
        CHECK(r.code == 429 && r.retryAfterSec == 0);
        CHECK(s.maxNow >= LIMIT && s.maxNow < LIMIT + 2000);
    }
    // a server that never answers: the budget ends it
    {
        ScriptedStream s;
        HttpResponse r = httpReadResponse(s, 0, LIMIT);
        CHECK(r.code == -1 && s.maxNow >= LIMIT && s.maxNow < LIMIT + 10);
    }
    // a server that closes at once: no waiting for the budget
    {
        ScriptedStream s;
        s.closes = true; s.closedAtMs = 0;
        HttpResponse r = httpReadResponse(s, 0, LIMIT);
        CHECK(r.code == -1 && s.maxNow < 100);
    }
    // a server that closes after a partial line
    {
        ScriptedStream s;
        s.at(0, "HTTP/1.1 2");
        s.closes = true; s.closedAtMs = 300;
        HttpResponse r = httpReadResponse(s, 0, LIMIT);
        CHECK(r.code == -1 && s.maxNow < 1000);
    }
    // across a millis() wrap
    {
        ScriptedStream s; s.now = 0xFFFFFF00u;
        s.at(0xFFFFFF00u, "HTTP/1.1 204 No Content\r\n");
        CHECK(httpReadResponse(s, 0xFFFFFF00u, LIMIT).code == 204);
        ScriptedStream d; d.now = 0xFFFFFF00u;
        HttpResponse r = httpReadResponse(d, 0xFFFFFF00u, LIMIT);
        CHECK(r.code == -1 && (uint32_t)(d.now - 0xFFFFFF00u) >= LIMIT);
    }
    // junk is a final answer with no code
    {
        ScriptedStream s;
        s.at(0, "garbage\r\n");
        CHECK(httpReadResponse(s, 0, LIMIT).code == -1);
    }
}

static void testRetryAfter() {
    uint32_t v = 0;
    CHECK(httpParseRetryAfter("Retry-After: 120", &v) && v == 120);
    CHECK(httpParseRetryAfter("retry-after:5", &v) && v == 5);
    CHECK(httpParseRetryAfter("RETRY-AFTER:   30  ", &v) && v == 30);
    CHECK(httpParseRetryAfter("Retry-After: 0", &v) && v == 0);
    CHECK(httpParseRetryAfter("Retry-After: 99999999999999", &v) && v == 86400);       // capped, never overflows
    CHECK(!httpParseRetryAfter("Retry-After: Wed, 21 Oct 2026 07:28:00 GMT", &v));       // the date form is not read
    CHECK(!httpParseRetryAfter("Retry-After:", &v));
    CHECK(!httpParseRetryAfter("Retry-After: -5", &v));
    CHECK(!httpParseRetryAfter("Retry-After: 1x", &v));
    CHECK(!httpParseRetryAfter("X-Retry-After: 5", &v));
    CHECK(!httpParseRetryAfter("Content-Length: 5", &v));
    CHECK(!httpParseRetryAfter("", &v));
}

int main() {
    testUrl();
    testHeader();
    testStatusLine();
    testLineReader();
    testDeadline();
    testReader();
    testControlCharacters();
    testTlsRules();
    testTlsBudget();
    testReadResponse();
    testRetryAfter();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
