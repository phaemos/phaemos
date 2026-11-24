// tls_checks.h - checks the hub makes itself on a TLS connection, because the pinned core's mbedTLS
// is built without them. no Arduino types, so the host test covers them.
//
// the core is precompiled with CONFIG_MBEDTLS_HAVE_TIME_DATE unset (tools/sdk/esp32/sdkconfig).
// mbedtls_x509_time_is_past and mbedtls_x509_time_is_future are then each "return 0" (confirmed with
// objdump on the built firmware.elf), so the handshake never looks at a certificate's dates. the
// signature chain and the trust root are still verified. the dates are not. so we check them after
// the handshake and before anything is sent:
//   every certificate the server presented (the leaf and any intermediates) has to be valid now
//   the clock has to be plausible (not before the build date)
//   the negotiated protocol has to be TLS 1.2
// not checked: the pinned roots' own dates. a root is not part of what the server presents. the
// ISRG roots expire in 2035 and 2040 and are rechecked whenever an image is rebuilt.
#pragma once

#include <stddef.h>
#include <stdint.h>

// a certificate time as mbedTLS keeps it (UTC)
struct CertTime {
    int year, mon, day, hour, min, sec;
};

// seconds since 1970 for a calendar time. false when a field is out of range or the date does not
// exist (month 13, 30 February, hour 24 and so on). the range is 1970 to 9999.
bool certTimeToEpoch(const CertTime& t, int64_t* epoch);

// true when from <= now <= to. both bounds are inclusive, as in mbedTLS (past means now > to, future
// means now < from). false for a malformed bound, for a certificate whose to is before its from and
// for a clock that is not plausible (nowEpoch < floorEpoch, negative or zero).
bool certDatesValid(const CertTime& from, const CertTime& to, int64_t nowEpoch, int64_t floorEpoch);

// the rule over a whole chain. n certificates (leaf first) with their bounds. false for an empty
// chain, for more than CERT_CHAIN_MAX certificates (a chain that long is refused and never cut short,
// because stopping early would leave the rest with their dates unchecked) and when any one is not
// valid. *badIndex, when given, is the first certificate that failed (n for a chain that is too long).
#define CERT_CHAIN_MAX 10
bool certChainValid(const CertTime* from, const CertTime* to, size_t n, int64_t nowEpoch, int64_t floorEpoch,
                    size_t* badIndex);

// the version string mbedTLS reports ("TLSv1.2"). only TLS 1.2 is accepted. the core's mbedTLS also
// negotiates TLS 1.0 and 1.1 (CONFIG_MBEDTLS_SSL_PROTO_TLS1 and TLS1_1 are set) and its WiFiClientSecure
// has no call to set a minimum, so the hub refuses the connection after the handshake and before it
// sends the key if anything lower was negotiated. there is no TLS 1.3 in this core.
bool tlsVersionOk(const char* version);
