from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# I use create_engine to build the connection pool that talks to the PostgreSQL database
engine = create_engine(settings.database_url)

# I use sessionmaker to return a factory class; every call to SessionLocal() gives a fresh DB session
# autocommit=False means I only save changes when db.commit() is called explicitly
# autoflush=False means I prevent SQLAlchemy from automatically syncing pending changes before every query
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# I use DeclarativeBase - the modern SQLAlchemy 2.x way to define ORM models as plain Python classes
class Base(DeclarativeBase):
    pass


# I act as a FastAPI dependency - I hand a DB session to a route handler then clean up afterwards
def get_db():
    db = SessionLocal()
    try:
        # I use 'yield' to turn this into a generator; FastAPI pauses here while the route runs
        yield db
    finally:
        # I always close the session, even if the route raised an exception, to release the connection
        db.close()
