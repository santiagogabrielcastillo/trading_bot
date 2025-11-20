# Project Blueprint: Scalable Python Trading Bot (BTC)

**Role:** Senior Quantitative Architect & Python Developer.
**Project Goal:** Build a modular, scalable, and easy-to-deploy trading bot for Bitcoin.
**Core Philosophy:** "Start small, scale fast." The architecture must support rapid iteration of strategies without rewriting the core engine.

## 1. Architectural Context & Principles
We are building a professional-grade algorithmic trading system, NOT a simple script.
* **Separation of Concerns:** The `Strategy` logic must never know about the `Exchange`. It only outputs signals. The `Executor` handles the API.
* **Vectorization First:** Backtesting must be instant. We strictly **FORBID** iterating over DataFrames row-by-row (`for` loops) during signal generation or backtesting calculations. We use `pandas` and `numpy` vector operations.
* **Type Safety:** We use Python type hints and `Pydantic` for strict configuration validation.
* **Interface-Driven:** All core components (`DataHandler`, `Strategy`, `Executor`) are defined by abstract base classes (Interfaces).

### ✅ Definition of Done (DoD)
A step or feature is **ONLY** considered complete when:
1.  **Code is Implemented:** The functionality works as requested.
2.  **Tests are Passed:** A corresponding unit test (using `pytest`) exists and passes.
3.  **No Magic Numbers:** All parameters are extracted to config or constants.
4.  **Reproducible:** If it involves data, it must work in "Offline Mode" without relying on a live API connection.

## 2. Current Project State
We are in **Phase 2 (Simulation Engine)**.
* **Core:** Interfaces, Models, and basic Handler are in place.
* **Strategy:** Vectorized `SmaCrossStrategy` is implemented.
* **Backtester:** Basic `engine.py` exists but contains **CRITICAL BUGS** (Math & Logic) that must be fixed immediately.

---

## 🚨 MANDATORY PROTOCOL: AUTO-LOGGING 🚨
**CRITICAL INSTRUCTION:**
After you successfully complete ANY step or task defined below, you **MUST** automatically update the file `DEVLOG.md` located in the root directory.
**Do not ask for permission.** Treat the log update as part of the code generation process.

---

## 3. Execution Roadmap

### 🛑 IMMEDIATE PRIORITY: CRITICAL HOTFIXES (Current Task) 🛑
*Before moving forward, we must fix the technical debt identified in the audit.*

**Task 1: Fix Sharpe Ratio Logic (Math Error)**
* **File:** `app/backtesting/engine.py`
* **Issue:** `periods_per_year` is hardcoded to 252 (Traditional Finance). Crypto is 24/7.
* **Fix:** Calculate annualization factor dynamically based on `self.timeframe`.
    * If timeframe is '1h', factor = $365 \times 24 = 8760$.
    * If timeframe is '1d', factor = $365$.
    * Throw error if timeframe is unknown.

**Task 2: Fix Data Pagination (Scalability Error)**
* **File:** `app/data/handler.py`
* **Issue:** `fetch_ohlcv` only gets the latest 1000 candles. Long backtests are impossible.
* **Fix:** Implement a pagination loop (while loop).
    * Fetch batch -> update `since` timestamp -> fetch next batch.
    * Continue until `limit` is reached or current time is reached.
    * Concatenate all batches into one DataFrame.

**Task 3: Fix Look-Ahead Bias (Logic Error)**
* **File:** `app/backtesting/engine.py`
* **Issue:** Data is sliced using `.loc[start:end]` *before* indicators are calculated. This causes the first N candles (the warm-up period) to be `NaN` inside the backtest window, distorting results.
* **Fix:**
    1.  Fetch data with a buffer (e.g., `start_date` - 1000 candles).
    2.  Run `strategy.calculate_indicators(df)` on the FULL dataset.
    3.  **ONLY THEN** slice the DataFrame to `df.loc[start_date:end_date]` for the PnL calculation.

---

### PHASE 2: Simulation Engine (Continued)

#### Step 5: Simulation Hardening (Tests & Offline Mode)
* **Objective:** Make the backtest robust, reproducible, and mathematically proven.
* **Sub-task 5.1: Offline Data Mode**
    * Update `CryptoDataHandler`. Add methods `save_to_csv(symbol, timeframe)` and `load_from_csv`.
    * Modify `get_historical_data`: If a local file exists and covers the requested range, load it. Else, download from API and save it.
    * **Why:** Prevents API rate limits and ensures we test against the exact same data every time.
* **Sub-task 5.2: Unit Testing Suite**
    * Install `pytest`.
    * Create `tests/test_engine_logic.py`.
    * **Test Case:** Create a manual DataFrame (e.g., 10 rows) with known prices and known signals. Calculate expected PnL manually. Run `Backtester` on it. Assert results match exactly.

#### Step 5.5: Time-Aware Data Refactor (CRITICAL)
* **Objective:** Fix the "Recency Bias" in data fetching to allow backtesting specific historical periods (e.g., 2022).
* **Tasks:**
    1.  **Update Interface:** `IDataHandler.get_historical_data` must accept `start_date` and `end_date`.
    2.  **Refactor Handler:**
        - If `start_date` is present, fetch FORWARD from that date using `since` parameter in CCXT.
        - Stop fetching when `end_date` is reached.
        - **Smart Caching:** Verify cache by DATE RANGE (`min_date <= start` and `max_date >= end`), not just by length.
    3.  **Update Engine:** Pass the calculation start date to the handler.

#### Step 6: Advanced Backtest CLI (Iterability)
* **Objective:** Allow rapid strategy iteration by overriding parameters via CLI without editing config files.
* **File:** `run_backtest.py`
* **Tasks:**
    1.  **Dynamic Arguments:** Update `argparse` to accept strategy parameters dynamically (e.g., `--param fast_window=20`).
    2.  **Config Override:** Logic to merge CLI parameters into the loaded `BotConfig` object before running the backtest.
    3.  **Result Persistence:** Instead of just printing, SAVE the results (Metrics + Equity Curve) to a folder `results/backtest_{timestamp}.json`.
    4.  **Reporting:** Print a clear comparison table in the console (Config used vs Result).

---

#### Step 7: Persistence Layer (Database)
* **Objective:** Implement a persistent storage engine to track trades, signals, and bot state (preventing amnesia on restarts).
* **Tech Stack:** SQLAlchemy (ORM) + SQLite.
* **Tasks:**
    1.  **Setup:** Add `sqlalchemy` to dependencies. Create `app/core/database.py` (Engine & Session Factory).
    2.  **Models:** Create `app/models/sql.py` defining tables:
        - `Trade` (id, symbol, side, quantity, price, timestamp, strategy_id, pnl).
        - `Signal` (id, symbol, timestamp, signal_value, raw_data_json).
    3.  **Repositories:** Create `app/repositories/` implementing the Repository Pattern (abstraction over DB operations).
        - `trade_repo.add(trade)`, `trade_repo.get_all()`.
    4.  **Testing:** Unit tests for database operations using an in-memory SQLite instance (`:memory:`).

### PHASE 3: Live Execution

#### Step 8: Stateful Mock Executor (Paper Trading) ✅ COMPLETE
* **Objective:** Implement an execution engine that simulates trades and persists them to the database (The "Live" simulation).
* **File:** `app/execution/mock_executor.py`
* **Status:** Fully implemented with database persistence, position tracking, and CCXT-compatible interface.
* **Completed Tasks:**
    1.  ✅ **Implement Interface:** Inherits from `IExecutor` with full compliance.
    2.  ✅ **Dependency Injection:** Accepts `TradeRepository` and optional `SignalRepository` in `__init__`.
    3.  ✅ **Execution Logic:**
        - `execute_order` persists every trade to database
        - Simulates 100% fill rate
        - Returns CCXT-compatible order structure
        - Includes trade_db_id in order info
    4.  ✅ **State Management:** 
        - `get_position(symbol)` calculates net position from database
        - In-memory position cache for performance
        - `reset_position_cache()` method for testing
    5.  ✅ **Test:** Created `tests/test_execution.py` with 21 comprehensive test cases (all passing).

#### Step 9: The Live Trading Loop (Orchestrator) ✅ COMPLETE
* **Objective:** Connect all components (Data, Strategy, Executor, DB) into a running loop that reacts to the market in real-time.
* **Files:** `app/core/bot.py` and `run_live.py`.
* **Status:** Fully implemented with robust orchestration, error handling, and comprehensive testing.
* **Completed Tasks:**
    1.  ✅ **Class `TradingBot`:**
        - Coordinates Data → Strategy → Execution cycle
        - `run_once()`: Fetch data → Calculate indicators → Generate signals → Check position → Execute trades → Save signal
        - `start()`: Infinite loop with exception handling, logging, and configurable sleep
        - Buffer size auto-calculated from strategy parameters
        - Last signal tracking to avoid duplicate trades
    2.  ✅ **Signal Persistence:** Every signal saved to `SignalRepository` with metadata (indicators, price, timestamp)
    3.  ✅ **Order Logic:**
        - Signal 1 (BUY) + Flat → Execute BUY
        - Signal -1 (SELL) + Long → Execute SELL
        - Signal 0 (NEUTRAL) → No action
        - Duplicate signals filtered
        - Position conflicts handled correctly
    4.  ✅ **Entrypoint (`run_live.py`):**
        - Complete dependency injection chain
        - CLI args: --config, --mode (mock/live), --sleep
        - Loads config, initializes DB, creates all components
        - Runs bot with error handling
    5.  ✅ **Test:** Created `tests/test_trading_bot.py` with 23 comprehensive test cases (all passing).


#### Step 9.5: The Real Money Bridge (Binance Executor) ✅ **DONE**
* **Objective:** Implement the actual connection to Binance via CCXT and allow switching between "Paper" and "Live" modes.
* **Requirements Met:**
    1.  ✅ **Config Update:** Added `execution_mode` field to `BotConfig` with Literal["paper", "live"] type. Defaults to "paper". Added validator with warnings when live mode is enabled. Updated `settings/config.json` with execution_mode field.
    2.  ✅ **BinanceExecutor:** Created `app/execution/binance_executor.py` (267 lines).
        - ✅ Implements `IExecutor` interface (same as MockExecutor).
        - ✅ Integrated with CCXT library for real exchange orders.
        - ✅ Supports market and limit orders via `create_market_order()` and `create_limit_order()`.
        - ✅ Comprehensive error handling:
            - `ccxt.NetworkError` → Logged and re-raised for bot to retry
            - `ccxt.InsufficientFunds` → Logged, returned None, bot continues
            - `ccxt.ExchangeError` → Logged and re-raised
            - Unexpected errors → Critical log and re-raised
        - ✅ **Database Persistence:** All successful trades saved to DB with trade_repository.create().
        - ✅ **Position Tracking:** Uses `client.fetch_balance()` to get real exchange position.
        - ✅ Multiple warning logs with ⚠️ emoji throughout execution.
    3.  ✅ **Factory Logic:** Updated `run_live.py` executor factory:
        - ✅ Reads `config.execution_mode` to determine executor type.
        - ✅ Creates BinanceExecutor for "live" mode with CCXT client.
        - ✅ Creates MockExecutor for "paper" mode.
        - ✅ Supports sandbox mode via `config.exchange.sandbox_mode`.
        - ✅ Fallback to MockExecutor if BinanceExecutor initialization fails.
        - ✅ Updated CLI documentation (removed --mode arg, now uses config).
    4.  ✅ **Test:** Created `tests/test_binance_executor.py` with 20 comprehensive test cases (all passing).
* **Safety Features:**
    - ⚠️ Multiple warnings when live mode is enabled
    - Sandbox mode support for testing with fake money
    - Database persistence failure doesn't crash trading
    - All errors logged with appropriate severity levels

---

### PHASE 4: Deployment & QA

#### Step 10: Dockerization & Hardening
* **Objective:** Containerize the application for reliable 24/7 deployment on any server.
* **Tasks:**
    1.  **Config Update:** Add `trade_quantity` (or `fixed_size`) to `BotConfig` model and `config.json` to remove the hardcoded value in `bot.py`.
    2.  **Dockerfile:** Create a lightweight image based on `python:3.11-slim`.
    3.  **Docker Compose:** Create `docker-compose.yml` defining:
        - Service `trading_bot`.
        - **Volumes:** Persist `data_cache/`, `results/`, `logs/` and `trading_state.db` so they survive restarts.
        - **Env Vars:** Inject API Keys securely.
    4.  **Documentation:** Add `DEPLOY.md` with simple instructions to boot the bot on a VPS.

#### Step 11: QA Hooks
* **Task:** Setup `pre-commit` to run `ruff` (linting) and `mypy` (typing) before every commit.