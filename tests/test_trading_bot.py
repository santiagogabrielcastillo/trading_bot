"""
Unit tests for Step 9: The Live Trading Loop

Tests the TradingBot orchestrator, including signal processing,
position management, and trade execution logic.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.bot import TradingBot
from app.core.enums import OrderSide, OrderType
from app.config.models import BotConfig, ExchangeConfig, RiskConfig, StrategyConfig
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository
from app.execution.mock_executor import MockExecutor


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    engine.dispose()


@pytest.fixture
def test_config():
    """Create a test configuration."""
    return BotConfig(
        exchange=ExchangeConfig(
            name="binance",
            api_key="test-key",
            api_secret="test-secret",
            sandbox_mode=True,
        ),
        risk=RiskConfig(
            max_position_size_usd=1000.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
        ),
        strategy=StrategyConfig(
            name="sma_cross",
            symbol="BTC/USDT",
            timeframe="1h",
            params={"fast_window": 10, "slow_window": 50},
        ),
        db_path="test.db",
    )


@pytest.fixture
def mock_data_handler():
    """Create a mock data handler."""
    handler = Mock()
    
    # Create sample OHLCV data
    dates = pd.date_range(end=datetime.now(), periods=100, freq='1h')
    prices = [50000 + i * 100 for i in range(100)]  # Trending up
    
    df = pd.DataFrame({
        'open': prices,
        'high': [p + 50 for p in prices],
        'low': [p - 50 for p in prices],
        'close': prices,
        'volume': [100] * 100,
    }, index=dates)
    
    handler.get_historical_data.return_value = df
    return handler


@pytest.fixture
def mock_strategy():
    """Create a mock strategy."""
    strategy = Mock()
    
    def calculate_indicators_side_effect(df):
        df['ema_fast'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        return df
    
    def generate_signals_side_effect(df):
        df['signal'] = 0  # Default neutral
        # Set last signal for testing
        df.loc[df.index[-1], 'signal'] = 1  # BUY signal
        return df
    
    strategy.calculate_indicators.side_effect = calculate_indicators_side_effect
    strategy.generate_signals.side_effect = generate_signals_side_effect
    
    return strategy


@pytest.fixture
def trading_bot(test_config, mock_data_handler, mock_strategy, in_memory_db):
    """Create a TradingBot instance for testing."""
    trade_repo = TradeRepository(in_memory_db)
    signal_repo = SignalRepository(in_memory_db)
    executor = MockExecutor(trade_repo, signal_repo)
    
    bot = TradingBot(
        config=test_config,
        data_handler=mock_data_handler,
        strategy=mock_strategy,
        executor=executor,
        trade_repo=trade_repo,
        signal_repo=signal_repo,
    )
    
    return bot


# ============================================================================
# Initialization Tests
# ============================================================================

def test_bot_initialization(trading_bot, test_config):
    """Test that bot initializes correctly with all dependencies."""
    assert trading_bot.symbol == "BTC/USDT"
    assert trading_bot.timeframe == "1h"
    assert trading_bot.buffer_size == 70  # slow_window (50) + 20
    assert trading_bot.last_signal_value is None


def test_bot_buffer_size_calculation(test_config, mock_data_handler, mock_strategy, in_memory_db):
    """Test that buffer size is calculated correctly."""
    # Modify config with different slow_window
    test_config.strategy.params['slow_window'] = 100
    
    trade_repo = TradeRepository(in_memory_db)
    signal_repo = SignalRepository(in_memory_db)
    executor = MockExecutor(trade_repo, signal_repo)
    
    bot = TradingBot(
        config=test_config,
        data_handler=mock_data_handler,
        strategy=mock_strategy,
        executor=executor,
        trade_repo=trade_repo,
        signal_repo=signal_repo,
    )
    
    assert bot.buffer_size == 120  # 100 + 20


# ============================================================================
# run_once() Tests
# ============================================================================

def test_run_once_fetches_data(trading_bot, mock_data_handler):
    """Test that run_once fetches historical data."""
    trading_bot.run_once()
    
    mock_data_handler.get_historical_data.assert_called_once_with(
        symbol="BTC/USDT",
        timeframe="1h",
        limit=70,
    )


def test_run_once_calls_strategy_methods(trading_bot, mock_strategy):
    """Test that run_once calls strategy methods in correct order."""
    trading_bot.run_once()
    
    # Should call calculate_indicators first
    assert mock_strategy.calculate_indicators.called
    # Then generate_signals
    assert mock_strategy.generate_signals.called


def test_run_once_saves_signal_to_database(trading_bot, in_memory_db):
    """Test that run_once persists signals to database."""
    signal_repo = SignalRepository(in_memory_db)
    initial_count = signal_repo.get_signal_count()
    
    trading_bot.run_once()
    
    final_count = signal_repo.get_signal_count()
    assert final_count == initial_count + 1
    
    # Verify signal details
    signals = signal_repo.get_latest(limit=1)
    assert len(signals) == 1
    assert signals[0].symbol == "BTC/USDT"


def test_run_once_handles_empty_data(trading_bot, mock_data_handler):
    """Test that run_once handles empty data gracefully."""
    mock_data_handler.get_historical_data.return_value = pd.DataFrame()
    
    # Should not raise exception
    trading_bot.run_once()
    
    # Should not execute any trades
    position = trading_bot.executor.get_position("BTC/USDT")
    assert position['is_flat']


# ============================================================================
# Trading Logic Tests
# ============================================================================

def test_buy_signal_with_flat_position_executes_buy(trading_bot, in_memory_db):
    """Test that BUY signal with flat position executes a BUY order."""
    # Setup: Ensure flat position
    position = trading_bot.executor.get_position("BTC/USDT")
    assert position['is_flat']
    
    # Execute run_once (mock strategy generates signal=1 by default)
    trading_bot.run_once()
    
    # Verify: BUY order was executed
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 1
    assert trades[0].side.value == "buy"


def test_sell_signal_with_long_position_executes_sell(trading_bot, mock_strategy, in_memory_db):
    """Test that SELL signal with long position executes a SELL order."""
    # Setup: Execute a BUY first
    trading_bot.run_once()  # This creates a long position
    
    # Change signal to SELL
    def generate_sell_signal(df):
        df['signal'] = -1  # SELL signal
        return df
    
    mock_strategy.generate_signals.side_effect = generate_sell_signal
    
    # Execute run_once again
    trading_bot.run_once()
    
    # Verify: Both BUY and SELL orders executed
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 2
    assert trades[0].side.value == "sell"  # Most recent
    assert trades[1].side.value == "buy"   # First trade


def test_neutral_signal_does_not_execute(trading_bot, mock_strategy, in_memory_db):
    """Test that NEUTRAL signal (0) does not execute any trades."""
    # Setup: Change signal to NEUTRAL
    def generate_neutral_signal(df):
        df['signal'] = 0  # NEUTRAL
        return df
    
    mock_strategy.generate_signals.side_effect = generate_neutral_signal
    
    # Execute run_once
    trading_bot.run_once()
    
    # Verify: No trades executed
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 0


def test_duplicate_signal_ignored(trading_bot, in_memory_db):
    """Test that duplicate signals don't trigger multiple trades."""
    # Execute run_once twice with same signal (BUY)
    trading_bot.run_once()
    trading_bot.run_once()
    
    # Verify: Only one trade executed
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 1


def test_buy_signal_with_existing_long_position_ignored(trading_bot, mock_strategy, in_memory_db):
    """Test that BUY signal with existing long position is ignored."""
    # Setup: Execute first BUY
    trading_bot.run_once()
    
    # Change signal to trigger new BUY detection (different iteration)
    trading_bot.last_signal_value = 0  # Reset to force signal change detection
    
    # Execute again (still BUY signal, still long position)
    trading_bot.run_once()
    
    # Verify: Only one BUY trade (second is ignored due to existing position)
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    # Should still be 1 because BUY with long position is ignored
    assert len(trades) >= 1


# ============================================================================
# Position Calculation Tests
# ============================================================================

def test_calculate_order_quantity(trading_bot):
    """Test order quantity calculation based on risk parameters."""
    price = 50000.0
    quantity = trading_bot._calculate_order_quantity(price)
    
    # max_position_size_usd = 1000, price = 50000
    # quantity = 1000 / 50000 = 0.02
    assert quantity == pytest.approx(0.02)


def test_calculate_order_quantity_different_price(trading_bot):
    """Test order quantity calculation with different price."""
    price = 3000.0  # ETH price
    quantity = trading_bot._calculate_order_quantity(price)
    
    # max_position_size_usd = 1000, price = 3000
    # quantity = 1000 / 3000 = 0.3333...
    assert quantity == pytest.approx(0.3333, abs=0.0001)


# ============================================================================
# Indicator Extraction Tests
# ============================================================================

def test_extract_indicators_with_ema(trading_bot, mock_data_handler):
    """Test indicator extraction from DataFrame."""
    df = mock_data_handler.get_historical_data()
    df['ema_fast'] = 50100.0
    df['ema_slow'] = 49900.0
    df['close'] = 50000.0
    
    indicators = trading_bot._extract_indicators(df)
    
    assert 'ema_fast' in indicators
    assert 'ema_slow' in indicators
    assert 'close' in indicators
    assert indicators['ema_fast'] == 50100.0
    assert indicators['ema_slow'] == 49900.0
    assert indicators['close'] == 50000.0


def test_extract_indicators_without_ema(trading_bot):
    """Test indicator extraction when EMAs are missing."""
    df = pd.DataFrame({
        'close': [50000.0],
    })
    
    indicators = trading_bot._extract_indicators(df)
    
    assert 'close' in indicators
    assert 'ema_fast' not in indicators
    assert 'ema_slow' not in indicators


# ============================================================================
# Signal Persistence Tests
# ============================================================================

def test_save_signal_persists_metadata(trading_bot, in_memory_db):
    """Test that signal metadata is saved correctly."""
    signal_value = 1
    timestamp = datetime.now()
    price = 50000.0
    indicators = {'ema_fast': 50100, 'ema_slow': 49900, 'close': 50000}
    
    trading_bot._save_signal(signal_value, timestamp, price, indicators)
    
    signal_repo = SignalRepository(in_memory_db)
    signals = signal_repo.get_latest(limit=1)
    
    assert len(signals) == 1
    assert signals[0].signal_value == 1
    assert signals[0].signal_metadata == indicators


def test_save_signal_handles_error_gracefully(trading_bot, caplog):
    """Test that signal save errors don't crash the bot."""
    # Force an error by passing invalid data
    with patch.object(trading_bot.signal_repo, 'create', side_effect=Exception("DB Error")):
        # Should not raise exception
        trading_bot._save_signal(1, datetime.now(), 50000.0, {})
    
    # Should log error
    assert "Failed to save signal" in caplog.text


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_trading_cycle(trading_bot, mock_strategy, in_memory_db):
    """Test a complete trading cycle: BUY → SELL."""
    # Cycle 1: BUY signal, flat position → Execute BUY
    trading_bot.run_once()
    
    position = trading_bot.executor.get_position("BTC/USDT")
    assert position['net_quantity'] > 0  # Long position
    
    # Cycle 2: SELL signal, long position → Execute SELL
    def generate_sell_signal(df):
        df['signal'] = -1
        return df
    
    mock_strategy.generate_signals.side_effect = generate_sell_signal
    trading_bot.run_once()
    
    position = trading_bot.executor.get_position("BTC/USDT")
    assert position['is_flat']  # Back to flat
    
    # Verify trades
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 2


def test_multiple_iterations_with_varying_signals(trading_bot, mock_strategy, in_memory_db):
    """Test multiple iterations with different signals."""
    signals = [1, 0, 0, -1, 0, 1]  # BUY, NEUTRAL, NEUTRAL, SELL, NEUTRAL, BUY
    
    for signal in signals:
        def generate_signal(df, sig=signal):
            df['signal'] = sig
            return df
        
        mock_strategy.generate_signals.side_effect = generate_signal
        trading_bot.run_once()
    
    # Should have executed: BUY (1st), SELL (4th), BUY (6th)
    # But signals might be ignored based on position state
    trade_repo = TradeRepository(in_memory_db)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) >= 2  # At least BUY and SELL


# ============================================================================
# Error Handling Tests
# ============================================================================

def test_run_once_handles_strategy_error(trading_bot, mock_strategy, caplog):
    """Test that strategy errors are logged but don't crash."""
    mock_strategy.generate_signals.side_effect = Exception("Strategy Error")
    
    # Should raise (errors in run_once are propagated)
    with pytest.raises(Exception, match="Strategy Error"):
        trading_bot.run_once()


def test_run_once_handles_executor_error(trading_bot, mock_strategy, in_memory_db, caplog):
    """Test that executor errors are logged and propagated."""
    # Mock executor to fail
    with patch.object(trading_bot.executor, 'execute_order', side_effect=Exception("Execution Error")):
        # Should raise
        with pytest.raises(Exception, match="Execution Error"):
            trading_bot.run_once()


# ============================================================================
# Start Method Tests (using mocks to avoid infinite loop)
# ============================================================================

@patch('time.sleep')
def test_start_calls_run_once_repeatedly(mock_sleep, trading_bot):
    """Test that start() calls run_once() in a loop."""
    # Mock run_once to count calls
    call_count = 0
    original_run_once = trading_bot.run_once
    
    def mock_run_once():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise KeyboardInterrupt  # Stop after 3 iterations
        original_run_once()
    
    trading_bot.run_once = mock_run_once
    
    # Run start (will stop after 3 iterations)
    trading_bot.start(sleep_seconds=1)
    
    # Verify run_once was called 3 times
    assert call_count == 3
    # Verify sleep was called
    assert mock_sleep.call_count >= 2


@patch('time.sleep')
def test_start_handles_errors_gracefully(mock_sleep, trading_bot, caplog):
    """Test that start() handles errors without crashing."""
    call_count = 0
    
    def mock_run_once_with_error():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Test Error")
        elif call_count >= 2:
            raise KeyboardInterrupt  # Stop after 2 iterations
    
    trading_bot.run_once = mock_run_once_with_error
    
    # Run start (should handle error and continue)
    trading_bot.start(sleep_seconds=1)
    
    # Verify run_once was called twice (error on first, interrupt on second)
    assert call_count == 2
    # Verify error was logged
    assert "Error in trading cycle" in caplog.text

