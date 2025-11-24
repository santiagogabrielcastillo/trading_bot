"""
Strategy Factory Module

Centralized strategy instantiation logic with support for market regime filters.
This module provides a unified interface for creating strategy instances from
configuration, following the DRY principle.
"""
from typing import Optional

from app.core.interfaces import BaseStrategy
from app.config.models import (
    BotConfig,
    StrategyConfig,
    RegimeFilterConfig,
    MomentumFilterConfig,
)
from app.strategies.sma_cross import SmaCrossStrategy
from app.strategies.atr_strategy import VolatilityAdjustedStrategy
from app.strategies.regime_filters import ADXVolatilityFilter
from app.strategies.momentum_filters import MACDConfirmationFilter


def create_strategy(
    config: BotConfig,
    regime_filter_config: Optional[RegimeFilterConfig] = None,
    momentum_filter_config: Optional[MomentumFilterConfig] = None,
) -> BaseStrategy:
    """
    Create and instantiate a trading strategy from configuration.
    
    This is the centralized strategy factory that handles:
    - Dynamic strategy class resolution based on config.strategy.name
    - Optional market regime filter instantiation and injection
    - Backward compatibility (filter is optional)
    
    Args:
        config: Bot configuration containing strategy config
        regime_filter_config: Optional regime filter configuration. If not provided,
                            will use config.regime_filter if present.
    
    Returns:
        Instantiated strategy instance with optional filter injected
    
    Raises:
        ValueError: If strategy name is unknown or invalid
    """
    strategy_config = config.strategy
    
    # Use provided filter config or fall back to config.regime_filter / momentum_filter
    filter_config = regime_filter_config or config.regime_filter
    momentum_config = momentum_filter_config or config.momentum_filter
    
    # Instantiate filters if configs are provided
    regime_filter = ADXVolatilityFilter(config=filter_config) if filter_config else None
    momentum_filter = MACDConfirmationFilter(config=momentum_config) if momentum_config else None
    
    # Strategy name mapping
    strategy_map = {
        "sma_cross": SmaCrossStrategy,
        "SmaCrossStrategy": SmaCrossStrategy,
        "VolatilityAdjustedStrategy": VolatilityAdjustedStrategy,
    }
    
    strategy_name = strategy_config.name
    strategy_class = strategy_map.get(strategy_name)
    
    if strategy_class is None:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available strategies: {list(strategy_map.keys())}"
        )
    
    # Instantiate strategy with optional filter
    strategy = strategy_class(
        config=strategy_config,
        regime_filter=regime_filter,
        momentum_filter=momentum_filter,
    )
    
    return strategy


def create_regime_filter(
    filter_config: RegimeFilterConfig
) -> Optional[ADXVolatilityFilter]:
    """
    Create a market regime filter instance.
    
    Args:
        filter_config: Filter configuration
    
    Returns:
        ADXVolatilityFilter instance, or None if config is None
    """
    if filter_config is None:
        return None
    
    return ADXVolatilityFilter(config=filter_config)

