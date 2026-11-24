"""
Shared dependencies for routes.

Paging. Every list takes `limit` and `offset` (and `skip`, an older name for `offset`, accepted for this release):

    @router.get("/things")
    def list_things(response: Response, page: Page = Depends(Page), db: Session = Depends(get_db)):
        query = db.query(Thing).order_by(Thing.created_at.desc(), Thing.id)      # every order ends in id
        set_total(response, query.count())
        return query.offset(page.offset).limit(page.limit).all()

A route with a different ceiling states it with `Page.up_to(500, default=100)`:

    page: Page = Depends(Page.up_to(500, default=100))
"""

from fastapi import Query, Response

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# no list is ever read from further down than this. A client that needs more uses a keyset filter such as `before`
MAX_OFFSET = 100_000


class Page:
    """The paging parameters of a list: `limit` and `offset`. Read `page.limit` and `page.offset`."""

    # a plain class and not a dataclass field list: FastAPI reads the signature of __init__ and a Query default cannot be a
    # dataclass default on every Python version
    def __init__(
        self,
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="How many rows to return"),
        offset: int = Query(default=0, ge=0, le=MAX_OFFSET, description="How many rows to skip"),
        skip: int | None = Query(default=None, ge=0, le=MAX_OFFSET, deprecated=True, description="Older name for offset"),
    ):
        self.limit = limit
        # an explicit skip stands in for an offset that was not sent
        self.offset = skip if skip is not None and not offset else offset

    def __repr__(self) -> str:
        return f"Page(limit={self.limit}, offset={self.offset})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Page) and (self.limit, self.offset) == (other.limit, other.offset)

    __hash__ = None  # type: ignore[assignment]

    @staticmethod
    def up_to(maximum: int, default: int = DEFAULT_LIMIT):
        """A paging dependency with its own maximum (and default) for a route that needs a different one."""
        if not 1 <= default <= maximum:
            raise ValueError("the default must lie between 1 and the maximum")

        class _Page(Page):
            def __init__(
                self,
                limit: int = Query(default=default, ge=1, le=maximum, description="How many rows to return"),
                offset: int = Query(default=0, ge=0, le=MAX_OFFSET, description="How many rows to skip"),
                skip: int | None = Query(default=None, ge=0, le=MAX_OFFSET, deprecated=True, description="Older name for offset"),
            ):
                super().__init__(limit=limit, offset=offset, skip=skip)

        _Page.__name__ = "Page"
        return _Page


def set_total(response: Response, total: int) -> None:
    """Put the unpaged row count in X-Total-Count. Every paged list sends it."""
    response.headers["X-Total-Count"] = str(int(total))
