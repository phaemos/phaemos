#include "credentials.h"

#include <Preferences.h>
#include <string.h>

#include "../config.h"
#include "cred_record.h"

namespace {
const char* NS = "phaemos-cfg";
}

void credsLoad(Credentials* c) {
    memset(c, 0, sizeof *c);
#if USE_COMPILED_SECRETS
    snprintf(c->ssid, sizeof c->ssid, "%s", WIFI_SSID);
    snprintf(c->pass, sizeof c->pass, "%s", WIFI_PASSWORD);
    snprintf(c->url, sizeof c->url, "%s", API_URL);
    snprintf(c->id, sizeof c->id, "%s", DEVICE_ID);
    snprintf(c->key, sizeof c->key, "%s", DEVICE_API_KEY);
    c->present = true;
#else
    Preferences p;
    // read-only open. a missing namespace is simply nothing stored
    if (!p.begin(NS, true)) return;
    CredRecord rec;
    size_t got = p.getBytes("rec", &rec, sizeof rec);
    p.end();
    // one record with a checksum: a record that was cut, damaged or only partly written is not used
    ProvFields f;
    if (got == sizeof rec && crUnpack(&rec, ALLOW_PLAIN_HTTP != 0, &f)) {
        memcpy(c->ssid, f.ssid, sizeof c->ssid);
        memcpy(c->pass, f.pass, sizeof c->pass);
        memcpy(c->url, f.url, sizeof c->url);
        memcpy(c->id, f.id, sizeof c->id);
        memcpy(c->key, f.key, sizeof c->key);
        c->present = true;
    }
    provWipe(&f);
    memset(&rec, 0, sizeof rec);
#endif
}

bool credsStoredInFlash() {
#if USE_COMPILED_SECRETS
    return false;
#else
    Preferences p;
    if (!p.begin(NS, true)) return false;
    bool has = p.isKey("rec");
    p.end();
    return has;
#endif
}

bool credsSave(const ProvFields* f) {
#if USE_COMPILED_SECRETS
    (void)f;
    return false;
#else
    CredRecord rec;
    crPack(f, &rec);
    Preferences p;
    if (!p.begin(NS, false)) return false;
    // one write. the old record stays whole until the new one is committed, so a reset at any point
    // leaves either the old five values or the new five and never a mixture
    bool ok = p.putBytes("rec", &rec, sizeof rec) == sizeof rec;
    p.end();
    memset(&rec, 0, sizeof rec);
    if (!ok) return false;
    // read it back. a record that did not take is not a success
    Credentials back;
    credsLoad(&back);
    bool same = back.present && strcmp(back.ssid, f->ssid) == 0 && strcmp(back.pass, f->pass) == 0 &&
                strcmp(back.url, f->url) == 0 && strcmp(back.id, f->id) == 0 && strcmp(back.key, f->key) == 0;
    memset(&back, 0, sizeof back);
    return same;
#endif
}

void credsClear() {
#if !USE_COMPILED_SECRETS
    Preferences p;
    if (p.begin(NS, false)) {
        p.clear();
        p.end();
    }
#endif
}
