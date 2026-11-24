"""
A route that moved: registered at its new path and, for this release, at its old path as a deprecated alias.

    @moved(router, canonical, "GET", "/users", "/users", response_model=list[UserSummary])
    @limiter.limit(...)
    def list_users(...): ...

The two paths run the SAME function, so an alias has exactly the same auth class, limit, proof and answer as the route it
stands for. The old path answers with `Deprecation: true`, a `Sunset` date and a `Link` to the new path and is marked
deprecated in the OpenAPI document. The walking test has both paths in its table.
"""

from fastapi import APIRouter, Depends, Response

# 90 days after the day these routes moved (22 November 2026). After this date the old paths are removed
SUNSET = "Sat, 20 Feb 2027 00:00:00 GMT"
API_PREFIX = "/api/v1"


def deprecation_headers(successor: str):
    def add(response: Response) -> None:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = SUNSET
        response.headers["Link"] = f'<{successor}>; rel="successor-version"'

    return add


def moved(old_router: APIRouter, new_router: APIRouter, method: str, old_path: str, new_path: str, **route_options):
    def register(function):
        new_router.add_api_route(new_path, function, methods=[method], operation_id=function.__name__, **route_options)
        old_router.add_api_route(
            old_path, function, methods=[method], deprecated=True, operation_id=f"{function.__name__}_legacy",
            dependencies=[Depends(deprecation_headers(API_PREFIX + new_path))], **route_options,
        )
        return function

    return register
