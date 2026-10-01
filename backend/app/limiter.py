import ipaddress

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


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


def _real_ip(request: Request) -> str:
    # behind Nginx every request arrives from the proxy, so the client's address
    # comes from the X-Real-IP header Nginx sets. The header is only believed when
    # the request really came from a trusted proxy: anyone reaching the API
    # directly could otherwise send a new value each time and never hit a limit.
    peer = get_remote_address(request)
    if _trusted(peer):
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
    return peer


# instantiate the limiter once here so main.py and individual routes both import
# the same object - slowapi requires the same Limiter instance to be registered on
# the app.state and used in route decorators.
limiter = Limiter(key_func=_real_ip)
