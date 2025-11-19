from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

# Importaciones relativas dentro del paquete app
from app.core.enums import OrderSide, OrderType, PositionStatus
from app.config.models import StrategyConfig

# --- Interfaz de Datos ---


class IDataHandler(ABC):
    @abstractmethod
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_latest_bar(self, symbol: str) -> pd.Series:
        pass

# --- Interfaz de Persistencia ---


class IPositionManager(ABC):
    @abstractmethod
    def get_current_status(self, symbol: str) -> dict:
        pass

    @abstractmethod
    def set_position(self, symbol: str, status: PositionStatus, price: float, size: float, order_id: str):
        pass

# --- Interfaz de Ejecución ---


class IExecutor(ABC):
    @abstractmethod
    def execute_order(self, symbol: str, side: OrderSide, quantity: float, order_type: OrderType) -> dict:
        pass

# --- Interfaz de Estrategia ---


class BaseStrategy(ABC):
    def __init__(self, config: StrategyConfig):
        self.config = config

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula indicadores técnicos vectorizados.
        Modifica el DF in-place o retorna uno nuevo.
        """
        pass

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Genera señales de trading vectorizadas para todo el histórico.
        
        Debe agregar una columna 'signal':
         1 : Señal de COMPRA (Trigger)
        -1 : Señal de VENTA (Trigger)
         0 : Neutro / Mantener
         
        Args:
            df (pd.DataFrame): DataFrame con indicadores ya calculados.
            
        Returns:
            pd.DataFrame: DataFrame con la columna 'signal' agregada.
        """
        pass