#include <Arduino.h>
#include <Wire.h>

#include "../config.h"
#include "sensor_rail.h"
#if HAS_EXPANDER
#include "mcp23017.h"
#endif

void sensorRailInit() {
    // INPUT is high impedance with no pull. the board holds the switch on by itself.
    pinMode(SENSOR_POWER_PIN, INPUT);
}

void sensorRailPowerCycle() {
    // the switch alone does not remove power. while it is off, the I2C pull-ups would feed
    // the rail through the sensors' data pins. end the bus and hold both lines low for the
    // whole off period.
    Wire.end();
    pinMode(I2C_SDA, OUTPUT);
    pinMode(I2C_SCL, OUTPUT);
    digitalWrite(I2C_SDA, LOW);
    digitalWrite(I2C_SCL, LOW);
    // the DS18B20's data line has its own pull-up and the part can power itself from it, so it
    // is held low too. otherwise the probe stays alive through the off period and keeps its state.
    pinMode(DS18B20_PIN, OUTPUT);
    digitalWrite(DS18B20_PIN, LOW);

    // write the level before enabling the output so the pin never glitches low.
    digitalWrite(SENSOR_POWER_PIN, HIGH);
    pinMode(SENSOR_POWER_PIN, OUTPUT);
    delay(SENSOR_RAIL_OFF_MS);

    // back to an input is what switches the rail on. never drive this pin low.
    pinMode(SENSOR_POWER_PIN, INPUT);
    // the gate network has a 10 ms time constant, so SENSOR_RAIL_SETTLE_MS waits five of them before letting the bus lines go so the
    // sensors never see a bus that rises before their own supply does.
    delay(SENSOR_RAIL_SETTLE_MS);
    // release the clock first and the data line second. releasing data first would look like
    // a start condition to any device on the unswitched rail and leave it mid-address.
    pinMode(I2C_SCL, INPUT);
    pinMode(I2C_SDA, INPUT);
    pinMode(DS18B20_PIN, INPUT);

    // give the sensors time to start, then bring the bus back up.
    delay(SENSOR_RAIL_STARTUP_MS);
    Wire.begin(I2C_SDA, I2C_SCL, I2C_FREQ_HZ);
    Wire.setClock(I2C_FREQ_HZ);

#if HAS_EXPANDER
    // SENS_OK on the expander proves the rail came back and never that it went off, because the
    // pull-ups can keep it high while the switch is off. so the driver only looks for it to read high
    // within SENSOR_RAIL_RETURN_LIMIT_MS and never for it to fall. it reports the rail missing if it
    // does not and the sensors are still set up again, because they report their own loss. the check
    // is judged on the loop's own polls, so nothing here waits.
    expanderArmSensRailReturn(millis(), SENSOR_RAIL_RETURN_LIMIT_MS);
#endif
}
