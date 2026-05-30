# firmware/pico_w/ssd1306.py
# MicroPython SSD1306 OLED driver for I2C.
#
# I write my own minimal driver rather than relying on the MicroPython
# standard library's ssd1306.py because not all MicroPython builds for the
# Pico 2W include it in the frozen modules, and keeping dependencies local
# means the firmware is self-contained and does not require an internet
# connection on the Pico to install packages via upip.

import framebuf


class SSD1306_I2C:
    """SSD1306 128x64 (or 128x32) OLED display over I2C."""

    # SSD1306 command bytes used in the init sequence.
    # I define them as class constants rather than inline magic numbers so the
    # init sequence below reads like the datasheet command names.
    _CMD_DISPLAY_OFF        = 0xAE
    _CMD_DISPLAY_ON         = 0xAF
    _CMD_SET_CONTRAST       = 0x81
    _CMD_ENTIRE_DISPLAY_RAM = 0xA4   # Output follows RAM content
    _CMD_NORMAL_DISPLAY     = 0xA6   # Non-inverted
    _CMD_MEM_ADDR_MODE      = 0x20
    _CMD_ADDR_MODE_HORIZ    = 0x00   # Horizontal addressing - row auto-increments
    _CMD_SET_COL_ADDR       = 0x21
    _CMD_SET_PAGE_ADDR      = 0x22
    _CMD_SET_DISP_START_LINE= 0x40
    _CMD_SET_SEG_REMAP      = 0xA1   # Column address 127 mapped to SEG0
    _CMD_SET_MUX_RATIO      = 0xA8
    _CMD_SET_COM_SCAN_DIR   = 0xC8   # COM scan from N-1 to 0 (vertical flip)
    _CMD_SET_DISP_OFFSET    = 0xD3
    _CMD_SET_COM_PINS       = 0xDA
    _CMD_SET_DISP_CLK_DIV   = 0xD5
    _CMD_SET_PRECHARGE      = 0xD9
    _CMD_SET_VCOM_DESEL     = 0xDB
    _CMD_CHARGE_PUMP        = 0x8D
    _CHARGE_PUMP_ON         = 0x14

    def __init__(self, width, height, i2c, addr=0x3C):
        """Initialise display, allocate framebuffer, send init sequence.

        Args:
            width:  Display width in pixels (typically 128)
            height: Display height in pixels (typically 64 or 32)
            i2c:    machine.I2C instance
            addr:   I2C address (0x3C when SA0=GND, 0x3D when SA0=VCC)
        """
        self.width  = width
        self.height = height
        self._i2c   = i2c
        self._addr  = addr

        # I allocate the framebuffer as a bytearray of width * height / 8
        # bytes because the SSD1306 uses 1 bit per pixel packed into bytes.
        # framebuf.MONO_VLSB means column 0 row 0 is bit 0 of byte 0, which
        # matches the SSD1306's native memory layout in horizontal address mode.
        self._buffer = bytearray(width * height // 8)
        self._fb = framebuf.FrameBuffer(self._buffer, width, height,
                                        framebuf.MONO_VLSB)

        self._init_display()

    def _cmd(self, *commands):
        """Send one or more command bytes to the display.

        The SSD1306 I2C protocol uses a control byte (0x00) before each
        command byte.  I send them as a single I2C write to minimise the
        number of I2C transactions.
        """
        for c in commands:
            self._i2c.writeto(self._addr, bytes([0x00, c]))

    def _init_display(self):
        """Send the SSD1306 initialisation sequence.

        I follow the initialisation sequence from the SSD1306 datasheet
        Application Note and the Adafruit SSD1306 library, which has been
        validated across many displays.  The sequence is:
          1. Turn display off
          2. Set clock, mux, offset, start line
          3. Set segment remap and COM scan direction (for correct orientation)
          4. Set COM pins layout for 128x64 vs 128x32
          5. Set contrast, pre-charge, VCOM
          6. Enable internal charge pump (required for 3.3V operation)
          7. Clear RAM, enable normal display, turn display on
        """
        mux = self.height - 1
        com_pins = 0x12 if self.height == 64 else 0x02

        self._cmd(self._CMD_DISPLAY_OFF)
        self._cmd(self._CMD_SET_DISP_CLK_DIV, 0x80)
        self._cmd(self._CMD_SET_MUX_RATIO, mux)
        self._cmd(self._CMD_SET_DISP_OFFSET, 0x00)
        self._cmd(self._CMD_SET_DISP_START_LINE | 0x00)
        self._cmd(self._CMD_CHARGE_PUMP, self._CHARGE_PUMP_ON)  # Enable internal VCHP
        self._cmd(self._CMD_MEM_ADDR_MODE, self._CMD_ADDR_MODE_HORIZ)
        self._cmd(self._CMD_SET_SEG_REMAP)
        self._cmd(self._CMD_SET_COM_SCAN_DIR)
        self._cmd(self._CMD_SET_COM_PINS, com_pins)
        self._cmd(self._CMD_SET_CONTRAST, 0xCF)
        self._cmd(self._CMD_SET_PRECHARGE, 0xF1)
        self._cmd(self._CMD_SET_VCOM_DESEL, 0x40)
        self._cmd(self._CMD_ENTIRE_DISPLAY_RAM)
        self._cmd(self._CMD_NORMAL_DISPLAY)
        self.fill(0)
        self.show()
        self._cmd(self._CMD_DISPLAY_ON)

    def fill(self, color):
        """Fill the entire framebuffer with color (0=black, 1=white)."""
        self._fb.fill(color)

    def text(self, string, x, y, color=1):
        """Draw a text string at (x, y) using the 8x8 built-in font.

        I delegate to framebuf.text() which uses the MicroPython built-in
        8x8 monospaced font - no external font data required.
        """
        self._fb.text(string, x, y, color)

    def pixel(self, x, y, color):
        """Set or clear a single pixel at (x, y)."""
        self._fb.pixel(x, y, color)

    def show(self):
        """Transfer the framebuffer to the display over I2C.

        I send the framebuffer in 16-byte chunks rather than one large
        transfer because some I2C implementations (including certain
        MicroPython builds and I2C peripheral drivers) have a 32-byte
        buffer limit.  16 bytes + 1 control byte = 17 bytes per write,
        safely within that limit.

        The write format is: [0x40, data0, data1, ..., data15]
        where 0x40 is the SSD1306 "data follows" control byte.
        """
        # Set column and page address windows to the full display size so
        # the display's internal pointer auto-increments correctly across
        # all 8 pages (for 64px height).
        self._cmd(self._CMD_SET_COL_ADDR, 0, self.width - 1)
        self._cmd(self._CMD_SET_PAGE_ADDR, 0, self.height // 8 - 1)

        chunk_size = 16
        buf_len = len(self._buffer)
        offset = 0

        while offset < buf_len:
            chunk = self._buffer[offset:offset + chunk_size]
            # Prepend the 0x40 data control byte to each chunk.
            self._i2c.writeto(self._addr, bytes([0x40]) + chunk)
            offset += chunk_size
