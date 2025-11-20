"""
Mock executor for paper trading with database persistence.

Simulates order execution without connecting to real exchanges,
while persisting all trades to the database for analysis and tracking.
"""
from datetime import datetime
from typing import Optional, Dict
import uuid

from app.core.interfaces import IExecutor
from app.core.enums import OrderSide as InterfaceOrderSide, OrderType
from app.models.sql import OrderSide as ModelOrderSide
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository


class MockExecutor(IExecutor):
    """
    Mock executor for paper trading.
    
    Simulates order execution with 100% fill rate and persists all
    trades to the database. Tracks positions by calculating net quantity
    from historical trades.
    
    This executor is designed for paper trading and testing, providing
    realistic trade simulation without connecting to live exchanges.
    """
    
    def __init__(
        self,
        trade_repository: TradeRepository,
        signal_repository: Optional[SignalRepository] = None,
    ):
        """
        Initialize the mock executor with repository dependencies.
        
        Args:
            trade_repository: Repository for persisting and querying trades
            signal_repository: Optional repository for signal tracking
        """
        self.trade_repository = trade_repository
        self.signal_repository = signal_repository
        
        # In-memory position cache for fast access
        # Format: {symbol: net_quantity}
        self._position_cache: Dict[str, float] = {}
    
    def execute_order(
        self,
        symbol: str,
        side: InterfaceOrderSide,
        quantity: float,
        order_type: OrderType,
        price: Optional[float] = None,
    ) -> dict:
        """
        Execute a simulated order and persist to database.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            side: Order side (BUY or SELL)
            quantity: Quantity to trade (in base currency)
            order_type: Order type (MARKET or LIMIT)
            price: Optional execution price. If None, uses a simulated price
            
        Returns:
            Dictionary mimicking CCXT order structure with:
                - id: Unique order ID
                - symbol: Trading pair
                - side: Order side ('buy' or 'sell')
                - type: Order type ('market' or 'limit')
                - price: Execution price
                - amount: Order quantity
                - filled: Filled quantity (always 100% for mock)
                - remaining: Remaining quantity (always 0 for mock)
                - status: Order status (always 'closed' for mock)
                - timestamp: Execution timestamp (ms)
                - datetime: ISO format datetime
        """
        # Convert interface enum to model enum
        model_side = self._convert_order_side(side)
        
        # If no price provided, use a simulated price
        # In real paper trading, this would come from live market data
        if price is None:
            price = self._get_simulated_price(symbol)
        
        # Generate unique order ID
        order_id = str(uuid.uuid4())
        
        # Create timestamp
        now = datetime.utcnow()
        timestamp_ms = int(now.timestamp() * 1000)
        
        # Persist trade to database
        trade = self.trade_repository.create(
            symbol=symbol,
            side=model_side,
            price=price,
            quantity=quantity,
            pnl=None,  # PnL calculated later when closing position
            timestamp=now,
        )
        
        # Update position cache
        self._update_position_cache(symbol, side, quantity)
        
        # Return CCXT-like order structure
        return {
            "id": order_id,
            "clientOrderId": None,
            "symbol": symbol,
            "side": side.value.lower(),  # 'buy' or 'sell'
            "type": order_type.value.lower(),  # 'market' or 'limit'
            "price": price,
            "amount": quantity,
            "cost": price * quantity,
            "average": price,
            "filled": quantity,  # 100% fill for mock
            "remaining": 0.0,  # Always fully filled
            "status": "closed",  # Always immediately filled
            "fee": None,  # Fees not simulated in basic mock
            "trades": None,
            "timestamp": timestamp_ms,
            "datetime": now.isoformat(),
            "lastTradeTimestamp": timestamp_ms,
            "info": {
                "trade_db_id": trade.id,
                "simulated": True,
            },
        }
    
    def get_position(self, symbol: str) -> Dict[str, float]:
        """
        Get current position for a symbol.
        
        Calculates net position by summing all BUY and SELL trades from
        the database. Positive values indicate a long position, negative
        values indicate a short position.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            
        Returns:
            Dictionary with position information:
                - net_quantity: Net position (positive=long, negative=short)
                - total_buys: Total quantity bought
                - total_sells: Total quantity sold
                - is_flat: True if no position (net_quantity == 0)
        """
        # Check cache first
        if symbol in self._position_cache:
            net_quantity = self._position_cache[symbol]
        else:
            # Calculate from database
            net_quantity = self._calculate_net_position(symbol)
            self._position_cache[symbol] = net_quantity
        
        # Calculate detailed position info
        trades = self.trade_repository.get_by_symbol(symbol)
        total_buys = sum(
            t.quantity for t in trades 
            if t.side == ModelOrderSide.BUY
        )
        total_sells = sum(
            t.quantity for t in trades 
            if t.side == ModelOrderSide.SELL
        )
        
        return {
            "symbol": symbol,
            "net_quantity": net_quantity,
            "total_buys": total_buys,
            "total_sells": total_sells,
            "is_flat": abs(net_quantity) < 1e-8,  # Account for floating point precision
        }
    
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
    
    def _get_simulated_price(self, symbol: str) -> float:
        """
        Generate a simulated price for testing.
        
        In a real paper trading system, this would fetch the current
        market price from the exchange. For now, returns a default price.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Simulated price
        """
        # Simple simulation: return different prices for different symbols
        if "BTC" in symbol:
            return 50000.0
        elif "ETH" in symbol:
            return 3000.0
        else:
            return 100.0
    
    def _calculate_net_position(self, symbol: str) -> float:
        """
        Calculate net position from database trades.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Net quantity (buys - sells)
        """
        trades = self.trade_repository.get_by_symbol(symbol)
        
        net_quantity = 0.0
        for trade in trades:
            if trade.side == ModelOrderSide.BUY:
                net_quantity += trade.quantity
            elif trade.side == ModelOrderSide.SELL:
                net_quantity -= trade.quantity
        
        return net_quantity
    
    def _update_position_cache(
        self,
        symbol: str,
        side: InterfaceOrderSide,
        quantity: float,
    ) -> None:
        """
        Update the in-memory position cache.
        
        Args:
            symbol: Trading pair
            side: Order side
            quantity: Trade quantity
        """
        if symbol not in self._position_cache:
            self._position_cache[symbol] = 0.0
        
        if side == InterfaceOrderSide.BUY:
            self._position_cache[symbol] += quantity
        elif side == InterfaceOrderSide.SELL:
            self._position_cache[symbol] -= quantity
    
    def reset_position_cache(self) -> None:
        """
        Clear the position cache and force recalculation from database.
        
        Useful for testing or when database is modified externally.
        """
        self._position_cache.clear()

