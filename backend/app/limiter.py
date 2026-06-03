from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _real_ip(request: Request) -> str:
    # I read X-Real-IP first because Nginx sets this to the genuine client IP before
    # forwarding the request. Without this, get_remote_address returns the Nginx proxy
    # IP (127.0.0.1), putting all users in the same rate-limit bucket and making
    # per-IP limits useless in production.
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


# I instantiate the limiter once here so main.py and individual routes both import
# the same object - slowapi requires the same Limiter instance to be registered on
# the app.state and used in route decorators.
limiter = Limiter(key_func=_real_ip)
