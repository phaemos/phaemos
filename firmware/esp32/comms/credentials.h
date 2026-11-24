// credentials.h - where the Wi-Fi password, the device key, the API address and the device id
// live at run time. by default they are in the hub's own flash (non-volatile storage), written at
// the bench over the serial console (see provision.h). with USE_COMPILED_SECRETS they come from
// the untracked secrets.h instead.
//
// what this protects: no secret is in the tracked source or compiled into the image, one image
// fits every hub and the core keeps no second copy of the Wi-Fi password (WiFi.persistent(false)).
// what it does not protect: non-volatile storage is not encrypted. anyone who holds the hub can read
// the flash and read these values. only flash encryption and Secure Boot stop that and they are
// one-way hardware settings that this firmware does not use (see Safety in firmware/README.md).
#pragma once

#include <Arduino.h>

#include "provision.h"

struct Credentials {
    char ssid[PROV_SSID_MAX + 1];
    char pass[PROV_PASS_MAX + 1];
    char url[PROV_URL_MAX + 1];
    char id[PROV_ID_MAX + 1];
    char key[PROV_KEY_MAX + 1];
    bool present;            // all five are stored and valid
};

// reads the stored values. present is false when nothing is stored or a value is damaged
void credsLoad(Credentials* c);
// true when credentials are stored in flash (never for a build with compiled secrets)
bool credsStoredInFlash();
// stores the five values as one checksummed record in one write and reads them back. false when the storage did not take them
bool credsSave(const ProvFields* f);
// forgets every stored value
void credsClear();
