"""
Market Regime Filter Module

This module implements market regime classification filters that enable
context-aware signal generation. Strategies can use these filters to avoid
trading during unfavorable market conditions (e.g., ranging markets).

The primary implementation uses ADX (Average Directional Index) and DMI
(Directional Movement Index) to classify market states as:
- TRENDING_UP: Strong uptrend (favorable for long positions)
- TRENDING_DOWN: Strong downtrend (favorable for short positions)
- RANGING: Sideways market (unfavorable for trend-following strategies)
"""
import numpy as np
import pandas as pd

from app.core.interfaces import IMarketRegimeFilter
from app.core.enums import MarketState
from app.config.models import RegimeFilterConfig


class ADXVolatilityFilter(IMarketRegimeFilter):
    """
    ADX-based market regime filter.
    
    Uses ADX (Average Directional Index) and DMI (Directional Movement Index)
    to classify market conditions:
    - High ADX (> threshold) + DI+ > DI- → TRENDING_UP
    - High ADX (> threshold) + DI- > DI+ → TRENDING_DOWN
    - Low ADX (<= threshold) → RANGING
    
    This filter enables strategies to avoid trading during ranging markets
    where trend-following strategies typically underperform.
    
    Implementation:
    - 100% vectorized using pandas/numpy operations (NO for loops)
    - All parameters extracted from config (no magic numbers)
    """
    
    def __init__(self, config: RegimeFilterConfig):
        """
        Initialize ADX-based market regime filter.
        
        Args:
            config: Filter configuration with adx_window and adx_threshold
        """
        self.config = config
        self.adx_window = config.adx_window
        self.adx_threshold = config.adx_threshold
    
    @property
    def max_lookback_period(self) -> int:
        """
        Return the maximum lookback period required by all filter indicators.
        
        For ADX/DMI calculation:
        - First smoothed values (ATR, +DM, -DM) need adx_window periods
        - ADX calculation starts at 2 * adx_window - 2 (needs two smoothed periods)
        - Full ADX/DMI values available after 2 * adx_window periods
        
        Returns:
            Number of periods needed for indicator warm-up (2 * adx_window)
        """
        # ADX requires: adx_window for smoothed TR/DM, then another adx_window for smoothed DX
        # First valid ADX value appears at index: 2 * adx_window - 2
        # To be safe, we use 2 * adx_window as the lookback
        return 2 * self.adx_window
    
    def get_regime(self, data: pd.DataFrame) -> pd.Series:
        """
        Classify market regime for each row using ADX and DMI indicators.
        
        Classification Rules:
        - TRENDING_UP: ADX > threshold AND +DI > -DI
        - TRENDING_DOWN: ADX > threshold AND -DI > +DI
        - RANGING: ADX <= threshold (weak trend, sideways market)
        
        Args:
            data: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            
        Returns:
            Series of MarketState enum values with same index as input DataFrame
        """
        # Calculate ADX and DMI indicators
        df = self._calculate_adx_dmi(data.copy())
        
        # Extract indicators
        adx = df['ADX']
        di_plus = df['+DI']
        di_minus = df['-DI']
        
        # Initialize regime series with default RANGING state
        regime = pd.Series(
            MarketState.RANGING,
            index=data.index,
            name='market_regime',
            dtype="object"
        )
        
        # TRENDING_UP: Strong trend (ADX > threshold) AND upward direction (+DI > -DI)
        trending_up = (adx > self.adx_threshold) & (di_plus > di_minus)
        
        # TRENDING_DOWN: Strong trend (ADX > threshold) AND downward direction (-DI > +DI)
        trending_down = (adx > self.adx_threshold) & (di_minus > di_plus)
        
        # Assign regime values (vectorized)
        regime.loc[trending_up] = MarketState.TRENDING_UP
        regime.loc[trending_down] = MarketState.TRENDING_DOWN
        
        return regime
    
    def _calculate_adx_dmi(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate ADX and DMI indicators using vectorized operations.
        
        ADX (Average Directional Index) measures trend strength:
        - High ADX (>25): Strong trend
        - Low ADX (<20): Weak trend or ranging market
        
        DMI (Directional Movement Index) measures trend direction:
        - +DI: Positive Directional Indicator (uptrend strength)
        - -DI: Negative Directional Indicator (downtrend strength)
        
        Calculation Steps (vectorized):
        1. Calculate True Range (TR)
        2. Calculate Directional Movement (+DM and -DM)
        3. Smooth TR and DM using Wilder's smoothing
        4. Calculate Directional Indicators (+DI and -DI)
        5. Calculate ADX from smoothed DI values
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            DataFrame with added columns: +DI, -DI, ADX
        """
        # Step 1: Calculate True Range (TR)
        # TR = max(high-low, |high-prev_close|, |low-prev_close|)
        prev_close = data['close'].shift(1)
        
        tr1 = data['high'] - data['low']  # High - Low
        tr2 = (data['high'] - prev_close).abs()  # |High - Previous Close|
        tr3 = (data['low'] - prev_close).abs()  # |Low - Previous Close|
        
        # Take maximum of the three (vectorized)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Step 2: Calculate Directional Movement (+DM and -DM)
        # +DM = high - prev_high if (high - prev_high) > (prev_low - low) else 0
        # -DM = prev_low - low if (prev_low - low) > (high - prev_high) else 0
        prev_high = data['high'].shift(1)
        prev_low = data['low'].shift(1)
        
        up_move = data['high'] - prev_high
        down_move = prev_low - data['low']
        
        # +DM: Upward movement is positive and greater than downward movement
        plus_dm = np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0.0
        )
        
        # -DM: Downward movement is positive and greater than upward movement
        minus_dm = np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0.0
        )
        
        # Step 3: Smooth TR and DM using Wilder's smoothing (vectorized via EWM)
        def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
            return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        
        atr = _wilder_smooth(tr, self.adx_window)
        smoothed_plus_dm = _wilder_smooth(pd.Series(plus_dm, index=data.index), self.adx_window)
        smoothed_minus_dm = _wilder_smooth(pd.Series(minus_dm, index=data.index), self.adx_window)
        
        # Step 4: Calculate Directional Indicators (+DI and -DI)
        atr_safe = atr.replace(0, np.nan)
        di_plus = 100 * (smoothed_plus_dm / atr_safe)
        di_minus = 100 * (smoothed_minus_dm / atr_safe)
        
        # Step 5: Calculate DX and ADX (0-100 range)
        di_sum = (di_plus + di_minus).replace(0, np.nan)
        di_diff = (di_plus - di_minus).abs()
        dx = 100 * (di_diff / di_sum)
        adx = _wilder_smooth(dx, self.adx_window)
        
        # Normalize indicator ranges and replace NaNs from warm-up
        di_plus = di_plus.clip(lower=0, upper=100).fillna(0)
        di_minus = di_minus.clip(lower=0, upper=100).fillna(0)
        adx = adx.clip(lower=0, upper=100).fillna(0)
        
        # Add columns to DataFrame
        data['+DI'] = di_plus
        data['-DI'] = di_minus
        data['ADX'] = adx
        
        return data

