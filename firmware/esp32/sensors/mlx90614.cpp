#include "mlx90614.h"
#include <Wire.h>
#include <Adafruit_MLX90614.h>

// the library defines its own MLX90614_ADDR for a register (0x2E), which clashes
// with the I2C address in config.h. drop the library's macro before config.h
// brings in the project one.
#undef MLX90614_ADDR
#include "../config.h"

// begin() takes the address from config.h so the bus map stays in one place.
static Adafruit_MLX90614 mlx;

bool initMLX90614() {
    if (!mlx.begin(MLX90614_ADDR)) {
        Serial.println("[MLX90614] ERROR: sensor not found");
        return false;
    }
    Serial.println("[MLX90614] init OK");
    return true;
}

float readMLX90614() {
    // read object temperature rather than ambient because the use case
    // is non-contact surface measurement, not air temperature.
    return mlx.readObjectTempC();
}
