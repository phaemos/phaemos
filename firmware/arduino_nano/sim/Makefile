# builds both firmware images with PlatformIO then the simulator harness and runs it.
# build outputs go under build/, which the repository .gitignore already covers.
SIMAVR  ?= /opt/homebrew
FW_DIR  := ../nano_node
ELF     := $(FW_DIR)/.pio/build/nanoatmega328/firmware.elf
ELF_WDT := $(FW_DIR)/.pio/build/nanoatmega328new_wdt/firmware.elf
ELF_CAL := $(FW_DIR)/.pio/build/nanoatmega328new_cal/firmware.elf
# the bootloader images the emulation starts the chip in, from the pinned Arduino core
CORE    ?= $(HOME)/.platformio/packages/framework-arduino-avr
HEX_NEW := $(CORE)/bootloaders/optiboot/optiboot_atmega328.hex
HEX_OLD := $(CORE)/bootloaders/atmega/ATmegaBOOT_168_atmega328.hex
CC      ?= cc
CFLAGS  ?= -O3 -std=gnu11 -Wall -Wextra -I$(SIMAVR)/include/simavr -I$(SIMAVR)/include/simavr/avr
LDLIBS  := $(SIMAVR)/lib/libsimavr.a -lm

.PHONY: all run firmware clean
all: build/sim_nano

run: firmware build/sim_nano
	cd build && ./sim_nano --elf ../$(ELF) --elf-wdt ../$(ELF_WDT) --elf-cal ../$(ELF_CAL) \
		--hex-new $(HEX_NEW) --hex-old $(HEX_OLD) $(ARGS)

# both images are rebuilt on every run so the test always sees the current source: the default build
# the one with the watchdog flag on and the one with BANDGAP_CALIBRATED on.
firmware:
	cd $(FW_DIR) && pio run -e nanoatmega328 -e nanoatmega328new_wdt -e nanoatmega328new_cal

build/sim_nano: sim_nano.c bme280_sim.c bme280_sim.h ../nano_node/linkframe.h
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ sim_nano.c bme280_sim.c $(LDLIBS)

clean:
	rm -rf build
