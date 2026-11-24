#include "cred_record.h"

#include <string.h>

uint32_t crChecksum(const CredRecord* r) {
    const uint8_t* p = (const uint8_t*)r;
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < offsetof(CredRecord, check); i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

void crPack(const ProvFields* f, CredRecord* r) {
    memset(r, 0, sizeof *r);
    r->magic = CRED_RECORD_MAGIC;
    memcpy(r->ssid, f->ssid, sizeof r->ssid);
    memcpy(r->pass, f->pass, sizeof r->pass);
    memcpy(r->url, f->url, sizeof r->url);
    memcpy(r->id, f->id, sizeof r->id);
    memcpy(r->key, f->key, sizeof r->key);
    r->check = crChecksum(r);
}

bool crUnpack(const CredRecord* r, bool allowPlain, ProvFields* out) {
    if (r->magic != CRED_RECORD_MAGIC || r->check != crChecksum(r)) return false;
    ProvFields f;
    provInit(&f);
    memcpy(f.ssid, r->ssid, sizeof f.ssid);
    memcpy(f.pass, r->pass, sizeof f.pass);
    memcpy(f.url, r->url, sizeof f.url);
    memcpy(f.id, r->id, sizeof f.id);
    memcpy(f.key, r->key, sizeof f.key);
    if (!provValidate(&f, allowPlain)) return false;
    f.have = PROV_HAVE_ALL;
    *out = f;
    return true;
}
