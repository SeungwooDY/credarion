from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# pool_pre_ping guards against stale pooled connections; connect_timeout makes
# an unreachable database fail fast (10s) instead of hanging the request; and
# pool_recycle stays under the idle timeouts of hosted poolers (e.g. Supabase).
# SQLite (tests) doesn't accept connect_timeout, so only pass it to Postgres.
_connect_args = (
    {"connect_timeout": 10} if settings.database_url.startswith("postgresql") else {}
)
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=5,
    pool_timeout=15,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
