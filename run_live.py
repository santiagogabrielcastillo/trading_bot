#!/usr/bin/env python3
"""
Live trading runner for the trading bot.

This script orchestrates the full dependency injection chain and starts
the live trading loop with paper trading (MockExecutor) or real execution.

The execution mode is determined by the 'execution_mode' field in config.json:
  - "paper": Paper trading with MockExecutor (safe, no real money)
  - "live": Real trading with BinanceExecutor (⚠️ REAL MONEY AT RISK!)

Usage:
    python run_live.py [--config path/to/config.json] [--sleep SECONDS]
    
Examples:
    # Paper trading (default)
    python run_live.py
    
    # Live trading (requires config.json with execution_mode: "live")
    python run_live.py --config settings/live_config.json
    
    # Custom sleep interval (30 seconds)
    python run_live.py --sleep 30
"""
import argparse
import logging
import sys
from pathlib import Path

from app.config.models import BotConfig
from app.core.database import init_db, db
from app.core.bot import TradingBot
from app.core.interfaces import IExecutor
from app.core.strategy_factory import create_strategy
from app.data.handler import CryptoDataHandler
from app.execution.mock_executor import MockExecutor
from app.execution.binance_executor import BinanceExecutor
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository
import ccxt


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    
    Note: Execution mode is now determined by config.execution_mode,
    not by a CLI argument.
    """
    parser = argparse.ArgumentParser(
        description="Run the live trading bot. Execution mode (paper/live) is set in config.json."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "settings" / "config.json"),
        help="Path to the bot configuration file (default: settings/config.json)",
    )
    parser.add_argument(
        "--sleep",
        type=int,
        default=60,
        help="Sleep interval between iterations in seconds (default: 60)",
    )
    return parser.parse_args()


def load_config(config_path: str) -> BotConfig:
    """
    Load bot configuration from JSON file.
    
    Args:
        config_path: Path to config.json
        
    Returns:
        Validated BotConfig instance
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config is invalid
    """
    logger.info(f"Loading configuration from: {config_path}")
    
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    config = BotConfig.load_from_file(str(config_file))
    logger.info(f"Configuration loaded successfully")
    logger.info(f"  Symbol: {config.strategy.symbol}")
    logger.info(f"  Timeframe: {config.strategy.timeframe}")
    logger.info(f"  Strategy: {config.strategy.name}")
    logger.info(f"  Database: {config.db_path}")
    logger.info(f"  Execution Mode: {config.execution_mode.upper()}")
    
    if config.execution_mode == "live":
        logger.warning("=" * 70)
        logger.warning("⚠️  WARNING: LIVE TRADING MODE CONFIGURED!")
        logger.warning("⚠️  REAL MONEY WILL BE AT RISK!")
        logger.warning("=" * 70)
    
    return config


def initialize_database(db_path: str) -> None:
    """
    Initialize the database for trade and signal persistence.
    
    Args:
        db_path: Path to SQLite database file
    """
    logger.info(f"Initializing database: {db_path}")
    init_db(db_path)
    logger.info("Database initialized successfully")


def create_data_handler(config: BotConfig) -> CryptoDataHandler:
    """
    Create and initialize the data handler.
    
    Args:
        config: Bot configuration
        
    Returns:
        Initialized CryptoDataHandler
    """
    logger.info("Creating data handler...")
    data_handler = CryptoDataHandler(config.exchange)
    logger.info(f"Data handler created for exchange: {config.exchange.name}")
    return data_handler


def create_strategy_from_config(config: BotConfig):
    """
    Create and initialize the trading strategy using the centralized factory.
    
    This function uses the strategy factory which handles:
    - Dynamic strategy class resolution
    - Optional market regime filter instantiation
    - Backward compatibility
    
    Args:
        config: Bot configuration
    
    Returns:
        Initialized strategy instance (may be SmaCrossStrategy, VolatilityAdjustedStrategy, etc.)
    """
    logger.info("Creating strategy...")
    
    try:
        strategy = create_strategy(config)
        
        # Log strategy details
        logger.info(f"Strategy created: {config.strategy.name}")
        logger.info(f"  Parameters: {config.strategy.params}")
        
        # Log filter status if present
        if config.regime_filter:
            logger.info(
                f"  Market Regime Filter: Enabled "
                f"(ADX window={config.regime_filter.adx_window}, "
                f"threshold={config.regime_filter.adx_threshold})"
            )
        else:
            logger.info("  Market Regime Filter: Disabled")
        
        return strategy
    
    except ValueError as e:
        logger.error(f"Failed to create strategy: {e}")
        raise


def create_executor(config: BotConfig) -> IExecutor:
    """
    Create the order executor based on configuration.
    
    Uses config.execution_mode to determine which executor to create:
    - "paper": MockExecutor for simulated trading
    - "live": BinanceExecutor for real money trading
    
    Args:
        config: Bot configuration
        
    Returns:
        Executor instance (MockExecutor or BinanceExecutor)
    """
    execution_mode = config.execution_mode
    logger.info(f"Creating executor in '{execution_mode}' mode...")
    
    with db.session_scope() as session:
        trade_repo = TradeRepository(session)
        signal_repo = SignalRepository(session)
        
        if execution_mode == "live":
            # ⚠️  LIVE TRADING MODE - REAL MONEY! ⚠️
            logger.warning("=" * 70)
            logger.warning("⚠️  ⚠️  ⚠️  LIVE TRADING MODE ENABLED ⚠️  ⚠️  ⚠️")
            logger.warning("⚠️  REAL MONEY AT RISK - USE WITH EXTREME CAUTION! ⚠️")
            logger.warning("=" * 70)
            
            # Create CCXT exchange instance
            try:
                exchange_class = getattr(ccxt, config.exchange.name)
                exchange = exchange_class({
                    'apiKey': config.exchange.api_key.get_secret_value(),
                    'secret': config.exchange.api_secret.get_secret_value(),
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'spot',  # spot trading
                    }
                })
                
                # Enable sandbox mode if configured
                if config.exchange.sandbox_mode:
                    logger.info("Sandbox mode enabled - using testnet")
                    exchange.set_sandbox_mode(True)
                else:
                    logger.warning("⚠️  PRODUCTION MODE - REAL MONEY! ⚠️")
                
                executor = BinanceExecutor(exchange, trade_repo)
                logger.info("✅ BinanceExecutor created (LIVE TRADING)")
            
            except Exception as e:
                logger.error(f"Failed to create BinanceExecutor: {e}")
                logger.error("Falling back to MockExecutor (paper trading)")
                executor = MockExecutor(trade_repo, signal_repo)
        
        else:
            # Paper trading mode (safe)
            executor = MockExecutor(trade_repo, signal_repo)
            logger.info("✅ MockExecutor created (paper trading)")
    
    return executor


def create_bot(
    config: BotConfig,
    data_handler: CryptoDataHandler,
    strategy,
    executor: IExecutor,
) -> TradingBot:
    """
    Create the TradingBot with all dependencies.
    
    Args:
        config: Bot configuration
        data_handler: Data handler instance
        strategy: Strategy instance
        executor: Executor instance
        
    Returns:
        Initialized TradingBot
    """
    logger.info("Creating TradingBot...")
    
    with db.session_scope() as session:
        trade_repo = TradeRepository(session)
        signal_repo = SignalRepository(session)
        
        bot = TradingBot(
            config=config,
            data_handler=data_handler,
            strategy=strategy,
            executor=executor,
            trade_repo=trade_repo,
            signal_repo=signal_repo,
        )
    
    logger.info("TradingBot created successfully")
    return bot


def main():
    """
    Main entry point for live trading.
    
    Orchestrates:
    1. Configuration loading
    2. Database initialization
    3. Dependency injection (data handler, strategy, executor, repositories)
    4. Bot creation
    5. Start trading loop
    """
    # Parse arguments
    args = parse_args()
    
    logger.info("=" * 70)
    logger.info("🤖 TRADING BOT - LIVE MODE")
    logger.info("=" * 70)
    
    try:
        # 1. Load configuration
        config = load_config(args.config)
        
        # 2. Initialize database
        initialize_database(config.db_path)
        
        # 3. Create data handler
        data_handler = create_data_handler(config)
        
        # 4. Create strategy
        strategy = create_strategy_from_config(config)
        
        # 5. Create executor (based on config.execution_mode)
        executor = create_executor(config)
        
        # 6. Create bot
        bot = create_bot(config, data_handler, strategy, executor)
        
        # 7. Start trading loop
        logger.info("=" * 70)
        logger.info("All components initialized successfully!")
        logger.info("Starting live trading loop...")
        logger.info("=" * 70)
        
        bot.start(sleep_seconds=args.sleep)
        
    except KeyboardInterrupt:
        logger.info("\n" + "=" * 70)
        logger.info("Bot stopped by user")
        logger.info("=" * 70)
        sys.exit(0)
    
    except Exception as e:
        logger.critical(f"💥 FATAL ERROR: {e}", exc_info=True)
        logger.critical("Bot cannot continue. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    main()

