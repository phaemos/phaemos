from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


# --- TelemetryIngest ---
# The payload any firmware node POSTs to /api/v1/telemetry.
# All sensor fields are optional so nodes with fewer sensors still pass validation.
class TelemetryIngest(BaseModel):
    # Sent as a plain string from firmware; the backend resolves it to a UUID before storing.
    device_id:    str
    # node_type identifies which board sent this reading (esp32, stm32, nano, pico_w)
    node_type:    str | None = None

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


# --- TelemetryResponse ---
# What the API returns when a client queries stored telemetry records.
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

    # ML output
    # Computed by the anomaly-detection model; higher value = more unusual reading.
    anomaly_score:  float | None
    # Boolean flag derived from anomaly_score; makes it easy to filter alerts without comparing floats.
    is_anomaly:     bool

    # Server-side timestamp set when the record is written - not trusting the device clock.
    recorded_at:    datetime

    # Required so Pydantic can serialise SQLAlchemy ORM row objects into this schema.
    model_config = {"from_attributes": True}
