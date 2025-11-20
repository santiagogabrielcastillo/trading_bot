"""
Unit tests for Step 8: Stateful Mock Executor

Tests the mock executor for paper trading, including database persistence,
position tracking, and CCXT-like order structure.
"""
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.enums import OrderSide, OrderType
from app.models.sql import Trade, OrderSide as ModelOrderSide
from app.repositories.trade_repository import TradeRepository
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
def trade_repo(in_memory_db):
    """Create a TradeRepository with in-memory session."""
    return TradeRepository(in_memory_db)


@pytest.fixture
def mock_executor(trade_repo):
    """Create a MockExecutor instance."""
    return MockExecutor(trade_repo)


# ============================================================================
# Order Execution Tests
# ============================================================================

def test_execute_order_creates_database_record(mock_executor, trade_repo):
    """Test that execute_order persists trade to database."""
    # Initial trade count should be 0
    initial_count = trade_repo.get_trade_count()
    assert initial_count == 0
    
    # Execute order
    order = mock_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.1,
        order_type=OrderType.MARKET,
        price=50000.0,
    )
    
    # Verify trade was persisted
    final_count = trade_repo.get_trade_count()
    assert final_count == 1
    
    # Verify trade details
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 1
    trade = trades[0]
    assert trade.symbol == "BTC/USDT"
    assert trade.side == ModelOrderSide.BUY
    assert trade.price == 50000.0
    assert trade.quantity == 0.1


def test_execute_order_returns_valid_structure(mock_executor):
    """Test that execute_order returns CCXT-like order dictionary."""
    order = mock_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.5,
        order_type=OrderType.MARKET,
        price=51000.0,
    )
    
    # Verify required fields exist
    assert "id" in order
    assert "symbol" in order
    assert "side" in order
    assert "type" in order
    assert "price" in order
    assert "amount" in order
    assert "filled" in order
    assert "remaining" in order
    assert "status" in order
    assert "timestamp" in order
    assert "datetime" in order
    
    # Verify field values
    assert order["id"] is not None
    assert order["symbol"] == "BTC/USDT"
    assert order["side"] == "buy"
    assert order["type"] == "market"
    assert order["price"] == 51000.0
    assert order["amount"] == 0.5
    assert order["filled"] == 0.5  # 100% fill
    assert order["remaining"] == 0.0  # Fully filled
    assert order["status"] == "closed"
    assert order["cost"] == 51000.0 * 0.5


def test_execute_order_with_simulated_price(mock_executor, trade_repo):
    """Test execute_order without explicit price (uses simulated price)."""
    order = mock_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        quantity=0.2,
        order_type=OrderType.MARKET,
    )
    
    # Should use simulated BTC price
    assert order["price"] == 50000.0
    
    # Verify in database
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 1
    assert trades[0].price == 50000.0


def test_execute_multiple_orders(mock_executor, trade_repo):
    """Test executing multiple orders in sequence."""
    # Execute 3 orders
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.1, OrderType.MARKET, 50000.0)
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.2, OrderType.MARKET, 51000.0)
    mock_executor.execute_order("ETH/USDT", OrderSide.BUY, 1.0, OrderType.MARKET, 3000.0)
    
    # Verify all trades persisted
    assert trade_repo.get_trade_count() == 3
    assert trade_repo.get_trade_count("BTC/USDT") == 2
    assert trade_repo.get_trade_count("ETH/USDT") == 1


def test_execute_order_buy_and_sell(mock_executor, trade_repo):
    """Test executing both buy and sell orders."""
    # Buy
    buy_order = mock_executor.execute_order(
        "BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0
    )
    
    # Sell
    sell_order = mock_executor.execute_order(
        "BTC/USDT", OrderSide.SELL, 0.3, OrderType.MARKET, 51000.0
    )
    
    # Verify both persisted
    trades = trade_repo.get_by_symbol("BTC/USDT")
    assert len(trades) == 2
    
    # Verify sides (most recent first)
    assert trades[0].side == ModelOrderSide.SELL
    assert trades[1].side == ModelOrderSide.BUY


def test_execute_order_with_limit_type(mock_executor):
    """Test executing a LIMIT order."""
    order = mock_executor.execute_order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.1,
        order_type=OrderType.LIMIT,
        price=49000.0,
    )
    
    assert order["type"] == "limit"
    assert order["price"] == 49000.0


# ============================================================================
# Position Tracking Tests
# ============================================================================

def test_get_position_empty(mock_executor):
    """Test get_position with no trades."""
    position = mock_executor.get_position("BTC/USDT")
    
    assert position["symbol"] == "BTC/USDT"
    assert position["net_quantity"] == 0.0
    assert position["total_buys"] == 0.0
    assert position["total_sells"] == 0.0
    assert position["is_flat"] is True


def test_get_position_after_buy(mock_executor):
    """Test get_position after a buy order."""
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0)
    
    position = mock_executor.get_position("BTC/USDT")
    
    assert position["net_quantity"] == 0.5
    assert position["total_buys"] == 0.5
    assert position["total_sells"] == 0.0
    assert position["is_flat"] is False


def test_get_position_after_multiple_buys(mock_executor):
    """Test get_position after multiple buy orders."""
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.3, OrderType.MARKET, 50000.0)
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.2, OrderType.MARKET, 50500.0)
    
    position = mock_executor.get_position("BTC/USDT")
    
    assert position["net_quantity"] == 0.5
    assert position["total_buys"] == 0.5


def test_get_position_after_buy_and_sell(mock_executor):
    """Test get_position after buy and sell orders."""
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 1.0, OrderType.MARKET, 50000.0)
    mock_executor.execute_order("BTC/USDT", OrderSide.SELL, 0.6, OrderType.MARKET, 51000.0)
    
    position = mock_executor.get_position("BTC/USDT")
    
    assert position["net_quantity"] == 0.4  # 1.0 - 0.6
    assert position["total_buys"] == 1.0
    assert position["total_sells"] == 0.6
    assert position["is_flat"] is False


def test_get_position_flat_after_closing(mock_executor):
    """Test get_position returns flat after closing position."""
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0)
    mock_executor.execute_order("BTC/USDT", OrderSide.SELL, 0.5, OrderType.MARKET, 51000.0)
    
    position = mock_executor.get_position("BTC/USDT")
    
    assert position["net_quantity"] == 0.0
    assert position["is_flat"] is True


def test_get_position_short(mock_executor):
    """Test get_position with a short position (negative net_quantity)."""
    mock_executor.execute_order("BTC/USDT", OrderSide.SELL, 0.3, OrderType.MARKET, 50000.0)
    
    position = mock_executor.get_position("BTC/USDT")
    
    assert position["net_quantity"] == -0.3
    assert position["total_buys"] == 0.0
    assert position["total_sells"] == 0.3
    assert position["is_flat"] is False


def test_get_position_multiple_symbols(mock_executor):
    """Test get_position tracks multiple symbols independently."""
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0)
    mock_executor.execute_order("ETH/USDT", OrderSide.BUY, 2.0, OrderType.MARKET, 3000.0)
    
    btc_position = mock_executor.get_position("BTC/USDT")
    eth_position = mock_executor.get_position("ETH/USDT")
    
    assert btc_position["net_quantity"] == 0.5
    assert eth_position["net_quantity"] == 2.0


def test_position_cache_updated(mock_executor):
    """Test that position cache is updated correctly."""
    # Execute orders
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0)
    
    # Check cache
    assert "BTC/USDT" in mock_executor._position_cache
    assert mock_executor._position_cache["BTC/USDT"] == 0.5
    
    # Execute another order
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.3, OrderType.MARKET, 50500.0)
    
    # Cache should be updated
    assert mock_executor._position_cache["BTC/USDT"] == 0.8


def test_reset_position_cache(mock_executor):
    """Test that reset_position_cache clears the cache."""
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0)
    
    # Cache should have data
    assert len(mock_executor._position_cache) > 0
    
    # Reset cache
    mock_executor.reset_position_cache()
    
    # Cache should be empty
    assert len(mock_executor._position_cache) == 0
    
    # Position should still be calculable from database
    position = mock_executor.get_position("BTC/USDT")
    assert position["net_quantity"] == 0.5


# ============================================================================
# Simulated Price Tests
# ============================================================================

def test_simulated_price_btc(mock_executor):
    """Test simulated price for BTC."""
    order = mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.1, OrderType.MARKET)
    assert order["price"] == 50000.0


def test_simulated_price_eth(mock_executor):
    """Test simulated price for ETH."""
    order = mock_executor.execute_order("ETH/USDT", OrderSide.BUY, 1.0, OrderType.MARKET)
    assert order["price"] == 3000.0


def test_simulated_price_default(mock_executor):
    """Test simulated price for unknown symbol."""
    order = mock_executor.execute_order("XRP/USDT", OrderSide.BUY, 100.0, OrderType.MARKET)
    assert order["price"] == 100.0


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_trading_cycle(mock_executor, trade_repo):
    """Test a complete trading cycle: buy, hold, sell."""
    symbol = "BTC/USDT"
    
    # Start with flat position
    position = mock_executor.get_position(symbol)
    assert position["is_flat"] is True
    
    # Buy
    buy_order = mock_executor.execute_order(
        symbol, OrderSide.BUY, 1.0, OrderType.MARKET, 50000.0
    )
    assert buy_order["status"] == "closed"
    
    # Check position is long
    position = mock_executor.get_position(symbol)
    assert position["net_quantity"] == 1.0
    assert position["is_flat"] is False
    
    # Sell half
    sell_order = mock_executor.execute_order(
        symbol, OrderSide.SELL, 0.5, OrderType.MARKET, 51000.0
    )
    assert sell_order["status"] == "closed"
    
    # Check position is reduced
    position = mock_executor.get_position(symbol)
    assert position["net_quantity"] == 0.5
    
    # Sell remaining
    mock_executor.execute_order(
        symbol, OrderSide.SELL, 0.5, OrderType.MARKET, 52000.0
    )
    
    # Check position is flat
    position = mock_executor.get_position(symbol)
    assert position["is_flat"] is True
    
    # Verify all trades in database
    trades = trade_repo.get_by_symbol(symbol)
    assert len(trades) == 3


def test_concurrent_symbols(mock_executor):
    """Test trading multiple symbols concurrently."""
    # Trade BTC
    mock_executor.execute_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET, 50000.0)
    
    # Trade ETH
    mock_executor.execute_order("ETH/USDT", OrderSide.BUY, 2.0, OrderType.MARKET, 3000.0)
    
    # Trade BTC again
    mock_executor.execute_order("BTC/USDT", OrderSide.SELL, 0.2, OrderType.MARKET, 51000.0)
    
    # Verify positions are independent
    btc_position = mock_executor.get_position("BTC/USDT")
    eth_position = mock_executor.get_position("ETH/USDT")
    
    assert btc_position["net_quantity"] == 0.3  # 0.5 - 0.2
    assert eth_position["net_quantity"] == 2.0


def test_order_info_contains_trade_id(mock_executor):
    """Test that order info contains the database trade ID."""
    order = mock_executor.execute_order(
        "BTC/USDT", OrderSide.BUY, 0.1, OrderType.MARKET, 50000.0
    )
    
    # Check info field
    assert "info" in order
    assert "trade_db_id" in order["info"]
    assert "simulated" in order["info"]
    assert order["info"]["simulated"] is True
    assert order["info"]["trade_db_id"] is not None

