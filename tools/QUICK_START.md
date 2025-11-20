# Quick Start: Backtest Analysis Tool

## One-Minute Guide

### Run Analysis

```bash
poetry run python tools/analyze_backtest.py results/backtest_sma_cross_20251120_195448.json
```

### What You Get

1. **Console Output** - Formatted metrics table
2. **PNG Chart** - `analysis_report.png` with:
   - Equity curve
   - Drawdown analysis
   - Performance metrics overlay

### Common Commands

```bash
# Analyze latest backtest
poetry run python tools/analyze_backtest.py $(ls -t results/backtest_*.json | head -1)

# Custom output location
poetry run python tools/analyze_backtest.py results/my_backtest.json -o reports/my_analysis.png

# Show help
poetry run python tools/analyze_backtest.py --help
```

## Sample Output

### Console
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

### Chart Features

- **Equity Curve**: Portfolio value over time with profit/loss shading
- **Drawdown Chart**: Percentage decline from peak with maximum highlighted
- **High Resolution**: 300 DPI PNG suitable for presentations

## Troubleshooting

**Module not found error?**
```bash
poetry install
```

**File not found?**
- Check the path to your JSON file
- Use tab completion: `tools/analyze_backtest.py results/<TAB>`

**Need help?**
```bash
poetry run python tools/analyze_backtest.py --help
```

