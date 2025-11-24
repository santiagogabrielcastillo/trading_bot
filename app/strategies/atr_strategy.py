"""
Volatility-Adjusted Strategy using ATR (Average True Range).

This strategy enhances the basic EMA cross strategy by incorporating:
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

from app.core.interfaces import BaseStrategy, IMarketRegimeFilter, IMomentumFilter
from app.core.enums import MarketState, Signal
from app.config.models import StrategyConfig


class VolatilityAdjustedStrategy(BaseStrategy):
    """
    Advanced trading strategy combining EMA Cross with ATR volatility filtering.
    
    Signal Generation Rules:
    - BUY: Fast EMA crosses above Slow EMA AND price shows sufficient volatility
    - SELL: Fast EMA crosses below Slow EMA
    - HOLD: No cross or insufficient volatility
    
    Risk Management:
    - Each BUY signal includes a calculated stop_loss_price = Entry - (ATR * multiplier)
    - Stop-loss adapts to current market volatility automatically
    
    Implementation:
    - 100% vectorized using pandas/numpy operations (NO for loops)
    - All parameters extracted from config (no magic numbers)
    - Follows the same interface as SmaCrossStrategy
    """
    
    def __init__(
        self,
        config: StrategyConfig,
        regime_filter: Optional[IMarketRegimeFilter] = None,
        momentum_filter: Optional[IMomentumFilter] = None,
    ):
        """
        Initialize the Volatility-Adjusted Strategy.
        
        Args:
            config: Strategy configuration containing params dict with:
                - fast_window: Fast EMA period (default: 10)
                - slow_window: Slow EMA period (default: 100)
                - atr_window: ATR calculation period (default: 14)
                - atr_multiplier: Stop-loss distance multiplier (default: 2.0)
                - volatility_lookback: Period for volatility check (default: 5)
            regime_filter: Optional market regime filter for context-aware signal generation
        """
        super().__init__(config, regime_filter, momentum_filter)
        
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
        Calculate all technical indicators: EMA (fast/slow) and ATR.
        
        ATR (Average True Range) measures market volatility:
        - True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        - ATR = Rolling mean of True Range over atr_window periods
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            
        Returns:
            DataFrame with added columns: ema_fast, ema_slow, atr, stop_loss_price
        """
        # 1. Calculate EMAs (same as SmaCrossStrategy, now EMA-based)
        df['ema_fast'] = df['close'].ewm(span=self.fast_window, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.slow_window, adjust=False).mean()
        
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
        Generate trading signals with volatility filtering and market regime awareness.
        
        Signal Logic:
        1. Golden Cross (BUY):
           - Fast EMA crosses above Slow EMA (same as basic strategy)
           - AND price has moved significantly (volatility filter)
           - AND market regime is TRENDING_UP (if regime filter is enabled)
           - Volatility Check: price_change_over_N_bars > 1.0 * current_ATR
        
        2. Death Cross (SELL):
           - Fast EMA crosses below Slow EMA
           - AND market regime is TRENDING_DOWN (if regime filter is enabled)
           - Note: Exit signals (SL/TP) are NOT filtered by regime (handled by engine/bot)
        
        3. HOLD (NEUTRAL):
           - No cross or cross fails volatility/regime filter
        
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
        
        # --- Step 1: Detect EMA Crossovers (same as SmaCrossStrategy) ---
        
        prev_fast = df['ema_fast'].shift(1)
        prev_slow = df['ema_slow'].shift(1)
        curr_fast = df['ema_fast']
        curr_slow = df['ema_slow']
        
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
        
        # --- Step 3: Apply Market Regime Filter (if available) ---
        
        # Get market regime classification if filter is available
        regime_filter_active = True
        if self.regime_filter is not None:
            try:
                regime_series = self.regime_filter.get_regime(df)
                # Filter BUY signals: only allow in TRENDING_UP regime
                buy_regime_ok = (regime_series == MarketState.TRENDING_UP)
                # Filter SELL entry signals: only allow in TRENDING_DOWN regime
                sell_regime_ok = (regime_series == MarketState.TRENDING_DOWN)
            except Exception:
                # If regime filter fails, disable it and log warning
                regime_filter_active = False
                buy_regime_ok = pd.Series(True, index=df.index)
                sell_regime_ok = pd.Series(True, index=df.index)
        else:
            # No regime filter: allow all signals
            buy_regime_ok = pd.Series(True, index=df.index)
            sell_regime_ok = pd.Series(True, index=df.index)
        
        # --- Step 4: Apply Momentum Filter (if available) ---
        
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
        
        # --- Step 5: Combine conditions ---
        
        # BUY: Golden Cross AND sufficient volatility AND favorable regime (if filter active)
        buy_condition = golden_cross & has_volatility
        if regime_filter_active and self.regime_filter is not None:
            buy_condition = buy_condition & buy_regime_ok
        buy_condition = buy_condition & momentum_buy_ok
        
        # SELL: Death Cross AND favorable regime (if filter active)
        # Note: Exit signals (SL/TP) are handled by backtesting engine/trading bot,
        # not filtered here. This only filters entry SELL signals.
        sell_condition = death_cross
        if regime_filter_active and self.regime_filter is not None:
            sell_condition = sell_condition & sell_regime_ok
        sell_condition = sell_condition & momentum_sell_ok
        
        # --- Step 6: Assign signals (vectorized) ---
        
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
    
    @property
    def max_lookback_period(self) -> int:
        """
        Return the maximum lookback period required by all strategy indicators.
        
        For VolatilityAdjustedStrategy, this is the maximum of:
        - fast_window
        - slow_window
        - atr_window
        - volatility_lookback
        - filter's max_lookback_period (if filter is present)
        
        Returns:
            Number of periods needed for indicator warm-up
        """
        # Get strategy-specific lookback (max of all strategy windows)
        strategy_lookback = max(
            self.fast_window,
            self.slow_window,
            self.atr_window,
            self.volatility_lookback
        )
        
        lookbacks = [strategy_lookback]
        if self.regime_filter is not None:
            lookbacks.append(self.regime_filter.max_lookback_period)
        if self.momentum_filter is not None:
            lookbacks.append(self.momentum_filter.max_lookback_period)
        
        return max(lookbacks)
    
    def get_required_warmup_periods(self) -> int:
        """
        DEPRECATED: Use max_lookback_period property instead.
        
        This method is kept for backward compatibility but now delegates
        to the max_lookback_period property.
        
        Returns:
            Number of periods needed for warmup
        """
        return self.max_lookback_period

