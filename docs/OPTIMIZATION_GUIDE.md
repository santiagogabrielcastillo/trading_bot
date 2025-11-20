# Strategy Parameter Optimization Guide

This guide explains how to use the parameter optimization infrastructure to find optimal trading strategy parameters through systematic grid search.

## Overview

The optimization system implements the **"Load Once, Compute Many"** pattern for maximum efficiency:

1. **Load Once:** Fetch historical data from the exchange EXACTLY ONCE
2. **Cache in Memory:** Store the data in a pandas DataFrame
3. **Mock the Handler:** Create a cached data handler that serves pre-loaded data
4. **Compute Many:** Run hundreds of backtests using the cached data (no API calls)
5. **Analyze Results:** Identify robust parameter combinations

## Quick Start

### Basic Usage

```bash
# Run optimization with default settings (BTC/USDT, 1h, 2023 data)
poetry run python tools/optimize_strategy.py

# Specify date range
poetry run python tools/optimize_strategy.py --start-date 2023-01-01 --end-date 2023-12-31

# Optimize different asset and timeframe
poetry run python tools/optimize_strategy.py --symbol ETH/USDT --timeframe 4h

# Custom parameter ranges
poetry run python tools/optimize_strategy.py --fast 5,10,15,20 --slow 30,40,50,60
```

### View All Options

```bash
poetry run python tools/optimize_strategy.py --help
```

## Architecture

### The "Load Once, Compute Many" Pattern

**Problem:** Running 30+ backtests that each fetch data independently wastes time and API rate limits.

**Solution:** Load data once, mock the data handler for all subsequent iterations.

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: LOAD ONCE (API Call)                               │
│ ┌───────────────┐         ┌──────────────────────┐         │
│ │ CryptoData    │ Fetch   │ Pandas DataFrame     │         │
│ │ Handler       │────────>│ (8760 rows × 5 cols) │         │
│ └───────────────┘         └──────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: COMPUTE MANY (In-Memory Operations)                │
│                                                             │
│ ┌────────────────────┐                                     │
│ │ CachedDataHandler  │ (Mocks IDataHandler)                │
│ │ (Returns cached DF)│                                     │
│ └────────────────────┘                                     │
│          │                                                  │
│          ▼                                                  │
│ ┌──────────────────────────────────────────────────┐       │
│ │ Iteration 1: fast=5,  slow=20 → Sharpe: 0.85    │       │
│ │ Iteration 2: fast=5,  slow=30 → Sharpe: 1.12    │       │
│ │ Iteration 3: fast=5,  slow=40 → Sharpe: 1.05    │       │
│ │ ...                                              │       │
│ │ Iteration 30: fast=25, slow=80 → Sharpe: 0.92   │       │
│ └──────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. `CachedDataHandler` (Mock)

```python
class CachedDataHandler(IDataHandler):
    """
    Mock data handler that serves pre-loaded data from memory.
    Implements IDataHandler interface without making API calls.
    """
    
    def get_historical_data(self, ...) -> pd.DataFrame:
        # Returns cached data (no API call)
        return self.cached_data.copy()
```

**Why This Matters:**
- Backtester calls `data_handler.get_historical_data()` for each run
- Without mocking: 30 iterations × 2 seconds = 60 seconds + rate limit issues
- With mocking: 30 iterations × 0.1 seconds = 3 seconds (20x faster!)

#### 2. `StrategyOptimizer` (Orchestrator)

Manages the optimization workflow:
1. `load_data_once()` - Fetches data from exchange
2. `optimize()` - Runs grid search with mocked handler
3. `save_results()` - Exports sorted results to JSON

## Configuration

### Default Parameter Ranges

```python
# Fast SMA windows (short-term trend)
fast_window_range = [5, 10, 15, 20, 25]

# Slow SMA windows (long-term trend)
slow_window_range = [20, 30, 40, 50, 60, 80]
```

### Validation Rules

- **Constraint:** `fast_window < slow_window` (enforced automatically)
- **Valid Combinations:** 30 out of 30 possible (5 × 6)
- **Invalid Examples:** (20, 20), (25, 20) - skipped automatically

### Customizing Ranges

```bash
# Test aggressive parameters (faster signals)
poetry run python tools/optimize_strategy.py --fast 3,5,8 --slow 15,20,25

# Test conservative parameters (slower signals)
poetry run python tools/optimize_strategy.py --fast 20,30,40 --slow 60,80,100

# Fine-grained search around known good values
poetry run python tools/optimize_strategy.py --fast 8,9,10,11,12 --slow 48,49,50,51,52
```

## Output Format

### JSON Structure

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
      "params": {
        "fast_window": 10,
        "slow_window": 50
      },
      "metrics": {
        "total_return": 0.1495,
        "sharpe_ratio": 1.4235,
        "max_drawdown": -0.0815
      }
    },
    {
      "params": {
        "fast_window": 15,
        "slow_window": 50
      },
      "metrics": {
        "total_return": 0.1380,
        "sharpe_ratio": 1.3891,
        "max_drawdown": -0.0902
      }
    }
  ]
}
```

**Note:** Results are automatically sorted by Sharpe ratio (descending).

## Console Output Example

```
======================================================================
LOADING HISTORICAL DATA (One-Time Operation)
======================================================================
Symbol:     BTC/USDT
Timeframe:  1h
Date Range: 2023-01-01 to 2023-12-31

Fetching data from 2022-10-22 (with buffer for indicators)...
✓ Loaded 8760 candles successfully
  Date range: 2022-10-22 to 2023-12-31
  Memory size: 0.68 MB

======================================================================
STARTING GRID SEARCH OPTIMIZATION
======================================================================
Parameter Space:
  Fast Window: [5, 10, 15, 20, 25]
  Slow Window: [20, 30, 40, 50, 60, 80]
  Total Combinations: 30
  Valid Combinations: 30 (fast < slow)

  [  1/30] Fast= 5, Slow=20 → Sharpe:  0.852, Return:  10.25%
  [  2/30] Fast= 5, Slow=30 → Sharpe:  1.123, Return:  12.45%
  [  3/30] Fast= 5, Slow=40 → Sharpe:  1.054, Return:  11.80%
  ...
  [ 30/30] Fast=25, Slow=80 → Sharpe:  0.921, Return:   9.15%

======================================================================
OPTIMIZATION COMPLETE
======================================================================
Total successful runs: 30/30

Best Parameters:
  Fast Window: 10
  Slow Window: 50
  Sharpe Ratio: 1.4235
  Total Return: 14.95%
  Max Drawdown: -8.15%

✓ Results saved to: results/optimization_20251120_143000.json
  File size: 2.45 KB

✓ Optimization complete!
  Next step: Analyze results in results/optimization_20251120_143000.json
```

## Performance Benchmarks

### Optimization Speed Comparison

| Method | Data Loading | Computation | Total Time | API Calls |
|--------|--------------|-------------|------------|-----------|
| **Without Caching** | 30 × 2s = 60s | 30 × 0.5s = 15s | **~75s** | 30+ |
| **With Caching** | 1 × 2s = 2s | 30 × 0.1s = 3s | **~5s** | 1 |
| **Speedup** | 30x | 5x | **15x** | 30x |

### Memory Usage

- Cached DataFrame: ~0.5-1 MB per 10,000 candles
- Peak memory: ~50 MB (includes strategy calculations)
- Minimal overhead for mocking layer

## Next Steps: Analysis

After optimization completes, analyze the results to find the "sweet spot":

### 1. Manual Analysis

Open the JSON file and look for:
- **Cluster patterns:** Groups of similar parameters performing well
- **Isolated peaks:** Single high-performers (likely overfit)
- **Robustness:** Neighbors of top performers also doing well

### 2. Automated Analysis (Future)

```bash
# TODO: Implement analysis tool
poetry run python tools/analyze_optimization.py results/optimization_20251120_143000.json
```

### 3. Use the Analysis Prompt

Follow the structured analysis guide in:
```
settings/optimization_analysis_prompt.md
```

This prompt provides:
- Robustness assessment methodology
- Overfitting detection criteria
- Production parameter selection framework
- Risk-adjusted ranking approach

## Best Practices

### ✅ DO

1. **Use sufficient historical data** (1+ years for robust results)
2. **Test on out-of-sample periods** after selecting parameters
3. **Prefer round numbers** (10, 20, 50) over specific values (17, 23)
4. **Check robustness** of top performers by testing neighboring values
5. **Consider market regimes** (bull/bear/sideways) in date range selection
6. **Re-optimize periodically** (quarterly or after major market changes)

### ❌ DON'T

1. **Don't use the best backtest result blindly** - check for overfitting
2. **Don't optimize on recent data only** - recency bias is real
3. **Don't ignore drawdown** in favor of high returns
4. **Don't trust isolated peaks** - they rarely generalize
5. **Don't optimize too frequently** - leads to curve-fitting
6. **Don't use insufficient data** (< 6 months) - results unreliable

## Extending the System

### Adding New Parameters

Edit `optimize_strategy.py`:

```python
# Add new parameter ranges
rsi_period_range = [7, 14, 21]
rsi_threshold_range = [30, 40, 50]

# Update combination generation
param_combinations = list(itertools.product(
    fast_window_range,
    slow_window_range,
    rsi_period_range,      # New
    rsi_threshold_range,   # New
))
```

### Supporting New Strategies

1. Create strategy class inheriting from `BaseStrategy`
2. Implement `calculate_indicators()` and `generate_signals()`
3. Update optimizer to instantiate your strategy class
4. Define appropriate parameter ranges for your strategy

## Troubleshooting

### "No data received from exchange"

**Cause:** API connection issue or invalid date range  
**Solution:** 
- Check internet connection
- Verify date range is reasonable (not future dates)
- Try reducing date range to test connectivity

### "Memory Error"

**Cause:** Dataset too large for available RAM  
**Solution:**
- Reduce date range
- Use longer timeframe (4h instead of 1h)
- Close other applications

### Slow Optimization

**Cause:** Complex strategy or insufficient CPU  
**Solution:**
- Reduce parameter grid density
- Use faster timeframe (1d instead of 1h)
- Run on machine with more cores

### Invalid Sharpe Ratios (NaN)

**Cause:** No trades generated or all returns identical  
**Solution:**
- Check parameter ranges aren't too extreme
- Verify strategy logic generates signals
- Ensure sufficient data for indicator warm-up

## References

- Main optimization script: `tools/optimize_strategy.py`
- Analysis guide: `settings/optimization_analysis_prompt.md`
- Strategy implementation: `app/strategies/sma_cross.py`
- Backtesting engine: `app/backtesting/engine.py`

