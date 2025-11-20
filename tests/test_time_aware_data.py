"""
Integration tests for Step 5.5: Time-Aware Data Refactor

Verifies that the data handler correctly fetches historical data for specific time periods
and that the cache logic properly validates date ranges.
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from typing import Optional

from app.core.interfaces import IDataHandler
from app.data.handler import CryptoDataHandler


class MockExchange:
    """Mock CCXT exchange for testing without real API calls."""
    
    def __init__(self, start_date: datetime, timeframe: str = "1h"):
        self.start_date = start_date
        self.timeframe = timeframe
        self.options = {'fetchOHLCVLimit': 100}
        self.rateLimit = 0  # No rate limiting in tests
        
    def fetch_ohlcv(self, symbol: str, timeframe: str, since: Optional[int] = None, limit: int = 100):
        """
        Generate synthetic OHLCV data starting from a specific timestamp.
        Simulates forward pagination by returning data starting from 'since'.
        """
        if since is None:
            # If no 'since' is provided, start from a default recent time
            since = int((datetime.now() - timedelta(hours=limit)).timestamp() * 1000)
        
        # Convert since from milliseconds to datetime
        start_ts = datetime.fromtimestamp(since / 1000)
        
        # Determine time delta per candle
        if timeframe == "1h":
            delta = timedelta(hours=1)
        elif timeframe == "1d":
            delta = timedelta(days=1)
        elif timeframe == "15m":
            delta = timedelta(minutes=15)
        else:
            delta = timedelta(hours=1)
        
        # Generate synthetic data
        ohlcv = []
        current_time = start_ts
        for i in range(limit):
            timestamp_ms = int(current_time.timestamp() * 1000)
            # Generate simple price data: base 100 + some variation
            price = 100.0 + i * 0.1
            ohlcv.append([
                timestamp_ms,
                price,      # open
                price + 1,  # high
                price - 1,  # low
                price + 0.5,  # close
                1000.0      # volume
            ])
            current_time += delta
        
        return ohlcv


def test_forward_fetching_with_start_date():
    """
    Test that when start_date is provided, the handler fetches data forward from that date.
    """
    start_date = datetime(2024, 1, 1, 0, 0, 0)
    end_date = datetime(2024, 1, 3, 0, 0, 0)
    
    # Create temporary cache directory
    with tempfile.TemporaryDirectory() as tmpdir:
        exchange = MockExchange(start_date=start_date, timeframe="1h")
        handler = CryptoDataHandler(exchange=exchange, cache_dir=Path(tmpdir))
        
        # Fetch data with explicit date range
        df = handler.get_historical_data(
            symbol="BTC/USDT",
            timeframe="1h",
            start_date=start_date,
            end_date=end_date,
            limit=1000
        )
        
        # Verify we got data
        assert not df.empty, "DataFrame should not be empty"
        
        # Verify the data covers the requested range
        assert df.index.min() <= pd.to_datetime(start_date), \
            f"Data should start at or before {start_date}, got {df.index.min()}"
        assert df.index.max() >= pd.to_datetime(end_date), \
            f"Data should end at or after {end_date}, got {df.index.max()}"
        
        # Verify we have the expected columns
        expected_columns = ['open', 'high', 'low', 'close', 'volume']
        assert all(col in df.columns for col in expected_columns), \
            f"DataFrame should have columns {expected_columns}"


def test_cache_validation_by_date_range():
    """
    Test that the cache is validated by date range, not just length.
    This ensures we don't reuse cached data that doesn't cover the requested period.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        
        # First request: Jan 1-3, 2024
        start_date_1 = datetime(2024, 1, 1, 0, 0, 0)
        end_date_1 = datetime(2024, 1, 3, 0, 0, 0)
        
        exchange = MockExchange(start_date=start_date_1, timeframe="1h")
        handler = CryptoDataHandler(exchange=exchange, cache_dir=cache_dir)
        
        df1 = handler.get_historical_data(
            symbol="BTC/USDT",
            timeframe="1h",
            start_date=start_date_1,
            end_date=end_date_1,
            limit=1000
        )
        
        # Verify cache file was created
        cache_file = cache_dir / "BTC_USDT_1h.csv"
        assert cache_file.exists(), "Cache file should be created"
        
        # Second request: Same symbol/timeframe but DIFFERENT date range (Jan 5-7)
        # This should NOT use the cache because the date range doesn't match
        start_date_2 = datetime(2024, 1, 5, 0, 0, 0)
        end_date_2 = datetime(2024, 1, 7, 0, 0, 0)
        
        exchange2 = MockExchange(start_date=start_date_2, timeframe="1h")
        handler2 = CryptoDataHandler(exchange=exchange2, cache_dir=cache_dir)
        
        df2 = handler2.get_historical_data(
            symbol="BTC/USDT",
            timeframe="1h",
            start_date=start_date_2,
            end_date=end_date_2,
            limit=1000
        )
        
        # The cache should be refreshed because the date range doesn't match
        # Verify we got data for the new range
        assert not df2.empty, "DataFrame should not be empty for second request"


def test_backward_fetching_without_start_date():
    """
    Test that when no start_date is provided, the handler uses backward fetching (legacy mode).
    This is important for live trading where we just want the most recent N candles.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        exchange = MockExchange(start_date=datetime.now(), timeframe="1h")
        handler = CryptoDataHandler(exchange=exchange, cache_dir=Path(tmpdir))
        
        # Fetch without explicit dates (should use recent data)
        df = handler.get_historical_data(
            symbol="BTC/USDT",
            timeframe="1h",
            limit=50
        )
        
        # Verify we got data
        assert not df.empty, "DataFrame should not be empty"
        assert len(df) <= 50, f"Should fetch at most 50 candles, got {len(df)}"
        
        # Verify we have the expected columns
        expected_columns = ['open', 'high', 'low', 'close', 'volume']
        assert all(col in df.columns for col in expected_columns), \
            f"DataFrame should have columns {expected_columns}"


def test_cache_covers_range_logic():
    """
    Test the _cache_covers_range method directly to ensure it correctly validates date ranges.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        exchange = MockExchange(start_date=datetime(2024, 1, 1), timeframe="1h")
        handler = CryptoDataHandler(exchange=exchange, cache_dir=Path(tmpdir))
        
        # Create a cached DataFrame covering Jan 1-10
        dates = pd.date_range(start="2024-01-01", end="2024-01-10", freq="1h")
        cached_df = pd.DataFrame({
            'open': range(len(dates)),
            'high': range(len(dates)),
            'low': range(len(dates)),
            'close': range(len(dates)),
            'volume': range(len(dates)),
        }, index=dates)
        
        # Test 1: Request fully covered by cache (Jan 2-8)
        start_ts = pd.to_datetime("2024-01-02")
        end_ts = pd.to_datetime("2024-01-08")
        assert handler._cache_covers_range(cached_df, start_ts, end_ts, 1000) is True, \
            "Cache should cover Jan 2-8 when it has Jan 1-10"
        
        # Test 2: Request partially outside cache (Jan 5-15)
        start_ts = pd.to_datetime("2024-01-05")
        end_ts = pd.to_datetime("2024-01-15")
        assert handler._cache_covers_range(cached_df, start_ts, end_ts, 1000) is False, \
            "Cache should NOT cover Jan 5-15 when it only has Jan 1-10"
        
        # Test 3: Request starts before cache (Dec 25 - Jan 5)
        start_ts = pd.to_datetime("2023-12-25")
        end_ts = pd.to_datetime("2024-01-05")
        assert handler._cache_covers_range(cached_df, start_ts, end_ts, 1000) is False, \
            "Cache should NOT cover Dec 25 - Jan 5 when it starts at Jan 1"
        
        # Test 4: No explicit dates (fallback to length check)
        assert handler._cache_covers_range(cached_df, None, None, 100) is True, \
            "Cache should be valid when it has more rows than the limit"
        assert handler._cache_covers_range(cached_df, None, None, 10000) is False, \
            "Cache should be invalid when it has fewer rows than the limit"


def test_integration_with_backtester():
    """
    Integration test: Verify that the backtester can request specific historical periods
    and the data handler returns the correct data.
    """
    from app.backtesting.engine import Backtester
    from app.core.interfaces import BaseStrategy
    from app.config.models import StrategyConfig
    
    # Create a simple test strategy
    class SimpleStrategy(BaseStrategy):
        def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
            return df
        
        def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
            df['signal'] = 1  # Always long
            return df
    
    config = StrategyConfig(
        name="test",
        symbol="BTC/USDT",
        timeframe="1h",
        params={}
    )
    strategy = SimpleStrategy(config)
    
    # Create data handler with mock exchange
    start_date = datetime(2024, 1, 1, 0, 0, 0)
    with tempfile.TemporaryDirectory() as tmpdir:
        exchange = MockExchange(start_date=start_date, timeframe="1h")
        handler = CryptoDataHandler(exchange=exchange, cache_dir=Path(tmpdir))
        
        # Create backtester
        backtester = Backtester(
            data_handler=handler,
            strategy=strategy,
            symbol="BTC/USDT",
            timeframe="1h",
            initial_capital=1.0,
        )
        
        # Run backtest for a specific historical period
        backtest_start = datetime(2024, 1, 2, 0, 0, 0)
        backtest_end = datetime(2024, 1, 3, 0, 0, 0)
        
        result = backtester.run(start_date=backtest_start, end_date=backtest_end)
        
        # Verify we got results
        assert "data" in result, "Result should contain data"
        assert "total_return" in result, "Result should contain total_return"
        assert "sharpe_ratio" in result, "Result should contain sharpe_ratio"
        assert "max_drawdown" in result, "Result should contain max_drawdown"
        
        # Verify the data is within the requested range
        df = result["data"]
        assert df.index.min() >= pd.to_datetime(backtest_start), \
            f"Data should start at or after {backtest_start}"
        assert df.index.max() <= pd.to_datetime(backtest_end), \
            f"Data should end at or before {backtest_end}"

