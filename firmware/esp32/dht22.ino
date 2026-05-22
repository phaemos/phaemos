// ============================================================
// dht22.ino - DHT22 temperature and humidity sensor
// ============================================================

// DHT.h is provided by the "DHT sensor library" by Adafruit - install via Arduino Library Manager.
#include <DHT.h>
// config.h defines DHT_PIN and other board-level constants so this file stays hardware-agnostic.
#include "config.h"

// I tell the library which protocol variant to use; DHT22 has higher precision than DHT11.
#define DHT_TYPE DHT22

// I declare the sensor instance globally so initDHT() and readDHT() share the same object without passing pointers.
DHT dht(DHT_PIN, DHT_TYPE);

void initDHT() {
  // I prepare the internal state machine for sampling.
  // This must be called in setup() before the first readTemperature()/readHumidity() call.
  dht.begin();
}

// I use C++ references for temperature and humidity so changes here update the caller's variables directly.
void readDHT(float &temperature, float &humidity) {
  // I read temperature in Celsius and relative humidity as a percentage.
  temperature = dht.readTemperature();
  humidity    = dht.readHumidity();

  // I guard against occasional DHT failures caused by timing or noise.
  // isnan() checks for IEEE-754 NaN, which the library returns when a read times out.
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT22 read failed - using 0.0");
    // I fall back to 0.0 so the JSON payload is always a valid number, not NaN/null.
    temperature = 0.0;
    humidity    = 0.0;
  }
}
