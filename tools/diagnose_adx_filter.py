#!/usr/bin/env python3
"""
ADX Filter Diagnostic Tool

This tool isolates and diagnoses issues with the ADXVolatilityFilter by:
1. Loading data from a known strong trend period
2. Calculating ADX/DMI indicators
3. Classifying market regime
4. Displaying detailed diagnostic output

Usage:
    poetry run python tools/diagnose_adx_filter.py
    poetry run python tools/diagnose_adx_filter.py --start-date 2021-01-01 --end-date 2022-01-01
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import ccxt

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data.handler import CryptoDataHandler
from app.strategies.regime_filters import ADXVolatilityFilter
from app.config.models import RegimeFilterConfig
from app.core.enums import MarketState


def load_market_data(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    start_date: str = "2021-01-01",
    end_date: str = "2022-01-01",
) -> pd.DataFrame:
    """
    Load market data for a known strong trend period.
    
    Args:
        symbol: Trading pair (default: BTC/USDT)
        timeframe: Candle timeframe (default: 1h)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    
    Returns:
        DataFrame with OHLCV data
    """
    print("=" * 80)
    print("LOADING MARKET DATA")
    print("=" * 80)
    print(f"Symbol:     {symbol}")
    print(f"Timeframe:  {timeframe}")
    print(f"Period:     {start_date} to {end_date}")
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
        
        # Convert dates to datetime
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        
        # Fetch data
        print("Fetching data from exchange...")
        df = handler.get_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_ts,
            end_date=end_ts,
            limit=10000,
        )
        
        if df.empty:
            raise ValueError("No data received from exchange")
        
        print(f"✓ Loaded {len(df)} candles successfully")
        print(f"  Date range: {df.index.min()} to {df.index.max()}")
        print()
        
        return df
    
    except Exception as e:
        print(f"✗ Error loading data: {e}")
        raise


def diagnose_filter(
    data: pd.DataFrame,
    adx_window: int = 14,
    adx_threshold: int = 25,
) -> pd.DataFrame:
    """
    Diagnose ADX filter by calculating indicators and regime classification.
    
    Args:
        data: DataFrame with OHLCV data
        adx_window: ADX calculation window (default: 14)
        adx_threshold: ADX threshold for trend classification (default: 25)
    
    Returns:
        DataFrame with ADX, +DI, -DI, and REGIME columns
    """
    print("=" * 80)
    print("DIAGNOSING ADX FILTER")
    print("=" * 80)
    print(f"ADX Window:    {adx_window}")
    print(f"ADX Threshold: {adx_threshold}")
    print()
    
    # Create filter configuration
    filter_config = RegimeFilterConfig(
        adx_window=adx_window,
        adx_threshold=adx_threshold
    )
    
    # Instantiate filter
    filter_instance = ADXVolatilityFilter(config=filter_config)
    
    # Calculate ADX/DMI indicators (internal method)
    print("Calculating ADX/DMI indicators...")
    df_with_indicators = filter_instance._calculate_adx_dmi(data.copy())
    
    # Get regime classification
    print("Classifying market regime...")
    regime_series = filter_instance.get_regime(data.copy())
    
    # Combine into diagnostic DataFrame
    diagnostic_df = pd.DataFrame({
        'timestamp': df_with_indicators.index,
        'close': df_with_indicators['close'],
        'ADX': df_with_indicators['ADX'],
        '+DI': df_with_indicators['+DI'],
        '-DI': df_with_indicators['-DI'],
        'REGIME': regime_series.values,
    })
    
    diagnostic_df.set_index('timestamp', inplace=True)
    
    print(f"✓ Calculated indicators for {len(diagnostic_df)} candles")
    print()
    
    return diagnostic_df


def print_diagnostic_table(df: pd.DataFrame, title: str, num_rows: int = 50):
    """
    Print a formatted diagnostic table.
    
    Args:
        df: DataFrame with diagnostic data
        title: Table title
        num_rows: Number of rows to display
    """
    print("=" * 80)
    print(title)
    print("=" * 80)
    
    # Select columns to display
    display_cols = ['close', 'ADX', '+DI', '-DI', 'REGIME']
    display_df = df[display_cols].copy()
    
    # Format numeric columns
    display_df['close'] = display_df['close'].apply(lambda x: f"{x:,.2f}")
    display_df['ADX'] = display_df['ADX'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "NaN")
    display_df['+DI'] = display_df['+DI'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "NaN")
    display_df['-DI'] = display_df['-DI'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "NaN")
    
    # Convert REGIME to string for display
    display_df['REGIME'] = display_df['REGIME'].astype(str)
    
    # Print table
    pd.set_option('display.max_rows', num_rows)
    pd.set_option('display.width', 120)
    pd.set_option('display.max_columns', None)
    
    print(display_df.to_string())
    print()


def analyze_adx_values(df: pd.DataFrame, threshold: int = 25):
    """
    Analyze ADX values and print diagnostic metrics.
    
    Args:
        df: DataFrame with ADX column
        threshold: ADX threshold value
    """
    print("=" * 80)
    print("ADX VALUE ANALYSIS")
    print("=" * 80)
    
    # Calculate statistics
    adx_values = df['ADX'].replace(0, np.nan)  # Replace 0 with NaN for warm-up period
    
    max_adx = adx_values.max()
    min_adx = adx_values.min()
    mean_adx = adx_values.mean()
    median_adx = adx_values.median()
    
    # Count regimes
    regime_counts = df['REGIME'].value_counts()
    
    # Count periods where ADX > threshold
    adx_above_threshold = (adx_values > threshold).sum()
    total_valid = adx_values.notna().sum()
    pct_above_threshold = (adx_above_threshold / total_valid * 100) if total_valid > 0 else 0
    
    print(f"Maximum ADX Value:        {max_adx:.2f}")
    print(f"Minimum ADX Value:        {min_adx:.2f}")
    print(f"Mean ADX Value:           {mean_adx:.2f}")
    print(f"Median ADX Value:         {median_adx:.2f}")
    print()
    print(f"ADX Threshold:           {threshold}")
    print(f"Periods with ADX > {threshold}: {adx_above_threshold} / {total_valid} ({pct_above_threshold:.1f}%)")
    print()
    print("Regime Distribution:")
    for regime, count in regime_counts.items():
        pct = (count / len(df)) * 100
        print(f"  {regime}: {count} periods ({pct:.1f}%)")
    print()
    
    # Failure check
    if max_adx < threshold:
        print("=" * 80)
        print("⚠️  WARNING: ADX CALCULATION FAILURE DETECTED")
        print("=" * 80)
        print(f"Maximum ADX value ({max_adx:.2f}) is less than threshold ({threshold})")
        print("This indicates a problem with the ADX calculation algorithm.")
        print("The filter will never classify the market as TRENDING_UP or TRENDING_DOWN.")
        print()
    else:
        print("=" * 80)
        print("✓ ADX CALCULATION APPEARS CORRECT")
        print("=" * 80)
        print(f"Maximum ADX value ({max_adx:.2f}) exceeds threshold ({threshold})")
        print("ADX calculation is working correctly.")
        print()
        
        # Check if regimes are being classified
        if regime_counts.get(MarketState.TRENDING_UP, 0) == 0 and regime_counts.get(MarketState.TRENDING_DOWN, 0) == 0:
            print("⚠️  WARNING: NO TRENDING REGIMES DETECTED")
            print("=" * 80)
            print("ADX values are correct, but no periods classified as TRENDING_UP or TRENDING_DOWN.")
            print("This suggests an issue with the regime classification logic (DI comparison).")
            print()
        else:
            print("✓ REGIME CLASSIFICATION WORKING")
            print("=" * 80)
            print("Filter is correctly classifying trending periods.")
            print()


def main() -> int:
    """
    Main entry point for ADX filter diagnostic tool.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description='Diagnose ADX filter by analyzing indicator calculations and regime classification',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: Diagnose BTC/USDT 1h data from 2021-01-01 to 2022-01-01
  %(prog)s
  
  # Custom date range
  %(prog)s --start-date 2020-01-01 --end-date 2021-01-01
  
  # Custom ADX parameters
  %(prog)s --adx-window 20 --adx-threshold 30
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
        default='2021-01-01',
        help='Start date YYYY-MM-DD (default: 2021-01-01)'
    )
    
    parser.add_argument(
        '--end-date',
        type=str,
        default='2022-01-01',
        help='End date YYYY-MM-DD (default: 2022-01-01)'
    )
    
    parser.add_argument(
        '--adx-window',
        type=int,
        default=14,
        help='ADX calculation window (default: 14)'
    )
    
    parser.add_argument(
        '--adx-threshold',
        type=int,
        default=25,
        help='ADX threshold for trend classification (default: 25)'
    )
    
    args = parser.parse_args()
    
    try:
        # Step 1: Load market data
        data = load_market_data(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        
        # Step 2: Diagnose filter
        diagnostic_df = diagnose_filter(
            data=data,
            adx_window=args.adx_window,
            adx_threshold=args.adx_threshold,
        )
        
        # Step 3: Print diagnostic tables
        print_diagnostic_table(
            df=diagnostic_df.head(50),
            title="FIRST 50 ROWS (After Warm-up Period)",
            num_rows=50
        )
        
        print_diagnostic_table(
            df=diagnostic_df.tail(50),
            title="LAST 50 ROWS",
            num_rows=50
        )
        
        # Step 4: Analyze ADX values
        analyze_adx_values(diagnostic_df, threshold=args.adx_threshold)
        
        print("=" * 80)
        print("DIAGNOSTIC COMPLETE")
        print("=" * 80)
        print()
        print("Review the output above to identify issues with:")
        print("  1. ADX calculation (check if max ADX < threshold)")
        print("  2. Regime classification (check if no TRENDING periods)")
        print("  3. DI comparison logic (check if ADX > threshold but still RANGING)")
        print()
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠ Diagnostic interrupted by user")
        return 130
        
    except Exception as e:
        print(f"\n✗ Diagnostic failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

