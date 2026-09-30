import httpx

from phaemos_client.api import PhaemosClient


def make_client(handler, api_key="key-123"):
    client = PhaemosClient("http://phaemos.test", api_key=api_key)
    client._http = httpx.Client(
        base_url="http://phaemos.test", transport=httpx.MockTransport(handler), headers={"X-API-Key": api_key}
    )
    return client


def test_send_reading_posts_with_the_device_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("X-API-Key")
        return httpx.Response(201, json={"anomaly_score": 0.12, "is_anomaly": False})

    with make_client(handler) as client:
        stored = client.send_reading({"device_id": "d1", "temperature": 24.0})
    assert seen == {"path": "/api/v1/telemetry", "key": "key-123"}
    assert stored["is_anomaly"] is False


def test_errors_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid API key"})

    with make_client(handler) as client:
        try:
            client.send_reading({"device_id": "d1"})
        except httpx.HTTPStatusError as error:
            assert error.response.status_code == 401
        else:
            raise AssertionError("expected an HTTP error")
