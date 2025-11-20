import argparse
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

import ccxt

from app.config.models import BotConfig, ExchangeConfig
from app.data.handler import CryptoDataHandler
from app.strategies.sma_cross import SmaCrossStrategy
from app.backtesting.engine import Backtester


def load_config(config_path: Path) -> BotConfig:
    """
    Load configuration from JSON file and overlay environment variables.
    
    Environment variables take precedence over config.json values:
    - BINANCE_API_KEY: Overrides exchange.api_key
    - BINANCE_SECRET: Overrides exchange.api_secret
    - BINANCE_SANDBOX: Overrides exchange.sandbox_mode
    
    This allows keeping config.json clean while injecting secrets from the environment.
    
    Args:
        config_path: Path to the config.json file
        
    Returns:
        BotConfig with environment variable overrides applied
    """
    with config_path.open() as fp:
        data = json.load(fp)
    
    # Overlay environment variables if present
    env_api_key = os.getenv("BINANCE_API_KEY")
    env_secret = os.getenv("BINANCE_SECRET")
    env_sandbox = os.getenv("BINANCE_SANDBOX")
    
    if env_api_key is not None:
        data['exchange']['api_key'] = env_api_key
    
    if env_secret is not None:
        data['exchange']['api_secret'] = env_secret
    
    if env_sandbox is not None:
        # Convert string to boolean
        data['exchange']['sandbox_mode'] = env_sandbox.lower() in ('true', '1', 'yes')
    
    return BotConfig(**data)


def build_exchange(exchange_cfg: ExchangeConfig) -> ccxt.Exchange:
    try:
        exchange_class = getattr(ccxt, exchange_cfg.name)
    except AttributeError as exc:
        raise ValueError(f"Exchange '{exchange_cfg.name}' is not supported by ccxt.") from exc
    
    exchange_params = {
        "enableRateLimit": True,
        "options": {
            "fetchCurrencies": False,
            "defaultType": "spot"
        }
    }

    api_key = exchange_cfg.api_key.get_secret_value()
    secret = exchange_cfg.api_secret.get_secret_value()

    if api_key and len(api_key.strip()) > 0 and secret and len(secret.strip()) > 0:
        exchange_params["apiKey"] = api_key
        exchange_params["secret"] = secret

    exchange = exchange_class(exchange_params)

    if exchange_cfg.sandbox_mode:
        exchange.set_sandbox_mode(True)
    return exchange


def parse_params(params_str: str) -> Dict[str, Any]:
    """
    Parse parameter string into a dictionary.
    Supports two formats:
    1. JSON string: '{"fast_window": 20, "slow_window": 60}'
    2. Key=value pairs: 'fast_window=20,slow_window=60' or 'fast_window=20 slow_window=60'
    
    Returns:
        Dict with parameter names and values (auto-converts to int/float when possible)
    """
    params_str = params_str.strip()
    
    # Try parsing as JSON first
    if params_str.startswith('{'):
        try:
            return json.loads(params_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format in --params: {e}")
    
    # Parse as key=value pairs
    params = {}
    # Split by comma or space
    pairs = params_str.replace(',', ' ').split()
    
    for pair in pairs:
        if '=' not in pair:
            raise ValueError(f"Invalid parameter format: '{pair}'. Expected 'key=value'")
        
        key, value = pair.split('=', 1)
        key = key.strip()
        value = value.strip()
        
        # Try to convert to number
        try:
            # Try int first
            if '.' not in value:
                params[key] = int(value)
            else:
                params[key] = float(value)
        except ValueError:
            # Keep as string if not a number
            params[key] = value
    
    return params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a backtest for the configured strategy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic backtest with config defaults
  python run_backtest.py --start 2024-01-01 --end 2024-06-01
  
  # Override parameters with JSON
  python run_backtest.py --start 2024-01-01 --end 2024-06-01 --params '{"fast_window": 20, "slow_window": 60}'
  
  # Override parameters with key=value pairs
  python run_backtest.py --start 2024-01-01 --end 2024-06-01 --params 'fast_window=20,slow_window=60'
        """
    )
    parser.add_argument("--start", required=True, help="Start date (e.g., 2024-01-01)")
    parser.add_argument("--end", required=True, help="End date (e.g., 2024-06-01)")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "settings" / "config.json"),
        help="Path to the bot configuration file.",
    )
    parser.add_argument(
        "--params",
        type=str,
        default=None,
        help="Override strategy parameters. Accepts JSON string or key=value pairs (e.g., 'fast_window=20,slow_window=60')",
    )
    return parser.parse_args()


def overlay_params(config: BotConfig, param_overrides: Dict[str, Any]) -> BotConfig:
    """
    Overlay CLI parameter overrides onto the config.
    
    Creates a new config object with updated strategy parameters,
    preserving all other config values.
    
    Args:
        config: Original BotConfig
        param_overrides: Dict of parameters to override
        
    Returns:
        New BotConfig with overlaid parameters
    """
    if not param_overrides:
        return config
    
    # Convert config to dict
    config_dict = config.model_dump()
    
    # Overlay parameters
    config_dict['strategy']['params'].update(param_overrides)
    
    # Reconstruct config
    return BotConfig(**config_dict)


def save_results(
    results: Dict[str, Any],
    config: BotConfig,
    start_date: str,
    end_date: str,
    results_dir: Path,
) -> Path:
    """
    Save backtest results to JSON file.
    
    Args:
        results: Backtest results including metrics and data
        config: Final config used for the backtest
        start_date: Start date string
        end_date: End date string
        results_dir: Directory to save results
        
    Returns:
        Path to the saved results file
    """
    results_dir.mkdir(exist_ok=True)
    
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    strategy_name = config.strategy.name
    filename = f"backtest_{strategy_name}_{timestamp}.json"
    filepath = results_dir / filename
    
    # Extract equity curve from DataFrame
    df = results["data"]
    equity_curve = df["equity_curve"].tolist()
    
    # Extract metrics (everything except 'data')
    metrics = {k: v for k, v in results.items() if k != "data"}
    
    # Prepare output
    output = {
        "metadata": {
            "timestamp": timestamp,
            "start_date": start_date,
            "end_date": end_date,
        },
        "metrics": metrics,
        "params": config.strategy.params,
        "config": config.model_dump(),
        "equity_curve": equity_curve,
    }
    
    # Save to file
    with filepath.open('w') as f:
        json.dump(output, f, indent=2, default=str)
    
    return filepath


def print_mission_report(
    metrics: Dict[str, float],
    params: Dict[str, Any],
    start_date: str,
    end_date: str,
    strategy_name: str,
    saved_path: Path,
) -> None:
    """
    Print a clean mission report with backtest results.
    
    Args:
        metrics: Dictionary of performance metrics
        params: Final parameters used
        start_date: Start date string
        end_date: End date string
        strategy_name: Name of the strategy
        saved_path: Path where results were saved
    """
    print("\n" + "="*70)
    print("🚀 BACKTEST MISSION REPORT".center(70))
    print("="*70)
    
    # Header info
    print(f"\n📅 Period: {start_date} → {end_date}")
    print(f"📊 Strategy: {strategy_name}")
    
    # Parameters section
    print("\n" + "-"*70)
    print("⚙️  PARAMETERS USED".center(70))
    print("-"*70)
    max_key_len = max(len(str(k)) for k in params.keys()) if params else 0
    for key, value in params.items():
        print(f"  {key:<{max_key_len}} : {value}")
    
    # Metrics section
    print("\n" + "-"*70)
    print("📈 PERFORMANCE METRICS".center(70))
    print("-"*70)
    
    # Format metrics nicely
    metric_labels = {
        "total_return": "Total Return",
        "sharpe_ratio": "Sharpe Ratio",
        "max_drawdown": "Max Drawdown",
    }
    
    for key, value in metrics.items():
        label = metric_labels.get(key, key.replace('_', ' ').title())
        
        # Format based on metric type
        if 'return' in key.lower() or 'drawdown' in key.lower():
            formatted = f"{value:>10.2%}"
        else:
            formatted = f"{value:>10.4f}"
        
        # Add emoji indicators
        if 'return' in key.lower():
            emoji = "📈" if value > 0 else "📉"
        elif 'sharpe' in key.lower():
            emoji = "⭐" if value > 1 else "⚠️"
        elif 'drawdown' in key.lower():
            emoji = "🔻"
        else:
            emoji = "  "
        
        print(f"  {emoji} {label:<20} : {formatted}")
    
    # Footer
    print("\n" + "-"*70)
    print(f"💾 Results saved to: {saved_path}")
    print("="*70 + "\n")


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    # Load base config
    config = load_config(config_path)
    
    # Parse and overlay CLI parameters if provided
    if args.params:
        param_overrides = parse_params(args.params)
        print(f"\n🔧 Overlaying parameters: {param_overrides}")
        config = overlay_params(config, param_overrides)
    
    # Build exchange and components
    exchange = build_exchange(config.exchange)
    data_handler = CryptoDataHandler(exchange)
    strategy = SmaCrossStrategy(config.strategy)
    backtester = Backtester(
        data_handler=data_handler,
        strategy=strategy,
        symbol=config.strategy.symbol,
        timeframe=config.strategy.timeframe,
    )

    # Run backtest
    print(f"\n🔄 Running backtest: {args.start} → {args.end}")
    result = backtester.run(start_date=args.start, end_date=args.end)
    
    # Extract metrics and data
    metrics = {k: v for k, v in result.items() if k != "data"}
    
    # Save results
    results_dir = Path(__file__).parent / "results"
    saved_path = save_results(
        results=result,
        config=config,
        start_date=args.start,
        end_date=args.end,
        results_dir=results_dir,
    )
    
    # Print mission report
    print_mission_report(
        metrics=metrics,
        params=config.strategy.params,
        start_date=args.start,
        end_date=args.end,
        strategy_name=config.strategy.name,
        saved_path=saved_path,
    )


if __name__ == "__main__":
    main()

