# ESP32 Comms Modules

Handles all network and inter-board communication for the primary gateway node.

| File pair | Purpose |
|---|---|
| wifi_manager.h / .cpp | Wi-Fi connection, reconnect logic, connection status |
| http_client.h / .cpp | POST telemetry payload to the backend API over HTTP |
| serial_parser.h / .cpp | UART receive and parse structured data from STM32 and Nano |

The HTTP client sends to `NEXT_PUBLIC_API_URL/api/v1/telemetry` with `X-API-Key` header.
The serial parser reads UART1 (Nano, GPIO16/17) and merges the data into the main telemetry payload before posting.
