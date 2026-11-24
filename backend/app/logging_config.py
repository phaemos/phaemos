import logging
import re

from app.config import is_development_name

_FORMAT = "%(levelname)s:     %(name)s [%(request_id)s] - %(message)s"


# a query string up to the next space or quote. uvicorn writes the full request address of a live
# socket (token included) to its own connection line and --no-access-log does not stop that line.
_QUERY = re.compile(r"\?[^\s\"']*")


class StripQueryStrings(logging.Filter):
    """Cut everything after a question mark from a log message, so a token in an address is never written."""

    def filter(self, record: logging.LogRecord) -> bool:
        # the record keeps its shape: the same message template and the same number of arguments, so every handler that formats it
        # afterwards (uvicorn's access formatter unpacks exactly five) works and cutting a second time changes nothing. Emptying
        # the arguments instead made the formatter fail on every line ("not enough values to unpack")
        cut = lambda value: _QUERY.sub("", value) if isinstance(value, str) and "?" in value else value  # noqa: E731
        args = record.args
        if not args and isinstance(record.msg, str):
            # no arguments: the text is the whole message. With arguments the template is left alone, so no placeholder is lost
            record.msg = cut(record.msg)
        if isinstance(args, tuple):
            record.args = tuple(cut(value) for value in args)
        elif isinstance(args, dict):
            record.args = {key: cut(value) for key, value in args.items()}
        return True


class AddRequestId(logging.Filter):
    """Put the id of the request being served on every record or "-" outside a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        from app.request_id import request_id_var

        record.request_id = request_id_var.get()
        return True


def _strip_query_strings_from_uvicorn() -> None:
    # the filter sits on the loggers uvicorn writes through. It is added once, however many
    # times this runs.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        if not any(isinstance(f, StripQueryStrings) for f in target.filters):
            target.addFilter(StripQueryStrings())


def configure_logging(environment: str) -> None:
    """Set the level of the API's own loggers: INFO in development and WARNING elsewhere.

    Uvicorn keeps its own levels and handlers. Its loggers only get a filter that removes query
    strings from messages, because the live socket address carries an access token.
    """
    _strip_query_strings_from_uvicorn()
    app_logger = logging.getLogger("app")
    development = is_development_name(environment)
    app_logger.setLevel(logging.INFO if development else logging.WARNING)
    # one line for each request (see RequestIdMiddleware), in production too: method, path with no query string, status and
    # duration, with the request id from the format. Nothing that names a person is in it
    logging.getLogger("app.request").setLevel(logging.INFO)
    # called more than once (a reload or a test) must not stack handlers
    if not any(getattr(h, "_phaemos", False) for h in app_logger.handlers):
        handler = logging.StreamHandler()
        handler.addFilter(AddRequestId())
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._phaemos = True  # type: ignore[attr-defined]
        app_logger.addHandler(handler)
