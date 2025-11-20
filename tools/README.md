# Trading Bot Tools

This directory contains utility scripts and tools for analyzing and managing the trading bot.

## Available Tools

### 1. Strategy Parameter Optimizer (`optimize_strategy.py`)

A powerful grid search optimization tool for finding optimal strategy parameters.

#### Features

- **"Load Once, Compute Many"** architecture for maximum efficiency
- **Cached Data Handler**: Pre-loads data once, serves from memory for all iterations
- **Grid Search**: Exhaustive search over parameter combinations
- **Smart Filtering**: Automatically skips invalid parameter combinations
- **Real-time Progress**: Live updates on optimization progress
- **Sorted Results**: Automatically ranks by Sharpe ratio
- **Comprehensive Output**: JSON export with metadata and full results

#### Key Innovation: Zero API Overhead

Traditional approach:
```
30 backtests × 2 seconds per API call = 60 seconds + rate limit issues
```

Our approach:
```
1 API call (2 seconds) + 30 in-memory backtests (3 seconds) = 5 seconds total
15x faster! 🚀
```

#### Usage

```bash
# Basic usage (BTC/USDT, 1h, 2023 data)
poetry run python tools/optimize_strategy.py

# Custom date range
poetry run python tools/optimize_strategy.py --start-date 2023-01-01 --end-date 2023-12-31

# Different asset and timeframe
poetry run python tools/optimize_strategy.py --symbol ETH/USDT --timeframe 4h

# Custom parameter ranges
poetry run python tools/optimize_strategy.py --fast 5,10,15,20 --slow 30,40,50,60

# Save to custom location
poetry run python tools/optimize_strategy.py -o results/my_optimization.json

# View all options
poetry run python tools/optimize_strategy.py --help
```

#### Default Parameter Ranges

- **Fast Window**: [5, 10, 15, 20, 25]
- **Slow Window**: [20, 30, 40, 50, 60, 80]
- **Valid Combinations**: 30 (automatically filters fast >= slow)

#### Output Format

```json
{
  "metadata": {
    "timestamp": "2025-11-20T14:30:00",
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "total_combinations_tested": 30
  },
  "results": [
    {
      "params": {"fast_window": 10, "slow_window": 50},
      "metrics": {
        "total_return": 0.1495,
        "sharpe_ratio": 1.4235,
        "max_drawdown": -0.0815
      }
    }
  ]
}
```

Results are automatically sorted by Sharpe ratio (descending).

#### Next Steps After Optimization

1. **Analyze Results**: Use the quantitative analysis prompt in `settings/optimization_analysis_prompt.md`
2. **Check Robustness**: Verify top performers have strong neighboring parameters
3. **Validate Out-of-Sample**: Test on different time periods
4. **Deploy to Production**: Use robust parameters, not just highest backtest returns

#### Performance Benchmarks

- **Speed**: 15x faster than naive approach
- **Memory**: ~1 MB per 10,000 candles
- **API Calls**: 1 (vs 30+ without caching)

See `docs/OPTIMIZATION_GUIDE.md` for comprehensive documentation.

---

### 2. Backtest Results Analyzer (`analyze_backtest.py`)

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

