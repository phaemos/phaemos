// the Arduino and Wi-Fi headers come before the local ones so the ESP32 Arduino core
// types are fully resolved when the local declarations are parsed.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "../config.h"
#include "http_client.h"
#include "http_parse.h"
#include "post_rules.h"
#include "tls_checks.h"
#include "trust_roots.h"

namespace {

// the last address that resolved. a healthy network then costs no lookups. a failed
// lookup is the only thing that can use the pinned core's 15 s DNS wait.
struct DnsCache {
    char       host[64];
    IPAddress  addr;
    uint32_t   atMs;
    bool       valid;
};
DnsCache g_dns = { "", IPAddress(), 0, false };

bool resolve(const char* host, IPAddress* out) {
    if (httpHostIsIp(host)) return out->fromString(host);
    uint32_t now = millis();
    if (g_dns.valid && strcmp(g_dns.host, host) == 0 &&
        (uint32_t)(now - g_dns.atMs) < DNS_CACHE_MS) {
        *out = g_dns.addr;
        return true;
    }
    // WiFiGenericClass::hostByName waits up to 15 s and cannot be cut short. it counts against
    // the wall-clock limit of the post.
    IPAddress addr;
    if (!WiFi.hostByName(host, addr)) return false;
    snprintf(g_dns.host, sizeof g_dns.host, "%s", host);
    g_dns.addr = addr;
    g_dns.atMs = millis();
    g_dns.valid = true;
    *out = addr;
    return true;
}

// the core's WiFiClientSecure keeps its context where only a subclass can reach it. the negotiated
// protocol is read from there after the handshake
class SecureClient : public WiFiClientSecure {
public:
    const char* tlsVersion() { return mbedtls_ssl_get_version(&sslclient->ssl_ctx); }
};

// the socket as the response reader sees it
class SocketStream : public HttpStream {
public:
    explicit SocketStream(WiFiClient* c) : c_(c) {}
    int      available() override { return c_->available(); }
    int      read() override { return c_->read(); }
    bool     connected() override { return c_->connected(); }
    void     pause(uint32_t ms) override { delay(ms); }
    uint32_t nowMs() override { return millis(); }
private:
    WiFiClient* c_;
};

CertTime toCertTime(const mbedtls_x509_time& t) {
    CertTime c = { t.year, t.mon, t.day, t.hour, t.min, t.sec };
    return c;
}

// what the hub checks after the handshake and before it sends anything. the core's mbedTLS is built
// without date checks (see tls_checks.h) so every certificate the server presented is checked here.
// returns false, with the reason on the serial monitor, when the post must not go on
bool tlsAfterHandshake(SecureClient& client) {
    if (!tlsVersionOk(client.tlsVersion())) {
        Serial.print(F("httpPost: refused. the server negotiated "));
        Serial.print(client.tlsVersion() ? client.tlsVersion() : "no version");
        Serial.println(F(" and the hub accepts TLS 1.2 only. nothing was sent"));
        return false;
    }
    int64_t now = (int64_t)time(nullptr);
    if (now < (int64_t)TIME_VALID_MIN_EPOCH) {
        Serial.println(F("httpPost: refused. the clock is before this image was built, so certificate dates cannot be checked. nothing was sent"));
        return false;
    }
    // collect the presented chain (one more than the limit is enough to know it is too long), then apply
    // the rule in tls_checks.cpp, which the host test covers
    CertTime from[CERT_CHAIN_MAX + 1], to[CERT_CHAIN_MAX + 1];
    size_t n = 0;
    for (const mbedtls_x509_crt* c = client.getPeerCertificate(); c != nullptr && n < CERT_CHAIN_MAX + 1; c = c->next) {
        from[n] = toCertTime(c->valid_from);
        to[n] = toCertTime(c->valid_to);
        n++;
    }
    size_t bad = 0;
    if (n == 0) {
        Serial.println(F("httpPost: refused. the server presented no certificate to check. nothing was sent"));
        return false;
    }
    if (!certChainValid(from, to, n, now, (int64_t)TIME_VALID_MIN_EPOCH, &bad)) {
        if (n > CERT_CHAIN_MAX) {
            Serial.println(F("httpPost: refused. the server's chain is longer than ten certificates. nothing was sent"));
        } else {
            Serial.print(F("httpPost: refused. certificate "));
            Serial.print((unsigned)bad + 1);
            Serial.println(F(" of the server's chain is expired or not yet valid by the hub's clock. nothing was sent"));
        }
        return false;
    }
    return true;
}

}  // namespace

HttpResult httpPost(const String& url, const String& payload, const char* apiKey) {
    HttpResult res = { -1, 0, 0 };
    // check WiFi status up front and return -1 immediately rather than
    // letting the client behave unpredictably on a disconnected radio.
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println(F("httpPost: WiFi not connected"));
        return res;
    }

    char host[64], path[96];
    uint16_t port = 80;
    bool tls = false;
    if (!httpParseUrl(url.c_str(), host, sizeof host, &port, path, sizeof path, &tls)) {
        Serial.println(F("httpPost: the address must be https://host[:port]/path"));
        return res;
    }
    // the policy lives here and not only where the address is stored, so no caller can post
    // anywhere it should not
    UrlPolicy policy = httpUrlPolicy(tls, ALLOW_PLAIN_HTTP != 0, host);
    if (policy == URL_REFUSED_PLAIN) {
        Serial.println(F("httpPost: refused. a plain http:// address would send the key and the readings in clear. use https://"));
        return res;
    }
    if (policy == URL_REFUSED_TLS_IP) {
        Serial.println(F("httpPost: refused. an https:// address needs a host name, because the certificate is checked against the name"));
        return res;
    }
    if (tls && trustRootsArePlaceholders()) {
        Serial.println(F("httpPost: refused. comms/trust_roots.h still holds placeholders, so a TLS connection could not be verified"));
        return res;
    }

    // the whole post (resolve, connect, handshake, send and read the status line) shares one
    // wall-clock budget that this function enforces itself. the library's own timeouts are gaps
    // between events, so a server that drips one header line every 1.9 s could keep a library post
    // busy for ever.
    uint32_t start = millis();

    IPAddress addr;
    if (!resolve(host, &addr)) {
        Serial.println(F("httpPost: the host did not resolve"));
        return res;
    }

    uint32_t left = httpRemainingMs(start, millis(), POST_WALL_CLOCK_MS);
    uint32_t connectMs = left < HTTP_CONNECT_TIMEOUT_MS ? left : HTTP_CONNECT_TIMEOUT_MS;
    uint32_t handshakeMs = 0;
    if (tls) {
        if (!httpTlsPlan(left, HTTP_CONNECT_TIMEOUT_MS, HTTP_TLS_HANDSHAKE_MS, HTTP_TLS_RESERVE_MS,
                         HTTP_TLS_MIN_CONNECT_MS, HTTP_TLS_MIN_HANDSHAKE_MS, &connectMs, &handshakeMs)) {
            Serial.println(F("httpPost: not enough time left after the lookup for a TLS handshake"));
            return res;
        }
    } else if (left < 500) {
        Serial.println(F("httpPost: out of time after the lookup"));
        return res;
    }

    WiFiClient plain;
    SecureClient secure;
    WiFiClient* client = &plain;
    uint32_t connectStart = millis();
    bool connected;
    if (tls) {
        // verified against the pinned roots and never setInsecure(). the host name goes to the
        // connect call so the certificate is checked against the name and not the address
        client = &secure;
        secure.setCACert(TRUST_ROOTS_PEM);
        secure.setTimeout((connectMs + 999) / 1000);
        secure.setHandshakeTimeout(handshakeMs / 1000 > 0 ? handshakeMs / 1000 : 1);
        connected = secure.connect(addr, port, host, TRUST_ROOTS_PEM, nullptr, nullptr) != 0;
    } else {
        connected = plain.connect(addr, port, (int32_t)connectMs) != 0;
    }
    if (!connected) {
        Serial.println(tls ? F("httpPost: could not connect or the TLS handshake failed (certificate, clock or time-out)")
                           : F("httpPost: could not connect"));
        // the address may be stale (the backend moved or Wi-Fi came back on another network), so
        // the next post looks it up again
        g_dns.valid = false;
        return res;
    }
    if (tls) {
        res.handshakeMs = (uint32_t)(millis() - connectStart);
        // dates and protocol version are checked here, before any header or the key is written
        if (!tlsAfterHandshake(secure)) {
            secure.stop();
            return res;
        }
    }

    // send the header and then the body in short pieces. the send buffer holds a whole body, so
    // a write returns at once unless the peer has stopped reading. the budget is checked
    // between pieces.
    char header[360];
    size_t hlen = httpBuildHeader(header, sizeof header, host, port, tls, path, apiKey,
                                  "PHAEMOS-hub/" FIRMWARE_VERSION, payload.length());
    if (hlen == 0) {
        client->stop();
        Serial.println(F("httpPost: the request header does not fit or holds a bad character, so nothing was sent"));
        return res;
    }
    const uint8_t* parts[2]  = { (const uint8_t*)header, (const uint8_t*)payload.c_str() };
    size_t         lens[2]   = { hlen, (size_t)payload.length() };
    for (int i = 0; i < 2; i++) {
        size_t sent = 0;
        while (sent < lens[i]) {
            if (httpRemainingMs(start, millis(), POST_WALL_CLOCK_MS) == 0) {
                client->stop();
                Serial.println(F("httpPost: out of time while sending"));
                return res;
            }
            size_t chunk = lens[i] - sent;
            if (chunk > 512) chunk = 512;
            size_t n = client->write(parts[i] + sent, chunk);
            if (n == 0) {
                client->stop();
                Serial.println(F("httpPost: the write failed"));
                return res;
            }
            sent += n;
        }
    }

    // read the final status line. a 429 also has its headers read, up to the blank line, for a
    // Retry-After. the connection is closed after that so whatever the server goes on to send
    // does not matter. the reader is the one the host test drives with a scripted slow stream
    SocketStream stream(client);
    HttpResponse resp = httpReadResponse(stream, start, POST_WALL_CLOCK_MS);
    int code = resp.code;
    res.retryAfterSec = resp.retryAfterSec;
    client->stop();
    res.code = code;
    if (code < 0) Serial.println(F("httpPost: no status line before the time ran out"));
    return res;
}
