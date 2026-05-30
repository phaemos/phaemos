# firmware/pico_w/bme280.py
# Full MicroPython BME280 driver - no external library required.
#
# I include the full compensation math here rather than returning raw ADC
# values because the Pico does not have the precision integer math limitations
# of an 8-bit AVR.  The RP2040 handles 32-bit and 64-bit integer arithmetic
# natively, so the Bosch-specified compensation formulas run correctly without
# the workarounds needed on Arduino.
#
# Compensation formulas are taken directly from the BME280 datasheet
# (BST-BME280-DS002, Section 4.2.3 "Compensation formulas in double precision
# floating point").  I use the integer variant (Section 4.2.3, code listing 1)
# for temperature and pressure to match the datasheet reference implementation,
# then convert to practical units at the end.
#
# Output units:
#   temperature : int, units of 0.01 degC  (divide by 100 for Celsius)
#   pressure    : int, units of 1/256 Pa   (divide by 256 for Pa, /25600 for hPa)
#   humidity    : int, units of 1/1024 %RH (divide by 1024 for %RH)


class BME280:
    """BME280 temperature, pressure, and humidity sensor driver."""

    # Register addresses from BME280 datasheet Table 18 / Table 19
    _REG_CALIB_T_P  = 0x88   # Start of temperature and pressure calibration data (24 bytes)
    _REG_ID         = 0xD0   # Chip ID register - should read 0x60 for BME280
    _REG_RESET      = 0xE0
    _REG_CALIB_H1   = 0xA1   # dig_H1 (1 byte)
    _REG_CTRL_HUM   = 0xF2
    _REG_STATUS     = 0xF3
    _REG_CTRL_MEAS  = 0xF4
    _REG_CONFIG     = 0xF5
    _REG_PRESS_MSB  = 0xF7   # Start of measurement data block (8 bytes)
    _REG_CALIB_H2   = 0xE1   # Start of dig_H2..dig_H6 (7 bytes)

    def __init__(self, i2c, addr=0x76):
        """Initialise BME280 and read all calibration registers.

        I read calibration on __init__ rather than on each measurement call
        because calibration registers are one-time programmed in the sensor
        factory and never change - reading them once at startup avoids 24+
        extra I2C bytes per measurement at 5-second intervals.

        Args:
            i2c:  machine.I2C instance (already initialised with correct pins)
            addr: BME280 I2C address, either 0x76 (SDO=GND) or 0x77 (SDO=VCC)
        """
        self._i2c = i2c
        self._addr = addr

        # Verify chip identity before attempting calibration reads.
        # I check the chip ID so a wiring error produces a clear error message
        # instead of silently reading garbage calibration data.
        chip_id = self._read_byte(self._REG_ID)
        if chip_id not in (0x60, 0x58):
            # 0x60 = BME280, 0x58 = BMP280 (no humidity but compatible otherwise)
            raise RuntimeError(
                "BME280 not found at 0x{:02X} (chip ID=0x{:02X})".format(
                    addr, chip_id
                )
            )

        self._read_calibration()
        self._configure()

    def _read_byte(self, reg):
        """Read one byte from register reg."""
        return self._i2c.readfrom_mem(self._addr, reg, 1)[0]

    def _read_bytes(self, reg, count):
        """Read count bytes starting from register reg."""
        return self._i2c.readfrom_mem(self._addr, reg, count)

    def _write_byte(self, reg, value):
        """Write one byte to register reg."""
        self._i2c.writeto_mem(self._addr, reg, bytes([value]))

    def _read_calibration(self):
        """Read all factory calibration coefficients from the sensor.

        I store them as instance attributes with the same names as the
        datasheet (dig_T1, dig_P1, etc.) so the compensation formulas
        in read_compensated_data() can be verified against the datasheet
        line-by-line.
        """
        raw = self._read_bytes(self._REG_CALIB_T_P, 24)

        # Temperature calibration: dig_T1 (unsigned), dig_T2, dig_T3 (signed)
        self.dig_T1 = (raw[1] << 8) | raw[0]           # uint16
        self.dig_T2 = self._signed16((raw[3] << 8) | raw[2])
        self.dig_T3 = self._signed16((raw[5] << 8) | raw[4])

        # Pressure calibration: dig_P1 (unsigned), dig_P2..dig_P9 (signed)
        self.dig_P1 = (raw[7]  << 8) | raw[6]          # uint16
        self.dig_P2 = self._signed16((raw[9]  << 8) | raw[8])
        self.dig_P3 = self._signed16((raw[11] << 8) | raw[10])
        self.dig_P4 = self._signed16((raw[13] << 8) | raw[12])
        self.dig_P5 = self._signed16((raw[15] << 8) | raw[14])
        self.dig_P6 = self._signed16((raw[17] << 8) | raw[16])
        self.dig_P7 = self._signed16((raw[19] << 8) | raw[18])
        self.dig_P8 = self._signed16((raw[21] << 8) | raw[20])
        self.dig_P9 = self._signed16((raw[23] << 8) | raw[22])

        # Humidity calibration (split across two non-contiguous register banks)
        self.dig_H1 = self._read_byte(self._REG_CALIB_H1)   # uint8

        raw_h = self._read_bytes(self._REG_CALIB_H2, 7)
        self.dig_H2 = self._signed16((raw_h[1] << 8) | raw_h[0])
        self.dig_H3 = raw_h[2]                               # uint8
        # dig_H4 and dig_H5 share a nibble in raw_h[3] - this split is
        # specified in the BME280 datasheet Table 17.
        self.dig_H4 = self._signed16((raw_h[3] << 4) | (raw_h[4] & 0x0F))
        self.dig_H5 = self._signed16((raw_h[5] << 4) | (raw_h[4] >> 4))
        self.dig_H6 = self._signed8(raw_h[6])

    def _configure(self):
        """Put the sensor into normal mode with 1x oversampling.

        I use 1x oversampling on all three measurements because the Pico
        node posts every 5 seconds and sensor noise averaging is not critical
        for the ambient monitoring use case.  Higher oversampling would
        increase current draw without benefit at this reporting rate.
        """
        # I2C mode (no SPI) is selected by the sensor's CSB pin wiring.
        # Set humidity oversampling to 1x before ctrl_meas (datasheet requirement).
        self._write_byte(self._REG_CTRL_HUM, 0x01)   # osrs_h = 1x
        # Normal mode, temperature 1x, pressure 1x
        self._write_byte(self._REG_CTRL_MEAS, 0x27)  # osrs_t=1, osrs_p=1, mode=normal
        # Standby 1000ms, filter off, SPI 3-wire off
        self._write_byte(self._REG_CONFIG, 0xA0)

    @staticmethod
    def _signed16(val):
        """Convert unsigned 16-bit int to signed."""
        return val if val < 32768 else val - 65536

    @staticmethod
    def _signed8(val):
        """Convert unsigned 8-bit int to signed."""
        return val if val < 128 else val - 256

    def read_compensated_data(self):
        """Read raw ADC values and apply datasheet compensation formulas.

        Returns:
            Tuple (temperature, pressure, humidity) as integers:
              temperature : units of 0.01 degC  - divide by 100.0 for Celsius
              pressure    : units of 1/256 Pa   - divide by 25600.0 for hPa
              humidity    : units of 1/1024 %RH - divide by 1024.0 for %RH
        """
        # Read all 8 measurement bytes in one I2C transaction to ensure
        # all three values are from the same sensor measurement snapshot.
        raw = self._read_bytes(self._REG_PRESS_MSB, 8)

        # Unpack 20-bit ADC values (MSB, LSB, XLSB format)
        adc_P = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
        adc_T = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
        adc_H = (raw[6] << 8)  |  raw[7]

        # ---- Temperature compensation (datasheet 4.2.3, listing 1) ----
        # var1 and var2 use a "t_fine" intermediate value that is also reused
        # by the pressure compensation - I store it as self._t_fine.
        var1 = (adc_T / 16384.0 - self.dig_T1 / 1024.0) * self.dig_T2
        var2 = (adc_T / 131072.0 - self.dig_T1 / 8192.0) ** 2 * self.dig_T3
        self._t_fine = int(var1 + var2)
        temperature = int((var1 + var2) / 5120.0 * 100)   # units: 0.01 degC

        # ---- Pressure compensation (datasheet 4.2.3, listing 1) ----
        var1 = self._t_fine / 2.0 - 64000.0
        var2 = var1 * var1 * self.dig_P6 / 32768.0
        var2 = var2 + var1 * self.dig_P5 * 2.0
        var2 = var2 / 4.0 + self.dig_P4 * 65536.0
        var1 = (self.dig_P3 * var1 * var1 / 524288.0 + self.dig_P2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.dig_P1

        if var1 == 0.0:
            # I guard against division by zero here exactly as the Bosch
            # reference implementation does - if var1 is 0 the pressure
            # formula would produce infinity or a crash.
            pressure = 0
        else:
            p = 1048576.0 - adc_P
            p = ((p - var2 / 4096.0) * 6250.0) / var1
            var1 = self.dig_P9 * p * p / 2147483648.0
            var2 = p * self.dig_P8 / 32768.0
            p = p + (var1 + var2 + self.dig_P7) / 16.0
            pressure = int(p * 256)   # units: 1/256 Pa

        # ---- Humidity compensation (datasheet 4.2.3, listing 1) ----
        h = self._t_fine - 76800.0
        h = ((adc_H - (self.dig_H4 * 64.0 + self.dig_H5 / 16384.0 * h)) *
             (self.dig_H2 / 65536.0 *
              (1.0 + self.dig_H6 / 67108864.0 * h *
               (1.0 + self.dig_H3 / 67108864.0 * h))))
        h = h * (1.0 - self.dig_H1 * h / 524288.0)
        h = max(0.0, min(h, 100.0))   # clamp to valid %RH range
        humidity = int(h * 1024)      # units: 1/1024 %RH

        return temperature, pressure, humidity
