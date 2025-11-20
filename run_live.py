#!/usr/bin/env python3
"""
Live trading runner for the trading bot.

This script orchestrates the full dependency injection chain and starts
the live trading loop with paper trading (MockExecutor) or real execution.

Usage:
    python run_live.py [--config path/to/config.json] [--mode mock|live]
"""
import argparse
import logging
import sys
from pathlib import Path

from app.config.models import BotConfig
from app.core.database import init_db, db
from app.core.bot import TradingBot
from app.data.handler import CryptoDataHandler
from app.strategies.sma_cross import SmaCrossStrategy
from app.execution.mock_executor import MockExecutor
from app.repositories.trade_repository import TradeRepository
from app.repositories.signal_repository import SignalRepository


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the live trading bot with paper or real execution."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "settings" / "config.json"),
        help="Path to the bot configuration file (default: settings/config.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "live"],
        default="mock",
        help="Execution mode: 'mock' for paper trading, 'live' for real execution (default: mock)",
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


def create_strategy(config: BotConfig) -> SmaCrossStrategy:
    """
    Create and initialize the trading strategy.
    
    Args:
        config: Bot configuration
        
    Returns:
        Initialized strategy instance
    """
    logger.info("Creating strategy...")
    
    # For now, we only support SMA Cross strategy
    if config.strategy.name.lower() != "sma_cross":
        raise ValueError(
            f"Unsupported strategy: {config.strategy.name}. "
            "Only 'sma_cross' is currently implemented."
        )
    
    strategy = SmaCrossStrategy(config.strategy)
    logger.info(
        f"Strategy created: {config.strategy.name} "
        f"(fast={config.strategy.params.get('fast_window')}, "
        f"slow={config.strategy.params.get('slow_window')})"
    )
    return strategy


def create_executor(mode: str, config: BotConfig) -> MockExecutor:
    """
    Create the order executor based on mode.
    
    Args:
        mode: Execution mode ('mock' or 'live')
        config: Bot configuration
        
    Returns:
        Executor instance (MockExecutor for now)
        
    Note:
        'live' mode not yet implemented - will create BinanceExecutor in future.
    """
    logger.info(f"Creating executor in '{mode}' mode...")
    
    if mode == "live":
        logger.warning(
            "⚠️  Live mode not yet implemented! "
            "Falling back to mock mode (paper trading)."
        )
        mode = "mock"
    
    # Create executor with repositories
    with db.session_scope() as session:
        trade_repo = TradeRepository(session)
        signal_repo = SignalRepository(session)
        executor = MockExecutor(trade_repo, signal_repo)
    
    logger.info(f"Executor created: MockExecutor (paper trading)")
    return executor


def create_bot(
    config: BotConfig,
    data_handler: CryptoDataHandler,
    strategy: SmaCrossStrategy,
    executor: MockExecutor,
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
        strategy = create_strategy(config)
        
        # 5. Create executor
        executor = create_executor(args.mode, config)
        
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

