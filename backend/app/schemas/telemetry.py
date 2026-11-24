import math
import re
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.sensor_map import SENSOR_FIELDS, canonical_key, clean_faults, has_unstorable_key, storable_text

# the fields a node adds to describe its own health. They are not sensor readings, so they never reach the
# telemetry columns by name, the alert rules or the model
HEALTH_FIELDS = frozenset({
    "seq", "boot", "up", "ts", "faults", "reset_reason", "rssi", "heap_free", "fw", "links",
    "diag", "board_mismatch", "not_fitted",
    "dropped_health", "dropped_values",
})
# fields of the ingest body that are neither a sensor reading nor a node health field: the device label (ignored), the node type and
# the time a gateway says the reading was taken. Listed on purpose, so a new field is either a measurement that belongs to a
# sensor (tests/test_sensor_map.py) or named here
NON_MEASUREMENT_FIELDS = frozenset({"device_id", "node_type", "observed_at"})
# the two fields the validator fills in to say what it left out. A node cannot send them
DROPPED_FIELDS = frozenset({"dropped_health", "dropped_values"})

# the new satellite values and the range each may take. A value outside it is physically impossible for the part
# (the Nano's ADC is 10 bit, the BME280 compensates inside its data sheet range, the MPU6050 never exceeds its
# +/-16 g full scale and the peak of the alternating part can reach twice that). Healthy firmware already keeps its
# own values inside these, so an outside value means a corrupt line. It is dropped and the reading is kept, which
# differs from the older sensor values and is noted in quality.dropped_values
_VALUE_RANGES = {
    # the classic sensor fields. Each range is wider than the part's own data sheet range, so a healthy part is never touched
    # and far inside what a corrupt or hostile number looks like (1e308 was accepted before). A value outside it is dropped
    # and noted like the satellite values and the sensor that makes it is then treated as out of range by the sensor fault
    # alerts (services/health_service.py), so a node cannot use an impossible value to quietly switch a rule off
    "temperature": (-90.0, 250.0),
    "humidity": (0.0, 100.0),
    "pressure": (300.0, 1100.0),
    "vibration_x": (-160.0, 160.0),
    "vibration_y": (-160.0, 160.0),
    "vibration_z": (-160.0, 160.0),
    "gyro_x": (-2100.0, 2100.0),
    "gyro_y": (-2100.0, 2100.0),
    "gyro_z": (-2100.0, 2100.0),
    "bus_voltage": (0.0, 32.0),
    "current_ma": (-10_000.0, 10_000.0),
    "power_mw": (-100_000.0, 100_000.0),
    "ir_temperature": (-70.0, 380.0),
    "distance_mm": (0.0, 9000.0),
    "gas_level": (0.0, 65_535.0),
    "shaft_angle": (0.0, 360.0),
    "shaft_rpm": (-30_000.0, 30_000.0),
    "sound_level": (0.0, 65_535.0),
    "light_level": (0.0, 65_535.0),
    # the DS18B20 reports -127 when it is not connected, which is outside its range and so reads as the fault it is
    "contact_temp": (-55.0, 125.0),
    "moisture_level": (0.0, 65_535.0),
    "fft_peak_hz": (0.0, 50_000.0),
    "vib_magnitude": (0.0, 160.0),
    "nano_temp": (-40.0, 85.0),
    "nano_hum": (0.0, 100.0),
    "nano_pres": (300.0, 1100.0),
    "nano_light": (0.0, 1023.0),
    "nano_moist": (0.0, 1023.0),
    "vib_rms_x": (0.0, 16.0),
    "vib_rms_y": (0.0, 16.0),
    "vib_rms_z": (0.0, 16.0),
    "vib_peak": (0.0, 32.0),
    "stm32_vib_x": (-16.0, 16.0),
    "stm32_vib_y": (-16.0, 16.0),
    "stm32_vib_z": (-16.0, 16.0),
}

# per serial link counters and their bounds: good lines, checksum errors, lines refused for their format,
# sequence gaps and satellite restarts since the hub booted, the satellite's status mask, its uptime in seconds
# and its supply in millivolts
_LINK_INTS = {
    "ok": (0, 4_294_967_295), "crc": (0, 4_294_967_295), "fmt": (0, 4_294_967_295), "gaps": (0, 4_294_967_295),
    "restarts": (0, 4_294_967_295), "st": (0, 65_535), "up": (0, 2_147_483_647), "vcc": (0, 65_535),
}
MAX_LINKS = 4
MAX_LINK_NAME_LENGTH = 16

# bench counters the hub posts as `diag`: at most this many keys, each a short name and a whole number in range
MAX_DIAG_KEYS = 16
MAX_DIAG_NAME_LENGTH = 24
DIAG_MAX_VALUE = 4_294_967_295
_DIAG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
# a node type: 1 to 20 of a-z 0-9 _ -, never starting with a hyphen
_NODE_TYPE = re.compile(r"[a-z0-9_][a-z0-9_-]{0,19}")

# the integer health fields and their inclusive bounds and the string ones with their longest length
_HEALTH_INTS = {
    "seq": (0, 4_294_967_295),
    "boot": (0, 2_147_483_647),
    "up": (0, 2_147_483_647),
    # Unix seconds, 2001 to 2100
    "ts": (1_000_000_000, 4_102_444_800),
    "rssi": (-127, 20),
    "heap_free": (0, 2_147_483_647),
}
_HEALTH_STRINGS = {"reset_reason": 40, "fw": 50}


def _valid_health_int(value, low: int, high: int) -> bool:
    # a whole number inside the bounds. A bool is not a count and a string is not a number
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        value = int(value) if value.is_integer() else None
    return isinstance(value, int) and low <= value <= high


def clean_links(raw) -> tuple[dict, bool]:
    """
    The per link counters of a post, cut down to the known names and bounds.

    Returns the cleaned object and whether anything had to be dropped. A value out of bounds is left out of its
    link, a link that is not an object or has an unstorable name is left out and at most MAX_LINKS are kept.
    """
    if not isinstance(raw, dict):
        return {}, True
    out: dict = {}
    bad = False
    for name, entry in raw.items():
        key = str(name).strip().lower()[:MAX_LINK_NAME_LENGTH]
        if not storable_text(str(name)) or not key or not isinstance(entry, dict) or len(out) >= MAX_LINKS:
            bad = True
            continue
        item = {}
        for field, (low, high) in _LINK_INTS.items():
            if entry.get(field) is None:
                continue
            if _valid_health_int(entry[field], low, high):
                item[field] = int(entry[field])
            else:
                bad = True
        out[key] = item
    return out, bad


def clean_diag(raw) -> tuple[dict, bool]:
    """
    The hub's bench counters, cut down to at most MAX_DIAG_KEYS short names with whole-number values in range.

    Returns the cleaned object and whether anything was dropped: a key that is too long, badly spelt or past the
    limit and a value that is negative, too large, fractional or not a number.
    """
    if not isinstance(raw, dict):
        return {}, True
    out: dict = {}
    bad = False
    for name, value in raw.items():
        ok = (
            isinstance(name, str) and len(name) <= MAX_DIAG_NAME_LENGTH and _DIAG_NAME.fullmatch(name)
            and _valid_health_int(value, 0, DIAG_MAX_VALUE)
        )
        if not ok or len(out) >= MAX_DIAG_KEYS:
            bad = True
            continue
        out[name] = int(value)
    return out, bad


def clean_not_fitted(raw) -> tuple[list, bool]:
    """The sensor keys the firmware was built without: only keys in the sensor map (aliases mapped), each once."""
    if not isinstance(raw, list):
        return [], True
    out: list = []
    bad = False
    for item in raw:
        key = canonical_key(str(item).strip().lower()) if isinstance(item, str) else None
        if key in SENSOR_FIELDS and key not in out:
            out.append(key)
        else:
            bad = key not in SENSOR_FIELDS or bad
    return out, bad


# --- TelemetryIngest ---
# the payload any firmware node POSTs to /api/v1/telemetry.
# all sensor fields are optional so nodes with fewer sensors still pass validation.
class TelemetryIngest(BaseModel):
    # a NaN or infinity passes for a float by default and one such reading would blank a whole bucket's average,
    # so they are refused with a 422. A reading a sensor cannot take is sent as null or left out
    model_config = ConfigDict(allow_inf_nan=False)

    # sent as a plain string from firmware; the backend resolves it to a UUID before storing.
    # optional and ignored: the device is the one the X-API-Key belongs to, so the body cannot name another. A client may send its own
    # label (the clients send "node-1" and the like) or leave it out
    device_id:    str | None = None
    # when the reading was taken, for a gateway that spooled it. recorded_at stays the time it was received. Honoured within a bound
    # of the past and never in the future and a reading older than a live one is stored but not judged as current: see
    # routes/telemetry.py resolve_observed
    observed_at:  datetime | None = None
    # node_type identifies which board sent this reading (esp32, stm32, nano, pico_w)
    node_type:    str | None = Field(default=None, max_length=20)

    # BME280
    temperature:  float | None = None
    humidity:     float | None = None
    pressure:     float | None = None

    # MPU6050 accelerometer axes (g-units)
    vibration_x:  float | None = None
    vibration_y:  float | None = None
    vibration_z:  float | None = None
    # MPU6050 gyroscope axes (degrees/second)
    gyro_x:       float | None = None
    gyro_y:       float | None = None
    gyro_z:       float | None = None

    # INA219 current monitor
    bus_voltage:  float | None = None
    current_ma:   float | None = None
    power_mw:     float | None = None

    # MLX90614 IR surface temperature
    ir_temperature: float | None = None

    # VL53L0X time-of-flight distance
    distance_mm:  float | None = None

    # MQ-2 gas sensor
    gas_level:    float | None = None
    gas_alert:    bool | None = None

    # AS5600 magnetic encoder
    shaft_angle:  float | None = None
    shaft_rpm:    float | None = None

    # MAX4466 microphone
    sound_level:  float | None = None

    # LDR ambient light (raw ADC reading)
    light_level:  float | None = None

    # DS18B20 contact temperature
    contact_temp: float | None = None

    # FC-28 moisture / water ingress
    moisture_level: float | None = None
    water_detected: bool | None = None

    # STM32 FFT output fields forwarded by the ESP32 after parsing UART
    fft_peak_hz:  float | None = None
    vib_magnitude: float | None = None
    # the Black Pill's RMS and peak of the alternating part and its three axis means, forwarded by the hub. In g
    vib_rms_x:    float | None = None
    vib_rms_y:    float | None = None
    vib_rms_z:    float | None = None
    vib_peak:     float | None = None
    stm32_vib_x:  float | None = None
    stm32_vib_y:  float | None = None
    stm32_vib_z:  float | None = None
    # true when a sample in the window reached the vibration sensor's limit. A reading and not a fault
    vib_clipping: bool | None = None

    # the Arduino Nano's values, forwarded by the hub
    nano_temp:    float | None = None
    nano_hum:     float | None = None
    nano_pres:    float | None = None
    nano_light:   float | None = None
    nano_moist:   float | None = None
    nano_water:   bool | None = None

    # --- node health, all optional so a node that does not send them keeps working ---
    # a bad health field never costs the reading: it is dropped, named in dropped_health and counted on the device's
    # health row. Sensor values above keep their strict validation.
    # a counter that rises by one per post. A jump means posts were lost
    seq:          int | None = None
    # boot count kept in the node's flash. A rise is a restart
    boot:         int | None = None
    # uptime in seconds
    up:           int | None = None
    # Unix seconds from the node's own clock, sent only once that clock is set
    ts:           int | None = None
    # sensor key -> state for each sensor that is not trustworthy. Empty or absent when all is well
    faults:       dict[str, str] | None = None
    reset_reason: str | None = None
    # Wi-Fi signal strength in dBm
    rssi:         int | None = None
    # free heap in bytes
    heap_free:    int | None = None
    # firmware version string
    fw:           str | None = None
    # the state and counters of each serial link the hub watches: {"nano": {"ok": 1042, "crc": 0, "gaps": 0,
    # "restarts": 0, "st": 0, "up": 5210, "vcc": 4980}, "stm32": {...}}
    links:        dict[str, dict[str, int]] | None = None
    # the hub's bench counters (post counters, bodies replaced, stack high-water marks, lowest free heap, largest free
    # block), at most 16 short names with whole-number values. Anything else is dropped
    diag:         dict[str, int] | None = None
    # true when the firmware image was built for another board than the one it runs on. Raises one monitoring alert
    board_mismatch: bool | None = None
    # the sensor keys the firmware was built without, posted once per boot. A fault on one of them is not a fault
    not_fitted:   list[str] | None = None
    # what the validator below left out of this post, so the row can say so. A node cannot send these
    dropped_health: list[str] | None = None
    dropped_values: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_bad_health(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # a node cannot name its own dropped fields
        for name in DROPPED_FIELDS:
            data.pop(name, None)
        dropped: list[str] = []
        dropped_values: list[str] = []
        # node_type is stored in a 20 character column. One that is longer or holds a control character, is dropped
        # and the reading kept (it is then scored by the general model) and it is named like a dropped value
        node_type = data.get("node_type")
        if isinstance(node_type, str):
            # lower case, as the models name node types, so "ESP32" and "esp32" are one
            node_type = node_type.strip().lower()
            data["node_type"] = node_type
        # a name is letters, digits, underscore and hyphen only. A leading = + - @ or a control character in a cell would be a
        # formula in a spreadsheet that opens an export
        if node_type is not None and not (isinstance(node_type, str) and _NODE_TYPE.fullmatch(node_type)):
            dropped_values.append("node_type")
            data.pop("node_type")
        for name, (low, high) in _VALUE_RANGES.items():
            value = data.get(name)
            # a number given as a string is checked as the number it will become
            if isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    value = None
            # a non-number is left for the type check and a non-finite one for the finite check, which both refuse
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                if not low <= value <= high:
                    dropped_values.append(name)
                    data.pop(name)
        for name, (low, high) in _HEALTH_INTS.items():
            if data.get(name) is not None and not _valid_health_int(data[name], low, high):
                dropped.append(name)
                data.pop(name)
        for name, longest in _HEALTH_STRINGS.items():
            if data.get(name) is not None and not (
                isinstance(data[name], str) and len(data[name]) <= longest and storable_text(data[name])
            ):
                dropped.append(name)
                data.pop(name)
        if "faults" in data:
            try:
                # a key that cannot be stored is left out of the map and the rest is kept
                if has_unstorable_key(data["faults"]):
                    dropped.append("faults")
                data["faults"] = clean_faults(data["faults"])
            except ValueError:
                dropped.append("faults")
                data.pop("faults")
        if data.get("links") is not None:
            if isinstance(data["links"], dict):
                data["links"], bad = clean_links(data["links"])
                if bad:
                    dropped.append("links")
            else:
                # not an object: dropped whole, so the last links stay
                dropped.append("links")
                data.pop("links")
        elif "links" in data:
            data.pop("links")
        if data.get("diag") is not None:
            if isinstance(data["diag"], dict):
                data["diag"], bad = clean_diag(data["diag"])
                if bad:
                    dropped.append("diag")
            else:
                # not an object: dropped whole, so the last counters stay
                dropped.append("diag")
                data.pop("diag")
        elif "diag" in data:
            data.pop("diag")
        if data.get("board_mismatch") is not None and not isinstance(data["board_mismatch"], bool):
            dropped.append("board_mismatch")
            data.pop("board_mismatch")
        if data.get("not_fitted") is not None:
            if isinstance(data["not_fitted"], list):
                data["not_fitted"], bad = clean_not_fitted(data["not_fitted"])
                if bad:
                    dropped.append("not_fitted")
            else:
                dropped.append("not_fitted")
                data.pop("not_fitted")
        elif "not_fitted" in data:
            data.pop("not_fitted")
        if dropped:
            data["dropped_health"] = dropped
        if dropped_values:
            data["dropped_values"] = dropped_values
        return data

    def reading(self) -> dict:
        """The sensor readings alone: no device id and none of the health fields."""
        return self.model_dump(exclude={"device_id", "observed_at"} | HEALTH_FIELDS)


# --- TelemetryResponse ---
# what the API returns when a client queries stored telemetry records.
class TelemetryResponse(BaseModel):
    id:             UUID
    # device_id is a proper UUID here because the backend has already resolved it from the ingest string.
    device_id:      UUID
    node_type:      str | None

    # BME280
    temperature:    float | None
    humidity:       float | None
    pressure:       float | None

    # MPU6050
    vibration_x:    float | None
    vibration_y:    float | None
    vibration_z:    float | None
    gyro_x:         float | None
    gyro_y:         float | None
    gyro_z:         float | None

    # INA219
    bus_voltage:    float | None
    current_ma:     float | None
    power_mw:       float | None

    # MLX90614
    ir_temperature: float | None

    # VL53L0X
    distance_mm:    float | None

    # MQ-2
    gas_level:      float | None
    gas_alert:      bool | None

    # AS5600
    shaft_angle:    float | None
    shaft_rpm:      float | None

    # MAX4466
    sound_level:    float | None

    # LDR
    light_level:    float | None

    # DS18B20
    contact_temp:   float | None

    # FC-28
    moisture_level: float | None
    water_detected: bool | None

    # STM32 FFT
    fft_peak_hz:    float | None
    vib_magnitude:  float | None

    # the Black Pill's RMS and peak of the alternating part and its three axis means, in g
    vib_rms_x:      float | None = None
    vib_rms_y:      float | None = None
    vib_rms_z:      float | None = None
    vib_peak:       float | None = None
    stm32_vib_x:    float | None = None
    stm32_vib_y:    float | None = None
    stm32_vib_z:    float | None = None
    # true when a sample in the window reached the vibration sensor's limit
    vib_clipping:   bool | None = None

    # the Arduino Nano's values, forwarded by the hub
    nano_temp:      float | None = None
    nano_hum:       float | None = None
    nano_pres:      float | None = None
    nano_light:     float | None = None
    nano_moist:     float | None = None
    nano_water:     bool | None = None

    # ML output
    # computed by the anomaly-detection model; higher value = more unusual reading.
    anomaly_score:  float | None
    # boolean flag derived from anomaly_score; makes it easy to filter alerts without comparing floats.
    is_anomaly:     bool

    # server-side timestamp set when the record is written - not trusting the device clock.
    recorded_at:    datetime

    # node health that arrived with this reading. All empty for a node that does not send it.
    # the node's post counter and the time from its own clock (shown, never used to order rows)
    seq:            int | None = None
    device_ts:      datetime | None = None
    # {"faults": {sensor: state}, "rejected": {field: value}, "dropped_health": [field]} when the node reported a
    # fault or sent a health field that could not be used, else null. rejected holds a value the node sent for a
    # faulted sensor, which is stored as null in its own column. dropped_health names health fields that were
    # out of bounds or malformed and were left out while the reading was kept
    quality:        dict | None = None

    # required so Pydantic can serialise SQLAlchemy ORM row objects into this schema.
    model_config = {"from_attributes": True}


# --- TelemetryBucketResponse ---
# one row per time bucket when GET /telemetry/{device_id} is called with ?bucket=SECONDS.
# the aggregate for each column is fixed by what the reading means (see services/telemetry_buckets.py):
# mean for continuous readings, a circular mean for shaft_angle, a peak (_peak) beside the mean of each signed axis,
# maximum for anomaly_score and vib_magnitude, fft_peak_hz taken from the strongest vibration, logical OR for flags.
class TelemetryBucketResponse(BaseModel):
    device_id:      UUID
    # the start of the bucket, aligned to the Unix epoch: a 300 second bucket starts on a five minute mark.
    recorded_at:    datetime
    # how many rows (posts) fall in the bucket. It is not a count per column: when several node types report for one
    # machine a given column may come from only some of them. Lets a thin bucket be told from a full one.
    reading_count:  int

    # means
    temperature:    float | None
    humidity:       float | None
    pressure:       float | None
    vibration_x:    float | None
    vibration_y:    float | None
    vibration_z:    float | None
    gyro_x:         float | None
    gyro_y:         float | None
    gyro_z:         float | None
    bus_voltage:    float | None
    current_ma:     float | None
    power_mw:       float | None
    ir_temperature: float | None
    distance_mm:    float | None
    gas_level:      float | None
    # circular mean in degrees, 0 up to 360
    shaft_angle:    float | None
    shaft_rpm:      float | None
    sound_level:    float | None
    light_level:    float | None
    contact_temp:   float | None
    moisture_level: float | None

    # largest absolute value in the bucket, for the signed axes whose mean is only the static offset
    vibration_x_peak: float | None
    vibration_y_peak: float | None
    vibration_z_peak: float | None
    gyro_x_peak:    float | None
    gyro_y_peak:    float | None
    gyro_z_peak:    float | None

    # means of the satellite values
    vib_rms_x:      float | None = None
    vib_rms_y:      float | None = None
    vib_rms_z:      float | None = None
    stm32_vib_x:    float | None = None
    stm32_vib_y:    float | None = None
    stm32_vib_z:    float | None = None
    nano_temp:      float | None = None
    nano_hum:       float | None = None
    nano_pres:      float | None = None
    nano_light:     float | None = None
    nano_moist:     float | None = None
    # largest absolute value in the bucket, as for the other signed axes
    stm32_vib_x_peak: float | None = None
    stm32_vib_y_peak: float | None = None
    stm32_vib_z_peak: float | None = None

    # maxima
    anomaly_score:  float | None
    vib_magnitude:  float | None
    # the largest peak of the alternating part in the bucket
    vib_peak:       float | None = None
    # the frequency of the reading with the strongest vibration (largest vib_magnitude) in the bucket
    fft_peak_hz:    float | None

    # logical OR: true when any reading in the bucket had the flag raised
    gas_alert:      bool | None
    water_detected: bool | None
    nano_water:     bool | None = None
    # true when any reading in the bucket hit the vibration sensor's limit
    vib_clipping:   bool | None = None
    is_anomaly:     bool
