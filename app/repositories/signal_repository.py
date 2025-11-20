"""
Repository for Signal model data access.
"""
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.sql import Signal
from app.repositories.base import BaseRepository


class SignalRepository(BaseRepository[Signal]):
    """
    Repository for managing Signal records.
    
    Provides specialized queries for signal history, filtering by signal type,
    and retrieving signals with metadata.
    """
    
    def __init__(self, session: Session):
        """Initialize with Signal model and session."""
        super().__init__(Signal, session)
    
    def get_by_symbol(self, symbol: str, limit: Optional[int] = None) -> List[Signal]:
        """
        Get all signals for a specific symbol.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            limit: Maximum number of signals to return
            
        Returns:
            List of Signal instances ordered by timestamp
        """
        query = self.session.query(Signal).filter(Signal.symbol == symbol).order_by(Signal.timestamp.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def get_latest(self, symbol: Optional[str] = None, limit: int = 10) -> List[Signal]:
        """
        Get the most recent signals.
        
        Args:
            symbol: Optional symbol filter
            limit: Maximum number of signals
            
        Returns:
            List of Signal instances ordered by timestamp (most recent first)
        """
        query = self.session.query(Signal)
        if symbol:
            query = query.filter(Signal.symbol == symbol)
        return query.order_by(Signal.timestamp.desc()).limit(limit).all()
    
    def get_by_signal_value(
        self,
        signal_value: int,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Signal]:
        """
        Get signals by signal value (buy/sell/neutral).
        
        Args:
            signal_value: 1 (buy), -1 (sell), or 0 (neutral)
            symbol: Optional symbol filter
            limit: Maximum number of signals
            
        Returns:
            List of Signal instances
        """
        query = self.session.query(Signal).filter(Signal.signal_value == signal_value)
        if symbol:
            query = query.filter(Signal.symbol == symbol)
        query = query.order_by(Signal.timestamp.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def get_by_date_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Signal]:
        """
        Get signals within a date range for a symbol.
        
        Args:
            symbol: Trading pair
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            
        Returns:
            List of Signal instances
        """
        return (
            self.session.query(Signal)
            .filter(
                Signal.symbol == symbol,
                Signal.timestamp >= start_date,
                Signal.timestamp <= end_date
            )
            .order_by(Signal.timestamp.asc())
            .all()
        )
    
    def get_signal_count(
        self,
        symbol: Optional[str] = None,
        signal_value: Optional[int] = None,
    ) -> int:
        """
        Count signals with optional filters.
        
        Args:
            symbol: Optional symbol filter
            signal_value: Optional signal value filter
            
        Returns:
            Number of signals
        """
        query = self.session.query(Signal)
        if symbol:
            query = query.filter(Signal.symbol == symbol)
        if signal_value is not None:
            query = query.filter(Signal.signal_value == signal_value)
        return query.count()

