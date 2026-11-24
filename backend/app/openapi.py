"""
The OpenAPI document, with what the framework cannot know: the two credentials (a bearer token and a device key), the auth
class of every operation, the shared error shape and the answers every route can give.

`classify` in app/services/token_access.py is the one place that says who may call a route, so the document is made from it
and cannot disagree with the code.
"""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.config import settings
from app.services import token_access

ERROR_SCHEMA = {
    "type": "object",
    "required": ["code", "detail"],
    "properties": {
        "code": {"type": "string", "description": "Stable and snake_case. Read this, not the sentence", "example": "device_not_found"},
        "detail": {"type": "string", "description": "A sentence a person can act on. Its wording can change"},
        "request_id": {"type": "string", "description": "Quote this when you report a problem"},
        "errors": {
            "type": "array",
            "description": "Only for validation_failed: where each problem is",
            "items": {
                "type": "object",
                "properties": {"loc": {"type": "array", "items": {}}, "msg": {"type": "string"}, "type": {"type": "string"}},
            },
        },
    },
}

_ERROR_REF = {"description": "", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}


def _error(description: str) -> dict:
    return {**_ERROR_REF, "description": description}


_RESPONSES = {
    "401": _error("No credential or one that is bad, expired or revoked"),
    "403": _error("Not allowed: a role, a scope or a session is needed"),
    "404": _error("Does not exist or the caller may not read it"),
    "422": _error("The request is not valid. `errors` says where"),
    "429": _error("Limited. Wait `Retry-After` seconds"),
    "500": _error("Something went wrong on our side. Quote `request_id`"),
}
_BY_CLASS = {
    token_access.PUBLIC: ("422", "429", "500"),
    token_access.DEVICE_KEY: ("401", "422", "429", "500"),
    token_access.TOKEN: ("401", "403", "404", "422", "429", "500"),
    token_access.SESSION_ONLY: ("401", "403", "404", "422", "429", "500"),
}


def build(app: FastAPI) -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    doc = get_openapi(
        title=app.title, version=settings.release_version, description=app.description, routes=app.routes,
        servers=[{"url": "/", "description": "Relative to the host that serves this document"}],
    )
    components = doc.setdefault("components", {})
    components.setdefault("schemas", {})["Error"] = ERROR_SCHEMA
    components["securitySchemes"] = {
        "BearerAuth": {
            "type": "http", "scheme": "bearer",
            "description": "A session's access token or an API token (`pht_...`) for scripts and tools",
        },
        "DeviceKey": {"type": "apiKey", "in": "header", "name": "X-API-Key", "description": "A machine's device key"},
    }
    for route in token_access.iter_routes(app):
        if not route.include_in_schema:
            continue
        for method in (getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}:
            operation = doc.get("paths", {}).get(route.path_format, {}).get(method.lower())
            if operation is None:
                continue
            kind = token_access.classify(route, method)
            operation["x-auth-class"] = kind.kind
            if kind.least_scope:
                operation["x-least-scope"] = kind.least_scope
            if kind.kind == token_access.DEVICE_KEY:
                operation["security"] = [{"DeviceKey": []}]
            elif kind.kind == token_access.PUBLIC:
                operation["security"] = []
            else:
                operation["security"] = [{"BearerAuth": []}]
            responses = operation.setdefault("responses", {})
            for status in _BY_CLASS.get(kind.kind, ()):
                responses[status] = _RESPONSES[status]
            if "422" in responses:
                responses["422"] = _RESPONSES["422"]
    app.openapi_schema = doc
    return doc
