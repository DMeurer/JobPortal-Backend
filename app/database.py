from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    # Verify a connection is alive before handing it out. Without this, every
    # connection pooled across a database restart is dead and the request that
    # picks it up fails.
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # Drop connections before proxies or the server time them out.
    pool_recycle=settings.db_pool_recycle,
    # Fail with an error instead of blocking forever when the pool is saturated.
    pool_timeout=settings.db_pool_timeout,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
