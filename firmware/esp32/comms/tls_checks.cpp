#include "tls_checks.h"

#include <string.h>

namespace {

bool leap(int y) {
    return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
}

int daysInMonth(int y, int m) {
    static const int d[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    return m == 2 && leap(y) ? 29 : d[m - 1];
}

}  // namespace

bool certTimeToEpoch(const CertTime& t, int64_t* epoch) {
    if (t.year < 1970 || t.year > 9999 || t.mon < 1 || t.mon > 12) return false;
    if (t.day < 1 || t.day > daysInMonth(t.year, t.mon)) return false;
    if (t.hour < 0 || t.hour > 23 || t.min < 0 || t.min > 59 || t.sec < 0 || t.sec > 59) return false;
    int64_t days = 0;
    for (int y = 1970; y < t.year; y++) days += leap(y) ? 366 : 365;
    for (int m = 1; m < t.mon; m++) days += daysInMonth(t.year, m);
    days += t.day - 1;
    *epoch = days * 86400 + t.hour * 3600 + t.min * 60 + t.sec;
    return true;
}

bool certDatesValid(const CertTime& from, const CertTime& to, int64_t nowEpoch, int64_t floorEpoch) {
    int64_t a, b;
    if (!certTimeToEpoch(from, &a) || !certTimeToEpoch(to, &b)) return false;
    if (b < a) return false;
    if (nowEpoch <= 0 || nowEpoch < floorEpoch) return false;
    return nowEpoch >= a && nowEpoch <= b;
}

bool certChainValid(const CertTime* from, const CertTime* to, size_t n, int64_t nowEpoch, int64_t floorEpoch,
                    size_t* badIndex) {
    if (n == 0) { if (badIndex) *badIndex = 0; return false; }
    if (n > CERT_CHAIN_MAX) { if (badIndex) *badIndex = n; return false; }
    for (size_t i = 0; i < n; i++) {
        if (!certDatesValid(from[i], to[i], nowEpoch, floorEpoch)) { if (badIndex) *badIndex = i; return false; }
    }
    return true;
}

bool tlsVersionOk(const char* version) {
    return version != nullptr && strcmp(version, "TLSv1.2") == 0;
}
