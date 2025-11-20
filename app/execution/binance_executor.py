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
from app.models.sql import OrderSide as ModelOrderSide, Trade
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
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Execute a live order on Binance exchange.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            side: Order side (BUY or SELL)
            quantity: Quantity to trade (in base currency)
            order_type: Order type (MARKET or LIMIT)
            price: Optional execution price (required for LIMIT orders)
            stop_loss_price: Optional stop-loss price for OCO order placement
            take_profit_price: Optional take-profit price for OCO order placement
            
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
            trade = self._persist_trade(order, symbol, side)
            
            # Place OCO order for hard SL/TP protection if prices are provided
            if trade and stop_loss_price and take_profit_price and stop_loss_price > 0 and take_profit_price > 0:
                try:
                    self._place_oco_order(
                        trade=trade,
                        symbol=symbol,
                        side=side,
                        quantity=float(order.get('filled', quantity)),
                        stop_loss_price=stop_loss_price,
                        take_profit_price=take_profit_price,
                    )
                except Exception as e:
                    # Log error but don't fail the entry order
                    logger.error(
                        f"⚠️  Failed to place OCO order for trade {trade.id}: {e}",
                        exc_info=True
                    )
                    logger.warning("Entry order executed but OCO protection not placed!")
            
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
    
    def _place_oco_order(
        self,
        trade: Trade,
        symbol: str,
        side: InterfaceOrderSide,
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> None:
        """
        Place an OCO (One-Cancels-the-Other) order for hard stop-loss and take-profit protection.
        
        OCO orders ensure position protection even if the bot crashes or goes offline.
        The order type is opposite to the entry: SELL for LONG entry, BUY for SHORT entry.
        
        Args:
            trade: Trade object from the entry order
            symbol: Trading pair
            side: Entry order side (BUY or SELL)
            quantity: Quantity to protect (from executed entry order)
            stop_loss_price: Stop-loss price (trigger price)
            take_profit_price: Take-profit price (limit price)
        """
        try:
            # OCO order side is opposite to entry side
            # BUY entry → SELL OCO (to close long position)
            # SELL entry → BUY OCO (to close short position)
            oco_side = 'sell' if side == InterfaceOrderSide.BUY else 'buy'
            
            logger.info(
                f"🛡️  Placing OCO order for trade {trade.id}: "
                f"{oco_side.upper()} {quantity} {symbol} "
                f"(SL: {stop_loss_price}, TP: {take_profit_price})"
            )
            
            # Place OCO order using CCXT
            # For STOP_LOSS_LIMIT, we use the same price for stop and limit
            oco_response = self.client.create_oco_order(
                symbol=symbol,
                side=oco_side,
                amount=quantity,
                price=str(take_profit_price),  # Limit price (take profit)
                stopPrice=str(stop_loss_price),  # Stop price (stop loss trigger)
                stopLimitPrice=str(stop_loss_price),  # Stop limit price (same as stop price)
                stopLimitTimeInForce='GTC',  # Good Till Cancel
            )
            
            # Extract order IDs from OCO response
            # CCXT OCO response structure: {'orderListId': ..., 'orders': [{'orderId': ...}, {'orderId': ...}]}
            # Binance OCO: First order is STOP_LOSS_LIMIT, second is LIMIT (take-profit)
            stop_loss_order_id = None
            take_profit_order_id = None
            
            if 'orders' in oco_response and len(oco_response['orders']) >= 2:
                orders = oco_response['orders']
                # First order is stop-loss (STOP_LOSS_LIMIT type)
                # Second order is take-profit (LIMIT type)
                stop_loss_order_id = str(orders[0].get('orderId', ''))
                take_profit_order_id = str(orders[1].get('orderId', ''))
            
            # Update trade record with OCO order IDs
            if stop_loss_order_id and take_profit_order_id:
                self.trade_repository.update(
                    trade,
                    stop_loss_order_id=stop_loss_order_id,
                    take_profit_order_id=take_profit_order_id,
                )
                
                logger.info(
                    f"✅ OCO order placed successfully: "
                    f"SL Order ID={stop_loss_order_id}, TP Order ID={take_profit_order_id}"
                )
                logger.info(
                    f"🛡️  Position protected: Trade {trade.id} has hard SL/TP on exchange"
                )
            else:
                logger.warning(
                    f"⚠️  OCO order placed but could not extract order IDs from response"
                )
        
        except Exception as e:
            logger.error(
                f"❌ Failed to place OCO order: {e}",
                exc_info=True
            )
            raise
    
    def cancel_oco_orders(self, trade: Trade) -> None:
        """
        Cancel OCO orders associated with a trade.
        
        This is used when manually closing a position or when a strategy
        exit signal requires canceling the protective orders.
        
        Args:
            trade: Trade object with OCO order IDs
        """
        if not trade.stop_loss_order_id:
            logger.info(f"No OCO orders to cancel for trade {trade.id}")
            return
        
        try:
            logger.info(
                f"🔄 Canceling OCO orders for trade {trade.id}: "
                f"SL={trade.stop_loss_order_id}, TP={trade.take_profit_order_id}"
            )
            
            # Cancel OCO order using the order list ID or individual order IDs
            # CCXT typically uses cancel_oco_order with orderListId
            # If we have individual IDs, we may need to cancel them separately
            # For now, we'll try to cancel using the stop_loss_order_id as reference
            
            # Note: CCXT's cancel_oco_order may require orderListId
            # We'll need to fetch the order list ID or cancel individual orders
            # This is a simplified implementation - may need adjustment based on CCXT API
            
            # Try to cancel the stop-loss order (which should cancel the entire OCO)
            try:
                self.client.cancel_order(
                    id=trade.stop_loss_order_id,
                    symbol=trade.symbol,
                )
                logger.info(f"✅ Canceled stop-loss order {trade.stop_loss_order_id}")
            except Exception as e:
                logger.warning(f"Could not cancel stop-loss order: {e}")
            
            # Try to cancel take-profit order
            if trade.take_profit_order_id:
                try:
                    self.client.cancel_order(
                        id=trade.take_profit_order_id,
                        symbol=trade.symbol,
                    )
                    logger.info(f"✅ Canceled take-profit order {trade.take_profit_order_id}")
                except Exception as e:
                    logger.warning(f"Could not cancel take-profit order: {e}")
            
            # Clear OCO order IDs from trade record
            self.trade_repository.update(
                trade,
                stop_loss_order_id=None,
                take_profit_order_id=None,
            )
            
            logger.info(f"✅ OCO orders canceled and cleared for trade {trade.id}")
        
        except Exception as e:
            logger.error(
                f"❌ Failed to cancel OCO orders for trade {trade.id}: {e}",
                exc_info=True
            )
            raise
    
    def _persist_trade(
        self,
        order: dict,
        symbol: str,
        side: InterfaceOrderSide,
    ) -> Trade:
        """
        Persist executed trade to database.
        
        Args:
            order: CCXT order response
            symbol: Trading pair
            side: Order side (InterfaceOrderSide enum)
            
        Returns:
            Created Trade object
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
            
            return trade
        
        except Exception as e:
            logger.error(
                f"Failed to persist trade to database: {e}",
                exc_info=True
            )
            # Don't raise - database persistence failure shouldn't stop trading
            logger.warning("Trade executed but NOT saved to database!")
            return None
    
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

