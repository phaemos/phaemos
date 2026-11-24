#include "provision.h"

#include <stdio.h>
#include <string.h>

#include "http_parse.h"

namespace {

bool printable(const char* s, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if ((unsigned char)s[i] < 0x20 || (unsigned char)s[i] > 0x7E) return false;
    }
    return true;
}

bool inSet(char c, const char* extra) {
    if ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')) return true;
    for (; *extra; extra++) if (c == *extra) return true;
    return false;
}

bool allIn(const char* s, size_t n, const char* extra) {
    for (size_t i = 0; i < n; i++) if (!inSet(s[i], extra)) return false;
    return true;
}

bool okSsid(const char* v) {
    size_t n = strlen(v);
    return n >= 1 && n <= PROV_SSID_MAX && printable(v, n);
}
bool okPass(const char* v) {
    size_t n = strlen(v);
    return (n == 0 || (n >= 8 && n <= PROV_PASS_MAX)) && printable(v, n);
}
bool okUrl(const char* v, bool allowPlain) {
    // refused, not stripped: the server answers 404 for /api/v1/telemetry/ (it no longer redirects a
    // trailing slash), so an address that ends in one would fail on every post
    if (v[0] != 0 && v[strlen(v) - 1] == '/') return false;
    char host[64], path[96];
    uint16_t port;
    bool tls;
    if (!httpParseUrl(v, host, sizeof host, &port, path, sizeof path, &tls)) return false;
    return httpUrlPolicy(tls, allowPlain, host) == URL_OK;
}
bool okId(const char* v) {
    size_t n = strlen(v);
    return n >= 1 && n <= PROV_ID_MAX && allIn(v, n, "-_");
}
bool okKey(const char* v) {
    size_t n = strlen(v);
    return n >= 16 && n <= PROV_KEY_MAX && allIn(v, n, "-_.~+/=");
}

void say(char* reply, size_t cap, const char* text) {
    if (cap == 0) return;
    snprintf(reply, cap, "%s", text);
}

}  // namespace

void provInit(ProvFields* f) {
    memset(f, 0, sizeof *f);
}

void provWipe(ProvFields* f) {
    // volatile writes so the compiler cannot drop the wipe of a value that is never read again
    volatile char* p = (volatile char*)f;
    for (size_t i = 0; i < sizeof *f; i++) p[i] = 0;
}

bool provValidate(const ProvFields* f, bool allowPlain) {
    // the fields must be terminated inside their arrays
    if (memchr(f->ssid, 0, sizeof f->ssid) == nullptr || memchr(f->pass, 0, sizeof f->pass) == nullptr ||
        memchr(f->url, 0, sizeof f->url) == nullptr || memchr(f->id, 0, sizeof f->id) == nullptr ||
        memchr(f->key, 0, sizeof f->key) == nullptr) return false;
    return okSsid(f->ssid) && okPass(f->pass) && okUrl(f->url, allowPlain) && okId(f->id) && okKey(f->key);
}

ProvResult provLine(ProvFields* f, const char* line, bool allowPlain, char* reply, size_t replyCap) {
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\r' || line[len - 1] == '\n')) len--;
    if (len > PROV_LINE_MAX) {
        say(reply, replyCap, "ERR line too long");
        return PR_BAD_COMMAND;
    }
    char buf[PROV_LINE_MAX + 1];
    memcpy(buf, line, len);
    buf[len] = 0;

    // split the command from its value at the first space
    char* value = strchr(buf, ' ');
    if (value) { *value = 0; value++; } else value = buf + len;
    const char* cmd = buf;

    if (strcmp(cmd, "SHOW") == 0) {
        snprintf(reply, replyCap, "SSID %s | PASS %s | URL %s | ID %s | KEY %s",
                 (f->have & 1) ? f->ssid : "not set", (f->have & 2) ? "set" : "not set",
                 (f->have & 4) ? f->url : "not set", (f->have & 8) ? f->id : "not set",
                 (f->have & 16) ? "set" : "not set");
        return PR_INFO;
    }
    if (strcmp(cmd, "HELP") == 0) {
        say(reply, replyCap, "SSID <text> | PASS <text> | URL <https address> | ID <text> | KEY <text> | SHOW | SAVE | CLEAR");
        return PR_INFO;
    }
    if (strcmp(cmd, "CLEAR") == 0) {
        say(reply, replyCap, "OK clearing stored credentials");
        return PR_CLEAR;
    }
    if (strcmp(cmd, "SAVE") == 0) {
        if ((f->have & PROV_HAVE_ALL) != PROV_HAVE_ALL) {
            say(reply, replyCap, "ERR not all five values are set. send SHOW");
            return PR_INCOMPLETE;
        }
        if (!provValidate(f, allowPlain)) {
            say(reply, replyCap, "ERR a value is not valid. send the values again");
            return PR_BAD_VALUE;
        }
        say(reply, replyCap, "OK saving and restarting");
        return PR_SAVE;
    }

    struct Field { const char* name; char* dst; size_t cap; uint8_t bit; };
    Field fields[5] = {
        { "SSID", f->ssid, sizeof f->ssid, 1 }, { "PASS", f->pass, sizeof f->pass, 2 },
        { "URL",  f->url,  sizeof f->url,  4 }, { "ID",   f->id,   sizeof f->id,   8 },
        { "KEY",  f->key,  sizeof f->key,  16 }
    };
    for (Field& fl : fields) {
        if (strcmp(cmd, fl.name) != 0) continue;
        bool ok = false;
        const char* why = "ERR value rejected";
        if (fl.bit == 1)       { ok = okSsid(value);              why = "ERR SSID must be 1 to 32 printable characters"; }
        else if (fl.bit == 2)  { ok = okPass(value);              why = "ERR PASS must be empty or 8 to 63 printable characters"; }
        else if (fl.bit == 4)  {
            ok = okUrl(value, allowPlain);
            why = (value[0] != 0 && value[strlen(value) - 1] == '/')
                      ? "ERR URL must not end in a slash: the server answers 404 for /api/v1/telemetry/. leave the slash off"
                      : (allowPlain ? "ERR URL must be a valid http:// or https:// address"
                                    : "ERR URL must be an https:// address with a host name");
        }
        else if (fl.bit == 8)  { ok = okId(value);                why = "ERR ID must be 1 to 39 letters, digits, - or _"; }
        else                   { ok = okKey(value);               why = "ERR KEY rejected (16 to 96 characters from letters, digits and - _ . ~ + / =)"; }
        if (!ok) {
            say(reply, replyCap, why);
            return PR_BAD_VALUE;
        }
        // the value fits its array: every check above bounds its length
        memcpy(fl.dst, value, strlen(value) + 1);
        f->have |= fl.bit;
        // the reply names the field and never repeats the value
        snprintf(reply, replyCap, "OK %s set", fl.name);
        return PR_OK;
    }
    say(reply, replyCap, "ERR unknown command. send HELP");
    return PR_BAD_COMMAND;
}

void provConsoleInit(ProvConsole* c) {
    memset(c, 0, sizeof *c);
}

size_t provConsoleFeed(ProvConsole* c, ProvFields* f, bool allowPlain, const uint8_t* bytes, size_t n,
                       uint32_t nowMs, char* reply, size_t replyCap, ProvResult* result, bool* hasReply) {
    *result = PR_OK;
    *hasReply = false;
    if (replyCap > 0) reply[0] = 0;
    if (n > PROV_BYTES_PER_PASS) n = PROV_BYTES_PER_PASS;
    for (size_t i = 0; i < n; i++) {
        char ch = (char)bytes[i];
        if (ch == '\r') continue;
        if (ch != '\n') {
            if (c->len < PROV_LINE_MAX + 1) c->line[c->len++] = ch;
            else c->overflow = true;
            continue;
        }
        // a line is complete
        bool error = false;
        if (c->overflow || c->len > PROV_LINE_MAX) {
            say(reply, replyCap, "ERR line too long");
            *result = PR_BAD_COMMAND;
            error = true;
        } else if (c->len > 0) {
            c->line[c->len] = 0;
            *result = provLine(f, c->line, allowPlain, reply, replyCap);
            error = (*result == PR_BAD_COMMAND || *result == PR_BAD_VALUE || *result == PR_INCOMPLETE);
        } else {
            // an empty line needs no reply
            c->len = 0;
            c->overflow = false;
            continue;
        }
        // wipe the line buffer: it may have held the key
        memset(c->line, 0, sizeof c->line);
        c->len = 0;
        c->overflow = false;
        if (error) {
            // at most one error reply a second. the rest are dropped silently
            if (c->haveErrReply && (uint32_t)(nowMs - c->lastErrReplyMs) < PROV_ERROR_REPLY_GAP_MS) {
                *hasReply = false;
            } else {
                c->haveErrReply = true;
                c->lastErrReplyMs = nowMs;
                *hasReply = true;
            }
        } else {
            *hasReply = true;
        }
        return i + 1;
    }
    return n;
}
