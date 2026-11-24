"""
Sensor map - which telemetry fields each sensor produces and the fault states a node may report.

A node names a failed sensor in the `faults` object of its post (for example {"bme280": "missing"}). The backend
turns that into "do not trust these fields": a reading the sensor produced is stored as null, no threshold rule
fires on it and the anomaly model does not score the row. The keys below come from docs/sensor_reference.md, from
the JSON keys that firmware/esp32/esp32.ino posts and from the serial link contract between the hub and its two
satellites. Every telemetry field a node can send belongs to a sensor and a test fails when a new field is added
without one.
"""

# sensor key -> the telemetry fields it produces. Keys are lower case and match the part name where there is one.
SENSOR_FIELDS: dict[str, tuple[str, ...]] = {
    "bme280":   ("temperature", "humidity", "pressure"),
    "mpu6050":  ("vibration_x", "vibration_y", "vibration_z", "gyro_x", "gyro_y", "gyro_z"),
    "ina219":   ("bus_voltage", "current_ma", "power_mw"),
    "mlx90614": ("ir_temperature",),
    "vl53l0x":  ("distance_mm",),
    "mq2":      ("gas_level", "gas_alert"),
    "as5600":   ("shaft_angle", "shaft_rpm"),
    "max4466":  ("sound_level",),
    "ldr":      ("light_level",),
    "ds18b20":  ("contact_temp",),
    "fc28":     ("moisture_level", "water_detected"),
    # the Nano's own sensor and supply. The Nano's light and moisture inputs have no key of their own: only the
    # link to the Nano can stop them
    "nano_bme280": ("nano_temp", "nano_hum", "nano_pres"),
    "nano_supply": (),
    # the Black Pill's accelerometer and what the hub makes of it
    "stm32_mpu6050": (
        "fft_peak_hz", "vib_magnitude", "vib_rms_x", "vib_rms_y", "vib_rms_z", "vib_peak",
        "stm32_vib_x", "stm32_vib_y", "stm32_vib_z", "vib_clipping",
    ),
    # the serial links. A dead link stops every value that arrives over it, whatever sensor made it
    "nano_link": ("nano_temp", "nano_hum", "nano_pres", "nano_light", "nano_moist", "nano_water"),
    "stm32_link": (
        "fft_peak_hz", "vib_magnitude", "vib_rms_x", "vib_rms_y", "vib_rms_z", "vib_peak",
        "stm32_vib_x", "stm32_vib_y", "stm32_vib_z", "vib_clipping",
    ),
    # a known key that stops no telemetry field: the supply reading is not a telemetry column
    "supply":   (),
}

# the keys that name a serial link. A link shares its fields with the sensor behind it, so these are the only keys
# allowed to claim a field that another key claims
LINK_KEYS = frozenset({"nano_link", "stm32_link"})

# older or shorter spellings a node may send, mapped to the key above. "stm32" was the first name of stm32_link
SENSOR_ALIASES: dict[str, str] = {"stm32": "stm32_link"}

# field -> the sensor that owns it: the sensor behind the value or the link when only the link can stop it
FIELD_SENSOR: dict[str, str] = {}
for _sensor, _fields in SENSOR_FIELDS.items():
    if _sensor in LINK_KEYS:
        continue
    for _field in _fields:
        FIELD_SENSOR[_field] = _sensor
for _sensor in LINK_KEYS:
    for _field in SENSOR_FIELDS[_sensor]:
        FIELD_SENSOR.setdefault(_field, _sensor)

# a few states stop only some of a key's fields. An unplugged moisture input reads the same on this circuit as a probe
# flooded with a conductive liquid, so the leak alarm must win: unplugged stops the moisture level and keeps the water
# flag, stored and still firing its rule. Any other state of the key stops every field, as usual. Any other key can
# be listed here the same way
PARTIAL_STATE_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("fc28", "unplugged"): ("moisture_level",),
}


def state_fields(key: str, state: str) -> tuple[str, ...]:
    """The fields a sensor key stops while it is in the given state."""
    key = SENSOR_ALIASES.get(key, key)
    return PARTIAL_STATE_FIELDS.get((key, state), SENSOR_FIELDS.get(key, ()))


# the fields that hold a true or false flag and not a number
BOOLEAN_FIELDS = frozenset({"gas_alert", "water_detected", "nano_water", "vib_clipping"})

# the states a node may report for a sensor (design review section 2.2). "ok" is accepted and means no fault,
# so a node that lists every sensor is not read as having faults
FAULT_STATES = (
    "missing", "stuck", "out_of_range", "rate", "stale", "intermittent", "disagree", "warming_up", "not_fitted",
    # an analogue input that reads zero and the states of a serial link
    "unplugged", "line_low", "silent", "garbage", "one_way",
)
# stored for any state string the backend does not know, so a newer firmware never loses a fault
UNKNOWN_STATE = "unknown"
# the states that are not a failure: warming up ends by itself and not fitted is a statement about the machine
QUIET_STATES = frozenset({"warming_up", "not_fitted"})

# what each state means in plain words, for the text of an alert
STATE_WORDS = {
    "missing": "not answering",
    "stuck": "stuck on one value",
    "out_of_range": "reading outside what it can measure",
    "rate": "changing faster than it can",
    "stale": "giving old values",
    "intermittent": "dropping in and out",
    "disagree": "disagreeing with another sensor",
    "warming_up": "still warming up",
    "not_fitted": "not fitted",
    "unplugged": "unplugged",
    "line_low": "cut off, with its line held low",
    "silent": "silent",
    "garbage": "sending corrupt data",
    "one_way": "answering in one direction only",
    UNKNOWN_STATE: "in a fault state the backend does not know",
}

# limits on what one post may carry, so a faulty node cannot make a row or a log line large
# comfortably more than there are keys in the map (the rest is room for a few the backend does not know yet), derived from it
# so adding a key to the map cannot leave the cap below the number of keys
MAX_FAULT_ENTRIES = len(SENSOR_FIELDS) + 16
MAX_FAULT_KEY_LENGTH = 32


def canonical_key(key: str) -> str:
    return SENSOR_ALIASES.get(key, key)


def storable_text(value) -> bool:
    """
    True when a string can be stored as it is: no control character (a NUL is refused by PostgreSQL) and no lone
    surrogate (which cannot be encoded as UTF-8).
    """
    if not isinstance(value, str):
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def clean_faults(raw) -> dict[str, str]:
    """
    Reduce a node's `faults` object to a short map of sensor key to a known state string.

    Absent, null and empty all mean nothing is wrong. A state of "ok" is dropped. Any other state the backend does
    not know is stored as "unknown". Keys are trimmed, lower cased, cut to MAX_FAULT_KEY_LENGTH and mapped through
    SENSOR_ALIASES and only the first MAX_FAULT_ENTRIES entries are kept. A key that cannot be stored (a control
    character or a lone surrogate) is left out. A value that is not an object is refused by the caller.
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("faults must be an object mapping a sensor key to a state")
    cleaned: dict[str, str] = {}
    for key, state in raw.items():
        if not storable_text(str(key)):
            continue
        name = str(key).strip().lower()[:MAX_FAULT_KEY_LENGTH]
        if not name:
            continue
        name = canonical_key(name)
        word = state.strip().lower() if isinstance(state, str) else ""
        if word == "ok":
            continue
        cleaned[name] = word if word in FAULT_STATES else UNKNOWN_STATE
        if len(cleaned) >= MAX_FAULT_ENTRIES:
            break
    return cleaned


def has_unstorable_key(raw) -> bool:
    """True when a raw faults object has a key that clean_faults would leave out as unstorable."""
    return isinstance(raw, dict) and any(not storable_text(str(k)) for k in raw)


def faulted_fields(faults: dict[str, str]) -> set[str]:
    """The telemetry fields that a fault map stops, which is every field of every sensor it names."""
    return {field for sensor, state in faults.items() for field in state_fields(sensor, state)}
