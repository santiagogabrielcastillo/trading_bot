import pandas as pd
import numpy as np

from app.strategies.momentum_filters import MACDConfirmationFilter
from app.config.models import MomentumFilterConfig
from app.core.enums import Signal


def _build_df(prices: np.ndarray) -> pd.DataFrame:
    """Helper to build OHLCV DataFrame from closing prices."""
    return pd.DataFrame({
        'open': prices,
        'high': prices + 1,
        'low': prices - 1,
        'close': prices,
        'volume': np.full_like(prices, 1000, dtype=float),
    })


def test_macd_filter_buy_requires_positive_histogram():
    prices = np.linspace(100, 200, 200)
    df = _build_df(prices)
    filt = MACDConfirmationFilter(MomentumFilterConfig(macd_fast=12, macd_slow=26, macd_signal=9))
    
    signal_ok = filt.is_entry_valid(df, Signal.BUY)
    
    assert bool(signal_ok.iloc[-1]) is True
    assert bool(signal_ok.iloc[0]) is False  # warm-up should still be False


def test_macd_filter_sell_requires_negative_histogram():
    prices = np.linspace(200, 100, 200)
    df = _build_df(prices)
    filt = MACDConfirmationFilter(MomentumFilterConfig())
    
    signal_ok = filt.is_entry_valid(df, Signal.SELL)
    
    assert bool(signal_ok.iloc[-1]) is True
    assert signal_ok.dtype == bool
    assert bool(filt.is_entry_valid(df, Signal.BUY).iloc[-1]) is False


def test_macd_filter_reports_correct_lookback():
    config = MomentumFilterConfig(macd_fast=8, macd_slow=30, macd_signal=5)
    filt = MACDConfirmationFilter(config)
    
    assert filt.max_lookback_period == 35

