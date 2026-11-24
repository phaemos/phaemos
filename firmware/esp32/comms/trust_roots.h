// trust_roots.h - the root certificates the hub trusts for TLS. a post to an https:// address is
// verified against these two and nothing else. the hub's own post path never calls setInsecure()
// in any build.
//
// the two slots below hold PLACEHOLDERS on purpose. a certificate written from memory is the
// kind of thing that is silently wrong, so none is written here. a release build
// (PHAEMOS_RELEASE=1) fails to compile until both are replaced. a default build compiles and then
// refuses every TLS post at run time, with a message, while a placeholder is still there.
//
// what the owner does, once, for each root:
//   1. open the issuing authority's own certificates page: https://letsencrypt.org/certificates/
//   2. under "Root Certificates" download ISRG Root X1 and ISRG Root X2 in PEM format (the
//      "Self-signed" PEM links). download over HTTPS from that page and nowhere else.
//   3. check the fingerprint before pasting. on the same page each certificate shows its
//      SHA-256 fingerprint. compute the file's own with
//          openssl x509 -in isrg-root-x1.pem -noout -fingerprint -sha256
//      and compare the two strings character by character. do not use a fingerprint from any
//      other page, from a chat or from this repository.
//   4. check the expiry the same way (openssl x509 -noout -enddate). ISRG Root X1 expires in
//      2035 and ISRG Root X2 in 2040. a hub built today holds roots that outlive any one image.
//      recheck the roots whenever an image is rebuilt.
//   5. paste each PEM between the quotes of its slot, one line per string piece, keeping the
//      "-----BEGIN CERTIFICATE-----" and "-----END CERTIFICATE-----" lines and delete the
//      matching TRUST_ROOT_..._PLACEHOLDER line.
//
// why roots and not the certificate of the one server: Let's Encrypt certificates change every
// few months and their intermediates change too. the roots are the stable part. X1 is RSA and X2 is
// ECDSA, so the hub can still verify if the issuing chain moves from one family to the other.
// the pinned core ships no certificate bundle file to take these from (the bundle code exists in
// its WiFiClientSecure library but the data is not a file that can be checked offline), so the
// owner pastes them here.
#pragma once

#include "../config.h"

// delete a line below when the PEM beneath it is a real certificate
#define TRUST_ROOT_X1_PLACEHOLDER 1
#define TRUST_ROOT_X2_PLACEHOLDER 1

#if PHAEMOS_RELEASE
#ifdef TRUST_ROOT_X1_PLACEHOLDER
#error "comms/trust_roots.h: the ISRG Root X1 slot is still a placeholder. paste the real PEM and delete TRUST_ROOT_X1_PLACEHOLDER"
#endif
#ifdef TRUST_ROOT_X2_PLACEHOLDER
#error "comms/trust_roots.h: the ISRG Root X2 slot is still a placeholder. paste the real PEM and delete TRUST_ROOT_X2_PLACEHOLDER"
#endif
#endif

// ISRG Root X1 (RSA 4096, expires 2035)
#define TRUST_ROOT_X1_PEM \
    "-----BEGIN CERTIFICATE-----\n" \
    "PLACEHOLDER-paste-the-ISRG-Root-X1-PEM-here\n" \
    "-----END CERTIFICATE-----\n"

// ISRG Root X2 (ECDSA P-384, expires 2040)
#define TRUST_ROOT_X2_PEM \
    "-----BEGIN CERTIFICATE-----\n" \
    "PLACEHOLDER-paste-the-ISRG-Root-X2-PEM-here\n" \
    "-----END CERTIFICATE-----\n"

// both roots in one buffer, which is what setCACert() takes. mbedTLS reads every certificate in it
static const char TRUST_ROOTS_PEM[] = TRUST_ROOT_X1_PEM TRUST_ROOT_X2_PEM;

// true while either slot is still a placeholder. checked at run time as a second guard, so a
// default build never tries a handshake it cannot verify
inline bool trustRootsArePlaceholders() {
    const char* p = TRUST_ROOTS_PEM;
    const char key[] = "PLACEHOLDER";
    for (; *p; p++) {
        const char* a = p;
        const char* b = key;
        while (*a && *b && *a == *b) { a++; b++; }
        if (*b == 0) return true;
    }
    return false;
}
