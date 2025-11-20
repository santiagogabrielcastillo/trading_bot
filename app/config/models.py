from pydantic import BaseModel, Field, SecretStr, field_validator
from typing import Literal

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
    execution_mode: Literal["paper", "live"] = Field(
        default="paper",
        description="Execution mode: 'paper' for simulated trading, 'live' for real money"
    )
    
    @field_validator('execution_mode')
    @classmethod
    def validate_execution_mode(cls, v: str) -> str:
        """Validate and warn if live mode is enabled."""
        if v == "live":
            import warnings
            warnings.warn(
                "⚠️  LIVE TRADING MODE ENABLED - REAL MONEY AT RISK! ⚠️",
                UserWarning,
                stacklevel=2
            )
        return v
    
    @classmethod
    def load_from_file(cls, file_path: str) -> "BotConfig":
        """
        Load configuration from a JSON file.
        
        Args:
            file_path: Path to JSON configuration file
            
        Returns:
            BotConfig instance
        """
        import json
        with open(file_path, 'r') as f:
            config_dict = json.load(f)
        return cls(**config_dict)