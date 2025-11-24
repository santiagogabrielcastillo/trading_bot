import numpy as np
import pandas as pd
from typing import Optional
from app.core.interfaces import BaseStrategy, IMarketRegimeFilter, IMomentumFilter

class SmaCrossStrategy(BaseStrategy):
    """
    Estrategia de Cruce de Medias Exponenciales (EMA Cross) vectorizada.
    Conservamos el nombre histórico para compatibilidad, pero ahora priorizamos
    datos recientes usando EMAs en lugar de SMAs.
    """
    
    def __init__(
        self,
        config,
        regime_filter: Optional[IMarketRegimeFilter] = None,
        momentum_filter: Optional[IMomentumFilter] = None,
    ):
        """Initialize SMA Cross Strategy with optional filters."""
        super().__init__(config, regime_filter, momentum_filter)

    @property
    def max_lookback_period(self) -> int:
        """
        Return the maximum lookback period required by all strategy indicators.
        
        For EMA Cross strategy, this is the maximum of:
        - fast_window
        - slow_window
        - filter's max_lookback_period (if filter is present)
        
        Returns:
            Number of periods needed for indicator warm-up
        """
        # Get strategy-specific lookback (max of fast and slow windows)
        fast_window = self.config.params.get('fast_window', 10)
        slow_window = self.config.params.get('slow_window', 50)
        strategy_lookback = max(fast_window, slow_window)
        
        lookbacks = [strategy_lookback]
        if self.regime_filter is not None:
            lookbacks.append(self.regime_filter.max_lookback_period)
        if self.momentum_filter is not None:
            lookbacks.append(self.momentum_filter.max_lookback_period)
        
        return max(lookbacks)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula las EMAs rápida y lenta basándose en parámetros de configuración.
        """
        # 1. Extraer parámetros con valores por defecto seguros
        fast_window = self.config.params.get('fast_window', 10)
        slow_window = self.config.params.get('slow_window', 50)

        # 2. Cálculo vectorizado usando exponenciales (prioriza datos recientes)
        df['ema_fast'] = df['close'].ewm(span=fast_window, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=slow_window, adjust=False).mean()

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
        prev_fast = df['ema_fast'].shift(1)
        prev_slow = df['ema_slow'].shift(1)
        curr_fast = df['ema_fast']
        curr_slow = df['ema_slow']

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

        # --- Aplicar Symmetry Blockade (Long Only) si está habilitado ---
        
        # Si long_only es True, convertir todas las señales SELL a NEUTRAL
        # Esto aísla el rendimiento de la señal LONG del lastre de los shorts fallidos
        if self.config.long_only:
            df['signal'] = np.where(df['signal'] == -1, 0, df['signal'])

        # Limpieza: Convertir a entero y llenar NaNs (generados por rolling/shift) con 0
        df['signal'] = df['signal'].fillna(0).astype(int)

        return df