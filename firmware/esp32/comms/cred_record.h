// cred_record.h - the five credentials as ONE record with a checksum, so that storing them is
// atomic. five separate writes could be cut by a reset: a new address beside an old key would still
// pass every check and the old key would be posted to the new address. one record is written in
// one storage operation and a record that was cut or damaged fails its checksum and is not used.
// no Arduino types, so the host test covers every cut point.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "provision.h"

#define CRED_RECORD_MAGIC 0x50434431u      // "PCD1"

struct CredRecord {
    uint32_t magic;
    char     ssid[PROV_SSID_MAX + 1];
    char     pass[PROV_PASS_MAX + 1];
    char     url[PROV_URL_MAX + 1];
    char     id[PROV_ID_MAX + 1];
    char     key[PROV_KEY_MAX + 1];
    uint32_t check;                        // FNV-1a over every byte before this field
};

// fills the record from five valid values and seals it
void crPack(const ProvFields* f, CredRecord* r);
// the checksum of the bytes before the check field
uint32_t crChecksum(const CredRecord* r);
// reads a record back: the magic and checksum must be right and every value must pass provValidate.
// false for anything else, including a record that was cut part way
bool crUnpack(const CredRecord* r, bool allowPlain, ProvFields* out);
