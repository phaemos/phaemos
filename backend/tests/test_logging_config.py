import logging

import pytest

from app.logging_config import configure_logging
from app.services import email_service


@pytest.fixture
def restore_level():
    logger = logging.getLogger("app")
    level, handlers = logger.level, list(logger.handlers)
    yield
    logger.setLevel(level)
    logger.handlers = handlers


def test_development_logs_info_without_the_test_raising_the_level(restore_level, caplog):
    # caplog.at_level is deliberately not used: the level comes from configure_logging alone
    configure_logging("development")
    email_service._log.info("dev line")
    assert "dev line" in caplog.text


@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_other_environments_drop_info_and_keep_warnings(restore_level, caplog, environment):
    configure_logging(environment)
    email_service._log.info("quiet line")
    email_service._log.warning("loud line")
    assert "quiet line" not in caplog.text
    assert "loud line" in caplog.text


def test_environment_is_trimmed_and_lowercased(restore_level):
    configure_logging(" Development ")
    assert logging.getLogger("app").level == logging.INFO


def test_repeated_calls_do_not_stack_handlers(restore_level):
    configure_logging("development")
    configure_logging("development")
    assert len([h for h in logging.getLogger("app").handlers if getattr(h, "_phaemos", False)]) == 1


def test_uvicorn_loggers_are_left_alone(restore_level):
    before = logging.getLogger("uvicorn").level, logging.getLogger("uvicorn.access").level
    configure_logging("development")
    assert (logging.getLogger("uvicorn").level, logging.getLogger("uvicorn.access").level) == before
