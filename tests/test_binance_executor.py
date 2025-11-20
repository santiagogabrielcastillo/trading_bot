"""
Tests for BinanceExecutor - Live trading executor.

These tests verify the BinanceExecutor integrates correctly with CCXT
and properly handles various exchange scenarios (success, errors, etc).
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
import ccxt

from app.core.database import Database
from app.core.enums import OrderSide, OrderType
from app.execution.binance_executor import BinanceExecutor
from app.repositories import TradeRepository
from app.models.sql import OrderSide as ModelOrderSide, Trade


@pytest.fixture(scope="function")
def in_memory_db_session():
    """
    Provides an in-memory SQLite database and a session for testing.
    Each test gets a fresh database.
    """
    # Reset the singleton for each test
    Database._instance = None
    
    db = Database()
    db.initialize("sqlite:///:memory:")
    
    with db.session_scope() as session:
        yield session
    
    # Clean up after test
    Database._instance = None


@pytest.fixture
def mock_ccxt_client():
    """Create a mock CCXT exchange client."""
    mock = MagicMock(spec=ccxt.Exchange)
    mock.name = "binance"
    mock.sandbox = False
    mock.load_markets = MagicMock()
    return mock


@pytest.fixture
def binance_executor(mock_ccxt_client, in_memory_db_session):
    """Create BinanceExecutor with mocked CCXT client."""
    trade_repo = TradeRepository(in_memory_db_session)
    return BinanceExecutor(mock_ccxt_client, trade_repo)


# --- Initialization Tests ---

def test_initialization_success(mock_ccxt_client, in_memory_db_session):
    """Test successful executor initialization."""
    trade_repo = TradeRepository(in_memory_db_session)
    executor = BinanceExecutor(mock_ccxt_client, trade_repo)
    
    assert executor.client == mock_ccxt_client
    assert executor.trade_repository == trade_repo
    mock_ccxt_client.load_markets.assert_called_once()


def test_initialization_failure(in_memory_db_session):
    """Test initialization fails gracefully when exchange unavailable."""
    mock_client = MagicMock()
    mock_client.load_markets.side_effect = Exception("Network error")
    
    trade_repo = TradeRepository(in_memory_db_session)
    with pytest.raises(Exception, match="Network error"):
        BinanceExecutor(mock_client, trade_repo)


# --- Market Order Tests ---

def test_execute_market_buy_order_success(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test successful market buy order execution."""
    # Mock CCXT response
    mock_order = {
        'id': '12345',
        'symbol': 'BTC/USDT',
        'type': 'market',
        'side': 'buy',
        'price': 50000.0,
        'average': 50000.0,
        'amount': 0.01,
        'filled': 0.01,
        'remaining': 0.0,
        'status': 'closed',
        'timestamp': 1609459200000,  # 2021-01-01 00:00:00
    }
    mock_ccxt_client.create_market_order = MagicMock(return_value=mock_order)
    
    # Execute order
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.MARKET,
    )
    
    # Verify CCXT call
    mock_ccxt_client.create_market_order.assert_called_once_with(
        symbol='BTC/USDT',
        side='buy',
        amount=0.01,
        params={},
    )
    
    # Verify return value
    assert result == mock_order
    assert result['id'] == '12345'
    assert result['status'] == 'closed'
    
    # Verify database persistence
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].symbol == 'BTC/USDT'
    assert trades[0].side == ModelOrderSide.BUY
    assert trades[0].price == 50000.0
    assert trades[0].quantity == 0.01


def test_execute_market_sell_order_success(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test successful market sell order execution."""
    mock_order = {
        'id': '12346',
        'symbol': 'ETH/USDT',
        'type': 'market',
        'side': 'sell',
        'average': 3000.0,
        'filled': 0.5,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    mock_ccxt_client.create_market_order = MagicMock(return_value=mock_order)
    
    result = binance_executor.execute_order(
        symbol='ETH/USDT',
        side=OrderSide.SELL,
        quantity=0.5,
        order_type=OrderType.MARKET,
    )
    
    assert result['side'] == 'sell'
    
    # Verify database
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].side == ModelOrderSide.SELL


# --- Limit Order Tests ---

def test_execute_limit_buy_order_success(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test successful limit buy order execution."""
    mock_order = {
        'id': '12347',
        'symbol': 'BTC/USDT',
        'type': 'limit',
        'side': 'buy',
        'price': 49000.0,
        'average': 49000.0,
        'filled': 0.02,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    mock_ccxt_client.create_limit_order = MagicMock(return_value=mock_order)
    
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.02,
        order_type=OrderType.LIMIT,
        price=49000.0,
    )
    
    # Verify CCXT call
    mock_ccxt_client.create_limit_order.assert_called_once_with(
        symbol='BTC/USDT',
        side='buy',
        amount=0.02,
        price=49000.0,
        params={},
    )
    
    assert result['type'] == 'limit'
    assert result['price'] == 49000.0


def test_execute_limit_order_without_price_fails(binance_executor: BinanceExecutor):
    """Test limit order fails when price not provided."""
    with pytest.raises(ValueError, match="Price is required for LIMIT orders"):
        binance_executor.execute_order(
            symbol='BTC/USDT',
            side=OrderSide.BUY,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            price=None,
        )


# --- Error Handling Tests ---

def test_insufficient_funds_error(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test handling of insufficient funds error."""
    mock_ccxt_client.create_market_order.side_effect = ccxt.InsufficientFunds("Not enough balance")
    
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=100.0,  # Too much
        order_type=OrderType.MARKET,
    )
    
    # Should return None (not raise)
    assert result is None
    
    # Should NOT persist to database
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 0


def test_network_error_raises(binance_executor: BinanceExecutor, mock_ccxt_client):
    """Test network errors are re-raised for retry."""
    mock_ccxt_client.create_market_order.side_effect = ccxt.NetworkError("Connection timeout")
    
    with pytest.raises(ccxt.NetworkError, match="Connection timeout"):
        binance_executor.execute_order(
            symbol='BTC/USDT',
            side=OrderSide.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )


def test_exchange_error_raises(binance_executor: BinanceExecutor, mock_ccxt_client):
    """Test exchange errors are re-raised."""
    mock_ccxt_client.create_market_order.side_effect = ccxt.ExchangeError("Invalid symbol")
    
    with pytest.raises(ccxt.ExchangeError, match="Invalid symbol"):
        binance_executor.execute_order(
            symbol='INVALID/PAIR',
            side=OrderSide.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )


def test_unexpected_error_raises(binance_executor: BinanceExecutor, mock_ccxt_client):
    """Test unexpected errors are re-raised with logging."""
    mock_ccxt_client.create_market_order.side_effect = RuntimeError("Unexpected error")
    
    with pytest.raises(RuntimeError, match="Unexpected error"):
        binance_executor.execute_order(
            symbol='BTC/USDT',
            side=OrderSide.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )


# --- Position Tracking Tests ---

def test_get_position_success(binance_executor: BinanceExecutor, mock_ccxt_client):
    """Test successful position retrieval."""
    mock_ccxt_client.fetch_balance = MagicMock(return_value={
        'BTC': {'free': 0.5, 'used': 0.1, 'total': 0.6},
        'USDT': {'free': 1000.0, 'used': 0.0, 'total': 1000.0},
    })
    
    position = binance_executor.get_position('BTC/USDT')
    
    assert position['symbol'] == 'BTC/USDT'
    assert position['net_quantity'] == 0.6
    assert position['free_balance'] == 0.5
    assert position['used_balance'] == 0.1
    assert position['is_flat'] is False


def test_get_position_flat(binance_executor: BinanceExecutor, mock_ccxt_client):
    """Test position returns flat when balance is zero."""
    mock_ccxt_client.fetch_balance = MagicMock(return_value={
        'BTC': {'free': 0.0, 'used': 0.0, 'total': 0.0},
    })
    
    position = binance_executor.get_position('BTC/USDT')
    
    assert position['net_quantity'] == 0.0
    assert position['is_flat'] is True


def test_get_position_handles_errors(binance_executor: BinanceExecutor, mock_ccxt_client):
    """Test position returns safe default on error."""
    mock_ccxt_client.fetch_balance.side_effect = ccxt.NetworkError("Connection failed")
    
    position = binance_executor.get_position('BTC/USDT')
    
    # Should return safe default instead of raising
    assert position['net_quantity'] == 0.0
    assert position['is_flat'] is True


# --- Trade Persistence Tests ---

def test_trade_persistence_on_success(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test trade is persisted to database on successful execution."""
    mock_order = {
        'id': '99999',
        'symbol': 'BTC/USDT',
        'average': 51000.0,
        'filled': 0.05,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    mock_ccxt_client.create_market_order = MagicMock(return_value=mock_order)
    
    binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.05,
        order_type=OrderType.MARKET,
    )
    
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].price == 51000.0
    assert trades[0].quantity == 0.05


def test_trade_not_persisted_on_error(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test trade is NOT persisted when order fails."""
    mock_ccxt_client.create_market_order.side_effect = ccxt.InsufficientFunds("No funds")
    
    binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=100.0,
        order_type=OrderType.MARKET,
    )
    
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 0


def test_persistence_failure_doesnt_crash(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test that database persistence failure doesn't crash the executor."""
    mock_order = {
        'id': '88888',
        'symbol': 'BTC/USDT',
        'average': 52000.0,
        'filled': 0.01,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    mock_ccxt_client.create_market_order = MagicMock(return_value=mock_order)
    
    # Mock repository to raise error
    with patch.object(binance_executor.trade_repository, 'create', side_effect=Exception("DB Error")):
        # Should not raise, just log warning
        result = binance_executor.execute_order(
            symbol='BTC/USDT',
            side=OrderSide.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )
    
    # Order should still be returned successfully
    assert result is not None
    assert result['id'] == '88888'


# --- Integration Tests ---

def test_full_trading_cycle(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test complete buy-sell cycle."""
    # Buy order
    buy_order = {
        'id': 'buy_001',
        'average': 50000.0,
        'filled': 0.1,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    mock_ccxt_client.create_market_order = MagicMock(return_value=buy_order)
    
    binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.1,
        order_type=OrderType.MARKET,
    )
    
    # Sell order
    sell_order = {
        'id': 'sell_001',
        'average': 52000.0,
        'filled': 0.1,
        'status': 'closed',
        'timestamp': 1609462800000,
    }
    mock_ccxt_client.create_market_order = MagicMock(return_value=sell_order)
    
    binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.SELL,
        quantity=0.1,
        order_type=OrderType.MARKET,
    )
    
    # Verify both trades persisted
    trades = in_memory_db_session.query(Trade).order_by(Trade.timestamp).all()
    assert len(trades) == 2
    assert trades[0].side == ModelOrderSide.BUY
    assert trades[0].price == 50000.0
    assert trades[1].side == ModelOrderSide.SELL
    assert trades[1].price == 52000.0


def test_multiple_symbols(binance_executor: BinanceExecutor, mock_ccxt_client, in_memory_db_session):
    """Test trading multiple symbols."""
    btc_order = {
        'id': 'btc_001',
        'average': 50000.0,
        'filled': 0.01,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    eth_order = {
        'id': 'eth_001',
        'average': 3000.0,
        'filled': 0.5,
        'status': 'closed',
        'timestamp': 1609462800000,
    }
    
    mock_ccxt_client.create_market_order = MagicMock(side_effect=[btc_order, eth_order])
    
    binance_executor.execute_order('BTC/USDT', OrderSide.BUY, 0.01, OrderType.MARKET)
    binance_executor.execute_order('ETH/USDT', OrderSide.BUY, 0.5, OrderType.MARKET)
    
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 2
    symbols = {t.symbol for t in trades}
    assert symbols == {'BTC/USDT', 'ETH/USDT'}


# --- Order Side Conversion Tests ---

def test_order_side_conversion_buy(binance_executor: BinanceExecutor):
    """Test conversion from interface OrderSide.BUY to model OrderSide.BUY."""
    model_side = binance_executor._convert_order_side(OrderSide.BUY)
    assert model_side == ModelOrderSide.BUY


def test_order_side_conversion_sell(binance_executor: BinanceExecutor):
    """Test conversion from interface OrderSide.SELL to model OrderSide.SELL."""
    model_side = binance_executor._convert_order_side(OrderSide.SELL)
    assert model_side == ModelOrderSide.SELL


# --- OCO Order Tests ---

def test_execute_order_places_oco_on_successful_entry(
    binance_executor: BinanceExecutor,
    mock_ccxt_client,
    in_memory_db_session
):
    """Test that OCO order is placed after successful entry order when SL/TP prices provided."""
    # Mock entry order response
    entry_order = {
        'id': 'entry_12345',
        'symbol': 'BTC/USDT',
        'type': 'market',
        'side': 'buy',
        'price': 50000.0,
        'average': 50000.0,
        'amount': 0.01,
        'filled': 0.01,
        'remaining': 0.0,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    
    # Mock OCO order response
    oco_response = {
        'orderListId': 'oco_list_123',
        'contingencyType': 'OCO',
        'listStatusType': 'EXECUTING',
        'listOrderStatus': 'EXECUTING',
        'orders': [
            {
                'orderId': 'sl_order_456',
                'symbol': 'BTC/USDT',
                'clientOrderId': 'sl_client_456',
                'price': '49000.00',
                'stopPrice': '49000.00',
            },
            {
                'orderId': 'tp_order_789',
                'symbol': 'BTC/USDT',
                'clientOrderId': 'tp_client_789',
                'price': '52000.00',
            },
        ],
    }
    
    # Setup mocks
    mock_ccxt_client.create_market_order = MagicMock(return_value=entry_order)
    mock_ccxt_client.create_oco_order = MagicMock(return_value=oco_response)
    
    # Execute order with SL/TP prices
    stop_loss_price = 49000.0
    take_profit_price = 52000.0
    
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.MARKET,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
    )
    
    # Verify entry order was executed
    assert result == entry_order
    mock_ccxt_client.create_market_order.assert_called_once_with(
        symbol='BTC/USDT',
        side='buy',
        amount=0.01,
        params={},
    )
    
    # Verify OCO order was placed
    mock_ccxt_client.create_oco_order.assert_called_once()
    oco_call_args = mock_ccxt_client.create_oco_order.call_args
    
    # Verify OCO call parameters
    assert oco_call_args[1]['symbol'] == 'BTC/USDT'
    assert oco_call_args[1]['side'] == 'sell'  # Opposite of entry (BUY → SELL)
    assert oco_call_args[1]['amount'] == 0.01
    assert oco_call_args[1]['price'] == str(take_profit_price)  # Limit price (TP)
    assert oco_call_args[1]['stopPrice'] == str(stop_loss_price)  # Stop price (SL)
    assert oco_call_args[1]['stopLimitPrice'] == str(stop_loss_price)  # Stop limit price
    assert oco_call_args[1]['stopLimitTimeInForce'] == 'GTC'
    
    # Verify trade was persisted with OCO order IDs
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.stop_loss_order_id == 'sl_order_456'
    assert trade.take_profit_order_id == 'tp_order_789'
    assert trade.exchange_order_id == 'entry_12345'


def test_execute_order_skips_oco_when_no_sl_tp_prices(
    binance_executor: BinanceExecutor,
    mock_ccxt_client,
    in_memory_db_session
):
    """Test that OCO order is NOT placed when SL/TP prices are not provided."""
    entry_order = {
        'id': 'entry_12345',
        'symbol': 'BTC/USDT',
        'type': 'market',
        'side': 'buy',
        'average': 50000.0,
        'filled': 0.01,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    
    mock_ccxt_client.create_market_order = MagicMock(return_value=entry_order)
    
    # Execute order without SL/TP prices
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.MARKET,
    )
    
    # Verify entry order executed
    assert result == entry_order
    
    # Verify OCO order was NOT called
    assert not hasattr(mock_ccxt_client, 'create_oco_order') or \
           not mock_ccxt_client.create_oco_order.called
    
    # Verify trade persisted without OCO order IDs
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].stop_loss_order_id is None
    assert trades[0].take_profit_order_id is None


def test_execute_order_skips_oco_when_zero_prices(
    binance_executor: BinanceExecutor,
    mock_ccxt_client,
    in_memory_db_session
):
    """Test that OCO order is NOT placed when SL/TP prices are zero."""
    entry_order = {
        'id': 'entry_12345',
        'symbol': 'BTC/USDT',
        'type': 'market',
        'side': 'buy',
        'average': 50000.0,
        'filled': 0.01,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    
    mock_ccxt_client.create_market_order = MagicMock(return_value=entry_order)
    
    # Execute order with zero SL/TP prices
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.MARKET,
        stop_loss_price=0.0,
        take_profit_price=0.0,
    )
    
    # Verify entry order executed
    assert result == entry_order
    
    # Verify OCO order was NOT called
    assert not hasattr(mock_ccxt_client, 'create_oco_order') or \
           not mock_ccxt_client.create_oco_order.called


def test_oco_order_failure_does_not_fail_entry(
    binance_executor: BinanceExecutor,
    mock_ccxt_client,
    in_memory_db_session
):
    """Test that OCO order failure doesn't fail the entry order."""
    entry_order = {
        'id': 'entry_12345',
        'symbol': 'BTC/USDT',
        'type': 'market',
        'side': 'buy',
        'average': 50000.0,
        'filled': 0.01,
        'status': 'closed',
        'timestamp': 1609459200000,
    }
    
    mock_ccxt_client.create_market_order = MagicMock(return_value=entry_order)
    mock_ccxt_client.create_oco_order = MagicMock(side_effect=ccxt.ExchangeError("OCO order failed"))
    
    # Execute order with SL/TP prices - OCO should fail but entry should succeed
    result = binance_executor.execute_order(
        symbol='BTC/USDT',
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.MARKET,
        stop_loss_price=49000.0,
        take_profit_price=52000.0,
    )
    
    # Verify entry order still executed successfully
    assert result == entry_order
    
    # Verify trade was persisted (even though OCO failed)
    trades = in_memory_db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].stop_loss_order_id is None  # OCO failed, so no IDs
    assert trades[0].take_profit_order_id is None


def test_cancel_oco_orders_success(
    binance_executor: BinanceExecutor,
    mock_ccxt_client,
    in_memory_db_session
):
    """Test successful cancellation of OCO orders."""
    # Create a trade with OCO order IDs
    trade = Trade(
        id='test_trade_123',
        symbol='BTC/USDT',
        side=ModelOrderSide.BUY,
        price=50000.0,
        quantity=0.01,
        exchange_order_id='entry_12345',
        stop_loss_order_id='sl_order_456',
        take_profit_order_id='tp_order_789',
    )
    in_memory_db_session.add(trade)
    in_memory_db_session.commit()
    
    # Mock cancel order responses
    mock_ccxt_client.cancel_order = MagicMock(return_value={'id': 'canceled'})
    
    # Cancel OCO orders
    binance_executor.cancel_oco_orders(trade)
    
    # Verify cancel_order was called for both SL and TP
    assert mock_ccxt_client.cancel_order.call_count == 2
    
    # Verify trade OCO order IDs were cleared
    in_memory_db_session.refresh(trade)
    assert trade.stop_loss_order_id is None
    assert trade.take_profit_order_id is None


def test_cancel_oco_orders_no_orders(
    binance_executor: BinanceExecutor,
    mock_ccxt_client,
    in_memory_db_session
):
    """Test cancel_oco_orders handles trade without OCO orders gracefully."""
    trade = Trade(
        id='test_trade_123',
        symbol='BTC/USDT',
        side=ModelOrderSide.BUY,
        price=50000.0,
        quantity=0.01,
        exchange_order_id='entry_12345',
        stop_loss_order_id=None,
        take_profit_order_id=None,
    )
    in_memory_db_session.add(trade)
    in_memory_db_session.commit()
    
    # Should not raise and should not call cancel_order
    binance_executor.cancel_oco_orders(trade)
    
    # Verify cancel_order was NOT called
    assert not hasattr(mock_ccxt_client, 'cancel_order') or \
           not mock_ccxt_client.cancel_order.called

