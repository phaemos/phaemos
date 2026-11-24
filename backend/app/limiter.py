import ipaddress

import time

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import HTTPConnection, Request

from app.config import settings
from app.errors import ApiError, Code, rate_limit_headers
from app.services.counters import Counters


def _trusted(peer: str) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for network in settings.trusted_proxies.split(","):
        network = network.strip()
        if network and address in ipaddress.ip_network(network, strict=False):
            return True
    return False


def normalise_address(address: str) -> str:
    """Key an IPv6 client by its /64, because one /64 hands a single caller as many addresses as they like."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(ip, ipaddress.IPv6Address) and not ip.ipv4_mapped:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    if isinstance(ip, ipaddress.IPv6Address):
        return str(ip.ipv4_mapped)
    return str(ip)


def _real_ip(request: Request) -> str:
    # behind Nginx every request arrives from the proxy, so the client's address
    # comes from the X-Real-IP header Nginx sets. The header is only believed when
    # the request really came from a trusted proxy: anyone reaching the API
    # directly could otherwise send a new value each time and never hit a limit.
    peer = get_remote_address(request)
    if _trusted(peer):
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return normalise_address(real_ip)
    return normalise_address(peer)


def _rate_key(request: Request) -> str:
    """What a limit is counted against: the token for a call made with a verified access token and the address otherwise.

    The token key is set by get_current_user only after the token has been checked against the database and slowapi reads
    it after the dependencies have run, so a made-up Authorization header never gets a bucket of its own. Making more tokens
    does not widen an account's share, because every token call also counts against the account (see token_access).
    """
    return getattr(request.state, "rate_key", None) or _real_ip(request)


_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_limit(spec: str) -> tuple[int, int]:
    """'120/minute' is (120, 60): the count and the window in seconds."""
    count, _, unit = spec.strip().partition("/")
    return int(count), _UNITS[unit.strip().removesuffix("s")]


# the named limit classes. Each is a setting, so an operator changes a number without a code change:
#   anonymous  a caller with no credential, counted by address
#   signed_in  an account or API token, counted by account (or token)
#   write      a route that changes something
#   sensitive  a route that is costly or dangerous to repeat (a reset link, an export)
LIMIT_CLASSES = ("anonymous", "signed_in", "write", "sensitive")


def named(name: str):
    """The value of a named class, for a route's own limit: `@limiter.limit(named("write"))`."""
    if name not in LIMIT_CLASSES:
        raise ValueError(f"unknown limit class {name!r}")
    return lambda: getattr(settings, f"rate_limit_{name}")


# counters for the default limits. Redis when it answers, memory when it does not (see services/counters.py)
default_counters = Counters("phaemos:limit:")


def hit(name: str, who: str) -> None:
    """Count one call of a class against `who` and raise a 429 with Retry-After when the class's allowance is used up."""
    count, window = parse_limit(getattr(settings, f"rate_limit_{name}"))
    now = int(time.time())
    used = default_counters.incr(f"{name}:{who}:{now // window}", window)
    if used > count:
        retry = max(1, window - now % window)
        raise ApiError(
            429, Code.RATE_LIMITED, f"Too many requests. Try again in {retry} seconds",
            headers=rate_limit_headers(count, retry),
        )


_kinds: dict = {}


def _has_own_limit(route) -> bool:
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False
    return f"{endpoint.__module__}.{endpoint.__name__}" in limiter._route_limits


def default_limit(connection: HTTPConnection) -> None:
    """The default limit on every route, as an application dependency (see main.py).

    - a route with its own `@limiter.limit` keeps that and is not counted here
    - a public route is counted by address in the `anonymous` class
    - a device key route is not counted here: the ingest allowance and the firmware limits belong to the device
    - a signed-in route is counted by account in `signed_in` once the caller is known (see get_current_user)
    - a WebSocket is never counted here: its own per-account and per-address cap applies
    """
    if connection.scope.get("type") != "http" or not limiter.enabled:
        return
    # imported here because the auth module imports this one
    from app.services import token_access

    route = token_access.effective_route(connection.scope)
    if route is None or _has_own_limit(route):
        return

    key = (id(route), connection.scope["method"])
    if key not in _kinds:
        _kinds[key] = token_access.classify(route, connection.scope["method"]).kind
    kind = _kinds[key]
    if kind == token_access.PUBLIC:
        hit("anonymous", _real_ip(connection))


def count_signed_in(who: str) -> None:
    """Called by get_current_user once the caller is verified: the account's share across every route."""
    if limiter.enabled:
        hit("signed_in", who)


class AppLimiter(Limiter):
    def reset(self) -> None:
        super().reset()
        default_counters.reset()


# instantiate the limiter once here so main.py and individual routes both import
# the same object - slowapi requires the same Limiter instance to be registered on
# the app.state and used in route decorators. Its counters are in Redis outside development and fall back to memory with a
# warning when Redis fails, so a Redis outage never takes the API down
limiter = AppLimiter(
    key_func=_rate_key,
    storage_uri=None if settings.is_development else settings.redis_url,
    in_memory_fallback_enabled=True,
)
