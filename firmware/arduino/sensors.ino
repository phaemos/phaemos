// ============================================================
// sensors.ino - DHT22 and LDR sensor helpers for Arduino Uno
// ============================================================

#include <DHT.h>

#define DHT_PIN  2
#define DHT_TYPE DHT22
#define LDR_PIN  A0

// DHT object wraps timing-sensitive protocol handling for the sensor.
DHT dht(DHT_PIN, DHT_TYPE);

void initSensors() {
  // Must be called before first read; sets up internal timing state.
  dht.begin();
}

void readDHT(float &temperature, float &humidity) {
  // Library returns NAN on checksum/timing failures.
  temperature = dht.readTemperature();
  humidity    = dht.readHumidity();

  // Fallback to safe defaults so downstream code always has numbers.
  if (isnan(temperature)) temperature = 0.0;
  if (isnan(humidity))    humidity    = 0.0;
}

void readLDR(int &lightLevel) {
  // Raw ADC value (board dependent range, typically 0-1023 on Uno).
  lightLevel = analogRead(LDR_PIN);
}
