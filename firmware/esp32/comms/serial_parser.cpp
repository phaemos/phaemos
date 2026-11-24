// include Arduino.h to get Stream on a .cpp file - the Arduino IDE only injects it
// automatically in .ino files.
#include <Arduino.h>
#include <string.h>

#include "serial_parser.h"

// read at most this many bytes per call so a chatty link cannot hold the loop. the UART
// buffer keeps the rest for the next pass.
#define POLL_MAX_BYTES 256

void serialLinkPoll(LinkCore* link, Stream& port, uint32_t nowMs) {
    for (int n = 0; n < POLL_MAX_BYTES && port.available() > 0; n++) {
        int c = port.read();
        if (c < 0) break;
        lcFeedByte(link, (uint8_t)c, nowMs);
    }

    // the request is about ten bytes and the UART FIFO holds 128, so writing it cannot block.
    char ping[16];
    if (lcPingDue(link, nowMs, ping, sizeof ping)) {
        port.write((const uint8_t*)ping, strlen(ping));
    }
}
