"""
Live trading bot orchestrator.

Coordinates data fetching, signal generation, position management,
and order execution in a continuous loop.
"""
import logging
import time
from datetime import datetime
from typing import Optional

from app.config.models import BotConfig
from app.core.interfaces import IDataHandler, IExecutor, BaseStrategy
from app.core.enums import OrderSide, OrderType
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository

# Setup logging
logger = logging.getLogger(__name__)


class TradingBot:
    """
    Main trading bot orchestrator for live trading.
    
    Coordinates the full trading cycle:
    1. Fetch latest market data
    2. Calculate indicators and generate signals
    3. Check current position
    4. Execute trades based on signal changes
    5. Persist signals to database
    
    Designed to run continuously in production with robust error handling.
    """
    
    def __init__(
        self,
        config: BotConfig,
        data_handler: IDataHandler,
        strategy: BaseStrategy,
        executor: IExecutor,
        trade_repo: TradeRepository,
        signal_repo: SignalRepository,
    ):
        """
        Initialize the trading bot with all dependencies.
        
        Args:
            config: Bot configuration (symbol, timeframe, risk params, etc.)
            data_handler: Data handler for fetching market data
            strategy: Trading strategy for signal generation
            executor: Order executor (mock or real exchange)
            trade_repo: Repository for persisting trades
            signal_repo: Repository for persisting signals
        """
        self.config = config
        self.data_handler = data_handler
        self.strategy = strategy
        self.executor = executor
        self.trade_repo = trade_repo
        self.signal_repo = signal_repo
        
        # Extract configuration
        self.symbol = config.strategy.symbol
        self.timeframe = config.strategy.timeframe
        
        # Calculate required buffer size for indicators
        # Use the larger of the two windows + some buffer
        slow_window = config.strategy.params.get('slow_window', 50)
        self.buffer_size = slow_window + 20  # Extra buffer for safety
        
        # Track last signal to avoid duplicate trades
        self.last_signal_value: Optional[int] = None
        
        logger.info(f"TradingBot initialized for {self.symbol} on {self.timeframe} timeframe")
        logger.info(f"Strategy: {config.strategy.name}, Buffer size: {self.buffer_size}")
    
    def run_once(self) -> None:
        """
        Execute one iteration of the trading loop.
        
        This method:
        1. Fetches latest market data (with buffer for indicators)
        2. Calculates indicators using the strategy
        3. Generates trading signals
        4. Extracts the latest signal
        5. Checks current position
        6. Executes trades if signal conflicts with position
        7. Persists signal to database
        
        Raises:
            Exception: Any errors during execution are propagated to caller
        """
        logger.info(f"--- Starting trading cycle for {self.symbol} ---")
        
        # 1. Fetch latest N candles (buffer needed for indicators)
        logger.info(f"Fetching last {self.buffer_size} candles...")
        df = self.data_handler.get_historical_data(
            symbol=self.symbol,
            timeframe=self.timeframe,
            limit=self.buffer_size,
        )
        
        if df.empty:
            logger.warning("No data received from data handler. Skipping cycle.")
            return
        
        logger.info(f"Received {len(df)} candles. Latest: {df.index[-1]}")
        
        # 2. Calculate indicators
        logger.info("Calculating indicators...")
        df = self.strategy.calculate_indicators(df)
        
        # 3. Generate signals
        logger.info("Generating signals...")
        df = self.strategy.generate_signals(df)
        
        # 4. Get the LATEST signal (last row)
        latest_signal = int(df['signal'].iloc[-1])
        latest_close = float(df['close'].iloc[-1])
        latest_timestamp = df.index[-1]
        
        logger.info(
            f"Latest signal: {latest_signal} "
            f"(1=BUY, -1=SELL, 0=NEUTRAL) at {latest_timestamp}, "
            f"price: {latest_close:.2f}"
        )
        
        # 5. Check current position
        position = self.executor.get_position(self.symbol)
        net_position = position['net_quantity']
        is_flat = position['is_flat']
        
        logger.info(
            f"Current position: {net_position:.4f} "
            f"({'FLAT' if is_flat else 'LONG' if net_position > 0 else 'SHORT'})"
        )
        
        # 6. Trading logic: Execute if signal conflicts with position
        self._execute_trading_logic(
            signal=latest_signal,
            net_position=net_position,
            is_flat=is_flat,
            price=latest_close,
        )
        
        # 7. Persist signal to database (track all signals for analysis)
        self._save_signal(
            signal_value=latest_signal,
            timestamp=latest_timestamp,
            price=latest_close,
            indicators=self._extract_indicators(df),
        )
        
        logger.info("--- Trading cycle complete ---\n")
    
    def _execute_trading_logic(
        self,
        signal: int,
        net_position: float,
        is_flat: bool,
        price: float,
    ) -> None:
        """
        Execute trading logic based on signal and current position.
        
        Rules:
        - Signal 1 (BUY) + Flat position → Execute BUY
        - Signal -1 (SELL) + Long position → Execute SELL (close position)
        - Signal 0 (NEUTRAL) → No action
        - Avoid duplicate trades if signal unchanged
        
        Args:
            signal: Signal value (1=BUY, -1=SELL, 0=NEUTRAL)
            net_position: Current net position quantity
            is_flat: True if position is flat
            price: Current market price
        """
        # Check if signal has changed (avoid duplicate trades)
        if signal == self.last_signal_value:
            logger.info("Signal unchanged. No action needed.")
            return
        
        # Update last signal
        self.last_signal_value = signal
        
        # Determine if we should execute
        should_execute = False
        side = None
        reason = ""
        
        if signal == 1 and is_flat:
            # BUY signal with flat position → Open long
            should_execute = True
            side = OrderSide.BUY
            reason = "BUY signal with flat position"
        
        elif signal == -1 and net_position > 0:
            # SELL signal with long position → Close long
            should_execute = True
            side = OrderSide.SELL
            reason = "SELL signal with long position (closing)"
        
        elif signal == 0:
            # NEUTRAL signal → No action
            logger.info("NEUTRAL signal. Holding position.")
            return
        
        else:
            # Other cases: log but don't execute
            logger.info(
                f"Signal {signal} does not require action with current position. "
                f"(net_position={net_position:.4f})"
            )
            return
        
        # Execute order if needed
        if should_execute and side is not None:
            logger.info(f"EXECUTING TRADE: {reason}")
            
            # Calculate quantity from config
            quantity = self._calculate_order_quantity(price)
            
            try:
                order = self.executor.execute_order(
                    symbol=self.symbol,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                    price=price,
                )
                
                logger.info(
                    f"✅ Order executed successfully: "
                    f"{side.value} {quantity} {self.symbol} @ {price:.2f}"
                )
                logger.info(f"Order ID: {order['id']}, Status: {order['status']}")
                
            except Exception as e:
                logger.error(f"❌ Failed to execute order: {e}", exc_info=True)
                raise
    
    def _calculate_order_quantity(self, price: float) -> float:
        """
        Calculate order quantity based on risk parameters.
        
        For now, uses max_position_size_usd from config.
        Future: Can be enhanced with more sophisticated risk management.
        
        Args:
            price: Current market price
            
        Returns:
            Order quantity in base currency
        """
        max_position_usd = self.config.risk.max_position_size_usd
        quantity = max_position_usd / price
        
        logger.info(
            f"Calculated order quantity: {quantity:.6f} "
            f"(${max_position_usd} / ${price:.2f})"
        )
        
        return quantity
    
    def _extract_indicators(self, df) -> dict:
        """
        Extract indicator values from the latest row for signal metadata.
        
        Args:
            df: DataFrame with indicators
            
        Returns:
            Dictionary of indicator values
        """
        indicators = {}
        
        # Extract SMA values if they exist
        if 'sma_fast' in df.columns:
            indicators['sma_fast'] = float(df['sma_fast'].iloc[-1])
        if 'sma_slow' in df.columns:
            indicators['sma_slow'] = float(df['sma_slow'].iloc[-1])
        
        # Extract price
        if 'close' in df.columns:
            indicators['close'] = float(df['close'].iloc[-1])
        
        return indicators
    
    def _save_signal(
        self,
        signal_value: int,
        timestamp: datetime,
        price: float,
        indicators: dict,
    ) -> None:
        """
        Persist signal to database for historical analysis.
        
        Args:
            signal_value: Signal value (1, -1, or 0)
            timestamp: Signal timestamp
            price: Market price at signal
            indicators: Indicator values that generated the signal
        """
        try:
            signal = self.signal_repo.create(
                symbol=self.symbol,
                signal_value=signal_value,
                signal_metadata=indicators,
                timestamp=timestamp,
            )
            logger.info(f"Signal saved to database (ID: {signal.id})")
        except Exception as e:
            logger.error(f"Failed to save signal to database: {e}", exc_info=True)
            # Don't raise - signal persistence failure shouldn't stop trading
    
    def start(self, sleep_seconds: int = 60) -> None:
        """
        Start the live trading loop.
        
        Runs continuously until interrupted (Ctrl+C) or fatal error.
        Each iteration:
        1. Executes run_once()
        2. Handles exceptions gracefully (logs but doesn't crash)
        3. Sleeps before next iteration
        
        Args:
            sleep_seconds: Seconds to sleep between iterations (default: 60)
        """
        logger.info("=" * 70)
        logger.info("🚀 Starting Live Trading Bot")
        logger.info("=" * 70)
        logger.info(f"Symbol: {self.symbol}")
        logger.info(f"Timeframe: {self.timeframe}")
        logger.info(f"Sleep interval: {sleep_seconds}s")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 70)
        
        iteration = 0
        
        try:
            while True:
                iteration += 1
                logger.info(f"\n{'#' * 70}")
                logger.info(f"Iteration #{iteration} - {datetime.now()}")
                logger.info(f"{'#' * 70}")
                
                try:
                    # Execute one trading cycle
                    self.run_once()
                    
                except Exception as e:
                    # Log error but don't crash - bot should keep running
                    logger.error(
                        f"❌ Error in trading cycle: {e}",
                        exc_info=True
                    )
                    logger.error("Bot will retry on next iteration...")
                
                # Sleep before next iteration
                logger.info(f"⏳ Waiting {sleep_seconds}s for next bar...")
                time.sleep(sleep_seconds)
        
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 70)
            logger.info("🛑 Bot stopped by user (Ctrl+C)")
            logger.info("=" * 70)
        
        except Exception as e:
            logger.critical(
                f"💥 FATAL ERROR - Bot crashed: {e}",
                exc_info=True
            )
            raise

