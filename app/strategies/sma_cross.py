import numpy as np
import pandas as pd
from typing import Optional
from app.core.interfaces import BaseStrategy, IMarketRegimeFilter

class SmaCrossStrategy(BaseStrategy):
    """
    Estrategia de Cruce de Medias Móviles Simple (SMA Cross).
    Implementación Vectorizada.
    """
    
    def __init__(self, config, regime_filter: Optional[IMarketRegimeFilter] = None):
        """Initialize SMA Cross Strategy with optional regime filter."""
        super().__init__(config, regime_filter)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula las SMAs rápida y lenta basándose en parámetros de configuración.
        """
        # 1. Extraer parámetros con valores por defecto seguros
        fast_window = self.config.params.get('fast_window', 10)
        slow_window = self.config.params.get('slow_window', 50)

        # 2. Cálculo vectorizado usando rolling (Pandas optimizado en C)
        df['sma_fast'] = df['close'].rolling(window=fast_window).mean()
        df['sma_slow'] = df['close'].rolling(window=slow_window).mean()

        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Genera señales 1 (Buy) y -1 (Sell) EXCLUSIVAMENTE en el momento del cruce.
        """
        # Inicializar columna signal en 0 (Neutro)
        df['signal'] = 0

        # --- Lógica de Vectorización ---
        
        # Capturamos el estado anterior (t-1) y el actual (t)
        # shift(1) desplaza los datos una fila hacia abajo para alinear t-1 con t
        prev_fast = df['sma_fast'].shift(1)
        prev_slow = df['sma_slow'].shift(1)
        curr_fast = df['sma_fast']
        curr_slow = df['sma_slow']

        # Definimos las máscaras booleanas para los cruces
        
        # Golden Cross (Compra):
        # Antes: Rápida <= Lenta  Y  Ahora: Rápida > Lenta
        buy_condition = (prev_fast <= prev_slow) & (curr_fast > curr_slow)
        
        # Death Cross (Venta):
        # Antes: Rápida >= Lenta  Y  Ahora: Rápida < Lenta
        sell_condition = (prev_fast >= prev_slow) & (curr_fast < curr_slow)

        # Aplicamos numpy.where anidado para asignar valores numéricos
        # Sintaxis: np.where(condición, valor_si_true, valor_si_false)
        df['signal'] = np.where(
            buy_condition, 
            1, 
            np.where(sell_condition, -1, 0)
        )

        # Limpieza: Convertir a entero y llenar NaNs (generados por rolling/shift) con 0
        df['signal'] = df['signal'].fillna(0).astype(int)

        return df