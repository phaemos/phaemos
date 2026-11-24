"""
Checks on an address the API is asked to call, so an admin cannot point it at the
network it runs in.

Call `check_outbound_url(url)` before saving an address and again just before each
delivery, because a name can resolve somewhere else later. Everything is refused unless
every address the host resolves to is a public one.
"""

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from app.config import settings


class UnsafeUrl(ValueError):
    """The address must not be called. The message says why and is safe to show."""


class CannotResolve(UnsafeUrl):
    """The name did not resolve. That is not a finding about the address: it may be a passing resolver fault.

    It is an UnsafeUrl so saving an address still refuses a name that does not exist. Delivery tells the two
    apart: it switches a webhook off only for a positive finding, never for this.
    """


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # an IPv4 address written inside an IPv6 one is judged as the IPv4 address
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # is_global is false for private, loopback, link-local, shared (100.64.0.0/10) and reserved
    # ranges. The explicit checks cover multicast and the unspecified address as well.
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified or ip.is_reserved or ip.is_loopback)


def check_outbound_url(url: str) -> list[str]:
    """Raise UnsafeUrl unless the address is https (http in development) and only public addresses.

    Returns the addresses the host resolved to, all of them public.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise UnsafeUrl("That is not a valid address") from None
    allowed = {"https", "http"} if settings.is_development else {"https"}
    if parts.scheme not in allowed:
        raise UnsafeUrl("The address must start with https://")
    if not host:
        raise UnsafeUrl("That is not a valid address")
    if parts.username is not None or parts.password is not None:
        # a user name and password in an address would be lost when the request is sent to the checked IP
        raise UnsafeUrl("The address must not contain a user name or password")

    try:
        literal = [str(ipaddress.ip_address(host))]
    except ValueError:
        literal = None

    if literal is not None:
        addresses = literal
    else:
        try:
            found = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError):
            raise CannotResolve("That address could not be found") from None
        # IPv4 first: a host with no IPv6 route (a default Docker bridge) cannot reach an IPv6 address
        addresses = sorted({info[4][0] for info in found}, key=lambda a: (":" in a, a))
    if not addresses:
        raise CannotResolve("That address could not be found")

    # every address counts: one private answer among public ones is still refused
    if not all(_is_public(address) for address in addresses):
        raise UnsafeUrl("The address points inside a private or reserved network")
    return addresses


def outbound_candidates(url: str) -> list[tuple[str, dict[str, str], dict]]:
    """Check the address, then give every checked address as something to send to, IPv4 first.

    Each item is (url with the checked IP in place of the name, extra headers, httpx request extensions). The
    Host header and the TLS server name stay the original name, so the certificate is still verified against
    it. Without this a name can be re-resolved to a private address between the check and the connection. A
    caller tries them in order and moves on when one cannot be reached.
    """
    addresses = check_outbound_url(url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        ipaddress.ip_address(host)
        return [(url, {}, {})]  # already a literal address, so there is nothing to swap
    except ValueError:
        pass
    host_header = host + (f":{parts.port}" if parts.port else "")
    extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
    out = []
    for ip in addresses:
        netloc = f"[{ip}]" if ":" in ip else ip
        if parts.port:
            netloc += f":{parts.port}"
        out.append((urlunsplit((parts.scheme, netloc, parts.path, parts.query, "")), {"Host": host_header}, extensions))
    return out


def pin_outbound_url(url: str) -> tuple[str, dict[str, str], dict]:
    """The first of outbound_candidates: the address to use when only one attempt is made."""
    return outbound_candidates(url)[0]
