// relay_proof - whether a relay that was commanded on can be shown to have pulled in.
// the relay module takes 1.6 to 1.8 mA from the board at its input (set by the module's own 1 k
// resistor), against the 2 mA its listing asks for. so a command is never taken as proof that the
// contacts closed. a relay counts as confirmed only when the relay and strip rail is seen to draw a
// coil's worth more current once it has had time to pull in. with no rail reading it stays
// unconfirmed and says so.
#pragma once

#include <stdint.h>

enum RelayProof : uint8_t {
    RELAY_OFF = 0,          // commanded off
    RELAY_CONFIRMED = 1,    // commanded on and the rail rose by a coil's worth
    RELAY_UNCONFIRMED = 2,  // commanded on and not shown to have pulled in
};

// the least rise a pulled-in coil makes on the rail. a 5 V relay coil draws about 70 mA, so half of
// that leaves room for the meter's error and for the strip changing at the same moment
#define RELAY_COIL_MIN_RISE_MA 35
// how long after the command the rail is read again. a small relay pulls in within about 10 ms
#define RELAY_PULL_IN_MS 20

struct RailReading {
    bool valid;
    int32_t ma;
};

class RelayProofTracker {
   public:
    static const uint8_t kChannels = 4;
    // a change of command for one relay, with the rail as it was just before the change
    void command(uint8_t ch, bool on, uint32_t nowMs, RailReading before);
    // a later pass with the command unchanged. once the coil has had time to pull in the rise is judged
    void tick(uint8_t ch, uint32_t nowMs, RailReading now);
    RelayProof proof(uint8_t ch) const;
    // true while a switch-on is still waiting for its second reading
    bool waiting(uint8_t ch) const;
    // bit n set for relay n+1 commanded on and not confirmed
    uint8_t unconfirmedMask() const;

   private:
    struct Channel {
        RelayProof proof = RELAY_OFF;
        bool waiting = false;
        uint32_t sinceMs = 0;
        int32_t beforeMa = 0;
    };
    Channel ch_[kChannels];
};
