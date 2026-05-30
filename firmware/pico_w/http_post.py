# firmware/pico_w/http_post.py
# HTTP POST helper for telemetry upload from the Pico 2W ambient node.

import json

try:
    import urequests as requests
except ImportError:
    # I keep this fallback so the module can be imported in a CPython test
    # environment (e.g. unit tests on a dev machine) without crashing.
    import requests


def post_telemetry(url, payload_dict, api_key):
    """POST a JSON telemetry payload to the given URL.

    I catch all exceptions and return -1 rather than crashing the main loop
    because network errors are transient on a Pico - a dropped Wi-Fi packet,
    a temporary server restart, or a DNS hiccup should not halt sensor
    collection.  The caller can decide to log the failure or retry.

    Args:
        url:          Full URL string including scheme and path
                      e.g. "http://192.168.1.10:8000/api/v1/telemetry"
        payload_dict: Python dict - will be JSON-encoded before sending
        api_key:      API key string sent as X-API-Key header

    Returns:
        HTTP status code as int (e.g. 200, 201, 400, 500) on success.
        -1 on any exception (network error, timeout, encoding failure).
    """
    try:
        body = json.dumps(payload_dict)

        # I set Content-Type explicitly to application/json because urequests
        # does not infer the content type from the body automatically - without
        # this header some server frameworks reject the request with 415.
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        }

        response = requests.post(url, data=body, headers=headers)
        status = response.status_code

        # I close the response immediately after reading the status code to
        # release the socket back to the MicroPython network stack.  Leaving
        # sockets open causes "OSError: [Errno 12] ENOMEM" after a few
        # iterations on the Pico's constrained socket pool.
        response.close()

        return status

    except Exception as e:
        # I print the exception here so it appears in Thonny's output pane
        # during debugging, but the function still returns -1 so the main
        # loop can continue collecting sensor data.
        print("http_post error:", e)
        return -1
