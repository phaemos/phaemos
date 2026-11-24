from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# use create_engine to build the connection pool that talks to the PostgreSQL database
# hide_parameters keeps the values of a failed statement out of the error and so out of the log: they hold emails,
# password hashes and device keys
engine = create_engine(settings.database_url, hide_parameters=True)

# use sessionmaker to return a factory class; every call to SessionLocal() gives a fresh DB session
# autocommit=False means changes are only saved when db.commit() is called explicitly
# autoflush=False prevents SQLAlchemy from automatically syncing pending changes before every query
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# use DeclarativeBase - the modern SQLAlchemy 2.x way to define ORM models as plain Python classes
class Base(DeclarativeBase):
    pass


def create_tables() -> None:
    """Create any table the models define that is missing. Never alters a table.

    Importing the app does not do this any more (so the OpenAPI document can be made with no database). The API calls it at
    start in development, the one-shot `schema` job runs it as the database owner in production and the tests call it.
    The models must be registered first: import app.main (or the model modules) before calling.
    """
    Base.metadata.create_all(bind=engine)


# act as a FastAPI dependency - hand a DB session to a route handler then clean up afterwards
def get_db():
    db = SessionLocal()
    try:
        # use 'yield' to turn this into a generator; FastAPI pauses here while the route runs
        yield db
    finally:
        # always close the session, even if the route raised an exception, to release the connection
        db.close()
