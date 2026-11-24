"""
A sensor whose value has stopped moving.

The anomaly model cannot see this: a frozen reading is a perfectly normal reading, repeated (in the evaluation it caught none
of 30 injected cases). So the server watches for it and raises it as a sensor fault of kind `stuck`, through the same alert
path as a fault the node reports itself (one open alert per machine and sensor).

It is built so it cannot nag:

- a column is judged only against its own table row below: the smallest change that counts as movement and the shortest flat
  spell that is not explained by noise, with the reason. Columns where a steady value is normal are not checked at all
- only readings that arrive count. A silent stretch adds at most one interval, so a node that went offline and came back with
  the same value is not "flat for the whole outage"
- a column is judged only after it has moved at least MIN_MOVES times. A column that has always been flat (a fixed
  distance, an input nothing is wired to) is the machine's normal and is never flagged
- a column that can sit at zero legitimately (a stopped shaft, a machine that is off, a dark room) is not flagged while it
  reads zero
- the machine's own history sets the threshold: the longest flat spell it has had before the value moved (up to three times
  the table's period) raises the bar to twice that, so a node whose firmware rounds coarsely is not flagged for the flat
  spells its rounding makes
- it clears the moment the value moves. The sensor alert then resolves after its own one minute of calm

A stuck value is not hidden from the rules and the model: a frozen reading may still be the true reading, so it is flagged for a
person and nothing is suppressed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.sensor_map import FIELD_SENSOR

# a column must have moved this many times before a flat spell means anything
MIN_MOVES = 30
# the longest healthy flat spell learned is capped at this many table periods, so one real fault cannot teach it that
# flat is normal
LEARN_CAP_PERIODS = 3
# the learned spell raises the threshold to this many times itself
LEARN_FACTOR = 2.0


@dataclass(frozen=True)
class Rule:
    min_s: float    # the shortest flat spell, in seconds of posts received, that is not explained by noise
    step: float     # the smallest change that counts as movement
    rest_zero: bool  # zero is a normal resting value, so a flat zero is not stuck
    why: str


STUCK_RULES: dict[str, Rule] = {
    "temperature": Rule(600, 0.01, False, "BME280: 0.01 degC resolution and the machine's own heat noise. Never exactly flat for ten minutes on a running machine"),
    "humidity": Rule(900, 0.01, False, "BME280 humidity wanders with the air. Fifteen minutes exactly flat is a frozen sensor"),
    "pressure": Rule(1800, 0.01, False, "pressure moves slowly, so half an hour. Its noise alone is larger than the step"),
    "vibration_x": Rule(300, 0.001, True, "MPU6050 noise is several steps even at rest. Zero at rest is normal"),
    "vibration_y": Rule(300, 0.001, True, "as vibration_x"),
    "vibration_z": Rule(300, 0.001, True, "as vibration_x"),
    "gyro_x": Rule(300, 0.01, True, "gyro offset noise never holds one value for five minutes"),
    "gyro_y": Rule(300, 0.01, True, "as gyro_x"),
    "gyro_z": Rule(300, 0.01, True, "as gyro_x"),
    "bus_voltage": Rule(900, 0.001, False, "INA219 reads in 4 mV steps and a supply ripples by more"),
    "current_ma": Rule(600, 0.1, True, "a machine that is off draws zero. Running current always varies"),
    "power_mw": Rule(600, 0.1, True, "as current_ma"),
    "ir_temperature": Rule(600, 0.01, False, "MLX90614 noise is 0.1 degC. Ten minutes flat is a frozen sensor"),
    "gas_level": Rule(3600, 1.0, True, "a gas sensor at rest in clean air can hold one value for a long time, so a full hour"),
    "shaft_rpm": Rule(600, 0.1, True, "a stopped shaft reads zero"),
    "sound_level": Rule(900, 0.1, False, "an ADC count of a microphone always shows some noise floor"),
    "light_level": Rule(3600, 1.0, True, "a dark room or a saturated input holds one count for hours, so a full hour"),
    "contact_temp": Rule(1800, 0.01, False, "DS18B20 resolves in 0.0625 degC steps, so a steady surface can hold one value for a while"),
    "moisture_level": Rule(3600, 1.0, True, "moisture changes slowly and a dry probe holds one count"),
    "nano_temp": Rule(900, 0.01, False, "the Nano's BME280, as temperature but slower to be sure over a serial link"),
    "nano_hum": Rule(900, 0.01, False, "as humidity"),
    "nano_pres": Rule(1800, 0.01, False, "as pressure"),
    "nano_light": Rule(3600, 1.0, True, "as light_level"),
    "nano_moist": Rule(3600, 1.0, True, "as moisture_level"),
    "vib_rms_x": Rule(300, 0.0001, True, "RMS of the alternating part: noise alone is above the step. Zero at rest is normal"),
    "vib_rms_y": Rule(300, 0.0001, True, "as vib_rms_x"),
    "vib_rms_z": Rule(300, 0.0001, True, "as vib_rms_x"),
    "vib_peak": Rule(300, 0.0001, True, "as vib_rms_x"),
    "stm32_vib_x": Rule(300, 0.0001, False, "an axis mean carries gravity and noise"),
    "stm32_vib_y": Rule(300, 0.0001, False, "as stm32_vib_x"),
    "stm32_vib_z": Rule(300, 0.0001, False, "as stm32_vib_x"),
    "vib_magnitude": Rule(300, 0.0001, True, "as vib_rms_x"),
}
# columns left out on purpose, each with the reason: a steady value is their normal
NOT_CHECKED = {
    "distance_mm": "a fixed target reads the same millimetre for hours",
    "shaft_angle": "a stopped shaft holds its angle",
    "fft_peak_hz": "the peak sits on one of a few frequency bins and a steady machine stays on one",
}


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def update(state: dict | None, reading: dict, now_s: float, interval_s: float) -> tuple[dict, dict[str, str]]:
    """
    Fold one reading into the per column state and say which sensors are stuck.

    state    what this returned last time ({} or None at first): per column {"q": last value in steps, "f": seconds flat,
             "m": times it has moved, "l": longest healthy flat spell, "t": time of the last reading it appeared in}
    now_s    the reading's time in seconds (any fixed epoch)
    Returns (new_state, {sensor_key: "stuck"}). The state is a new dict and holds only JSON friendly values.
    """
    state = dict(state or {})
    interval_s = max(float(interval_s or 5), 1.0)
    credit = max(30.0, 3.0 * interval_s)
    stuck: dict[str, str] = {}
    for col, rule in STUCK_RULES.items():
        value = reading.get(col)
        if not _finite_number(value):
            # no value is no evidence either way: a column that was flagged stays flagged until it moves
            if state.get(col, {}).get("x"):
                stuck[FIELD_SENSOR[col]] = "stuck"
            continue
        quantised = int(round(value / rule.step))
        st = state.get(col)
        if st is None:
            state[col] = {"q": quantised, "f": 0.0, "m": 0, "l": 0.0, "t": now_s}
            continue
        elapsed = max(0.0, now_s - st["t"])
        st = dict(st)
        st["t"] = now_s
        if quantised != st["q"]:
            # it moved. The spell that just ended is learned, up to the cap, so the longest flat spell this machine's own sensor
            # makes in health sets how long a flat spell must last before it means anything
            st["l"] = min(max(st["l"], st["f"]), LEARN_CAP_PERIODS * rule.min_s)
            st["m"] = min(st["m"] + 1, 1000)
            st["q"] = quantised
            st["f"] = 0.0
            st["x"] = False
        else:
            # only time the node was posting counts: a silent stretch adds one credit and no more
            st["f"] = st["f"] + min(elapsed, credit)
            limit = max(rule.min_s, LEARN_FACTOR * st["l"])
            if st["m"] >= MIN_MOVES and st["f"] >= limit and not (rule.rest_zero and quantised == 0):
                stuck[FIELD_SENSOR[col]] = "stuck"
                st["x"] = True
        state[col] = st
    return state, stuck
