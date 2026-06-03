import uuid
# Float stores decimal sensor readings; Boolean stores true/false flags (e.g. is_anomaly)
# String added in v2.0 to store the node_type identifier (esp32, stm32, nano, pico_w)
from sqlalchemy import Column, Float, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Telemetry(Base):
    __tablename__ = "telemetry"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # ForeignKey("devices.id") creates a database-level link to the devices table
    # ondelete="CASCADE" means if a device is deleted, all its telemetry rows are also deleted automatically
    device_id     = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    # I store node_type so the API can filter readings by which physical board sent them
    node_type     = Column(String(20))

    # Sensor readings are nullable - a device may not report every metric on every reading

    # BME280 - temperature, humidity, pressure (I2C 0x76)
    temperature   = Column(Float)
    humidity      = Column(Float)
    pressure      = Column(Float)

    # MPU6050 - accelerometer and gyroscope axes (I2C 0x68)
    # Vibration is split into three axes (x, y, z) to capture the full 3-D motion vector
    vibration_x   = Column(Float)
    vibration_y   = Column(Float)
    vibration_z   = Column(Float)
    # Gyro axes give rotational rate in degrees/second; useful for detecting shaft wobble
    gyro_x        = Column(Float)
    gyro_y        = Column(Float)
    gyro_z        = Column(Float)

    # INA219 - current and voltage monitor (I2C 0x40)
    # I track bus_voltage + current_ma + power_mw together; dropping any one of them
    # makes the electrical health check incomplete
    bus_voltage   = Column(Float)
    current_ma    = Column(Float)
    power_mw      = Column(Float)

    # MLX90614 - contactless IR surface temperature (I2C 0x5A)
    # Separate from BME280 temperature so hot-spot detection works alongside ambient
    ir_temperature = Column(Float)

    # VL53L0X - time-of-flight distance sensor (I2C 0x29)
    # Used to detect shaft displacement or proximity alerts
    distance_mm   = Column(Float)

    # MQ-2 - gas and smoke detection (analog GPIO34)
    gas_level     = Column(Float)
    # gas_alert is a pre-computed boolean from the digital output pin; avoids re-thresholding on the backend
    gas_alert     = Column(Boolean, default=False)

    # AS5600 - magnetic rotary encoder (I2C 0x36)
    shaft_angle   = Column(Float)
    shaft_rpm     = Column(Float)

    # MAX4466 - electret microphone amplifier (analog GPIO32)
    sound_level   = Column(Float)

    # LDR - ambient light (analog GPIO33 in v2)
    light_level   = Column(Float)

    # DS18B20 - precision contact temperature via OneWire (GPIO4)
    # Distinct from ir_temperature and BME280 temperature to allow tripling up on heat monitoring
    contact_temp  = Column(Float)

    # FC-28 - water ingress / moisture sensor (analog GPIO36)
    moisture_level = Column(Float)
    water_detected = Column(Boolean, default=False)

    # STM32 Black Pill FFT output - received over UART from the vibration node
    # fft_peak_hz tells us which frequency dominates the vibration spectrum
    fft_peak_hz   = Column(Float)
    vib_magnitude = Column(Float)

    # ML output - computed by ml_service after ingest
    # anomaly_score is a continuous value (e.g. 0.0–1.0) from an ML model indicating how unusual this reading is
    anomaly_score = Column(Float)
    # is_anomaly is a derived boolean flag: True when anomaly_score crosses the configured threshold
    is_anomaly    = Column(Boolean, default=False)

    # server_default=func.now() stamps the row with the DB server's current time at insert
    recorded_at   = Column(DateTime(timezone=True), server_default=func.now())
