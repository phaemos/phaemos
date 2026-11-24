// http_parse.h - the pure parts of the hub's own HTTP post: reading the address, building the
// request, reading the status line and the wall-clock arithmetic. no Arduino types, so the host
// test covers them. comms/http_client.cpp moves the bytes.
#pragma once

#include <stddef.h>
#include <stdint.h>

// what this client does and does not do. it sends one POST and reads the status line. it does
// not follow redirects (a 3xx is a failed post) and does not use a proxy. an https:// address
// is posted over TLS with the pinned roots (see trust_roots.h). a plain http:// address is
// refused unless the build allows plain HTTP, which is for a bench only.
//
// splits "http[s]://host[:port][/path]". the default port is 80 for http and 443 for https and
// *tls says which scheme it was. false when it does not fit or when the host or path holds a
// control character, a space or a DEL, so a request can never be split.
bool httpParseUrl(const char* url, char* host, size_t hostCap, uint16_t* port,
                  char* path, size_t pathCap, bool* tls);

// what may be done with a parsed address. a plain address needs the bench build flag. a TLS
// address needs a host name, because the certificate is checked against the name and a bare
// IPv4 address never matches a public certificate.
enum UrlPolicy : uint8_t {
    URL_OK,
    URL_REFUSED_PLAIN,       // http:// in a build that does not allow plain HTTP
    URL_REFUSED_TLS_IP       // https:// to a bare IP address
};
UrlPolicy httpUrlPolicy(bool tls, bool allowPlain, const char* host);

// the time plan for a TLS post inside one wall-clock budget. leftMs is what is left after the
// lookup. the send and the read of the status line keep reserveMs. the TCP connect gets at most
// connectCapMs and a third of what remains and the handshake gets the rest up to
// handshakeCapMs. false when the connect would get less than minConnectMs or the handshake less
// than minHandshakeMs, so the post is not even started. the handshake is documented at one to
// three seconds and the firmware sets the minimum to the top of that (HTTP_TLS_MIN_HANDSHAKE_MS).
bool httpTlsPlan(uint32_t leftMs, uint32_t connectCapMs, uint32_t handshakeCapMs,
                 uint32_t reserveMs, uint32_t minConnectMs, uint32_t minHandshakeMs,
                 uint32_t* connectMs, uint32_t* handshakeMs);

// the seconds from a "Retry-After: <seconds>" header line, case-insensitive. the date form is
// not read. the value is capped at 86,400. false when the line is not that header.
bool httpParseRetryAfter(const char* line, uint32_t* seconds);
// true when the host is a dotted IPv4 address, which needs no lookup
bool httpHostIsIp(const char* host);
// the request header. returns its length (0 when it does not fit).
size_t httpBuildHeader(char* out, size_t cap, const char* host, uint16_t port, bool tls,
                       const char* path, const char* apiKey, const char* userAgent, size_t bodyLen);
// the status code from "HTTP/1.1 200 OK" (-1 when the line is not a status line)
int httpParseStatusLine(const char* line);

// true for a 1xx status. it is an interim response, so the final status is still to come
bool httpIsInformational(int code);

// reads the final status. a blank line before the status line is ignored. a 1xx response (100
// continue and the like) and its headers are skipped, because the server goes on to send the real
// status. feed it one byte at a time. it returns true once the final code is known (-1 when the
// line was not a status line).
// collects one response line, byte by byte. the line ends at LF. CR is dropped. a line longer
// than the buffer is cut. that is fine because only the status line is read.
struct HttpLine {
    char     buf[48];
    uint8_t  len;
};
void httpLineInit(HttpLine* l);
// true when the line is complete
bool httpLineFeed(HttpLine* l, char c);

// milliseconds left of a wall-clock budget that started at startMs. 0 once it is spent.
struct HttpReader {
    HttpLine line;
    uint8_t  state;     // 0 waiting for a status line, 1 skipping the headers of an interim response
    int      code;
};
void httpReaderInit(HttpReader* r);
bool httpReaderFeed(HttpReader* r, char c);

uint32_t httpRemainingMs(uint32_t startMs, uint32_t nowMs, uint32_t limitMs);

// ─── reading the response ────────────────────────────────────────────────────
// the byte source the response reader pulls from. http_client.cpp wraps the real socket in it and
// the host test drives the same reader with a scripted stream (a server that drips one byte every
// 1.9 s, one that never answers, one that closes early) and a virtual clock.
class HttpStream {
public:
    virtual ~HttpStream() {}
    virtual int      available() = 0;
    virtual int      read() = 0;              // -1 when there is nothing
    virtual bool     connected() = 0;
    virtual void     pause(uint32_t ms) = 0;  // wait a little (the real one delays 5 ms)
    virtual uint32_t nowMs() = 0;
};
struct HttpResponse {
    int      code;             // the final status, -1 when none arrived in time
    uint32_t retryAfterSec;    // from a 429's Retry-After, else 0
};
// reads the final status line and, for a 429, its headers up to the blank line. it never runs past
// limitMs after startMs however slowly the server sends and reads no more bytes than it needs.
HttpResponse httpReadResponse(HttpStream& s, uint32_t startMs, uint32_t limitMs);
