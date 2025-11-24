import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, Union
import logging

from app.core.interfaces import IDataHandler, BaseStrategy
from app.config.models import RiskConfig

logger = logging.getLogger(__name__)


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
        risk_config: Optional[RiskConfig] = None,
    ) -> None:
        self.data_handler = data_handler
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        self.risk_config = risk_config

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

        minutes_per_candle = self._timeframe_to_minutes(self.timeframe)
        if minutes_per_candle is None:
            buffer_minutes = 1000 * 60  # Default to 1000 hours if timeframe unknown
        else:
            buffer_minutes = 1000 * minutes_per_candle
        
        buffer_start = start_ts - pd.Timedelta(minutes=buffer_minutes)
        
        window_limit = self._estimate_limit(start_ts, end_ts)
        buffer_limit = 1000  # Buffer candles
        total_limit = window_limit + buffer_limit
        
        df = self.data_handler.get_historical_data(
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=buffer_start,
            end_date=end_ts,
            limit=total_limit,
        )

        if df.empty:
            raise ValueError("No market data available from the data handler.")

        # Calculate indicators on full dataset (including buffer)
        df = self.strategy.calculate_indicators(df)
        df = self.strategy.generate_signals(df)
        
        # Get the maximum lookback period required by strategy and filter
        max_lookback = self.strategy.max_lookback_period
        
        # Skip the warm-up period by slicing from max_lookback index
        # This ensures all indicators are fully calculated before signal processing
        if max_lookback > 0 and len(df) > max_lookback:
            df = df.iloc[max_lookback:].copy()
            logger.info(
                f"Skipped {max_lookback} initial candles for indicator warm-up. "
                f"Starting backtest at {df.index[0]}"
            )
        
        # NOW slice to the requested window (after indicators are calculated and warm-up skipped)
        df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()
        if df.empty:
            raise ValueError("No market data available for the requested window after indicator calculation.")

        # Enforce stop-loss and take-profit if risk_config is provided
        if self.risk_config is not None:
            df = self._enforce_sl_tp(df)
        
        df["pct_change"] = df["close"].pct_change().fillna(0.0)
        df["shifted_signal"] = df["signal"].shift(1).fillna(0.0)
        df["strategy_return"] = df["shifted_signal"] * df["pct_change"]
        df["equity_curve"] = (1 + df["strategy_return"]).cumprod() * self.initial_capital

        metrics = self._compute_metrics(df)
        metrics["data"] = df
        return metrics

    def _compute_metrics(self, df: pd.DataFrame) -> Dict[str, float]:
        total_return = df["equity_curve"].iloc[-1] / self.initial_capital - 1

        periods_per_year = self._calculate_periods_per_year()
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

    def _calculate_periods_per_year(self) -> int:
        """
        Calculate the number of periods per year based on the timeframe.
        Crypto markets are 24/7, so we use actual calendar periods.
        
        Examples:
            - '1h' -> 365 * 24 = 8760 periods/year
            - '1d' -> 365 periods/year
            - '1m' -> 365 * 24 * 60 = 525600 periods/year
        """
        minutes_per_candle = self._timeframe_to_minutes(self.timeframe)
        if minutes_per_candle is None:
            raise ValueError(
                f"Unknown timeframe '{self.timeframe}'. Cannot calculate annualization factor."
            )
        
        minutes_per_year = 365 * 24 * 60
        periods_per_year = minutes_per_year // minutes_per_candle
        
        return periods_per_year

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

    def _enforce_sl_tp(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enforce stop-loss and take-profit exits in backtesting.
        
        This method processes signals sequentially to track position state
        and override signals when SL/TP levels are hit.
        
        Args:
            df: DataFrame with signals already generated
            
        Returns:
            DataFrame with signals modified to include SL/TP exits
        """
        if df.empty:
            return df
        
        # Create a copy to avoid modifying original
        df = df.copy()
        
        # Track position state
        in_position = False
        entry_price = 0.0
        stop_loss_price = 0.0
        take_profit_price = 0.0
        entry_index = None
        
        # Track SL/TP exit statistics
        sl_exits = 0
        tp_exits = 0
        
        # Process each bar sequentially
        for idx in range(len(df)):
            current_price = df.iloc[idx]['close']
            current_signal = df.iloc[idx]['signal']
            
            # Check for SL/TP exit if in position
            if in_position:
                # Check stop-loss (price dropped to or below SL)
                if current_price <= stop_loss_price:
                    # Force exit via stop-loss
                    df.loc[df.index[idx], 'signal'] = -1
                    sl_exits += 1
                    logger.debug(
                        f"SL hit at {df.index[idx]}: price={current_price:.2f}, "
                        f"SL={stop_loss_price:.2f}, entry={entry_price:.2f}"
                    )
                    in_position = False
                    entry_price = 0.0
                    stop_loss_price = 0.0
                    take_profit_price = 0.0
                    continue
                
                # Check take-profit (price rose to or above TP)
                if current_price >= take_profit_price:
                    # Force exit via take-profit
                    df.loc[df.index[idx], 'signal'] = -1
                    tp_exits += 1
                    logger.debug(
                        f"TP hit at {df.index[idx]}: price={current_price:.2f}, "
                        f"TP={take_profit_price:.2f}, entry={entry_price:.2f}"
                    )
                    in_position = False
                    entry_price = 0.0
                    stop_loss_price = 0.0
                    take_profit_price = 0.0
                    continue
            
            # Handle entry signals
            if current_signal == 1 and not in_position:
                # BUY signal - enter position
                entry_price = current_price
                
                # Extract stop-loss from DataFrame if available (strategy-provided)
                if 'stop_loss_price' in df.columns:
                    sl_price = df.iloc[idx]['stop_loss_price']
                    if pd.notna(sl_price) and sl_price > 0:
                        stop_loss_price = float(sl_price)
                    else:
                        # Fallback to config-based SL
                        stop_loss_price = entry_price * (1 - self.risk_config.stop_loss_pct)
                else:
                    # Calculate from config
                    stop_loss_price = entry_price * (1 - self.risk_config.stop_loss_pct)
                
                # Calculate take-profit from config
                take_profit_price = entry_price * (1 + self.risk_config.take_profit_pct)
                
                in_position = True
                entry_index = idx
                
                logger.debug(
                    f"Position entered at {df.index[idx]}: entry={entry_price:.2f}, "
                    f"SL={stop_loss_price:.2f}, TP={take_profit_price:.2f}"
                )
            
            # Handle exit signals (strategy-generated SELL)
            elif current_signal == -1 and in_position:
                # SELL signal - exit position
                in_position = False
                entry_price = 0.0
                stop_loss_price = 0.0
                take_profit_price = 0.0
        
        # Log summary
        if sl_exits > 0 or tp_exits > 0:
            logger.info(
                f"Backtest SL/TP enforcement: {sl_exits} SL exits, {tp_exits} TP exits "
                f"out of {len(df)} bars"
            )
        
        return df
    
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

