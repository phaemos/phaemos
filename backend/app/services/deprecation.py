"""
Headers for a route kept as an alias for one release.

An old path, parameter or method that still works answers with `Deprecation: true` and a `Sunset` date 90 days after the release
that deprecated it and a `Link` to what replaces it. A client logging those headers learns of a removal before it happens.
"""

from fastapi import Response

# 90 days after 22 November 2026, the day these aliases were announced
SUNSET = "Sat, 20 Feb 2027 00:00:00 GMT"


def deprecate(response: Response, replacement: str | None = None) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = SUNSET
    if replacement:
        response.headers["Link"] = f'<{replacement}>; rel="successor-version"'
