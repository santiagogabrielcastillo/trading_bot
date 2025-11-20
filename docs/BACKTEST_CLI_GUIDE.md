# Advanced Backtest CLI - User Guide

## Overview

The `run_backtest.py` script now supports advanced features for rapid strategy iteration:
- **Dynamic parameter overrides** via CLI (no need to edit config files)
- **Automatic result persistence** with timestamped JSON files
- **Beautiful mission reports** with performance metrics and parameters

---

## Basic Usage

### 1. Run with Default Config

```bash
python run_backtest.py --start 2024-01-01 --end 2024-06-01
```

This runs the backtest using parameters from `settings/config.json`:
- `fast_window: 10`
- `slow_window: 50`

---

## Advanced Usage: Parameter Overrides

### 2. Override Parameters with JSON

```bash
python run_backtest.py \
  --start 2024-01-01 \
  --end 2024-06-01 \
  --params '{"fast_window": 20, "slow_window": 60}'
```

### 3. Override Parameters with Key=Value Pairs (Comma-Separated)

```bash
python run_backtest.py \
  --start 2024-01-01 \
  --end 2024-06-01 \
  --params 'fast_window=20,slow_window=60'
```

### 4. Override Parameters with Key=Value Pairs (Space-Separated)

```bash
python run_backtest.py \
  --start 2024-01-01 \
  --end 2024-06-01 \
  --params 'fast_window=20 slow_window=60'
```

### 5. Partial Overrides (Only Change Some Parameters)

```bash
# Only change fast_window, keep slow_window from config
python run_backtest.py \
  --start 2024-01-01 \
  --end 2024-06-01 \
  --params 'fast_window=15'
```

---

## Output

### Console: Mission Report

After each run, you'll see a beautiful mission report:

```
======================================================================
                    🚀 BACKTEST MISSION REPORT                        
======================================================================

📅 Period: 2024-01-01 → 2024-06-01
📊 Strategy: sma_cross

----------------------------------------------------------------------
                       ⚙️  PARAMETERS USED                            
----------------------------------------------------------------------
  fast_window : 20
  slow_window : 60

----------------------------------------------------------------------
                      📈 PERFORMANCE METRICS                          
----------------------------------------------------------------------
  📈 Total Return      :      5.23%
  ⭐ Sharpe Ratio      :     1.4567
  🔻 Max Drawdown      :     -8.45%

----------------------------------------------------------------------
💾 Results saved to: results/backtest_sma_cross_20241120_142537.json
======================================================================
```

### Saved Results

Results are automatically saved to `results/backtest_{STRATEGY}_{TIMESTAMP}.json`:

```json
{
  "metadata": {
    "timestamp": "20241120_142537",
    "start_date": "2024-01-01",
    "end_date": "2024-06-01"
  },
  "metrics": {
    "total_return": 0.0523,
    "sharpe_ratio": 1.4567,
    "max_drawdown": -0.0845
  },
  "params": {
    "fast_window": 20,
    "slow_window": 60
  },
  "config": {
    "exchange": { ... },
    "strategy": { ... },
    "risk": { ... }
  },
  "equity_curve": [1.0, 1.01, 1.02, ...]
}
```

---

## Strategy Iteration Workflow

### Goal: Find optimal SMA windows for 2024 Q1

```bash
# Test 1: Default (10/50)
python run_backtest.py --start 2024-01-01 --end 2024-03-31

# Test 2: Faster cross (5/20)
python run_backtest.py --start 2024-01-01 --end 2024-03-31 \
  --params 'fast_window=5,slow_window=20'

# Test 3: Medium cross (15/40)
python run_backtest.py --start 2024-01-01 --end 2024-03-31 \
  --params 'fast_window=15,slow_window=40'

# Test 4: Slower cross (20/100)
python run_backtest.py --start 2024-01-01 --end 2024-03-31 \
  --params 'fast_window=20,slow_window=100'

# Test 5: Very slow cross (50/200)
python run_backtest.py --start 2024-01-01 --end 2024-03-31 \
  --params 'fast_window=50,slow_window=200'
```

All results are saved with unique timestamps in `results/`, making it easy to:
1. Compare performance across different parameters
2. Track which parameters were used for each backtest
3. Reproduce any backtest exactly
4. Build optimization scripts that parse the JSON files

---

## Tips & Best Practices

### 1. Use Cached Data for Speed

On the first run with a date range, data is downloaded and cached.
Subsequent runs with the same date range are **instant** because they use the cache!

```bash
# First run: Downloads data (~10 seconds)
python run_backtest.py --start 2024-01-01 --end 2024-06-01 \
  --params 'fast_window=10,slow_window=50'

# Second run: Uses cache (instant!)
python run_backtest.py --start 2024-01-01 --end 2024-06-01 \
  --params 'fast_window=15,slow_window=60'
```

### 2. Test Different Timeframes

Want to test on 1-day candles instead of 1-hour? Edit `config.json` once:

```json
{
  "strategy": {
    "timeframe": "1d"
  }
}
```

Then all your parameter tests will use daily data.

### 3. Compare Results Programmatically

Write a script to parse and compare all saved results:

```python
import json
from pathlib import Path
import pandas as pd

results_dir = Path("results")
results = []

for file in results_dir.glob("backtest_sma_cross_*.json"):
    with file.open() as f:
        data = json.load(f)
        results.append({
            "fast_window": data["params"]["fast_window"],
            "slow_window": data["params"]["slow_window"],
            "sharpe": data["metrics"]["sharpe_ratio"],
            "return": data["metrics"]["total_return"],
            "drawdown": data["metrics"]["max_drawdown"],
        })

df = pd.DataFrame(results)
df = df.sort_values("sharpe", ascending=False)
print(df.head(10))  # Top 10 parameter combinations
```

### 4. Batch Testing with Shell Scripts

Create a shell script for systematic testing:

```bash
#!/bin/bash
# test_parameters.sh

START="2024-01-01"
END="2024-06-01"

for FAST in 5 10 15 20 25; do
  for SLOW in 30 40 50 60 80 100; do
    if [ $SLOW -gt $((FAST * 2)) ]; then
      echo "Testing fast=$FAST, slow=$SLOW"
      python run_backtest.py \
        --start $START \
        --end $END \
        --params "fast_window=$FAST,slow_window=$SLOW"
      sleep 1  # Rate limit
    fi
  done
done
```

Run it:
```bash
chmod +x test_parameters.sh
./test_parameters.sh
```

This will test 30 different parameter combinations and save all results!

---

## Command Reference

### Arguments

| Argument | Required | Description | Example |
|----------|----------|-------------|---------|
| `--start` | Yes | Start date (YYYY-MM-DD) | `2024-01-01` |
| `--end` | Yes | End date (YYYY-MM-DD) | `2024-06-01` |
| `--config` | No | Path to config file | `settings/config.json` (default) |
| `--params` | No | Parameter overrides | `'fast_window=20,slow_window=60'` |

### Parameter Format Options

| Format | Example | Use Case |
|--------|---------|----------|
| JSON | `'{"fast_window": 20, "slow_window": 60}'` | Complex types, nested objects |
| Comma-separated | `'fast_window=20,slow_window=60'` | Simple, concise |
| Space-separated | `'fast_window=20 slow_window=60'` | Shell-friendly |

### Value Type Auto-Detection

- **Integers**: `window=50` → `{"window": 50}`
- **Floats**: `threshold=0.5` → `{"threshold": 0.5}`
- **Strings**: `mode=aggressive` → `{"mode": "aggressive"}`

---

## Troubleshooting

### Error: "Invalid JSON format"

**Problem:** Your JSON string has syntax errors.

**Solution:** Check quotes and commas:
```bash
# ❌ Bad
--params '{"fast_window": 20, "slow_window": }'

# ✅ Good
--params '{"fast_window": 20, "slow_window": 60}'
```

### Error: "Invalid parameter format"

**Problem:** Key=value pair missing the `=`.

**Solution:**
```bash
# ❌ Bad
--params 'fast_window 20'

# ✅ Good
--params 'fast_window=20'
```

### Results Not Saving

**Problem:** The `results/` directory doesn't exist.

**Solution:** The script creates it automatically, but check permissions:
```bash
ls -la results/
```

---

## Next Steps

1. **Run your first parameter sweep** to find optimal windows
2. **Analyze saved results** to identify best-performing configurations
3. **Test on different time periods** to verify robustness
4. **Update config.json** with the best parameters for live trading

Happy backtesting! 🚀

