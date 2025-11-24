"""
Bollinger Band Mean Reversion Strategy.

This strategy pivots from trend-following (EMA Cross) to mean reversion,
using Bollinger Bands to detect price over-extension conditions.

Signal Logic:
- LONG Trigger: Price crosses below Lower Bollinger Band (oversold condition)
- SHORT Trigger: Price crosses above Upper Bollinger Band (overbought condition)
- Filtering: Maintains triple-layer filtering (ADX Regime + MACD Momentum)
- Risk Management: Inherits ATR/Max Hold period from base architecture

Architectural Design:
- Inherits existing filter architecture (regime_filter, momentum_filter)
- Supports long_only mode for diagnostic purposes
- 100% vectorized calculations (no for loops)
- All parameters extracted from config (no magic numbers)
"""
import numpy as np
import pandas as pd
from typing import Optional

from app.core.interfaces import BaseStrategy, IMarketRegimeFilter, IMomentumFilter
from app.core.enums import MarketState, Signal
from app.config.models import StrategyConfig


class BollingerBandStrategy(BaseStrategy):
    """
    Mean reversion strategy using Bollinger Bands for entry signals.
    
    Bollinger Bands consist of:
    - Middle Band: Simple Moving Average of close prices (bb_window periods)
    - Upper Band: Middle + (bb_std_dev * standard deviation)
    - Lower Band: Middle - (bb_std_dev * standard deviation)
    
    Signal Generation Rules:
    - BUY: Price crosses below Lower Band (oversold, expect bounce back to mean)
    - SELL: Price crosses above Upper Band (overbought, expect pullback to mean)
    - HOLD: Price within bands or filters block the signal
    
    Filtering:
    - Regime Filter: Only trade in favorable market conditions
    - Momentum Filter: Confirm acceleration in entry direction
    
    Implementation:
    - 100% vectorized using pandas/numpy operations (NO for loops)
    - All parameters extracted from config (no magic numbers)
    - Follows the same interface as VolatilityAdjustedStrategy
    """
    
    def __init__(
        self,
        config: StrategyConfig,
        regime_filter: Optional[IMarketRegimeFilter] = None,
        momentum_filter: Optional[IMomentumFilter] = None,
    ):
        """
        Initialize the Bollinger Band Mean Reversion Strategy.
        
        Args:
            config: Strategy configuration containing params dict with:
                - bb_window: Bollinger Band window period (default: 20)
                - bb_std_dev: Standard deviation multiplier (default: 2.0)
            regime_filter: Optional market regime filter for context-aware signal generation
            momentum_filter: Optional momentum confirmation filter
        """
        super().__init__(config, regime_filter, momentum_filter)
        
        # Extract parameters with safe defaults
        self.bb_window = config.params.get('bb_window', 20)
        self.bb_std_dev = config.params.get('bb_std_dev', 2.0)
        
        # Validation
        if self.bb_window <= 0:
            raise ValueError(f"bb_window ({self.bb_window}) must be greater than 0")
        if self.bb_std_dev <= 0:
            raise ValueError(f"bb_std_dev ({self.bb_std_dev}) must be greater than 0")
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Bollinger Bands indicators.
        
        Bollinger Bands Calculation:
        1. Middle Band = SMA(close, bb_window)
        2. Standard Deviation = std(close, bb_window)
        3. Upper Band = Middle + (bb_std_dev * std)
        4. Lower Band = Middle - (bb_std_dev * std)
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            
        Returns:
            DataFrame with added columns: bb_middle, bb_upper, bb_lower, bb_std
        """
        # Calculate Middle Band (SMA of close prices)
        df['bb_middle'] = df['close'].rolling(window=self.bb_window).mean()
        
        # Calculate rolling standard deviation
        df['bb_std'] = df['close'].rolling(window=self.bb_window).std()
        
        # Calculate Upper and Lower Bands
        df['bb_upper'] = df['bb_middle'] + (self.bb_std_dev * df['bb_std'])
        df['bb_lower'] = df['bb_middle'] - (self.bb_std_dev * df['bb_std'])
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate mean reversion trading signals based on Bollinger Band crossovers.
        
        Signal Logic:
        1. LONG Trigger:
           - Current close crosses below Lower Band (oversold condition)
           - Expect price to revert back toward the middle band
           - AND market regime is favorable (if regime filter is enabled)
           - AND momentum confirms (if momentum filter is enabled)
        
        2. SHORT Trigger:
           - Current close crosses above Upper Band (overbought condition)
           - Expect price to revert back toward the middle band
           - AND market regime is favorable (if regime filter is enabled)
           - AND momentum confirms (if momentum filter is enabled)
        
        3. HOLD (NEUTRAL):
           - Price within bands
           - Or filters block the signal
        
        Args:
            df: DataFrame with indicators already calculated (must include bb_upper, bb_lower, bb_middle)
            
        Returns:
            DataFrame with 'signal' column added:
                1 = BUY trigger (oversold reversal)
                -1 = SELL trigger (overbought reversal)
                0 = NEUTRAL/HOLD
        """
        # Initialize signal column
        df['signal'] = 0
        
        # Validate required columns exist
        required_cols = ['bb_upper', 'bb_lower', 'close']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column '{col}' in DataFrame. Ensure calculate_indicators() was called first.")
        
        # --- Step 1: Detect Bollinger Band Crossovers (vectorized) ---
        
        prev_close = df['close'].shift(1)
        curr_close = df['close']
        
        prev_bb_lower = df['bb_lower'].shift(1)
        curr_bb_lower = df['bb_lower']
        
        prev_bb_upper = df['bb_upper'].shift(1)
        curr_bb_upper = df['bb_upper']
        
        # LONG Trigger: Price crosses below Lower Band (oversold)
        # Previous bar: close >= lower_band, Current bar: close < lower_band
        long_trigger = (prev_close >= prev_bb_lower) & (curr_close < curr_bb_lower)
        
        # SHORT Trigger: Price crosses above Upper Band (overbought)
        # Previous bar: close <= upper_band, Current bar: close > upper_band
        short_trigger = (prev_close <= prev_bb_upper) & (curr_close > curr_bb_upper)
        
        # --- Step 2: Apply Market Regime Filter (if available) ---
        
        # Get market regime classification if filter is available
        regime_filter_active = True
        if self.regime_filter is not None:
            try:
                regime_series = self.regime_filter.get_regime(df)
                # For mean reversion:
                # - LONG: Prefer RANGING or TRENDING_UP (oversold bounce in trending up is good)
                # - SHORT: Prefer RANGING or TRENDING_DOWN (overbought pullback in trending down is good)
                # But we want to avoid strong trends in opposite direction
                # LONG is safer in TRENDING_UP or RANGING (avoid TRENDING_DOWN)
                buy_regime_ok = (regime_series == MarketState.TRENDING_UP) | (regime_series == MarketState.RANGING)
                # SHORT is safer in TRENDING_DOWN or RANGING (avoid TRENDING_UP)
                sell_regime_ok = (regime_series == MarketState.TRENDING_DOWN) | (regime_series == MarketState.RANGING)
            except Exception:
                # If regime filter fails, disable it and log warning
                regime_filter_active = False
                buy_regime_ok = pd.Series(True, index=df.index)
                sell_regime_ok = pd.Series(True, index=df.index)
        else:
            # No regime filter: allow all signals
            buy_regime_ok = pd.Series(True, index=df.index)
            sell_regime_ok = pd.Series(True, index=df.index)
        
        # --- Step 3: Apply Momentum Filter (if available) ---
        
        if self.momentum_filter is not None:
            try:
                momentum_buy_ok = self.momentum_filter.is_entry_valid(df, Signal.BUY)
                momentum_sell_ok = self.momentum_filter.is_entry_valid(df, Signal.SELL)
            except Exception:
                momentum_buy_ok = pd.Series(True, index=df.index)
                momentum_sell_ok = pd.Series(True, index=df.index)
        else:
            momentum_buy_ok = pd.Series(True, index=df.index)
            momentum_sell_ok = pd.Series(True, index=df.index)
        
        # --- Step 4: Combine conditions ---
        
        # BUY: Price crosses below Lower Band AND favorable regime AND momentum confirms
        buy_condition = long_trigger
        if regime_filter_active and self.regime_filter is not None:
            buy_condition = buy_condition & buy_regime_ok
        buy_condition = buy_condition & momentum_buy_ok
        
        # SELL: Price crosses above Upper Band AND favorable regime AND momentum confirms
        sell_condition = short_trigger
        if regime_filter_active and self.regime_filter is not None:
            sell_condition = sell_condition & sell_regime_ok
        sell_condition = sell_condition & momentum_sell_ok
        
        # --- Step 5: Assign signals (vectorized) ---
        
        df['signal'] = np.where(
            buy_condition,
            1,  # BUY
            np.where(sell_condition, -1, 0)  # SELL or NEUTRAL
        )
        
        # --- Step 6: Apply Long-Only Symmetry Blockade (if enabled) ---
        
        # If long_only is True, convert all SELL signals to NEUTRAL
        # This isolates LONG signal performance from failed SHORT trades
        if self.config.long_only:
            df['signal'] = np.where(df['signal'] == -1, 0, df['signal'])
        
        # Clean up: Fill NaN values (from rolling/shift) with 0
        df['signal'] = df['signal'].fillna(0).astype(int)
        
        return df
    
    @property
    def max_lookback_period(self) -> int:
        """
        Return the maximum lookback period required by all strategy indicators.
        
        For BollingerBandStrategy, this is the maximum of:
        - bb_window (for SMA and std calculation)
        - filter's max_lookback_period (if filter is present)
        
        Returns:
            Number of periods needed for indicator warm-up
        """
        # Get strategy-specific lookback (BB window for SMA and std)
        strategy_lookback = self.bb_window
        
        lookbacks = [strategy_lookback]
        if self.regime_filter is not None:
            lookbacks.append(self.regime_filter.max_lookback_period)
        if self.momentum_filter is not None:
            lookbacks.append(self.momentum_filter.max_lookback_period)
        
        return max(lookbacks)

