import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import docs_options
from app.services import ml_service


def _settings(**values):
    # _env_file=None keeps a local .env from filling in values the test leaves out
    return Settings(_env_file=None, database_url="postgresql://u:p@db:5432/x", **values)


def _key(length=64):
    # generated per run so no key sits in the source for a secret scanner to find
    return secrets.token_hex(32)[:length]


def test_development_accepts_a_short_placeholder_key():
    assert _settings(secret_key="change_this_in_production", environment="development")


@pytest.mark.parametrize("environment", ["development", "production", "staging", ""])
def test_an_empty_key_is_refused_everywhere(environment):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key="  ", environment=environment)


@pytest.mark.parametrize("key", [
    "change_this_in_production",
    "change-this-to-a-random-32-char-string-minimum",
    "placeholder-placeholder-placeholder-1234",
    "ci-test-secret-key-not-for-production",
    "test-secret-key-not-for-production",
    "short",
])
@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_other_environments_refuse_an_unsafe_key(key, environment):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key=key, environment=environment)


def test_key_length_boundary_outside_development():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key=_key(31), environment="production")
    assert _settings(secret_key=_key(32), environment="production")


def test_environment_name_is_trimmed_and_lower_cased():
    padded = _settings(secret_key="short", environment="  DEVELOPMENT ")
    assert padded.is_development
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key="short", environment=" Production ")
    assert not _settings(secret_key=_key(), environment="prod").is_development


def test_production_accepts_a_random_key():
    assert _settings(secret_key=_key(), environment="production").environment == "production"


def test_model_path_defaults_to_the_ml_folder_and_can_be_set(monkeypatch):
    default = _settings(secret_key=_key(), environment="production").model_path
    assert default.endswith("/ml/model.pkl")
    monkeypatch.setenv("MODEL_PATH", "/var/lib/phaemos/model/model.pkl")
    assert _settings(secret_key=_key(), environment="production").model_path == "/var/lib/phaemos/model/model.pkl"


def test_ml_service_reads_its_path_from_settings():
    from app.config import settings
    assert ml_service.MODEL_PATH == settings.model_path


@pytest.mark.parametrize("development,expected", [(True, 200), (False, 404)])
def test_interactive_docs_are_development_only(development, expected):
    client = TestClient(FastAPI(**docs_options(development)))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == expected
