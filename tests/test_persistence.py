"""
Unit tests for Step 7: Persistence Layer

Tests database infrastructure, models, and repositories using in-memory SQLite.
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.database import Base, Database
from app.models.sql import Trade, Signal, OrderSide
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository


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
def signal_repo(in_memory_db):
    """Create a SignalRepository with in-memory session."""
    return SignalRepository(in_memory_db)


# ============================================================================
# Trade Model Tests
# ============================================================================

def test_create_trade(trade_repo):
    """Test creating a basic Trade record."""
    trade = trade_repo.create(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        price=50000.0,
        quantity=0.1,
        pnl=None,
    )
    
    assert trade.id is not None
    assert trade.symbol == "BTC/USDT"
    assert trade.side == OrderSide.BUY
    assert trade.price == 50000.0
    assert trade.quantity == 0.1
    assert trade.pnl is None
    assert trade.timestamp is not None


def test_read_trade_by_id(trade_repo):
    """Test retrieving a Trade by ID."""
    # Create trade
    trade = trade_repo.create(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        price=51000.0,
        quantity=0.1,
        pnl=100.0,
    )
    trade_id = trade.id
    
    # Retrieve trade
    retrieved = trade_repo.get_by_id(trade_id)
    
    assert retrieved is not None
    assert retrieved.id == trade_id
    assert retrieved.symbol == "BTC/USDT"
    assert retrieved.side == OrderSide.SELL
    assert retrieved.price == 51000.0
    assert retrieved.pnl == 100.0


def test_trade_with_pnl(trade_repo):
    """Test creating a Trade with PnL."""
    trade = trade_repo.create(
        symbol="ETH/USDT",
        side=OrderSide.SELL,
        price=3000.0,
        quantity=1.0,
        pnl=250.50,
    )
    
    assert trade.pnl == 250.50


def test_get_trades_by_symbol(trade_repo):
    """Test retrieving trades filtered by symbol."""
    # Create multiple trades for different symbols
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.BUY, price=50000.0, quantity=0.1)
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.SELL, price=51000.0, quantity=0.1)
    trade_repo.create(symbol="ETH/USDT", side=OrderSide.BUY, price=3000.0, quantity=1.0)
    
    # Get BTC trades
    btc_trades = trade_repo.get_by_symbol("BTC/USDT")
    
    assert len(btc_trades) == 2
    assert all(t.symbol == "BTC/USDT" for t in btc_trades)


def test_get_latest_trades(trade_repo):
    """Test retrieving the most recent trades."""
    # Create trades with different timestamps
    now = datetime.utcnow()
    for i in range(5):
        trade_repo.create(
            symbol="BTC/USDT",
            side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
            price=50000.0 + i * 100,
            quantity=0.1,
            timestamp=now - timedelta(minutes=i),
        )
    
    # Get latest 3 trades
    latest = trade_repo.get_latest(limit=3)
    
    assert len(latest) == 3
    # Should be ordered by timestamp descending (most recent first)
    assert latest[0].timestamp >= latest[1].timestamp >= latest[2].timestamp


def test_get_trades_by_date_range(trade_repo):
    """Test retrieving trades within a date range."""
    now = datetime.utcnow()
    start_date = now - timedelta(days=7)
    end_date = now - timedelta(days=1)
    
    # Create trades: some before, some in range, some after
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.BUY, price=50000.0, quantity=0.1,
                     timestamp=now - timedelta(days=10))  # Before range
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.SELL, price=51000.0, quantity=0.1,
                     timestamp=now - timedelta(days=5))   # In range
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.BUY, price=52000.0, quantity=0.1,
                     timestamp=now - timedelta(days=3))   # In range
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.SELL, price=53000.0, quantity=0.1,
                     timestamp=now)                        # After range
    
    # Get trades in range
    trades_in_range = trade_repo.get_by_date_range("BTC/USDT", start_date, end_date)
    
    assert len(trades_in_range) == 2
    assert all(start_date <= t.timestamp <= end_date for t in trades_in_range)


def test_get_total_pnl(trade_repo):
    """Test calculating total PnL across trades."""
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.BUY, price=50000.0, quantity=0.1, pnl=100.0)
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.SELL, price=51000.0, quantity=0.1, pnl=150.0)
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.BUY, price=49000.0, quantity=0.1, pnl=-50.0)
    
    total_pnl = trade_repo.get_total_pnl("BTC/USDT")
    
    assert total_pnl == 200.0  # 100 + 150 - 50


def test_get_trade_count(trade_repo):
    """Test counting trades."""
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.BUY, price=50000.0, quantity=0.1)
    trade_repo.create(symbol="BTC/USDT", side=OrderSide.SELL, price=51000.0, quantity=0.1)
    trade_repo.create(symbol="ETH/USDT", side=OrderSide.BUY, price=3000.0, quantity=1.0)
    
    total_count = trade_repo.get_trade_count()
    btc_count = trade_repo.get_trade_count("BTC/USDT")
    
    assert total_count == 3
    assert btc_count == 2


# ============================================================================
# Signal Model Tests
# ============================================================================

def test_create_signal(signal_repo):
    """Test creating a basic Signal record."""
    signal = signal_repo.create(
        symbol="BTC/USDT",
        signal_value=1,
        signal_metadata={"fast_sma": 50000, "slow_sma": 48000},
    )
    
    assert signal.id is not None
    assert signal.symbol == "BTC/USDT"
    assert signal.signal_value == 1
    assert signal.signal_metadata == {"fast_sma": 50000, "slow_sma": 48000}
    assert signal.timestamp is not None


def test_read_signal_by_id(signal_repo):
    """Test retrieving a Signal by ID."""
    # Create signal
    signal = signal_repo.create(
        symbol="ETH/USDT",
        signal_value=-1,
        signal_metadata={"price": 3000, "rsi": 75},
    )
    signal_id = signal.id
    
    # Retrieve signal
    retrieved = signal_repo.get_by_id(signal_id)
    
    assert retrieved is not None
    assert retrieved.id == signal_id
    assert retrieved.symbol == "ETH/USDT"
    assert retrieved.signal_value == -1
    assert retrieved.signal_metadata["rsi"] == 75


def test_signal_with_null_metadata(signal_repo):
    """Test creating a Signal without metadata."""
    signal = signal_repo.create(
        symbol="BTC/USDT",
        signal_value=0,
        signal_metadata=None,
    )
    
    assert signal.signal_metadata is None


def test_get_signals_by_symbol(signal_repo):
    """Test retrieving signals filtered by symbol."""
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None)
    signal_repo.create(symbol="BTC/USDT", signal_value=-1, signal_metadata=None)
    signal_repo.create(symbol="ETH/USDT", signal_value=1, signal_metadata=None)
    
    btc_signals = signal_repo.get_by_symbol("BTC/USDT")
    
    assert len(btc_signals) == 2
    assert all(s.symbol == "BTC/USDT" for s in btc_signals)


def test_get_latest_signals(signal_repo):
    """Test retrieving the most recent signals."""
    now = datetime.utcnow()
    for i in range(5):
        signal_repo.create(
            symbol="BTC/USDT",
            signal_value=1 if i % 2 == 0 else -1,
            signal_metadata=None,
            timestamp=now - timedelta(minutes=i),
        )
    
    latest = signal_repo.get_latest(limit=3)
    
    assert len(latest) == 3
    assert latest[0].timestamp >= latest[1].timestamp >= latest[2].timestamp


def test_get_signals_by_value(signal_repo):
    """Test retrieving signals by signal value."""
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None)
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None)
    signal_repo.create(symbol="BTC/USDT", signal_value=-1, signal_metadata=None)
    signal_repo.create(symbol="BTC/USDT", signal_value=0, signal_metadata=None)
    
    buy_signals = signal_repo.get_by_signal_value(1, symbol="BTC/USDT")
    sell_signals = signal_repo.get_by_signal_value(-1, symbol="BTC/USDT")
    
    assert len(buy_signals) == 2
    assert len(sell_signals) == 1
    assert all(s.signal_value == 1 for s in buy_signals)


def test_get_signals_by_date_range(signal_repo):
    """Test retrieving signals within a date range."""
    now = datetime.utcnow()
    start_date = now - timedelta(days=7)
    end_date = now - timedelta(days=1)
    
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None,
                      timestamp=now - timedelta(days=10))  # Before range
    signal_repo.create(symbol="BTC/USDT", signal_value=-1, signal_metadata=None,
                      timestamp=now - timedelta(days=5))   # In range
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None,
                      timestamp=now - timedelta(days=3))   # In range
    signal_repo.create(symbol="BTC/USDT", signal_value=-1, signal_metadata=None,
                      timestamp=now)                        # After range
    
    signals_in_range = signal_repo.get_by_date_range("BTC/USDT", start_date, end_date)
    
    assert len(signals_in_range) == 2
    assert all(start_date <= s.timestamp <= end_date for s in signals_in_range)


def test_get_signal_count(signal_repo):
    """Test counting signals with filters."""
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None)
    signal_repo.create(symbol="BTC/USDT", signal_value=1, signal_metadata=None)
    signal_repo.create(symbol="BTC/USDT", signal_value=-1, signal_metadata=None)
    signal_repo.create(symbol="ETH/USDT", signal_value=1, signal_metadata=None)
    
    total_count = signal_repo.get_signal_count()
    btc_count = signal_repo.get_signal_count(symbol="BTC/USDT")
    buy_count = signal_repo.get_signal_count(signal_value=1)
    btc_buy_count = signal_repo.get_signal_count(symbol="BTC/USDT", signal_value=1)
    
    assert total_count == 4
    assert btc_count == 3
    assert buy_count == 3
    assert btc_buy_count == 2


# ============================================================================
# Database Infrastructure Tests
# ============================================================================

def test_database_singleton():
    """Test that Database uses singleton pattern."""
    db1 = Database()
    db2 = Database()
    
    assert db1 is db2


def test_database_initialization():
    """Test database initialization with file path."""
    db = Database()
    db.initialize("sqlite:///:memory:")
    
    engine = db.get_engine()
    assert engine is not None
    
    session = db.get_session()
    assert session is not None
    session.close()


def test_session_scope_commit():
    """Test session_scope context manager with successful commit."""
    db = Database()
    db.initialize("sqlite:///:memory:")
    
    with db.session_scope() as session:
        trade_repo = TradeRepository(session)
        trade = trade_repo.create(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            price=50000.0,
            quantity=0.1,
        )
        trade_id = trade.id
    
    # Verify trade was committed
    with db.session_scope() as session:
        trade_repo = TradeRepository(session)
        retrieved = trade_repo.get_by_id(trade_id)
        assert retrieved is not None


def test_session_scope_rollback():
    """Test session_scope context manager with rollback on exception."""
    db = Database()
    db.initialize("sqlite:///:memory:")
    
    try:
        with db.session_scope() as session:
            trade_repo = TradeRepository(session)
            trade = trade_repo.create(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                price=50000.0,
                quantity=0.1,
            )
            trade_id = trade.id
            raise ValueError("Test exception")
    except ValueError:
        pass
    
    # Verify trade was NOT committed
    with db.session_scope() as session:
        trade_repo = TradeRepository(session)
        retrieved = trade_repo.get_by_id(trade_id)
        assert retrieved is None

