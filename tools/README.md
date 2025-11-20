# Trading Bot Tools

This directory contains utility scripts and tools for analyzing and managing the trading bot.

## Available Tools

### 1. Backtest Results Analyzer (`analyze_backtest.py`)

A comprehensive visualization and analysis tool for backtest results.

#### Features

- **Console Metrics Summary**: Displays key performance metrics in a formatted table
- **Equity Curve Visualization**: Line chart showing portfolio value over time with profit/loss areas
- **Drawdown Analysis**: Area chart showing percentage decline from peak equity
- **Professional Export**: High-resolution PNG output suitable for reports

#### Requirements

The script uses the following dependencies (automatically installed via Poetry):
- `pandas` - Data manipulation and analysis
- `matplotlib` - Charting and visualization
- `numpy` - Numerical operations

#### Usage

```bash
# Basic usage (saves to analysis_report.png)
poetry run python tools/analyze_backtest.py results/backtest_sma_cross_20251120_195448.json

# Specify custom output path
poetry run python tools/analyze_backtest.py results/my_backtest.json -o my_analysis.png

# View help
poetry run python tools/analyze_backtest.py --help
```

#### Input Format

The script expects a JSON file with the following structure:

```json
{
  "metadata": {
    "timestamp": "20251120_195448",
    "start_date": "2023-01-01",
    "end_date": "2023-12-31"
  },
  "metrics": {
    "total_return": -0.10951404881076676,
    "sharpe_ratio": -1.3736788920465597,
    "max_drawdown": -0.12145854454617433
  },
  "params": {
    "fast_window": 10,
    "slow_window": 30
  },
  "equity_curve": [1.0, 0.998, ...]
}
```

#### Output

**Console Output:**
```
============================================================
                BACKTEST PERFORMANCE METRICS                
============================================================

  Total Return                       -10.95%
  Sharpe Ratio                       -1.374
  Max Drawdown                       -12.15%

------------------------------------------------------------
                    STRATEGY PARAMETERS                     
------------------------------------------------------------

  Fast Window                            10
  Slow Window                            30

============================================================
```

**Visual Output:**
- PNG image with two subplots:
  - **Top**: Equity curve with initial capital reference line
  - **Bottom**: Drawdown chart with maximum drawdown highlighted
- High resolution (300 DPI) suitable for presentations and reports

#### Error Handling

The script gracefully handles:
- Missing files (FileNotFoundError)
- Invalid JSON format (JSONDecodeError)
- Missing required fields (ValueError)

All errors are reported with clear messages and appropriate exit codes.

#### Examples

```bash
# Analyze a single backtest result
poetry run python tools/analyze_backtest.py results/backtest_sma_cross_20251120_195448.json

# Save to custom location
poetry run python tools/analyze_backtest.py results/backtest_sma_cross_20251120_195448.json -o reports/q4_analysis.png

# Process latest backtest result
poetry run python tools/analyze_backtest.py $(ls -t results/backtest_*.json | head -1)
```

## Adding New Tools

When adding new tools to this directory:

1. Follow the same code style and documentation standards
2. Add type hints and docstrings
3. Include proper error handling
4. Add usage instructions to this README
5. Update dependencies in `pyproject.toml` if needed

## Development

All tools should be:
- Python 3.11+ compatible
- Properly typed with mypy
- Tested with pytest
- Documented with clear docstrings
- CLI-friendly with argparse

