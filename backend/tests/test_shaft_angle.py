"""
The bucketed shaft angle: always 0 up to but not including 360 and null when the angles in a bucket do not agree.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.telemetry import Telemetry


def _bucket(client, db, device, auth_headers, angles):
    # a fixed spot inside one hour bucket, so the rows can never straddle a bucket edge
    now = datetime.now(timezone.utc)
    base = now.replace(minute=10, second=0, microsecond=0) - timedelta(hours=2)
    for i, angle in enumerate(angles):
        db.add(Telemetry(device_id=device.id, shaft_angle=angle, shaft_rpm=60.0, recorded_at=base + timedelta(seconds=i)))
    db.flush()
    start = (base - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (base + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = client.get(f"/api/v1/telemetry/{device.id}?bucket=3600&from_ts={start}&to_ts={end}", headers=auth_headers)
    assert res.status_code == 200, res.text
    (row,) = res.json()
    return row["shaft_angle"]


def test_a_steady_shaft_gives_its_angle(client, db, device, auth_headers):
    assert _bucket(client, db, device, auth_headers, [44.0, 45.0, 46.0]) == pytest.approx(45.0, abs=0.01)


def test_angles_either_side_of_north_average_to_zero_and_never_to_360(client, db, device, auth_headers):
    # 350 and 10 average to 0. A mean that is a hair below zero used to be moved up to exactly 360.0
    value = _bucket(client, db, device, auth_headers, [350.0, 10.0])
    assert 0.0 <= value < 360.0
    assert min(value, 360.0 - value) < 1e-6


@pytest.mark.parametrize("angles", [[359.99999999999994], [0.0, 0.0], [359.9999999, 0.0000001], [180.0, 180.0]])
def test_the_angle_is_always_below_360(client, db, device, auth_headers, angles):
    value = _bucket(client, db, device, auth_headers, angles)
    assert 0.0 <= value < 360.0


def test_a_turning_shaft_has_no_mean_angle(client, db, device, auth_headers):
    # angles spread all round the circle: the mean vector is nearly zero, so the mean angle is noise
    assert _bucket(client, db, device, auth_headers, [0.0, 90.0, 180.0, 270.0]) is None


def test_a_bucket_with_loosely_agreeing_angles_still_has_one(client, db, device, auth_headers):
    # mean vector length about 0.7: a wobble, not a spin
    value = _bucket(client, db, device, auth_headers, [0.0, 90.0])
    assert value == pytest.approx(45.0, abs=0.01)
