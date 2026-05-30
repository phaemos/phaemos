// I include Arduino.h to get String and the F() macro on a .cpp file - the
// Arduino IDE only injects it automatically in .ino files.
#include <Arduino.h>

#include "serial_parser.h"

// ---------------------------------------------------------------------------
// Helper: extract the numeric value after a label like "TEMP:" in a CSV line.
// I implement this as a static file-scope function to keep both parse functions
// DRY - the same pattern repeats for every field.
// I return NAN on failure so the caller can check isnan() rather than receiving
// a silent 0.0 that looks like a valid reading.
// ---------------------------------------------------------------------------
static float extractField(const String& line, const char* label) {
    int idx = line.indexOf(label);
    if (idx < 0) return NAN;

    int start = idx + strlen(label);
    // I find the next comma or end-of-string to delimit the value substring.
    int end = line.indexOf(',', start);
    if (end < 0) end = line.length();

    String token = line.substring(start, end);
    token.trim();
    return token.toFloat();
}

// ---------------------------------------------------------------------------
// parseNanoSerial
// Expected format (one line, newline-terminated):
// "TEMP:28.5,HUM:55.2,PRES:1013.2,LIGHT:340,MOIST:210,WATER:0"
// ---------------------------------------------------------------------------
void parseNanoSerial(const String& line, NanoData* d) {
    // I zero the struct through the valid flag first so partial failures leave
    // a clearly invalid struct rather than half-filled garbage.
    d->valid = false;

    if (line.length() == 0) return;

    float temp  = extractField(line, "TEMP:");
    float hum   = extractField(line, "HUM:");
    float pres  = extractField(line, "PRES:");
    float light = extractField(line, "LIGHT:");
    float moist = extractField(line, "MOIST:");
    float water = extractField(line, "WATER:");

    // I treat any NAN as a parse failure and reject the whole line so the
    // caller never ingests a partially valid reading.
    if (isnan(temp) || isnan(hum) || isnan(pres) ||
        isnan(light) || isnan(moist) || isnan(water)) {
        return;
    }

    d->temperature   = temp;
    d->humidity      = hum;
    d->pressure      = pres;
    d->light_level   = light;
    d->moisture      = moist;
    // I cast water to int before comparing to 0 because toFloat() on "0" gives
    // 0.0, but a future "0.5" would also pass a raw float comparison to 0.
    d->water_detected = ((int)water != 0);
    d->valid          = true;
}

// ---------------------------------------------------------------------------
// parseSTM32Serial
// Expected format (one line, newline-terminated):
// "VIB:x,y,z,MAG:m,FFT_PEAK:hHz"
// where h is a float followed by the literal character 'H'.
// ---------------------------------------------------------------------------
void parseSTM32Serial(const String& line, STM32Data* d) {
    d->valid = false;

    if (line.length() == 0) return;

    float mag = extractField(line, "MAG:");
    if (isnan(mag)) return;

    // I handle FFT_PEAK separately because its value is suffixed with "Hz"
    // which extractField (using toFloat) will stop at automatically.
    float fftPeak = extractField(line, "FFT_PEAK:");
    if (isnan(fftPeak)) return;

    d->vib_magnitude = mag;
    d->fft_peak_hz   = fftPeak;
    d->valid         = true;
}
