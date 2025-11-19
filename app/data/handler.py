import pandas as pd
import ccxt
from typing import Optional
from pathlib import Path
import logging

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
    
    def _cache_covers_range(self, df: pd.DataFrame, limit: int) -> bool:
        """
        Check if cached data covers the requested limit.
        Since we fetch backwards from the most recent candle, we check if
        the cache has at least 'limit' rows.
        """
        return len(df) >= limit
    
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        """
        Descarga velas históricas y devuelve un DataFrame formateado.
        
        Implements offline caching: checks for cached CSV first, only fetches from API
        if cache is missing or insufficient. New data overwrites the cache.
        
        Implements pagination to fetch large datasets beyond the exchange's single-request limit.
        For long backtests, this ensures we can fetch thousands of candles by making multiple
        API calls and concatenating the results.
        
        Fetches data going backwards from the most recent candle.
        """
        # Try to load from cache first
        cached_df = self._load_from_csv(symbol, timeframe)
        if cached_df is not None and self._cache_covers_range(cached_df, limit):
            # Cache hit - return requested amount (most recent 'limit' rows)
            return cached_df.tail(limit).copy()
        
        # Cache miss or insufficient - fetch from API
        import time
        
        if hasattr(self.exchange, 'options') and 'fetchOHLCVLimit' in self.exchange.options:
            max_per_request = self.exchange.options['fetchOHLCVLimit']
        else:
            max_per_request = 1000  # Safe default for most exchanges
        
        all_ohlcv = []
        since = None
        remaining = limit
        
        while remaining > 0:
            batch_size = min(remaining, max_per_request)
            
            try:
                batch = self.exchange.fetch_ohlcv(
                    symbol, 
                    timeframe, 
                    since=since, 
                    limit=batch_size
                )
                
                if not batch or len(batch) == 0:
                    break
                
                all_ohlcv.extend(batch)
                remaining -= len(batch)
                
                if len(batch) < batch_size:
                    break
                
                oldest_timestamp = batch[0][0]
                
                minutes_per_candle = self._timeframe_to_minutes(timeframe)
                if minutes_per_candle:
                    ms_per_candle = minutes_per_candle * 60 * 1000
                    since = oldest_timestamp - ms_per_candle
                else:
                    since = oldest_timestamp - (60 * 60 * 1000)
                
                if hasattr(self.exchange, 'rateLimit') and self.exchange.rateLimit > 0:
                    time.sleep(max(0.1, self.exchange.rateLimit / 1000.0))
                    
            except Exception as e:
                if not all_ohlcv:
                    raise RuntimeError(f"Failed to fetch historical data: {e}") from e
                break
        
        if not all_ohlcv:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)

        # Save to cache for future use
        self._save_to_csv(df, symbol, timeframe)
        
        # Return requested amount (most recent 'limit' rows)
        return df.tail(limit).copy()
    
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