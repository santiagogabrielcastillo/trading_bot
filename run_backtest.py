import argparse
import json
from pathlib import Path

import ccxt

from app.config.models import BotConfig, ExchangeConfig
from app.data.handler import CryptoDataHandler
from app.strategies.sma_cross import SmaCrossStrategy
from app.backtesting.engine import Backtester


def load_config(config_path: Path) -> BotConfig:
    with config_path.open() as fp:
        data = json.load(fp)
    return BotConfig(**data)


def build_exchange(exchange_cfg: ExchangeConfig) -> ccxt.Exchange:
    try:
        exchange_class = getattr(ccxt, exchange_cfg.name)
    except AttributeError as exc:
        raise ValueError(f"Exchange '{exchange_cfg.name}' is not supported by ccxt.") from exc

    exchange = exchange_class(
        {
            "apiKey": exchange_cfg.api_key.get_secret_value(),
            "secret": exchange_cfg.api_secret.get_secret_value(),
        }
    )
    if exchange_cfg.sandbox_mode:
        exchange.set_sandbox_mode(True)
    return exchange


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a backtest for the configured strategy.")
    parser.add_argument("--start", required=True, help="Start date (e.g., 2024-01-01)")
    parser.add_argument("--end", required=True, help="End date (e.g., 2024-06-01)")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "settings" / "config.json"),
        help="Path to the bot configuration file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = load_config(config_path)
    exchange = build_exchange(config.exchange)

    data_handler = CryptoDataHandler(exchange)
    strategy = SmaCrossStrategy(config.strategy)
    backtester = Backtester(
        data_handler=data_handler,
        strategy=strategy,
        symbol=config.strategy.symbol,
        timeframe=config.strategy.timeframe,
    )

    result = backtester.run(start_date=args.start, end_date=args.end)
    df = result["data"]
    metrics = {k: v for k, v in result.items() if k != "data"}

    print("\n=== Backtest Metrics ===")
    for key, value in metrics.items():
        print(f"{key}: {value:.4f}")

    print("\n=== Equity Curve Snapshot ===")
    print(df[["close", "signal", "equity_curve"]].tail())


if __name__ == "__main__":
    main()

