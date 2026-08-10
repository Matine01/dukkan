"""
Dukkan Cloud - Database Configuration
SQLAlchemy database session management and connection pooling.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from typing import Generator
import logging

from app.config import settings
from app.models import Base

logger = logging.getLogger(__name__)


# Create database engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,  # Enable connection health checks
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def init_db() -> None:
    """
    Initialize database tables.
    Creates all tables defined in models.py if they don't exist.
    """
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialization complete.")


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for getting database sessions.
    Ensures proper cleanup after each request.
    
    Usage in FastAPI routes:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Set SQLite pragmas if using SQLite (for development).
    This is ignored when using PostgreSQL.
    """
    pass  # PostgreSQL doesn't need pragma settings


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """
    Log connection checkout for debugging.
    """
    logger.debug("Database connection checked out from pool")


@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """
    Log connection checkin for debugging.
    """
    logger.debug("Database connection returned to pool")


class DatabaseContextManager:
    """
    Context manager for database sessions.
    Useful for background tasks and scripts outside of FastAPI requests.
    
    Usage:
        with DatabaseContextManager() as db:
            users = db.query(User).all()
    """
    
    def __init__(self):
        self.db = None
    
    def __enter__(self) -> Session:
        self.db = SessionLocal()
        return self.db
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.db.rollback()
            logger.error(f"Database transaction rolled back: {exc_val}")
        self.db.close()
        return False  # Don't suppress exceptions


# Convenience function for one-off queries
def query_db():
    """
    Simple query helper for scripts and background tasks.
    Returns a session that must be manually closed.
    
    Usage:
        db = query_db()
        try:
            users = db.query(User).all()
        finally:
            db.close()
    """
    return SessionLocal()
