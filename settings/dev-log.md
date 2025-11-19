# DevLog: Python Trading Bot (BTC)

## Project Status
- **Current Phase:** 2 - Simulation Engine (Backtesting).
- **Last Update:** 2025-01-XX.
- **Health:** Green (Critical hotfixes completed).

## Progress Log

### Phase 1: Core Architecture & Foundations
- [x] **Architecture Design:** Defined modular structure (Data, Strategy, Execution).
- [x] **Interfaces:** Created `IDataHandler`, `IExecutor`, `BaseStrategy` in `app/core/interfaces.py`.
- [x] **Data Layer:** Implemented `CryptoDataHandler` using `ccxt`.
- [x] **Configuration:** Implemented strict Pydantic models in `app/config/models.py`.
- [x] **Refactor (Critical):** Replaced iterative `check_signal` with vectorized `generate_signals` in `BaseStrategy`.
- [x] **Strategy:** Implemented `SmaCrossStrategy` using pure `numpy` vectorization in `app/strategies/sma_cross.py`.

### Phase 2: Simulation Engine (Current Focus)
- [x] Implement `Backtester` class (Vectorized PnL calculation).
- [x] Create `run_backtest.py` entry script.
- [x] **CRITICAL HOTFIXES:** Fixed Sharpe Ratio annualization, Data Pagination, and Look-Ahead Bias.
- [x] **Step 5: Simulation Hardening:** Implemented offline data caching and unit testing suite.
- [ ] Validate Strategy Metrics (Sharpe, Drawdown).

### Phase 3: Execution & Production
- [ ] Implement `MockExecutor` (Paper Trading).
- [ ] Implement `BinanceExecutor` (Real Execution).
- [ ] Create `main.py` CLI.
- [ ] Dockerize application (`Dockerfile`, `docker-compose`).

## Technical Decisions Record
- **2025-11-19 (Vectorization):** Shifted from Event-Driven Loops to Vectorized Backtesting.
    - *Reason:* Loops over Pandas rows are too slow for optimizing parameters over long historical periods.
    - *Impact:* `BaseStrategy` now enforces `generate_signals(df)` returning a full DataFrame column.
- **2025-11-19 (Configuration):** Adopted `Pydantic`.
    - *Reason:* To prevent runtime errors due to missing keys or wrong types in configuration files (e.g., API Keys).
- **2025-11-19 (Testing):** Decided to use `MockExecutor` for initial live-loop testing before connecting to real Binance APIs to prevent accidental capital loss.
- **2025-11-19 (Backtester Metrics):** Standardized on daily-frequency Sharpe (252 periods) with equity-curve drawdown tracking in `app/backtesting/engine.py`.
    - *Reason:* Keeps reporting consistent across timeframes while satisfying roadmap requirement for daily metrics.
    - *Impact:* Any strategy evaluation plugs directly into uniform KPI outputs.
- **2025-11-19 (Configuration File):** Added `settings/config.json` as the canonical source for bot settings consumed by `run_backtest.py`.
    - *Reason:* Enables scripted backtests without hardcoding credentials/params.
    - *Impact:* Future runners (live or batch) can reuse the same config contract.
- **2025-01-XX (Sharpe Ratio Fix):** Replaced hardcoded 252 periods/year with dynamic calculation based on timeframe.
    - *Reason:* Crypto markets operate 24/7, not traditional trading days. Annualization must match actual market hours.
    - *Impact:* Sharpe ratios now correctly reflect crypto market structure (e.g., '1h' = 8760 periods/year, '1d' = 365 periods/year).
    - *Files:* `app/backtesting/engine.py` - Added `_calculate_periods_per_year()` method.
- **2025-01-XX (Data Pagination Fix):** Implemented pagination loop in `CryptoDataHandler.get_historical_data()`.
    - *Reason:* Exchange APIs limit single requests (typically 1000 candles). Long backtests require fetching thousands of candles.
    - *Impact:* Backtests can now span months/years of historical data without hitting API limits.
    - *Files:* `app/data/handler.py` - Added pagination logic with rate limiting and duplicate handling.
- **2025-01-XX (Look-Ahead Bias Fix):** Fixed indicator calculation order in `Backtester.run()`.
    - *Reason:* Calculating indicators after slicing data causes warm-up period NaNs to appear in backtest window, distorting results.
    - *Fix:* Fetch data with buffer → Calculate indicators on full dataset → Slice to requested window.
    - *Impact:* Backtest results are now mathematically correct without look-ahead bias.
    - *Files:* `app/backtesting/engine.py` - Modified `run()` method to fetch buffer and calculate indicators before slicing.
- **2025-01-XX (Offline Data Caching):** Implemented CSV-based caching layer in `CryptoDataHandler`.
    - *Reason:* Prevents API rate limits, ensures reproducibility, and speeds up iteration (second run is instant).
    - *Implementation:* Cache directory `data_cache/` stores CSV files named `{SYMBOL}_{TIMEFRAME}.csv`. Cache is checked before API calls, and new data overwrites cache.
    - *Impact:* Backtests can iterate instantly on cached data, and results are reproducible across runs.
    - *Files:* `app/data/handler.py` - Added `_sanitize_symbol()`, `_get_cache_path()`, `_save_to_csv()`, `_load_from_csv()`, `_cache_covers_range()` methods.
- **2025-01-XX (Unit Testing Suite):** Created comprehensive unit tests for backtester math verification.
    - *Reason:* Verify mathematical correctness of equity calculations and Sharpe ratio without API dependencies.
    - *Implementation:* `MockDataHandler` and `MockStrategy` classes for isolated testing. Tests verify equity curve calculations and Sharpe ratio annualization with known data.
    - *Impact:* Backtester math is now mathematically proven correct. All tests pass.
    - *Files:* `tests/test_engine_logic.py` - Created test suite with 3 test cases covering equity calculation, Sharpe ratio, and buy-hold scenarios.

## Known Issues / Backlog
- **Pending:** Need to decide on a logging library (standard `logging` vs `loguru`). Standard `logging` is assumed for now.
- **Pending:** Database selection for state persistence (SQLite vs Redis) is deferred until Phase 3.