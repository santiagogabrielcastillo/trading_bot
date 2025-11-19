from pydantic import BaseModel, Field, SecretStr

class ExchangeConfig(BaseModel):
    """Configuración de conexión al Exchange"""
    name: str = Field(..., description="Nombre del exchange en ccxt (ej. binance)")
    api_key: SecretStr
    api_secret: SecretStr
    sandbox_mode: bool = False

class RiskConfig(BaseModel):
    """Reglas de gestión de riesgo"""
    max_position_size_usd: float = Field(..., gt=0)
    stop_loss_pct: float = Field(0.02, description="Stop Loss por defecto (2%)")
    take_profit_pct: float = Field(0.04, description="Take Profit por defecto (4%)")

class StrategyConfig(BaseModel):
    """Parámetros de la estrategia"""
    name: str
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    params: dict = Field(default_factory=dict)

class BotConfig(BaseModel):
    """Configuración Global"""
    exchange: ExchangeConfig
    risk: RiskConfig
    strategy: StrategyConfig
    db_path: str = "trading_state.db"