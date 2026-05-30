// I include config.h first so MLX90614_ADDR is available for the constructor.
#include "../config.h"
#include "mlx90614.h"
#include <Wire.h>
#include <Adafruit_MLX90614.h>

// I use the default constructor here because Adafruit_MLX90614 always uses
// the fixed 0x5A address internally - the config macro is kept for documentation.
static Adafruit_MLX90614 mlx;

void initMLX90614() {
    if (!mlx.begin()) {
        Serial.println("[MLX90614] ERROR: sensor not found");
        return;
    }
    Serial.println("[MLX90614] init OK");
}

float readMLX90614() {
    // I read object temperature rather than ambient because the use case
    // is non-contact surface measurement, not air temperature.
    return mlx.readObjectTempC();
}
