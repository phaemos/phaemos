// ============================================================
// PHAEMOS - Arduino Uno Firmware
// Reads DHT22 and LDR, outputs formatted serial strings
// to be parsed by the ESP32 Wi-Fi gateway.
//
// Serial format (one line per reading):
//   TEMP:23.4,HUM:61.2,LIGHT:512
// ============================================================

#include "sensors.h"

void setup() {
  Serial.begin(9600);
  initSensors();
}

void loop() {
  float temp, hum;
  int light;

  readDHT(temp, hum);
  readLDR(light);

  Serial.print("TEMP:");
  Serial.print(temp);
  Serial.print(",HUM:");
  Serial.print(hum);
  Serial.print(",LIGHT:");
  Serial.println(light);

  delay(5000);
}
