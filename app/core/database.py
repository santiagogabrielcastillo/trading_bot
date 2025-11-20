"""
Core database infrastructure using SQLAlchemy and SQLite.

Provides singleton Database class for connection management and
session handling via dependency injection.
"""
from contextlib import contextmanager
from typing import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

# Declarative base for all models
Base = declarative_base()


class Database:
    """
    Singleton database manager for SQLite connections.
    
    Handles engine creation, session management, and ensures
    proper foreign key constraints are enabled for SQLite.
    """
    
    _instance = None
    _engine: Engine = None
    _session_factory: sessionmaker = None
    
    def __new__(cls):
        """Ensure only one Database instance exists (singleton pattern)."""
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
        return cls._instance
    
    def initialize(self, db_path: str) -> None:
        """
        Initialize the database engine and session factory.
        
        Args:
            db_path: Path to SQLite database file (e.g., 'trading_state.db')
                    or full SQLite URL (e.g., 'sqlite:///:memory:')
        """
        if self._engine is not None:
            return  # Already initialized
        
        # Create database URL
        # If already a SQLite URL, use as-is
        if db_path.startswith("sqlite://"):
            db_url = db_path
        else:
            # Otherwise treat as file path
            db_url = f"sqlite:///{db_path}"
        
        # Create engine
        self._engine = create_engine(
            db_url,
            echo=False,  # Set to True for SQL query logging (debugging)
            future=True,  # Use SQLAlchemy 2.0 style
        )
        
        # Enable foreign key constraints for SQLite
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        
        # Create session factory
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        
        # Create all tables
        Base.metadata.create_all(self._engine)
    
    def get_engine(self) -> Engine:
        """Get the SQLAlchemy engine."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine
    
    def get_session(self) -> Session:
        """
        Create a new database session.
        
        Returns:
            SQLAlchemy Session instance
            
        Note:
            Caller is responsible for closing the session.
            Consider using get_db() context manager instead.
        """
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._session_factory()
    
    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope for database operations.
        
        Usage:
            with db.session_scope() as session:
                session.add(trade)
                # Automatic commit on success, rollback on exception
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def close(self) -> None:
        """Close the database engine and clean up resources."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Global database instance
db = Database()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency injection helper for getting database sessions.
    
    Usage (FastAPI style):
        def create_trade(trade_data: dict, session: Session = Depends(get_db)):
            session.add(Trade(**trade_data))
            session.commit()
    
    Usage (Manual):
        for session in get_db():
            session.add(Trade(...))
            session.commit()
    """
    session = db.get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(db_path: str) -> None:
    """
    Initialize the database with the given path.
    
    Convenience function for one-line initialization.
    
    Args:
        db_path: Path to SQLite database file
    """
    db.initialize(db_path)

