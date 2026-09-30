"""The four PHAEMOS node types and the healthy operating range of each sensor field."""

from dataclasses import dataclass

# (mean, standard deviation) of each field on a healthy machine
HEALTHY: dict[str, tuple[float, float]] = {
    "temperature": (24.0, 0.6),
    "humidity": (48.0, 2.0),
    "pressure": (1013.0, 1.5),
    "vibration_x": (0.05, 0.02),
    "vibration_y": (0.05, 0.02),
    "vibration_z": (1.0, 0.02),
    "gyro_x": (0.0, 0.5),
    "gyro_y": (0.0, 0.5),
    "gyro_z": (0.0, 0.5),
    "bus_voltage": (5.0, 0.05),
    "current_ma": (420.0, 15.0),
    "power_mw": (2100.0, 80.0),
    "ir_temperature": (31.0, 0.8),
    "distance_mm": (120.0, 2.0),
    "gas_level": (180.0, 15.0),
    "shaft_angle": (180.0, 100.0),
    "shaft_rpm": (1450.0, 10.0),
    "sound_level": (52.0, 3.0),
    "light_level": (620.0, 40.0),
    "contact_temp": (29.0, 0.5),
    "moisture_level": (40.0, 10.0),
    "fft_peak_hz": (24.2, 0.3),
    "vib_magnitude": (0.08, 0.02),
}


@dataclass(frozen=True)
class Node:
    node_type: str
    fields: tuple[str, ...]


NODES: dict[str, Node] = {
    # the ESP32 primary node carries 11 sensors and forwards the STM32's FFT results
    "esp32": Node(
        "esp32",
        (
            "temperature",
            "humidity",
            "pressure",
            "vibration_x",
            "vibration_y",
            "vibration_z",
            "gyro_x",
            "gyro_y",
            "gyro_z",
            "bus_voltage",
            "current_ma",
            "power_mw",
            "ir_temperature",
            "distance_mm",
            "gas_level",
            "shaft_angle",
            "shaft_rpm",
            "sound_level",
            "light_level",
            "contact_temp",
            "moisture_level",
            "fft_peak_hz",
            "vib_magnitude",
        ),
    ),
    "stm32": Node(
        "stm32",
        (
            "vibration_x",
            "vibration_y",
            "vibration_z",
            "gyro_x",
            "gyro_y",
            "gyro_z",
            "fft_peak_hz",
            "vib_magnitude",
        ),
    ),
    "nano": Node("nano", ("temperature", "humidity", "pressure", "light_level", "moisture_level")),
    "pico_w": Node("pico_w", ("temperature", "humidity", "pressure", "light_level")),
}

# how each fault moves the fields at full severity, as multiples of the healthy mean
FAULTS: dict[str, dict[str, float]] = {
    "bearing": {
        "vibration_x": 12.0,
        "vibration_y": 12.0,
        "vib_magnitude": 10.0,
        "fft_peak_hz": 3.5,
        "sound_level": 1.4,
        "contact_temp": 1.3,
    },
    "overheat": {
        "temperature": 1.6,
        "ir_temperature": 2.2,
        "contact_temp": 2.4,
        "current_ma": 1.5,
        "power_mw": 1.5,
    },
    "leak": {"moisture_level": 2.4, "humidity": 1.5},
    "gas": {"gas_level": 5.0},
}
