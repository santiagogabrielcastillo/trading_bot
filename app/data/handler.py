import pandas as pd
import ccxt
from typing import Optional

# Importamos la interfaz que definimos previamente
from app.core.interfaces import IDataHandler

class CryptoDataHandler(IDataHandler):
    """
    Implementación concreta usando CCXT para obtener datos de mercado.
    """
    
    def __init__(self, exchange: ccxt.Exchange):
        """
        Recibe una instancia ya configurada de ccxt.Exchange.
        Esto permite inyección de dependencias (facilita tests y cambios de exchange).
        """
        self.exchange = exchange

    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        """
        Descarga velas históricas y devuelve un DataFrame formateado.
        
        Implements pagination to fetch large datasets beyond the exchange's single-request limit.
        For long backtests, this ensures we can fetch thousands of candles by making multiple
        API calls and concatenating the results.
        
        Fetches data going backwards from the most recent candle.
        """
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