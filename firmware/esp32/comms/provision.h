// provision.h - the line protocol a hub is provisioned with over its serial console and the
// checks on every value. no Arduino types, so the host test covers it. comms/credentials.cpp
// stores what this accepts and esp32.ino moves the bytes.
//
// one command per line, ASCII, at most PROV_LINE_MAX bytes, ending in LF or CR LF:
//   SSID <text>      the Wi-Fi network name (1 to 32 printable characters)
//   PASS <text>      the Wi-Fi password (8 to 63 printable characters). "PASS" alone is an open network
//   URL <address>    the telemetry endpoint. https:// with a host name (http:// only in a bench build).
//                    an address ending in a slash is refused, because the server answers 404 for it
//   ID <text>        the device id (1 to 39 letters, digits, hyphens or underscores)
//   KEY <text>       the device key (16 to 96 letters, digits and - _ . ~ + / =)
//   SHOW             what is set. the password and the key are never shown, only whether they are set
//   SAVE             store every value and restart. refused until all five are set
//   CLEAR            forget everything that is stored and restart
//   HELP             the list above
// no reply ever contains the password or the key. a rejected KEY or PASS line says only that it
// was rejected and why in general terms, never the text.
#pragma once

#include <stddef.h>
#include <stdint.h>

#define PROV_LINE_MAX   200
#define PROV_SSID_MAX   32
#define PROV_PASS_MAX   63
#define PROV_URL_MAX    159
#define PROV_ID_MAX     39
#define PROV_KEY_MAX    96

struct ProvFields {
    char    ssid[PROV_SSID_MAX + 1];
    char    pass[PROV_PASS_MAX + 1];
    char    url[PROV_URL_MAX + 1];
    char    id[PROV_ID_MAX + 1];
    char    key[PROV_KEY_MAX + 1];
    uint8_t have;                      // bit 0 ssid, 1 pass, 2 url, 3 id, 4 key
};
#define PROV_HAVE_ALL   0x1F

enum ProvResult : uint8_t {
    PR_OK,             // a value was accepted
    PR_INFO,           // SHOW or HELP: only a reply
    PR_SAVE,           // SAVE with all five set: the caller stores the fields
    PR_CLEAR,          // CLEAR: the caller forgets what is stored
    PR_BAD_COMMAND,
    PR_BAD_VALUE,
    PR_INCOMPLETE      // SAVE before all five are set
};

void       provInit(ProvFields* f);
// wipes every value (the password and the key too), for after SAVE has stored them
void       provWipe(ProvFields* f);
// handles one line (without its line end). allowPlain is the build's ALLOW_PLAIN_HTTP.
// reply is always filled and never holds the password or the key.
ProvResult provLine(ProvFields* f, const char* line, bool allowPlain, char* reply, size_t replyCap);
// true when the five values are all well formed (the same checks provLine makes). used on values
// read back from storage, so a damaged record is not used
bool       provValidate(const ProvFields* f, bool allowPlain);

// ─── the console around the protocol ─────────────────────────────────────────
// the main loop reads the console on every pass, so the console must never keep it long. at most
// PROV_BYTES_PER_PASS bytes are taken per pass, at most one line is handled per pass (so at most one
// reply is written per pass) and an error reply is written at most once every PROV_ERROR_REPLY_GAP_MS.
// an error that is not written is dropped silently. a flood of short bad lines therefore costs the
// loop a bounded amount of time on every pass and never a blocking write per line.
#define PROV_BYTES_PER_PASS      256
#define PROV_ERROR_REPLY_GAP_MS  1000UL

struct ProvConsole {
    char     line[PROV_LINE_MAX + 2];
    uint16_t len;
    bool     overflow;
    bool     haveErrReply;
    uint32_t lastErrReplyMs;
};
void provConsoleInit(ProvConsole* c);
// takes bytes from bytes[0..n), at most PROV_BYTES_PER_PASS, stopping after the first complete line.
// returns how many bytes it took. *hasReply says whether reply should be written (an error reply that
// is rate limited sets it false). *result is the line's result (PR_OK when no line completed).
size_t provConsoleFeed(ProvConsole* c, ProvFields* f, bool allowPlain, const uint8_t* bytes, size_t n,
                       uint32_t nowMs, char* reply, size_t replyCap, ProvResult* result, bool* hasReply);
