"""
CORS that sends cookies only to the origins that need them.

The dashboard signs in and refreshes with an httpOnly cookie, so it must be allowed to send credentials. The
public website only calls the contact route and needs none. One CORS setting with credentials on gave every
allowed origin the right to make the browser attach the refresh cookie and to read the reply.
"""

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware


# response headers a browser page may read across origins. X-Total-Count is the unpaged total of a list and X-Next-Before is
# where the next page of a keyset list starts. Date lets the dashboard correct for a wrong clock on the person's computer.
# X-Request-ID, Retry-After and the X-RateLimit headers are what a client needs from an error, Deprecation, Sunset and Link
# announce a moved route and Idempotent-Replayed says a create was answered from the stored first answer. A browser hides
# every other header unless it is listed
EXPOSED_HEADERS = [
    "X-Total-Count", "X-Next-Before", "Date", "X-Request-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining",
    "X-RateLimit-Reset", "Deprecation", "Sunset", "Link", "Idempotent-Replayed",
]


class PerOriginCORS:
    def __init__(self, app, credentialed: list[str], others: list[str], **options):
        self._others = set(others) - set(credentialed)
        self._with_credentials = CORSMiddleware(app, allow_origins=credentialed, allow_credentials=True, **options)
        self._without_credentials = CORSMiddleware(app, allow_origins=sorted(self._others), allow_credentials=False, **options)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and Headers(scope=scope).get("origin") in self._others:
            await self._without_credentials(scope, receive, send)
            return
        await self._with_credentials(scope, receive, send)
