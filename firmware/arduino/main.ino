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
  // Open serial so ESP32 (or Serial Monitor) can read outgoing sensor lines.
  Serial.begin(9600);
  // Initialize attached sensors once during boot.
  initSensors();
}

void loop() {
  // Local variables hold one sampled frame before printing.
  float temp, hum;
  int light;

  // Read sensor values by reference.
  readDHT(temp, hum);
  readLDR(light);

  // Emit one CSV-like line per sample for easy parser logic on ESP32.
  Serial.print("TEMP:");
  Serial.print(temp);
  Serial.print(",HUM:");
  Serial.print(hum);
  Serial.print(",LIGHT:");
  Serial.println(light);

  // Match backend ingest cadence and avoid flooding serial output.
  delay(5000);
}
