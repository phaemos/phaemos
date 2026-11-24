// test_tls.cpp - host test of comms/tls_checks.cpp: the certificate date check the hub makes itself
// (the pinned core's mbedTLS never looks at dates) and the TLS version rule. it covers a clock before
// the certificate, inside it, after it, the boundary seconds on both ends, a far-future clock, an
// unset clock, malformed times, a certificate that ends before it starts, leap days and the whole
// chain rule (every certificate presented has to be valid).
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_tls.cpp ../comms/tls_checks.cpp -o "${TMPDIR:-/tmp}/test_tls" && "${TMPDIR:-/tmp}/test_tls"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_tls.cpp ../comms/tls_checks.cpp -o "${TMPDIR:-/tmp}/test_tls_san" && "${TMPDIR:-/tmp}/test_tls_san"

#include <cstdio>
#include <ctime>
#include <vector>

#include "../comms/tls_checks.h"

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

static int64_t ep(CertTime t) {
    int64_t e = 0;
    return certTimeToEpoch(t, &e) ? e : -1;
}

static void testEpoch() {
    CHECK(ep({ 1970, 1, 1, 0, 0, 0 }) == 0);
    CHECK(ep({ 2026, 1, 1, 0, 0, 0 }) == 1767225600LL);
    CHECK(ep({ 2026, 11, 22, 12, 30, 15 }) == 1795305600LL + 12 * 3600 + 30 * 60 + 15);
    CHECK(ep({ 2000, 2, 29, 0, 0, 0 }) == 951782400LL);                  // 2000 was a leap year
    CHECK(ep({ 2038, 1, 19, 3, 14, 8 }) == 2147483648LL);                // past a 32 bit time_t
    // every day from 1970 to 2100 against the C library's own calendar
    for (int y = 1970; y <= 2100; y += 3) {
        for (int m = 1; m <= 12; m++) {
            for (int d : { 1, 15, 28 }) {
                struct tm tmv = {};
                tmv.tm_year = y - 1900; tmv.tm_mon = m - 1; tmv.tm_mday = d; tmv.tm_hour = 13; tmv.tm_min = 7; tmv.tm_sec = 59;
                time_t ref = timegm(&tmv);
                CHECK(ep({ y, m, d, 13, 7, 59 }) == (int64_t)ref);
            }
        }
    }
    // dates that do not exist
    CHECK(ep({ 2026, 13, 1, 0, 0, 0 }) == -1);
    CHECK(ep({ 2026, 0, 1, 0, 0, 0 }) == -1);
    CHECK(ep({ 2026, 2, 29, 0, 0, 0 }) == -1);                           // 2026 is not a leap year
    CHECK(ep({ 1900, 2, 29, 0, 0, 0 }) == -1);
    CHECK(ep({ 2026, 4, 31, 0, 0, 0 }) == -1);
    CHECK(ep({ 2026, 1, 0, 0, 0, 0 }) == -1);
    CHECK(ep({ 2026, 1, 1, 24, 0, 0 }) == -1);
    CHECK(ep({ 2026, 1, 1, 0, 60, 0 }) == -1);
    CHECK(ep({ 2026, 1, 1, 0, 0, 60 }) == -1);
    CHECK(ep({ 2026, 1, 1, -1, 0, 0 }) == -1);
    CHECK(ep({ 1969, 12, 31, 23, 59, 59 }) == -1);
    CHECK(ep({ 10000, 1, 1, 0, 0, 0 }) == -1);
    CHECK(ep({ 0, 0, 0, 0, 0, 0 }) == -1);
}

static void testDates() {
    const CertTime from = { 2026, 3, 1, 12, 0, 0 };
    const CertTime to   = { 2026, 6, 1, 12, 0, 0 };
    int64_t a = ep(from), b = ep(to);
    const int64_t floorE = 1767225600LL;
    // before, the first second, inside, the last second, after
    CHECK(!certDatesValid(from, to, a - 1, floorE));
    CHECK(certDatesValid(from, to, a, floorE));
    CHECK(certDatesValid(from, to, a + 1, floorE));
    CHECK(certDatesValid(from, to, (a + b) / 2, floorE));
    CHECK(certDatesValid(from, to, b - 1, floorE));
    CHECK(certDatesValid(from, to, b, floorE));
    CHECK(!certDatesValid(from, to, b + 1, floorE));
    // a far-future clock, a clock that wrapped to a tiny value, a negative clock, zero
    CHECK(!certDatesValid(from, to, 4102444800LL, floorE));              // 2100
    CHECK(!certDatesValid(from, to, 253402300799LL, floorE));            // the year 9999
    CHECK(!certDatesValid(from, to, 5, floorE));
    CHECK(!certDatesValid(from, to, 0, floorE));
    CHECK(!certDatesValid(from, to, -1, floorE));
    // a clock before the build date is not a clock, even when the certificate would cover it
    CertTime longFrom = { 2020, 1, 1, 0, 0, 0 }, longTo = { 2035, 1, 1, 0, 0, 0 };
    CHECK(certDatesValid(longFrom, longTo, floorE + 10, floorE));
    CHECK(!certDatesValid(longFrom, longTo, floorE - 1, floorE));
    CHECK(!certDatesValid(longFrom, longTo, 1600000000LL, floorE));
    // a malformed bound fails whichever end it is
    CHECK(!certDatesValid({ 2026, 13, 1, 0, 0, 0 }, to, (a + b) / 2, floorE));
    CHECK(!certDatesValid(from, { 2026, 6, 31, 12, 0, 0 }, (a + b) / 2, floorE));
    CHECK(!certDatesValid({ 0, 0, 0, 0, 0, 0 }, { 0, 0, 0, 0, 0, 0 }, (a + b) / 2, floorE));
    // a certificate that ends before it starts is never valid
    CHECK(!certDatesValid(to, from, (a + b) / 2, floorE));
    CHECK(!certDatesValid(to, from, a, floorE));
    // a one second certificate
    CHECK(certDatesValid(from, from, a, floorE));
    CHECK(!certDatesValid(from, from, a + 1, floorE));
    // the same boundaries on a leap day
    CertTime lf = { 2028, 2, 29, 0, 0, 0 }, lt = { 2028, 2, 29, 23, 59, 59 };
    CHECK(certDatesValid(lf, lt, ep(lf), floorE) && certDatesValid(lf, lt, ep(lt), floorE));
    CHECK(!certDatesValid(lf, lt, ep(lt) + 1, floorE) && !certDatesValid(lf, lt, ep(lf) - 1, floorE));
}

// the chain rule the client applies: every certificate presented has to be valid and an empty chain
// is not valid. the same loop is in http_client.cpp, which cannot be built on the host, so the rule
// is stated here over the same function
static bool chainOk(const std::vector<std::pair<CertTime, CertTime>>& chain, int64_t now, int64_t floorE) {
    if (chain.empty()) return false;
    for (const auto& c : chain) if (!certDatesValid(c.first, c.second, now, floorE)) return false;
    return true;
}

static void testChain() {
    const int64_t floorE = 1767225600LL;
    std::pair<CertTime, CertTime> leaf = { { 2026, 10, 1, 0, 0, 0 }, { 2027, 1, 1, 0, 0, 0 } };
    std::pair<CertTime, CertTime> inter = { { 2024, 3, 13, 0, 0, 0 }, { 2027, 3, 12, 23, 59, 59 } };
    std::pair<CertTime, CertTime> expiredInter = { { 2020, 1, 1, 0, 0, 0 }, { 2026, 6, 1, 0, 0, 0 } };
    int64_t now = ep({ 2026, 11, 22, 0, 0, 0 });
    CHECK(chainOk({ leaf, inter }, now, floorE));
    CHECK(!chainOk({}, now, floorE));
    CHECK(!chainOk({ leaf, expiredInter }, now, floorE));                // one expired certificate fails the chain
    CHECK(!chainOk({ expiredInter, inter }, now, floorE));
    CHECK(!chainOk({ leaf, inter }, ep({ 2027, 1, 1, 0, 0, 1 }), floorE));   // the leaf has just ended
    CHECK(!chainOk({ leaf, inter }, ep({ 2026, 9, 30, 23, 59, 59 }), floorE)); // the leaf has not started
}

static void testChainLimit() {
    const int64_t floorE = 1767225600LL;
    int64_t now = ep({ 2026, 11, 22, 0, 0, 0 });
    CertTime okFrom = { 2026, 1, 1, 0, 0, 0 }, okTo = { 2027, 1, 1, 0, 0, 0 };
    CertTime badFrom = { 2020, 1, 1, 0, 0, 0 }, badTo = { 2026, 6, 1, 0, 0, 0 };
    CertTime f[12], t[12];
    size_t bad = 99;
    for (int i = 0; i < 12; i++) { f[i] = okFrom; t[i] = okTo; }
    // ten are walked in full: an expired one in the tenth place is found
    CHECK(certChainValid(f, t, 10, now, floorE, &bad));
    f[9] = badFrom; t[9] = badTo;
    CHECK(!certChainValid(f, t, 10, now, floorE, &bad) && bad == 9);
    // eleven are refused outright, even with an expired certificate hidden in the eleventh place and
    // even when all eleven are valid
    f[9] = okFrom; t[9] = okTo;
    CHECK(!certChainValid(f, t, 11, now, floorE, &bad) && bad == 11);
    f[10] = badFrom; t[10] = badTo;
    CHECK(!certChainValid(f, t, 11, now, floorE, &bad) && bad == 11);
    CHECK(!certChainValid(f, t, 12, now, floorE, nullptr));
    CHECK(!certChainValid(f, t, 0, now, floorE, &bad) && bad == 0);
    CHECK(CERT_CHAIN_MAX == 10);
}

static void testVersion() {
    CHECK(tlsVersionOk("TLSv1.2"));
    CHECK(!tlsVersionOk("TLSv1"));
    CHECK(!tlsVersionOk("TLSv1.0"));
    CHECK(!tlsVersionOk("TLSv1.1"));
    CHECK(!tlsVersionOk("TLSv1.3"));              // not in this core and not accepted if it ever appears
    CHECK(!tlsVersionOk("DTLSv1.2"));
    CHECK(!tlsVersionOk("SSLv3"));
    CHECK(!tlsVersionOk("tlsv1.2"));
    CHECK(!tlsVersionOk("TLSv1.2 "));
    CHECK(!tlsVersionOk(""));
    CHECK(!tlsVersionOk(nullptr));
}

int main() {
    testEpoch();
    testDates();
    testChain();
    testChainLimit();
    testVersion();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
