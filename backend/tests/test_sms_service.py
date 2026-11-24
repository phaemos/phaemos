import json
import logging

import httpx
import pytest

from app.config import settings
from app.services import sms_service

URL = "https://api.brevo.com/v3/transactionalSMS/send"


@pytest.fixture
def brevo(monkeypatch):
    # backs the HTTP client with a mock transport, so no test reaches the network.
    calls = []
    behaviour = {"handler": lambda request: httpx.Response(201, json={"messageId": 1})}
    real_client = httpx.Client

    def handler(request):
        calls.append(request)
        return behaviour["handler"](request)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(sms_service.httpx, "Client", factory)
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    monkeypatch.setattr(settings, "brevo_sms_sender", "PHAEMOS")
    sms_service._sender_is_valid.cache_clear()
    yield behaviour, calls
    sms_service._sender_is_valid.cache_clear()


def test_request_shape(brevo):
    _, calls = brevo
    assert sms_service.send_sms("+447700900000", "hello") is True
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.headers["api-key"] == "test-brevo-key"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "sender": "PHAEMOS",
        "recipient": "447700900000",
        "content": "hello",
        "type": "transactional",
    }


@pytest.mark.parametrize("number", [
    "447700900000", "+44 7700 900000", "+4477", "+4477009000001234", "07700900000", "+44770090000a", "", "+",
])
def test_invalid_number_is_refused_without_a_call(brevo, number):
    _, calls = brevo
    assert sms_service.send_sms(number, "hello") is False
    assert calls == []


@pytest.mark.parametrize("number", ["+12345678", "+123456789012345"])
def test_number_length_limits_are_accepted(brevo, number):
    _, calls = brevo
    assert sms_service.send_sms(number, "hello") is True
    assert len(calls) == 1


@pytest.mark.parametrize("key", ["", "placeholder"])
def test_unconfigured_makes_no_call(brevo, monkeypatch, key):
    _, calls = brevo
    monkeypatch.setattr(settings, "brevo_api_key", key)
    assert sms_service.send_sms("+447700900000", "hello") is False
    assert calls == []


@pytest.mark.parametrize("sender", ["", "TOOLONGSENDER1", "MY SENDER", "PHAEMOS!", "Caf\u00e9", "1234567890123456", "12345678901A"])
def test_invalid_sender_is_refused_and_logged_once(brevo, monkeypatch, caplog, sender):
    _, calls = brevo
    monkeypatch.setattr(settings, "brevo_sms_sender", sender)
    with caplog.at_level(logging.ERROR):
        assert sms_service.send_sms("+447700900000", "hello") is False
        assert sms_service.send_sms("+447700900000", "hello") is False
    assert calls == []
    assert caplog.text.count("BREVO_SMS_SENDER") == 1


@pytest.mark.parametrize("sender", ["ABCDEFGHIJK", "447700900000", "123456789012345", "A"])
def test_eleven_letters_or_digits_or_fifteen_digits_are_valid(brevo, monkeypatch, sender):
    _, calls = brevo
    monkeypatch.setattr(settings, "brevo_sms_sender", sender)
    assert sms_service.send_sms("+447700900000", "hello") is True
    assert json.loads(calls[0].content)["sender"] == sender


def test_long_message_is_capped_without_splitting_a_word_or_number(brevo):
    _, calls = brevo
    message = "a" * 150 + " 12345678901 tail"
    sms_service.send_sms("+447700900000", message)
    content = json.loads(calls[0].content)["content"]
    assert len(content) <= 160
    assert content == "a" * 150
    assert "12345" not in content


def test_message_of_exactly_160_is_untouched(brevo):
    _, calls = brevo
    sms_service.send_sms("+447700900000", "b" * 160)
    assert json.loads(calls[0].content)["content"] == "b" * 160


def test_non_plain_characters_are_simplified(brevo):
    _, calls = brevo
    sms_service.send_sms("+447700900000", "Caf\u00e9 {pump}`x`\nrow")
    assert json.loads(calls[0].content)["content"] == "Cafe pump x row"


def test_critical_message_keeps_the_numbers_when_the_name_is_long(brevo):
    _, calls = brevo
    assert sms_service.notify_critical("+447700900000", "Pump" + "x" * 300, "temperature", 123.456, 99.5) is True
    content = json.loads(calls[0].content)["content"]
    assert len(content) <= 160
    assert content.endswith("= 123.456 (threshold: 99.5)")
    assert content.startswith("PHAEMOS CRITICAL: temperature on Pump")
    # the room sum is exact: a name that has to give way fills the message to the cap
    assert len(content) == 160


def test_critical_without_a_phone_number_sends_nothing(brevo):
    _, calls = brevo
    assert sms_service.notify_critical(None, "Pump", "temperature", 1.0, 2.0) is False
    assert calls == []


def test_vendor_error_status_returns_false_and_logs_no_number(brevo, caplog):
    behaviour, _ = brevo
    behaviour["handler"] = lambda request: httpx.Response(400, json={"message": "bad +447700900000"})
    with caplog.at_level(logging.WARNING):
        assert sms_service.send_sms("+447700900000", "hello") is False
    assert "447700900000" not in caplog.text
    assert "400" in caplog.text


def test_timeout_returns_false(brevo):
    behaviour, _ = brevo

    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    behaviour["handler"] = boom
    assert sms_service.send_sms("+447700900000", "hello") is False


def test_the_call_has_a_five_second_timeout(monkeypatch):
    seen = {}

    class Recorder:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            return httpx.Response(201, json={}, request=httpx.Request("POST", URL))

    monkeypatch.setattr(sms_service.httpx, "Client", Recorder)
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    monkeypatch.setattr(settings, "brevo_sms_sender", "PHAEMOS")
    assert sms_service.send_sms("+447700900000", "hello") is True
    assert seen["timeout"] == 5.0


@pytest.mark.parametrize("value, expected", [
    (0.30000000000000004, "0.3"),
    (99.0, "99"),
    (123.456789, "123.457"),
    (-0.0001, "0"),
    (0.1 + 0.2, "0.3"),
    (80, "80"),
    (1.5, "1.5"),
])
def test_numbers_have_at_most_three_decimals_and_no_float_noise(value, expected):
    assert sms_service.format_number(value) == expected


def test_critical_message_shows_clean_numbers(brevo):
    _, calls = brevo
    sms_service.notify_critical("+447700900000", "Pump", "temperature", 0.30000000000000004, 80.0)
    content = json.loads(calls[0].content)["content"]
    assert content == "PHAEMOS CRITICAL: temperature on Pump = 0.3 (threshold: 80)"


@pytest.mark.parametrize("name", ["", "   ", "\u2603\u2603", "`"])
def test_a_name_that_is_empty_after_cleaning_reads_device(brevo, name):
    _, calls = brevo
    sms_service.notify_critical("+447700900000", name, "temperature", 1.0, 2.0)
    assert "temperature on device =" in json.loads(calls[0].content)["content"]


def test_a_backtick_is_stripped(brevo):
    _, calls = brevo
    sms_service.send_sms("+447700900000", "a`b")
    assert "`" not in json.loads(calls[0].content)["content"]


def test_brevo_error_code_is_logged_but_not_the_message(brevo, caplog):
    behaviour, _ = brevo
    behaviour["handler"] = lambda request: httpx.Response(
        400, json={"code": "invalid_parameter", "message": "bad number 447700900000"})
    with caplog.at_level(logging.WARNING):
        assert sms_service.send_sms("+447700900000", "hello") is False
    assert "invalid_parameter" in caplog.text
    assert "bad number" not in caplog.text
    assert "447700900000" not in caplog.text


def test_brevo_error_without_json_logs_an_unknown_code(brevo, caplog):
    behaviour, _ = brevo
    behaviour["handler"] = lambda request: httpx.Response(502, text="<html>bad gateway</html>")
    with caplog.at_level(logging.WARNING):
        assert sms_service.send_sms("+447700900000", "hello") is False
    assert "HTTP 502" in caplog.text and "code unknown" in caplog.text
