// use #pragma once for consistency with every other header in this project.
#pragma once

#include <Arduino.h>

#include "link_protocol.h"

// serialLinkPoll is the thin Arduino caller for one link. it moves the bytes that have
// arrived into the parser in comms/link_protocol.cpp, never waiting for a line end. sends
// a ping when one is due. every decision about lines, counters and link state is made there.
void serialLinkPoll(LinkCore* link, Stream& port, uint32_t nowMs);
