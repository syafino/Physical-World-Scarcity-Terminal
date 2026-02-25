"""
Database Connection Management

Provides SQLAlchemy engine and session factory for PostgreSQL/PostGIS.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from src.config.settings import settings

# Create engine with connection pooling
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before use
    echo=settings.debug,  # Log SQL in debug mode
)

# Session factory
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@event.listens_for(engine, "connect")
def set_search_path(dbapi_conn, connection_record):
    """Set search path to include PostGIS functions."""
    cursor = dbapi_conn.cursor()
    cursor.execute("SET search_path TO public, topology")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI/Streamlit to get database session.
    
    Usage:
        @app.get("/data")
        def get_data(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database session (non-FastAPI usage).
    
    Usage:
        with get_db_context() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Alias for compatibility
get_db_session = get_db_context


def check_database_connection() -> bool:
    """
    Verify database connectivity.
    
    Returns:
        True if connection successful, False otherwise.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # Check PostGIS
            result = conn.execute(text("SELECT PostGIS_Version()"))
            version = result.scalar()
            if version:
                return True
        return False
    except Exception:
        return False


def get_postgis_version() -> str | None:
    """Get PostGIS version string."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT PostGIS_Version()"))
            return result.scalar()
    except Exception:
        return None
