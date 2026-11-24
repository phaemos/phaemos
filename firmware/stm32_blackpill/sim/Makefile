# emulation test for the Black Pill node: builds the firmware, runs every scenario in Renode.
# see README.md.  needs PlatformIO, Renode (RENODE=/path/to/macos_run.command to override) and python 3.
RENODE ?= $(HOME)/Applications/Renode.app/Contents/MacOS/macos_run.command
FW     := ..
ELF    := $(FW)/.pio/build/blackpill_f411ce/firmware.elf

.PHONY: run firmware negative-control

run: firmware
	python3 run_sim.py --renode "$(RENODE)" --elf "$(ELF)" $(ARGS)

firmware:
	cd $(FW) && pio run

# builds deliberately broken copies of the firmware outside the repository (one or more for every scenario,
# and for the transmit and receive host test) and checks that the harness or the host test, fails each of them
negative-control: firmware
	python3 run_sim.py --renode "$(RENODE)" --negative-control $(ARGS)
