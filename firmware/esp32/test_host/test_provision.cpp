// test_provision.cpp - host test of the serial provisioning protocol in comms/provision.cpp: every
// value is checked, SAVE is refused until all five are set, a plain http:// address is refused
// unless the bench flag is on and no reply ever holds the password or the key.
//
// build and run from this folder:
//   c++ -std=c++17 -Wall -Wextra -I.. test_provision.cpp ../comms/provision.cpp ../comms/cred_record.cpp ../comms/http_parse.cpp -o "${TMPDIR:-/tmp}/test_provision" && "${TMPDIR:-/tmp}/test_provision"
//   c++ -std=c++17 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -I.. test_provision.cpp ../comms/provision.cpp ../comms/cred_record.cpp ../comms/http_parse.cpp -o "${TMPDIR:-/tmp}/test_provision_san" && "${TMPDIR:-/tmp}/test_provision_san"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include <vector>

#include "../comms/cred_record.h"
#include "../comms/provision.h"

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

static const char* KEY = "k3y-Value_0123456789.abc~DEF+/=";
static const char* PASS = "correct horse battery";

static ProvResult send(ProvFields* f, const std::string& line, bool plain, std::string* reply = nullptr) {
    char r[256];
    ProvResult res = provLine(f, line.c_str(), plain, r, sizeof r);
    if (reply) *reply = r;
    // no reply ever holds the password or the key, whatever the line was
    CHECK(std::strstr(r, KEY) == nullptr);
    CHECK(std::strstr(r, PASS) == nullptr);
    return res;
}

static void fillAll(ProvFields* f) {
    CHECK(send(f, "SSID Workshop", false) == PR_OK);
    CHECK(send(f, std::string("PASS ") + PASS, false) == PR_OK);
    CHECK(send(f, "URL https://api.example.org/api/v1/telemetry", false) == PR_OK);
    CHECK(send(f, "ID 123e4567-e89b-12d3-a456-426614174000", false) == PR_OK);
    CHECK(send(f, std::string("KEY ") + KEY, false) == PR_OK);
}

static void testHappyPath() {
    ProvFields f;
    provInit(&f);
    std::string reply;
    CHECK(send(&f, "SAVE", false, &reply) == PR_INCOMPLETE);
    fillAll(&f);
    CHECK(f.have == PROV_HAVE_ALL);
    CHECK(provValidate(&f, false));
    CHECK(std::strcmp(f.ssid, "Workshop") == 0 && std::strcmp(f.pass, PASS) == 0 && std::strcmp(f.key, KEY) == 0);
    // SHOW lists what is set and never the password or the key
    CHECK(send(&f, "SHOW", false, &reply) == PR_INFO);
    CHECK(reply.find("Workshop") != std::string::npos && reply.find("PASS set") != std::string::npos);
    CHECK(reply.find("KEY set") != std::string::npos);
    CHECK(send(&f, "SAVE", false, &reply) == PR_SAVE);
    // wiping clears every value, the password and the key included
    provWipe(&f);
    CHECK(f.have == 0 && f.key[0] == 0 && f.pass[0] == 0 && f.ssid[0] == 0);
    CHECK(send(&f, "CLEAR", false) == PR_CLEAR);
    CHECK(send(&f, "HELP", false) == PR_INFO);
}

static void testCrLfAndSpaces() {
    ProvFields f;
    provInit(&f);
    CHECK(send(&f, "SSID My Home Net\r\n", false) == PR_OK && std::strcmp(f.ssid, "My Home Net") == 0);
    CHECK(send(&f, "PASS\r", false) == PR_OK && f.pass[0] == 0 && (f.have & 2));      // an open network is explicit
    CHECK(send(&f, "BOGUS 1", false) == PR_BAD_COMMAND);
    CHECK(send(&f, "", false) == PR_BAD_COMMAND);
    CHECK(send(&f, "ssid lowercase", false) == PR_BAD_COMMAND);
}

static void testValueChecks() {
    ProvFields f;
    provInit(&f);
    // ssid
    CHECK(send(&f, "SSID ", false) == PR_BAD_VALUE);
    CHECK(send(&f, "SSID " + std::string(33, 'a'), false) == PR_BAD_VALUE);
    CHECK(send(&f, "SSID " + std::string(32, 'a'), false) == PR_OK);
    CHECK(send(&f, std::string("SSID a\x01") + "b", false) == PR_BAD_VALUE);
    CHECK(send(&f, std::string("SSID caf\xC3\xA9"), false) == PR_BAD_VALUE);
    // password: empty or 8 to 63
    CHECK(send(&f, "PASS short", false) == PR_BAD_VALUE);
    CHECK(send(&f, "PASS " + std::string(7, 'p'), false) == PR_BAD_VALUE);
    CHECK(send(&f, "PASS " + std::string(8, 'p'), false) == PR_OK);
    CHECK(send(&f, "PASS " + std::string(63, 'p'), false) == PR_OK);
    CHECK(send(&f, "PASS " + std::string(64, 'p'), false) == PR_BAD_VALUE);
    // url: https with a name. plain only with the bench flag. never an address with user info
    CHECK(send(&f, "URL http://api.example.org/x", false) == PR_BAD_VALUE);
    CHECK(send(&f, "URL http://api.example.org/x", true) == PR_OK);
    CHECK(send(&f, "URL https://10.0.0.1/x", false) == PR_BAD_VALUE);          // a certificate cannot match a bare address
    CHECK(send(&f, "URL https://10.0.0.1/x", true) == PR_BAD_VALUE);
    CHECK(send(&f, "URL https://u:p@api.example.org/x", false) == PR_BAD_VALUE);
    CHECK(send(&f, "URL ftp://api.example.org/x", false) == PR_BAD_VALUE);
    CHECK(send(&f, "URL api.example.org/x", false) == PR_BAD_VALUE);
    CHECK(send(&f, "URL https://api.example.org/a b", false) == PR_BAD_VALUE);
    CHECK(send(&f, "URL https://api.example.org/x", false) == PR_OK);
    // a trailing slash is refused, in both modes and says why. the old value is kept
    std::string slashReply;
    CHECK(send(&f, "URL https://api.example.org/api/v1/telemetry/", false, &slashReply) == PR_BAD_VALUE);
    CHECK(slashReply.find("slash") != std::string::npos && slashReply.find("404") != std::string::npos);
    CHECK(send(&f, "URL https://api.example.org/", false) == PR_BAD_VALUE);
    CHECK(send(&f, "URL http://api.example.org/api/", true) == PR_BAD_VALUE);
    CHECK(send(&f, "URL https://api.example.org/api/v1/telemetry", false) == PR_OK);
    CHECK(std::strcmp(f.url, "https://api.example.org/api/v1/telemetry") == 0);
    // a stored record whose address ends in a slash is not valid either
    ProvFields sl = f;
    std::strcpy(sl.url, "https://api.example.org/api/v1/telemetry/");
    CHECK(!provValidate(&sl, false));
    // id
    CHECK(send(&f, "ID ", false) == PR_BAD_VALUE);
    CHECK(send(&f, "ID a b", false) == PR_BAD_VALUE);
    CHECK(send(&f, "ID " + std::string(40, 'a'), false) == PR_BAD_VALUE);
    CHECK(send(&f, "ID " + std::string(39, 'a'), false) == PR_OK);
    // key: 16 to 96 of the url-safe set. a rejected key says so and does not repeat it
    CHECK(send(&f, "KEY " + std::string(15, 'k'), false) == PR_BAD_VALUE);
    CHECK(send(&f, "KEY " + std::string(97, 'k'), false) == PR_BAD_VALUE);
    CHECK(send(&f, "KEY " + std::string(96, 'k'), false) == PR_OK);
    CHECK(send(&f, std::string("KEY ") + KEY + " ", false) == PR_BAD_VALUE);   // a trailing space is not part of a key
    CHECK(send(&f, std::string("KEY ") + KEY + "\x7f", false) == PR_BAD_VALUE);
    CHECK(send(&f, std::string("KEY ") + KEY + "!", false) == PR_BAD_VALUE);
    CHECK(send(&f, std::string("KEY ") + KEY + "\"", false) == PR_BAD_VALUE);
    CHECK(send(&f, "KEY aaaaaaaaaaaaaaaa\nX-Evil: 1", false) == PR_BAD_VALUE);
    // a line over the limit is refused whole
    CHECK(send(&f, "SSID " + std::string(300, 'a'), false) == PR_BAD_COMMAND);
}

static void testBadValueKeepsOld() {
    ProvFields f;
    provInit(&f);
    CHECK(send(&f, "SSID First", false) == PR_OK);
    CHECK(send(&f, "SSID " + std::string(40, 'x'), false) == PR_BAD_VALUE);
    CHECK(std::strcmp(f.ssid, "First") == 0 && (f.have & 1));
}

static void testSaveNeedsAllFive() {
    for (int skip = 0; skip < 5; skip++) {
        ProvFields f;
        provInit(&f);
        const char* lines[5] = { "SSID Workshop", "PASS correct horse battery", "URL https://api.example.org/x",
                                 "ID abc-123", "KEY k3y-Value_0123456789.abc~DEF+/=" };
        for (int i = 0; i < 5; i++) if (i != skip) CHECK(send(&f, lines[i], false) == PR_OK);
        CHECK(send(&f, "SAVE", false) == PR_INCOMPLETE);
        CHECK(send(&f, lines[skip], false) == PR_OK);
        CHECK(send(&f, "SAVE", false) == PR_SAVE);
    }
}

static void testValidate() {
    ProvFields f;
    provInit(&f);
    fillAll(&f);
    CHECK(provValidate(&f, false));
    // a record read back from storage that is damaged is not used
    ProvFields g = f;
    g.key[0] = 0;
    CHECK(!provValidate(&g, false));
    g = f; std::memset(g.ssid, 'a', sizeof g.ssid);            // not terminated
    CHECK(!provValidate(&g, false));
    g = f; std::strcpy(g.url, "http://api.example.org/x");
    CHECK(!provValidate(&g, false) && provValidate(&g, true));
    g = f; g.id[0] = '!';
    CHECK(!provValidate(&g, false));
}

// random lines never crash, never overflow, never put anything past a field's end and never put
// the key or the password in a reply
static void testRandom() {
    srand(7);
    const char* cmds[] = { "SSID ", "PASS ", "URL ", "ID ", "KEY ", "SAVE", "SHOW", "CLEAR", "HELP", "", "XX " };
    for (int n = 0; n < 200000; n++) {
        ProvFields f;
        provInit(&f);
        for (int k = 0; k < 6; k++) {
            std::string line = cmds[rand() % 11];
            int len = rand() % 260;
            for (int i = 0; i < len; i++) line.push_back((char)(rand() % 256));
            if (line.find('\0') != std::string::npos) line = line.substr(0, line.find('\0'));
            char r[256];
            provLine(&f, line.c_str(), rand() % 2, r, sizeof r);
            CHECK(std::strlen(r) < sizeof r);
            CHECK(std::memchr(f.ssid, 0, sizeof f.ssid) && std::memchr(f.pass, 0, sizeof f.pass) &&
                  std::memchr(f.url, 0, sizeof f.url) && std::memchr(f.id, 0, sizeof f.id) &&
                  std::memchr(f.key, 0, sizeof f.key));
        }
    }
}

static void fill(ProvFields* f, const char* ssid, const char* pass, const char* url, const char* id, const char* key) {
    provInit(f);
    std::snprintf(f->ssid, sizeof f->ssid, "%s", ssid);
    std::snprintf(f->pass, sizeof f->pass, "%s", pass);
    std::snprintf(f->url, sizeof f->url, "%s", url);
    std::snprintf(f->id, sizeof f->id, "%s", id);
    std::snprintf(f->key, sizeof f->key, "%s", key);
    f->have = PROV_HAVE_ALL;
}

// the five values are stored as ONE record. a reset can cut a write at any byte. every cut of a write of
// a new record over an old one has to read back as the old five values, the new five or nothing and
// never as a mixture, such as the new address with the old key
static void testRecordCutPoints() {
    ProvFields a, b;
    fill(&a, "OldNet", "oldpassword1", "https://old.example.org/api/v1/telemetry", "old-id-1", "OLDKEY0123456789abcd");
    fill(&b, "NewNet", "newpassword2", "https://new.example.org/api/v1/telemetry", "new-id-2", "NEWKEY0123456789wxyz");
    CredRecord ra, rb;
    crPack(&a, &ra);
    crPack(&b, &rb);
    ProvFields out;
    CHECK(crUnpack(&ra, false, &out) && std::strcmp(out.key, a.key) == 0 && std::strcmp(out.url, a.url) == 0);
    CHECK(crUnpack(&rb, false, &out) && std::strcmp(out.key, b.key) == 0 && std::strcmp(out.url, b.url) == 0);

    // a write that stops after k bytes leaves the new bytes in front and the old bytes behind
    const uint8_t* pa = (const uint8_t*)&ra;
    const uint8_t* pb = (const uint8_t*)&rb;
    int oldSeen = 0, newSeen = 0, rejected = 0;
    for (size_t k = 0; k <= sizeof(CredRecord); k++) {
        CredRecord mix;
        std::memcpy(&mix, pa, sizeof mix);
        std::memcpy(&mix, pb, k);
        ProvFields got;
        if (crUnpack(&mix, false, &got)) {
            bool isOld = std::strcmp(got.ssid, a.ssid) == 0 && std::strcmp(got.pass, a.pass) == 0 &&
                         std::strcmp(got.url, a.url) == 0 && std::strcmp(got.id, a.id) == 0 && std::strcmp(got.key, a.key) == 0;
            bool isNew = std::strcmp(got.ssid, b.ssid) == 0 && std::strcmp(got.pass, b.pass) == 0 &&
                         std::strcmp(got.url, b.url) == 0 && std::strcmp(got.id, b.id) == 0 && std::strcmp(got.key, b.key) == 0;
            CHECK(isOld != isNew);                      // exactly one, never a mixture
            if (isOld) oldSeen++; else newSeen++;
        } else {
            rejected++;
        }
    }
    CHECK(oldSeen >= 1 && newSeen >= 1);                // k = 0 is the old record and k = all is the new one
    CHECK(rejected > 300);                              // nearly every cut in between is refused
    // the five separate writes the first version made, cut between url and key: the new address with the old
    // key passes provValidate on its own. that is the failure the single record removes
    ProvFields mixed = a;
    std::strcpy(mixed.url, b.url);
    CHECK(provValidate(&mixed, false));
    CredRecord rm;
    std::memcpy(&rm, pa, sizeof rm);
    std::memcpy(rm.url, rb.url, sizeof rm.url);          // the url written, the key not yet
    CHECK(!crUnpack(&rm, false, &out));

    // every single byte flipped in a stored record is refused
    int accepted = 0;
    for (size_t i = 0; i < sizeof(CredRecord); i++) {
        CredRecord bad = rb;
        ((uint8_t*)&bad)[i] ^= 0x01;
        if (crUnpack(&bad, false, &out)) accepted++;
    }
    CHECK(accepted == 0);
    // a record that is too short, a wrong magic and an all-zero record
    CredRecord zero;
    std::memset(&zero, 0, sizeof zero);
    CHECK(!crUnpack(&zero, false, &out));
    CredRecord badMagic = rb;
    badMagic.magic ^= 1;
    badMagic.check = crChecksum(&badMagic);
    CHECK(!crUnpack(&badMagic, false, &out));
    // a sealed record that holds a value the rules refuse is not used either
    ProvFields plain = b;
    std::strcpy(plain.url, "http://new.example.org/x");
    CredRecord rp;
    crPack(&plain, &rp);
    CHECK(!crUnpack(&rp, false, &out) && crUnpack(&rp, true, &out));
}

// the console never keeps the loop long: at most 256 bytes and one line per pass, an error reply at most
// once a second and the wiped line buffer never holds the key
static void testConsoleFlood() {
    ProvConsole c;
    provConsoleInit(&c);
    ProvFields f;
    provInit(&f);
    char reply[128];
    ProvResult r;
    bool has;
    // a flood of short bad lines in one big read: each call takes at most 256 bytes and handles one line
    std::string flood;
    for (int i = 0; i < 2000; i++) flood += "X\n";
    size_t pos = 0;
    int calls = 0, replies = 0;
    uint32_t now = 5000;
    while (pos < flood.size() && calls < 5000) {
        size_t took = provConsoleFeed(&c, &f, false, (const uint8_t*)flood.data() + pos, flood.size() - pos, now, reply, sizeof reply, &r, &has);
        CHECK(took >= 1 && took <= PROV_BYTES_PER_PASS);
        pos += took;
        calls++;
        if (has) replies++;
        now += 1;                                         // a pass takes about a millisecond
    }
    CHECK(pos == flood.size());
    // 2000 bad lines over about 2 seconds of passes: a reply at most once a second
    CHECK(replies >= 1 && replies <= 3);
    CHECK(calls >= 2000);                                 // one line per call
    // an error reply is allowed again after the gap
    now += PROV_ERROR_REPLY_GAP_MS;
    provConsoleFeed(&c, &f, false, (const uint8_t*)"X\n", 2, now, reply, sizeof reply, &r, &has);
    CHECK(has && std::strstr(reply, "ERR") != nullptr);
    CHECK(provConsoleFeed(&c, &f, false, (const uint8_t*)"X\n", 2, now + 10, reply, sizeof reply, &r, &has) == 2 && !has);
    // a good line is always answered, even right after an error
    provConsoleFeed(&c, &f, false, (const uint8_t*)"SSID Net\n", 9, now + 20, reply, sizeof reply, &r, &has);
    CHECK(has && r == PR_OK && std::strcmp(f.ssid, "Net") == 0);
    // a big read with no newline takes at most 256 bytes per call and the line is dropped when it ends
    std::string longLine(1000, 'a');
    longLine += "\n";
    pos = 0;
    int took256 = 0;
    bool sawErr = false;
    now += 5000;
    while (pos < longLine.size()) {
        size_t took = provConsoleFeed(&c, &f, false, (const uint8_t*)longLine.data() + pos, longLine.size() - pos, now, reply, sizeof reply, &r, &has);
        CHECK(took <= PROV_BYTES_PER_PASS);
        if (took == PROV_BYTES_PER_PASS) took256++;
        if (has && std::strstr(reply, "too long")) sawErr = true;
        pos += took;
    }
    CHECK(took256 >= 3 && sawErr);
    // the key arrives in pieces, a byte at a time and the buffer holds nothing after the line
    const char* line = "KEY k3y-Value_0123456789.abc~DEF+/=\n";
    for (const char* p = line; *p; p++) provConsoleFeed(&c, &f, false, (const uint8_t*)p, 1, now + 100, reply, sizeof reply, &r, &has);
    CHECK((f.have & 16) && std::strcmp(f.key, KEY) == 0);
    CHECK(std::strstr(c.line, "k3y") == nullptr && c.len == 0);
    CHECK(std::strstr(reply, KEY) == nullptr);
    // CR LF line ends and SAVE are handled the same
    provConsoleFeed(&c, &f, false, (const uint8_t*)"SAVE\r\n", 6, now + 3000, reply, sizeof reply, &r, &has);
    CHECK(has && r == PR_INCOMPLETE);
    // a clock that wraps between two errors still rate limits by the difference
    ProvConsole w;
    provConsoleInit(&w);
    provConsoleFeed(&w, &f, false, (const uint8_t*)"X\n", 2, 0xFFFFFF00u, reply, sizeof reply, &r, &has);
    CHECK(has);
    provConsoleFeed(&w, &f, false, (const uint8_t*)"X\n", 2, 0xFFFFFF00u + 300u, reply, sizeof reply, &r, &has);
    CHECK(!has);
    provConsoleFeed(&w, &f, false, (const uint8_t*)"X\n", 2, (uint32_t)(0xFFFFFF00u + 1000u), reply, sizeof reply, &r, &has);
    CHECK(has);
}

int main() {
    testHappyPath();
    testCrLfAndSpaces();
    testValueChecks();
    testBadValueKeepsOld();
    testSaveNeedsAllFive();
    testValidate();
    testRandom();
    testRecordCutPoints();
    testConsoleFlood();
    std::printf("%d checks, %d failed\n", g_checks, g_failed);
    return g_failed ? 1 : 0;
}
