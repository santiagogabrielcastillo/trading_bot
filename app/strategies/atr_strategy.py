"""
Volatility-Adjusted Strategy using ATR (Average True Range).

This strategy enhances the basic SMA cross strategy by incorporating:
1. ATR-based volatility filtering to avoid low-volatility whipsaws
2. Dynamic stop-loss calculation based on market volatility
3. Risk-aware position sizing through ATR multiples

Architectural Impact:
- Signals now carry stop_loss_price in metadata
- Strategy becomes market-regime aware (adapts to volatility)
- Paves the way for dynamic risk management in TradingBot
"""
import numpy as np
import pandas as pd
from typing import Optional

from app.core.interfaces import BaseStrategy
from app.config.models import StrategyConfig


class VolatilityAdjustedStrategy(BaseStrategy):
    """
    Advanced trading strategy combining SMA Cross with ATR volatility filtering.
    
    Signal Generation Rules:
    - BUY: Fast SMA crosses above Slow SMA AND price shows sufficient volatility
    - SELL: Fast SMA crosses below Slow SMA
    - HOLD: No cross or insufficient volatility
    
    Risk Management:
    - Each BUY signal includes a calculated stop_loss_price = Entry - (ATR * multiplier)
    - Stop-loss adapts to current market volatility automatically
    
    Implementation:
    - 100% vectorized using pandas/numpy operations (NO for loops)
    - All parameters extracted from config (no magic numbers)
    - Follows the same interface as SmaCrossStrategy
    """
    
    def __init__(self, config: StrategyConfig):
        """
        Initialize the Volatility-Adjusted Strategy.
        
        Args:
            config: Strategy configuration containing params dict with:
                - fast_window: Fast SMA period (default: 10)
                - slow_window: Slow SMA period (default: 100)
                - atr_window: ATR calculation period (default: 14)
                - atr_multiplier: Stop-loss distance multiplier (default: 2.0)
                - volatility_lookback: Period for volatility check (default: 5)
        """
        super().__init__(config)
        
        # Extract parameters with safe defaults
        self.fast_window = config.params.get('fast_window', 10)
        self.slow_window = config.params.get('slow_window', 100)
        self.atr_window = config.params.get('atr_window', 14)
        self.atr_multiplier = config.params.get('atr_multiplier', 2.0)
        self.volatility_lookback = config.params.get('volatility_lookback', 5)
        
        # Validation
        if self.slow_window <= self.fast_window:
            raise ValueError(
                f"slow_window ({self.slow_window}) must be greater than "
                f"fast_window ({self.fast_window})"
            )
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators: SMA (fast/slow) and ATR.
        
        ATR (Average True Range) measures market volatility:
        - True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        - ATR = Rolling mean of True Range over atr_window periods
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            
        Returns:
            DataFrame with added columns: sma_fast, sma_slow, atr, stop_loss_price
        """
        # 1. Calculate SMAs (same as SmaCrossStrategy)
        df['sma_fast'] = df['close'].rolling(window=self.fast_window).mean()
        df['sma_slow'] = df['close'].rolling(window=self.slow_window).mean()
        
        # 2. Calculate True Range (vectorized)
        # TR = max(high-low, |high-prev_close|, |low-prev_close|)
        prev_close = df['close'].shift(1)
        
        tr1 = df['high'] - df['low']  # High - Low
        tr2 = (df['high'] - prev_close).abs()  # |High - Previous Close|
        tr3 = (df['low'] - prev_close).abs()  # |Low - Previous Close|
        
        # Take maximum of the three
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # 3. Calculate ATR (Average True Range)
        df['atr'] = true_range.rolling(window=self.atr_window).mean()
        
        # 4. Calculate dynamic stop-loss price (Entry - ATR * multiplier)
        # This will be used when BUY signal is generated
        df['stop_loss_price'] = df['close'] - (df['atr'] * self.atr_multiplier)
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals with volatility filtering.
        
        Signal Logic:
        1. Golden Cross (BUY):
           - Fast SMA crosses above Slow SMA (same as basic strategy)
           - AND price has moved significantly (volatility filter)
           - Volatility Check: price_change_over_N_bars > 1.0 * current_ATR
        
        2. Death Cross (SELL):
           - Fast SMA crosses below Slow SMA (no volatility filter on exits)
        
        3. HOLD (NEUTRAL):
           - No cross or cross fails volatility filter
        
        Args:
            df: DataFrame with indicators already calculated
            
        Returns:
            DataFrame with 'signal' column added:
                1 = BUY trigger
                -1 = SELL trigger
                0 = NEUTRAL/HOLD
        """
        # Initialize signal column
        df['signal'] = 0
        
        # --- Step 1: Detect SMA Crossovers (same as SmaCrossStrategy) ---
        
        prev_fast = df['sma_fast'].shift(1)
        prev_slow = df['sma_slow'].shift(1)
        curr_fast = df['sma_fast']
        curr_slow = df['sma_slow']
        
        # Golden Cross: Fast crosses above Slow
        golden_cross = (prev_fast <= prev_slow) & (curr_fast > curr_slow)
        
        # Death Cross: Fast crosses below Slow
        death_cross = (prev_fast >= prev_slow) & (curr_fast < curr_slow)
        
        # --- Step 2: Apply Volatility Filter for BUY signals ---
        
        # Calculate price change over lookback period
        price_change = df['close'] - df['close'].shift(self.volatility_lookback)
        
        # Volatility threshold: price must have moved at least 1.0 * ATR
        # This filters out low-volatility whipsaws
        volatility_threshold = 1.0 * df['atr']
        
        # Volatility condition: price movement exceeds threshold
        has_volatility = price_change.abs() >= volatility_threshold
        
        # --- Step 3: Combine conditions ---
        
        # BUY: Golden Cross AND sufficient volatility
        buy_condition = golden_cross & has_volatility
        
        # SELL: Death Cross (no volatility filter on exits for safety)
        sell_condition = death_cross
        
        # --- Step 4: Assign signals (vectorized) ---
        
        df['signal'] = np.where(
            buy_condition,
            1,  # BUY
            np.where(sell_condition, -1, 0)  # SELL or NEUTRAL
        )
        
        # Clean up: Fill NaN values (from rolling/shift) with 0
        df['signal'] = df['signal'].fillna(0).astype(int)
        
        return df
    
    def get_stop_loss_price(self, df: pd.DataFrame, index: Optional[int] = None) -> Optional[float]:
        """
        Get the stop-loss price for a given index (or latest bar).
        
        This is a utility method to extract stop-loss prices for use by
        the TradingBot or BacktestingEngine.
        
        Args:
            df: DataFrame with indicators calculated
            index: Row index (default: -1, last row)
            
        Returns:
            Stop-loss price as float, or None if not available
        """
        if 'stop_loss_price' not in df.columns:
            return None
        
        if index is None:
            index = -1
        
        try:
            sl_price = float(df['stop_loss_price'].iloc[index])
            return sl_price if not pd.isna(sl_price) else None
        except (IndexError, KeyError):
            return None
    
    def get_required_warmup_periods(self) -> int:
        """
        Calculate the minimum number of periods required for indicator warmup.
        
        This is the maximum of all window sizes to ensure no NaN values
        in the calculation period.
        
        Returns:
            Number of periods needed for warmup
        """
        return max(
            self.slow_window,
            self.atr_window,
            self.volatility_lookback
        )

