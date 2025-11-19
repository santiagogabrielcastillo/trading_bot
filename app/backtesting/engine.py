import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, Union

from app.core.interfaces import IDataHandler, BaseStrategy


class Backtester:
    """
    Vectorized backtesting engine that evaluates strategy performance
    over a historical window fetched from an IDataHandler.
    """

    def __init__(
        self,
        data_handler: IDataHandler,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        initial_capital: float = 1.0,
        risk_free_rate: float = 0.0,
    ) -> None:
        self.data_handler = data_handler
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate

    def run(
        self,
        start_date: Union[str, datetime, pd.Timestamp],
        end_date: Union[str, datetime, pd.Timestamp],
    ) -> Dict[str, Union[float, pd.DataFrame]]:
        """
        Execute the backtest between the provided dates.
        """

        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)

        limit = self._estimate_limit(start_ts, end_ts)
        df = self.data_handler.get_historical_data(
            symbol=self.symbol,
            timeframe=self.timeframe,
            limit=limit,
        )

        df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()
        if df.empty:
            raise ValueError("No market data available for the requested window.")

        df = self.strategy.calculate_indicators(df)
        df = self.strategy.generate_signals(df)

        df["pct_change"] = df["close"].pct_change().fillna(0.0)
        df["shifted_signal"] = df["signal"].shift(1).fillna(0.0)
        df["strategy_return"] = df["shifted_signal"] * df["pct_change"]
        df["equity_curve"] = (1 + df["strategy_return"]).cumprod() * self.initial_capital

        metrics = self._compute_metrics(df)
        metrics["data"] = df
        return metrics

    def _compute_metrics(self, df: pd.DataFrame) -> Dict[str, float]:
        total_return = df["equity_curve"].iloc[-1] / self.initial_capital - 1

        # Assuming daily frequency for Sharpe, consistent with roadmap requirement.
        periods_per_year = 252
        return_series = df["strategy_return"]
        excess_return = return_series - (self.risk_free_rate / periods_per_year)

        avg_excess = excess_return.mean()
        std_dev = excess_return.std(ddof=0)
        sharpe_ratio = (
            np.sqrt(periods_per_year) * avg_excess / std_dev if std_dev > 0 else np.nan
        )

        rolling_max = df["equity_curve"].cummax()
        drawdown = df["equity_curve"] / rolling_max - 1
        max_drawdown = drawdown.min()

        return {
            "total_return": float(total_return),
            "sharpe_ratio": float(sharpe_ratio),
            "max_drawdown": float(max_drawdown),
        }

    def _estimate_limit(self, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> int:
        """
        Estimate the number of candles needed to cover the requested window.
        Adds a small buffer to ensure indicator warm-up.
        """
        minutes_per_candle = self._timeframe_to_minutes(self.timeframe)
        if minutes_per_candle is None:
            # Default fallback if timeframe is not parseable.
            return 2000

        window_minutes = max(int((end_ts - start_ts).total_seconds() // 60), 1)
        bars_needed = window_minutes // minutes_per_candle + 50  # buffer for indicators
        return max(int(bars_needed), 500)  # minimum sensible fetch size

    @staticmethod
    def _timeframe_to_minutes(timeframe: str) -> Optional[int]:
        """
        Convert a ccxt-style timeframe string (e.g., '1m', '1h', '1d')
        to the number of minutes represented by each candle.
        """

        unit_multipliers = {
            "m": 1,
            "h": 60,
            "d": 60 * 24,
            "w": 60 * 24 * 7,
        }

        try:
            value = int(timeframe[:-1])
            unit = timeframe[-1]
            return value * unit_multipliers[unit]
        except (ValueError, KeyError):
            return None

