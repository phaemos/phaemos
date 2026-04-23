// ============================================================
// dht22.ino - DHT22 temperature and humidity sensor
// ============================================================

#include <DHT.h>
#include "config.h"

#define DHT_TYPE DHT22

// Global sensor instance bound to configured pin/type.
DHT dht(DHT_PIN, DHT_TYPE);

void initDHT() {
  // Prepare internal state machine for sampling.
  dht.begin();
}

void readDHT(float &temperature, float &humidity) {
  // Read temperature (C) and relative humidity (%).
  temperature = dht.readTemperature();
  humidity    = dht.readHumidity();

  // DHT can occasionally fail due to timing/noise; guard with defaults.
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT22 read failed - using 0.0");
    temperature = 0.0;
    humidity    = 0.0;
  }
}
