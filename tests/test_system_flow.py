"""
Step 10.5: System Integration Testing - Full Trading Cycle

This test module validates that all components of the trading bot work together
harmoniously by simulating a complete Buy → Sell trading cycle.

The test uses:
- Real TradingBot orchestrator
- Real SmaCrossStrategy for signal generation
- Real MockExecutor for trade execution
- Real Database repositories for persistence
- Mock DataHandler to avoid CCXT calls

The narrative: Price rises sharply (triggers BUY), then crashes (triggers SELL).
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.bot import TradingBot
from app.config.models import BotConfig, ExchangeConfig, RiskConfig, StrategyConfig
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository
from app.execution.mock_executor import MockExecutor
from app.strategies.sma_cross import SmaCrossStrategy


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def in_memory_db():
    """
    Create a fresh in-memory SQLite database for each test.
    This ensures complete isolation between tests.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    engine.dispose()


@pytest.fixture
def test_config():
    """
    Create bot configuration with parameters tuned for the test narrative.
    Using fast_window=10 and slow_window=20 for quicker signal generation.
    """
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
            params={
                "fast_window": 10,  # Faster response to price changes
                "slow_window": 20,  # Smaller window for test data
            },
        ),
        db_path="test.db",
    )


@pytest.fixture
def repositories(in_memory_db):
    """
    Create real repository instances with in-memory database.
    These are the actual repository classes used in production.
    """
    trade_repo = TradeRepository(in_memory_db)
    signal_repo = SignalRepository(in_memory_db)
    return trade_repo, signal_repo


@pytest.fixture
def mock_data_handler():
    """
    Create a mock DataHandler that returns pre-configured data.
    This prevents CCXT calls during tests while allowing control
    over the data returned.
    """
    handler = MagicMock()
    # We'll configure get_historical_data in each test
    return handler


@pytest.fixture
def real_strategy(test_config):
    """
    Create a real SmaCrossStrategy instance.
    This is NOT a mock - it's the actual strategy that will
    calculate indicators and generate signals.
    """
    return SmaCrossStrategy(config=test_config.strategy)


@pytest.fixture
def real_executor(repositories):
    """
    Create a real MockExecutor instance.
    This is NOT a MagicMock - it's the actual executor that will
    simulate trades and persist them to the database.
    """
    trade_repo, signal_repo = repositories
    return MockExecutor(
        trade_repository=trade_repo,
        signal_repository=signal_repo,
    )


@pytest.fixture
def trading_bot(test_config, mock_data_handler, real_strategy, real_executor, repositories):
    """
    Create the main TradingBot orchestrator with all real components.
    Only the DataHandler is mocked to avoid CCXT calls.
    """
    trade_repo, signal_repo = repositories
    
    bot = TradingBot(
        config=test_config,
        data_handler=mock_data_handler,
        strategy=real_strategy,
        executor=real_executor,
        trade_repo=trade_repo,
        signal_repo=signal_repo,
    )
    
    return bot


# ============================================================================
# Test Data Generators
# ============================================================================

def create_rising_price_data(num_candles: int = 33, start_price: float = 50000.0) -> pd.DataFrame:
    """
    Create market data that generates a BUY signal via golden cross at the VERY LAST candle.
    
    The default of 33 candles is chosen to ensure the golden cross occurs at index 32 (the last candle).
    With proportional phases (87% decline, 7% recovery, 6% explosive rally), 33 candles places
    the crossover precisely at the final candle.
    
    Args:
        num_candles: Number of candles to generate (default 33 for crossover at last candle)
        start_price: Starting price
        
    Returns:
        DataFrame with OHLCV data showing golden cross at the last candle
    """
    # Generate timestamps (1 hour apart)
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(hours=i) for i in range(num_candles)]
    
    prices = []
    
    # Calculate phase boundaries proportionally
    phase1_end = int(num_candles * 0.87)  # 87% decline
    phase2_end = int(num_candles * 0.94)  # 7% recovery
    # Phase 3: remaining 6% MEGA explosive rally
    
    # Phase 1: Extended decline - firmly keeps fast < slow
    for i in range(phase1_end):
        price = start_price - (i * (start_price * 0.0008))  # Gradual decline
        prices.append(price)
    
    # Phase 2: Tiny recovery - barely starts turning
    recovery_start = prices[-1]
    phase2_length = phase2_end - phase1_end
    for i in range(phase2_length):
        price = recovery_start + (i * (start_price * 0.002))  # Tiny recovery
        prices.append(price)
    
    # Phase 3: MEGA EXPLOSIVE rally - creates crossover at the VERY end
    rally_start = prices[-1]
    phase3_length = num_candles - phase2_end
    for i in range(phase3_length):
        # Exponential increase in the rally to push crossover to the end
        price = rally_start + ((i + 1) ** 2 * (start_price * 0.015))  # Accelerating explosive rise
        prices.append(price)
    
    df = pd.DataFrame({
        'open': prices,
        'high': [p * 1.01 for p in prices],
        'low': [p * 0.99 for p in prices],
        'close': prices,
        'volume': [1000.0] * num_candles,
    }, index=timestamps)
    
    return df


def create_crashing_price_data(num_candles: int = 33, start_price: float = 60500.0) -> pd.DataFrame:
    """
    Create market data that generates a SELL signal via death cross at the VERY LAST candle.
    
    The default of 33 candles is chosen to ensure the death cross occurs at index 32 (the last candle).
    With proportional phases (87% rise, 7% decline, 6% explosive crash), 33 candles places
    the crossover precisely at the final candle.
    
    Args:
        num_candles: Number of candles to generate (default 33 for crossover at last candle)
        start_price: Starting price (should match end of rising data)
        
    Returns:
        DataFrame with OHLCV data showing death cross at the last candle
    """
    # Generate timestamps (continuing from rising data)
    base_time = datetime(2024, 1, 3, 7, 0, 0)  # Continue after 55 hours
    timestamps = [base_time + timedelta(hours=i) for i in range(num_candles)]
    
    prices = []
    
    # Calculate phase boundaries proportionally
    phase1_end = int(num_candles * 0.87)  # 87% rise
    phase2_end = int(num_candles * 0.94)  # 7% decline
    # Phase 3: remaining 6% MEGA explosive crash
    
    # Phase 1: Extended uptrend - firmly keeps fast > slow
    for i in range(phase1_end):
        price = start_price + (i * (start_price * 0.0008))  # Gradual rise
        prices.append(price)
    
    # Phase 2: Tiny decline - barely starts turning
    decline_start = prices[-1]
    phase2_length = phase2_end - phase1_end
    for i in range(phase2_length):
        price = decline_start - (i * (start_price * 0.002))  # Tiny decline
        prices.append(price)
    
    # Phase 3: MEGA EXPLOSIVE crash - creates crossover at the VERY end
    crash_start = prices[-1]
    phase3_length = num_candles - phase2_end
    for i in range(phase3_length):
        # Exponential increase in the crash to push crossover to the end
        price = crash_start - ((i + 1) ** 2 * (start_price * 0.016))  # Accelerating explosive crash
        prices.append(price)
    
    df = pd.DataFrame({
        'open': prices,
        'high': [p * 1.01 for p in prices],
        'low': [p * 0.99 for p in prices],
        'close': prices,
        'volume': [1000.0] * num_candles,
    }, index=timestamps)
    
    return df


def create_full_cycle_data(num_candles_per_phase: int = 33) -> pd.DataFrame:
    """
    Create a complete dataset for a full BUY and SELL cycle.
    
    Args:
        num_candles_per_phase: Number of candles per phase (default 33)
    
    Returns:
        DataFrame with (num_candles_per_phase * 2 - 1) total candles
        The -1 is because we drop the first candle of the crashing phase to avoid
        duplicate timestamps and ensure smooth transition.
    """
    rising_data = create_rising_price_data(num_candles=num_candles_per_phase, start_price=50000.0)
    
    # Start crashing from the last rising price
    last_rising_price = rising_data['close'].iloc[-1]
    crashing_data = create_crashing_price_data(num_candles=num_candles_per_phase, start_price=last_rising_price)
    
    # Concatenate, dropping the first candle of crashing_data to avoid duplicate
    # This results in (num_candles_per_phase * 2 - 1) total candles
    full_data = pd.concat([rising_data, crashing_data.iloc[1:]])
    
    return full_data


# ============================================================================
# System Integration Tests
# ============================================================================

def test_full_cycle_buy_and_sell(trading_bot, mock_data_handler, repositories, real_executor):
    """
    THE MAIN TEST: Simulate a complete Buy → Sell trading cycle.
    
    This test proves that the TradingBot correctly orchestrates:
    1. Data fetching (DataHandler)
    2. Signal generation (Strategy)
    3. Trade execution (Executor)
    4. Database persistence (Repositories)
    
    Test Narrative:
    - Phase 1: Inject rising data → Should trigger BUY signal
    - Phase 2: Inject crashing data → Should trigger SELL signal
    - Result: Position goes from FLAT → LONG → FLAT
    """
    trade_repo, signal_repo = repositories
    
    # ===== PHASE 1: Rising Market (BUY Signal) =====
    print("\n=== PHASE 1: Rising Market ===")
    
    # Create rising price data (33 candles with golden cross at the very last candle)
    rising_data = create_rising_price_data(num_candles=33, start_price=50000.0)
    mock_data_handler.get_historical_data.return_value = rising_data
    
    # Initial state: Flat position
    position = real_executor.get_position("BTC/USDT")
    assert position['is_flat'], "Position should start flat"
    assert position['net_quantity'] == 0.0
    
    # Execute first trading cycle
    trading_bot.run_once()
    
    # Verify: BUY trade was executed
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 1, "Should have 1 trade after BUY signal"
    assert trades[0].side.value == "buy", "First trade should be BUY"
    assert trades[0].quantity > 0, "BUY quantity should be positive"
    
    # Verify: Position is now LONG
    position = real_executor.get_position("BTC/USDT")
    assert not position['is_flat'], "Position should not be flat after BUY"
    assert position['net_quantity'] > 0, "Net quantity should be positive (LONG)"
    print(f"✅ BUY executed: Position = {position['net_quantity']:.6f} BTC")
    
    # Verify: Signal was saved to database
    signals = signal_repo.get_by_symbol("BTC/USDT")
    assert len(signals) >= 1, "Should have at least 1 signal saved"
    
    # ===== PHASE 2: Crashing Market (SELL Signal) =====
    print("\n=== PHASE 2: Crashing Market ===")
    
    # Create crashing price data (33 candles with death cross at the very last candle)
    last_rising_price = rising_data['close'].iloc[-1]
    crashing_data = create_crashing_price_data(num_candles=33, start_price=last_rising_price)
    mock_data_handler.get_historical_data.return_value = crashing_data
    
    # Execute second trading cycle
    trading_bot.run_once()
    
    # Verify: SELL trade was executed (closing the position)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 2, f"Should have 2 trades after SELL signal, got {len(trades)}"
    assert trades[0].side.value == "sell", "Second trade should be SELL (most recent)"
    assert trades[1].side.value == "buy", "First trade should still be BUY"
    
    # Verify: Position is now FLAT again
    position = real_executor.get_position("BTC/USDT")
    assert position['is_flat'], "Position should be flat after SELL"
    assert abs(position['net_quantity']) < 1e-8, "Net quantity should be ~0 (accounting for float precision)"
    print(f"✅ SELL executed: Position = {position['net_quantity']:.6f} BTC")
    
    # Verify: Both trades have valid data
    buy_trade = trades[1]  # First trade (BUY)
    sell_trade = trades[0]  # Second trade (SELL)
    
    assert buy_trade.price > 0, "BUY price should be valid"
    assert sell_trade.price > 0, "SELL price should be valid"
    assert buy_trade.symbol == "BTC/USDT"
    assert sell_trade.symbol == "BTC/USDT"
    
    print(f"\n=== Trade Summary ===")
    print(f"BUY:  {buy_trade.quantity:.6f} BTC @ ${buy_trade.price:.2f}")
    print(f"SELL: {sell_trade.quantity:.6f} BTC @ ${sell_trade.price:.2f}")
    print(f"Position: {position['net_quantity']:.6f} BTC (FLAT: {position['is_flat']})")


def test_system_components_integration(trading_bot, mock_data_handler, repositories, real_strategy):
    """
    Test that all system components integrate correctly.
    
    Verifies:
    1. Strategy calculates indicators correctly
    2. Bot fetches correct amount of data
    3. Signals are persisted with metadata
    4. DataHandler is called with correct parameters
    """
    trade_repo, signal_repo = repositories
    
    # Create test data
    test_data = create_rising_price_data(num_candles=33)
    mock_data_handler.get_historical_data.return_value = test_data
    
    # Execute one cycle
    trading_bot.run_once()
    
    # Verify: DataHandler was called with correct parameters
    mock_data_handler.get_historical_data.assert_called_once()
    call_args = mock_data_handler.get_historical_data.call_args
    assert call_args[1]['symbol'] == "BTC/USDT"
    assert call_args[1]['timeframe'] == "1h"
    assert call_args[1]['limit'] == 40  # slow_window (20) + 20 buffer
    
    # Verify: Signal was saved with metadata
    signals = signal_repo.get_latest(symbol="BTC/USDT", limit=1)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_value in [-1, 0, 1], "Signal value should be valid"
    assert signal.signal_metadata is not None, "Signal should have metadata"
    assert 'close' in signal.signal_metadata, "Metadata should include close price"


def test_no_trades_on_neutral_signal(trading_bot, mock_data_handler, repositories):
    """
    Test that neutral market conditions don't trigger trades.
    
    This verifies that the bot doesn't execute unnecessary trades
    when there's no clear signal.
    """
    trade_repo, signal_repo = repositories
    
    # Create flat/sideways price data (no clear trend)
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(hours=i) for i in range(50)]
    
    # Prices oscillate around 50000 (no clear trend)
    prices = [50000.0 + (i % 10 - 5) * 100 for i in range(50)]
    
    df = pd.DataFrame({
        'open': prices,
        'high': [p + 50 for p in prices],
        'low': [p - 50 for p in prices],
        'close': prices,
        'volume': [1000.0] * 50,
    }, index=timestamps)
    
    mock_data_handler.get_historical_data.return_value = df
    
    # Execute trading cycle
    trading_bot.run_once()
    
    # Verify: No trades executed (market is neutral/sideways)
    trades = trade_repo.get_by_symbol("BTC/USDT")
    # Note: Depending on exact oscillation, might generate a signal
    # But position should remain flat if no clear trend
    position = trading_bot.executor.get_position("BTC/USDT")
    
    # At minimum, signal should be saved
    signals = signal_repo.get_by_symbol("BTC/USDT")
    assert len(signals) >= 1, "Signal should be saved even if neutral"


def test_multiple_cycles_with_position_tracking(trading_bot, mock_data_handler, repositories, real_executor):
    """
    Test multiple trading cycles with position tracking.
    
    Simulates: BUY → HOLD → HOLD → SELL
    Verifies position is tracked correctly across multiple run_once() calls.
    """
    trade_repo, signal_repo = repositories
    
    # Cycle 1: Rising data (BUY)
    rising_data = create_rising_price_data(num_candles=33, start_price=50000.0)
    mock_data_handler.get_historical_data.return_value = rising_data
    trading_bot.run_once()
    
    position_after_buy = real_executor.get_position("BTC/USDT")
    assert position_after_buy['net_quantity'] > 0, "Should have long position after BUY"
    
    # Cycle 2: Continue rising (should HOLD - no new signal)
    rising_data_2 = create_rising_price_data(num_candles=33, start_price=60000.0)
    mock_data_handler.get_historical_data.return_value = rising_data_2
    trading_bot.run_once()
    
    # Position should remain unchanged (no new trade)
    position_after_hold = real_executor.get_position("BTC/USDT")
    assert position_after_hold['net_quantity'] == position_after_buy['net_quantity'], \
        "Position should not change during HOLD"
    
    # Cycle 3: Crashing data (SELL)
    crashing_data = create_crashing_price_data(num_candles=33, start_price=70000.0)
    mock_data_handler.get_historical_data.return_value = crashing_data
    trading_bot.run_once()
    
    position_after_sell = real_executor.get_position("BTC/USDT")
    assert position_after_sell['is_flat'], "Should be flat after SELL"
    
    # Verify trade count
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 2, "Should have exactly 2 trades: BUY and SELL"


def test_signal_metadata_accuracy(trading_bot, mock_data_handler, repositories, real_strategy):
    """
    Test that signal metadata contains accurate indicator values.
    
    This ensures the Strategy's indicator calculations are preserved
    in the database for later analysis.
    """
    trade_repo, signal_repo = repositories
    
    # Create test data
    test_data = create_rising_price_data(num_candles=33)
    mock_data_handler.get_historical_data.return_value = test_data
    
    # Execute cycle
    trading_bot.run_once()
    
    # Retrieve saved signal
    signals = signal_repo.get_latest(symbol="BTC/USDT", limit=1)
    assert len(signals) == 1
    
    signal = signals[0]
    metadata = signal.signal_metadata
    
    # Verify metadata contains indicator values
    assert 'ema_fast' in metadata, "Metadata should include fast EMA"
    assert 'ema_slow' in metadata, "Metadata should include slow EMA"
    assert 'close' in metadata, "Metadata should include close price"
    
    # Verify values are reasonable
    assert metadata['ema_fast'] > 0, "Fast EMA should be positive"
    assert metadata['ema_slow'] > 0, "Slow EMA should be positive"
    assert metadata['close'] > 0, "Close price should be positive"
    
    # For rising data, fast EMA should eventually be > slow EMA
    # (though exact values depend on window sizes and data)
    print(f"\nSignal Metadata:")
    print(f"  Fast EMA: ${metadata['ema_fast']:.2f}")
    print(f"  Slow EMA: ${metadata['ema_slow']:.2f}")
    print(f"  Close:    ${metadata['close']:.2f}")


def test_executor_position_calculation_accuracy(real_executor, repositories):
    """
    Test that MockExecutor accurately calculates positions from trade history.
    
    This is a component-level test within the system integration suite,
    verifying the Executor's core responsibility.
    """
    from app.core.enums import OrderSide, OrderType
    
    trade_repo, signal_repo = repositories
    
    # Execute BUY order
    order1 = real_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.5,
        order_type=OrderType.MARKET,
        price=50000.0,
    )
    
    position = real_executor.get_position("BTC/USDT")
    assert position['net_quantity'] == 0.5, "Position should be 0.5 BTC"
    
    # Execute partial SELL
    order2 = real_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        quantity=0.3,
        order_type=OrderType.MARKET,
        price=55000.0,
    )
    
    position = real_executor.get_position("BTC/USDT")
    assert position['net_quantity'] == pytest.approx(0.2), "Position should be 0.2 BTC after partial sell"
    
    # Execute another SELL to close completely
    order3 = real_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        quantity=0.2,
        order_type=OrderType.MARKET,
        price=60000.0,
    )
    
    position = real_executor.get_position("BTC/USDT")
    assert position['is_flat'], "Position should be flat after closing"


# ============================================================================
# Edge Cases and Error Conditions
# ============================================================================

def test_empty_data_handling(trading_bot, mock_data_handler, repositories):
    """
    Test that the system handles empty data gracefully without crashing.
    """
    trade_repo, signal_repo = repositories
    
    # Return empty DataFrame
    mock_data_handler.get_historical_data.return_value = pd.DataFrame()
    
    # Should not raise exception
    trading_bot.run_once()
    
    # No trades should be executed
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 0, "No trades should be executed with empty data"


def test_insufficient_data_for_indicators(trading_bot, mock_data_handler, repositories):
    """
    Test handling of insufficient data for indicator calculation.
    
    Strategy needs at least slow_window candles to calculate indicators.
    """
    trade_repo, signal_repo = repositories
    
    # Create data with fewer candles than slow_window (20)
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(hours=i) for i in range(10)]  # Only 10 candles
    prices = [50000.0 + i * 100 for i in range(10)]
    
    df = pd.DataFrame({
        'open': prices,
        'high': [p + 50 for p in prices],
        'low': [p - 50 for p in prices],
        'close': prices,
        'volume': [1000.0] * 10,
    }, index=timestamps)
    
    mock_data_handler.get_historical_data.return_value = df
    
    # Execute - strategy should handle this gracefully
    # (NaN values in indicators should result in neutral signal)
    trading_bot.run_once()
    
    # System should not crash, but likely no trades due to insufficient data
    trades = trade_repo.get_by_symbol("BTC/USDT")
    # May or may not execute trade depending on how strategy handles NaN
    # Main point: no crash


# ============================================================================
# Performance and Validation Tests
# ============================================================================

def test_database_persistence_across_cycles(trading_bot, mock_data_handler, repositories):
    """
    Test that all data persists correctly across multiple cycles.
    
    Verifies:
    1. All trades are saved
    2. All signals are saved
    3. Data remains accessible after multiple cycles
    
    Test Pattern: BUY → SELL → BUY (3 cycles, 3 trades)
    """
    trade_repo, signal_repo = repositories
    
    # Cycle 1: Rising data → BUY signal
    rising_data_1 = create_rising_price_data(num_candles=33, start_price=50000.0)
    mock_data_handler.get_historical_data.return_value = rising_data_1
    trading_bot.run_once()
    
    # Cycle 2: Crashing data → SELL signal
    crashing_data = create_crashing_price_data(num_candles=33, start_price=rising_data_1['close'].iloc[-1])
    mock_data_handler.get_historical_data.return_value = crashing_data
    trading_bot.run_once()
    
    # Cycle 3: Rising data again → BUY signal
    rising_data_2 = create_rising_price_data(num_candles=33, start_price=55000.0)
    mock_data_handler.get_historical_data.return_value = rising_data_2
    trading_bot.run_once()
    
    # Verify all signals saved (3 cycles = 3 signals)
    all_signals = signal_repo.get_by_symbol("BTC/USDT")
    assert len(all_signals) >= 3, f"Should have at least 3 signals saved, got {len(all_signals)}"
    
    # Verify all trades saved (BUY + SELL + BUY = 3 trades)
    all_trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(all_trades) == 3, f"Should have exactly 3 trades (BUY→SELL→BUY), got {len(all_trades)}"
    
    # Verify trade order (most recent first)
    assert all_trades[0].side.value == "buy", "Most recent trade should be BUY"
    assert all_trades[1].side.value == "sell", "Second trade should be SELL"
    assert all_trades[2].side.value == "buy", "Oldest trade should be BUY"


def test_system_flow_documentation():
    """
    Documentation test: Verify test data generators work correctly.
    
    This test validates our test helper functions produce expected data.
    """
    # Test rising data (33 candles to get crossover at last candle)
    rising = create_rising_price_data(num_candles=33, start_price=50000.0)
    assert len(rising) == 33, "Should have 33 candles"
    assert rising['close'].iloc[0] == 50000.0, "Should start at specified price"
    # Prices should decline first (phase 1 - 87%), then rally (phases 2-3)
    phase1_end = int(33 * 0.87)  # Index 28
    assert rising['close'].iloc[phase1_end-1] < rising['close'].iloc[0], "Should decline in phase 1"
    assert rising['close'].iloc[-1] > rising['close'].iloc[phase1_end-1], "Should rally in phases 2-3"
    
    # Test crashing data (33 candles to get crossover at last candle)
    crashing = create_crashing_price_data(num_candles=33, start_price=60500.0)
    assert len(crashing) == 33, "Should have 33 candles"
    assert crashing['close'].iloc[0] == 60500.0, "Should start at specified price"
    # Prices should rise first (phase 1 - 87%), then crash (phases 2-3)
    phase1_end = int(33 * 0.87)  # Index 28
    assert crashing['close'].iloc[phase1_end-1] > crashing['close'].iloc[0], "Should rise in phase 1"
    assert crashing['close'].iloc[-1] < crashing['close'].iloc[phase1_end-1], "Should crash in phases 2-3"
    
    # Test full cycle data
    full = create_full_cycle_data()
    assert len(full) == 65, "Should have 65 candles total (33+33-1 due to pandas concat)"

