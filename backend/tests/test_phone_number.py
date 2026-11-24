import pytest
from pydantic import ValidationError

from app.schemas.user import UserUpdate


@pytest.mark.parametrize("value, stored", [
    ("+447700900000", "+447700900000"),
    ("+44 7700 900000", "+447700900000"),
    ("+44-7700-900000", "+447700900000"),
    ("", ""),
    ("   ", ""),
    (None, None),
])
def test_valid_or_empty_numbers_are_accepted(value, stored):
    assert UserUpdate(phone_number=value).phone_number == stored


@pytest.mark.parametrize("value", ["07700900000", "447700900000", "+4477", "+4477009000001234", "+44abc7700900", "phone"])
def test_other_numbers_are_refused_with_the_format_shown(value):
    with pytest.raises(ValidationError) as error:
        UserUpdate(phone_number=value)
    assert "+447700900000" in str(error.value)


def test_profile_update_refuses_a_bad_number(client, auth_headers):
    res = client.patch("/api/v1/auth/me", json={"phone_number": "07700900000"}, headers=auth_headers)
    assert res.status_code == 422
    assert "+447700900000" in res.text


def test_profile_update_saves_a_good_number(client, auth_headers):
    # the number is where critical alert texts go, so changing it needs the password as an email change does
    res = client.patch("/api/v1/auth/me", json={"phone_number": "+447700900000", "current_password": "Admin1234!"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["phone_number"] == "+447700900000"


def test_profile_update_clears_the_number_with_an_empty_value(client, auth_headers):
    proof = {"current_password": "Admin1234!"}
    client.patch("/api/v1/auth/me", json={"phone_number": "+447700900000", **proof}, headers=auth_headers)
    res = client.patch("/api/v1/auth/me", json={"phone_number": "", **proof}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["phone_number"] == ""
