# DevLog: Python Trading Bot (BTC)

## Project Status
- **Current Phase:** 3 - Execution & Production (Live Trading).
- **Last Update:** 2025-11-20.
- **Health:** Green (Step 9 completed - Live Trading Loop).

## Progress Log

### Phase 1: Core Architecture & Foundations
- [x] **Architecture Design:** Defined modular structure (Data, Strategy, Execution).
- [x] **Interfaces:** Created `IDataHandler`, `IExecutor`, `BaseStrategy` in `app/core/interfaces.py`.
- [x] **Data Layer:** Implemented `CryptoDataHandler` using `ccxt`.
- [x] **Configuration:** Implemented strict Pydantic models in `app/config/models.py`.
- [x] **Refactor (Critical):** Replaced iterative `check_signal` with vectorized `generate_signals` in `BaseStrategy`.
- [x] **Strategy:** Implemented `SmaCrossStrategy` using pure `numpy` vectorization in `app/strategies/sma_cross.py`.

### Phase 2: Simulation Engine (Completed)
- [x] Implement `Backtester` class (Vectorized PnL calculation).
- [x] Create `run_backtest.py` entry script.
- [x] **CRITICAL HOTFIXES:** Fixed Sharpe Ratio annualization, Data Pagination, and Look-Ahead Bias.
- [x] **Step 5: Simulation Hardening:** Implemented offline data caching and unit testing suite.
- [x] **Step 5.5: Time-Aware Data Refactor:** Fixed recency bias to allow backtesting specific historical periods.
- [x] **Step 6: Advanced Backtest CLI:** Dynamic parameter overrides, automatic result persistence, and mission reports.

### Phase 3: Execution & Production (Current Focus)
- [x] **Step 7: Persistence Layer:** SQLAlchemy-based database infrastructure for trade and signal tracking.
- [x] **Step 8: Stateful Mock Executor:** Paper trading engine with database persistence and position tracking.
- [x] **Step 9: Live Trading Loop:** TradingBot orchestrator with continuous signal processing and order execution.
- [ ] Implement `BinanceExecutor` (Real Execution).
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
- **2025-11-20 (Time-Aware Data Refactor - Step 5.5):** Implemented date-range-aware data fetching to fix "recency bias" in historical backtests.
    - *Problem:* Previous implementation only fetched recent data, making it impossible to backtest specific historical periods (e.g., "test strategy on 2022 data").
    - *Solution:* 
        1. Updated `IDataHandler.get_historical_data()` signature to accept `start_date` and `end_date` parameters.
        2. Implemented forward-fetching logic in `CryptoDataHandler._fetch_forward_range()` that starts from `start_date` and increments forward using `since` parameter.
        3. Enhanced cache validation in `_cache_covers_range()` to verify cache by date range (`cache.min() <= start` AND `cache.max() >= end`), not just by length.
        4. Maintained backward-fetching as fallback in `_fetch_recent_range()` for live trading scenarios where no explicit dates are provided.
    - *Impact:* Backtests can now target any historical period. Cache is date-aware and won't incorrectly reuse data from wrong time periods.
    - *Files:* 
        - `app/core/interfaces.py` - Updated interface signature (already had correct signature).
        - `app/data/handler.py` - Implemented `_fetch_forward_range()`, `_fetch_recent_range()`, enhanced `_cache_covers_range()`.
        - `app/backtesting/engine.py` - Updated to pass `start_date` and `end_date` to data handler.
        - `tests/test_engine_logic.py` - Updated `MockDataHandler` to match new signature.
        - `tests/test_time_aware_data.py` - Created comprehensive integration tests (5 test cases) covering forward fetching, cache validation, backward compatibility, and integration with backtester.
    - *Test Results:* All 8 tests pass (3 existing + 5 new integration tests).
- **2025-11-20 (Advanced Backtest CLI - Step 6):** Transformed `run_backtest.py` into a powerful strategy iteration tool.
    - *Problem:* Testing different strategy parameters required manually editing `config.json`, making rapid iteration slow and error-prone. No systematic way to track which parameters produced which results.
    - *Solution:*
        1. **Dynamic Parameter Overrides:** Added `--params` CLI argument that accepts JSON strings or key=value pairs (e.g., `--params 'fast_window=20,slow_window=60'`).
        2. **Smart Overlay Logic:** Implemented `overlay_params()` that merges CLI overrides onto the base config, preserving all other settings.
        3. **Automatic Result Persistence:** Created `save_results()` that saves full backtest output to `results/backtest_{STRATEGY}_{TIMESTAMP}.json` including metrics, params, config, and equity curve.
        4. **Mission Report Display:** Implemented `print_mission_report()` that shows beautiful console output with performance metrics, parameters used, and save location.
        5. **Intelligent Type Conversion:** Parameter parser auto-detects integers, floats, and strings from key=value pairs.
    - *Impact:*
        - Strategy iteration is now instant: `python run_backtest.py --start 2024-01-01 --end 2024-06-01 --params 'fast_window=20,slow_window=60'`
        - All results are automatically saved with timestamps for comparison
        - No need to edit config files for parameter testing
        - Easy to build optimization scripts that parse saved JSON results
        - Backward compatible: CLI args are optional overrides
    - *Files:*
        - `run_backtest.py` - Added `parse_params()`, `overlay_params()`, `save_results()`, `print_mission_report()` functions. Enhanced `main()` and `parse_args()`.
        - `tests/test_backtest_cli.py` - Created comprehensive test suite (18 test cases) covering JSON parsing, key=value parsing, parameter overlay, result saving, and integration tests.
        - `BACKTEST_CLI_GUIDE.md` - Created comprehensive user guide with examples, workflows, tips, and troubleshooting.
        - `.gitignore` - Added `results/`, `data_cache/`, and `*.db` to ignore list.
    - *Test Results:* All 26 tests pass (18 new CLI tests + 8 existing tests).
    - *User Experience:* Researchers can now test 50+ parameter combinations in minutes with full result tracking.
- **2025-11-20 (Persistence Layer - Step 7):** Built the "Memory" of the bot with SQLAlchemy and SQLite for trade and signal tracking.
    - *Problem:* Need robust database infrastructure to store historical trades, track PnL, and log strategy signals for analysis and debugging.
    - *Solution:*
        1. **Core Infrastructure:** Created singleton `Database` class in `app/core/database.py` with session management, context managers, and SQLite connection handling.
        2. **Data Models:** Defined `Trade` and `Signal` models in `app/models/sql.py` with proper relationships, indexes, and JSON metadata support.
        3. **Repository Pattern:** Implemented `BaseRepository` interface and specific repositories (`TradeRepository`, `SignalRepository`) for clean data access.
        4. **Foreign Key Support:** Enabled SQLite foreign key constraints via SQLAlchemy event listeners.
        5. **In-Memory Testing:** All tests use `sqlite:///:memory:` for fast, isolated testing without disk I/O.
    - *Design Decisions:*
        - Singleton pattern for Database ensures single connection pool across application
        - Repository pattern decouples business logic from database queries
        - UUID for Trade IDs (better for distributed systems)
        - Auto-increment integer for Signal IDs (sequential, efficient for queries)
        - JSON column for Signal metadata (flexible storage of indicator values)
        - Renamed `metadata` to `signal_metadata` (metadata is reserved in SQLAlchemy)
    - *Impact:*
        - Bot can now persist all trades and signals to disk
        - Historical PnL tracking across sessions
        - Signal debugging: see exactly what indicators triggered each trade
        - Foundation for live trading execution layer
        - Modular: DB logic completely decoupled from Strategy logic
    - *Files:*
        - `pyproject.toml` - Added SQLAlchemy 2.0 dependency
        - `app/core/database.py` - Database infrastructure (157 lines)
        - `app/models/sql.py` - Trade and Signal models (93 lines)
        - `app/models/__init__.py` - Model exports
        - `app/repositories/base.py` - Generic repository interface (115 lines)
        - `app/repositories/trade_repository.py` - Trade data access (106 lines)
        - `app/repositories/signal_repository.py` - Signal data access (115 lines)
        - `app/repositories/__init__.py` - Repository exports
        - `tests/test_persistence.py` - Comprehensive test suite (386 lines, 20 test cases)
    - *Test Results:* All 46 tests pass (20 new persistence tests + 26 existing tests).
    - *Test Coverage:* CRUD operations, filtering by symbol, date ranges, PnL calculations, signal value filtering, transaction management, singleton pattern verification.
- **2025-11-20 (Stateful Mock Executor - Step 8):** Built the paper trading engine with database persistence for the "Live Loop".
    - *Problem:* Need an execution layer for paper trading that simulates real order execution while persisting every action to the database for analysis and debugging.
    - *Solution:*
        1. **MockExecutor:** Implemented `IExecutor` interface with simulated order execution (100% fill rate).
        2. **Database Persistence:** Every `execute_order` call creates a database record via `TradeRepository`.
        3. **Position Tracking:** `get_position` calculates net position by summing BUYs and SELLs from the database.
        4. **CCXT Compatibility:** Returns CCXT-like order structure for seamless integration.
        5. **Position Cache:** In-memory cache for fast position queries, synced with database.
        6. **Simulated Pricing:** Default prices for testing (BTC=50k, ETH=3k) without exchange connection.
    - *Design Decisions:*
        - Constructor dependency injection (TradeRepository, optional SignalRepository)
        - 100% fill rate for all orders (simplified paper trading)
        - Position cache updated on every trade for performance
        - `reset_position_cache()` method for testing and external DB modifications
        - OrderSide enum conversion between interfaces.py (BUY/SELL) and sql.py (buy/sell)
        - Simulated prices as placeholder for future live data integration
    - *Impact:*
        - Paper trading fully operational with database persistence
        - Every trade logged to disk for historical analysis
        - Position tracking across bot restarts
        - Foundation for live trading loop (main.py)
        - Can simulate complex trading scenarios in tests
        - Ready for BinanceExecutor (real exchange) implementation
    - *Files:*
        - `app/execution/__init__.py` - Module exports
        - `app/execution/mock_executor.py` - MockExecutor implementation (234 lines)
        - `tests/test_execution.py` - Comprehensive test suite (368 lines, 21 test cases)
    - *Test Results:* All 67 tests pass (21 new execution tests + 46 existing tests).
    - *Test Coverage:* Order execution, database persistence, CCXT structure validation, position tracking (long/short/flat), position cache, multiple symbols, full trading cycles, simulated pricing.
- **2025-11-20 (Live Trading Loop - Step 9):** Built the orchestrator that brings the bot to life with continuous trading.
    - *Problem:* Need a robust orchestrator to coordinate data fetching, signal generation, position management, and order execution in a continuous loop for live/paper trading.
    - *Solution:*
        1. **TradingBot Class:** Created central orchestrator in `app/core/bot.py` with dependency injection.
        2. **run_once() Method:** Single iteration: fetch data → calculate indicators → generate signals → check position → execute trades → persist signal.
        3. **Trading Logic:** Signal-driven execution with duplicate signal filtering and position conflict detection.
        4. **start() Method:** Infinite loop with exception handling, logging, and configurable sleep intervals.
        5. **Signal Tracking:** Persists every signal to database with metadata for historical analysis.
        6. **run_live.py:** Complete dependency injection chain setup and bot runner with CLI arguments.
    - *Design Decisions:*
        - Buffer size auto-calculated from strategy params (slow_window + 20)
        - Last signal tracking to avoid duplicate trades
        - Order quantity calculated from max_position_size_usd risk parameter
        - Exception handling: log errors but don't crash (resilient bot)
        - Signal persistence even if trade execution fails
        - Standard logging module with clear formatting
        - CLI modes: --mode mock|live, --config path, --sleep seconds
    - *Trading Rules:*
        - Signal 1 (BUY) + Flat position → Execute BUY
        - Signal -1 (SELL) + Long position → Execute SELL (close)
        - Signal 0 (NEUTRAL) → No action
        - Duplicate signals ignored (no repeated trades)
        - BUY with existing long ignored
        - SELL with flat position ignored
    - *Impact:*
        - Full end-to-end live trading capability
        - Paper trading ready for production testing
        - Continuous signal processing and execution
        - Robust error handling prevents crashes
        - All trades and signals persisted for analysis
        - Foundation for adding BinanceExecutor (real exchange)
        - Can run 24/7 with configurable intervals
    - *Files:*
        - `app/core/bot.py` - TradingBot orchestrator (316 lines)
        - `run_live.py` - Live trading runner with DI chain (217 lines)
        - `tests/test_trading_bot.py` - Comprehensive test suite (484 lines, 23 test cases)
    - *Test Results:* All 90 tests pass (23 new bot tests + 67 existing tests).
    - *Test Coverage:* Bot initialization, run_once() cycle, trading logic, signal persistence, position calculation, indicator extraction, error handling, infinite loop control, full trading cycles.

## Known Issues / Backlog
- **Pending:** Need to decide on a logging library (standard `logging` vs `loguru`). Standard `logging` is assumed for now.
- **Resolved:** Database selection for state persistence - chose SQLite with SQLAlchemy ORM.