#include "http_parse.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

bool httpParseUrl(const char* url, char* host, size_t hostCap, uint16_t* port,
                  char* path, size_t pathCap, bool* tls) {
    const char* p = url;
    bool secure;
    if (strncmp(p, "https://", 8) == 0) {
        secure = true;
        p += 8;
    } else if (strncmp(p, "http://", 7) == 0) {
        secure = false;
        p += 7;
    } else {
        return false;
    }
    const char* slash = strchr(p, '/');
    size_t authLen = slash ? (size_t)(slash - p) : strlen(p);
    if (authLen == 0) return false;
    const char* colon = (const char*)memchr(p, ':', authLen);
    size_t hostLen = colon ? (size_t)(colon - p) : authLen;
    if (hostLen == 0 || hostLen + 1 > hostCap) return false;
    memcpy(host, p, hostLen);
    host[hostLen] = 0;
    // a host name or a dotted address: letters, digits, dots, hyphens and underscores. that also
    // refuses user info (user@host), brackets and every control character
    for (size_t i = 0; i < hostLen; i++) {
        char c = host[i];
        bool ok = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                  c == '.' || c == '-' || c == '_';
        if (!ok) return false;
    }
    uint32_t prt = secure ? 443 : 80;
    if (colon) {
        prt = 0;
        const char* d = colon + 1;
        if (d >= p + authLen) return false;
        for (; d < p + authLen; d++) {
            if (*d < '0' || *d > '9') return false;
            prt = prt * 10 + (uint32_t)(*d - '0');
            if (prt > 65535) return false;
        }
        if (prt == 0) return false;
    }
    *port = (uint16_t)prt;
    const char* pth = slash ? slash : "/";
    if (strlen(pth) + 1 > pathCap) return false;
    for (const char* c = pth; *c; c++) {
        if ((unsigned char)*c <= 0x20 || (unsigned char)*c == 0x7F) return false;
    }
    strcpy(path, pth);
    *tls = secure;
    return true;
}

UrlPolicy httpUrlPolicy(bool tls, bool allowPlain, const char* host) {
    if (!tls) return allowPlain ? URL_OK : URL_REFUSED_PLAIN;
    if (httpHostIsIp(host)) return URL_REFUSED_TLS_IP;
    return URL_OK;
}

bool httpTlsPlan(uint32_t leftMs, uint32_t connectCapMs, uint32_t handshakeCapMs,
                 uint32_t reserveMs, uint32_t minConnectMs, uint32_t minHandshakeMs,
                 uint32_t* connectMs, uint32_t* handshakeMs) {
    if (leftMs <= reserveMs) return false;
    uint32_t avail = leftMs - reserveMs;
    uint32_t connect = avail / 3;
    if (connect > connectCapMs) connect = connectCapMs;
    if (connect < minConnectMs) return false;
    uint32_t handshake = avail - connect;
    if (handshake > handshakeCapMs) handshake = handshakeCapMs;
    if (handshake < minHandshakeMs) return false;
    *connectMs = connect;
    *handshakeMs = handshake;
    return true;
}

bool httpParseRetryAfter(const char* line, uint32_t* seconds) {
    static const char name[] = "retry-after:";
    size_t i = 0;
    for (; name[i]; i++) {
        char c = line[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        if (c != name[i]) return false;
    }
    const char* p = line + i;
    while (*p == ' ' || *p == '\t') p++;
    if (*p == 0) return false;
    uint32_t v = 0;
    for (; *p; p++) {
        if (*p == ' ' || *p == '\t') break;
        if (*p < '0' || *p > '9') return false;
        v = v * 10 + (uint32_t)(*p - '0');
        if (v > 86400) v = 86400;
    }
    *seconds = v;
    return true;
}

bool httpHostIsIp(const char* host) {
    int dots = 0;
    int digits = 0;
    for (const char* c = host; *c; c++) {
        if (*c == '.') {
            if (digits == 0) return false;
            dots++;
            digits = 0;
        } else if (*c >= '0' && *c <= '9') {
            if (++digits > 3) return false;
        } else {
            return false;
        }
    }
    return dots == 3 && digits > 0;
}

size_t httpBuildHeader(char* out, size_t cap, const char* host, uint16_t port, bool tls,
                       const char* path, const char* apiKey, const char* userAgent, size_t bodyLen) {
    // a value that holds a control character, a space or a DEL could split the request, so
    // none is sent. the key and the agent text can come from storage and not only from the build
    const char* checked[2] = { apiKey, userAgent };
    for (int k = 0; k < 2; k++) {
        for (const char* c = checked[k]; *c; c++) {
            if ((unsigned char)*c < 0x20 || (unsigned char)*c == 0x7F) return 0;
        }
    }
    for (const char* c = apiKey; *c; c++) {
        if (*c == ' ') return 0;
    }
    char hostHeader[96];
    if (port == (tls ? 443 : 80)) snprintf(hostHeader, sizeof hostHeader, "%s", host);
    else            snprintf(hostHeader, sizeof hostHeader, "%s:%u", host, (unsigned)port);
    int n = snprintf(out, cap,
                     "POST %s HTTP/1.1\r\n"
                     "Host: %s\r\n"
                     "Content-Type: application/json\r\n"
                     "User-Agent: %s\r\n"
                     "X-API-Key: %s\r\n"
                     "Content-Length: %u\r\n"
                     "Connection: close\r\n"
                     "\r\n",
                     path, hostHeader, userAgent, apiKey, (unsigned)bodyLen);
    if (n < 0 || (size_t)n >= cap) return 0;
    return (size_t)n;
}

int httpParseStatusLine(const char* line) {
    if (strncmp(line, "HTTP/1.", 7) != 0) return -1;
    if (line[7] != '0' && line[7] != '1') return -1;
    if (line[8] != ' ') return -1;
    const char* c = line + 9;
    if (c[0] < '0' || c[0] > '9' || c[1] < '0' || c[1] > '9' || c[2] < '0' || c[2] > '9') return -1;
    if (c[3] != 0 && c[3] != ' ') return -1;
    return (c[0] - '0') * 100 + (c[1] - '0') * 10 + (c[2] - '0');
}

bool httpIsInformational(int code) {
    return code >= 100 && code < 200;
}

void httpReaderInit(HttpReader* r) {
    httpLineInit(&r->line);
    r->state = 0;
    r->code = -1;
}

bool httpReaderFeed(HttpReader* r, char c) {
    if (!httpLineFeed(&r->line, c)) return false;
    bool blank = r->line.buf[0] == 0;
    int code = r->state == 0 && !blank ? httpParseStatusLine(r->line.buf) : -1;
    httpLineInit(&r->line);
    if (r->state == 1) {
        if (blank) r->state = 0;        // the interim response's headers are over. the real status follows
        return false;
    }
    if (blank) return false;            // a blank line before the status line is ignored
    if (httpIsInformational(code)) {
        r->state = 1;
        return false;
    }
    r->code = code;
    return true;
}

void httpLineInit(HttpLine* l) {
    l->len = 0;
    l->buf[0] = 0;
}

bool httpLineFeed(HttpLine* l, char c) {
    if (c == '\r') return false;
    if (c == '\n') {
        l->buf[l->len] = 0;
        return true;
    }
    if (l->len + 1 < sizeof l->buf) {
        l->buf[l->len++] = c;
        l->buf[l->len] = 0;
    }
    return false;
}

uint32_t httpRemainingMs(uint32_t startMs, uint32_t nowMs, uint32_t limitMs) {
    uint32_t used = (uint32_t)(nowMs - startMs);
    return used >= limitMs ? 0 : limitMs - used;
}

HttpResponse httpReadResponse(HttpStream& s, uint32_t startMs, uint32_t limitMs) {
    HttpResponse res = { -1, 0 };
    HttpReader reader;
    httpReaderInit(&reader);
    HttpLine headerLine;
    httpLineInit(&headerLine);
    bool done = false;
    while (!done && httpRemainingMs(startMs, s.nowMs(), limitMs) > 0) {
        if (s.available() > 0) {
            int c = s.read();
            if (c < 0) break;
            if (res.code < 0) {
                // a 1xx interim response is skipped and the final status is read. a blank line
                // before the status line is ignored
                if (httpReaderFeed(&reader, (char)c)) {
                    res.code = reader.code;
                    // only a 429 has its headers read, for a Retry-After
                    if (res.code != 429) done = true;
                }
            } else if (httpLineFeed(&headerLine, (char)c)) {
                if (headerLine.buf[0] == 0) {
                    done = true;                    // the blank line ends the headers
                } else {
                    uint32_t secs;
                    if (httpParseRetryAfter(headerLine.buf, &secs)) res.retryAfterSec = secs;
                }
                httpLineInit(&headerLine);
            }
        } else if (!s.connected()) {
            break;
        } else {
            s.pause(5);
        }
    }
    return res;
}
