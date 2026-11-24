// fitted.h - which of the hub's own sensors are fitted. the list comes from the HAS_ switches in
// config.h and is fixed at build time. it is never learned at boot, because a sensor that is dead
// at power-up must not be taken for one that is not fitted. a sensor that is not fitted is never
// set up, never probed, never reported as a fault and never in the faults map. header only and free
// of Arduino types, so the host test covers it.
#pragma once

#include "../config.h"
#include "health.h"

// the satellites and the supply have their own switches. the parts behind a satellite follow it.
inline bool sensorFitted(SensorKey k) {
    switch (k) {
        case SK_BME280:        return HAS_BME280 != 0;
        case SK_MPU6050:       return HAS_MPU6050 != 0;
        case SK_INA219:        return HAS_INA219 != 0;
        case SK_MLX90614:      return HAS_MLX90614 != 0;
        case SK_VL53L0X:       return HAS_VL53L0X != 0;
        case SK_AS5600:        return HAS_AS5600 != 0;
        case SK_DS18B20:       return HAS_DS18B20 != 0;
        case SK_MQ2:           return HAS_MQ2 != 0;
        case SK_LDR:           return HAS_LDR != 0;
        case SK_FC28:          return HAS_FC28 != 0;
        case SK_MAX4466:       return HAS_MAX4466 != 0;
        case SK_NANO_LINK:     return HAS_NANO != 0;
        case SK_NANO_BME280:   return HAS_NANO != 0;
        case SK_NANO_SUPPLY:   return HAS_NANO != 0;
        case SK_STM32_LINK:    return HAS_STM32 != 0;
        case SK_STM32_MPU6050: return HAS_STM32 != 0;
        case SK_SUPPLY:        return HAS_INPUT_MONITOR != 0;
        default:               return true;
    }
}

// at least one temperature source is fitted. a hub with none has no over-temperature alarm to
// report as unavailable
#define TEMP_ANY_FITTED (HAS_BME280 || HAS_DS18B20 || HAS_MLX90614)
