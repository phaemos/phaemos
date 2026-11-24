# ESP32 Comms Modules

Handles all network and inter-board communication for the primary gateway node.

| File pair | Purpose |
|---|---|
| wifi_manager.h / .cpp | Wi-Fi connection, reconnect logic, connection status |
| tls_checks.h / .cpp | The checks the hub makes itself after a TLS handshake, because the core's mbedTLS is built without them: the dates of every certificate the server presented and TLS 1.2 only. No Arduino types, so `test_host/test_tls.cpp` covers it |
| cred_record.h / .cpp | The five credentials as one checksummed record, so storing them is atomic. No Arduino types, so `test_host/test_provision.cpp` covers every cut point |
| trust_roots.h | The two pinned root certificates (ISRG Root X1 and X2) a TLS post is verified against. Placeholders until the owner pastes them. A release build fails to compile while they are |
| post_rules.h / .cpp | The pure rules around a post: the clock gate for TLS, what each response code means for the next attempt (Retry-After, a rejected key) and the boot and sequence numbers that never repeat. No Arduino types, so `test_host/test_rules.cpp` covers it |
| provision.h / .cpp | The serial provisioning line protocol and the checks on every value. No Arduino types, so `test_host/test_provision.cpp` covers it |
| credentials.h / .cpp | Where the Wi-Fi password, key, address and device id live at run time: the hub's own flash or the untracked `secrets.h` for a bench build |
| http_client.h / .cpp | The hub's own small HTTP client. It posts the telemetry payload over TLS to an `https://` address (verified against the pinned roots, never `setInsecure()`, with the certificate dates and TLS version checked by the hub after the handshake) and over plain HTTP only with the bench flag, inside one wall-clock budget (`POST_WALL_CLOCK_MS`) and reads only the final status line (a 1xx is skipped and a leading blank line is ignored). It follows no redirects and does no TLS. It sends a `User-Agent`, refuses a control character in the address and keeps a resolved address for `DNS_CACHE_MS`, dropping it when a connect fails |
| http_parse.h / .cpp | The pure parts of that client: the address, the request header, the status line reader and the budget arithmetic. No Arduino types, so `test_host/test_http.cpp` covers them |
| post_task.h / .cpp | The post task on core 0: the Wi-Fi connect, reconnects, the OTA check and every post. It takes the newest body from a one-slot mailbox, so the main loop never waits on the network |
| post_queue.h / .cpp | The pure parts of the post task: the mailbox, the back-off, the post schedule gate, the time since a post succeeded and the watch the main loop keeps on the task. No Arduino or FreeRTOS types, so `test_host/test_post.cpp` covers them |
| telemetry_body.h / .cpp | Builds the JSON body from plain values. The firmware and the host tests call the same function |
| link_protocol.h / .cpp | The serial link format: CRC, line assembly, both satellite parsers, counters, sequence and restart logic, status bits, pings and link states. No Arduino types, so `test_host/test_link.cpp` covers it |
| serial_parser.h / .cpp | A thin Arduino caller that moves bytes from a UART into `link_protocol` and sends the ping |

The serial buffers are 2,048 bytes each (`UART_RX_BUFFER_BYTES`).
The HTTP client sends to the stored API address (the backend's `/api/v1/telemetry` endpoint, from the hub's flash or from `secrets.h`) with an `X-API-Key` header. The TLS handshake is inside the same wall-clock budget. The whole post has to finish inside `POST_WALL_CLOCK_MS`. The connect step gives up after `HTTP_CONNECT_TIMEOUT_MS`.
The serial parser reads UART1 (Nano, GPIO16/17) and UART2 (STM32, GPIO18/19). The body builder merges the data into the telemetry payload. On the revised board the two receive pins (GPIO16 and GPIO18) have 100 kohm pull-downs, so the revised image turns the serial driver's internal pull-up off again with `gpio_pullup_dis()`. The present board has none. A link is reported as `line_low`, `garbage`, `silent`, `one_way`, `intermittent` or ok, as described in the main README. The hub sends `PING:<n>` on GPIO17 and GPIO19 every 30 s and expects a checksummed pong. A link switched off by `HAS_NANO` or `HAS_STM32` in `config.h` is never started or watched.
The telemetry post carries `seq`, `boot`, `up`, `faults`, `links`, `diag`, `reset_reason`, `rssi`, `heap_free` and `fw` as well as the readings. It adds `board_mismatch`, `board_check`, `reset_loop`, `setup_excluded` and `not_fitted` when they apply. The backend schema keeps neither `diag` nor `board_mismatch` today. See the main README for what each means.
