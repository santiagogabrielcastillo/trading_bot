"""
Repository for Trade model data access.
"""
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.sql import Trade
from app.repositories.base import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    """
    Repository for managing Trade records.
    
    Provides specialized queries for trade history, PnL tracking,
    and symbol-specific trade retrieval.
    """
    
    def __init__(self, session: Session):
        """Initialize with Trade model and session."""
        super().__init__(Trade, session)
    
    def get_by_symbol(self, symbol: str, limit: Optional[int] = None) -> List[Trade]:
        """
        Get all trades for a specific symbol.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            limit: Maximum number of trades to return
            
        Returns:
            List of Trade instances ordered by timestamp
        """
        query = self.session.query(Trade).filter(Trade.symbol == symbol).order_by(Trade.timestamp.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def get_latest(self, symbol: Optional[str] = None, limit: int = 10) -> List[Trade]:
        """
        Get the most recent trades.
        
        Args:
            symbol: Optional symbol filter
            limit: Maximum number of trades
            
        Returns:
            List of Trade instances ordered by timestamp (most recent first)
        """
        query = self.session.query(Trade)
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        return query.order_by(Trade.timestamp.desc()).limit(limit).all()
    
    def get_by_date_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Trade]:
        """
        Get trades within a date range for a symbol.
        
        Args:
            symbol: Trading pair
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            
        Returns:
            List of Trade instances
        """
        return (
            self.session.query(Trade)
            .filter(
                Trade.symbol == symbol,
                Trade.timestamp >= start_date,
                Trade.timestamp <= end_date
            )
            .order_by(Trade.timestamp.asc())
            .all()
        )
    
    def get_total_pnl(self, symbol: Optional[str] = None) -> float:
        """
        Calculate total realized PnL.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Total PnL (sum of all trade PnLs)
        """
        from sqlalchemy import func
        
        query = self.session.query(func.sum(Trade.pnl))
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        
        result = query.scalar()
        return float(result) if result else 0.0
    
    def get_trade_count(self, symbol: Optional[str] = None) -> int:
        """
        Count total number of trades.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Number of trades
        """
        query = self.session.query(Trade)
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        return query.count()

