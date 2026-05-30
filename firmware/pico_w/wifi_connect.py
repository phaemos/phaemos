# firmware/pico_w/wifi_connect.py
# Wi-Fi connection helper for the Pico 2W ambient node.

import network
import time


def connect_wifi(ssid, password, timeout_s=30):
    """Connect to a Wi-Fi network and return the WLAN interface.

    I raise on timeout rather than returning False so the caller does not
    silently skip posting - a missing network connection means all telemetry
    would be lost, so it is better to surface the failure loudly and let
    main.py decide whether to retry or halt.

    Args:
        ssid:      Wi-Fi network name (string)
        password:  Wi-Fi password (string)
        timeout_s: Maximum seconds to wait for connection (default 30)

    Returns:
        The active network.WLAN object on success.

    Raises:
        RuntimeError: If the connection is not established within timeout_s.
    """
    # I use STA_IF (station mode) because the Pico is a client connecting to
    # an existing access point, not hosting its own network.
    wlan = network.WLAN(network.STA_IF)

    # I activate the interface before calling connect() because on cold boot
    # the interface is inactive by default and connect() will silently do
    # nothing without an explicit activate().
    wlan.active(True)

    # Disconnect first if already connected to a different network from a
    # previous session that did not cleanly shut down.
    if wlan.isconnected():
        wlan.disconnect()
        time.sleep(0.5)

    wlan.connect(ssid, password)

    # I poll every 0.5 seconds rather than using a blocking wait so the loop
    # can be interrupted cleanly and gives a visible timeout counter on the
    # REPL for debugging during bring-up.
    elapsed = 0.0
    while not wlan.isconnected():
        time.sleep(0.5)
        elapsed += 0.5
        if elapsed >= timeout_s:
            wlan.active(False)
            raise RuntimeError(
                "Wi-Fi connection timeout after {}s - SSID: {}".format(
                    timeout_s, ssid
                )
            )

    ip = wlan.ifconfig()[0]
    print("Wi-Fi connected. IP:", ip)
    return wlan
