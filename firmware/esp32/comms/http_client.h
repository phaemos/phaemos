// use #pragma once for the same reason as every other header in this project.
#pragma once

// include WString.h (pulled in by Arduino.h) here indirectly through String
// so callers can use Arduino String without a separate include.
#include <Arduino.h>

// what a post returned. code is the HTTP status (-1 when there was none). retryAfterSec is the
// server's Retry-After on a 429, else 0. handshakeMs is the time TCP connect and the TLS
// handshake took together (0 for a plain post).
struct HttpResult {
    int      code;
    uint32_t retryAfterSec;
    uint32_t handshakeMs;
};

// httpPost - sends a JSON payload to the given URL with an X-API-Key header, over TLS for an
// https:// address (verified against the pinned roots in trust_roots.h, never setInsecure, with the certificate dates and the TLS version checked by the hub itself after
// the handshake: see tls_checks.h) and
// over plain HTTP only when the build allows it (ALLOW_PLAIN_HTTP).
// the whole post, handshake included, stays inside POST_WALL_CLOCK_MS.
// it returns code -1 when Wi-Fi is not connected, when the policy refuses the address or when the
// connection or handshake fails. a 3xx is returned as it is and is not followed.
HttpResult httpPost(const String& url, const String& payload, const char* apiKey);
