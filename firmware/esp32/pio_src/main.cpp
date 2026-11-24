// main.cpp - build entry point for PlatformIO.
// the Arduino sketch files stay where they are and are pulled into one
// translation unit here. ota.ino goes first so its function is defined before
// esp32.ino calls it.
#include <Arduino.h>

#include "../ota.ino"
#include "../esp32.ino"
