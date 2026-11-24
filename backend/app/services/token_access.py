"""
Access tokens: the format, the hash, the scopes and the one place that says which kind of caller each route accepts.

Every route under /api/v1 is in exactly one class. `classify` works the class out from the route's own dependencies, so a
route cannot be in a class its code does not match and the test that walks every route fails for one nobody classified.

| Class        | Who may call it                                                          | How a route gets it                         |
| ------------ | ------------------------------------------------------------------------ | ------------------------------------------- |
| public       | anyone                                                                   | no dependency that names a caller           |
| device_key   | a machine with an X-API-Key                                              | an `X-API-Key` header parameter             |
| token        | a session or a token whose scope is high enough for the method          | `Depends(get_current_user)`                 |
| session_only | a signed-in session. A token is refused with 403                         | `fresh_proof`, `session_only` or any route |
|              |                                                                          | under /api/v1/auth not listed below         |

The scope a token needs comes from the method and the route and not from a list kept by hand: a safe method (GET, HEAD,
OPTIONS) needs `read` and any other method needs `operate`. A route that depends on `require_admin` needs `admin` for every
method, a safe one included. `read` therefore cannot cause a write and the test checks that no GET handler writes.
"""

import hashlib
import hmac
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass

from app.services.keys import verification_keys

PREFIX = "pht_"
ID_LENGTH = 12
SECRET_LENGTH = 43          # 32 random bytes, URL-safe base64 with no padding: 256 bits
SCOPES = ("read", "operate", "admin")
_RANK = {name: n for n, name in enumerate(SCOPES)}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_TOKENS_PER_ACCOUNT = 20
# every call a token makes also counts here, whatever token it was, so many tokens cannot add up to a larger share
ACCOUNT_REQUESTS_PER_MINUTE = 600

# set to a fresh dict for each request by SourceMiddleware. get_current_user puts the token's id in it and the audit service
# reads it, so every audit row a token causes names the token. A dict is shared between the threads a request runs in, where
# a plain value set in a dependency would be lost
current_token: ContextVar[dict | None] = ContextVar("current_token", default=None)

INVALID = "Invalid or expired token"
SESSION_NEEDED = "A signed-in session is needed for this. An API token cannot do it"

AUTH_PREFIX = "/api/v1/auth"
# the only routes under /api/v1/auth a token may call. Everything else there is about the account's own security
TOKEN_AUTH_ROUTES = frozenset({("GET", "/api/v1/auth/whoami"), ("GET", "/api/v1/auth/tokens")})

_FORMAT = re.compile(rf"^{PREFIX}([0-9a-f]{{{ID_LENGTH}}})_([A-Za-z0-9_-]{{{SECRET_LENGTH}}})$")


def looks_like_token(value: str) -> bool:
    return value.startswith(PREFIX)


def new_token() -> tuple[str, str, str]:
    """A fresh (id, secret, whole token)."""
    token_id = secrets.token_hex(ID_LENGTH // 2)
    secret = secrets.token_urlsafe(32)
    return token_id, secret, f"{PREFIX}{token_id}_{secret}"


def parse(value: str) -> tuple[str, str] | None:
    found = _FORMAT.match(value)
    return (found.group(1), found.group(2)) if found else None


def _digest(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def hashes(value: str) -> list[str]:
    """The keyed hash of a secret, with the current key and with the previous key while a rotation is in progress."""
    return [_digest(key, value) for key in verification_keys("api_token")]


def matches(candidates: list[str], stored: str) -> bool:
    return any([hmac.compare_digest(candidate, stored) for candidate in candidates])


def effective_scope(scope: str, role: str) -> str:
    """The scope a token has now. `admin` is only as good as the account's role at this request."""
    return "operate" if scope == "admin" and role != "admin" else scope


def acts_as_admin(request, user) -> bool:
    """Whether this call may do what only an admin may. A token below the admin scope may not, whatever its account's role is.

    For a route a token reaches with `operate` where the code still gives an admin more (the admin-only fields of a machine),
    so that `operate` really is "operate" and not "admin" for an admin's own token.
    """
    if user.role != "admin":
        return False
    row = getattr(request.state, "api_token", None)
    return row is None or effective_scope(row.scope, user.role) == "admin"


def allows(scope: str, needed: str) -> bool:
    return _RANK.get(scope, -1) >= _RANK[needed]


# ── the route classes ───────────────────────────────────────────────────────

PUBLIC, DEVICE_KEY, TOKEN, SESSION_ONLY, UNCLASSIFIED = "public", "device_key", "token", "session_only", "unclassified"


@dataclass(frozen=True)
class RouteClass:
    kind: str
    least_scope: str | None = None     # for the token class, the lowest scope that may call this method


def session_only_marker(function):
    """Mark a dependency so that any route using it refuses a token. fresh_proof and session_only carry it."""
    function.session_only = True
    return function


def token_self_service_marker(function):
    """Mark a dependency for the one thing a token may do to tokens: revoke itself. Any scope may."""
    function.token_self_service = True
    return function


def _walk(dependant):
    yield dependant
    for child in dependant.dependencies:
        yield from _walk(child)


def iter_routes(app):
    """Every route the app serves, with its full path and the dependencies it really has.

    Newer FastAPI does not flatten an included router: `app.routes` holds the router and a request's `scope["route"]` is the
    original route with no prefix. This walks the included routers and yields, for each route, an object with the full
    `path_format`, `dependant`, `methods`, `response_model` and the rest (an APIRoute or its effective copy). Older FastAPI
    flattens and then this yields the routes as they are.
    """
    def walk(items):
        for item in items:
            children = item.effective_candidates() if hasattr(item, "effective_candidates") else None
            if children is not None:
                yield from walk(children)
            else:
                yield item

    for route in walk(app.routes):
        if getattr(route, "dependant", None) is not None:
            yield route


def effective_route(scope):
    """The route (with its full path and dependencies) that is serving this HTTP request or None."""
    app = scope.get("app")
    endpoint = scope.get("endpoint")
    method = scope.get("method")
    if app is None or endpoint is None:
        return None
    index = getattr(app.state, "_route_index", None)
    if index is None:
        index = {}
        for route in iter_routes(app):
            for verb in getattr(route, "methods", None) or ():
                index.setdefault((route.endpoint, verb), []).append(route)
        app.state._route_index = index
    candidates = index.get((endpoint, method), [])
    for route in candidates:
        regex = getattr(route, "path_regex", None)
        if regex is not None and regex.match(scope.get("path", "")):
            return route
    return None


def classify(route, method: str) -> RouteClass:
    """The class of a route for one method, worked out from its dependencies."""
    # imported here: auth.py imports this module
    from app.routes.auth import _bearer, get_current_user, require_admin

    path = getattr(route, "path_format", None) or route.path
    dependant = getattr(route, "dependant", None)
    parts = list(_walk(dependant)) if dependant is not None else []
    calls = [part.call for part in parts]
    device_key = any(
        (param.alias or param.name).lower().replace("_", "-") == "x-api-key" for part in parts for param in part.header_params
    )
    takes_caller = get_current_user in calls
    if device_key and takes_caller:
        return RouteClass(UNCLASSIFIED)
    if device_key:
        return RouteClass(DEVICE_KEY)
    if _bearer in calls and not takes_caller:
        return RouteClass(UNCLASSIFIED)
    if not takes_caller:
        return RouteClass(PUBLIC)
    if any(getattr(call, "session_only", False) for call in calls):
        return RouteClass(SESSION_ONLY)
    if any(getattr(call, "token_self_service", False) for call in calls):
        return RouteClass(TOKEN, "read")
    if path.startswith(AUTH_PREFIX + "/") and (method, path) not in TOKEN_AUTH_ROUTES:
        return RouteClass(SESSION_ONLY)
    if require_admin in calls:
        # administration is never `read`: the audit trail and the webhook list are only for an admin scope, even to look at
        return RouteClass(TOKEN, "admin")
    return RouteClass(TOKEN, "read" if method in SAFE_METHODS else "operate")
