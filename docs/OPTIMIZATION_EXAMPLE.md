# Complete Optimization Workflow Example

This document demonstrates a complete optimization workflow from start to finish, including result analysis.

## Scenario

**Objective:** Find optimal SMA Cross parameters for BTC/USDT trading on 1-hour timeframe using 2023 data.

**Goals:**
- Maximize risk-adjusted returns (Sharpe ratio)
- Minimize drawdown (< 15% preferred)
- Find robust parameters that aren't overfit

## Step 1: Run Optimization

### Command

```bash
poetry run python tools/optimize_strategy.py \
  --symbol BTC/USDT \
  --timeframe 1h \
  --start-date 2023-01-01 \
  --end-date 2023-12-31 \
  --fast 5,10,15,20,25 \
  --slow 20,30,40,50,60,80 \
  -o results/optimization_btc_2023.json
```

### Expected Output

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
  [  4/30] Fast= 5, Slow=50 → Sharpe:  0.981, Return:  10.50%
  [  5/30] Fast= 5, Slow=60 → Sharpe:  0.923, Return:   9.75%
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

✓ Results saved to: results/optimization_btc_2023.json
  File size: 2.45 KB
```

**Time Taken:** ~5 seconds (vs ~75 seconds without caching)

## Step 2: Examine Results

### Open the JSON File

```bash
cat results/optimization_btc_2023.json | jq '.results | .[:5]'
```

### Top 5 Results

```json
[
  {
    "params": {"fast_window": 10, "slow_window": 50},
    "metrics": {
      "total_return": 0.1495,
      "sharpe_ratio": 1.4235,
      "max_drawdown": -0.0815
    }
  },
  {
    "params": {"fast_window": 15, "slow_window": 50},
    "metrics": {
      "total_return": 0.1380,
      "sharpe_ratio": 1.3891,
      "max_drawdown": -0.0902
    }
  },
  {
    "params": {"fast_window": 10, "slow_window": 40},
    "metrics": {
      "total_return": 0.1521,
      "sharpe_ratio": 1.3654,
      "max_drawdown": -0.0945
    }
  },
  {
    "params": {"fast_window": 5, "slow_window": 30},
    "metrics": {
      "total_return": 0.1245,
      "sharpe_ratio": 1.1230,
      "max_drawdown": -0.1102
    }
  },
  {
    "params": {"fast_window": 15, "slow_window": 60},
    "metrics": {
      "total_return": 0.1198,
      "sharpe_ratio": 1.0987,
      "max_drawdown": -0.0865
    }
  }
]
```

## Step 3: Robustness Analysis

### Create Performance Heatmap

Using the analysis prompt (`settings/optimization_analysis_prompt.md`), analyze:

#### Performance Matrix (Sharpe Ratio)

|       | **Slow=20** | **Slow=30** | **Slow=40** | **Slow=50** | **Slow=60** | **Slow=80** |
|-------|-------------|-------------|-------------|-------------|-------------|-------------|
| **Fast=5**  | 0.852 | 1.123 | 1.054 | 0.981 | 0.923 | 0.815 |
| **Fast=10** | 0.921 | 1.045 | **1.365** | **1.424** | 1.187 | 0.958 |
| **Fast=15** | 0.895 | 0.998 | 1.289 | **1.389** | 1.099 | 0.923 |
| **Fast=20** | 0.784 | 0.912 | 1.045 | 1.156 | 0.987 | 0.845 |
| **Fast=25** | 0.723 | 0.856 | 0.934 | 1.023 | 0.921 | 0.798 |

**Observations:**
- 🎯 **High-performance cluster** around (10-15, 40-50)
- ✅ **Smooth gradient** - no isolated spikes
- ✅ **Round numbers** perform best (not overfit to specific values)
- ⚠️ Performance degrades at extremes (5,20) and (25,80)

### Neighborhood Analysis for Top Performer (10, 50)

**Immediate Neighbors:**
- (9, 45-55): Not tested (would need finer grid)
- (10, 40): Sharpe = 1.365 ✅ Strong
- (10, 60): Sharpe = 1.187 ✅ Good
- (15, 50): Sharpe = 1.389 ✅ Very Strong
- (5, 50): Sharpe = 0.981 ⚠️ Moderate

**Robustness Score: 8.5/10**

The parameter (10, 50) sits at the center of a high-performance cluster with graceful performance degradation in all directions.

## Step 4: Risk Profile Assessment

### Compare Top 3 Candidates

| Rank | Fast | Slow | Sharpe | Return | Drawdown | Risk Profile |
|------|------|------|--------|--------|----------|--------------|
| 1    | 10   | 50   | 1.424  | 14.95% | -8.15%   | **Balanced** |
| 2    | 15   | 50   | 1.389  | 13.80% | -9.02%   | **Conservative** |
| 3    | 10   | 40   | 1.365  | 15.21% | -9.45%   | **Aggressive** |

### Decision Matrix

```
         ┌─────────────────────────────────────┐
  Sharpe │                     ● (10,50)       │ High Sharpe
   1.5   │                   ● (15,50)         │ Low Risk
         │                 ● (10,40)           │
   1.4   │                                     │
         │                                     │
   1.3   │           ● (5,30)                  │
         │                                     │
   1.2   │                                     │
         │     ●                               │
   1.1   │  ● (25,80)  ● (15,60)               │
         └─────────────────────────────────────┘
          -5%   -7%   -9%   -11%  -13%  -15%
                  Max Drawdown →

  ● = Parameter combination
  Target: Top-right quadrant (high Sharpe, low drawdown)
```

**Winner:** (10, 50) - Best balance of Sharpe and drawdown

## Step 5: Production Recommendation

### Selected Parameters

```json
{
  "fast_window": 10,
  "slow_window": 50
}
```

### Justification

**1. Performance Metrics**
- Sharpe Ratio: 1.424 (excellent risk-adjusted returns)
- Annual Return: 14.95% (strong absolute performance)
- Max Drawdown: -8.15% (well-controlled risk)

**2. Robustness Evidence**
- Sits at center of high-performance cluster
- Neighbors (10, 40) and (15, 50) also perform strongly
- Smooth performance degradation (no cliff edges)
- Round numbers suggest fundamental market dynamics

**3. Market Interpretation**
- 10-period fast SMA (~10 hours) captures intraday trends
- 50-period slow SMA (~2 days) represents short-term market structure
- Ratio of 5:1 is classic technical analysis proportion

**4. Production Suitability**
- Not overfit (cluster performance vs isolated spike)
- Graceful degradation under parameter uncertainty
- Historical performance across different market regimes
- Reasonable trade frequency (not over-trading)

### Implementation

Update `settings/config.json`:

```json
{
  "strategy": {
    "name": "sma_cross",
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "params": {
      "fast_window": 10,
      "slow_window": 50
    }
  }
}
```

### Alternative Configurations

**Conservative (Lower Drawdown):**
```json
{
  "fast_window": 15,
  "slow_window": 50
}
```
- Sharpe: 1.389 (-2.5%)
- Return: 13.80% (-7.7%)
- Drawdown: -9.02% (-10.7% more drawdown)

**Aggressive (Higher Return):**
```json
{
  "fast_window": 10,
  "slow_window": 40
}
```
- Sharpe: 1.365 (-4.1%)
- Return: 15.21% (+1.7%)
- Drawdown: -9.45% (-16% more drawdown)

## Step 6: Validation (Critical!)

### Out-of-Sample Testing

```bash
# Test on 2024 data (if available)
poetry run python run_backtest.py \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --fast-window 10 \
  --slow-window 50

# Expected: Sharpe > 1.0, Drawdown < -15%
```

### Walk-Forward Analysis

```bash
# Q1 2023
poetry run python run_backtest.py --start-date 2023-01-01 --end-date 2023-03-31

# Q2 2023
poetry run python run_backtest.py --start-date 2023-04-01 --end-date 2023-06-30

# Q3 2023
poetry run python run_backtest.py --start-date 2023-07-01 --end-date 2023-09-30

# Q4 2023
poetry run python run_backtest.py --start-date 2023-10-01 --end-date 2023-12-31
```

**Success Criteria:** Sharpe > 0.8 in at least 3 of 4 quarters

## Step 7: Production Monitoring

### Key Metrics to Track

```python
# Set up alerts for:
- Sharpe ratio drops below 0.8 (rolling 30-day)
- Drawdown exceeds -12%
- Win rate drops below 40%
- Average trade return becomes negative
```

### Re-optimization Schedule

- **Quarterly:** Light review of performance
- **Semi-annually:** Full re-optimization if Sharpe < 1.0
- **Major market event:** Immediate review

## Common Pitfalls

### ❌ What NOT to Do

1. **Use the best backtest result blindly**
   - The #1 ranked result might be overfit
   - Always check robustness

2. **Ignore drawdown**
   - High Sharpe with -20% drawdown is risky
   - Balance risk-reward

3. **Skip validation**
   - Out-of-sample testing is mandatory
   - Historical performance ≠ future performance

4. **Over-optimize**
   - Don't run optimization every week
   - Leads to curve-fitting

### ✅ Best Practices

1. **Check the cluster**
   - Look for groups of similar high performers
   - Prefer center of cluster, not edge

2. **Test on different periods**
   - Bull market vs bear market
   - High volatility vs low volatility

3. **Start conservative**
   - Use parameters from conservative cluster first
   - Gradually adjust based on live performance

4. **Monitor continuously**
   - Real-time performance tracking
   - Automated alerts for degradation

## Conclusion

This example demonstrates how to:
1. ✅ Run efficient grid search optimization
2. ✅ Analyze results systematically
3. ✅ Identify robust parameters (not overfit)
4. ✅ Make production deployment decisions
5. ✅ Validate and monitor results

**Remember:** The best backtest result is NOT always the best production parameter.  
**Choose robust, cluster-centered, round-number parameters that balance risk and reward.**

---

## References

- Optimization script: `tools/optimize_strategy.py`
- Analysis guide: `settings/optimization_analysis_prompt.md`
- Full documentation: `docs/OPTIMIZATION_GUIDE.md`

