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
from typing import Dict, List, Any, Optional
import itertools

import pandas as pd
import ccxt

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data.handler import CryptoDataHandler
from app.core.interfaces import IDataHandler, BaseStrategy
from app.backtesting.engine import Backtester
from app.strategies.sma_cross import SmaCrossStrategy
from app.config.models import StrategyConfig
from app.execution.mock_executor import MockExecutor


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
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.start_date = start_date
        self.end_date = end_date
        self.split_date = split_date
        self.initial_capital = initial_capital
        
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
            
            # Calculate buffer start (add extra candles for SMA calculation)
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
    ) -> List[Dict[str, Any]]:
        """
        Perform grid search optimization over parameter combinations.
        
        Args:
            fast_window_range: List of fast SMA window values to test
            slow_window_range: List of slow SMA window values to test
        
        Returns:
            List of results sorted by Sharpe ratio (descending)
        """
        if self.cached_data is None:
            raise RuntimeError("Data not loaded. Call load_data_once() first.")
        
        print("=" * 70)
        print("STARTING GRID SEARCH OPTIMIZATION")
        print("=" * 70)
        
        # Generate all parameter combinations
        param_combinations = list(itertools.product(fast_window_range, slow_window_range))
        
        # Filter out invalid combinations (fast >= slow)
        valid_combinations = [
            (fast, slow) for fast, slow in param_combinations
            if fast < slow
        ]
        
        total_tests = len(valid_combinations)
        print(f"Parameter Space:")
        print(f"  Fast Window: {fast_window_range}")
        print(f"  Slow Window: {slow_window_range}")
        print(f"  Total Combinations: {len(param_combinations)}")
        print(f"  Valid Combinations: {total_tests} (fast < slow)")
        print()
        
        # Create cached data handler (used for ALL iterations)
        cached_handler = CachedDataHandler(
            cached_data=self.cached_data,
            symbol=self.symbol,
            timeframe=self.timeframe,
        )
        
        # Run backtest for each valid combination
        for idx, (fast_window, slow_window) in enumerate(valid_combinations, start=1):
            try:
                result = self._run_single_backtest(
                    cached_handler=cached_handler,
                    fast_window=fast_window,
                    slow_window=slow_window,
                    iteration=idx,
                    total=total_tests,
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
            print(f"  Fast Window: {best['params']['fast_window']}")
            print(f"  Slow Window: {best['params']['slow_window']}")
            print(f"  Sharpe Ratio: {best['metrics']['sharpe_ratio']:.4f}")
            print(f"  Total Return: {best['metrics']['total_return'] * 100:.2f}%")
            print(f"  Max Drawdown: {best['metrics']['max_drawdown'] * 100:.2f}%")
        
        return self.results
    
    def optimize_with_validation(
        self,
        fast_window_range: List[int],
        slow_window_range: List[int],
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Perform grid search with In-Sample/Out-of-Sample validation.
        
        Two-phase execution:
        1. Phase 1 (In-Sample): Run full grid search on data from start_date to split_date
        2. Phase 2 (Out-of-Sample): Validate top N performers on data from split_date to end_date
        
        Args:
            fast_window_range: List of fast SMA window values to test
            slow_window_range: List of slow SMA window values to test
            top_n: Number of top performers to validate (default: 5)
        
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
        
        # Generate all parameter combinations
        param_combinations = list(itertools.product(fast_window_range, slow_window_range))
        
        # Filter out invalid combinations (fast >= slow)
        valid_combinations = [
            (fast, slow) for fast, slow in param_combinations
            if fast < slow
        ]
        
        total_tests = len(valid_combinations)
        print(f"Parameter Space:")
        print(f"  Fast Window: {fast_window_range}")
        print(f"  Slow Window: {slow_window_range}")
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
        for idx, (fast_window, slow_window) in enumerate(valid_combinations, start=1):
            try:
                result = self._run_single_backtest(
                    cached_handler=cached_handler,
                    fast_window=fast_window,
                    slow_window=slow_window,
                    iteration=idx,
                    total=total_tests,
                    start_date=self.start_date,
                    end_date=self.split_date,
                    phase="IS",
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
        
        print(f"\nTop {len(top_performers)} In-Sample Performers:")
        for rank, result in enumerate(top_performers, start=1):
            params = result['params']
            metrics = result['metrics']
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
            fast_window = params['fast_window']
            slow_window = params['slow_window']
            
            try:
                oos_result = self._run_single_backtest(
                    cached_handler=cached_handler,
                    fast_window=fast_window,
                    slow_window=slow_window,
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
            print(f"\nValidation Results (sorted by IS Sharpe):")
            print(f"{'Rank':<6} {'Params':<15} {'IS Sharpe':<12} {'OOS Sharpe':<12} {'IS Return':<12} {'OOS Return':<12}")
            print("-" * 70)
            for rank, result in enumerate(validated_results, start=1):
                params = result['params']
                is_m = result['IS_metrics']
                oos_m = result['OOS_metrics']
                print(f"{rank:<6} ({params['fast_window']:2d},{params['slow_window']:2d}){'':<8} "
                      f"{is_m['sharpe_ratio']:>7.3f}      {oos_m['sharpe_ratio']:>7.3f}      "
                      f"{is_m['total_return']*100:>6.2f}%      {oos_m['total_return']*100:>6.2f}%")
        
        self.results = validated_results
        return validated_results
    
    def _run_single_backtest(
        self,
        cached_handler: CachedDataHandler,
        fast_window: int,
        slow_window: int,
        iteration: int,
        total: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phase: str = "",
    ) -> Dict[str, Any]:
        """
        Run a single backtest iteration with specific parameters.
        
        Args:
            cached_handler: Mock handler with pre-loaded data
            fast_window: Fast SMA period
            slow_window: Slow SMA period
            iteration: Current iteration number
            total: Total number of iterations
            start_date: Optional override for backtest start date
            end_date: Optional override for backtest end date
            phase: Optional phase label (e.g., "IS", "OOS") for logging
        
        Returns:
            Dictionary with params and metrics
        """
        # Use override dates if provided, otherwise use instance defaults
        bt_start = start_date or self.start_date
        bt_end = end_date or self.end_date
        
        # Create strategy config with current parameters
        strategy_config = StrategyConfig(
            name="sma_cross",
            symbol=self.symbol,
            timeframe=self.timeframe,
            params={
                "fast_window": fast_window,
                "slow_window": slow_window,
            }
        )
        
        # Instantiate strategy
        strategy = SmaCrossStrategy(config=strategy_config)
        
        # Create backtester with cached data handler
        backtester = Backtester(
            data_handler=cached_handler,
            strategy=strategy,
            symbol=self.symbol,
            timeframe=self.timeframe,
            initial_capital=self.initial_capital,
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
        print(f"  {phase_str}[{iteration:3d}/{total}] Fast={fast_window:2d}, Slow={slow_window:2d} "
              f"→ Sharpe: {sharpe_str:>7}, Return: {result_metrics['total_return']*100:>6.2f}%")
        
        return {
            'params': {
                'fast_window': fast_window,
                'slow_window': slow_window,
            },
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
  %(prog)s --fast 5,10,15,20 --slow 30,40,50,60
  
  # Walk-forward optimization with Out-of-Sample validation
  %(prog)s --start-date 2023-01-01 --end-date 2023-12-31 --split-date 2023-10-01
  %(prog)s --start-date 2023-01-01 --end-date 2024-01-01 --split-date 2023-07-01 --top-n 10
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
        default='1h',
        help='Candle timeframe (default: 1h)'
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
        default='5,10,15,20,25',
        help='Fast window range as comma-separated values (default: 5,10,15,20,25)'
    )
    
    parser.add_argument(
        '--slow',
        type=str,
        default='20,30,40,50,60,80',
        help='Slow window range as comma-separated values (default: 20,30,40,50,60,80)'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output file path (default: results/optimization_TIMESTAMP.json)'
    )
    
    args = parser.parse_args()
    
    try:
        # Parse parameter ranges
        fast_range = [int(x.strip()) for x in args.fast.split(',')]
        slow_range = [int(x.strip()) for x in args.slow.split(',')]
        
        # Create optimizer
        optimizer = StrategyOptimizer(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            split_date=args.split_date,
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
            )
        else:
            # Standard optimization (no validation)
            results = optimizer.optimize(
                fast_window_range=fast_range,
                slow_window_range=slow_range,
            )
        
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

