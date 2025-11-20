import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import logging

import ccxt
import pandas as pd

# Importamos la interfaz que definimos previamente
from app.core.interfaces import IDataHandler

logger = logging.getLogger(__name__)

class CryptoDataHandler(IDataHandler):
    """
    Implementación concreta usando CCXT para obtener datos de mercado.
    Supports offline caching to CSV files for faster iteration and reproducibility.
    """
    
    def __init__(self, exchange: ccxt.Exchange, cache_dir: Optional[Path] = None):
        """
        Recibe una instancia ya configurada de ccxt.Exchange.
        Esto permite inyección de dependencias (facilita tests y cambios de exchange).
        
        Args:
            exchange: Configured ccxt.Exchange instance
            cache_dir: Optional path to cache directory. Defaults to 'data_cache' in project root.
        """
        self.exchange = exchange
        if cache_dir is None:
            # Default to project root / data_cache
            project_root = Path(__file__).parent.parent.parent
            cache_dir = project_root / "data_cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _sanitize_symbol(self, symbol: str) -> str:
        """
        Sanitize symbol name for use in filenames.
        Example: 'BTC/USDT' -> 'BTC_USDT'
        """
        return symbol.replace('/', '_')
    
    def _get_cache_path(self, symbol: str, timeframe: str) -> Path:
        """
        Generate cache file path for a given symbol and timeframe.
        """
        sanitized_symbol = self._sanitize_symbol(symbol)
        filename = f"{sanitized_symbol}_{timeframe}.csv"
        return self.cache_dir / filename
    
    def _save_to_csv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        """
        Save DataFrame to CSV cache file.
        """
        cache_path = self._get_cache_path(symbol, timeframe)
        df.to_csv(cache_path)
        logger.info(f"Saved {len(df)} candles to cache: {cache_path}")
    
    def _load_from_csv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Load DataFrame from CSV cache file if it exists.
        Returns None if file doesn't exist or can't be read.
        """
        cache_path = self._get_cache_path(symbol, timeframe)
        if not cache_path.exists():
            return None
        
        try:
            df = pd.read_csv(cache_path, index_col='timestamp', parse_dates=True)
            logger.info(f"Loaded {len(df)} candles from cache: {cache_path}")
            return df
        except Exception as e:
            logger.warning(f"Failed to load cache from {cache_path}: {e}")
            return None
    
    def _cache_covers_range(
        self,
        df: pd.DataFrame,
        start_ts: Optional[pd.Timestamp],
        end_ts: Optional[pd.Timestamp],
        limit: int,
    ) -> bool:
        """
        Check if cached data covers the requested window.
        For explicit date windows we ensure the cache fully spans
        [start_ts, end_ts]. Otherwise we fallback to a length check.
        """
        if start_ts is not None and end_ts is not None:
            cache_start = df.index.min()
            cache_end = df.index.max()
            return cache_start <= start_ts and cache_end >= end_ts
        return len(df) >= limit
    
    def get_historical_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Descarga velas históricas y devuelve un DataFrame formateado.
        
        Implements offline caching: checks for cached CSV first, only fetches from API
        if cache is missing or insufficient. New data overwrites the cache.
        
        Implements pagination to fetch large datasets beyond the exchange's single-request limit.
        For long backtests, this ensures we can fetch thousands of candles by making multiple
        API calls and concatenating the results.
        
        Fetches data going backwards from the most recent candle.
        """
        minutes_per_candle = self._timeframe_to_minutes(timeframe)
        start_ts = pd.to_datetime(start_date) if start_date is not None else None
        end_ts = pd.to_datetime(end_date) if end_date is not None else None

        if start_ts is not None and end_ts is not None and start_ts > end_ts:
            raise ValueError("start_date must be earlier than end_date.")

        # If no explicit window, derive one from limit so caching logic can reuse it.
        effective_start, effective_end = self._resolve_request_window(
            start_ts, end_ts, limit, minutes_per_candle
        )

        cached_df = self._load_from_csv(symbol, timeframe)
        if cached_df is not None and self._cache_covers_range(
            cached_df, effective_start, effective_end, limit
        ):
            if effective_start is not None and effective_end is not None:
                return cached_df.loc[
                    (cached_df.index >= effective_start) & (cached_df.index <= effective_end)
                ].copy()
            return cached_df.tail(limit).copy()
        
        if effective_start is not None:
            df_full = self._fetch_forward_range(
                symbol=symbol,
                timeframe=timeframe,
                start_ts=effective_start,
                end_ts=effective_end,
                limit=limit,
                minutes_per_candle=minutes_per_candle,
            )
        else:
            df_full = self._fetch_recent_range(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                minutes_per_candle=minutes_per_candle,
            )

        if df_full.empty:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        self._save_to_csv(df_full, symbol, timeframe)

        if effective_start is not None and effective_end is not None:
            return df_full.loc[
                (df_full.index >= effective_start) & (df_full.index <= effective_end)
            ].copy()
        return df_full.tail(limit).copy()

    def _resolve_request_window(
        self,
        start_ts: Optional[pd.Timestamp],
        end_ts: Optional[pd.Timestamp],
        limit: int,
        minutes_per_candle: Optional[int],
    ) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
        """
        Determine the effective [start, end] window for the request.
        If only start is provided we infer the end based on the limit.
        """
        if start_ts is None:
            return None, None

        if end_ts is None:
            duration_minutes = (minutes_per_candle or 60) * max(limit - 1, 1)
            end_ts = start_ts + pd.Timedelta(minutes=duration_minutes)

        return start_ts, end_ts

    def _fetch_forward_range(
        self,
        symbol: str,
        timeframe: str,
        start_ts: pd.Timestamp,
        end_ts: Optional[pd.Timestamp],
        limit: int,
        minutes_per_candle: Optional[int],
    ) -> pd.DataFrame:
        """
        Fetch candles going forward starting from start_ts until end_ts or limit candles.
        """
        max_per_request = self._max_per_request()
        since = int(start_ts.value // 10**6)
        target_candles = self._estimate_candles_needed(start_ts, end_ts, limit, minutes_per_candle)

        all_ohlcv = []
        total_fetched = 0
        end_ms = int(end_ts.value // 10**6) if end_ts is not None else None

        while total_fetched < target_candles:
            batch_size = min(max_per_request, target_candles - total_fetched)
            try:
                batch = self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=batch_size,
                )
            except Exception as e:
                if not all_ohlcv:
                    raise RuntimeError(f"Failed to fetch historical data: {e}") from e
                break

            if not batch:
                break

            all_ohlcv.extend(batch)
            total_fetched += len(batch)

            last_ts = batch[-1][0]
            if end_ms is not None and last_ts >= end_ms:
                break

            if len(batch) < batch_size:
                break

            ms_per_candle = (minutes_per_candle or 60) * 60 * 1000
            since = last_ts + ms_per_candle

            self._respect_rate_limit()

        return self._format_ohlcv_to_df(all_ohlcv)

    def _fetch_recent_range(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        minutes_per_candle: Optional[int],
    ) -> pd.DataFrame:
        """
        Fetch the most recent candles using backwards pagination (legacy behavior)
        when no explicit start date is supplied.
        """
        max_per_request = self._max_per_request()
        all_ohlcv = []
        remaining = limit
        since = None

        while remaining > 0:
            batch_size = min(remaining, max_per_request)
            try:
                batch = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=since,
                    limit=batch_size,
                )
            except Exception as e:
                if not all_ohlcv:
                    raise RuntimeError(f"Failed to fetch historical data: {e}") from e
                break

            if not batch:
                break

            all_ohlcv.extend(batch)
            remaining -= len(batch)

            if len(batch) < batch_size:
                break

            oldest_timestamp = batch[0][0]
            ms_per_candle = (minutes_per_candle or 60) * 60 * 1000
            since = oldest_timestamp - ms_per_candle

            self._respect_rate_limit()

        return self._format_ohlcv_to_df(all_ohlcv)

    def _max_per_request(self) -> int:
        if hasattr(self.exchange, 'options') and 'fetchOHLCVLimit' in self.exchange.options:
            return self.exchange.options['fetchOHLCVLimit']
        return 1000

    def _estimate_candles_needed(
        self,
        start_ts: pd.Timestamp,
        end_ts: Optional[pd.Timestamp],
        limit: int,
        minutes_per_candle: Optional[int],
    ) -> int:
        if end_ts is not None:
            total_minutes = max(int((end_ts - start_ts).total_seconds() // 60), 1)
            minutes_per_bar = minutes_per_candle or 60
            estimated = total_minutes // minutes_per_bar + 2
            return max(estimated, limit)
        return limit

    def _respect_rate_limit(self) -> None:
        if hasattr(self.exchange, 'rateLimit') and self.exchange.rateLimit > 0:
            time.sleep(max(0.1, self.exchange.rateLimit / 1000.0))

    def _format_ohlcv_to_df(self, all_ohlcv) -> pd.DataFrame:
        if not all_ohlcv:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        df = pd.DataFrame(
            all_ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'],
        )
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)
        return df
    
    @staticmethod
    def _timeframe_to_minutes(timeframe: str) -> int:
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

    def get_latest_bar(self, symbol: str, timeframe: str = '1h') -> pd.Series:
        """
        Obtiene la vela más reciente.
        Útil para el loop en vivo (Live Trading).
        """
        # Pedimos pocas velas para ser eficientes, solo necesitamos la última
        # Pedimos 2 por si la última está formándose y queremos la anterior cerrada
        df = self.get_historical_data(symbol, timeframe, limit=5)
        
        if df.empty:
            return pd.Series()
            
        # Retornamos la última fila (la más reciente)
        return df.iloc[-1]