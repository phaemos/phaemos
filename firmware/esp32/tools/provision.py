#!/usr/bin/env python3
"""Provision a PHAEMOS hub over its serial console.

usage: python3 tools/provision.py /dev/cu.usbserial-0001

It asks for the Wi-Fi network, the Wi-Fi password, the API address, the device id and the device
key. The password and the key are read without echo and are sent to the hub and nowhere else. Nothing
is written to a file or printed back. Needs pyserial (pip install pyserial) in your own
environment. A terminal program works as well: see "Provisioning a hub" in README.md.
"""
import getpass
import sys
import time


def reply_line(port) -> str:
    """The hub also prints its own log lines. Skip them and return the reply to our command."""
    for _ in range(40):
        text = port.read_until(b"\n").decode("ascii", errors="replace").strip()
        if text.startswith(("OK", "ERR", "SSID ")):
            return text
    return "no reply from the hub"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        import serial  # type: ignore
    except ImportError:
        print("pyserial is not installed. Use a terminal program instead (see README.md).")
        return 2

    ssid = input("Wi-Fi network name: ")
    password = getpass.getpass("Wi-Fi password (blank for an open network): ")
    url = input("API address (https://host/api/v1/telemetry, no slash at the end): ")
    if url.endswith("/"):
        print("The address must not end in a slash: the server answers 404 for it. Leave the slash off.")
        return 2
    device_id = input("Device id: ")
    key = getpass.getpass("Device key: ")

    with serial.Serial(sys.argv[1], 115200, timeout=2) as port:
        port.reset_input_buffer()
        for line in (f"SSID {ssid}", f"PASS {password}", f"URL {url}", f"ID {device_id}", f"KEY {key}", "SHOW"):
            port.write((line + "\n").encode("ascii", errors="strict"))
            time.sleep(0.2)
            # the hub's reply never repeats the password or the key
            print(reply_line(port))
        if input("Save these and restart the hub? [y/N] ").strip().lower() == "y":
            port.write(b"SAVE\n")
            time.sleep(0.2)
            print(reply_line(port))
        else:
            print("Not saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
