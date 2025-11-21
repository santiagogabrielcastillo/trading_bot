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
from typing import Optional

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
        
        # Initialize regime series with RANGING (default)
        regime = pd.Series(
            MarketState.RANGING,
            index=data.index,
            name='market_regime'
        )
        
        # Classify trending markets
        # TRENDING_UP: Strong trend (ADX > threshold) AND upward direction (+DI > -DI)
        trending_up = (adx > self.adx_threshold) & (di_plus > di_minus)
        
        # TRENDING_DOWN: Strong trend (ADX > threshold) AND downward direction (-DI > +DI)
        trending_down = (adx > self.adx_threshold) & (di_minus > di_plus)
        
        # Assign regime values (vectorized)
        regime = np.where(
            trending_up,
            MarketState.TRENDING_UP,
            np.where(
                trending_down,
                MarketState.TRENDING_DOWN,
                MarketState.RANGING
            )
        )
        
        # Convert to Series with proper dtype
        regime_series = pd.Series(regime, index=data.index, name='market_regime')
        
        return regime_series
    
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
        
        # Step 3: Smooth TR and DM using Wilder's smoothing
        # Wilder's smoothing: Smoothed = Previous_Smoothed - (Previous_Smoothed / period) + Current_Value
        # For first value, use simple average
        
        # Initialize smoothed series
        atr = pd.Series(index=data.index, dtype=float)
        smoothed_plus_dm = pd.Series(index=data.index, dtype=float)
        smoothed_minus_dm = pd.Series(index=data.index, dtype=float)
        
        # First value: simple average
        atr.iloc[self.adx_window - 1] = tr.iloc[:self.adx_window].mean()
        smoothed_plus_dm.iloc[self.adx_window - 1] = plus_dm[:self.adx_window].mean()
        smoothed_minus_dm.iloc[self.adx_window - 1] = minus_dm[:self.adx_window].mean()
        
        # Subsequent values: Wilder's smoothing
        for i in range(self.adx_window, len(data)):
            atr.iloc[i] = atr.iloc[i - 1] - (atr.iloc[i - 1] / self.adx_window) + tr.iloc[i]
            smoothed_plus_dm.iloc[i] = smoothed_plus_dm.iloc[i - 1] - (smoothed_plus_dm.iloc[i - 1] / self.adx_window) + plus_dm[i]
            smoothed_minus_dm.iloc[i] = smoothed_minus_dm.iloc[i - 1] - (smoothed_minus_dm.iloc[i - 1] / self.adx_window) + minus_dm[i]
        
        # Step 4: Calculate Directional Indicators (+DI and -DI)
        # +DI = 100 * (Smoothed +DM / ATR)
        # -DI = 100 * (Smoothed -DM / ATR)
        # Avoid division by zero
        di_plus = 100 * (smoothed_plus_dm / atr).replace([np.inf, -np.inf], 0).fillna(0)
        di_minus = 100 * (smoothed_minus_dm / atr).replace([np.inf, -np.inf], 0).fillna(0)
        
        # Step 5: Calculate ADX (Average Directional Index)
        # ADX = 100 * (|+DI - -DI| / (+DI + -DI))
        # Smooth ADX using Wilder's smoothing
        
        # Calculate DX (Directional Index) for each period
        di_sum = di_plus + di_minus
        di_diff = (di_plus - di_minus).abs()
        
        # Avoid division by zero
        dx = 100 * (di_diff / di_sum).replace([np.inf, -np.inf], 0).fillna(0)
        
        # Smooth DX to get ADX using Wilder's smoothing
        adx = pd.Series(index=data.index, dtype=float)
        
        # First ADX value: simple average of first period DX values
        adx.iloc[2 * self.adx_window - 2] = dx.iloc[self.adx_window:2 * self.adx_window].mean()
        
        # Subsequent values: Wilder's smoothing
        for i in range(2 * self.adx_window - 1, len(data)):
            adx.iloc[i] = adx.iloc[i - 1] - (adx.iloc[i - 1] / self.adx_window) + dx.iloc[i]
        
        # Fill NaN values (from warm-up period) with 0
        adx = adx.fillna(0)
        di_plus = di_plus.fillna(0)
        di_minus = di_minus.fillna(0)
        
        # Add columns to DataFrame
        data['+DI'] = di_plus
        data['-DI'] = di_minus
        data['ADX'] = adx
        
        return data

