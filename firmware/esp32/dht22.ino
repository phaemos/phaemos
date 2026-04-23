// ============================================================
// dht22.ino - DHT22 temperature and humidity sensor
// ============================================================

#include <DHT.h>
#include "config.h"

#define DHT_TYPE DHT22

DHT dht(DHT_PIN, DHT_TYPE);

void initDHT() {
  dht.begin();
}

void readDHT(float &temperature, float &humidity) {
  temperature = dht.readTemperature();
  humidity    = dht.readHumidity();

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT22 read failed - using 0.0");
    temperature = 0.0;
    humidity    = 0.0;
  }
}
