from typing import Any

import httpx

Reading = dict[str, Any]


class PhaemosClient:
    """Thin wrapper over the PHAEMOS HTTP API.

    Telemetry ingest authenticates with a device API key in the X-API-Key header.
    Account routes use the session cookie set by login.
    """

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 10.0) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)

    def status(self) -> dict[str, Any]:
        return self._json(self._http.get("/status"))

    def login(self, email: str, password: str) -> dict[str, Any]:
        return self._json(self._http.post("/api/v1/auth/login", json={"email": email, "password": password}))

    def create_device(self, name: str, location: str, device_type: str) -> dict[str, Any]:
        body = {"name": name, "location": location, "device_type": device_type, "status": "online"}
        return self._json(self._http.post("/api/v1/devices", json=body))

    def send_reading(self, reading: Reading) -> dict[str, Any]:
        return self._json(self._http.post("/api/v1/telemetry", json=reading))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PhaemosClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data
