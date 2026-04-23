"""Run a fast end-to-end API smoke test without any physical hardware.

Prerequisite:
  - Start backend locally (for example: uvicorn app.main:app --reload)

Usage:
  - python scripts/quick_api_smoke.py
  - python scripts/quick_api_smoke.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import random
import time

import httpx


def _raise_for_status(response: httpx.Response, label: str) -> None:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{label} failed ({response.status_code}): {response.text}"
        )


def run(base_url: str) -> None:
    email = f"smoke_{int(time.time())}@phaemos.local"
    password = "SmokePass123!"

    try:
        with httpx.Client(base_url=base_url, timeout=15.0) as client:
            register_payload = {
                "name": "Smoke User",
                "email": email,
                "password": password,
            }
            register_res = client.post("/api/v1/auth/register", json=register_payload)
            _raise_for_status(register_res, "register")

            login_res = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
            _raise_for_status(login_res, "login")

            device_payload = {
                "name": "Smoke Device",
                "location": "Desk",
                "device_type": "esp32",
                "status": "online",
            }
            device_res = client.post("/api/v1/devices", json=device_payload)
            _raise_for_status(device_res, "register device")
            device = device_res.json()

            telemetry_payload = {
                "temperature": round(24.0 + random.uniform(-2.5, 2.5), 2),
                "humidity": round(52.0 + random.uniform(-8.0, 8.0), 2),
                "vibration_x": round(random.uniform(0.0, 0.8), 3),
                "vibration_y": round(random.uniform(0.0, 0.8), 3),
                "vibration_z": round(random.uniform(0.0, 0.8), 3),
                "light_level": round(260 + random.uniform(-70, 70), 2),
            }
            ingest_headers = {"x-api-key": device["api_key"]}
            ingest_res = client.post(
                "/api/v1/telemetry",
                json=telemetry_payload,
                headers=ingest_headers,
            )
            _raise_for_status(ingest_res, "ingest telemetry")

            latest_res = client.get(f"/api/v1/telemetry/{device['id']}/latest")
            _raise_for_status(latest_res, "latest telemetry")

            score_res = client.post("/api/v1/ml/score", json=telemetry_payload)
            _raise_for_status(score_res, "ml score")

            print("SMOKE TEST PASSED")
            print(f"- user: {email}")
            print(f"- device_id: {device['id']}")
            print(f"- latest_reading_id: {latest_res.json()['id']}")
            print(f"- ml_score: {score_res.json()}")
    except httpx.ConnectError as exc:
        raise SystemExit(
            "Could not reach backend. Start API first (for example: "
            "uvicorn app.main:app --reload from backend folder) and retry. "
            f"Details: {exc}"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run quick API smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    run(args.base_url.rstrip("/"))


if __name__ == "__main__":
    main()
