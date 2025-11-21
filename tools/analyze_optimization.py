#!/usr/bin/env python3
"""
Multi-Objective Robustness Analyzer for Walk-Forward Optimization Results

This script processes 4D Walk-Forward Validation (WFO) output and selects the most
robust parameters based on the stability of Out-of-Sample (OOS) performance.

The Robustness Factor (FR) is calculated as:
    FR = Sharpe_OOS × (Sharpe_OOS / Sharpe_IS)

This metric penalizes configurations with high In-Sample performance that fail to
generalize to unseen data, while rewarding configurations with consistent OOS performance.

Usage:
    python tools/analyze_optimization.py --input-file results/optimization_20251121_125455.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


def load_optimization_results(filepath: str) -> Dict[str, Any]:
    """
    Load and parse a Walk-Forward Optimization results JSON file.
    
    Args:
        filepath: Path to the optimization results JSON file
        
    Returns:
        Dictionary containing optimization results with metadata and results array
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
        ValueError: If required fields are missing
    """
    file_path = Path(filepath)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Optimization results file not found: {filepath}")
    
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {filepath}")
    
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    # Validate required fields
    required_fields = ['metadata', 'results']
    missing_fields = [field for field in required_fields if field not in data]
    
    if missing_fields:
        raise ValueError(f"Missing required fields in JSON: {', '.join(missing_fields)}")
    
    # Validate that results is a list
    if not isinstance(data['results'], list):
        raise ValueError("'results' field must be a list")
    
    # Validate that each result has required fields
    for i, result in enumerate(data['results']):
        if 'params' not in result:
            raise ValueError(f"Result {i} missing 'params' field")
        if 'IS_metrics' not in result:
            raise ValueError(f"Result {i} missing 'IS_metrics' field")
        if 'OOS_metrics' not in result:
            raise ValueError(f"Result {i} missing 'OOS_metrics' field")
        
        # Validate metrics have sharpe_ratio
        if 'sharpe_ratio' not in result['IS_metrics']:
            raise ValueError(f"Result {i} IS_metrics missing 'sharpe_ratio'")
        if 'sharpe_ratio' not in result['OOS_metrics']:
            raise ValueError(f"Result {i} OOS_metrics missing 'sharpe_ratio'")
    
    return data


def calculate_robustness_factor(sharpe_is: float, sharpe_oos: float) -> float:
    """
    Calculate the Robustness Factor (FR) for a parameter configuration.
    
    Formula:
        FR = Sharpe_OOS × (Sharpe_OOS / Sharpe_IS)
    
    This metric:
    - Rewards high OOS Sharpe ratios
    - Penalizes configurations where OOS performance degrades significantly from IS
    - A high FR indicates both good OOS performance AND stability (low degradation)
    
    Special handling:
    - If OOS Sharpe <= 0, FR = 0 (negative OOS performance is unacceptable)
    - If IS Sharpe <= 0.01, FR = 0 (prevents division by zero and penalizes negative IS)
    
    Args:
        sharpe_is: In-Sample Sharpe ratio
        sharpe_oos: Out-of-Sample Sharpe ratio
        
    Returns:
        Robustness Factor (FR). Returns 0.0 for negative OOS or invalid IS Sharpe.
    """
    # Reject negative OOS performance - these configurations are not robust
    if sharpe_oos <= 0:
        return 0.0
    
    # Handle division by zero or near-zero IS Sharpe
    # If IS Sharpe is <= 0 or very small (< 0.01), set FR to 0
    # This prevents division by zero and penalizes negative IS performance
    if sharpe_is <= 0.01:
        return 0.0
    
    # Calculate degradation ratio
    degradation_ratio = sharpe_oos / sharpe_is
    
    # Calculate Robustness Factor
    # Since we've already ensured sharpe_oos > 0, this will be positive
    robustness_factor = sharpe_oos * degradation_ratio
    
    return robustness_factor


def calculate_degradation_ratio(sharpe_is: float, sharpe_oos: float) -> float:
    """
    Calculate the degradation ratio (OOS/IS).
    
    Args:
        sharpe_is: In-Sample Sharpe ratio
        sharpe_oos: Out-of-Sample Sharpe ratio
        
    Returns:
        Degradation ratio. Returns 0.0 if IS Sharpe is zero or negative.
    """
    if sharpe_is <= 0:
        return 0.0
    
    return sharpe_oos / sharpe_is


def analyze_results(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Analyze optimization results and calculate robustness factors.
    
    Args:
        data: Dictionary containing optimization results
        
    Returns:
        List of analyzed results, sorted by Robustness Factor (descending)
    """
    analyzed_results = []
    
    for result in data['results']:
        params = result['params']
        is_metrics = result['IS_metrics']
        oos_metrics = result['OOS_metrics']
        
        sharpe_is = is_metrics['sharpe_ratio']
        sharpe_oos = oos_metrics['sharpe_ratio']
        
        # Calculate metrics
        robustness_factor = calculate_robustness_factor(sharpe_is, sharpe_oos)
        degradation_ratio = calculate_degradation_ratio(sharpe_is, sharpe_oos)
        
        analyzed_result = {
            'params': params,
            'sharpe_is': sharpe_is,
            'sharpe_oos': sharpe_oos,
            'degradation_ratio': degradation_ratio,
            'robustness_factor': robustness_factor,
            'is_return': is_metrics.get('total_return', 0.0),
            'oos_return': oos_metrics.get('total_return', 0.0),
            'is_drawdown': is_metrics.get('max_drawdown', 0.0),
            'oos_drawdown': oos_metrics.get('max_drawdown', 0.0),
        }
        
        analyzed_results.append(analyzed_result)
    
    # Sort by Robustness Factor (descending)
    analyzed_results.sort(key=lambda x: x['robustness_factor'], reverse=True)
    
    return analyzed_results


def format_params_string(params: Dict[str, Any]) -> str:
    """
    Format parameters dictionary into a readable string.
    
    Args:
        params: Dictionary of parameter names and values
        
    Returns:
        Formatted string (e.g., "Fast=10, Slow=100, ATR_W=14, ATR_M=2.0")
    """
    # Map parameter names to display names
    param_display = {
        'fast_window': 'Fast',
        'slow_window': 'Slow',
        'atr_window': 'ATR_W',
        'atr_multiplier': 'ATR_M',
    }
    
    parts = []
    for key, value in params.items():
        display_name = param_display.get(key, key.replace('_', ' ').title())
        if isinstance(value, float):
            parts.append(f"{display_name}={value:.1f}")
        else:
            parts.append(f"{display_name}={value}")
    
    return ", ".join(parts)


def format_top_results_table(analyzed_results: List[Dict[str, Any]], top_n: int = 5) -> str:
    """
    Format the top N results into a nicely aligned console table.
    
    Args:
        analyzed_results: List of analyzed results (already sorted by FR)
        top_n: Number of top results to display
        
    Returns:
        Formatted string table
    """
    lines = []
    lines.append("=" * 100)
    lines.append("TOP ROBUST PARAMETER CONFIGURATIONS".center(100))
    lines.append("=" * 100)
    lines.append("")
    
    # Table header
    header = (
        f"{'Rank':<6} "
        f"{'Parameters':<40} "
        f"{'Sharpe_IS':>10} "
        f"{'Sharpe_OOS':>12} "
        f"{'Degradation':>12} "
        f"{'Robustness (FR)':>16}"
    )
    lines.append(header)
    lines.append("-" * 100)
    
    # Display top N results
    for i, result in enumerate(analyzed_results[:top_n], 1):
        params_str = format_params_string(result['params'])
        # Truncate params if too long
        if len(params_str) > 38:
            params_str = params_str[:35] + "..."
        
        line = (
            f"{i:<6} "
            f"{params_str:<40} "
            f"{result['sharpe_is']:>10.3f} "
            f"{result['sharpe_oos']:>12.3f} "
            f"{result['degradation_ratio']:>12.3f} "
            f"{result['robustness_factor']:>16.3f}"
        )
        lines.append(line)
    
    lines.append("=" * 100)
    
    return "\n".join(lines)


def format_recommendation(result: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    """
    Format the final recommendation for config.json.
    
    Args:
        result: The top-ranked result (highest FR)
        metadata: Metadata from the optimization results
        
    Returns:
        Formatted recommendation string
    """
    lines = []
    lines.append("")
    lines.append("=" * 100)
    lines.append("RECOMMENDED PARAMETERS FOR config.json".center(100))
    lines.append("=" * 100)
    lines.append("")
    
    # Display parameters in JSON-like format
    lines.append("Strategy Configuration:")
    lines.append("")
    
    params = result['params']
    
    # Format for config.json (assuming VolatilityAdjustedStrategy)
    if 'atr_window' in params and 'atr_multiplier' in params:
        lines.append("  {")
        lines.append(f'    "name": "VolatilityAdjustedStrategy",')
        lines.append(f'    "symbol": "{metadata.get("symbol", "BTC/USDT")}",')
        lines.append(f'    "timeframe": "{metadata.get("timeframe", "1h")}",')
        lines.append('    "params": {')
        lines.append(f'      "fast_window": {params["fast_window"]},')
        lines.append(f'      "slow_window": {params["slow_window"]},')
        lines.append(f'      "atr_window": {params["atr_window"]},')
        lines.append(f'      "atr_multiplier": {params["atr_multiplier"]}')
        lines.append("    }")
        lines.append("  }")
    else:
        # Fallback for 2D optimization (SMA Cross)
        lines.append("  {")
        lines.append(f'    "name": "SmaCrossStrategy",')
        lines.append(f'    "symbol": "{metadata.get("symbol", "BTC/USDT")}",')
        lines.append(f'    "timeframe": "{metadata.get("timeframe", "1h")}",')
        lines.append('    "params": {')
        lines.append(f'      "fast_window": {params["fast_window"]},')
        lines.append(f'      "slow_window": {params["slow_window"]}')
        lines.append("    }")
        lines.append("  }")
    
    lines.append("")
    lines.append("Performance Metrics:")
    lines.append("")
    lines.append(f"  In-Sample Sharpe Ratio:    {result['sharpe_is']:>8.3f}")
    lines.append(f"  Out-of-Sample Sharpe Ratio: {result['sharpe_oos']:>8.3f}")
    lines.append(f"  Degradation Ratio:          {result['degradation_ratio']:>8.3f}")
    lines.append(f"  Robustness Factor (FR):     {result['robustness_factor']:>8.3f}")
    lines.append("")
    lines.append(f"  In-Sample Return:           {result['is_return']*100:>7.2f}%")
    lines.append(f"  Out-of-Sample Return:        {result['oos_return']*100:>7.2f}%")
    lines.append(f"  In-Sample Max Drawdown:      {result['is_drawdown']*100:>7.2f}%")
    lines.append(f"  Out-of-Sample Max Drawdown:  {result['oos_drawdown']*100:>7.2f}%")
    lines.append("")
    lines.append("=" * 100)
    
    return "\n".join(lines)


def main() -> int:
    """
    Main entry point for the optimization analyzer script.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description='Analyze Walk-Forward Optimization results and select robust parameters',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --input-file results/optimization_20251121_125455.json
  %(prog)s --input-file results/optimization_20251121_125455.json --top-n 10
        """
    )
    
    parser.add_argument(
        '--input-file',
        type=str,
        required=True,
        help='Path to the Walk-Forward Optimization results JSON file'
    )
    
    parser.add_argument(
        '--top-n',
        type=int,
        default=5,
        help='Number of top results to display (default: 5)'
    )
    
    args = parser.parse_args()
    
    try:
        # Load optimization results
        print(f"Loading optimization results from: {args.input_file}")
        data = load_optimization_results(args.input_file)
        
        metadata = data['metadata']
        num_results = len(data['results'])
        
        print(f"✓ Loaded {num_results} parameter configurations")
        print(f"  Symbol: {metadata.get('symbol', 'N/A')}")
        print(f"  Timeframe: {metadata.get('timeframe', 'N/A')}")
        if 'split_date' in metadata:
            print(f"  In-Sample Period: {metadata.get('in_sample_period', 'N/A')}")
            print(f"  Out-of-Sample Period: {metadata.get('out_of_sample_period', 'N/A')}")
        print("")
        
        # Analyze results
        print("Calculating Robustness Factors...")
        analyzed_results = analyze_results(data)
        print(f"✓ Analyzed {len(analyzed_results)} configurations")
        print("")
        
        # Display top results table
        print(format_top_results_table(analyzed_results, top_n=args.top_n))
        
        # Display recommendation
        if analyzed_results:
            best_result = analyzed_results[0]
            print(format_recommendation(best_result, metadata))
        else:
            print("\n⚠ Warning: No valid results to analyze.")
            return 1
        
        print(f"\n✓ Analysis complete!")
        print(f"  - Top {min(args.top_n, len(analyzed_results))} configurations displayed above")
        print(f"  - Recommended parameters shown in the final section")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(f"\nPlease check that the file path is correct.", file=sys.stderr)
        return 1
        
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format in file", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1
        
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

