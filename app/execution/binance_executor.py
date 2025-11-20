"""
Binance executor for live trading with real money.

Executes orders on Binance exchange using CCXT library, with proper
error handling and database persistence for all trades.

⚠️  WARNING: This executor trades with REAL MONEY. Use with caution! ⚠️
"""
import logging
from datetime import datetime
from typing import Optional, Dict
import ccxt

from app.core.interfaces import IExecutor
from app.core.enums import OrderSide as InterfaceOrderSide, OrderType
from app.models.sql import OrderSide as ModelOrderSide
from app.repositories.trade_repository import TradeRepository

logger = logging.getLogger(__name__)


class BinanceExecutor(IExecutor):
    """
    Live executor for real trading on Binance exchange.
    
    Executes orders using CCXT library and persists all trades to
    the database. Includes comprehensive error handling for network
    issues and insufficient funds scenarios.
    
    ⚠️  WARNING: This executor uses REAL MONEY! ⚠️
    - All orders are executed on the live exchange
    - Losses are real and irreversible
    - Always test thoroughly in paper trading first
    - Use sandbox_mode=True for testing
    """
    
    def __init__(
        self,
        client: ccxt.Exchange,
        trade_repository: TradeRepository,
    ):
        """
        Initialize the Binance executor with CCXT client.
        
        Args:
            client: CCXT exchange instance (already configured with API keys)
            trade_repository: Repository for persisting trades
        """
        self.client = client
        self.trade_repository = trade_repository
        
        # Verify exchange connection
        try:
            self.client.load_markets()
            logger.info(f"BinanceExecutor initialized with exchange: {self.client.name}")
            logger.info(f"Sandbox mode: {getattr(self.client, 'sandbox', False)}")
        except Exception as e:
            logger.error(f"Failed to initialize exchange: {e}")
            raise
    
    def execute_order(
        self,
        symbol: str,
        side: InterfaceOrderSide,
        quantity: float,
        order_type: OrderType,
        price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Execute a live order on Binance exchange.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            side: Order side (BUY or SELL)
            quantity: Quantity to trade (in base currency)
            order_type: Order type (MARKET or LIMIT)
            price: Optional execution price (required for LIMIT orders)
            
        Returns:
            CCXT order structure on success, None on recoverable errors
            
        Raises:
            ccxt.NetworkError: On network issues (should be retried)
            ccxt.ExchangeError: On unrecoverable exchange errors
        """
        try:
            # Convert enums to CCXT format
            ccxt_side = side.value.lower()  # 'buy' or 'sell'
            ccxt_type = order_type.value.lower()  # 'market' or 'limit'
            
            logger.info(
                f"⚠️  EXECUTING LIVE ORDER: {ccxt_side.upper()} {quantity} {symbol} "
                f"(type: {ccxt_type})"
            )
            
            # Prepare order parameters
            order_params = {}
            
            # Execute order via CCXT
            if ccxt_type == 'market':
                order = self.client.create_market_order(
                    symbol=symbol,
                    side=ccxt_side,
                    amount=quantity,
                    params=order_params,
                )
            elif ccxt_type == 'limit':
                if price is None:
                    raise ValueError("Price is required for LIMIT orders")
                order = self.client.create_limit_order(
                    symbol=symbol,
                    side=ccxt_side,
                    amount=quantity,
                    price=price,
                    params=order_params,
                )
            else:
                raise ValueError(f"Unsupported order type: {order_type}")
            
            logger.info(
                f"✅ Order executed successfully: {order['id']} "
                f"(status: {order['status']}, filled: {order['filled']})"
            )
            
            # Persist trade to database
            self._persist_trade(order, symbol, side)
            
            return order
        
        except ccxt.InsufficientFunds as e:
            # Insufficient funds - log error but don't raise
            # Bot should continue running
            logger.error(
                f"❌ INSUFFICIENT FUNDS: Cannot execute {side.value} {quantity} {symbol}"
            )
            logger.error(f"Error details: {e}")
            logger.error("Bot will continue running. Please add funds or reduce position size.")
            return None
        
        except ccxt.NetworkError as e:
            # Network error - log and raise for retry
            logger.error(
                f"❌ NETWORK ERROR: Failed to execute {side.value} {quantity} {symbol}"
            )
            logger.error(f"Error details: {e}")
            logger.error("Bot will retry on next iteration.")
            raise
        
        except ccxt.ExchangeError as e:
            # Exchange error - log detailed info
            logger.error(
                f"❌ EXCHANGE ERROR: Failed to execute {side.value} {quantity} {symbol}"
            )
            logger.error(f"Error details: {e}")
            # Re-raise for bot to handle
            raise
        
        except Exception as e:
            # Unexpected error - log and raise
            logger.critical(
                f"💥 UNEXPECTED ERROR: Failed to execute {side.value} {quantity} {symbol}"
            )
            logger.critical(f"Error type: {type(e).__name__}")
            logger.critical(f"Error details: {e}", exc_info=True)
            raise
    
    def get_position(self, symbol: str) -> Dict[str, float]:
        """
        Get current position for a symbol from exchange balance.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            
        Returns:
            Dictionary with position information:
                - net_quantity: Current balance of base currency
                - total_buys: (not available from exchange directly)
                - total_sells: (not available from exchange directly)
                - is_flat: True if balance is approximately zero
        """
        try:
            # Extract base currency from symbol (e.g., 'BTC' from 'BTC/USDT')
            base_currency = symbol.split('/')[0]
            
            # Fetch balance from exchange
            balance = self.client.fetch_balance()
            
            # Get free + used (total balance)
            free_balance = balance.get(base_currency, {}).get('free', 0.0)
            used_balance = balance.get(base_currency, {}).get('used', 0.0)
            total_balance = free_balance + used_balance
            
            # Check if flat (account for floating point precision)
            is_flat = abs(total_balance) < 1e-8
            
            logger.info(
                f"Position for {symbol}: {total_balance} {base_currency} "
                f"(free: {free_balance}, used: {used_balance})"
            )
            
            return {
                "symbol": symbol,
                "net_quantity": total_balance,
                "total_buys": 0.0,  # Not available from exchange API
                "total_sells": 0.0,  # Not available from exchange API
                "is_flat": is_flat,
                "free_balance": free_balance,
                "used_balance": used_balance,
            }
        
        except Exception as e:
            logger.error(f"Failed to fetch position for {symbol}: {e}", exc_info=True)
            # Return safe default (flat position) on error
            return {
                "symbol": symbol,
                "net_quantity": 0.0,
                "total_buys": 0.0,
                "total_sells": 0.0,
                "is_flat": True,
            }
    
    def _persist_trade(
        self,
        order: dict,
        symbol: str,
        side: InterfaceOrderSide,
    ) -> None:
        """
        Persist executed trade to database.
        
        Args:
            order: CCXT order response
            symbol: Trading pair
            side: Order side (InterfaceOrderSide enum)
        """
        try:
            # Convert side enum
            model_side = self._convert_order_side(side)
            
            # Extract relevant fields from CCXT order
            price = float(order.get('average') or order.get('price', 0.0))
            quantity = float(order.get('filled', 0.0))
            timestamp = datetime.fromtimestamp(order['timestamp'] / 1000) if order.get('timestamp') else datetime.utcnow()
            
            # Extract exchange order ID for reconciliation
            exchange_order_id = str(order.get('id', ''))
            
            # Create trade record
            trade = self.trade_repository.create(
                symbol=symbol,
                side=model_side,
                price=price,
                quantity=quantity,
                pnl=None,  # PnL calculated later
                timestamp=timestamp,
                exchange_order_id=exchange_order_id,
            )
            
            logger.info(
                f"Trade persisted to database: ID={trade.id}, "
                f"Exchange Order ID={exchange_order_id}"
            )
        
        except Exception as e:
            logger.error(
                f"Failed to persist trade to database: {e}",
                exc_info=True
            )
            # Don't raise - database persistence failure shouldn't stop trading
            logger.warning("Trade executed but NOT saved to database!")
    
    def _convert_order_side(self, side: InterfaceOrderSide) -> ModelOrderSide:
        """
        Convert interface OrderSide enum to model OrderSide enum.
        
        Args:
            side: OrderSide from interfaces.py
            
        Returns:
            OrderSide from sql.py
        """
        if side == InterfaceOrderSide.BUY:
            return ModelOrderSide.BUY
        elif side == InterfaceOrderSide.SELL:
            return ModelOrderSide.SELL
        else:
            raise ValueError(f"Unknown order side: {side}")

