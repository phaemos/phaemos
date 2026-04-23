// ============================================================
// sensors.ino - DHT22 and LDR sensor helpers for Arduino Uno
// ============================================================

#include <DHT.h>

#define DHT_PIN  2
#define DHT_TYPE DHT22
#define LDR_PIN  A0

DHT dht(DHT_PIN, DHT_TYPE);

void initSensors() {
  dht.begin();
}

void readDHT(float &temperature, float &humidity) {
  temperature = dht.readTemperature();
  humidity    = dht.readHumidity();

  if (isnan(temperature)) temperature = 0.0;
  if (isnan(humidity))    humidity    = 0.0;
}

void readLDR(int &lightLevel) {
  lightLevel = analogRead(LDR_PIN);
}
