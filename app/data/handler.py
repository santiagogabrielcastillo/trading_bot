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
        """
        # 1. Descargar datos crudos (List of Lists)
        # Estructura CCXT: [[timestamp, open, high, low, close, volume], ...]
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        # 2. Comprobación de seguridad
        if not ohlcv:
            # Retornar DF vacío con columnas correctas para evitar errores en estrategia
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        # 3. Crear DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # 4. Normalización de Timestamp
        # Convertimos ms a datetime y lo ponemos como índice
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        # 5. Asegurar tipos numéricos (floats)
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)

        return df

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