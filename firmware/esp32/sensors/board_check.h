// board_check.h - the two carrier boards need different things from GPIO14. on the present board
// it is relay 3 and the firmware drives it. on the revised board it is the sensor supply switch,
// which must never be driven low. the revised board is recognised by its MCP23017 at 0x20, which
// the present board does not have. an image that disagrees with the board never drives GPIO14 and
// neither does an image that cannot tell. header only and free of Arduino types, so the host test
// covers it.
//
// the order at boot is: GPIO14 is released as a plain input on both images, the sensor rail
// start-up wait passes, the I2C bus is started, its lines are checked for idling high, the expander
// is probed several times and a few other known devices are probed to show the bus works.
#pragma once

enum BoardVerdict {
    BOARD_OK,
    BOARD_MISMATCH,
    BOARD_UNKNOWN      // the bus is not known to work, so absence cannot be believed
};

// imageIsRevised is HAS_SENSOR_RAIL_SWITCH. linesIdle is whether SDA and SCL both read high with
// nothing driving them. mcpAnswered is whether 0x20 answered on any try. anyOtherAnswered is whether
// any other known device answered, which proves the bus works. an answer from the expander is proof
// in itself. its absence is believed only on a bus that is known to work.
inline BoardVerdict boardVerdict(bool imageIsRevised, bool linesIdle, bool mcpAnswered,
                                 bool anyOtherAnswered) {
    if (mcpAnswered) return imageIsRevised ? BOARD_OK : BOARD_MISMATCH;
    if (!linesIdle || !anyOtherAnswered) return BOARD_UNKNOWN;
    return imageIsRevised ? BOARD_MISMATCH : BOARD_OK;
}

// the present-board image may drive GPIO14 as relay 3 only when the board really is the present
// board. any doubt means it does not. the revised-board image never drives it as an output at boot.
inline bool mayDriveGpio14AsRelay(bool imageIsRevised, BoardVerdict v) {
    return !imageIsRevised && v == BOARD_OK;
}

// the revised-board image may switch the sensor supply (drive GPIO14 high) only on a revised board
inline bool maySwitchSensorRail(bool imageIsRevised, BoardVerdict v) {
    return imageIsRevised && v == BOARD_OK;
}
