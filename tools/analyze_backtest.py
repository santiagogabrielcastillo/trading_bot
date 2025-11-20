#!/usr/bin/env python3
"""
Backtest Results Analyzer and Visualizer

This script reads backtest result JSON files and generates:
1. A formatted console summary of key metrics
2. A comprehensive visualization with equity curve and drawdown charts

Usage:
    python tools/analyze_backtest.py results/backtest_sma_cross_20251120_195448.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta


def load_backtest_results(filepath: str) -> Dict[str, Any]:
    """
    Load and parse a backtest results JSON file.
    
    Args:
        filepath: Path to the backtest results JSON file
        
    Returns:
        Dictionary containing backtest results
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    file_path = Path(filepath)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Backtest results file not found: {filepath}")
    
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {filepath}")
    
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    # Validate required fields
    required_fields = ['equity_curve', 'metrics']
    missing_fields = [field for field in required_fields if field not in data]
    
    if missing_fields:
        raise ValueError(f"Missing required fields in JSON: {', '.join(missing_fields)}")
    
    return data


def calculate_drawdown(equity_curve: List[float]) -> pd.Series:
    """
    Calculate drawdown percentage from equity curve.
    
    Args:
        equity_curve: List of portfolio values over time
        
    Returns:
        Pandas Series containing drawdown percentages (negative values)
    """
    equity_series = pd.Series(equity_curve)
    
    # Calculate running maximum
    running_max = equity_series.expanding().max()
    
    # Calculate drawdown as percentage from peak
    drawdown = (equity_series - running_max) / running_max
    
    return drawdown


def format_metrics_table(metrics: Dict[str, float], params: Optional[Dict[str, Any]] = None) -> str:
    """
    Format metrics into a nicely aligned console table.
    
    Args:
        metrics: Dictionary of metric names and values
        params: Optional strategy parameters to display
        
    Returns:
        Formatted string table
    """
    lines = []
    lines.append("=" * 60)
    lines.append("BACKTEST PERFORMANCE METRICS".center(60))
    lines.append("=" * 60)
    lines.append("")
    
    # Format metrics
    for key, value in metrics.items():
        # Format the key (convert snake_case to Title Case)
        display_key = key.replace('_', ' ').title()
        
        # Format the value based on metric type
        if isinstance(value, float):
            if 'return' in key.lower() or 'drawdown' in key.lower():
                formatted_value = f"{value * 100:>10.2f}%"
            elif 'ratio' in key.lower():
                formatted_value = f"{value:>10.3f}"
            else:
                formatted_value = f"{value:>10.4f}"
        else:
            formatted_value = f"{value:>10}"
        
        lines.append(f"  {display_key:<30} {formatted_value}")
    
    # Add strategy parameters if provided
    if params:
        lines.append("")
        lines.append("-" * 60)
        lines.append("STRATEGY PARAMETERS".center(60))
        lines.append("-" * 60)
        lines.append("")
        
        for key, value in params.items():
            display_key = key.replace('_', ' ').title()
            lines.append(f"  {display_key:<30} {value:>10}")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def create_visualization(
    equity_curve: List[float],
    metrics: Dict[str, float],
    metadata: Optional[Dict[str, str]] = None,
    output_path: str = "analysis_report.png"
) -> None:
    """
    Create and save a comprehensive visualization of backtest results.
    
    Args:
        equity_curve: List of portfolio values over time
        metrics: Dictionary of performance metrics
        metadata: Optional metadata (timestamp, date range, etc.)
        output_path: Path where to save the PNG image
    """
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle('Backtest Analysis Report', fontsize=16, fontweight='bold', y=0.995)
    
    # Generate time index
    if metadata and 'start_date' in metadata and 'end_date' in metadata:
        try:
            start_date = pd.to_datetime(metadata['start_date'])
            end_date = pd.to_datetime(metadata['end_date'])
            time_index = pd.date_range(start=start_date, end=end_date, periods=len(equity_curve))
        except:
            time_index = range(len(equity_curve))
    else:
        time_index = range(len(equity_curve))
    
    # Convert to pandas Series for easier plotting
    equity_series = pd.Series(equity_curve, index=time_index)
    
    # --- Subplot 1: Equity Curve ---
    ax1.plot(time_index, equity_curve, linewidth=2, color='#2E86AB', label='Portfolio Value')
    ax1.axhline(y=1.0, color='#A23B72', linestyle='--', linewidth=1.5, 
                label='Initial Capital', alpha=0.7)
    
    # Fill area under/over initial capital
    ax1.fill_between(time_index, equity_curve, 1.0, 
                     where=[val >= 1.0 for val in equity_curve],
                     color='#06A77D', alpha=0.2, label='Profit')
    ax1.fill_between(time_index, equity_curve, 1.0,
                     where=[val < 1.0 for val in equity_curve],
                     color='#D62246', alpha=0.2, label='Loss')
    
    ax1.set_xlabel('Time', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Portfolio Value (Normalized)', fontsize=11, fontweight='bold')
    ax1.set_title('Equity Curve', fontsize=13, fontweight='bold', pad=10)
    ax1.legend(loc='best', framealpha=0.9)
    ax1.grid(True, alpha=0.3, linestyle='--')
    
    # Format x-axis if using dates
    if isinstance(time_index, pd.DatetimeIndex):
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # --- Subplot 2: Drawdown ---
    drawdown = calculate_drawdown(equity_curve)
    drawdown_pct = drawdown * 100  # Convert to percentage
    
    ax2.fill_between(time_index, drawdown_pct, 0, 
                     color='#D62246', alpha=0.5, label='Drawdown')
    ax2.plot(time_index, drawdown_pct, color='#8B0000', linewidth=1.5)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8, alpha=0.5)
    
    # Highlight max drawdown
    max_dd_idx = drawdown.idxmin()
    max_dd_val = drawdown.min() * 100
    ax2.scatter([max_dd_idx], [max_dd_val], color='red', s=100, 
               zorder=5, label=f'Max Drawdown: {max_dd_val:.2f}%')
    
    ax2.set_xlabel('Time', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Drawdown (%)', fontsize=11, fontweight='bold')
    ax2.set_title('Drawdown Chart', fontsize=13, fontweight='bold', pad=10)
    ax2.legend(loc='lower left', framealpha=0.9)
    ax2.grid(True, alpha=0.3, linestyle='--')
    
    # Format x-axis if using dates
    if isinstance(time_index, pd.DatetimeIndex):
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # Add metrics text box
    metrics_text = f"Total Return: {metrics.get('total_return', 0) * 100:.2f}%\n"
    metrics_text += f"Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}\n"
    metrics_text += f"Max Drawdown: {metrics.get('max_drawdown', 0) * 100:.2f}%"
    
    fig.text(0.99, 0.01, metrics_text, 
            fontsize=9, ha='right', va='bottom',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Adjust layout to prevent overlap
    plt.tight_layout(rect=[0, 0.03, 1, 0.98])
    
    # Save the figure
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    
    print(f"\n✓ Visualization saved to: {output_path}")
    
    # Close the figure to free memory
    plt.close(fig)


def main() -> int:
    """
    Main entry point for the backtest analyzer script.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description='Analyze and visualize trading bot backtest results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s results/backtest_sma_cross_20251120_195448.json
  %(prog)s results/my_backtest.json --output my_analysis.png
        """
    )
    
    parser.add_argument(
        'filepath',
        type=str,
        help='Path to the backtest results JSON file'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='analysis_report.png',
        help='Output path for the visualization PNG (default: analysis_report.png)'
    )
    
    parser.add_argument(
        '--no-display',
        action='store_true',
        help='Skip displaying the plot (only save to file)'
    )
    
    args = parser.parse_args()
    
    try:
        # Load backtest results
        print(f"Loading backtest results from: {args.filepath}")
        results = load_backtest_results(args.filepath)
        
        # Extract data
        equity_curve = results['equity_curve']
        metrics = results['metrics']
        params = results.get('params', None)
        metadata = results.get('metadata', None)
        
        # Print metrics table to console
        print("\n" + format_metrics_table(metrics, params))
        
        # Create visualization
        print("\nGenerating visualization...")
        create_visualization(
            equity_curve=equity_curve,
            metrics=metrics,
            metadata=metadata,
            output_path=args.output
        )
        
        print(f"\n✓ Analysis complete!")
        print(f"  - Metrics displayed above")
        print(f"  - Chart saved to: {args.output}")
        
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

