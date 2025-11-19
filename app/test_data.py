# test_data.py
import ccxt
from app.data.handler import CryptoDataHandler

def test_ingestion():
    # 1. Instanciamos Binance (público, no requiere API Key para esto)
    exchange = ccxt.binance()
    
    # 2. Inyectamos la dependencia al Handler
    handler = CryptoDataHandler(exchange)
    
    print("--- Probando Descarga Histórica ---")
    try:
        df = handler.get_historical_data("BTC/USDT", "1h", limit=5)
        print(f"Columnas detectadas: {df.columns.tolist()}")
        print("\nÚltimas 5 velas:")
        print(df)
        
        print("\n--- Probando Última Vela ---")
        last_bar = handler.get_latest_bar("BTC/USDT")
        print(f"Cierre actual: {last_bar['close']}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ingestion()