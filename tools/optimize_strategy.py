#!/usr/bin/env python3
"""
Strategy Parameter Optimization Tool (Grid Search with Walk-Forward Validation)

This script performs exhaustive grid search optimization for trading strategy parameters
using the "Load Once, Compute Many" pattern for maximum efficiency, with optional
In-Sample/Out-of-Sample validation to prevent overfitting.

Architecture:
    1. Load historical data EXACTLY ONCE from the exchange
    2. Cache it in memory
    3. Mock the data handler to serve the cached data for all backtest iterations
    4. Phase 1 (In-Sample): Iterate through parameter combinations on training data
    5. Phase 2 (Out-of-Sample): Validate top performers on unseen test data
    6. Save results with both IS and OOS metrics

Usage:
    # Standard optimization (no validation)
    python tools/optimize_strategy.py --start-date 2023-01-01 --end-date 2023-12-31
    
    # Walk-forward optimization with OOS validation
    python tools/optimize_strategy.py --start-date 2023-01-01 --end-date 2023-12-31 --split-date 2023-10-01
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import itertools

import pandas as pd
import ccxt

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data.handler import CryptoDataHandler
from app.core.interfaces import IDataHandler, BaseStrategy
from app.core.strategy_factory import create_strategy
from app.backtesting.engine import Backtester
from app.strategies.sma_cross import SmaCrossStrategy
from app.strategies.atr_strategy import VolatilityAdjustedStrategy
from app.strategies.bollinger_band import BollingerBandStrategy
from app.strategies.regime_filters import ADXVolatilityFilter
from app.strategies.momentum_filters import MACDConfirmationFilter
from app.config.models import (
    StrategyConfig,
    BotConfig,
    RiskConfig,
    RegimeFilterConfig,
    MomentumFilterConfig,
)
from app.execution.mock_executor import MockExecutor


def load_strategy_from_config(config_path: str = "settings/config.json") -> Tuple[BaseStrategy, StrategyConfig]:
    """
    Load strategy from config.json file using the centralized strategy factory.
    
    This function uses the strategy factory which handles:
    - Dynamic strategy class resolution
    - Optional market regime filter instantiation from config
    - Consistent behavior with run_backtest.py and run_live.py
    
    Args:
        config_path: Path to config.json file
        
    Returns:
        Tuple of (strategy_instance, strategy_config)
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    # Load config
    with open(config_file, 'r') as f:
        config_dict = json.load(f)
    
    bot_config = BotConfig(**config_dict)
    strategy_config = bot_config.strategy
    
    # Use centralized strategy factory (handles filter instantiation from config)
    strategy = create_strategy(bot_config)
    
    return strategy, strategy_config


class CachedDataHandler(IDataHandler):
    """
    Mock data handler that serves pre-loaded data from memory.
    
    This wrapper implements the IDataHandler interface but returns
    cached data instead of making API calls. This is critical for
    the "Load Once, Compute Many" pattern.
    """
    
    def __init__(self, cached_data: pd.DataFrame, symbol: str, timeframe: str):
        """
        Initialize with pre-loaded data.
        
        Args:
            cached_data: Pre-loaded historical market data
            symbol: Symbol this data represents (e.g., 'BTC/USDT')
            timeframe: Timeframe this data represents (e.g., '1h')
        """
        self.cached_data = cached_data.copy()
        self.symbol = symbol
        self.timeframe = timeframe
    
    def get_historical_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Return cached data instead of fetching from API.
        
        This method filters the cached DataFrame based on the requested
        date range, ensuring compatibility with the Backtester engine.
        """
        df = self.cached_data.copy()
        
        # Filter by date range if specified
        if start_date is not None:
            start_ts = pd.to_datetime(start_date)
            df = df[df.index >= start_ts]
        
        if end_date is not None:
            end_ts = pd.to_datetime(end_date)
            df = df[df.index <= end_ts]
        
        # Apply limit if specified
        if limit and len(df) > limit:
            df = df.tail(limit)
        
        return df
    
    def get_latest_bar(self, symbol: str, timeframe: str = '1h') -> pd.Series:
        """
        Return the most recent bar from cached data.
        """
        if self.cached_data.empty:
            return pd.Series()
        return self.cached_data.iloc[-1]


class StrategyOptimizer:
    """
    Grid search optimizer for trading strategies.
    
    Implements the "Load Once, Compute Many" pattern by pre-loading
    all market data before starting the optimization loop.
    """
    
    def __init__(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        start_date: str = "2023-01-01",
        end_date: str = "2023-12-31",
        split_date: Optional[str] = None,
        initial_capital: float = 1.0,
        base_strategy_config: Optional[StrategyConfig] = None,
        risk_config: Optional[RiskConfig] = None,
        momentum_filter_config: Optional[MomentumFilterConfig] = None,
    ):
        """
        Initialize the optimizer.
        
        Args:
            symbol: Trading pair to optimize (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
            split_date: Optional split date for walk-forward validation (YYYY-MM-DD)
                       If provided, enables In-Sample/Out-of-Sample validation
            initial_capital: Initial capital for backtests (normalized to 1.0)
            base_strategy_config: Base strategy config from config.json
            risk_config: Optional risk configuration (SL/TP enforcement)
            momentum_filter_config: Optional MACD momentum filter baseline config
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.start_date = start_date
        self.end_date = end_date
        self.split_date = split_date
        self.initial_capital = initial_capital
        self.base_strategy_config = base_strategy_config
        self.risk_config = risk_config
        self.base_momentum_filter_config = momentum_filter_config
        
        # Validate split_date if provided
        if self.split_date:
            start_ts = pd.to_datetime(self.start_date)
            end_ts = pd.to_datetime(self.end_date)
            split_ts = pd.to_datetime(self.split_date)
            
            if split_ts <= start_ts or split_ts >= end_ts:
                raise ValueError(
                    f"split_date ({self.split_date}) must be between "
                    f"start_date ({self.start_date}) and end_date ({self.end_date})"
                )
        
        # Results storage
        self.results: List[Dict[str, Any]] = []
        
        # Cached data (loaded once)
        self.cached_data: Optional[pd.DataFrame] = None
    
    def load_data_once(self) -> None:
        """
        Load historical data EXACTLY ONCE before optimization begins.
        
        This is the critical "Load Once" step that prevents redundant API calls.
        Data is stored in self.cached_data for use by all backtest iterations.
        """
        print("=" * 70)
        print("LOADING HISTORICAL DATA (One-Time Operation)")
        print("=" * 70)
        print(f"Symbol:     {self.symbol}")
        print(f"Timeframe:  {self.timeframe}")
        print(f"Date Range: {self.start_date} to {self.end_date}")
        print()
        
        try:
            # Initialize exchange and data handler
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                }
            })
            
            handler = CryptoDataHandler(exchange=exchange)
            
            # Fetch data with a buffer for indicator calculation
            # Add 1000 candles before start_date to warm up indicators
            start_ts = pd.to_datetime(self.start_date)
            end_ts = pd.to_datetime(self.end_date)
            
            # Calculate buffer start (add extra candles for EMA calculation)
            minutes_per_candle = self._timeframe_to_minutes(self.timeframe)
            buffer_minutes = 1000 * minutes_per_candle  # 1000 candles buffer
            buffer_start = start_ts - pd.Timedelta(minutes=buffer_minutes)
            
            print(f"Fetching data from {buffer_start.date()} (with buffer for indicators)...")
            
            self.cached_data = handler.get_historical_data(
                symbol=self.symbol,
                timeframe=self.timeframe,
                start_date=buffer_start,
                end_date=end_ts,
                limit=10000,  # Generous limit
            )
            
            if self.cached_data.empty:
                raise ValueError("No data received from exchange")
            
            print(f"✓ Loaded {len(self.cached_data)} candles successfully")
            print(f"  Date range: {self.cached_data.index.min()} to {self.cached_data.index.max()}")
            print(f"  Memory size: {self.cached_data.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")
            print()
            
        except Exception as e:
            print(f"✗ Error loading data: {e}")
            raise
    
    def optimize(
        self,
        fast_window_range: List[int],
        slow_window_range: List[int],
        atr_window_range: Optional[List[int]] = None,
        atr_multiplier_range: Optional[List[float]] = None,
        adx_window_range: Optional[List[int]] = None,
        adx_threshold_range: Optional[List[int]] = None,
        macd_fast_range: Optional[List[int]] = None,
        max_hold_hours_range: Optional[List[int]] = None,
        bb_window_range: Optional[List[int]] = None,
        bb_std_dev_range: Optional[List[float]] = None,
        is_bb_strategy: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Perform grid search optimization over parameter combinations.
        
        Args:
            fast_window_range: List of fast EMA window values to test (for EMA/SMA strategies)
            slow_window_range: List of slow EMA window values to test (for EMA/SMA strategies)
            atr_window_range: Optional list of ATR window values to test
            atr_multiplier_range: Optional list of ATR multiplier values to test
            adx_window_range: Optional list of ADX window values to test (for Market Regime Filter)
            adx_threshold_range: Optional list of ADX threshold values to test (for Market Regime Filter)
            macd_fast_range: Optional list of MACD fast EMA windows to test (for Momentum Filter)
            max_hold_hours_range: Optional list of max hold hours to test (for 8D optimization)
            bb_window_range: Optional list of BB window values to test (for BollingerBandStrategy)
            bb_std_dev_range: Optional list of BB std dev multiplier values to test (for BollingerBandStrategy)
            is_bb_strategy: True if optimizing BollingerBandStrategy (uses BB params instead of fast/slow)
        
        Returns:
            List of results sorted by Sharpe ratio (descending)
        """
        if self.cached_data is None:
            raise RuntimeError("Data not loaded. Call load_data_once() first.")
        
        print("=" * 70)
        print("STARTING GRID SEARCH OPTIMIZATION")
        print("=" * 70)
        
        # Determine optimization dimension (ADX is now optional - disabled for simplification)
        # Check for 6D optimization without ADX first (BB_W, BB_Std, ATR_W, ATR_M, MACD_F, MaxH)
        is_6d_no_adx = (
            atr_window_range is not None and atr_multiplier_range is not None and
            macd_fast_range is not None and max_hold_hours_range is not None and
            (adx_window_range is None or adx_threshold_range is None)
        )
        
        # Then check for 8D with ADX
        is_8d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            adx_window_range is not None and adx_threshold_range is not None and
            macd_fast_range is not None and max_hold_hours_range is not None and
            not is_6d_no_adx
        )
        # 7D with ADX but no MaxH
        is_7d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            adx_window_range is not None and adx_threshold_range is not None and
            macd_fast_range is not None and not is_8d_optimization and not is_6d_no_adx
        )
        # 6D with ADX but no MACD/MaxH
        is_6d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            adx_window_range is not None and adx_threshold_range is not None and
            not is_7d_optimization and not is_8d_optimization and not is_6d_no_adx
        )
        is_4d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            not is_6d_optimization and not is_7d_optimization and not is_8d_optimization and not is_6d_no_adx
        )
        
        # For BB strategy, use BB parameters instead of fast/slow windows
        if is_bb_strategy:
            # BB strategy uses bb_window and bb_std_dev as the first two dimensions
            strategy_dim1_range = bb_window_range or []
            strategy_dim2_range = bb_std_dev_range or []
            strategy_dim1_name = "BB Window"
            strategy_dim2_name = "BB Std Dev"
        else:
            # EMA/SMA strategies use fast_window and slow_window as the first two dimensions
            strategy_dim1_range = fast_window_range
            strategy_dim2_range = slow_window_range
            strategy_dim1_name = "Fast Window"
            strategy_dim2_name = "Slow Window"
        
        if is_8d_optimization:
            param_combinations = list(itertools.product(
                strategy_dim1_range,
                strategy_dim2_range,
                atr_window_range,
                atr_multiplier_range,
                adx_window_range,
                adx_threshold_range,
                macd_fast_range,
                max_hold_hours_range,
            ))
            
            # For BB strategy, no constraint (all combinations valid)
            # For EMA/SMA strategies, filter fast < slow
            if is_bb_strategy:
                valid_combinations = list(param_combinations)
            else:
                valid_combinations = [
                    (fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f, max_h)
                    for fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f, max_h in param_combinations
                    if fast < slow
                ]
            
            print(f"Parameter Space (8D):")
            print(f"  {strategy_dim1_name}:    {strategy_dim1_range}")
            print(f"  {strategy_dim2_name}:    {strategy_dim2_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
            print(f"  ADX Window:     {adx_window_range}")
            print(f"  ADX Threshold:  {adx_threshold_range}")
            print(f"  MACD Fast:      {macd_fast_range}")
            print(f"  Max Hold Hours: {max_hold_hours_range}")
        elif is_7d_optimization:
            param_combinations = list(itertools.product(
                strategy_dim1_range,
                strategy_dim2_range,
                atr_window_range,
                atr_multiplier_range,
                adx_window_range,
                adx_threshold_range,
                macd_fast_range,
            ))
            
            # For BB strategy, no constraint (all combinations valid)
            # For EMA/SMA strategies, filter fast < slow
            if is_bb_strategy:
                valid_combinations = list(param_combinations)
            else:
                valid_combinations = [
                    (fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f)
                    for fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f in param_combinations
                    if fast < slow
                ]
            
            print(f"Parameter Space (7D):")
            print(f"  {strategy_dim1_name}:    {strategy_dim1_range}")
            print(f"  {strategy_dim2_name}:    {strategy_dim2_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
            print(f"  ADX Window:     {adx_window_range}")
            print(f"  ADX Threshold:  {adx_threshold_range}")
            print(f"  MACD Fast:      {macd_fast_range}")
        elif is_6d_optimization:
            # 6D optimization: strategy_dim1, strategy_dim2, atr_window, atr_multiplier, adx_window, adx_threshold
            param_combinations = list(itertools.product(
                strategy_dim1_range,
                strategy_dim2_range,
                atr_window_range,
                atr_multiplier_range,
                adx_window_range,
                adx_threshold_range
            ))
            
            # For BB strategy, no constraint (all combinations valid)
            # For EMA/SMA strategies, filter fast < slow
            if is_bb_strategy:
                valid_combinations = list(param_combinations)
            else:
                valid_combinations = [
                    (fast, slow, atr_w, atr_m, adx_w, adx_t) 
                    for fast, slow, atr_w, atr_m, adx_w, adx_t in param_combinations
                    if fast < slow
                ]
            
            print(f"Parameter Space (6D):")
            print(f"  {strategy_dim1_name}:    {strategy_dim1_range}")
            print(f"  {strategy_dim2_name}:    {strategy_dim2_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
            print(f"  ADX Window:     {adx_window_range}")
            print(f"  ADX Threshold:  {adx_threshold_range}")
        elif is_4d_optimization:
            # 4D optimization: strategy_dim1, strategy_dim2, atr_window, atr_multiplier
            param_combinations = list(itertools.product(
                strategy_dim1_range,
                strategy_dim2_range,
                atr_window_range,
                atr_multiplier_range
            ))
            
            # For BB strategy, no constraint (all combinations valid)
            # For EMA/SMA strategies, filter fast < slow
            if is_bb_strategy:
                valid_combinations = list(param_combinations)
            else:
                valid_combinations = [
                    (fast, slow, atr_w, atr_m) for fast, slow, atr_w, atr_m in param_combinations
                    if fast < slow
                ]
            
            print(f"Parameter Space (4D):")
            print(f"  {strategy_dim1_name}:    {strategy_dim1_range}")
            print(f"  {strategy_dim2_name}:    {strategy_dim2_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
        else:
            # 2D optimization: strategy_dim1, strategy_dim2 (backward compatible)
            param_combinations = list(itertools.product(strategy_dim1_range, strategy_dim2_range))
            
            # For BB strategy, no constraint (all combinations valid)
            # For EMA/SMA strategies, filter fast < slow
            if is_bb_strategy:
                valid_combinations = list(param_combinations)
            else:
                valid_combinations = [
                    (fast, slow) for fast, slow in param_combinations
                    if fast < slow
                ]
            
            print(f"Parameter Space (2D):")
            print(f"  {strategy_dim1_name}:    {strategy_dim1_range}")
            print(f"  {strategy_dim2_name}:    {strategy_dim2_range}")
        
        total_tests = len(valid_combinations)
        print(f"  Total Combinations: {len(param_combinations)}")
        if is_bb_strategy:
            print(f"  Valid Combinations: {total_tests}")
        else:
            print(f"  Valid Combinations: {total_tests} (fast < slow)")
        print()
        
        # Create cached data handler (used for ALL iterations)
        cached_handler = CachedDataHandler(
            cached_data=self.cached_data,
            symbol=self.symbol,
            timeframe=self.timeframe,
        )
        
        # Run backtest for each valid combination
        for idx, params in enumerate(valid_combinations, start=1):
            try:
                if is_8d_optimization:
                    dim1, dim2, atr_window, atr_multiplier, adx_window, adx_threshold, macd_fast, max_hold_hours = params
                    # dim1 and dim2 are either fast/slow (EMA/SMA) or bb_window/bb_std_dev (BB)
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        macd_fast=macd_fast,
                        max_hold_hours=max_hold_hours,
                        iteration=idx,
                        total=total_tests,
                        is_bb_strategy=is_bb_strategy,
                    )
                elif is_7d_optimization:
                    dim1, dim2, atr_window, atr_multiplier, adx_window, adx_threshold, macd_fast = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        macd_fast=macd_fast,
                        iteration=idx,
                        total=total_tests,
                        is_bb_strategy=is_bb_strategy,
                    )
                elif is_6d_optimization:
                    dim1, dim2, atr_window, atr_multiplier, adx_window, adx_threshold = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        iteration=idx,
                        total=total_tests,
                        is_bb_strategy=is_bb_strategy,
                    )
                elif is_4d_optimization:
                    dim1, dim2, atr_window, atr_multiplier = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=None,
                        adx_threshold=None,
                        iteration=idx,
                        total=total_tests,
                        is_bb_strategy=is_bb_strategy,
                    )
                else:
                    dim1, dim2 = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=None,
                        atr_multiplier=None,
                        adx_window=None,
                        adx_threshold=None,
                        iteration=idx,
                        total=total_tests,
                        is_bb_strategy=is_bb_strategy,
                    )
                self.results.append(result)
                
            except Exception as e:
                print(f"  ✗ Error in iteration [{idx}/{total_tests}]: {e}")
                continue
        
        # Sort results by Sharpe ratio (descending)
        self.results.sort(key=lambda x: x['metrics'].get('sharpe_ratio', float('-inf')), reverse=True)
        
        print()
        print("=" * 70)
        print("OPTIMIZATION COMPLETE")
        print("=" * 70)
        print(f"Total successful runs: {len(self.results)}/{total_tests}")
        
        if self.results:
            best = self.results[0]
            print(f"\nBest Parameters:")
            
            # Display strategy-specific parameters
            if 'bb_window' in best['params']:
                # BB strategy parameters
                print(f"  BB Window: {best['params']['bb_window']}")
                if 'bb_std_dev' in best['params']:
                    print(f"  BB Std Dev: {best['params']['bb_std_dev']}")
            else:
                # EMA/SMA strategy parameters
                if 'fast_window' in best['params']:
                    print(f"  Fast Window: {best['params']['fast_window']}")
                if 'slow_window' in best['params']:
                    print(f"  Slow Window: {best['params']['slow_window']}")
            
            # Display filter parameters (same for all strategies)
            if 'atr_window' in best['params']:
                print(f"  ATR Window: {best['params']['atr_window']}")
            if 'atr_multiplier' in best['params']:
                print(f"  ATR Multiplier: {best['params']['atr_multiplier']}")
            if 'adx_window' in best['params']:
                print(f"  ADX Window: {best['params']['adx_window']}")
            if 'adx_threshold' in best['params']:
                print(f"  ADX Threshold: {best['params']['adx_threshold']}")
            if 'macd_fast' in best['params']:
                print(f"  MACD Fast: {best['params']['macd_fast']}")
            if 'macd_slow' in best['params']:
                print(f"  MACD Slow: {best['params']['macd_slow']}")
            if 'macd_signal' in best['params']:
                print(f"  MACD Signal: {best['params']['macd_signal']}")
            if 'max_hold_hours' in best['params']:
                print(f"  Max Hold Hours: {best['params']['max_hold_hours']}")
            print(f"  Sharpe Ratio: {best['metrics']['sharpe_ratio']:.4f}")
            print(f"  Total Return: {best['metrics']['total_return'] * 100:.2f}%")
            print(f"  Max Drawdown: {best['metrics']['max_drawdown'] * 100:.2f}%")
        
        return self.results
    
    def optimize_with_validation(
        self,
        fast_window_range: List[int],
        slow_window_range: List[int],
        top_n: int = 5,
        atr_window_range: Optional[List[int]] = None,
        atr_multiplier_range: Optional[List[float]] = None,
        adx_window_range: Optional[List[int]] = None,
        adx_threshold_range: Optional[List[int]] = None,
        macd_fast_range: Optional[List[int]] = None,
        max_hold_hours_range: Optional[List[int]] = None,
        bb_window_range: Optional[List[int]] = None,
        bb_std_dev_range: Optional[List[float]] = None,
        is_bb_strategy: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Perform grid search with In-Sample/Out-of-Sample validation.
        
        Two-phase execution:
        1. Phase 1 (In-Sample): Run full grid search on data from start_date to split_date
        2. Phase 2 (Out-of-Sample): Validate top N performers on data from split_date to end_date
        
        Args:
            fast_window_range: List of fast EMA window values to test
            slow_window_range: List of slow EMA window values to test
            top_n: Number of top performers to validate (default: 5)
            atr_window_range: Optional list of ATR window values to test (for VolatilityAdjustedStrategy)
            atr_multiplier_range: Optional list of ATR multiplier values to test (for VolatilityAdjustedStrategy)
            adx_window_range: Optional list of ADX window values to test (for Market Regime Filter)
            adx_threshold_range: Optional list of ADX threshold values to test (for Market Regime Filter)
            macd_fast_range: Optional list of MACD fast EMA windows to test (for Momentum Filter)
            max_hold_hours_range: Optional list of max hold hours to test (for 8D optimization)
        
        Returns:
            List of top N results with both IS and OOS metrics
        """
        if self.cached_data is None:
            raise RuntimeError("Data not loaded. Call load_data_once() first.")
        
        if not self.split_date:
            raise RuntimeError("split_date must be provided for walk-forward validation")
        
        print("=" * 70)
        print("WALK-FORWARD OPTIMIZATION WITH OUT-OF-SAMPLE VALIDATION")
        print("=" * 70)
        print(f"In-Sample Period:  {self.start_date} to {self.split_date}")
        print(f"Out-of-Sample:     {self.split_date} to {self.end_date}")
        print()
        
        # ========== PHASE 1: IN-SAMPLE OPTIMIZATION ==========
        print("=" * 70)
        print("PHASE 1: IN-SAMPLE GRID SEARCH")
        print("=" * 70)
        
        # Determine optimization dimension
        is_8d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            adx_window_range is not None and adx_threshold_range is not None and
            macd_fast_range is not None and max_hold_hours_range is not None
        )
        is_7d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            adx_window_range is not None and adx_threshold_range is not None and
            macd_fast_range is not None and not is_8d_optimization
        )
        is_6d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            adx_window_range is not None and adx_threshold_range is not None and
            not is_7d_optimization and not is_8d_optimization
        )
        is_4d_optimization = (
            atr_window_range is not None and atr_multiplier_range is not None and
            not is_6d_optimization and not is_7d_optimization and not is_8d_optimization
        )
        
        # For BB strategy, use BB parameters instead of fast/slow windows
        if is_bb_strategy:
            # BB strategy uses bb_window and bb_std_dev as the first two dimensions
            strategy_dim1_range = bb_window_range or []
            strategy_dim2_range = bb_std_dev_range or []
            strategy_dim1_name = "BB Window"
            strategy_dim2_name = "BB Std Dev"
        else:
            # EMA/SMA strategies use fast_window and slow_window as the first two dimensions
            strategy_dim1_range = fast_window_range
            strategy_dim2_range = slow_window_range
            strategy_dim1_name = "Fast Window"
            strategy_dim2_name = "Slow Window"
        
        if is_8d_optimization:
            param_combinations = list(itertools.product(
                strategy_dim1_range,
                strategy_dim2_range,
                atr_window_range,
                atr_multiplier_range,
                adx_window_range,
                adx_threshold_range,
                macd_fast_range,
                max_hold_hours_range,
            ))
            
            # For BB strategy, no constraint (all combinations valid)
            # For EMA/SMA strategies, filter fast < slow
            if is_bb_strategy:
                valid_combinations = list(param_combinations)
            else:
                valid_combinations = [
                    (fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f, max_h)
                    for fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f, max_h in param_combinations
                    if fast < slow
                ]
            
            print(f"Parameter Space (8D):")
            print(f"  {strategy_dim1_name}:    {strategy_dim1_range}")
            print(f"  {strategy_dim2_name}:    {strategy_dim2_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
            print(f"  ADX Window:     {adx_window_range}")
            print(f"  ADX Threshold:  {adx_threshold_range}")
            print(f"  MACD Fast:      {macd_fast_range}")
            print(f"  Max Hold Hours: {max_hold_hours_range}")
        elif is_7d_optimization:
            param_combinations = list(itertools.product(
                fast_window_range,
                slow_window_range,
                atr_window_range,
                atr_multiplier_range,
                adx_window_range,
                adx_threshold_range,
                macd_fast_range,
            ))
            
            valid_combinations = [
                (fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f) 
                for fast, slow, atr_w, atr_m, adx_w, adx_t, macd_f in param_combinations
                if fast < slow
            ]
            
            print(f"Parameter Space (7D):")
            print(f"  Fast Window:    {fast_window_range}")
            print(f"  Slow Window:    {slow_window_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
            print(f"  ADX Window:     {adx_window_range}")
            print(f"  ADX Threshold:  {adx_threshold_range}")
            print(f"  MACD Fast:      {macd_fast_range}")
        elif is_6d_optimization:
            # 6D optimization: fast_window, slow_window, atr_window, atr_multiplier, adx_window, adx_threshold
            param_combinations = list(itertools.product(
                fast_window_range,
                slow_window_range,
                atr_window_range,
                atr_multiplier_range,
                adx_window_range,
                adx_threshold_range
            ))
            
            # Filter out invalid combinations (fast >= slow)
            valid_combinations = [
                (fast, slow, atr_w, atr_m, adx_w, adx_t) 
                for fast, slow, atr_w, atr_m, adx_w, adx_t in param_combinations
                if fast < slow
            ]
            
            print(f"Parameter Space (6D):")
            print(f"  Fast Window:    {fast_window_range}")
            print(f"  Slow Window:    {slow_window_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
            print(f"  ADX Window:     {adx_window_range}")
            print(f"  ADX Threshold:  {adx_threshold_range}")
        elif is_4d_optimization:
            # 4D optimization: fast_window, slow_window, atr_window, atr_multiplier
            param_combinations = list(itertools.product(
                fast_window_range,
                slow_window_range,
                atr_window_range,
                atr_multiplier_range
            ))
            
            # Filter out invalid combinations (fast >= slow)
            valid_combinations = [
                (fast, slow, atr_w, atr_m) for fast, slow, atr_w, atr_m in param_combinations
                if fast < slow
            ]
            
            print(f"Parameter Space (4D):")
            print(f"  Fast Window:    {fast_window_range}")
            print(f"  Slow Window:    {slow_window_range}")
            print(f"  ATR Window:     {atr_window_range}")
            print(f"  ATR Multiplier: {atr_multiplier_range}")
        else:
            # 2D optimization: fast_window, slow_window (backward compatible)
            param_combinations = list(itertools.product(fast_window_range, slow_window_range))
            
            # Filter out invalid combinations (fast >= slow)
            valid_combinations = [
                (fast, slow) for fast, slow in param_combinations
                if fast < slow
            ]
            
            print(f"Parameter Space (2D):")
            print(f"  Fast Window: {fast_window_range}")
            print(f"  Slow Window: {slow_window_range}")
        
        total_tests = len(valid_combinations)
        print(f"  Total Combinations: {len(param_combinations)}")
        print(f"  Valid Combinations: {total_tests} (fast < slow)")
        print()
        
        # Create cached data handler (used for ALL iterations)
        cached_handler = CachedDataHandler(
            cached_data=self.cached_data,
            symbol=self.symbol,
            timeframe=self.timeframe,
        )
        
        # Store In-Sample results
        is_results: List[Dict[str, Any]] = []
        
        # Run backtest for each valid combination on IN-SAMPLE period
        for idx, params in enumerate(valid_combinations, start=1):
            try:
                if is_8d_optimization:
                    dim1, dim2, atr_window, atr_multiplier, adx_window, adx_threshold, macd_fast, max_hold_hours = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        macd_fast=macd_fast,
                        max_hold_hours=max_hold_hours,
                        iteration=idx,
                        total=total_tests,
                        start_date=self.start_date,
                        end_date=self.split_date,
                        phase="IS",
                        is_bb_strategy=is_bb_strategy,
                    )
                elif is_7d_optimization:
                    dim1, dim2, atr_window, atr_multiplier, adx_window, adx_threshold, macd_fast = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        macd_fast=macd_fast,
                        iteration=idx,
                        total=total_tests,
                        start_date=self.start_date,
                        end_date=self.split_date,
                        phase="IS",
                        is_bb_strategy=is_bb_strategy,
                    )
                elif is_6d_optimization:
                    dim1, dim2, atr_window, atr_multiplier, adx_window, adx_threshold = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        iteration=idx,
                        total=total_tests,
                        start_date=self.start_date,
                        end_date=self.split_date,
                        phase="IS",
                        is_bb_strategy=is_bb_strategy,
                    )
                elif is_4d_optimization:
                    dim1, dim2, atr_window, atr_multiplier = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=None,
                        adx_threshold=None,
                        iteration=idx,
                        total=total_tests,
                        start_date=self.start_date,
                        end_date=self.split_date,
                        phase="IS",
                        is_bb_strategy=is_bb_strategy,
                    )
                else:
                    dim1, dim2 = params
                    result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=dim1 if not is_bb_strategy else None,
                        slow_window=dim2 if not is_bb_strategy else None,
                        bb_window=dim1 if is_bb_strategy else None,
                        bb_std_dev=dim2 if is_bb_strategy else None,
                        atr_window=None,
                        atr_multiplier=None,
                        adx_window=None,
                        adx_threshold=None,
                        iteration=idx,
                        total=total_tests,
                        start_date=self.start_date,
                        end_date=self.split_date,
                        phase="IS",
                        is_bb_strategy=is_bb_strategy,
                    )
                is_results.append(result)
                
            except Exception as e:
                print(f"  ✗ Error in iteration [{idx}/{total_tests}]: {e}")
                continue
        
        # Sort IS results by Sharpe ratio (descending)
        is_results.sort(key=lambda x: x['metrics'].get('sharpe_ratio', float('-inf')), reverse=True)
        
        print()
        print("=" * 70)
        print("IN-SAMPLE OPTIMIZATION COMPLETE")
        print("=" * 70)
        print(f"Total successful runs: {len(is_results)}/{total_tests}")
        
        if not is_results:
            print("\n✗ No successful backtests in IS period. Cannot proceed with validation.")
            return []
        
        # Select top N performers
        top_performers = is_results[:min(top_n, len(is_results))]
        
        # Check if we have 8D, 7D, 6D, 4D, or 2D parameters (strategy-aware)
        is_bb = top_performers and 'bb_window' in top_performers[0]['params']
        is_8d = top_performers and 'max_hold_hours' in top_performers[0]['params']
        is_7d = top_performers and 'macd_fast' in top_performers[0]['params'] and not is_8d
        is_6d = top_performers and 'adx_window' in top_performers[0]['params'] and 'adx_threshold' in top_performers[0]['params'] and not (is_7d or is_8d)
        is_4d = top_performers and 'atr_window' in top_performers[0]['params'] and 'atr_multiplier' in top_performers[0]['params'] and not (is_7d or is_6d or is_8d)
        
        print(f"\nTop {len(top_performers)} In-Sample Performers:")
        for rank, result in enumerate(top_performers, start=1):
            params = result['params']
            metrics = result['metrics']
            if is_8d:
                if is_bb:
                    print(f"  [{rank}] BB_W={params['bb_window']:2d}, BB_Std={params['bb_std_dev']:.1f}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f}, "
                          f"ADX_W={params['adx_window']:2d}, ADX_T={params['adx_threshold']:2d}, "
                          f"MACD_F={params['macd_fast']:2d}, MaxH={params['max_hold_hours']:3d}h "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
                else:
                    print(f"  [{rank}] Fast={params['fast_window']:2d}, Slow={params['slow_window']:2d}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f}, "
                          f"ADX_W={params['adx_window']:2d}, ADX_T={params['adx_threshold']:2d}, "
                          f"MACD_F={params['macd_fast']:2d}, MaxH={params['max_hold_hours']:3d}h "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
            elif is_7d:
                if is_bb:
                    print(f"  [{rank}] BB_W={params['bb_window']:2d}, BB_Std={params['bb_std_dev']:.1f}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f}, "
                          f"ADX_W={params['adx_window']:2d}, ADX_T={params['adx_threshold']:2d}, "
                          f"MACD_F={params['macd_fast']:2d} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
                else:
                    print(f"  [{rank}] Fast={params['fast_window']:2d}, Slow={params['slow_window']:2d}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f}, "
                          f"ADX_W={params['adx_window']:2d}, ADX_T={params['adx_threshold']:2d}, "
                          f"MACD_F={params['macd_fast']:2d} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
            elif is_6d:
                if is_bb:
                    print(f"  [{rank}] BB_W={params['bb_window']:2d}, BB_Std={params['bb_std_dev']:.1f}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f}, "
                          f"ADX_W={params['adx_window']:2d}, ADX_T={params['adx_threshold']:2d} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
                else:
                    print(f"  [{rank}] Fast={params['fast_window']:2d}, Slow={params['slow_window']:2d}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f}, "
                          f"ADX_W={params['adx_window']:2d}, ADX_T={params['adx_threshold']:2d} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
            elif is_4d:
                if is_bb:
                    print(f"  [{rank}] BB_W={params['bb_window']:2d}, BB_Std={params['bb_std_dev']:.1f}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
                else:
                    print(f"  [{rank}] Fast={params['fast_window']:2d}, Slow={params['slow_window']:2d}, "
                          f"ATR_W={params['atr_window']:2d}, ATR_M={params['atr_multiplier']:.1f} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
            else:
                if is_bb:
                    print(f"  [{rank}] BB_W={params['bb_window']:2d}, BB_Std={params['bb_std_dev']:.1f} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
                else:
                    print(f"  [{rank}] Fast={params['fast_window']:2d}, Slow={params['slow_window']:2d} "
                          f"→ Sharpe: {metrics['sharpe_ratio']:7.3f}, Return: {metrics['total_return']*100:6.2f}%")
        
        # ========== PHASE 2: OUT-OF-SAMPLE VALIDATION ==========
        print()
        print("=" * 70)
        print("PHASE 2: OUT-OF-SAMPLE VALIDATION")
        print("=" * 70)
        print(f"Validating top {len(top_performers)} configurations on unseen data...")
        print()
        
        # Validate each top performer on OOS period
        validated_results: List[Dict[str, Any]] = []
        
        for idx, is_result in enumerate(top_performers, start=1):
            params = is_result['params']
            
            # Extract strategy parameters (BB or EMA/SMA)
            if is_bb:
                fast_window = None
                slow_window = None
                bb_window = params.get('bb_window')
                bb_std_dev = params.get('bb_std_dev')
            else:
                fast_window = params.get('fast_window')
                slow_window = params.get('slow_window')
                bb_window = None
                bb_std_dev = None
            
            try:
                if is_8d:
                    atr_window = params['atr_window']
                    atr_multiplier = params['atr_multiplier']
                    adx_window = params['adx_window']
                    adx_threshold = params['adx_threshold']
                    macd_fast = params['macd_fast']
                    max_hold_hours = params['max_hold_hours']
                    oos_result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=fast_window,
                        slow_window=slow_window,
                        bb_window=bb_window,
                        bb_std_dev=bb_std_dev,
                        is_bb_strategy=is_bb,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        macd_fast=macd_fast,
                        max_hold_hours=max_hold_hours,
                        iteration=idx,
                        total=len(top_performers),
                        start_date=self.split_date,
                        end_date=self.end_date,
                        phase="OOS",
                    )
                elif is_7d:
                    atr_window = params['atr_window']
                    atr_multiplier = params['atr_multiplier']
                    adx_window = params['adx_window']
                    adx_threshold = params['adx_threshold']
                    macd_fast = params['macd_fast']
                    oos_result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=fast_window,
                        slow_window=slow_window,
                        bb_window=bb_window,
                        bb_std_dev=bb_std_dev,
                        is_bb_strategy=is_bb,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        macd_fast=macd_fast,
                        iteration=idx,
                        total=len(top_performers),
                        start_date=self.split_date,
                        end_date=self.end_date,
                        phase="OOS",
                    )
                elif is_6d:
                    atr_window = params['atr_window']
                    atr_multiplier = params['atr_multiplier']
                    adx_window = params['adx_window']
                    adx_threshold = params['adx_threshold']
                    oos_result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=fast_window,
                        slow_window=slow_window,
                        bb_window=bb_window,
                        bb_std_dev=bb_std_dev,
                        is_bb_strategy=is_bb,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=adx_window,
                        adx_threshold=adx_threshold,
                        iteration=idx,
                        total=len(top_performers),
                        start_date=self.split_date,
                        end_date=self.end_date,
                        phase="OOS",
                    )
                elif is_4d:
                    atr_window = params['atr_window']
                    atr_multiplier = params['atr_multiplier']
                    oos_result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=fast_window,
                        slow_window=slow_window,
                        bb_window=bb_window,
                        bb_std_dev=bb_std_dev,
                        is_bb_strategy=is_bb,
                        atr_window=atr_window,
                        atr_multiplier=atr_multiplier,
                        adx_window=None,
                        adx_threshold=None,
                        iteration=idx,
                        total=len(top_performers),
                        start_date=self.split_date,
                        end_date=self.end_date,
                        phase="OOS",
                    )
                else:
                    oos_result = self._run_single_backtest(
                        cached_handler=cached_handler,
                        fast_window=fast_window,
                        slow_window=slow_window,
                        bb_window=bb_window,
                        bb_std_dev=bb_std_dev,
                        is_bb_strategy=is_bb,
                        atr_window=None,
                        atr_multiplier=None,
                        adx_window=None,
                        adx_threshold=None,
                        iteration=idx,
                        total=len(top_performers),
                        start_date=self.split_date,
                        end_date=self.end_date,
                        phase="OOS",
                    )
                
                # Combine IS and OOS metrics
                validated_entry = {
                    'params': params,
                    'IS_metrics': is_result['metrics'],
                    'OOS_metrics': oos_result['metrics'],
                }
                validated_results.append(validated_entry)
                
            except Exception as e:
                print(f"  ✗ Error validating [{idx}/{len(top_performers)}]: {e}")
                continue
        
        print()
        print("=" * 70)
        print("WALK-FORWARD VALIDATION COMPLETE")
        print("=" * 70)
        print(f"Successfully validated: {len(validated_results)}/{len(top_performers)}")
        
        if validated_results:
            # Check if we have 8D, 7D, 6D, 4D, or 2D parameters (strategy-aware)
            first_params = validated_results[0]['params']
            is_bb = 'bb_window' in first_params or 'bb_std_dev' in first_params
            is_8d = 'max_hold_hours' in first_params
            is_7d = 'macd_fast' in first_params and not is_8d
            is_6d = 'adx_window' in first_params and 'adx_threshold' in first_params and not (is_7d or is_8d)
            is_4d = 'atr_window' in first_params and 'atr_multiplier' in first_params and not (is_7d or is_6d or is_8d)
            
            if is_8d:
                print(f"\nValidation Results (sorted by IS Sharpe):")
                print(f"{'Rank':<6} {'Params':<65} {'IS Sharpe':<12} {'OOS Sharpe':<12} {'IS Return':<12} {'OOS Return':<12}")
                print("-" * 135)
                for rank, result in enumerate(validated_results, start=1):
                    params = result['params']
                    is_m = result['IS_metrics']
                    oos_m = result['OOS_metrics']
                    if is_bb:
                        print(f"{rank:<6} (BB_W={params.get('bb_window', 0):2d},BB_Std={params.get('bb_std_dev', 0):.1f},"
                              f"ATR_W={params['atr_window']:2d},ATR_M={params['atr_multiplier']:.1f},"
                              f"ADX_W={params['adx_window']:2d},ADX_T={params['adx_threshold']:2d},"
                              f"MACD_F={params['macd_fast']:2d},MaxH={params['max_hold_hours']:3d}h){'':<5} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
                    else:
                        print(f"{rank:<6} ({params['fast_window']:2d},{params['slow_window']:2d},{params['atr_window']:2d},{params['atr_multiplier']:.1f},"
                              f"{params['adx_window']:2d},{params['adx_threshold']:2d},{params['macd_fast']:2d},{params['max_hold_hours']:3d}h){'':<5} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
            elif is_7d:
                print(f"\nValidation Results (sorted by IS Sharpe):")
                print(f"{'Rank':<6} {'Params':<55} {'IS Sharpe':<12} {'OOS Sharpe':<12} {'IS Return':<12} {'OOS Return':<12}")
                print("-" * 125)
                for rank, result in enumerate(validated_results, start=1):
                    params = result['params']
                    is_m = result['IS_metrics']
                    oos_m = result['OOS_metrics']
                    if is_bb:
                        print(f"{rank:<6} (BB_W={params.get('bb_window', 0):2d},BB_Std={params.get('bb_std_dev', 0):.1f},"
                              f"ATR_W={params['atr_window']:2d},ATR_M={params['atr_multiplier']:.1f},"
                              f"ADX_W={params['adx_window']:2d},ADX_T={params['adx_threshold']:2d},"
                              f"MACD_F={params['macd_fast']:2d}){'':<5} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
                    else:
                        print(f"{rank:<6} ({params['fast_window']:2d},{params['slow_window']:2d},{params['atr_window']:2d},{params['atr_multiplier']:.1f},"
                              f"{params['adx_window']:2d},{params['adx_threshold']:2d},{params['macd_fast']:2d}){'':<5} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
            elif is_6d:
                print(f"\nValidation Results (sorted by IS Sharpe):")
                print(f"{'Rank':<6} {'Params':<45} {'IS Sharpe':<12} {'OOS Sharpe':<12} {'IS Return':<12} {'OOS Return':<12}")
                print("-" * 105)
                for rank, result in enumerate(validated_results, start=1):
                    params = result['params']
                    is_m = result['IS_metrics']
                    oos_m = result['OOS_metrics']
                    if is_bb:
                        print(f"{rank:<6} (BB_W={params.get('bb_window', 0):2d},BB_Std={params.get('bb_std_dev', 0):.1f},"
                              f"ATR_W={params['atr_window']:2d},ATR_M={params['atr_multiplier']:.1f},"
                              f"ADX_W={params['adx_window']:2d},ADX_T={params['adx_threshold']:2d}){'':<15} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
                    else:
                        print(f"{rank:<6} ({params['fast_window']:2d},{params['slow_window']:2d},{params['atr_window']:2d},{params['atr_multiplier']:.1f},{params['adx_window']:2d},{params['adx_threshold']:2d}){'':<15} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
            elif is_4d:
                print(f"\nValidation Results (sorted by IS Sharpe):")
                print(f"{'Rank':<6} {'Params':<25} {'IS Sharpe':<12} {'OOS Sharpe':<12} {'IS Return':<12} {'OOS Return':<12}")
                print("-" * 85)
                for rank, result in enumerate(validated_results, start=1):
                    params = result['params']
                    is_m = result['IS_metrics']
                    oos_m = result['OOS_metrics']
                    if is_bb:
                        print(f"{rank:<6} (BB_W={params.get('bb_window', 0):2d},BB_Std={params.get('bb_std_dev', 0):.1f},"
                              f"ATR_W={params['atr_window']:2d},ATR_M={params['atr_multiplier']:.1f}){'':<8} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
                    else:
                        print(f"{rank:<6} ({params['fast_window']:2d},{params['slow_window']:2d},{params['atr_window']:2d},{params['atr_multiplier']:.1f}){'':<8} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
            else:
                print(f"\nValidation Results (sorted by IS Sharpe):")
                print(f"{'Rank':<6} {'Params':<15} {'IS Sharpe':<12} {'OOS Sharpe':<12} {'IS Return':<12} {'OOS Return':<12}")
                print("-" * 70)
                for rank, result in enumerate(validated_results, start=1):
                    params = result['params']
                    is_m = result['IS_metrics']
                    oos_m = result['OOS_metrics']
                    if is_bb:
                        print(f"{rank:<6} (BB_W={params.get('bb_window', 0):2d},BB_Std={params.get('bb_std_dev', 0):.1f}){'':<8} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
                    else:
                        print(f"{rank:<6} ({params['fast_window']:2d},{params['slow_window']:2d}){'':<8} "
                              f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                              f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
        
        self.results = validated_results
        return validated_results
    
    def _run_single_backtest(
        self,
        cached_handler: CachedDataHandler,
        fast_window: int = None,
        slow_window: int = None,
        iteration: int = 1,
        total: int = 1,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phase: str = "",
        atr_window: Optional[int] = None,
        atr_multiplier: Optional[float] = None,
        adx_window: Optional[int] = None,
        adx_threshold: Optional[int] = None,
        macd_fast: Optional[int] = None,
        max_hold_hours: Optional[int] = None,
        bb_window: Optional[int] = None,
        bb_std_dev: Optional[float] = None,
        is_bb_strategy: bool = False,
    ) -> Dict[str, Any]:
        """
        Run a single backtest iteration with specific parameters.
        
        Args:
            cached_handler: Mock handler with pre-loaded data
            fast_window: Fast EMA period
            slow_window: Slow EMA period
            iteration: Current iteration number
            total: Total number of iterations
            start_date: Optional override for backtest start date
            end_date: Optional override for backtest end date
            phase: Optional phase label (e.g., "IS", "OOS") for logging
            atr_window: Optional ATR window period (for VolatilityAdjustedStrategy)
            atr_multiplier: Optional ATR multiplier (for VolatilityAdjustedStrategy)
            adx_window: Optional ADX window period (for Market Regime Filter)
            adx_threshold: Optional ADX threshold (for Market Regime Filter)
            macd_fast: Optional MACD fast EMA window (for Momentum Filter)
            max_hold_hours: Optional max hold hours (for 8D optimization)
        
        Returns:
            Dictionary with params and metrics
        """
        # Use override dates if provided, otherwise use instance defaults
        bt_start = start_date or self.start_date
        bt_end = end_date or self.end_date
        
        # Create strategy config with current parameters
        # Merge base config params with optimization params
        base_params = self.base_strategy_config.params.copy() if self.base_strategy_config else {}
        
        # Build params dict with optimization overrides
        params_dict = {
            **base_params,  # Include all params from config.json
        }
        
        # Add strategy-specific parameters based on strategy type
        if is_bb_strategy:
            # For BollingerBandStrategy, use BB parameters
            if bb_window is not None:
                params_dict["bb_window"] = bb_window
            if bb_std_dev is not None:
                params_dict["bb_std_dev"] = bb_std_dev
        else:
            # For EMA/SMA strategies, use fast/slow windows
            if fast_window is not None:
                params_dict["fast_window"] = fast_window
            if slow_window is not None:
                params_dict["slow_window"] = slow_window
        
        # Add ATR parameters if provided (for 4D/6D optimization)
        if atr_window is not None:
            params_dict["atr_window"] = atr_window
        if atr_multiplier is not None:
            params_dict["atr_multiplier"] = atr_multiplier
        
        strategy_config = StrategyConfig(
            name=self.base_strategy_config.name if self.base_strategy_config else "sma_cross",
            symbol=self.symbol,
            timeframe=self.timeframe,
            params=params_dict,
            max_hold_hours=max_hold_hours
        )
        
        # Instantiate market regime filter if ADX parameters are provided
        regime_filter = None
        if adx_window is not None and adx_threshold is not None:
            filter_config = RegimeFilterConfig(
                adx_window=adx_window,
                adx_threshold=adx_threshold
            )
            regime_filter = ADXVolatilityFilter(config=filter_config)
        
        # Instantiate momentum filter (MACD) if config is available
        momentum_filter = None
        applied_momentum_config: Optional[MomentumFilterConfig] = None
        base_momentum_config = self.base_momentum_filter_config
        if macd_fast is not None:
            macd_slow = base_momentum_config.macd_slow if base_momentum_config else 26
            macd_signal = base_momentum_config.macd_signal if base_momentum_config else 9
            applied_momentum_config = MomentumFilterConfig(
                macd_fast=macd_fast,
                macd_slow=macd_slow,
                macd_signal=macd_signal,
            )
            momentum_filter = MACDConfirmationFilter(config=applied_momentum_config)
        elif base_momentum_config is not None:
            applied_momentum_config = base_momentum_config
            momentum_filter = MACDConfirmationFilter(config=applied_momentum_config)
        
        # Instantiate strategy using factory function
        strategy_map = {
            "sma_cross": SmaCrossStrategy,
            "SmaCrossStrategy": SmaCrossStrategy,
            "VolatilityAdjustedStrategy": VolatilityAdjustedStrategy,
            "BollingerBandStrategy": BollingerBandStrategy,
            "bollinger_band": BollingerBandStrategy,
        }
        
        strategy_name = strategy_config.name
        strategy_class = strategy_map.get(strategy_name, SmaCrossStrategy)
        strategy = strategy_class(
            config=strategy_config,
            regime_filter=regime_filter,
            momentum_filter=momentum_filter,
        )
        
        # Create backtester with cached data handler
        backtester = Backtester(
            data_handler=cached_handler,
            strategy=strategy,
            symbol=self.symbol,
            timeframe=self.timeframe,
            initial_capital=self.initial_capital,
            risk_config=self.risk_config,
        )
        
        # Run backtest
        metrics = backtester.run(
            start_date=bt_start,
            end_date=bt_end,
        )
        
        # Extract metrics (remove 'data' field to save space)
        result_metrics = {
            'total_return': metrics['total_return'],
            'sharpe_ratio': metrics['sharpe_ratio'],
            'max_drawdown': metrics['max_drawdown'],
        }
        
        # Log progress
        sharpe = result_metrics['sharpe_ratio']
        sharpe_str = f"{sharpe:.3f}" if not pd.isna(sharpe) else "N/A"
        
        phase_str = f"[{phase}] " if phase else ""
        
        # Build params dict for return value (strategy-aware)
        params_dict = {}
        
        if is_bb_strategy:
            # For BB strategy, use BB parameters
            if bb_window is not None:
                params_dict['bb_window'] = bb_window
            if bb_std_dev is not None:
                params_dict['bb_std_dev'] = bb_std_dev
        else:
            # For EMA/SMA strategies, use fast/slow windows
            if fast_window is not None:
                params_dict['fast_window'] = fast_window
            if slow_window is not None:
                params_dict['slow_window'] = slow_window
        
        # Add ATR parameters if provided
        if atr_window is not None:
            params_dict['atr_window'] = atr_window
        if atr_multiplier is not None:
            params_dict['atr_multiplier'] = atr_multiplier
        
        # Add ADX parameters if provided
        if adx_window is not None:
            params_dict['adx_window'] = adx_window
        if adx_threshold is not None:
            params_dict['adx_threshold'] = adx_threshold
        
        if applied_momentum_config is not None:
            params_dict['macd_fast'] = applied_momentum_config.macd_fast
            params_dict['macd_slow'] = applied_momentum_config.macd_slow
            params_dict['macd_signal'] = applied_momentum_config.macd_signal
        
        # Add max_hold_hours if provided
        if max_hold_hours is not None:
            params_dict['max_hold_hours'] = max_hold_hours
        
        # Build log message (strategy-aware)
        if is_bb_strategy:
            # BB strategy logging
            if max_hold_hours is not None and macd_fast is not None and adx_window is not None and atr_window is not None:
                print(f"  {phase_str}[{iteration:3d}/{total}] BB_W={bb_window:2d}, BB_Std={bb_std_dev:.1f}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f}, "
                      f"ADX_W={adx_window:2d}, ADX_T={adx_threshold:2d}, MACD_F={macd_fast:2d}, MaxH={max_hold_hours:3d}h "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            elif macd_fast is not None and adx_window is not None and atr_window is not None:
                print(f"  {phase_str}[{iteration:3d}/{total}] BB_W={bb_window:2d}, BB_Std={bb_std_dev:.1f}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f}, "
                      f"ADX_W={adx_window:2d}, ADX_T={adx_threshold:2d}, MACD_F={macd_fast:2d} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            elif adx_window is not None and adx_threshold is not None and atr_window is not None:
                print(f"  {phase_str}[{iteration:3d}/{total}] BB_W={bb_window:2d}, BB_Std={bb_std_dev:.1f}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f}, "
                      f"ADX_W={adx_window:2d}, ADX_T={adx_threshold:2d} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            elif atr_window is not None and atr_multiplier is not None:
                print(f"  {phase_str}[{iteration:3d}/{total}] BB_W={bb_window:2d}, BB_Std={bb_std_dev:.1f}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            else:
                print(f"  {phase_str}[{iteration:3d}/{total}] BB_W={bb_window:2d}, BB_Std={bb_std_dev:.1f} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
        else:
            # EMA/SMA strategy logging (original)
            if max_hold_hours is not None:
                print(f"  {phase_str}[{iteration:3d}/{total}] Fast={fast_window:2d}, Slow={slow_window:2d}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f}, "
                      f"ADX_W={adx_window:2d}, ADX_T={adx_threshold:2d}, MACD_F={macd_fast:2d}, MaxH={max_hold_hours:3d}h "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            elif macd_fast is not None:
                print(f"  {phase_str}[{iteration:3d}/{total}] Fast={fast_window:2d}, Slow={slow_window:2d}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f}, "
                      f"ADX_W={adx_window:2d}, ADX_T={adx_threshold:2d}, MACD_F={macd_fast:2d} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            elif adx_window is not None and adx_threshold is not None:
                # 6D optimization: show all 6 parameters
                print(f"  {phase_str}[{iteration:3d}/{total}] Fast={fast_window:2d}, Slow={slow_window:2d}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f}, "
                      f"ADX_W={adx_window:2d}, ADX_T={adx_threshold:2d} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            elif atr_window is not None and atr_multiplier is not None:
                # 4D optimization: show ATR parameters
                print(f"  {phase_str}[{iteration:3d}/{total}] Fast={fast_window:2d}, Slow={slow_window:2d}, "
                      f"ATR_W={atr_window:2d}, ATR_M={atr_multiplier:.1f} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
            else:
                # 2D optimization: show only EMA parameters
                print(f"  {phase_str}[{iteration:3d}/{total}] Fast={fast_window:2d}, Slow={slow_window:2d} "
                      f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
        
        return {
            'params': params_dict,
            'metrics': result_metrics,
        }
    
    def save_results(self, output_path: Optional[str] = None) -> str:
        """
        Save optimization results to JSON file.
        
        Args:
            output_path: Optional custom output path
        
        Returns:
            Path to the saved file
        """
        if not self.results:
            raise ValueError("No results to save. Run optimization first.")
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"results/optimization_{timestamp}.json"
        
        # Ensure results directory exists
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare output data
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'total_combinations_tested': len(self.results),
        }
        
        # Add split_date to metadata if walk-forward validation was used
        if self.split_date:
            metadata['split_date'] = self.split_date
            metadata['validation_mode'] = 'walk_forward'
            metadata['in_sample_period'] = f"{self.start_date} to {self.split_date}"
            metadata['out_of_sample_period'] = f"{self.split_date} to {self.end_date}"
        else:
            metadata['validation_mode'] = 'standard'
        
        output_data = {
            'metadata': metadata,
            'results': self.results,
        }
        
        # Save to JSON
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"\n✓ Results saved to: {output_path}")
        print(f"  File size: {output_file.stat().st_size / 1024:.2f} KB")
        
        return str(output_file)
    
    @staticmethod
    def _timeframe_to_minutes(timeframe: str) -> int:
        """Convert timeframe string to minutes."""
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
            return 60  # Default to 1 hour


def main() -> int:
    """
    Main entry point for the optimization script.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description='Optimize trading strategy parameters using grid search with optional walk-forward validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard optimization (no validation)
  %(prog)s
  %(prog)s --start-date 2023-01-01 --end-date 2023-12-31
  %(prog)s --symbol ETH/USDT --timeframe 4h
  %(prog)s --fast 8,12,15,21 --slow 35,50,80,100
  
  # 4D optimization (VolatilityAdjustedStrategy with ATR parameters)
  %(prog)s --fast 8,12,15 --slow 50,80,100 --atr-window 10,14,20 --atr-multiplier 1.5,2.0,2.5
  
  # 6D optimization (VolatilityAdjustedStrategy + Market Regime Filter)
  %(prog)s --fast 8,12 --slow 35,50 --atr-window 10,14 --atr-multiplier 2.0 --adx-window 10,14,20 --adx-threshold 20,25,30,35
  
  # Walk-forward optimization with Out-of-Sample validation
  %(prog)s --start-date 2023-01-01 --end-date 2023-12-31 --split-date 2023-10-01
  %(prog)s --start-date 2023-01-01 --end-date 2024-01-01 --split-date 2023-07-01 --top-n 10
  %(prog)s --start-date 2020-01-01 --end-date 2025-11-20 --split-date 2023-01-01 --fast 8,12,15,21 --slow 35,50,80,100 --atr-window 10,14,20 --atr-multiplier 1.5,2.0,2.5 --adx-window 10,14,20 --adx-threshold 20,25,30,35
        """
    )
    
    parser.add_argument(
        '--symbol',
        type=str,
        default='BTC/USDT',
        help='Trading pair (default: BTC/USDT)'
    )
    
    parser.add_argument(
        '--timeframe',
        type=str,
        default='4h',
        help='Candle timeframe (default: 4h)'
    )
    
    parser.add_argument(
        '--start-date',
        type=str,
        default='2023-01-01',
        help='Backtest start date YYYY-MM-DD (default: 2023-01-01)'
    )
    
    parser.add_argument(
        '--end-date',
        type=str,
        default='2023-12-31',
        help='Backtest end date YYYY-MM-DD (default: 2023-12-31)'
    )
    
    parser.add_argument(
        '--split-date',
        type=str,
        default=None,
        help='Optional split date for walk-forward validation YYYY-MM-DD. '
             'If provided, runs In-Sample optimization from start-date to split-date, '
             'then validates top performers Out-of-Sample from split-date to end-date.'
    )
    
    parser.add_argument(
        '--top-n',
        type=int,
        default=5,
        help='Number of top performers to validate in OOS period (default: 5, only used with --split-date)'
    )
    
    parser.add_argument(
        '--fast',
        type=str,
        default='8,13,21',
        help='Fast window range as comma-separated values (default: 8,13,21 for 4H)'
    )
    
    parser.add_argument(
        '--slow',
        type=str,
        default='21,34,50,89',
        help='Slow window range as comma-separated values (default: 21,34,50,89 for 4H)'
    )
    
    parser.add_argument(
        '--atr-window',
        type=str,
        default='10,14,20',
        help='ATR window range as comma-separated values (default: 10,14,20)'
    )
    
    parser.add_argument(
        '--atr-multiplier',
        type=str,
        default='1.5,2.0,2.5',
        help='ATR multiplier range as comma-separated values (default: 1.5,2.0,2.5)'
    )
    
    parser.add_argument(
        '--adx-window',
        type=str,
        default='10,14,20',
        help='ADX window range as comma-separated values (default: 10,14,20)'
    )
    
    parser.add_argument(
        '--adx-threshold',
        type=str,
        default='20,25',
        help='ADX threshold range as comma-separated values (default: 20,25 for 4H; for Market Regime Filter)'
    )
    
    parser.add_argument(
        '--macd-fast',
        type=str,
        default='12,16',
        help='MACD fast window range as comma-separated values (default: 12,16 for 4H)'
    )
    
    parser.add_argument(
        '--max-hold-hours',
        type=str,
        default=None,
        help='Max hold hours range as comma-separated values (default: None; for 8D optimization, e.g., 48,72,96,120)'
    )
    
    parser.add_argument(
        '--bb-window',
        type=str,
        default=None,
        help='Bollinger Band window range as comma-separated values (default: None; for BollingerBandStrategy, e.g., 14,20,30)'
    )
    
    parser.add_argument(
        '--bb-std-dev',
        type=str,
        default=None,
        help='Bollinger Band standard deviation multiplier range as comma-separated values (default: None; for BollingerBandStrategy, e.g., 1.5,2.0,2.5)'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output file path (default: results/optimization_TIMESTAMP.json)'
    )
    
    args = parser.parse_args()
    
    try:
        # ========== STEP 0: Load strategy from config.json ==========
        print("=" * 70)
        print("STRATEGY CONFIGURATION")
        print("=" * 70)
        
        # Load full config to get risk settings
        risk_config = None
        try:
            bot_config = BotConfig.load_from_file("settings/config.json")
            risk_config = bot_config.risk
            print(f"✓ Risk config loaded from config.json:")
            print(f"  Stop Loss:    {risk_config.stop_loss_pct*100:.1f}%")
            print(f"  Take Profit:  {risk_config.take_profit_pct*100:.1f}%")
            print()
        except Exception as e:
            print(f"⚠ Warning: Could not load risk config from config.json: {e}")
            print("  SL/TP enforcement will be disabled in backtests")
            print()
        
        try:
            strategy, strategy_config = load_strategy_from_config()
            print(f"✓ Strategy loaded from config.json:")
            print(f"  Strategy Name: {strategy_config.name}")
            print(f"  Symbol:        {strategy_config.symbol}")
            print(f"  Timeframe:     {strategy_config.timeframe}")
            print(f"  Parameters from config.json:")
            for key, value in strategy_config.params.items():
                print(f"    - {key}: {value}")
            print()
        except Exception as e:
            print(f"⚠ Warning: Could not load strategy from config.json: {e}")
            print("  Falling back to default SmaCrossStrategy")
            print()
            strategy_config = StrategyConfig(
                name="sma_cross",
                symbol=args.symbol,
                timeframe=args.timeframe,
                params={}
            )
        
        # Detect strategy type (BollingerBandStrategy vs VolatilityAdjustedStrategy)
        is_bb_strategy = (
            strategy_config.name.lower() == "bollingerbandstrategy" or
            strategy_config.name.lower() == "bollinger_band" or
            strategy_config.name.lower() == "bollingerband"
        )
        
        if is_bb_strategy:
            print("=" * 70)
            print("STRATEGY TYPE: BOLLINGER BAND (Mean Reversion)")
            print("=" * 70)
            print("Using BB parameters (bb_window, bb_std_dev) instead of EMA/SMA parameters")
            print()
        
        # Parse parameter ranges based on strategy type
        if is_bb_strategy:
            # For BB strategy, parse BB parameters
            bb_window_range = None
            bb_std_dev_range = None
            
            if args.bb_window:
                bb_window_range = [int(x.strip()) for x in args.bb_window.split(',')]
            else:
                # Default BB ranges if not provided
                bb_window_range = [14, 20, 30]
                print(f"⚠ Using default BB window range: {bb_window_range}")
            
            if args.bb_std_dev:
                bb_std_dev_range = [float(x.strip()) for x in args.bb_std_dev.split(',')]
            else:
                # Default BB ranges if not provided
                bb_std_dev_range = [1.5, 2.0, 2.5]
                print(f"⚠ Using default BB std dev range: {bb_std_dev_range}")
            
            # BB strategy doesn't use fast/slow windows, but we need placeholders for backward compatibility
            # These won't be used in parameter combinations
            fast_range = []  # Empty - not used for BB
            slow_range = []  # Empty - not used for BB
            
            # Validate: both BB params must be provided or both use defaults
            if (bb_window_range is None) != (bb_std_dev_range is None):
                raise ValueError("--bb-window and --bb-std-dev must both be provided for BollingerBandStrategy optimization")
        else:
            # For EMA/SMA strategies, parse fast/slow windows
            fast_range = [int(x.strip()) for x in args.fast.split(',')]
            slow_range = [int(x.strip()) for x in args.slow.split(',')]
            bb_window_range = None
            bb_std_dev_range = None
        
        # Parse ATR parameters if provided
        atr_window_range = None
        atr_multiplier_range = None
        if args.atr_window:
            atr_window_range = [int(x.strip()) for x in args.atr_window.split(',')]
        if args.atr_multiplier:
            atr_multiplier_range = [float(x.strip()) for x in args.atr_multiplier.split(',')]
        
        # Parse ADX parameters if provided
        adx_window_range = None
        adx_threshold_range = None
        if args.adx_window:
            adx_window_range = [int(x.strip()) for x in args.adx_window.split(',')]
        if args.adx_threshold:
            adx_threshold_range = [int(x.strip()) for x in args.adx_threshold.split(',')]
        
        # Parse MACD parameters (momentum filter) if provided
        macd_fast_range = None
        if args.macd_fast:
            macd_fast_range = [int(x.strip()) for x in args.macd_fast.split(',')]
        
        # Parse max hold hours if provided
        max_hold_hours_range = None
        if args.max_hold_hours:
            max_hold_hours_range = [int(x.strip()) for x in args.max_hold_hours.split(',')]
        
        # Validate: if one ATR param is provided, both should be provided
        if (atr_window_range is None) != (atr_multiplier_range is None):
            print("⚠ Warning: --atr-window and --atr-multiplier must both be provided for 4D optimization.")
            print("  Falling back to 2D optimization (fast_window, slow_window only)")
            atr_window_range = None
            atr_multiplier_range = None
        
        # Validate: if one ADX param is provided, both should be provided (and ATR params too for higher dimensions)
        if (adx_window_range is None) != (adx_threshold_range is None):
            print("⚠ Warning: --adx-window and --adx-threshold must both be provided for 6D optimization.")
            print("  Falling back to 4D optimization (without ADX parameters)")
            adx_window_range = None
            adx_threshold_range = None
        
        # Validate: ADX params require ATR params for 6D optimization
        if (adx_window_range is not None or adx_threshold_range is not None):
            if atr_window_range is None or atr_multiplier_range is None:
                print("⚠ Warning: --adx-window and --adx-threshold require --atr-window and --atr-multiplier for 6D optimization.")
                print("  Falling back to 4D optimization (without ADX parameters)")
                adx_window_range = None
                adx_threshold_range = None
        
        # Validate: MACD fast range requires full 6D setup to enable 7D
        if macd_fast_range is not None:
            if is_bb_strategy:
                # For BB: MACD requires ATR, ADX ranges for 7D
                missing_dimensions = any(x is None for x in [atr_window_range, atr_multiplier_range, adx_window_range, adx_threshold_range])
                if missing_dimensions:
                    print("⚠ Warning: --macd-fast requires ATR and ADX ranges for 7D BB optimization.")
                    print("  Falling back to lower-dimensional optimization without MACD sweep")
                    macd_fast_range = None
            else:
                # For EMA/SMA strategies
                missing_dimensions = any(x is None for x in [atr_window_range, atr_multiplier_range, adx_window_range, adx_threshold_range])
                if missing_dimensions:
                    print("⚠ Warning: --macd-fast requires ATR and ADX ranges for 7D optimization.")
                    print("  Falling back to lower-dimensional optimization without MACD sweep")
                    macd_fast_range = None
        
        # Validate: max_hold_hours requires full 7D setup to enable 8D
        if max_hold_hours_range is not None:
            if is_bb_strategy:
                # For BB: max_hold_hours requires ATR, ADX, MACD ranges for 8D
                missing_dimensions = any(x is None for x in [atr_window_range, atr_multiplier_range, adx_window_range, adx_threshold_range, macd_fast_range])
                if missing_dimensions:
                    print("⚠ Warning: --max-hold-hours requires ATR, ADX, and MACD ranges for 8D BB optimization.")
                    print("  Falling back to lower-dimensional optimization without max hold hours sweep")
                    max_hold_hours_range = None
            else:
                # For EMA/SMA strategies
                missing_dimensions = any(x is None for x in [atr_window_range, atr_multiplier_range, adx_window_range, adx_threshold_range, macd_fast_range])
                if missing_dimensions:
                    print("⚠ Warning: --max-hold-hours requires ATR, ADX, and MACD ranges for 8D optimization.")
                    print("  Falling back to lower-dimensional optimization without max hold hours sweep")
                    max_hold_hours_range = None
        
        print("=" * 70)
        print("OPTIMIZATION PARAMETERS")
        print("=" * 70)
        print(f"Command-line arguments:")
        print(f"  Symbol:      {args.symbol}")
        print(f"  Timeframe:   {args.timeframe}")
        print(f"  Start Date:  {args.start_date}")
        print(f"  End Date:    {args.end_date}")
        if args.split_date:
            print(f"  Split Date:  {args.split_date} (Walk-Forward Mode)")
        
        if is_bb_strategy:
            # Display BB-specific parameters
            print(f"  BB Window Range:  {bb_window_range}")
            print(f"  BB Std Dev Range:  {bb_std_dev_range}")
            
            if max_hold_hours_range and macd_fast_range and adx_window_range and adx_threshold_range and atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  ADX Window Range:  {adx_window_range}")
                print(f"  ADX Threshold Range:  {adx_threshold_range}")
                print(f"  MACD Fast Range:  {macd_fast_range}")
                print(f"  Max Hold Hours Range:  {max_hold_hours_range}")
                print(f"  → 8D BB Optimization Mode (BB_W, BB_Std, ATR_W, ATR_M, ADX_W, ADX_T, MACD_F, MaxH)")
            elif macd_fast_range and adx_window_range and adx_threshold_range and atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  ADX Window Range:  {adx_window_range}")
                print(f"  ADX Threshold Range:  {adx_threshold_range}")
                print(f"  MACD Fast Range:  {macd_fast_range}")
                print(f"  → 7D BB Optimization Mode (BB_W, BB_Std, ATR_W, ATR_M, ADX_W, ADX_T, MACD_F)")
            elif adx_window_range and adx_threshold_range and atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  ADX Window Range:  {adx_window_range}")
                print(f"  ADX Threshold Range:  {adx_threshold_range}")
                print(f"  → 6D BB Optimization Mode (BB_W, BB_Std, ATR_W, ATR_M, ADX_W, ADX_T)")
            elif atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  → 4D BB Optimization Mode (BB_W, BB_Std, ATR_W, ATR_M)")
            else:
                print(f"  → 2D BB Optimization Mode (BB_W, BB_Std only)")
        else:
            # Display EMA/SMA-specific parameters
            print(f"  Fast Range:  {fast_range}")
            print(f"  Slow Range:  {slow_range}")
            
            if max_hold_hours_range and macd_fast_range and adx_window_range and adx_threshold_range and atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  ADX Window Range:  {adx_window_range}")
                print(f"  ADX Threshold Range:  {adx_threshold_range}")
                print(f"  MACD Fast Range:  {macd_fast_range}")
                print(f"  Max Hold Hours Range:  {max_hold_hours_range}")
                print(f"  → 8D Optimization Mode (Fast, Slow, ATR_W, ATR_M, ADX_W, ADX_T, MACD_F, MaxH)")
            elif macd_fast_range and adx_window_range and adx_threshold_range and atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  ADX Window Range:  {adx_window_range}")
                print(f"  ADX Threshold Range:  {adx_threshold_range}")
                print(f"  MACD Fast Range:  {macd_fast_range}")
                print(f"  → 7D Optimization Mode (Fast, Slow, ATR_W, ATR_M, ADX_W, ADX_T, MACD_F)")
            elif adx_window_range and adx_threshold_range and atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  ADX Window Range:  {adx_window_range}")
                print(f"  ADX Threshold Range:  {adx_threshold_range}")
                print(f"  → 6D Optimization Mode (Fast, Slow, ATR_W, ATR_M, ADX_W, ADX_T)")
            elif atr_window_range and atr_multiplier_range:
                print(f"  ATR Window Range:  {atr_window_range}")
                print(f"  ATR Multiplier Range:  {atr_multiplier_range}")
                print(f"  → 4D Optimization Mode (Fast, Slow, ATR_W, ATR_M)")
            else:
                print(f"  → 2D Optimization Mode (Fast, Slow only)")
        print()
        
        if risk_config:
            print("=" * 70)
            print("🛡️  RISK MANAGEMENT: Stop-Loss/Take-Profit ENABLED")
            print("=" * 70)
            print("✓ SL/TP enforcement is ACTIVE in backtests")
            print(f"  Stop Loss:    {risk_config.stop_loss_pct*100:.1f}%")
            print(f"  Take Profit:  {risk_config.take_profit_pct*100:.1f}%")
            if 'stop_loss_price' in strategy_config.params or hasattr(strategy, 'get_stop_loss_price'):
                print(f"  Strategy '{strategy_config.name}' provides dynamic stop-loss (ATR-based)")
            print("  Positions will exit early when SL/TP levels are hit")
            print()
        else:
            print("=" * 70)
            print("⚠️  BACKTESTING MODE: Stop-Loss/Take-Profit NOT Enforced")
            print("=" * 70)
            print("Note: Risk config not loaded. SL/TP enforcement disabled.")
            print("      Backtests will only follow strategy signals.")
            print()
        
        # Create optimizer with strategy config and risk config
        optimizer = StrategyOptimizer(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            split_date=args.split_date,
            base_strategy_config=strategy_config,
            risk_config=risk_config,
            momentum_filter_config=getattr(bot_config, "momentum_filter", None) if 'bot_config' in locals() else None,
        )
        
        # STEP 1: Load data ONCE
        optimizer.load_data_once()
        
        # STEP 2: Run optimization (Compute Many)
        if args.split_date:
            # Walk-forward optimization with In-Sample/Out-of-Sample validation
            results = optimizer.optimize_with_validation(
                fast_window_range=fast_range,
                slow_window_range=slow_range,
                top_n=args.top_n,
                atr_window_range=atr_window_range,
                atr_multiplier_range=atr_multiplier_range,
                adx_window_range=adx_window_range,
                adx_threshold_range=adx_threshold_range,
                macd_fast_range=macd_fast_range,
                max_hold_hours_range=max_hold_hours_range,
                bb_window_range=bb_window_range if is_bb_strategy else None,
                bb_std_dev_range=bb_std_dev_range if is_bb_strategy else None,
                is_bb_strategy=is_bb_strategy,
            )
        else:
            # Standard optimization (no validation)
            results = optimizer.optimize(
                fast_window_range=fast_range,
                slow_window_range=slow_range,
                atr_window_range=atr_window_range,
                atr_multiplier_range=atr_multiplier_range,
                adx_window_range=adx_window_range,
                adx_threshold_range=adx_threshold_range,
                macd_fast_range=macd_fast_range,
                max_hold_hours_range=max_hold_hours_range,
                bb_window_range=bb_window_range if is_bb_strategy else None,
                bb_std_dev_range=bb_std_dev_range if is_bb_strategy else None,
                is_bb_strategy=is_bb_strategy,
            )
        
        # Check if optimization produced any results
        if not results or not optimizer.results:
            print("\n✗ Optimization failed: No results generated.")
            print("  Possible causes:")
            print("    - All parameter combinations failed during backtesting")
            print("    - Data loading issues")
            print("    - Invalid parameter ranges")
            print("    - Strategy initialization errors")
            print("    - Check error messages above for specific failures")
            return 1
        
        # STEP 3: Save results
        output_path = optimizer.save_results(output_path=args.output)
        
        print(f"\n✓ Optimization complete!")
        print(f"  Next step: Analyze results in {output_path}")
        if args.split_date:
            print(f"  Review IS/OOS metrics to identify robust parameters")
        else:
            print(f"  Use: python tools/analyze_optimization.py {output_path}")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠ Optimization interrupted by user")
        return 130
        
    except Exception as e:
        print(f"\n✗ Optimization failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

