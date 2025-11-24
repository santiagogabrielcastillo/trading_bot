"""
Momentum confirmation filters (MACD-based) for trading strategies.

Provides a MACD histogram gate to confirm directional acceleration before
allowing entry signals to execute.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.interfaces import IMomentumFilter
from app.config.models import MomentumFilterConfig
from app.core.enums import Signal


@dataclass
class MACDComponents:
    """Simple container for MACD line, signal line, and histogram."""
    macd_line: pd.Series
    signal_line: pd.Series
    histogram: pd.Series


class MACDConfirmationFilter(IMomentumFilter):
    """
    MACD-based momentum confirmation filter.
    
    Confirms BUY entries only when MACD histogram > 0 (bullish acceleration) and
    SELL entries only when MACD histogram < 0 (bearish acceleration).
    """
    
    def __init__(self, config: MomentumFilterConfig):
        self.config = config
    
    @property
    def max_lookback_period(self) -> int:
        """
        MACD requires enough candles to stabilize both slow EMA and signal line.
        """
        return self.config.macd_slow + self.config.macd_signal
    
    def is_entry_valid(self, data: pd.DataFrame, direction: Signal) -> pd.Series:
        """
        Determine whether entries are valid based on MACD histogram sign.
        """
        if data.empty or 'close' not in data.columns:
            return pd.Series(False, index=data.index)
        
        macd = self._calculate_macd_components(data['close'])
        
        if direction == Signal.BUY:
            return (macd.histogram > 0).fillna(False)
        if direction == Signal.SELL:
            return (macd.histogram < 0).fillna(False)
        
        # Default to False for unsupported directions (e.g., HOLD)
        return pd.Series(False, index=data.index)
    
    def _calculate_macd_components(self, close: pd.Series) -> MACDComponents:
        """
        Calculate MACD line, signal line, and histogram using EMA.
        """
        macd_fast = close.ewm(span=self.config.macd_fast, adjust=False).mean()
        macd_slow = close.ewm(span=self.config.macd_slow, adjust=False).mean()
        macd_line = macd_fast - macd_slow
        signal_line = macd_line.ewm(span=self.config.macd_signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return MACDComponents(macd_line=macd_line, signal_line=signal_line, histogram=histogram)

