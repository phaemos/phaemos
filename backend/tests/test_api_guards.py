"""
The guards that keep the conventions from eroding. One test walks every registered route and fails when a route:

* is in no stated auth class (tests/test_access_tokens.py holds the table)
* has no limit (every route is covered by the default limit or has its own and a device key route must name its own)
* has a body and no response model
* is served by code that still raises an old-style HTTPException
* has an operation id that is not unique

The two lists of known gaps below are for routes and files another round has not moved over yet. They can only shrink: a
test fails for an entry that is no longer a gap, so whoever finishes a route removes it from the list.
"""

import re
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.datastructures import DefaultPlaceholder

from app.limiter import _has_own_limit, default_limit
from app.main import app
from app.services import token_access

BACKEND = Path(__file__).resolve().parents[1]

# routes that return a body and have no response model yet. Each belongs to a builder who is moving it over
RESPONSE_MODEL_GAPS: set = set()
# an attachment built by hand: the answer is a downloadable file and not a JSON model
# a file or a stream has no JSON model: the audit and reading exports and the firmware image
RESPONSE_MODEL_EXEMPT = {
    ("GET", "/api/v1/auth/me/export"), ("GET", "/api/v1/telemetry/export"), ("GET", "/api/v1/firmware/download"),
}

# files that still raise `HTTPException` themselves. Their answers come out in the one shape with a code from the status and
# they move to ApiError with a code from app/errors.py
OLD_STYLE_ERROR_GAPS: set = set()

# device key routes have no default limit (it would throttle a machine below its allowance). Each has its own
DEVICE_KEY_OWN_LIMIT = {
    ("POST", "/api/v1/telemetry"), ("POST", "/api/v1/telemetry/batch"),
    # counted per device key in services/ingest_limit.py
    ("GET", "/api/v1/firmware/latest"), ("GET", "/api/v1/firmware/download"),
}

_NON_JSON = (RedirectResponse, StreamingResponse, FileResponse, PlainTextResponse, HTMLResponse)


def _routes():
    for route in token_access.iter_routes(app):
        if route.include_in_schema:
            for method in sorted((getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}):
                yield route, method


def _has_json_body(route) -> bool:
    if route.status_code in (204, 205, 304):
        return False
    response_class = route.response_class.value if isinstance(route.response_class, DefaultPlaceholder) else route.response_class
    return not (isinstance(response_class, type) and issubclass(response_class, _NON_JSON))


def test_every_route_has_a_limit():
    missing = []
    for route, method in _routes():
        if default_limit not in [dep.call for dep in route.dependant.dependencies]:
            # the default is an application dependency, so every route has it unless the app was built without it
            missing.append((method, route.path_format, "no default limit"))
        kind = token_access.classify(route, method).kind
        if kind == token_access.DEVICE_KEY and not _has_own_limit(route) and (method, route.path_format) not in DEVICE_KEY_OWN_LIMIT:
            missing.append((method, route.path_format, "a device key route with no limit of its own"))
    assert not missing, missing


def test_every_route_with_a_body_has_a_response_model():
    found = {
        (method, route.path_format)
        for route, method in _routes()
        if _has_json_body(route) and route.response_model is None and (method, route.path_format) not in RESPONSE_MODEL_EXEMPT
    }
    new = sorted(found - RESPONSE_MODEL_GAPS)
    assert not new, f"routes with a body and no response_model (add one): {new}"
    present = {(method, route.path_format) for route, method in _routes()}
    stale = sorted(g for g in RESPONSE_MODEL_GAPS if g in present and g not in found)
    assert not stale, f"these now have a response model. Remove them from RESPONSE_MODEL_GAPS: {stale}"


def test_no_code_raises_an_old_style_error_apart_from_the_listed_files():
    found = set()
    for path in (BACKEND / "app").rglob("*.py"):
        if re.search(r"raise HTTPException\(", path.read_text()):
            found.add(str(path.relative_to(BACKEND)))
    assert found <= OLD_STYLE_ERROR_GAPS, f"raise ApiError(status, Code.X, ...) instead: {sorted(found - OLD_STYLE_ERROR_GAPS)}"
    assert OLD_STYLE_ERROR_GAPS <= found, f"these files are moved over. Remove them from OLD_STYLE_ERROR_GAPS: {sorted(OLD_STYLE_ERROR_GAPS - found)}"


def test_operation_ids_are_unique_and_are_function_names():
    seen = {}
    for route, method in _routes():
        operation_id = route.operation_id or route.unique_id
        assert operation_id not in seen, (operation_id, route.path_format, seen[operation_id])
        seen[operation_id] = route.path_format
        if route.operation_id is None:
            assert route.unique_id == route.name, (route.path_format, route.unique_id)


def test_every_code_used_in_the_app_exists():
    from app.errors import Code

    used = set()
    for path in (BACKEND / "app").rglob("*.py"):
        used |= set(re.findall(r"\bCode\.([A-Z_]+)\b", path.read_text()))
    assert not [name for name in used if not hasattr(Code, name)]


def test_every_error_code_is_in_the_set():
    """A code that is not in app.errors.Code fails here: a Code.X that does not exist or a string that is not in the set."""
    import ast

    from app.errors import CODES, Code

    bad = []
    for path in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ApiError" and len(node.args) >= 2:
                code = node.args[1]
                if isinstance(code, ast.Constant) and isinstance(code.value, str) and code.value not in CODES:
                    bad.append((str(path.relative_to(BACKEND)), node.lineno, code.value))
                if isinstance(code, ast.Attribute) and getattr(code.value, "id", None) == "Code" and not hasattr(Code, code.attr):
                    bad.append((str(path.relative_to(BACKEND)), node.lineno, code.attr))
    assert not bad, bad
    # the codes the ingest and webhook routes use as plain strings are in the set
    for code in ("replay_pair_missing", "counter_out_of_range", "observed_at_too_old", "webhook_template_invalid",
                 "webhook_not_json", "webhook_delivery_failed", "endpoint_removed", "idempotency_key_reused",
                 "replay_stale", "replay_counter_back"):
        assert code in CODES, code


def test_an_unknown_code_is_refused_loudly_in_development():
    import pytest

    from app.errors import ApiError

    with pytest.raises(ValueError):
        ApiError(400, "not_a_real_code", "x")
